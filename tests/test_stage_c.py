from __future__ import annotations

import sys
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fchn_stage_c import (  # noqa: E402
    assemble_meta_features,
    build_covariates,
    build_health_crossfit_folds,
    fit_health_anchor,
    fit_ridge_residualizer,
    high_order_fc,
    load_cell_fc,
    select_c_from_oof,
)


def test_ridge_is_train_only_and_preserves_training_feature_mean():
    age = np.arange(20, 40, dtype=float)
    sex = np.tile([0.0, 1.0], 10)
    subjects = {
        "age": age,
        "sex": sex,
        "mean_fd": np.linspace(0.05, 0.25, 20),
        "scan_length": np.full(20, 180.0),
    }
    cov, continuous = build_covariates(subjects, include_mean_fd=True)
    x = np.column_stack([3.0 * age + 2.0 * sex, -2.0 * age + sex])
    state, residual = fit_ridge_residualizer(x, cov, continuous, alpha=1.0)
    assert np.allclose(residual.mean(axis=0), x.mean(axis=0), atol=1e-10)
    shifted_cov = cov.copy()
    shifted_cov[:, 0] += 1000.0
    transformed = state.transform(x, shifted_cov)
    assert not np.allclose(transformed, residual)


def test_hofc_has_same_edge_width_and_is_finite():
    rng = np.random.default_rng(2)
    x = rng.normal(size=(4, 6))
    result = high_order_fc(x, n_roi=4)
    assert result.shape == (4, 6)
    assert np.isfinite(result).all()


def test_pooled_log_loss_c_selection_uses_smaller_c_for_tie():
    y = np.array([0, 1, 0, 1])
    predictions = {
        0.1: np.array([0.2, 0.8, 0.3, 0.7]),
        1.0: np.array([0.2, 0.8, 0.3, 0.7]),
    }
    selected, losses = select_c_from_oof(y, predictions)
    assert selected == 0.1
    assert losses[0.1] == losses[1.0]


def test_health_anchor_outputs_exactly_ten_summaries_without_prototype_id():
    rng = np.random.default_rng(4)
    health = rng.normal(size=(40, 12))
    state = fit_health_anchor(
        health, max_prototypes=8, minimum_health=10, shrinkage=0.10,
        variance_floor=1e-6, seed=7,
    )
    summaries, residual, nearest = state.transform(rng.normal(size=(5, 12)))
    assert state.n_prototypes == 4
    assert summaries.shape == (5, 10)
    assert residual.shape == (5, 12)
    assert nearest.shape == (5,)
    assert np.isfinite(summaries).all()


def test_health_anchor_rejects_fewer_than_ten_reference_subjects():
    with np.testing.assert_raises_regex(ValueError, "health reference"):
        fit_health_anchor(
            np.zeros((9, 3)), max_prototypes=8, minimum_health=10,
            shrinkage=0.10, variance_floor=1e-6, seed=1,
        )


def test_canonical_sex_rules_are_explicit_for_adhd_and_fcp():
    from fchn_stage_c import canonicalize_sex

    assert canonicalize_sex([0, 1], "adhd").tolist() == [1.0, 0.0]
    assert canonicalize_sex([1, 2], "fcp").tolist() == [0.0, 1.0]


def test_fcp_crossfit_folds_are_site_aware_and_self_excluding():
    subjects = np.array([
        ("fcp::site_a", "s1"), ("fcp::site_a", "s2"), ("fcp::site_a", "s3"),
        ("fcp::site_b", "s4"), ("fcp::site_b", "s5"), ("fcp::site_b", "s6"),
    ], dtype=[("site_id", "U20"), ("sample_key", "U20")])
    folds = build_health_crossfit_folds(subjects, n_splits=3)
    assert folds.tolist() == [0, 1, 2, 0, 1, 2]
    for fold in range(3):
        held_out = set(subjects[folds == fold]["sample_key"])
        fit = set(subjects[folds != fold]["sample_key"])
        assert held_out.isdisjoint(fit)


def test_meta_features_are_exactly_three_logits_plus_ten_summaries():
    meta = assemble_meta_features(
        [0.1, 0.2], [0.3, 0.4], [0.5, 0.6], np.zeros((2, 10))
    )
    assert meta.shape == (2, 13)


def test_stage_c_tuning_parallel_map_preserves_input_order():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    result = runner._ordered_parallel_map(lambda value: value * 2, [3, 1, 2], workers=2)
    assert result == [6, 2, 4]


def test_stage_c_config_freezes_two_tuning_workers():
    config = yaml.safe_load((PROJECT_ROOT / "config" / "stage_c.yaml").read_text(encoding="utf-8"))
    assert config["execution"]["tuning_workers"] == 2


def test_stage_c_schema_requires_execution_settings():
    schema = json.loads((PROJECT_ROOT / "config" / "stage_c.schema.json").read_text(encoding="utf-8"))
    assert "execution" in schema["required"]


def test_stage_c_identity_loaders_preserve_leading_zeroes(tmp_path):
    source = tmp_path / "source.npz"
    np.savez_compressed(
        source,
        X=np.zeros((1, 1)),
        subject_ids=np.asarray(["0050002"]),
        roi_indices=np.asarray([1, 2]),
    )
    cell = tmp_path / "outputs" / "cells" / "abide" / "HO112"
    cell.mkdir(parents=True)
    (cell / "fc_source.json").write_text(
        json.dumps({"path": str(source)}), encoding="utf-8"
    )
    pd.DataFrame({"edge_uid": ["e"], "matrix_position": [0]}).to_csv(
        cell / "edge_manifest.csv", index=False
    )
    pd.DataFrame({"sample_key": ["0050002"], "subject_id": ["0050002"]}).to_csv(
        cell / "subjects.csv", index=False
    )
    pd.DataFrame({"sample_key": ["0050002"], "qc_status": ["pass"]}).to_csv(
        cell / "qc_subject.csv", index=False
    )
    (cell / "cell_manifest.json").write_text("{}", encoding="utf-8")

    loaded = load_cell_fc(tmp_path, "abide", "HO112")
    assert loaded["subject_ids"].tolist() == ["0050002"]
    assert loaded["subjects"]["sample_key"].tolist() == ["0050002"]

    split = tmp_path / "split_membership.csv"
    pd.DataFrame({"sample_key": ["0050002"], "role": ["fit"]}).to_csv(
        split, index=False
    )
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_identity", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    assert runner._read_split_csv(split)["sample_key"].tolist() == ["0050002"]


def test_meta_oof_uses_only_common_view_identities_for_labels():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_meta", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    features = {
        "fc": pd.DataFrame([[0.1]], index=["a"]),
        "hofc": pd.DataFrame([[0.2]], index=["a"]),
        "normative": pd.DataFrame(
            [[0.3] + [0.0] * 10, [0.4] + [1.0] * 10], index=["a", "b"]
        ),
    }
    subjects = pd.DataFrame({"sample_key": ["a", "b"], "label": [0, 1]})
    meta, labels, keys = runner._assemble_oof_meta_features(features, subjects)
    assert meta.shape == (1, 13)
    assert labels.tolist() == [0]
    assert keys.tolist() == ["a"]


def test_meta_oof_rejects_duplicate_sample_identities():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_duplicate", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    features = {
        "fc": pd.DataFrame([[0.1], [0.2]], index=["a", "a"]),
        "hofc": pd.DataFrame([[0.3], [0.4]], index=["a", "a"]),
        "normative": pd.DataFrame(
            [[0.5] + [0.0] * 10, [0.6] + [1.0] * 10], index=["a", "a"]
        ),
    }
    subjects = pd.DataFrame({"sample_key": ["a"], "label": [0]})
    with np.testing.assert_raises_regex(ValueError, "unique sample_key"):
        runner._assemble_oof_meta_features(features, subjects)


def test_oof_piece_assembly_rejects_repeated_validation_identity():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_pieces", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    pieces = [
        (np.asarray(["a", "b"]), np.asarray([[0.1], [0.2]])),
        (np.asarray(["b", "c"]), np.asarray([[0.3], [0.4]])),
    ]
    with np.testing.assert_raises_regex(ValueError, "unique sample_key"):
        runner._assemble_oof_pieces(pieces)


def test_model_state_export_contains_required_numeric_states():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_state", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    classifier = SimpleNamespace(coef_=np.ones((1, 2)), intercept_=np.zeros(1))
    logistic = {
        "mean": np.zeros(2), "scale": np.ones(2), "pca": None,
        "classifier": classifier,
    }
    ridge = SimpleNamespace(
        cov_mean=np.zeros(2), cov_scale=np.ones(2), beta=np.ones((3, 2)),
        feature_mean=np.zeros(2),
    )
    anchor = SimpleNamespace(
        prototypes=np.ones((1, 2)), variances=np.ones((1, 2)),
        n_prototypes=1, variance_floor=1e-6,
    )
    models = {
        "fc": SimpleNamespace(classifier=logistic, prep={"medians": np.zeros(2), "ridge": ridge, "n_roi": 2}),
        "hofc": SimpleNamespace(classifier=logistic, prep={"medians": np.zeros(2), "ridge": ridge, "n_roi": 2}),
        "normative": SimpleNamespace(classifier=logistic, prep={
            "common_medians": np.zeros(2), "common_ridge": ridge,
            "scale_mean": np.zeros(2), "scale_scale": np.ones(2), "anchor": anchor,
        }),
    }
    result = {
        "models": models, "meta_final": logistic,
        "platt": SimpleNamespace(coef_=np.ones((1, 1)), intercept_=np.zeros(1)),
        "selected_c": {"fc": 0.1, "hofc": 0.1, "normative": 0.1}, "meta_c": 0.3,
    }
    arrays = runner._model_state_arrays(result)
    required = {
        "fc_imputer_median", "fc_ridge_beta", "fc_classifier_coef",
        "hofc_classifier_coef", "normative_common_ridge_beta",
        "normative_anchor_prototypes", "meta_classifier_coef", "platt_coef",
    }
    assert required.issubset(arrays)
    assert all(value.dtype != object for value in arrays.values())


def test_fold_freshness_requires_exact_run_hashes(tmp_path):
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_fresh", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    (tmp_path / "fold_manifest.json").write_text(
        json.dumps({"run_hashes": {"config": "abc", "source": "def"}}),
        encoding="utf-8",
    )
    (tmp_path / "_SUCCESS").write_text("stage_c_fold_ready\n", encoding="utf-8")
    assert runner._fold_is_fresh(tmp_path, {"config": "abc", "source": "def"})
    assert not runner._fold_is_fresh(tmp_path, {"config": "changed", "source": "def"})


def test_meta_prediction_excludes_nonfinite_rows_without_reordering():
    script = PROJECT_ROOT / "scripts" / "03_run_stage_c.py"
    spec = importlib.util.spec_from_file_location("stage_c_runner_finite", script)
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    model = runner.fit_logistic(
        np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]),
        np.asarray([0, 0, 1, 1]),
        1.0,
        pca_max=0,
        seed=1,
    )
    rows = np.asarray([[0.2, 0.8], [np.nan, 0.5], [0.9, 0.1]])
    logits, probabilities, valid = runner._predict_finite_rows(model, rows)
    assert valid.tolist() == [True, False, True]
    assert np.isfinite(logits[[0, 2]]).all()
    assert np.isfinite(probabilities[[0, 2]]).all()
    assert np.isnan(logits[1])
    assert np.isnan(probabilities[1])
