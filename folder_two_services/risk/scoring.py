"""Real implementation of the checkout hook `score_order(order)`.

Uses the trained fraud model (ai/train_fraud.py) when its artifact exists. Without it, a
transparent rule-based score with weights from config/business.yaml (risk.fallback_weights)
is used; the same rule score is the baseline the model is compared with in REPORT.md.
"""
from __future__ import annotations

from ai.common import load_artifact
from ai.features import FRAUD_FEATURES, fraud_row
from backend.shared.contracts import OrderSnapshot, RiskResult
from config.loader import business

REASON_TEXT = {
    "cod": "cash on delivery",
    "log_account_age_days": "new account",
    "address_mismatch": "shipping address differs from billing address",
    "past_refused": "previous refused deliveries",
    "total_per_10k": "high order value",
    "night_order": "placed at night",
    "item_count": "many items",
    "log_prior_orders": "little order history",
}


def level_for(score: int) -> str:
    cfg = business()["risk"]
    if score >= cfg["high_threshold"]:
        return "HIGH"
    if score >= cfg["medium_threshold"]:
        return "MEDIUM"
    return "LOW"


def rule_score(*, cod: bool, account_age_days: float, address_match: bool, past_refused: int, total: float) -> tuple[int, list[str]]:
    cfg = business()["risk"]
    w = cfg["fallback_weights"]
    score, reasons = 0, []
    if cod:
        score += w["cod"]; reasons.append(REASON_TEXT["cod"])
    if account_age_days < cfg["new_account_days"]:
        score += w["new_account"]; reasons.append(REASON_TEXT["log_account_age_days"])
    if not address_match:
        score += w["address_mismatch"]; reasons.append(REASON_TEXT["address_mismatch"])
    if past_refused:
        score += w["per_refused_delivery"] * past_refused; reasons.append(REASON_TEXT["past_refused"])
    if total > cfg["high_value_amount"]:
        score += w["high_value"]; reasons.append(REASON_TEXT["total_per_10k"])
    return min(100, score), reasons


def score_features(row: list[float], model_bundle) -> tuple[int, list[str]]:
    model = model_bundle["model"]
    prob = float(model.predict_proba([row])[0, 1])
    # Calibrated probability -> 0..100 via the training-time mapping (rank-preserving)
    score = int(round(100 * min(1.0, prob / model_bundle["prob_at_100"])))
    # Explain with the features whose value pushes risk up the most (vs. training means)
    contrib = [(abs(v - m) * imp * (1 if (v - m) * s > 0 else 0), name)
               for v, m, imp, s, name in zip(row, model_bundle["feature_means"], model_bundle["importances"],
                                             model_bundle["risk_direction"], FRAUD_FEATURES)]
    reasons = [REASON_TEXT[n] for c, n in sorted(contrib, reverse=True)[:3] if c > 0]
    return min(100, score), reasons


def score_order(order: OrderSnapshot) -> RiskResult:
    row = fraud_row(cod=not order.prepaid, account_age_days=order.account_age_days, address_match=order.address_match,
                    past_refused=order.past_refused_deliveries, total=float(order.total), hour=order.hour_of_day,
                    item_count=order.item_count, prior_orders=order.prior_orders)
    bundle = load_artifact("fraud")
    if bundle is not None:
        score, reasons = score_features(row, bundle)
        model = bundle["name"]
    else:
        score, reasons = rule_score(cod=not order.prepaid, account_age_days=order.account_age_days,
                                    address_match=order.address_match, past_refused=order.past_refused_deliveries,
                                    total=float(order.total))
        model = "rules (fraud model not trained)"
    return RiskResult(score=score, level=level_for(score), reasons=tuple(reasons) or ("no risk signals",), model=model)
