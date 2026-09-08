from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FOLD = (
    PROJECT_ROOT / "outputs" / "stage_c" / "folds" / "HO112" / "adhd"
    / "LOSO" / "HO112__adhd__LOSO__outer000__main"
)
FOLD_WITH_MISSING_COVARIATE = (
    PROJECT_ROOT / "outputs" / "stage_c" / "folds" / "HO112" / "adhd"
    / "LOSO" / "HO112__adhd__LOSO__outer003__main"
)
ABIDE_IDENTITY_FOLD = (
    PROJECT_ROOT / "outputs" / "stage_c" / "folds" / "HO112" / "abide"
    / "LOSO" / "HO112__abide__LOSO__outer000__main"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_real_stage_c_pilot_round_trip_gate():
    assert (FOLD / "_SUCCESS").read_text(encoding="utf-8") == "stage_c_fold_ready\n"
    manifest = json.loads((FOLD / "fold_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "passed"
    for name, metadata in manifest["artifacts"].items():
        path = FOLD / name
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]
    for name, digest in manifest["input_hashes"].items():
        relative = {
            "tasks": "outputs/splits/HO112/adhd/LOSO/tasks.csv",
            "nested_tasks": "outputs/splits/HO112/adhd/LOSO/nested_tasks.csv",
            "split_membership": "outputs/splits/HO112/adhd/LOSO/split_membership.csv",
            "cell_manifest": "outputs/cells/adhd/HO112/cell_manifest.json",
            "roi_manifest": "outputs/cells/adhd/HO112/roi_manifest.csv",
            "edge_manifest": "outputs/cells/adhd/HO112/edge_manifest.csv",
            "common_edge": "outputs/stage_a/common_edge_HO112.csv",
        }[name]
        assert _sha256(PROJECT_ROOT / relative) == digest

    predictions = pd.read_csv(FOLD / "predictions.csv", keep_default_na=False)
    required = {
        "sample_key", "task_id", "outer_fold", "split_path", "view",
        "variant", "prediction_level", "prediction", "logit", "probability", "raw_probability",
        "true_label", "selected_c", "meta_c", "train_subject_hash",
        "selected_c_fc", "selected_c_hofc", "selected_c_normative",
        "validation_subject_hash", "test_subject_hash", "roi_manifest_hash",
        "edge_manifest_hash", "imputer_state_hash", "ridge_state_hash",
        "scaler_pca_state_hash", "normative_state_hash", "task_status",
        "reason_code",
    }
    assert required.issubset(predictions.columns)
    assert predictions.groupby("view").size().to_dict() == {
        "fc": 245, "full_fchn": 245, "hofc": 245, "normative": 245,
    }
    assert predictions.groupby("view")["sample_key"].nunique().eq(245).all()
    assert np.isfinite(predictions[["logit", "probability", "raw_probability"]]).all().all()
    assert predictions["probability"].between(0, 1).all()
    assert predictions["task_status"].eq("passed").all()
    assert predictions["reason_code"].eq("").all()
    subjects = pd.read_csv(
        PROJECT_ROOT / "outputs" / "cells" / "adhd" / "HO112" / "subjects.csv",
        keep_default_na=False,
    ).set_index("sample_key")
    unique_predictions = predictions.drop_duplicates("sample_key").set_index("sample_key")
    expected_labels = subjects.loc[unique_predictions.index, "label"].astype(int)
    assert unique_predictions["true_label"].astype(int).equals(expected_labels)

    scores = np.load(FOLD / "normative_scores.npz", allow_pickle=False)
    common_edges = pd.read_csv(
        PROJECT_ROOT / "outputs" / "stage_a" / "common_edge_HO112.csv",
        keep_default_na=False,
    )
    assert {"sample_key", "edge_uid", "summary", "edge_z", "nearest_prototype"}.issubset(scores.files)
    assert scores["sample_key"].astype(str).tolist() == predictions.loc[
        predictions["view"] == "normative", "sample_key"
    ].astype(str).tolist()
    assert scores["edge_uid"].astype(str).tolist() == common_edges["edge_uid"].astype(str).tolist()
    assert scores["summary"].shape == (245, 10)
    assert scores["edge_z"].shape == (245, len(common_edges))
    assert np.isfinite(scores["summary"]).all()
    assert np.isfinite(scores["edge_z"]).all()

    state = np.load(FOLD / "model_state.npz", allow_pickle=False)
    required_state = {
        "fc_imputer_median", "fc_ridge_beta", "fc_classifier_coef",
        "hofc_classifier_coef", "normative_common_ridge_beta",
        "normative_anchor_prototypes", "meta_classifier_coef", "platt_coef",
    }
    assert required_state.issubset(state.files)
    assert all(state[name].dtype != object for name in state.files)

    audit = pd.read_csv(FOLD / "fcp_crossfit_audit.csv", keep_default_na=False)
    fcp_subjects = pd.read_csv(
        PROJECT_ROOT / "outputs" / "cells" / "fcp" / "HO112" / "subjects.csv",
        keep_default_na=False,
    )
    assert len(audit) == len(fcp_subjects) == audit["sample_key"].nunique()
    assert audit["self_excluded"].astype(str).str.lower().eq("true").all()
    assert audit["score_finite"].astype(str).str.lower().eq("true").all()

    spec = importlib.util.spec_from_file_location(
        "stage_c_runner_gate", PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    )
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    assert runner._fold_is_fresh(
        FOLD, runner._current_run_hashes(PROJECT_ROOT / "config" / "stage_c.yaml")
    )


def test_outer003_preserves_missing_covariate_identity_as_ineligible():
    fold = FOLD_WITH_MISSING_COVARIATE
    assert (fold / "_SUCCESS").read_text(encoding="utf-8") == "stage_c_fold_ready\n"
    predictions = pd.read_csv(fold / "predictions.csv", keep_default_na=False)
    assert len(predictions) == 257 * 4
    assert predictions.groupby(["task_status", "reason_code"]).size().to_dict() == {
        ("ineligible", "MISSING_REQUIRED_COVARIATE"): 4,
        ("passed", ""): 256 * 4,
    }
    ineligible = predictions["task_status"].eq("ineligible")
    assert predictions.loc[ineligible, "sample_key"].nunique() == 1
    assert predictions.loc[ineligible, "view"].nunique() == 4
    numeric = predictions[["logit", "probability", "raw_probability"]].apply(
        pd.to_numeric, errors="coerce"
    )
    assert np.isfinite(numeric.loc[~ineligible].to_numpy()).all()
    assert numeric.loc[ineligible].isna().all().all()
    assert predictions.loc[ineligible, "prediction"].eq("").all()
    scores = np.load(fold / "normative_scores.npz", allow_pickle=False)
    score_finite = np.isfinite(scores["summary"]).all(axis=1)
    assert scores["sample_key"].shape == (257,)
    assert scores["summary"].shape == (257, 10)
    assert int(score_finite.sum()) == 256
    assert int((~score_finite).sum()) == 1
    manifest = json.loads((fold / "fold_manifest.json").read_text(encoding="utf-8"))
    for name, metadata in manifest["artifacts"].items():
        path = fold / name
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]
    spec = importlib.util.spec_from_file_location(
        "stage_c_runner_outer003", PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    )
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    assert runner._fold_is_fresh(
        fold, runner._current_run_hashes(PROJECT_ROOT / "config" / "stage_c.yaml")
    )


def test_abide_fold_preserves_zero_padded_identity_end_to_end():
    fold = ABIDE_IDENTITY_FOLD
    assert (fold / "_SUCCESS").read_text(encoding="utf-8") == "stage_c_fold_ready\n"
    manifest = json.loads((fold / "fold_manifest.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(
        fold / "predictions.csv", keep_default_na=False, dtype={"sample_key": str}
    )
    membership = pd.read_csv(
        PROJECT_ROOT / "outputs" / "splits" / "HO112" / "abide" / "LOSO"
        / "split_membership.csv",
        keep_default_na=False,
        dtype={"sample_key": str},
    )
    test_keys = set(membership.loc[
        (membership["task_id"] == "HO112__abide__LOSO__outer000__main")
        & (membership["role"] == "test"),
        "sample_key",
    ])
    assert len(predictions) == len(test_keys) * 4
    assert predictions["sample_key"].nunique() == len(test_keys)
    assert set(predictions["sample_key"]) == test_keys
    assert predictions["sample_key"].str.len().eq(7).all()
    assert predictions["sample_key"].str.startswith("0").all()
    assert predictions["task_status"].eq("passed").all()
    scores = np.load(fold / "normative_scores.npz", allow_pickle=False)
    assert scores["sample_key"].shape == (len(test_keys),)
    assert scores["summary"].shape == (len(test_keys), 10)
    assert scores["edge_z"].shape == (len(test_keys), 6105)
    assert set(scores["sample_key"].astype(str)) == test_keys
    for name, metadata in manifest["artifacts"].items():
        path = fold / name
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]
    spec = importlib.util.spec_from_file_location(
        "stage_c_runner_abide_identity", PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    )
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    assert runner._fold_is_fresh(
        fold, runner._current_run_hashes(PROJECT_ROOT / "config" / "stage_c.yaml")
    )
