"""Review sentiment: TF-IDF + logistic regression; labels derived from star ratings
(4-5 positive, 3 neutral, 1-2 negative). Baseline: majority class."""
from __future__ import annotations

from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

from ai.common import data_hash, save_artifact
from ai.datasets import reviews_frame
from config.loader import ml


def train() -> dict:
    cfg = ml()["models"]["sentiment"]
    df = reviews_frame()
    Xtr, Xte, ytr, yte = train_test_split(df["text"], df["label"], test_size=ml()["models"]["test_size"],
                                          random_state=ml()["random_seed"], stratify=df["label"])
    def build():
        return make_pipeline(TfidfVectorizer(ngram_range=(1, cfg["ngram_max"]), min_df=cfg["min_df"], sublinear_tf=True),
                             LogisticRegression(C=cfg["C"], max_iter=2000, class_weight="balanced"))
    model = build().fit(Xtr, ytr)
    pred = model.predict(Xte)
    base = DummyClassifier(strategy="most_frequent").fit(Xtr, ytr).predict(Xte)
    metrics = {
        "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
        "label_distribution": df["label"].value_counts().to_dict(),
        "accuracy_model": accuracy_score(yte, pred), "macro_f1_model": f1_score(yte, pred, average="macro"),
        "accuracy_baseline_majority": accuracy_score(yte, base),
        "macro_f1_baseline_majority": f1_score(yte, base, average="macro"),
        "per_class": {k: {m: round(v, 3) for m, v in d.items()} for k, d in
                      classification_report(yte, pred, output_dict=True).items() if k in ("positive", "neutral", "negative")},
    }
    final = build().fit(df["text"], df["label"])
    save_artifact("sentiment", final, params=cfg, metrics=metrics, data_hash_value=data_hash(df[["id", "rating"]]),
                  notes="Labels are derived from ratings; ~6% of synthetic texts carry deliberately flipped sentiment.")
    return metrics
