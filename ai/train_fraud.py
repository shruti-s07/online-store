"""Fraud model on order features, label = confirmed fraud / refused delivery.
Time-based split (train on older orders, test on the newest). Candidate models (logistic
regression, gradient boosting) are compared on a time-ordered validation slice of the training
period; the winner is reported on the test set. Baseline: config-weighted rules."""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, roc_auc_score

from ai.common import data_hash, save_artifact
from ai.datasets import orders_frame
from ai.features import FRAUD_FEATURES, fraud_row
from backend.shared.payment_methods import is_cod
from config.loader import business, ml


def _features(df):
    return np.array([fraud_row(cod=is_cod(r.payment_method), account_age_days=r.account_age_days,
                               address_match=r.address_match, past_refused=r.past_refused, total=r.total,
                               hour=r.hour, item_count=r.item_count, prior_orders=r.prior_orders)
                     for r in df.itertuples()])


def make_model(name: str, cfg: dict):
    if name == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(C=cfg["logistic_C"], max_iter=2000))
    if name == "gradient_boosting":
        return GradientBoostingClassifier(n_estimators=cfg["n_estimators"], max_depth=cfg["max_depth"],
                                          learning_rate=cfg["learning_rate"], random_state=ml()["random_seed"])
    raise ValueError(name)


def importances(model) -> np.ndarray:
    if hasattr(model, "feature_importances_"):
        return model.feature_importances_
    lr = model[-1]
    imp = np.abs(lr.coef_[0])
    return imp / imp.sum()


def precision_at_budget(y, score, budget):
    k = max(1, int(round(len(y) * budget)))
    top = np.argsort(-score, kind="stable")[:k]
    return float(y[top].mean()), float(y[top].sum() / max(1, y.sum()))


def train() -> dict:
    from backend.folder_two_services.risk.scoring import rule_score

    cfg = ml()["models"]["fraud"]
    risk = business()["risk"]
    df = orders_frame()
    X, y = _features(df), df["label"].to_numpy()
    cut = int(len(df) * (1 - ml()["models"]["test_size"]))
    Xtr, Xte, ytr, yte = X[:cut], X[cut:], y[:cut], y[cut:]
    vcut = int(len(Xtr) * (1 - cfg["validation_share"]))
    validation = {}
    for name in cfg["candidates"]:
        m = make_model(name, cfg).fit(Xtr[:vcut], ytr[:vcut])
        validation[name] = float(average_precision_score(ytr[vcut:], m.predict_proba(Xtr[vcut:])[:, 1]))
    chosen = max(validation, key=validation.get)
    model = make_model(chosen, cfg).fit(Xtr, ytr)
    p = model.predict_proba(Xte)[:, 1]
    base = np.array([rule_score(cod=is_cod(r.payment_method), account_age_days=r.account_age_days,
                                address_match=r.address_match, past_refused=r.past_refused, total=r.total)[0]
                     for r in df.iloc[cut:].itertuples()], dtype=float)
    budget = cfg["review_budget"]
    m_prec, m_rec = precision_at_budget(yte, p, budget)
    b_prec, b_rec = precision_at_budget(yte, base + np.random.default_rng(0).random(len(base)) * 1e-3, budget)
    # Map probability -> 0..100 so that the review budget's share of orders lands at/above HIGH.
    ptr = model.predict_proba(Xtr)[:, 1]
    q = float(np.quantile(ptr, 1 - budget))
    prob_at_100 = q * 100 / risk["high_threshold"]
    test_scores = np.minimum(100, 100 * p / prob_at_100)
    metrics = {
        "chosen_model": chosen, "validation_avg_precision": validation,
        "fraud_rate_train": float(ytr.mean()), "fraud_rate_test": float(yte.mean()),
        "n_train": int(len(ytr)), "n_test": int(len(yte)),
        "roc_auc_model": float(roc_auc_score(yte, p)), "roc_auc_baseline_rules": float(roc_auc_score(yte, base)),
        "avg_precision_model": float(average_precision_score(yte, p)),
        "avg_precision_baseline_rules": float(average_precision_score(yte, base)),
        "review_budget": budget,
        "precision_at_budget_model": m_prec, "recall_at_budget_model": m_rec,
        "precision_at_budget_baseline_rules": b_prec, "recall_at_budget_baseline_rules": b_rec,
        "share_test_high": float((test_scores >= risk["high_threshold"]).mean()),
        "share_test_medium": float(((test_scores >= risk["medium_threshold"]) & (test_scores < risk["high_threshold"])).mean()),
    }
    model.fit(X, y)  # refit on all data for serving
    corr = [np.corrcoef(X[:, i], y)[0, 1] if X[:, i].std() > 0 else 0 for i in range(X.shape[1])]
    bundle = {"name": chosen, "model": model, "feature_means": X.mean(axis=0).tolist(),
              "importances": importances(model).tolist(), "risk_direction": np.sign(corr).tolist(),
              "prob_at_100": prob_at_100, "features": FRAUD_FEATURES}
    save_artifact("fraud", bundle, params={**cfg, "features": FRAUD_FEATURES, "thresholds": {
        "medium": risk["medium_threshold"], "high": risk["high_threshold"]}}, metrics=metrics,
        data_hash_value=data_hash(df[["id", "label", "total"]]))
    return metrics
