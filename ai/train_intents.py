"""Local intent classifier for the assistant / NL analytics fallback.
Utterances are generated from config/intents.yaml templates with catalogue words; the test
set uses templates never seen in training. Baseline: first-keyword matching."""
from __future__ import annotations

import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import make_pipeline, make_union

from ai.common import data_hash, save_artifact
from config.loader import intents, ml


def normalize(text: str, vocab: dict) -> str:
    """Delexicalise: time phrases, numbers, categories and catalogue words become placeholders,
    so the classifier learns the request's shape rather than the product it mentions."""
    t = " " + text.lower() + " "
    for phrase in sorted(intents()["time_phrases"], key=len, reverse=True):
        t = t.replace(f" {phrase} ", " timeref ")
    t = re.sub(r"\$?\d+(?:\.\d+)?", " num ", t)
    for c in sorted(vocab["categories"], key=len, reverse=True):
        t = t.replace(f" {c} ", " catref ")
    words = [("itemref" if w.strip(".,!?") in vocab["items"] else w) for w in t.split()]
    return " ".join(words)


def catalogue_vocab() -> dict:
    from backend.folder_one_core.catalog.models import Category, Product
    items = set()
    for p in Product.objects.all():
        for w in p.name.lower().split():
            items.add(w)
            if len(w) > 3:
                items.add(w + "s")
    return {"categories": [c.name.lower() for c in Category.objects.all()], "items": items}


def _fill(template: str, rng, vocab: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(rng.choice(vocab[m.group(1)])), template)


def generate(rng, vocab, n_per_intent, split_ratio):
    train, test = [], []
    for intent, spec in intents()["intents"].items():
        tpls = list(spec["templates"])
        rng.shuffle(tpls)
        n_test = max(1, int(round(len(tpls) * split_ratio)))
        for bucket, chosen in ((test, tpls[:n_test]), (train, tpls[n_test:])):
            for i in range(n_per_intent if bucket is train else max(10, n_per_intent // 4)):
                bucket.append((_fill(chosen[i % len(chosen)], rng, vocab).lower(), intent))
    return train, test


def channel_predict(model, texts, channels) -> list[str]:
    """Pick the best intent among those offered on the request's channel (assistant/analytics)."""
    spec = intents()["intents"]
    probs = model.predict_proba(texts)
    out = []
    for row, ch in zip(probs, channels):
        allowed = [spec[c]["channel"] in (ch, "both") for c in model.classes_]
        out.append(str(model.classes_[int(np.argmax(np.where(allowed, row, -1)))]))
    return out


def keyword_baseline(text: str) -> str:
    for intent, words in intents()["baseline_keywords"].items():
        if any(w in text for w in words):
            return intent
    return "help"


def build_model():
    return make_pipeline(
        make_union(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
                   TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)),
        LogisticRegression(C=ml()["models"]["intents"]["C"], max_iter=3000))


def train() -> dict:
    from backend.folder_one_core.catalog.models import Category, Product

    cfg = ml()["models"]["intents"]
    rng = np.random.default_rng(ml()["random_seed"])
    vocab = dict(intents()["fillers"])
    nouns = sorted({p.attributes.get("type", p.name.split()[-1]).lower() for p in Product.objects.all()})
    vocab["noun"] = nouns + sorted({p.name.lower() for p in Product.objects.all()})[:30]
    vocab["category"] = [c.name.lower() for c in Category.objects.all()]
    tr, te = generate(rng, vocab, cfg["samples_per_intent"], ml()["models"]["test_size"])
    cv = catalogue_vocab()
    Xtr, ytr = zip(*[(normalize(x, cv), y) for x, y in tr])
    Xte, yte = zip(*[(normalize(x, cv), y) for x, y in te])
    model = build_model().fit(Xtr, ytr)
    pred = model.predict(Xte)
    base = [keyword_baseline(t) for t, _ in te]
    spec = intents()["intents"]
    ch = [spec[t]["channel"] if spec[t]["channel"] != "both" else "assistant" for t in yte]
    pred_ch = channel_predict(model, Xte, ch)
    metrics = {"accuracy_model_channel_aware": accuracy_score(yte, pred_ch),
               "macro_f1_model_channel_aware": f1_score(yte, pred_ch, average="macro"),
               "n_train": len(Xtr), "n_test": len(Xte), "n_intents": len(set(ytr)),
               "accuracy_model": accuracy_score(yte, pred), "macro_f1_model": f1_score(yte, pred, average="macro"),
               "accuracy_baseline_keywords": accuracy_score(yte, base),
               "macro_f1_baseline_keywords": f1_score(yte, base, average="macro")}
    final = build_model().fit(list(Xtr) + list(Xte), list(ytr) + list(yte))
    save_artifact("intents", {"model": final, "vocab": cv}, params=cfg, metrics=metrics,
                  data_hash_value=data_hash(list(tr) + list(te)),
                  notes="Test utterances come from held-out templates (not seen during training).")
    return metrics
