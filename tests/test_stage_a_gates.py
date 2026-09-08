import json
from pathlib import Path

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((PROJECT_ROOT / "config" / "stage_a.yaml").read_text(encoding="utf-8"))
METADATA_DIR = PROJECT_ROOT / "config" / "atlas_metadata"
STAGE_DIR = PROJECT_ROOT / "outputs" / "stage_a"

ROI_COLUMNS = [
    "atlas_id", "roi_uid", "roi_original_index", "global_original_column",
    "roi_name", "roi_label", "description", "hemisphere", "network",
    "x", "y", "z", "metadata_source", "metadata_version",
    "metadata_license", "metadata_sha256",
]
EDGE_COLUMNS = [
    "atlas_id", "edge_uid", "roi_uid_i", "roi_uid_j",
    "roi_original_index_i", "roi_original_index_j",
    "global_original_column_i", "global_original_column_j",
]
SUBJECT_COLUMNS = [
    "sample_key", "dataset_id", "subject_id", "site_id", "label", "age",
    "sex", "scan_length", "mean_fd", "source_file", "source_row_hash",
    "demographic_source_file", "demographic_source_row_hash",
    "mean_fd_source", "sex_encoding_rule",
]
QC_COLUMNS = [
    "dataset_id", "sample_key", "atlas_id", "qc_status", "reason_code",
    "available_edge_count", "invalid_edge_count", "invalid_edge_ratio",
    "max_roi_invalid_ratio", "max_invalid_roi_uid", "fc_source_hash",
    "roi_manifest_hash", "edge_manifest_hash",
]


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_authoritative_atlas_masters_and_edges_are_complete():
    for atlas in CONFIG["atlases"]:
        count = CONFIG["theoretical_roi_count"][atlas]
        roi = pd.read_csv(METADATA_DIR / f"master_{atlas}.csv")
        edge = pd.read_csv(METADATA_DIR / f"master_edges_{atlas}.csv")
        assert roi.columns.tolist() == ROI_COLUMNS
        assert edge.columns.tolist() == EDGE_COLUMNS
        assert len(roi) == count
        assert len(edge) == count * (count - 1) // 2
        assert roi["roi_uid"].is_unique and edge["edge_uid"].is_unique
        expected_roi = [f"{atlas.lower()}:roi{i:03d}" for i in range(1, count + 1)]
        assert roi["roi_uid"].tolist() == expected_roi
        first = edge.iloc[0]
        assert first["edge_uid"] == f"{atlas.lower()}:roi001--roi002"


def test_atlas_source_snapshot_hashes_are_current():
    source_manifest = json.loads(
        (METADATA_DIR / "sources" / "source_manifest.json").read_text(encoding="utf-8")
    )
    assert source_manifest["access_date"] == "2026-08-26"
    assert set(source_manifest["atlases"]) == set(CONFIG["atlases"])
    for item in source_manifest["files"]:
        path = METADATA_DIR / "sources" / item["relative_path"]
        assert path.is_file()
        assert _sha256(path) == item["sha256"]


def test_aal_hemisphere_follows_official_label_suffix():
    aal = pd.read_csv(METADATA_DIR / "master_AAL116.csv")
    for row in aal.itertuples():
        expected = "L" if row.roi_name.endswith("_L") else "R" if row.roi_name.endswith("_R") else "M"
        assert row.hemisphere == expected


def test_common_spaces_are_exact_structural_intersections():
    for atlas in CONFIG["atlases"]:
        common_roi = pd.read_csv(STAGE_DIR / f"common_roi_{atlas}.csv")
        common_edge = pd.read_csv(STAGE_DIR / f"common_edge_{atlas}.csv")
        available_sets = []
        for dataset in CONFIG["datasets"]:
            cell_roi = pd.read_csv(PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "roi_manifest.csv")
            available_sets.append(set(cell_roi.loc[cell_roi["structural_status"] == "available", "roi_uid"]))
        expected = set.intersection(*available_sets)
        master = pd.read_csv(METADATA_DIR / f"master_{atlas}.csv")
        expected_order = master.loc[master["roi_uid"].isin(expected), "roi_uid"].tolist()
        assert common_roi["roi_uid"].tolist() == expected_order
        assert len(common_edge) == len(expected) * (len(expected) - 1) // 2
        assert set(common_edge["roi_uid_i"]).union(common_edge["roi_uid_j"]) == expected


def test_subjects_have_canonical_identity_and_demographic_provenance():
    for dataset in CONFIG["datasets"]:
        subjects = pd.read_csv(
            PROJECT_ROOT / "outputs" / "cells" / dataset / CONFIG["atlases"][0] / "subjects.csv",
            dtype={"sample_key": "string", "subject_id": "string", "site_id": "string"},
        )
        assert subjects.columns.tolist() == SUBJECT_COLUMNS
        assert subjects["sample_key"].tolist() == subjects["subject_id"].tolist()
        assert subjects["dataset_id"].eq(dataset).all()
        assert subjects["site_id"].notna().all()
        assert subjects["source_row_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
        assert subjects["demographic_source_row_hash"].str.fullmatch(r"[0-9a-f]{64}").all()

    mdd = pd.read_csv(PROJECT_ROOT / "outputs" / "cells" / "mdd" / "HO112" / "subjects.csv")
    fcp = pd.read_csv(PROJECT_ROOT / "outputs" / "cells" / "fcp" / "HO112" / "subjects.csv")
    assert mdd["age"].notna().all() and mdd["sex"].notna().all()
    assert fcp["sex"].isna().sum() == 0 and fcp["mean_fd"].isna().sum() == 176


def test_qc_has_per_subject_metrics_and_identity_hashes():
    for dataset in CONFIG["datasets"]:
        for atlas in CONFIG["atlases"]:
            qc = pd.read_csv(PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "qc_subject.csv")
            assert qc.columns.tolist() == QC_COLUMNS
            assert set(qc["qc_status"]).issubset({"pass", "fail"})
            assert qc["available_edge_count"].eq(qc["available_edge_count"].iloc[0]).all()
            for column in ["fc_source_hash", "roi_manifest_hash", "edge_manifest_hash"]:
                assert qc[column].str.fullmatch(r"[0-9a-f]{64}").all()


def test_stage_manifest_references_current_cell_manifests():
    stage = json.loads((STAGE_DIR / "stage_a_manifest.json").read_text(encoding="utf-8"))
    assert stage["status"] == "passed" and stage["cell_count"] == 20
    for relative_path, digest in stage["implementation_files"].items():
        assert _sha256(PROJECT_ROOT / relative_path) == digest
    assert len(stage["cells"]) == 20
    for item in stage["cells"]:
        path = PROJECT_ROOT / item["cell_manifest_path"]
        assert _sha256(path) == item["cell_manifest_sha256"]
    assert (STAGE_DIR / "input_inventory.csv").is_file()
    assert (STAGE_DIR / "atlas_metadata_sources.csv").is_file()
    assert (STAGE_DIR / "_SUCCESS").read_text(encoding="utf-8").strip() == "stage_a_ready"


def test_each_cell_manifest_audits_all_sources_and_artifacts():
    required_artifacts = {
        "subjects.csv", "roi_manifest.csv", "edge_manifest.csv", "fc_source.json",
        "ts_inventory.json", "nonfinite_mask.npz", "qc_subject.csv",
    }
    stage = json.loads((STAGE_DIR / "stage_a_manifest.json").read_text(encoding="utf-8"))
    for item in stage["cells"]:
        cell_manifest_path = PROJECT_ROOT / item["cell_manifest_path"]
        cell_dir = cell_manifest_path.parent
        cell = json.loads(cell_manifest_path.read_text(encoding="utf-8"))
        assert cell["dataset_id"] == cell_dir.parent.name
        assert cell["atlas_id"] == cell_dir.name
        assert len(cell["source_hashes"]) == 5
        for source_path, source_hash in cell["source_hashes"].items():
            assert _sha256(Path(source_path)) == source_hash
        assert set(cell["artifacts"]) == required_artifacts
        for name, descriptor in cell["artifacts"].items():
            artifact = cell_dir / name
            assert artifact.stat().st_size == descriptor["bytes"]
            assert _sha256(artifact) == descriptor["sha256"]
        fc_source = json.loads((cell_dir / "fc_source.json").read_text(encoding="utf-8"))
        assert fc_source["shape"][0] == cell["subject_count"]
        assert fc_source["shape"][1] == cell["available_edge_count"]
        assert _sha256(Path(fc_source["path"])) == fc_source["sha256"]
        assert (cell_dir / "_SUCCESS").read_text(encoding="utf-8").strip() == "stage_a_cell_ready"
