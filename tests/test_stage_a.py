from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_CONFIG = PROJECT_ROOT / "config" / "stage_a.yaml"

import sys
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_a import _number, _row_hash, build_cell_edge_manifest, build_cell_roi_manifest, compute_cell_qc, load_cell_inputs


def test_stage_a_config_has_20_cells_and_frozen_thresholds():
    config = yaml.safe_load(TEST_CONFIG.read_text(encoding="utf-8"))
    assert len(config["datasets"]) == 5
    assert len(config["atlases"]) == 4
    assert config["qc"]["subject_invalid_edge_ratio"] == 0.05
    assert config["qc"]["roi_incident_invalid_ratio"] == 0.30
    assert config["storage"]["unit_pattern"] == "outputs/cells/{dataset}/{atlas}"
    assert config["identity"]["sample_key_rule"] == "subject_id"
    assert config["identity"]["matrix_position_base"] == 0
    assert config["units"]["age"] == "years"


def test_source_row_hash_ignores_internal_derived_fields():
    source = {"ID": "S001", "Age": 20, "Sex": 1}
    enriched = dict(source, _expected_label=1, _sheet="MDD")
    assert _row_hash(source) == _row_hash(enriched)


def test_number_treats_source_empty_list_marker_as_missing():
    assert _number("[]") is None


CONFIG = yaml.safe_load(TEST_CONFIG.read_text(encoding="utf-8"))
DATA_ROOT = Path(CONFIG["data_root"])


def test_real_cell_inputs_have_edge_shape_and_identity():
    for dataset in CONFIG["datasets"]:
        for atlas in CONFIG["atlases"]:
            cell = load_cell_inputs(DATA_ROOT, dataset, atlas, CONFIG)
            assert cell["X"].ndim == 2
            assert cell["X"].shape[1] == len(cell["roi_indices"]) * (len(cell["roi_indices"]) - 1) // 2
            assert np.array_equal(cell["subject_ids"], cell["manifest"]["subject_id"].astype(str).to_numpy())


def test_missing_roi_keeps_original_identity():
    cell = {
        "atlas": "AAL116",
        "roi_indices": np.array([0, 2], dtype=int),
        "mask": pd.DataFrame({"roi_local_idx": [0, 1, 2], "kept": [1, 0, 1], "valid_rate": [1.0, 0.0, 1.0]}),
    }
    rows = build_cell_roi_manifest(cell, CONFIG)
    row = rows.loc[rows["roi_original_index"] == 2].iloc[0]
    assert row["roi_uid"] == "aal116:roi002"
    assert row["roi_name"] == "Precentral_R"
    assert str(row["roi_label"]) == "2"
    assert row["global_original_column"] == 2
    assert row["structural_status"] == "structural_unavailable"
    assert pd.isna(row["matrix_position"])


def test_edge_manifest_preserves_structural_edges_and_matrix_positions():
    cell = {"atlas": "AAL116", "roi_indices": np.array([0, 2]), "X": np.zeros((1, 1)), "mask": pd.DataFrame({"roi_local_idx": [0, 1, 2], "kept": [1, 0, 1], "valid_rate": [1.0, 0.0, 1.0]})}
    roi = build_cell_roi_manifest(cell, CONFIG)
    edge = build_cell_edge_manifest(cell, roi, CONFIG)
    assert len(edge) == 116 * 115 // 2
    assert edge.iloc[0]["edge_uid"] == "aal116:roi001--roi002"
    assert edge.loc[(edge["roi_original_index_i"] == 1) & (edge["roi_original_index_j"] == 2), "structural_status"].iloc[0] == "structural_unavailable"
    available = edge.loc[edge["structural_status"] == "available", "matrix_position"].to_numpy()
    assert np.array_equal(available, np.arange(1))


def test_qc_uses_threshold_boundaries_and_excludes_structural_edges():
    cell = {"atlas": "AAL116", "roi_indices": np.array([0, 2]), "X": np.array([[1.0], [np.nan]], dtype=float), "mask": pd.DataFrame({"roi_local_idx": [0, 1, 2], "kept": [1, 0, 1], "valid_rate": [1.0, 0.0, 1.0]})}
    roi = build_cell_roi_manifest(cell, CONFIG)
    edge = build_cell_edge_manifest(cell, roi, CONFIG)
    qc = compute_cell_qc(cell, edge, CONFIG)
    assert qc["bad_subject_count"] == 1
    assert qc["subject_invalid_edge_ratio"][1] == 1.0
    assert qc["usable_edge_count"] == 1


def test_qc_excludes_subject_for_roi_incident_threshold():
    cfg = dict(CONFIG)
    cfg["qc"] = dict(CONFIG["qc"], subject_invalid_edge_ratio=1.0, roi_incident_invalid_ratio=0.30)
    cell = {"atlas": "AAL116", "roi_indices": np.array([0, 1, 2]), "X": np.array([[np.nan, 1.0, 1.0]], dtype=float), "mask": pd.DataFrame({"roi_local_idx": [0, 1, 2], "kept": [1, 1, 1], "valid_rate": [1.0, 1.0, 1.0]})}
    roi = build_cell_roi_manifest(cell, cfg)
    edge = build_cell_edge_manifest(cell, roi, cfg)
    qc = compute_cell_qc(cell, edge, cfg)
    assert qc["qc_status"] == ["fail"]
    assert qc["reason_codes"] == ["ROI_INCIDENT_INVALID_GE_30PCT"]
    assert qc["invalid_edge_count"] == [1]
    assert qc["max_roi_invalid_ratio"] == [0.5]
    assert qc["max_invalid_roi_uid"] == ["aal116:roi001"]


def test_qc_roi_incident_denominator_is_edge_count_not_subject_count():
    cfg = dict(CONFIG)
    cfg["qc"] = dict(CONFIG["qc"], subject_invalid_edge_ratio=1.0, roi_incident_invalid_ratio=0.30)
    cell = {
        "atlas": "AAL116",
        "roi_indices": np.array([0, 1, 2]),
        "X": np.array([[np.nan, 1.0, 1.0], [np.nan, 1.0, 1.0]], dtype=float),
        "mask": pd.DataFrame({"roi_local_idx": [0, 1, 2], "kept": [1, 1, 1], "valid_rate": [1.0, 1.0, 1.0]}),
    }
    roi = build_cell_roi_manifest(cell, cfg)
    edge = build_cell_edge_manifest(cell, roi, cfg)
    qc = compute_cell_qc(cell, edge, cfg)
    assert qc["max_roi_invalid_ratio"] == [0.5, 0.5]
    assert qc["qc_status"] == ["fail", "fail"]
