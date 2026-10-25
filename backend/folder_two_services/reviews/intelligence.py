"""Review intelligence: sentiment (trained model), fake-review heuristics, pros/cons summary."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

import numpy as np

from ai.common import load_artifact
from config.loader import business, categories

from .models import Review

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentiment_model():
    return load_artifact("sentiment")


def predict_sentiment(texts: list[str]) -> list[tuple[str, float]] | None:
    """[(label, confidence)] or None when the model is not trained (no made-up values)."""
    model = sentiment_model()
    if model is None or not texts:
        return None
    probs = model.predict_proba(texts)
    labels = model.classes_
    return [(str(labels[i.argmax()]), float(i.max())) for i in probs]


def _signals(review: Review, siblings: list[Review], dup_sim: dict[int, float]) -> dict[str, bool]:
    cfg = business()["reviews"]["fake"]
    window = timedelta(hours=cfg["burst_window_hours"])
    # A burst = many *unverified* reviews of the same product within the window
    burst = sum(1 for s in siblings if not s.verified_purchase
                and abs((s.created_at - review.created_at).total_seconds()) <= window.total_seconds())
    age = (review.created_at - review.user.date_joined).total_seconds() / 86400
    words = len(review.body.split())
    mismatch = bool(review.sentiment) and (
        (review.sentiment == "negative" and review.rating >= 4) or (review.sentiment == "positive" and review.rating <= 2))
    return {
        "unverified_purchase": not review.verified_purchase,
        "duplicate_text": dup_sim.get(review.id, 0.0) >= cfg["duplicate_similarity"],
        "burst": not review.verified_purchase and burst >= cfg["burst_min_reviews"],
        "rating_sentiment_mismatch": mismatch,
        "new_account": age < cfg["new_account_days"],
        "short_extreme": words < cfg["short_review_words"] and review.rating in (1, 5),
    }


def _duplicate_similarity(reviews: list[Review]) -> dict[int, float]:
    if len(reviews) < 2:
        return {}
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    m = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform([r.body.lower() for r in reviews])
    sim = cosine_similarity(m)
    np.fill_diagonal(sim, 0)
    return {r.id: float(sim[i].max()) for i, r in enumerate(reviews)}


def analyse_product(product_id: int) -> int:
    """Recompute sentiment + fake score for every review of a product. Returns #reviews."""
    cfg = business()["reviews"]["fake"]
    reviews = list(Review.objects.filter(product_id=product_id).select_related("user"))
    if not reviews:
        return 0
    preds = predict_sentiment([f"{r.title}. {r.body}" for r in reviews])
    if preds:
        for r, (label, conf) in zip(reviews, preds):
            r.sentiment, r.sentiment_score = label, round(conf, 4)
    dup = _duplicate_similarity(reviews)
    for r in reviews:
        sig = _signals(r, reviews, dup)
        r.fake_score = round(min(1.0, sum(cfg["weights"][k] for k, v in sig.items() if v)), 3)
        r.fake_reasons = [k for k, v in sig.items() if v]
        if r.status == Review.Status.VISIBLE and r.fake_score >= cfg["flag_threshold"] and r.moderated_by_id is None:
            r.status = Review.Status.FLAGGED
    Review.objects.bulk_update(reviews, ["sentiment", "sentiment_score", "fake_score", "fake_reasons", "status"])
    return len(reviews)


def analyse_all() -> int:
    ids = Review.objects.order_by().values_list("product_id", flat=True).distinct()
    return sum(analyse_product(pid) for pid in ids)


def summary(product) -> dict:
    """Aspect-level pros/cons from visible reviews. Aspect lexicon per category: categories.yaml."""
    rcfg = business()["reviews"]
    top = rcfg["summary_terms"]
    aspects = next((c["aspects"] for c in categories() if c["slug"] == product.category.slug), [])
    reviews = list(Review.objects.filter(product=product, status=Review.Status.VISIBLE))
    total = len(reviews)
    dist = {str(k): 0 for k in range(1, 6)}
    for r in reviews:
        dist[str(r.rating)] += 1
    sentiments = defaultdict(int)
    for r in reviews:
        if r.sentiment:
            sentiments[r.sentiment] += 1
    # Sentence-level sentiment for aspect mentions
    sentences, owners = [], []
    for r in reviews:
        for s in _SENT_SPLIT.split(r.body):
            low = s.lower()
            for a in aspects:
                if a in low:
                    # Split "A is good and B is bad" into clause per aspect
                    clause = next((c for c in re.split(r"\b(?:and|but)\b", low) if a in c), low)
                    sentences.append(clause)
                    owners.append((a, r))
    preds = predict_sentiment(sentences)
    stats = defaultdict(lambda: {"positive": 0, "negative": 0, "neutral": 0})
    for i, (a, r) in enumerate(owners):
        label = preds[i][0] if preds else ("positive" if r.rating >= 4 else "negative" if r.rating <= 2 else "neutral")
        stats[a][label] += 1
    def share(a, label):
        s = stats[a]
        n = sum(s.values())
        return s[label] / n if n else 0
    mentioned = [a for a in stats if sum(stats[a].values()) >= 2]
    pros = sorted([a for a in mentioned if share(a, "positive") >= rcfg["pros_min_positive_share"]], key=lambda a: -stats[a]["positive"])[:top]
    cons = sorted([a for a in mentioned if share(a, "negative") >= rcfg["cons_min_negative_share"]], key=lambda a: -stats[a]["negative"])[:top]
    return {
        "review_count": total,
        "average_rating": round(sum(r.rating for r in reviews) / total, 2) if total else None,
        "rating_distribution": dist,
        "sentiment": dict(sentiments),
        "sentiment_source": "model" if preds is not None or sentiment_model() else "rating (model not trained)",
        "pros": [{"aspect": a, "mentions": sum(stats[a].values()), "positive_share": round(share(a, "positive"), 2)} for a in pros],
        "cons": [{"aspect": a, "mentions": sum(stats[a].values()), "negative_share": round(share(a, "negative"), 2)} for a in cons],
        "flagged": Review.objects.filter(product=product, status=Review.Status.FLAGGED).count(),
    }
