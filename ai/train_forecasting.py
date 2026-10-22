"""Demand forecasting per product.

Candidates: moving average (baseline), seasonal naive (weekly), Holt-Winters (statsmodels
ExponentialSmoothing, additive weekly seasonality), and a ridge regression on calendar features
(day of week, month, festival flag, trend).

Honest model selection: each product's model is chosen by mean WAPE over several rolling-origin
selection windows (before the evaluation window); the chosen model is then scored on the final
evaluation window, which played no part in the choice.
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from ai.common import data_hash, save_artifact
from ai.datasets import daily_demand
from ai.generators import festival_flag
from config.loader import business, ml

MODELS = ["moving_average", "seasonal_naive", "holt_winters", "ridge_calendar"]


def _calendar(dates, start_ord: int, festivals) -> np.ndarray:
    rows = []
    for d in dates:
        dow = np.eye(7)[d.weekday()]
        m = 2 * np.pi * (d.month - 1) / 12
        rows.append([*dow, np.sin(m), np.cos(m), festival_flag(d, festivals), (d.toordinal() - start_ord) / 365])
    return np.array(rows)


def forecast(model: str, y: np.ndarray, dates: list[date], h: int, cfg: dict) -> np.ndarray:
    future = [dates[-1] + timedelta(days=i + 1) for i in range(h)]
    if model == "moving_average":
        return np.full(h, y[-cfg["moving_average_window"]:].mean())
    if model == "seasonal_naive":
        p = cfg["seasonal_period"]
        last = y[-p:]
        return np.array([last[i % p] for i in range(h)])
    if model == "holt_winters":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add",
                                       seasonal_periods=cfg["seasonal_period"]).fit(optimized=True)
        return np.clip(fit.forecast(h), 0, None)
    if model == "ridge_calendar":
        festivals = ml()["synthetic"]["festivals"]
        start = dates[0].toordinal()
        reg = Ridge(alpha=ml()["models"]["forecasting"]["ridge_alpha"]).fit(_calendar(dates, start, festivals), y)
        return np.clip(reg.predict(_calendar(future, start, festivals)), 0, None)
    raise ValueError(model)


def wape(y, f) -> float:
    s = np.abs(y).sum()
    return float(np.abs(y - f).sum() / s) if s > 0 else float("nan")


def mape(y, f) -> float:
    m = y > 0
    return float(np.mean(np.abs(y[m] - f[m]) / y[m])) if m.any() else float("nan")


def train() -> dict:
    cfg = business()["forecasting"]
    table, products = daily_demand()
    dates = list(table.index)
    B = cfg["backtest_days"]
    H = cfg["max_horizon_days"]
    n = len(dates)
    W = cfg["selection_windows"]
    sel_end, eval_end = n - B, n  # selection windows end where the evaluation window [n-B, n) starts
    out_products, agg = {}, {m: [0.0, 0.0] for m in MODELS + ["best_per_product"]}
    mape_acc = {m: [] for m in MODELS + ["best_per_product"]}
    chosen_count = {m: 0 for m in MODELS}
    for sku in table.columns:
        y = table[sku].to_numpy()
        nz = np.nonzero(y)[0]
        first = int(nz[0]) if len(nz) else n
        hist_len = sel_end - W * B - first
        candidates = MODELS if hist_len >= cfg["min_history_days"] else ["moving_average"]
        # 1) choose by mean WAPE over W rolling-origin windows before the evaluation window
        sel_scores = {}
        for m in candidates:
            scores = []
            for w in range(W, 0, -1):
                cut = sel_end - w * B
                if cut - first < cfg["seasonal_period"] * 2:
                    continue
                f = forecast(m, y[first:cut], dates[first:cut], B, cfg)
                scores.append(wape(y[cut:cut + B], f))
            sel_scores[m] = float(np.nanmean(scores)) if scores and not np.all(np.isnan(scores)) else float("nan")
        best = min(sel_scores, key=lambda m: (np.nan_to_num(sel_scores[m], nan=1e9), MODELS.index(m)))
        chosen_count[best] += 1
        # 2) score every model + the chosen one on the untouched evaluation window
        ev_true = y[sel_end:eval_end]
        ev = {}
        for m in MODELS:
            mm = m if m in candidates else "moving_average"
            ev[m] = forecast(mm, y[first:sel_end], dates[first:sel_end], B, cfg)
            agg[m][0] += np.abs(ev_true - ev[m]).sum()
            agg[m][1] += ev_true.sum()
            mape_acc[m].append(mape(ev_true, ev[m]))
        agg["best_per_product"][0] += np.abs(ev_true - ev[best]).sum()
        agg["best_per_product"][1] += ev_true.sum()
        mape_acc["best_per_product"].append(mape(ev_true, ev[best]))
        resid_sd = float(np.std(ev_true - ev[best]))
        # 3) refit the chosen model on all history and forecast the max horizon
        fc = forecast(best, y[first:], dates[first:], H, cfg)
        out_products[sku] = {
            "model": best, "forecast": [float(v) for v in fc], "residual_sd": resid_sd,
            "backtest": {"selection_wape": {k: round(v, 4) for k, v in sel_scores.items()},
                         "evaluation_wape": round(wape(ev_true, ev[best]), 4),
                         "evaluation_wape_moving_average": round(wape(ev_true, ev["moving_average"]), 4)},
            "history_tail": [float(v) for v in y[-cfg["history_tail_days"]:]],
            "history_tail_start": dates[-cfg["history_tail_days"]].isoformat(),
        }
    metrics = {f"wape_{m}": (agg[m][0] / agg[m][1] if agg[m][1] else None) for m in agg}
    metrics.update({f"mape_{m}": float(np.nanmean(v)) for m, v in mape_acc.items()})
    metrics["chosen_models"] = chosen_count
    metrics["n_products"] = len(out_products)
    metrics["evaluation_window"] = f"{dates[sel_end]} .. {dates[-1]}"
    artifact = {"products": out_products, "forecast_start": (dates[-1] + timedelta(days=1)).isoformat(),
                "trained_at": pd.Timestamp.utcnow().isoformat(timespec="seconds")}
    save_artifact("forecasting", artifact, params={**cfg, **ml()["models"]["forecasting"], "candidates": MODELS},
                  metrics=metrics, data_hash_value=data_hash(table.reset_index(drop=True)),
                  notes="MAPE is computed over days with non-zero demand only; WAPE is the headline metric.")
    return metrics
