"""RFM + K-Means segmentation (recency, frequency, monetary, plus tenure and average order value).
Clusters are named by explicit rules on their centroids (config/ml.yaml segmentation.naming).
Baseline: simple quantile rules on the same features."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from ai.common import data_hash, save_artifact
from ai.datasets import truth
from config.loader import business, ml


def name_clusters(centers: np.ndarray, naming: list[dict]) -> dict[int, str]:
    from backend.folder_two_services.segmentation.service import RFM_COLUMNS

    remaining = list(range(len(centers)))
    out = {}
    for rule in naming:
        if not remaining:
            break
        if rule["pick"] == "rest":
            for c in remaining:
                out[c] = rule["label"]
            remaining = []
            break
        col = RFM_COLUMNS.index(rule["feature"])
        pick = (min if rule["pick"] == "min" else max)(remaining, key=lambda c: centers[c, col])
        out[pick] = rule["label"]
        remaining.remove(pick)
    return out


def rule_baseline(df) -> np.ndarray:
    q = ml()["models"]["segmentation"]["baseline_quantiles"]
    """Quantile rules: newest tenure -> new, stale recency -> at_risk, top order value -> big_spenders, else loyal."""
    t_new = df["tenure_days"].quantile(q["new_tenure"])
    r_risk = df["recency_days"].quantile(q["at_risk_recency"])
    m_big = df["avg_order_value"].quantile(q["big_spender_aov"])
    return np.select([df["tenure_days"] <= t_new, df["recency_days"] >= r_risk, df["avg_order_value"] >= m_big],
                     [2, 3, 1], 0)


def train() -> dict:
    from backend.folder_one_core.accounts.models import User
    from backend.folder_two_services.segmentation.service import rfm_frame, transform

    cfg = ml()["models"]["segmentation"]
    labels = business()["segmentation"]["labels"]
    k = business()["segmentation"]["n_clusters"]
    df = rfm_frame()
    scaler = StandardScaler().fit(transform(df))
    z = scaler.transform(transform(df))
    km = KMeans(n_clusters=k, n_init=cfg["n_init"], random_state=ml()["random_seed"]).fit(z)
    cluster_labels = name_clusters(km.cluster_centers_, cfg["naming"])
    rng = np.random.default_rng(ml()["random_seed"])
    sample = rng.choice(len(z), size=min(len(z), 3000), replace=False)
    base = rule_baseline(df)
    metrics = {
        "n_customers": int(len(df)), "k": k,
        "silhouette_kmeans": float(silhouette_score(z[sample], km.labels_[sample])),
        "silhouette_baseline_rules": float(silhouette_score(z[sample], base[sample])) if len(set(base)) > 1 else None,
        "cluster_sizes": {cluster_labels[c]: int((km.labels_ == c).sum()) for c in range(k)},
        "centroids_z": {cluster_labels[c]: [round(v, 2) for v in km.cluster_centers_[c]] for c in range(k)},
    }
    gt = truth("customers")
    if gt is not None:
        emails = dict(User.objects.filter(id__in=df["user_id"]).values_list("id", "email"))
        seg = gt.set_index("email")["segment"]
        true = df["user_id"].map(emails).map(seg)
        mask = true.notna().to_numpy()
        metrics["ari_vs_hidden_segments_kmeans"] = float(adjusted_rand_score(true[mask], km.labels_[mask]))
        metrics["ari_vs_hidden_segments_baseline_rules"] = float(adjusted_rand_score(true[mask], base[mask]))
        named = np.array([cluster_labels[c] for c in km.labels_])
        metrics["hidden_segment_mix_per_cluster"] = {
            lab: true[mask][named[mask] == lab].value_counts(normalize=True).round(2).to_dict()
            for lab in sorted(set(named))}
    bundle = {"scaler": scaler, "kmeans": km, "cluster_labels": cluster_labels}
    save_artifact("segmentation", bundle, params={**cfg, "k": k, "labels": labels, "features": "log1p(recency, frequency, monetary, tenure, avg order value)"},
                  metrics=metrics, data_hash_value=data_hash(df), notes=(
                      "Hidden generator customers include a small 'fraudster' group that has no "
                      "matching business label, so ARI is informative only."))
    return metrics
