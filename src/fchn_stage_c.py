"""Small, deterministic building blocks for the Stage C FCHN outer-fold runner."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss


EPS = 1e-12
_COMMON_EDGE_CACHE: dict[str, pd.DataFrame] = {}


def _as_float_matrix(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("expected a two-dimensional numeric matrix")
    return arr


def build_covariates(rows: Any, *, include_mean_fd: bool) -> tuple[np.ndarray, list[int]]:
    """Return [age, age², sex, (mean FD), log(scan length)] and continuous indices."""
    frame = pd.DataFrame(rows)
    age = pd.to_numeric(frame["age"], errors="coerce").to_numpy(dtype=np.float64)
    sex = pd.to_numeric(frame["sex"], errors="coerce").to_numpy(dtype=np.float64)
    scan = pd.to_numeric(frame["scan_length"], errors="coerce").to_numpy(dtype=np.float64)
    values = [age, age * age, sex]
    continuous = [0, 1]
    if include_mean_fd:
        values.append(pd.to_numeric(frame["mean_fd"], errors="coerce").to_numpy(dtype=np.float64))
        continuous.append(len(values) - 1)
    values.append(np.where(scan > 0, np.log(scan), np.nan))
    continuous.append(len(values) - 1)
    return np.column_stack(values), continuous


@dataclass
class RidgeResidualizer:
    cov_mean: np.ndarray
    cov_scale: np.ndarray
    beta: np.ndarray
    feature_mean: np.ndarray

    def _design(self, covariates: np.ndarray) -> np.ndarray:
        cov = _as_float_matrix(covariates)
        scaled = (cov - self.cov_mean) / self.cov_scale
        return np.column_stack([np.ones(scaled.shape[0]), scaled])

    def transform(self, x: np.ndarray, covariates: np.ndarray) -> np.ndarray:
        arr = _as_float_matrix(x)
        return arr - self._design(covariates) @ self.beta + self.feature_mean


def fit_ridge_residualizer(
    x_train: np.ndarray,
    covariates: np.ndarray,
    continuous_indices: list[int],
    *,
    alpha: float,
) -> tuple[RidgeResidualizer, np.ndarray]:
    x = _as_float_matrix(x_train)
    cov = _as_float_matrix(covariates)
    if x.shape[0] != cov.shape[0]:
        raise ValueError("feature/covariate row count mismatch")
    mean = np.zeros(cov.shape[1], dtype=np.float64)
    scale = np.ones(cov.shape[1], dtype=np.float64)
    for index in continuous_indices:
        mean[index] = float(np.mean(cov[:, index]))
        scale[index] = float(np.std(cov[:, index], ddof=0)) or 1.0
    scaled = (cov - mean) / scale
    design = np.column_stack([np.ones(len(cov)), scaled])
    penalty = np.eye(design.shape[1], dtype=np.float64) * float(alpha)
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ x)
    feature_mean = x.mean(axis=0)
    state = RidgeResidualizer(mean, scale, beta, feature_mean)
    return state, state.transform(x, cov)


def high_order_fc(x_fc: np.ndarray, *, n_roi: int) -> np.ndarray:
    """Construct HOFC by row-centred, row-normalised profile correlations."""
    x = _as_float_matrix(x_fc)
    expected = n_roi * (n_roi - 1) // 2
    if x.shape[1] != expected:
        raise ValueError(f"HOFC input has {x.shape[1]} edges; expected {expected}")
    upper = np.triu_indices(n_roi, k=1)
    matrices = np.broadcast_to(np.eye(n_roi, dtype=np.float64), (len(x), n_roi, n_roi)).copy()
    matrices[:, upper[0], upper[1]] = x
    matrices[:, upper[1], upper[0]] = x
    centred = matrices - matrices.mean(axis=2, keepdims=True)
    normalised = centred / np.maximum(np.linalg.norm(centred, axis=2, keepdims=True), EPS)
    profiles = np.einsum("nij,nkj->nik", normalised, normalised, optimize=True)
    return np.nan_to_num(profiles[:, upper[0], upper[1]])


def select_c_from_oof(
    y_true: np.ndarray, predictions: dict[float, np.ndarray]
) -> tuple[float, dict[float, float]]:
    """Select C by pooled OOF log-loss; exact ties use the smaller C."""
    y = np.asarray(y_true, dtype=np.int64)
    losses = {
        float(c): float(log_loss(y, np.clip(np.asarray(prob, dtype=np.float64), EPS, 1.0 - EPS)))
        for c, prob in predictions.items()
    }
    selected = min(losses, key=lambda c: (losses[c], c))
    return float(selected), losses


def assemble_meta_features(
    fc_logit: Any, hofc_logit: Any, normative_logit: Any, normative_summaries: Any
) -> np.ndarray:
    """Build the frozen 13-column late-fusion input."""
    fc = np.asarray(fc_logit, dtype=np.float64).reshape(-1)
    hofc = np.asarray(hofc_logit, dtype=np.float64).reshape(-1)
    normative = np.asarray(normative_logit, dtype=np.float64).reshape(-1)
    summaries = _as_float_matrix(normative_summaries)
    if not (len(fc) == len(hofc) == len(normative) == len(summaries)):
        raise ValueError("meta feature row count mismatch")
    if summaries.shape[1] != 10:
        raise ValueError("normative summaries must have exactly 10 columns")
    return np.column_stack([fc, hofc, normative, summaries])


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = _as_float_matrix(x)
    mean = arr.mean(axis=0)
    scale = arr.std(axis=0, ddof=0)
    scale[scale < 1e-12] = 1.0
    return (arr - mean) / scale, mean, scale


def _standardize_apply(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return (np.asarray(x, dtype=np.float64) - mean) / scale


@dataclass
class HealthAnchor:
    prototypes: np.ndarray
    variances: np.ndarray
    n_prototypes: int
    variance_floor: float

    def transform(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        values = _as_float_matrix(x)
        diff = values[:, None, :] - self.prototypes[None, :, :]
        distances = np.sqrt(np.mean((diff * diff) / self.variances[None, :, :], axis=2))
        nearest = np.argmin(distances, axis=1)
        residual = diff[np.arange(len(values)), nearest] / np.sqrt(
            self.variances[nearest]
        )
        ordered = np.sort(distances, axis=1)
        top_k = max(1, math.ceil(0.05 * residual.shape[1]))
        absolute = np.abs(residual)
        summaries = np.column_stack([
            ordered[:, 0],
            distances.mean(axis=1),
            distances.std(axis=1),
            (ordered[:, 1] if self.n_prototypes > 1 else ordered[:, 0]) - ordered[:, 0],
            1.0 / (1.0 + ordered[:, 0]),
            np.sqrt(np.mean(residual * residual, axis=1)),
            absolute.mean(axis=1),
            absolute.std(axis=1),
            np.partition(absolute, -top_k, axis=1)[:, -top_k:].mean(axis=1),
            (residual > 0).mean(axis=1),
        ])
        return summaries, residual, nearest


def fit_health_anchor(
    health_reference: np.ndarray,
    *,
    max_prototypes: int,
    minimum_health: int,
    shrinkage: float,
    variance_floor: float,
    seed: int,
    k_rule_divisor: int = 10,
    kmeans_n_init: int = 10,
) -> HealthAnchor:
    # KMeans may center its input in-place on some Windows backends; isolate the
    # fold-local health reference so a later tuning task cannot observe mutation.
    values = _as_float_matrix(health_reference).copy()
    if len(values) < int(minimum_health):
        raise ValueError("health reference has fewer than the required minimum")
    if not np.isfinite(values).all():
        raise ValueError(
            f"health reference contains {int((~np.isfinite(values)).sum())} nonfinite values"
        )
    n_prototypes = min(int(max_prototypes), max(1, len(values) // int(k_rule_divisor)))
    model = KMeans(
        n_clusters=n_prototypes, n_init=int(kmeans_n_init), random_state=int(seed)
    )
    labels = model.fit_predict(values)
    prototypes = np.asarray(model.cluster_centers_, dtype=np.float64)
    global_var = np.maximum(np.var(values, axis=0, ddof=0), variance_floor)
    variances = np.empty_like(prototypes)
    for index in range(n_prototypes):
        members = values[labels == index]
        local = global_var if len(members) < 3 else np.var(members, axis=0, ddof=0)
        variances[index] = np.maximum(
            (1.0 - float(shrinkage)) * local + float(shrinkage) * global_var,
            variance_floor,
        )
    return HealthAnchor(prototypes, variances, n_prototypes, float(variance_floor))


def canonicalize_sex(values: Any, dataset_id: str) -> np.ndarray:
    raw = pd.to_numeric(pd.Series(values), errors="coerce")
    if dataset_id == "adhd":
        mapped = raw.map({0.0: 1.0, 1.0: 0.0})
    else:
        mapped = raw.map({1.0: 0.0, 2.0: 1.0})
    return mapped.to_numpy(dtype=np.float64)


def build_health_crossfit_folds(subjects: Any, *, n_splits: int) -> np.ndarray:
    """Assign deterministic, site-aware round-robin folds for health references."""
    frame = pd.DataFrame(subjects)
    if "site_id" not in frame or "sample_key" not in frame:
        raise ValueError("health cross-fit requires site_id and sample_key")
    n = int(n_splits)
    if n < 2:
        raise ValueError("health cross-fit requires at least two folds")
    folds = np.full(len(frame), -1, dtype=np.int64)
    ordered = frame.assign(
        _row=np.arange(len(frame), dtype=np.int64),
        _site=frame["site_id"].astype(str),
        _key=frame["sample_key"].astype(str),
    ).sort_values(["_site", "_key", "_row"], kind="mergesort")
    for _, group in ordered.groupby("_site", sort=True):
        rows = group["_row"].to_numpy(dtype=np.int64)
        folds[rows] = np.arange(len(rows), dtype=np.int64) % n
    if (folds < 0).any():
        raise ValueError("health cross-fit produced unassigned subjects")
    return folds


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cell_fc(project_root: Path, dataset: str, atlas: str) -> dict[str, Any]:
    """Load one cell's source FC and stable edge mapping; never combines cells."""
    cell = project_root / "outputs" / "cells" / dataset / atlas
    source = json.loads((cell / "fc_source.json").read_text(encoding="utf-8"))
    archive = np.load(source["path"], allow_pickle=False)
    if "X" not in archive or "subject_ids" not in archive:
        raise ValueError(f"invalid FC source keys: {dataset}/{atlas}")
    return {
        "x": np.asarray(archive["X"], dtype=np.float64),
        "subject_ids": archive["subject_ids"].astype(str),
        "roi_indices": np.asarray(archive["roi_indices"], dtype=np.int64),
        "edge_manifest": pd.read_csv(cell / "edge_manifest.csv", keep_default_na=False),
        "subjects": pd.read_csv(
            cell / "subjects.csv",
            keep_default_na=False,
            dtype={"sample_key": str, "subject_id": str},
        ),
        "qc": pd.read_csv(
            cell / "qc_subject.csv",
            keep_default_na=False,
            dtype={"sample_key": str},
        ),
        "cell_manifest": json.loads((cell / "cell_manifest.json").read_text(encoding="utf-8")),
    }


def align_common_edges(
    x: np.ndarray, edge_manifest: pd.DataFrame, common_edge_path: Path
) -> tuple[np.ndarray, pd.DataFrame]:
    cache_key = str(common_edge_path.resolve())
    common = _COMMON_EDGE_CACHE.get(cache_key)
    if common is None:
        common = pd.read_csv(common_edge_path, keep_default_na=False)
        _COMMON_EDGE_CACHE[cache_key] = common
    positions = edge_manifest.set_index("edge_uid")["matrix_position"]
    try:
        columns = [int(positions.loc[uid]) for uid in common["edge_uid"]]
    except KeyError as exc:
        raise ValueError(f"cell is missing common edge {exc}") from exc
    return np.asarray(x)[:, columns], common


def fit_logistic(
    x_train: np.ndarray,
    y_train: np.ndarray,
    c: float,
    *,
    pca_max: int,
    seed: int,
    max_iter: int = 5000,
) -> dict[str, Any]:
    y = np.asarray(y_train, dtype=np.int64)
    if np.unique(y).size != 2:
        raise ValueError("both classes are required for logistic regression")
    scaled, mean, scale = _standardize_fit(x_train)
    pca = None
    if pca_max:
        components = min(int(pca_max), scaled.shape[0] - 1, scaled.shape[1])
        if components >= 1:
            pca = PCA(n_components=components, random_state=int(seed)).fit(scaled)
            scaled = pca.transform(scaled)
    classifier = LogisticRegression(
        C=float(c), solver="liblinear", dual=scaled.shape[1] > scaled.shape[0],
        max_iter=int(max_iter), random_state=int(seed)
    ).fit(scaled, y)
    return {"c": float(c), "mean": mean, "scale": scale, "pca": pca, "classifier": classifier}


def predict_logistic(model: dict[str, Any], x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = _standardize_apply(x, model["mean"], model["scale"])
    if model["pca"] is not None:
        values = model["pca"].transform(values)
    return model["classifier"].decision_function(values), model["classifier"].predict_proba(values)[:, 1]
