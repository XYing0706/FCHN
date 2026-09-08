"""Run one or all Stage C strict nested FCHN outer folds."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MISSING_COVARIATE_REASON = "MISSING_REQUIRED_COVARIATE"
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_b import reconstruct_nested_task_membership  # noqa: E402
from fchn_stage_c import (  # noqa: E402
    align_common_edges,
    assemble_meta_features,
    build_health_crossfit_folds,
    build_covariates,
    canonicalize_sex,
    fit_health_anchor,
    fit_logistic,
    fit_ridge_residualizer,
    high_order_fc,
    load_cell_fc,
    predict_logistic,
    select_c_from_oof,
    sha256_file,
)


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _ordered_parallel_map(function, items, *, workers: int) -> list:
    values = list(items)
    if int(workers) <= 1:
        return [function(item) for item in values]
    with ThreadPoolExecutor(max_workers=int(workers)) as executor:
        return list(executor.map(function, values))


def _assemble_oof_meta_features(
    feature_frames: dict[str, pd.DataFrame], subjects: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    for frame in feature_frames.values():
        if not frame.index.astype(str).is_unique:
            raise ValueError("meta OOF requires unique sample_key per view")
    if not subjects["sample_key"].astype(str).is_unique:
        raise ValueError("meta OOF requires unique sample_key in subjects")
    fc_keys = feature_frames["fc"].index.astype(str).tolist()
    hofc_keys = set(feature_frames["hofc"].index.astype(str))
    normative_keys = set(feature_frames["normative"].index.astype(str))
    keys = np.asarray(
        [key for key in fc_keys if key in hofc_keys and key in normative_keys],
        dtype=str,
    )
    normative = feature_frames["normative"].loc[keys].to_numpy()
    meta = assemble_meta_features(
        feature_frames["fc"].loc[keys].to_numpy()[:, 0],
        feature_frames["hofc"].loc[keys].to_numpy()[:, 0],
        normative[:, 0], normative[:, 1:],
    )
    finite = np.isfinite(meta).all(axis=1)
    keys = keys[finite]
    labels = subjects.set_index("sample_key").loc[keys, "label"].to_numpy(dtype=int)
    return meta[finite], labels, keys


def _assemble_oof_pieces(
    pieces: list[tuple[np.ndarray, np.ndarray]],
) -> pd.DataFrame:
    if not pieces:
        raise ValueError("OOF feature assembly received no validation pieces")
    keys = np.concatenate([np.asarray(key, dtype=str) for key, _ in pieces])
    values = np.vstack([np.asarray(value, dtype=np.float64) for _, value in pieces])
    if len(keys) != len(values):
        raise ValueError("OOF feature row count does not match sample_key count")
    if not pd.Index(keys).is_unique:
        raise ValueError("OOF validation requires unique sample_key")
    return pd.DataFrame(values, index=keys)


def _model_state_arrays(result: dict) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {
        "selected_c": np.asarray(
            [result["selected_c"][view] for view in ("fc", "hofc", "normative")],
            dtype=np.float64,
        ),
        "meta_c": np.asarray([result["meta_c"]], dtype=np.float64),
    }

    def add_logistic(prefix: str, model: dict) -> None:
        arrays[f"{prefix}_scaler_mean"] = np.asarray(model["mean"])
        arrays[f"{prefix}_scaler_scale"] = np.asarray(model["scale"])
        arrays[f"{prefix}_classifier_coef"] = np.asarray(model["classifier"].coef_)
        arrays[f"{prefix}_classifier_intercept"] = np.asarray(model["classifier"].intercept_)
        if model["pca"] is not None:
            arrays[f"{prefix}_pca_components"] = np.asarray(model["pca"].components_)
            arrays[f"{prefix}_pca_mean"] = np.asarray(model["pca"].mean_)

    def add_ridge(prefix: str, ridge) -> None:
        for name in ("cov_mean", "cov_scale", "beta", "feature_mean"):
            arrays[f"{prefix}_{name}"] = np.asarray(getattr(ridge, name))

    for view in ("fc", "hofc", "normative"):
        model = result["models"][view]
        add_logistic(view, model.classifier)
        if view == "normative":
            prep = model.prep
            arrays["normative_imputer_median"] = np.asarray(prep["common_medians"])
            add_ridge("normative_common_ridge", prep["common_ridge"])
            arrays["normative_common_scaler_mean"] = np.asarray(prep["scale_mean"])
            arrays["normative_common_scaler_scale"] = np.asarray(prep["scale_scale"])
            arrays["normative_anchor_prototypes"] = np.asarray(prep["anchor"].prototypes)
            arrays["normative_anchor_variances"] = np.asarray(prep["anchor"].variances)
            arrays["normative_anchor_metadata"] = np.asarray(
                [prep["anchor"].n_prototypes, prep["anchor"].variance_floor],
                dtype=np.float64,
            )
        else:
            arrays[f"{view}_imputer_median"] = np.asarray(model.prep["medians"])
            add_ridge(f"{view}_ridge", model.prep["ridge"])
            arrays[f"{view}_n_roi"] = np.asarray(
                [model.prep["n_roi"]], dtype=np.int64
            )
    add_logistic("meta", result["meta_final"])
    arrays["platt_coef"] = np.asarray(result["platt"].coef_)
    arrays["platt_intercept"] = np.asarray(result["platt"].intercept_)
    if any(value.dtype == object for value in arrays.values()):
        raise ValueError("model state contains object arrays")
    return arrays


def _array_group_hash(arrays: dict[str, np.ndarray], prefixes: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for name in sorted(name for name in arrays if name.startswith(prefixes)):
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(value.shape).encode("ascii"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _current_run_hashes(config_path: Path) -> dict[str, str]:
    paths = {
        "config": config_path,
        "runner": Path(__file__).resolve(),
        "stage_c_source": PROJECT_ROOT / "src" / "fchn_stage_c.py",
        "stage_b_source": PROJECT_ROOT / "src" / "fchn_stage_b.py",
        "stage_a_manifest": PROJECT_ROOT / "outputs" / "stage_a" / "stage_a_manifest.json",
        "stage_b_manifest": PROJECT_ROOT / "outputs" / "stage_b" / "stage_b_manifest.json",
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def _fold_is_fresh(fold_dir: Path, run_hashes: dict[str, str]) -> bool:
    marker = fold_dir / "_SUCCESS"
    manifest_path = fold_dir / "fold_manifest.json"
    if not marker.exists() or not manifest_path.exists():
        return False
    if marker.read_text(encoding="utf-8") != "stage_c_fold_ready\n":
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("run_hashes") == run_hashes


def _load_configs(path: Path) -> tuple[dict, dict]:
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    b = yaml.safe_load((PROJECT_ROOT / "config" / "stage_b.yaml").read_text(encoding="utf-8"))
    if Path(c["project_root"]).resolve() != PROJECT_ROOT.resolve():
        raise ValueError("stage_c project_root must equal this project directory")
    return c, b


def _canonical_subjects(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["sample_key"] = out["sample_key"].astype(str)
    out["sex"] = canonicalize_sex(out["sex"], str(out["dataset_id"].iloc[0]))
    for column in ("age", "scan_length", "mean_fd", "label"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def _read_split_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path, keep_default_na=False, dtype={"sample_key": str}
    )


def _ids(frame: pd.DataFrame, role: str) -> list[str]:
    return frame.loc[frame["role"] == role, "sample_key"].astype(str).tolist()


def _impute_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(x, dtype=np.float64)
    medians = np.nanmedian(values, axis=0)
    if np.isnan(medians).any():
        raise ValueError("all-train-nonfinite edge encountered")
    return np.where(np.isfinite(values), values, medians), medians


def _impute_apply(x: np.ndarray, medians: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x), x, medians)


class ViewModel:
    def __init__(self, view: str, prep: dict, classifier: dict):
        self.view, self.prep, self.classifier = view, prep, classifier

    def transform(self, x: np.ndarray, subjects: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray] | None]:
        features, extra = _transform_prepared(self.view, self.prep, subjects)
        logit, prob = predict_logistic(self.classifier, features)
        return logit, prob, extra


def _transform_prepared(view: str, prep: dict, subjects: pd.DataFrame) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray] | None]:
    indices = [prep["subject_index"][str(k)] for k in subjects["sample_key"]]
    if view == "normative":
        if "common_x_all" in prep:
            common = prep["common_x_all"][indices]
        else:
            raw = prep["x_all"][indices]
            common, _ = align_common_edges(
                raw, prep["edge_manifest"], prep["common_edge_path"]
            )
        cov, _ = build_covariates(subjects, include_mean_fd=False)
        residual = prep["common_ridge"].transform(
            _impute_apply(common, prep["common_medians"]), cov
        )
        scaled = (residual - prep["scale_mean"]) / prep["scale_scale"]
        summaries, edge_z, nearest = prep["anchor"].transform(scaled)
        return summaries, (summaries, edge_z, nearest)
    raw = _impute_apply(prep["x_all"][indices], prep["medians"])
    cov, _ = build_covariates(subjects, include_mean_fd=prep["include_mean_fd"])
    residual = prep["ridge"].transform(raw, cov)
    if view == "hofc":
        return high_order_fc(residual, n_roi=prep["n_roi"]), None
    return residual, None


def _prepare_view(
    view: str,
    train: pd.DataFrame,
    cell: dict,
    fcp: dict | None,
    common_edge_path: Path,
    config: dict,
    seed: int,
) -> tuple[dict, np.ndarray, np.ndarray]:
    include_fd = view != "normative"
    subject_index = {str(k): i for i, k in enumerate(cell["subject_ids"])}
    keys = train["sample_key"].astype(str).tolist()
    if any(k not in subject_index for k in keys):
        raise ValueError("split sample_key is absent from FC source")
    rows = [subject_index[k] for k in keys]
    raw = cell["x"][rows]
    imputed, medians = _impute_fit(raw)
    cov, continuous = build_covariates(train, include_mean_fd=include_fd)
    if not np.isfinite(cov).all():
        raise ValueError("missing covariate in eligible training set")
    ridge, residual = fit_ridge_residualizer(
        imputed, cov, continuous, alpha=float(config["preprocessing"]["ridge_alpha"])
    )
    prep = {
        "x_all": cell["x"], "subject_index": subject_index, "medians": medians,
        "ridge": ridge, "include_mean_fd": include_fd,
        "n_roi": int(cell["roi_indices"].size),
        "edge_manifest": cell["edge_manifest"], "common_edge_path": common_edge_path,
    }
    if view == "hofc":
        train_features = high_order_fc(residual, n_roi=prep["n_roi"])
    elif view == "normative":
        if fcp is None:
            raise ValueError("normative view requires FCP")
        common_all = cell.get("common_x")
        if common_all is None:
            common_all, _ = align_common_edges(
                cell["x"], cell["edge_manifest"], common_edge_path
            )
        common_fcp = fcp.get("common_x")
        if common_fcp is None:
            common_fcp, _ = align_common_edges(
                fcp["x"], fcp["edge_manifest"], common_edge_path
            )
        common_train = common_all[rows]
        common_train, common_medians = _impute_fit(common_train)
        common_cov, common_cont = build_covariates(train, include_mean_fd=False)
        common_ridge, common_residual = fit_ridge_residualizer(
            common_train, common_cov, common_cont,
            alpha=float(config["preprocessing"]["ridge_alpha"]),
        )
        # _fit_outer canonicalizes FCP once at load time; applying the raw 1/2
        # mapping a second time would turn canonical 0/1 into missing values.
        fcp_subjects = fcp["subjects"].copy()
        fcp_cov, _ = build_covariates(fcp_subjects, include_mean_fd=False)
        fcp_residual = common_ridge.transform(
            _impute_apply(common_fcp, common_medians), fcp_cov
        )
        scale_mean = common_residual.mean(axis=0)
        scale_scale = common_residual.std(axis=0, ddof=0)
        scale_scale[scale_scale < 1e-12] = 1.0
        train_scaled = (common_residual - scale_mean) / scale_scale
        fcp_scaled = (fcp_residual - scale_mean) / scale_scale
        healthy = np.vstack([fcp_scaled, train_scaled[train["label"].to_numpy() == 0]])
        anchor = fit_health_anchor(
            healthy,
            max_prototypes=int(config["normative"]["max_prototypes"]),
            minimum_health=int(config["normative"]["minimum_health_reference"]),
            shrinkage=float(config["normative"]["shrinkage"]),
            variance_floor=float(config["normative"]["variance_floor"]),
            seed=seed,
            k_rule_divisor=int(config["normative"]["k_rule_divisor"]),
            kmeans_n_init=int(config["normative"]["kmeans_n_init"]),
        )
        train_features, _, _ = anchor.transform(train_scaled)
        prep.update({
            "x_all": common_train if False else cell["x"],
            "common_x_all": common_all,
            "common_fcp": common_fcp,
            "common_medians": common_medians,
            "common_ridge": common_ridge,
            "scale_mean": scale_mean,
            "scale_scale": scale_scale,
            "anchor": anchor,
        })
        # ViewModel.transform uses the common-space branch below.
    else:
        train_features = residual
    return prep, train_features, residual


def _fit_view_model(
    view: str,
    train: pd.DataFrame,
    cell: dict,
    fcp: dict | None,
    common_edge_path: Path,
    config: dict,
    c: float,
    seed: int,
) -> ViewModel:
    train = _eligible(train, include_mean_fd=view != "normative")
    prep, features, _ = _prepare_view(view, train, cell, fcp, common_edge_path, config, seed)
    classifier = fit_logistic(
        features, train["label"].to_numpy(dtype=np.int64), c,
        pca_max=(int(config["views"]["hofc_pca_max"]) if view == "hofc" else 0),
        seed=seed, max_iter=int(config["models"]["max_iter"]),
    )
    return ViewModel(view, prep, classifier)


def _view_predict(model: ViewModel, subjects: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    valid = np.isfinite(
        build_covariates(subjects, include_mean_fd=model.prep["include_mean_fd"])[0]
    ).all(axis=1)
    if not bool(valid.all()):
        good = subjects.loc[valid].copy()
        good_logits, good_probs, good_extra = _view_predict(model, good)
        logits = np.full(len(subjects), np.nan); probs = np.full(len(subjects), np.nan)
        logits[valid] = good_logits; probs[valid] = good_probs
        if good_extra is None:
            return logits, probs, None
        summaries = np.full((len(subjects), good_extra[0].shape[1]), np.nan)
        edge_z = np.full((len(subjects), good_extra[1].shape[1]), np.nan)
        nearest = np.full(len(subjects), -1, dtype=int)
        summaries[valid] = good_extra[0]
        edge_z[valid] = good_extra[1]
        nearest[valid] = good_extra[2]
        return logits, probs, (summaries, edge_z, nearest)
    features, extra = _transform_prepared(model.view, model.prep, subjects)
    logit, prob = predict_logistic(model.classifier, features)
    return logit, prob, extra


def _predict_finite_rows(
    model: dict, features: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(features, dtype=np.float64)
    valid = np.isfinite(values).all(axis=1)
    logits = np.full(len(values), np.nan, dtype=np.float64)
    probabilities = np.full(len(values), np.nan, dtype=np.float64)
    if valid.any():
        logits[valid], probabilities[valid] = predict_logistic(model, values[valid])
    return logits, probabilities, valid


def _task_members(
    task_id: str, nested: pd.DataFrame, direct: pd.DataFrame, subjects: pd.DataFrame, bconfig: dict
) -> pd.DataFrame:
    if task_id in set(nested["task_id"]):
        return reconstruct_nested_task_membership(task_id, nested, subjects, direct, bconfig)
    return direct.loc[direct["task_id"] == task_id, ["role", "sample_key"]].copy()


def _frame_for_ids(subjects: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    wanted = set(map(str, keys))
    return subjects.loc[subjects["sample_key"].astype(str).isin(wanted)].copy()


def _eligible(frame: pd.DataFrame, *, include_mean_fd: bool) -> pd.DataFrame:
    cov, _ = build_covariates(frame, include_mean_fd=include_mean_fd)
    return frame.loc[np.isfinite(cov).all(axis=1)].copy()


def _fcp_crossfit_audit(
    fcp_scaled: np.ndarray,
    fcp_subjects: pd.DataFrame,
    outer_healthy_scaled: np.ndarray,
    config: dict,
    seed: int,
) -> pd.DataFrame:
    """Fit site-aware health anchors out of fold and record self-exclusion."""
    n_splits = int(config["normative"]["fcp_crossfit_splits"])
    folds = build_health_crossfit_folds(
        fcp_subjects[["site_id", "sample_key"]], n_splits=n_splits
    )
    keys = fcp_subjects["sample_key"].astype(str).to_numpy()
    rows: list[dict] = []
    for fold in range(n_splits):
        held = folds == fold
        fit = ~held
        reference = np.vstack([fcp_scaled[fit], outer_healthy_scaled])
        anchor = fit_health_anchor(
            reference,
            max_prototypes=int(config["normative"]["max_prototypes"]),
            minimum_health=int(config["normative"]["minimum_health_reference"]),
            shrinkage=float(config["normative"]["shrinkage"]),
            variance_floor=float(config["normative"]["variance_floor"]),
            seed=int(seed) + fold,
            k_rule_divisor=int(config["normative"]["k_rule_divisor"]),
            kmeans_n_init=int(config["normative"]["kmeans_n_init"]),
        )
        summaries, _, _ = anchor.transform(fcp_scaled[held])
        fit_keys = sorted(keys[fit].tolist())
        held_keys = keys[held].tolist()
        for key, finite in zip(held_keys, np.isfinite(summaries).all(axis=1)):
            rows.append({
                "sample_key": key,
                "crossfit_fold": int(fold),
                "fit_fcp_count": int(fit.sum()),
                "fit_outer_healthy_count": int(len(outer_healthy_scaled)),
                "fit_reference_count": int(len(reference)),
                "fit_subject_hash": _json_hash(fit_keys),
                "heldout_subject_hash": _json_hash(sorted(held_keys)),
                "self_excluded": bool(key not in set(fit_keys)),
                "score_finite": bool(finite),
            })
    audit = pd.DataFrame(rows).sort_values("sample_key").reset_index(drop=True)
    if len(audit) != len(fcp_subjects) or not bool(audit["self_excluded"].all()):
        raise ValueError("FCP health cross-fit self-exclusion audit failed")
    return audit


def _evaluate_c_tuning_task(
    task_id: str,
    view: str,
    nested: pd.DataFrame,
    direct: pd.DataFrame,
    subjects: pd.DataFrame,
    cell: dict,
    fcp: dict | None,
    common_path: Path,
    config: dict,
    bconfig: dict,
    seed: int,
) -> tuple[list[int], dict[float, list[float]]]:
    members = _task_members(task_id, nested, direct, subjects, bconfig)
    include_fd = view != "normative"
    train = _eligible(
        _frame_for_ids(subjects, _ids(members, "train")),
        include_mean_fd=include_fd,
    )
    val = _eligible(
        _frame_for_ids(subjects, _ids(members, "validation")),
        include_mean_fd=include_fd,
    )
    predictions = {float(c): [] for c in config["models"]["base_c_grid"]}
    if train["label"].nunique() < 2 or len(val) == 0:
        return [], predictions
    try:
        prep, train_features, _ = _prepare_view(
            view, train, cell, fcp, common_path, config, seed
        )
        val_features, _ = _transform_prepared(view, prep, val)
    except ValueError:
        return [], predictions
    for c in predictions:
        try:
            classifier = fit_logistic(
                train_features,
                train["label"].to_numpy(dtype=np.int64),
                c,
                pca_max=(
                    int(config["views"]["hofc_pca_max"])
                    if view == "hofc" else 0
                ),
                seed=seed,
                max_iter=int(config["models"]["max_iter"]),
            )
            _, probability = predict_logistic(classifier, val_features)
            predictions[c] = probability.tolist()
        except ValueError:
            predictions[c] = [np.nan] * len(val)
    return val["label"].astype(int).tolist(), predictions


def _build_oof_view_features(
    view: str,
    children: pd.DataFrame,
    nested: pd.DataFrame,
    direct: pd.DataFrame,
    subjects: pd.DataFrame,
    cell: dict,
    fcp: dict | None,
    common_path: Path,
    config: dict,
    bconfig: dict,
    c: float,
    seed: int,
) -> pd.DataFrame:
    pieces: list[tuple[np.ndarray, np.ndarray]] = []
    for child in children.itertuples(index=False):
        members = _task_members(child.task_id, nested, direct, subjects, bconfig)
        train = _eligible(
            _frame_for_ids(subjects, _ids(members, "train")),
            include_mean_fd=view != "normative",
        )
        validation = _eligible(
            _frame_for_ids(subjects, _ids(members, "validation")),
            include_mean_fd=view != "normative",
        )
        model = _fit_view_model(
            view, train, cell, fcp, common_path, config, c, seed
        )
        logit, _, extra = _view_predict(model, validation)
        value = (
            np.column_stack([logit, extra[0]])
            if view == "normative"
            else logit[:, None]
        )
        pieces.append((validation["sample_key"].astype(str).to_numpy(), value))
    return _assemble_oof_pieces(pieces)


def _select_base_c(
    view: str, outer_id: str, tasks: pd.DataFrame, nested: pd.DataFrame, direct: pd.DataFrame,
    subjects: pd.DataFrame, cell: dict, fcp: dict | None, common_path: Path,
    config: dict, bconfig: dict, seed: int,
) -> tuple[float, dict[float, float]]:
    base = nested.loc[(nested["task_level"] == "base_oof") & (nested["parent_task_id"] == outer_id), "task_id"]
    tuning = nested.loc[(nested["task_level"] == "base_c_tuning") & nested["parent_task_id"].isin(base)]
    predictions = {float(c): [] for c in config["models"]["base_c_grid"]}
    truth: list[int] = []
    def evaluate(task_id: str):
        return _evaluate_c_tuning_task(
            task_id, view, nested, direct, subjects, cell, fcp, common_path,
            config, bconfig, seed,
        )
    results = _ordered_parallel_map(
        evaluate,
        tuning["task_id"].astype(str).tolist(),
        workers=int(config["execution"]["tuning_workers"]),
    )
    for task_truth, task_predictions in results:
        truth.extend(task_truth)
        for c in predictions:
            predictions[c].extend(task_predictions[c])
    y = np.asarray(truth, dtype=np.int64)
    usable = {c: np.asarray(p, dtype=np.float64) for c, p in predictions.items()}
    usable = {c: p[np.isfinite(p)] for c, p in usable.items() if len(p) == len(y) and np.isfinite(p).all()}
    if not usable or y.size == 0:
        return float(config["models"]["base_c_grid"][0]), {}
    return select_c_from_oof(y, usable)


def _fit_outer(
    atlas: str, dataset: str, protocol: str, outer_id: str, config: dict, bconfig: dict
) -> dict:
    group = PROJECT_ROOT / "outputs" / "splits" / atlas / dataset / protocol
    tasks = pd.read_csv(group / "tasks.csv", keep_default_na=False)
    nested = pd.read_csv(group / "nested_tasks.csv", keep_default_na=False)
    direct = _read_split_csv(group / "split_membership.csv")
    cell = load_cell_fc(PROJECT_ROOT, dataset, atlas)
    subjects = _canonical_subjects(cell["subjects"])
    fcp = load_cell_fc(PROJECT_ROOT, "fcp", atlas)
    fcp["subjects"] = _canonical_subjects(fcp["subjects"])
    common_path = PROJECT_ROOT / "outputs" / "stage_a" / f"common_edge_{atlas}.csv"
    cell["common_x"], _ = align_common_edges(
        cell["x"], cell["edge_manifest"], common_path
    )
    fcp["common_x"], _ = align_common_edges(
        fcp["x"], fcp["edge_manifest"], common_path
    )
    outer_members = _task_members(outer_id, nested, direct, subjects, bconfig)
    train = _frame_for_ids(subjects, _ids(outer_members, "fit"))
    test = _frame_for_ids(subjects, _ids(outer_members, "test"))
    if train["label"].nunique() < 2:
        return {"status": "invalid_untrainable", "reason_code": "OUTER_TRAIN_SINGLE_CLASS"}
    models: dict[str, ViewModel] = {}
    selected: dict[str, float] = {}
    for offset, view in enumerate(("fc", "hofc", "normative")):
        print(f"stage C selecting base C: {atlas}/{dataset}/{protocol}/{outer_id}/{view}", flush=True)
        c, _ = _select_base_c(
            view, outer_id, tasks, nested, direct, subjects, cell, fcp, common_path,
            config, bconfig, int(config["seed"]) + offset,
        )
        selected[view] = c
        models[view] = _fit_view_model(
            view, train, cell, fcp, common_path, config, c, int(config["seed"]) + offset + 1000
        )
        if view == "normative":
            models[view].prep["edge_manifest"] = cell["edge_manifest"]
            models[view].prep["common_edge_path"] = common_path

    # Strict Meta OOF: each meta fold receives base features made by its own nested base folds.
    meta_rows = nested.loc[(nested["task_level"] == "meta_oof") & (nested["parent_task_id"] == outer_id)]
    meta_fold_data: list[
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ] = []
    for meta in meta_rows.itertuples(index=False):
        meta_members = _task_members(meta.task_id, nested, direct, subjects, bconfig)
        meta_train = _frame_for_ids(subjects, _ids(meta_members, "train"))
        meta_val = _frame_for_ids(subjects, _ids(meta_members, "validation"))
        train_features = {}
        val_features = {}
        for view_index, view in enumerate(("fc", "hofc", "normative")):
            base_children = nested.loc[
                (nested["task_level"] == "meta_base_oof") &
                (nested["parent_task_id"] == meta.task_id)
            ]
            tuning_ids = nested.loc[
                (nested["task_level"] == "meta_base_c_tuning") &
                nested["parent_task_id"].isin(base_children["task_id"]), "task_id"
            ]
            # Select this base C only from this meta train boundary.
            c_predictions = {float(c): [] for c in config["models"]["base_c_grid"]}
            c_truth: list[int] = []
            def evaluate(task_id: str):
                return _evaluate_c_tuning_task(
                    task_id, view, nested, direct, subjects, cell, fcp,
                    common_path, config, bconfig,
                    int(config["seed"]) + view_index,
                )
            tuning_results = _ordered_parallel_map(
                evaluate,
                tuning_ids.astype(str).tolist(),
                workers=int(config["execution"]["tuning_workers"]),
            )
            for task_truth, task_predictions in tuning_results:
                c_truth.extend(task_truth)
                for c in c_predictions:
                    c_predictions[c].extend(task_predictions[c])
            y_c = np.asarray(c_truth, dtype=np.int64)
            usable = {c: np.asarray(p) for c, p in c_predictions.items() if len(p) == len(y_c) and np.isfinite(p).all()}
            c = select_c_from_oof(y_c, usable)[0] if usable and y_c.size else float(config["models"]["base_c_grid"][0])
            train_features[view] = _build_oof_view_features(
                view, base_children, nested, direct, subjects, cell, fcp,
                common_path, config, bconfig, c,
                int(config["seed"]) + view_index + 200,
            )
            full_m = _fit_view_model(view, meta_train, cell, fcp, common_path, config, c, int(config["seed"]) + view_index + 400)
            lg, pr, extra = _view_predict(full_m, meta_val)
            val_features[view] = np.column_stack([lg, extra[0]]) if view == "normative" else lg[:, None]
        meta_tr, meta_train_y, keys = _assemble_oof_meta_features(
            train_features, subjects
        )
        meta_va = assemble_meta_features(
            val_features["fc"][:, 0], val_features["hofc"][:, 0],
            val_features["normative"][:, 0], val_features["normative"][:, 1:],
        )
        val_finite = np.isfinite(meta_va).all(axis=1)
        meta_va = meta_va[val_finite]
        meta_val_y = meta_val.loc[val_finite, "label"].to_numpy(dtype=int)
        meta_val_keys = meta_val.loc[val_finite, "sample_key"].astype(str).to_numpy()
        meta_fold_data.append(
            (meta_tr, meta_va, meta_train_y, meta_val_y, meta_val_keys)
        )
    if not meta_fold_data:
        return {"status": "invalid_untrainable", "reason_code": "NO_STRICT_META_OOF"}
    meta_predictions = {float(c): [] for c in config["models"]["meta_c_grid"]}
    meta_y: list[int] = []
    meta_oof_logit = np.full(len(subjects), np.nan)
    key_to_pos = {str(k): i for i, k in enumerate(subjects["sample_key"])}
    for tr_x, va_x, tr_y, va_y, _ in meta_fold_data:
        meta_y.extend(va_y.tolist())
        for c in meta_predictions:
            model = fit_logistic(tr_x, tr_y, c, pca_max=0, seed=int(config["seed"]))
            lg, pr = predict_logistic(model, va_x); meta_predictions[c].extend(pr.tolist())
        # selected after pooled comparison; store validation rows by key below.
    meta_c, meta_losses = select_c_from_oof(np.asarray(meta_y), {c: np.asarray(p) for c, p in meta_predictions.items()})
    # Fit the final Meta only on the top-level base OOF predictions. Each
    # eligible outer-train subject therefore contributes at most one row.
    top_base_children = nested.loc[
        (nested["task_level"] == "base_oof")
        & (nested["parent_task_id"] == outer_id)
    ]
    final_feature_frames = {
        view: _build_oof_view_features(
            view, top_base_children, nested, direct, subjects, cell, fcp,
            common_path, config, bconfig, selected[view],
            int(config["seed"]) + view_index + 6000,
        )
        for view_index, view in enumerate(("fc", "hofc", "normative"))
    }
    strict_features, strict_y, strict_keys = _assemble_oof_meta_features(
        final_feature_frames, subjects
    )
    meta_final = fit_logistic(
        strict_features, strict_y, meta_c, pca_max=0,
        seed=int(config["seed"]) + 9000,
    )
    strict_logits = []
    strict_labels = []
    strict_validation_keys: list[str] = []
    for tr_x, va_x, tr_y, va_y, val_keys in meta_fold_data:
        fold_model = fit_logistic(tr_x, tr_y, meta_c, pca_max=0, seed=int(config["seed"]) + 9001)
        fold_logits, _ = predict_logistic(fold_model, va_x)
        strict_logits.extend(fold_logits.tolist())
        strict_labels.extend(va_y.tolist())
        strict_validation_keys.extend(val_keys.tolist())
    if not pd.Index(strict_validation_keys).is_unique:
        raise ValueError("strict Meta validation requires unique sample_key")
    platt = LogisticRegression(C=float(config["models"]["platt_c"]), solver="lbfgs", max_iter=1000)
    platt.fit(np.asarray(strict_logits, dtype=np.float64).reshape(-1, 1), np.asarray(strict_labels, dtype=np.int64))
    test_features = []
    base_outputs = {}
    norm_extra = None
    for view in ("fc", "hofc", "normative"):
        lg, pr, extra = _view_predict(models[view], test)
        base_outputs[view] = (lg, pr)
        if view == "normative": norm_extra = extra
        test_features.append(lg[:, None])
    test_meta = assemble_meta_features(
        base_outputs["fc"][0], base_outputs["hofc"][0],
        base_outputs["normative"][0], norm_extra[0],
    )
    norm_prep = models["normative"].prep
    norm_train = _eligible(train, include_mean_fd=False)
    norm_rows = [norm_prep["subject_index"][str(k)] for k in norm_train["sample_key"]]
    norm_common, _ = align_common_edges(cell["x"][norm_rows], cell["edge_manifest"], common_path)
    norm_common = _impute_apply(norm_common, norm_prep["common_medians"])
    norm_cov, _ = build_covariates(norm_train, include_mean_fd=False)
    norm_residual = norm_prep["common_ridge"].transform(norm_common, norm_cov)
    norm_train_scaled = (norm_residual - norm_prep["scale_mean"]) / norm_prep["scale_scale"]
    outer_healthy = norm_train_scaled[norm_train["label"].to_numpy(dtype=int) == 0]
    fcp_cov, _ = build_covariates(fcp["subjects"], include_mean_fd=False)
    fcp_residual = norm_prep["common_ridge"].transform(
        _impute_apply(norm_prep["common_fcp"], norm_prep["common_medians"]), fcp_cov
    )
    fcp_scaled = (fcp_residual - norm_prep["scale_mean"]) / norm_prep["scale_scale"]
    fcp_audit = _fcp_crossfit_audit(
        fcp_scaled, fcp["subjects"], outer_healthy, config, int(config["seed"]) + 7000
    )
    test_meta_logit, test_meta_prob, test_meta_valid = _predict_finite_rows(
        meta_final, test_meta
    )
    test_meta_calibrated = np.full(len(test_meta), np.nan, dtype=np.float64)
    if test_meta_valid.any():
        test_meta_calibrated[test_meta_valid] = platt.predict_proba(
            test_meta_logit[test_meta_valid].reshape(-1, 1)
        )[:, 1]
    state_arrays = _model_state_arrays({
        "models": models, "meta_final": meta_final, "platt": platt,
        "selected_c": selected, "meta_c": meta_c,
    })
    outer_row = nested.loc[nested["task_id"] == outer_id].iloc[0]
    outer_fold = int(outer_row["outer_fold"])
    split_path = (
        f"outputs/splits/{atlas}/{dataset}/{protocol}/nested_tasks.csv"
        f"#task_id={outer_id}"
    )
    identity = {
        "task_id": outer_id,
        "outer_fold": outer_fold,
        "split_path": split_path,
        "variant": config["variant"],
        "train_subject_hash": _json_hash(sorted(strict_keys.tolist())),
        "validation_subject_hash": _json_hash(sorted(strict_validation_keys)),
        "test_subject_hash": _json_hash(sorted(test["sample_key"].astype(str))),
        "roi_manifest_hash": sha256_file(
            PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "roi_manifest.csv"
        ),
        "edge_manifest_hash": sha256_file(
            PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "edge_manifest.csv"
        ),
        "task_status": "passed",
        "reason_code": "",
    }
    view_state_hashes = {}
    for view in ("fc", "hofc", "normative"):
        ridge_prefix = (
            ("normative_common_ridge",) if view == "normative" else (f"{view}_ridge",)
        )
        view_state_hashes[view] = {
            "imputer_state_hash": _array_group_hash(state_arrays, (f"{view}_imputer",)),
            "ridge_state_hash": _array_group_hash(state_arrays, ridge_prefix),
            "scaler_pca_state_hash": _array_group_hash(state_arrays, (f"{view}_scaler", f"{view}_pca")),
            "normative_state_hash": (
                _array_group_hash(state_arrays, ("normative_common_scaler", "normative_anchor"))
                if view == "normative" else ""
            ),
        }
    full_state_hashes = {
        "imputer_state_hash": _array_group_hash(state_arrays, ("fc_imputer", "hofc_imputer", "normative_imputer")),
        "ridge_state_hash": _array_group_hash(state_arrays, ("fc_ridge", "hofc_ridge", "normative_common_ridge")),
        "scaler_pca_state_hash": _array_group_hash(state_arrays, ("fc_scaler", "fc_pca", "hofc_scaler", "hofc_pca", "normative_scaler", "meta_scaler", "meta_pca", "platt")),
        "normative_state_hash": _array_group_hash(state_arrays, ("normative_common_scaler", "normative_anchor")),
    }
    rows = []
    for i, key in enumerate(test["sample_key"].astype(str)):
        for view in ("fc", "hofc", "normative"):
            probability = float(base_outputs[view][1][i])
            valid = bool(np.isfinite(probability) and np.isfinite(base_outputs[view][0][i]))
            rows.append({**identity, **view_state_hashes[view], "sample_key": key, "view": view, "prediction_level": "base", "prediction": int(probability >= 0.5) if valid else "", "logit": float(base_outputs[view][0][i]), "probability": probability, "raw_probability": probability, "true_label": int(test.iloc[i]["label"]), "selected_c": selected[view], "selected_c_fc": selected["fc"], "selected_c_hofc": selected["hofc"], "selected_c_normative": selected["normative"], "meta_c": meta_c, "task_status": "passed" if valid else "ineligible", "reason_code": "" if valid else MISSING_COVARIATE_REASON})
        calibrated = float(test_meta_calibrated[i])
        valid = bool(test_meta_valid[i])
        rows.append({**identity, **full_state_hashes, "sample_key": key, "view": "full_fchn", "prediction_level": "meta", "prediction": int(calibrated >= 0.5) if valid else "", "logit": float(test_meta_logit[i]), "probability": calibrated, "raw_probability": float(test_meta_prob[i]), "true_label": int(test.iloc[i]["label"]), "selected_c": "", "selected_c_fc": selected["fc"], "selected_c_hofc": selected["hofc"], "selected_c_normative": selected["normative"], "meta_c": meta_c, "task_status": "passed" if valid else "ineligible", "reason_code": "" if valid else MISSING_COVARIATE_REASON})
    return {"status": "passed", "predictions": pd.DataFrame(rows), "selected_c": selected, "meta_c": meta_c, "meta_losses": meta_losses, "norm_extra": norm_extra, "fcp_crossfit_audit": fcp_audit, "test": test, "train": train, "models": models, "meta_final": meta_final, "platt": platt, "model_state": state_arrays, "identity": identity, "strict_meta_keys": strict_keys, "outer_members": outer_members, "nested": nested, "direct": direct, "cell": cell}


def _write_fold(
    result: dict, fold_dir: Path, config: dict, atlas: str, dataset: str,
    protocol: str, outer_id: str, run_hashes: dict[str, str]
) -> None:
    fold_dir.mkdir(parents=True, exist_ok=True)
    if result["status"] != "passed":
        (fold_dir / "fold_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (fold_dir / "_SUCCESS").write_text("stage_c_fold_invalid\n", encoding="utf-8")
        return
    result["predictions"].to_csv(fold_dir / "predictions.csv", index=False)
    if result.get("norm_extra") is not None:
        summaries, edge_z, nearest = result["norm_extra"]
        common_edges = pd.read_csv(
            PROJECT_ROOT / "outputs" / "stage_a" / f"common_edge_{atlas}.csv",
            keep_default_na=False,
        )
        np.savez_compressed(
            fold_dir / "normative_scores.npz",
            sample_key=np.asarray(
                result["test"]["sample_key"].astype(str).tolist(), dtype=str
            ),
            edge_uid=np.asarray(
                common_edges["edge_uid"].astype(str).tolist(), dtype=str
            ),
            summary=summaries,
            edge_z=edge_z,
            nearest_prototype=nearest,
        )
    result["fcp_crossfit_audit"].to_csv(fold_dir / "fcp_crossfit_audit.csv", index=False)
    np.savez_compressed(fold_dir / "model_state.npz", **result["model_state"])
    group = PROJECT_ROOT / "outputs" / "splits" / atlas / dataset / protocol
    cell = PROJECT_ROOT / "outputs" / "cells" / dataset / atlas
    input_paths = {
        "tasks": group / "tasks.csv",
        "nested_tasks": group / "nested_tasks.csv",
        "split_membership": group / "split_membership.csv",
        "cell_manifest": cell / "cell_manifest.json",
        "roi_manifest": cell / "roi_manifest.csv",
        "edge_manifest": cell / "edge_manifest.csv",
        "common_edge": PROJECT_ROOT / "outputs" / "stage_a" / f"common_edge_{atlas}.csv",
    }
    manifest = {
        "stage": "C", "status": "passed", "atlas_id": atlas, "dataset_id": dataset, "protocol": protocol,
        "outer_task_id": outer_id, "prediction_count": len(result["predictions"]),
        "selected_c": result["selected_c"], "meta_c": result["meta_c"],
        "subject_hashes": {
            "train": result["identity"]["train_subject_hash"],
            "validation": result["identity"]["validation_subject_hash"],
            "test": result["identity"]["test_subject_hash"],
        },
        "run_hashes": run_hashes,
        "input_hashes": {name: sha256_file(path) for name, path in input_paths.items()},
        "strict_meta_train_count": int(len(result["strict_meta_keys"])),
        "model_state_keys": sorted(result["model_state"]),
        "artifacts": {name: {"bytes": (fold_dir / name).stat().st_size, "sha256": sha256_file(fold_dir / name)} for name in ("predictions.csv", "normative_scores.npz", "model_state.npz", "fcp_crossfit_audit.csv")},
    }
    (fold_dir / "fold_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (fold_dir / "_SUCCESS").write_text("stage_c_fold_ready\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stage_c.yaml")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--atlas", default="HO112")
    parser.add_argument("--dataset", default="adhd")
    parser.add_argument("--protocol", default="LOSO")
    parser.add_argument("--outer-task")
    args = parser.parse_args()
    config, bconfig = _load_configs(args.config.resolve())
    run_hashes = _current_run_hashes(args.config.resolve())
    if not args.pilot and not args.all:
        raise ValueError("choose --pilot or --all")
    stage_b = json.loads((PROJECT_ROOT / config["stage_b_manifest"]).read_text(encoding="utf-8"))
    if stage_b.get("status") != "passed":
        raise ValueError("Stage B is not passed")
    groups = [(args.atlas, args.dataset, args.protocol)] if args.pilot else [
        (a, d, p) for a in config["atlases"] for d in config["disease_datasets"] for p in config["protocols"]
    ]
    done = 0
    for atlas, dataset, protocol in groups:
        tasks = pd.read_csv(PROJECT_ROOT / "outputs" / "splits" / atlas / dataset / protocol / "tasks.csv", keep_default_na=False)
        outer_ids = tasks.loc[tasks["task_level"] == "outer", "task_id"].astype(str).tolist()
        if args.outer_task:
            outer_ids = [args.outer_task]
        if args.pilot:
            outer_ids = outer_ids[:1]
        for outer_id in outer_ids:
            fold_dir = PROJECT_ROOT / config["storage"]["fold_pattern"].format(atlas=atlas, dataset=dataset, protocol=protocol, outer_task_id=outer_id)
            if (fold_dir / "_SUCCESS").exists() and config["execution"]["resume"]:
                if _fold_is_fresh(fold_dir, run_hashes):
                    continue
                raise FileExistsError(
                    f"stale Stage C fold must be archived before rerun: {fold_dir}"
                )
            staging = fold_dir.parent / (fold_dir.name + ".staging")
            if staging.exists(): shutil.rmtree(staging)
            try:
                result = _fit_outer(atlas, dataset, protocol, outer_id, config, bconfig)
                _write_fold(
                    result, staging, config, atlas, dataset, protocol, outer_id,
                    run_hashes,
                )
                if fold_dir.exists():
                    if not config["execution"]["overwrite"]: raise FileExistsError(fold_dir)
                    shutil.rmtree(fold_dir)
                staging.rename(fold_dir)
                done += 1
                print(f"stage C fold complete: {atlas}/{dataset}/{protocol}/{outer_id} status={result['status']}", flush=True)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
    if args.all:
        stage_dir = PROJECT_ROOT / config["storage"]["stage_dir"]
        expected_fold_dirs: list[Path] = []
        for atlas in config["atlases"]:
            for dataset in config["disease_datasets"]:
                for protocol in config["protocols"]:
                    task_path = (
                        PROJECT_ROOT / "outputs" / "splits" / atlas / dataset
                        / protocol / "tasks.csv"
                    )
                    group_tasks = pd.read_csv(task_path, keep_default_na=False)
                    outer_ids = group_tasks.loc[
                        group_tasks["task_level"] == "outer", "task_id"
                    ].astype(str)
                    expected_fold_dirs.extend(
                        PROJECT_ROOT / config["storage"]["fold_pattern"].format(
                            atlas=atlas, dataset=dataset, protocol=protocol,
                            outer_task_id=outer_id,
                        )
                        for outer_id in outer_ids
                    )
        fresh_fold_dirs = [
            path for path in expected_fold_dirs if _fold_is_fresh(path, run_hashes)
        ]
        expected = len(expected_fold_dirs)
        ready = len(fresh_fold_dirs)
        status = "passed" if ready == expected else "incomplete"
        manifest = {
            "stage": "C", "status": status, "expected_outer_folds": expected,
            "ready_outer_folds": ready, "config_path": str(args.config.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "config_sha256": sha256_file(args.config.resolve()),
            "stage_a_manifest_sha256": sha256_file(PROJECT_ROOT / config["stage_a_manifest"]),
            "stage_b_manifest_sha256": sha256_file(PROJECT_ROOT / config["stage_b_manifest"]),
            "run_hashes": run_hashes,
            "fold_manifest_hashes": {
                str((path / "fold_manifest.json").relative_to(PROJECT_ROOT)).replace("\\", "/"):
                    sha256_file(path / "fold_manifest.json")
                for path in fresh_fold_dirs
            },
        }
        (stage_dir / "stage_c_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (stage_dir / "stage_c_summary.md").write_text(
            f"# Stage C machine summary\n\nstatus: {status}\nouter folds ready: {ready}/{expected}\n",
            encoding="utf-8",
        )
        if status == "passed":
            (stage_dir / "_SUCCESS").write_text("stage_c_ready\n", encoding="utf-8")
        else:
            (stage_dir / "_SUCCESS").unlink(missing_ok=True)
    print(f"Stage C completed folds: {done}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
