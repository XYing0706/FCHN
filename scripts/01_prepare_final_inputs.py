"""Build and atomically publish the 20 independent Stage A input cells."""
from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_a import (  # noqa: E402
    build_cell_edge_manifest,
    build_cell_roi_manifest,
    build_subjects_table,
    compute_cell_qc,
    json_dump,
    load_cell_inputs,
    sha256_file,
)

CELL_ARTIFACTS = [
    "subjects.csv", "roi_manifest.csv", "edge_manifest.csv", "fc_source.json",
    "ts_inventory.json", "nonfinite_mask.npz", "qc_subject.csv",
]
QC_COLUMNS = [
    "dataset_id", "sample_key", "atlas_id", "qc_status", "reason_code",
    "available_edge_count", "invalid_edge_count", "invalid_edge_ratio",
    "max_roi_invalid_ratio", "max_invalid_roi_uid", "fc_source_hash",
    "roi_manifest_hash", "edge_manifest_hash",
]
IMPLEMENTATION_FILES = [
    "config/stage_a.yaml", "config/stage_a.schema.json",
    "src/fchn_stage_a.py", "src/fchn_stage_a_metadata.py",
    "scripts/00_prepare_atlas_metadata.py", "scripts/01_prepare_final_inputs.py",
    "tests/test_stage_a.py", "tests/test_stage_a_gates.py",
]


def _relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _inventory(directory: Path, names: list[str] | None = None) -> dict[str, dict[str, object]]:
    paths = [directory / name for name in names] if names else sorted(directory.iterdir())
    return {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in paths if path.is_file()
    }


def _write_cell(config: dict, dataset: str, atlas: str, cell_dir: Path) -> dict:
    cell = load_cell_inputs(Path(config["data_root"]), dataset, atlas, config)
    subjects = build_subjects_table(cell, config)
    roi = build_cell_roi_manifest(cell, config)
    edge = build_cell_edge_manifest(cell, roi, config)
    qc = compute_cell_qc(cell, edge, config)
    cell_dir.mkdir(parents=True)

    subjects.to_csv(cell_dir / "subjects.csv", index=False)
    roi.to_csv(cell_dir / "roi_manifest.csv", index=False)
    edge.to_csv(cell_dir / "edge_manifest.csv", index=False)
    roi_hash = sha256_file(cell_dir / "roi_manifest.csv")
    edge_hash = sha256_file(cell_dir / "edge_manifest.csv")
    fc_hash = cell["source_hashes"][str(cell["fc_path"])]

    json_dump(cell_dir / "fc_source.json", {
        "path": str(cell["fc_path"].resolve()),
        "shape": list(cell["X"].shape),
        "dtype": str(cell["X"].dtype),
        "roi_indices": cell["roi_indices"].tolist(),
        "roi_indices_semantics": "zero-based atlas-local source ROI indices in FC column order",
        "allow_pickle": bool(config["storage"]["allow_pickle"]),
        "copy_fc": bool(config["storage"]["copy_fc"]),
        "sha256": fc_hash,
    })
    with np.load(cell["ts_path"], allow_pickle=False) as ts:
        arrays = {
            key: {"shape": list(np.asarray(ts[key]).shape), "dtype": str(np.asarray(ts[key]).dtype)}
            for key in ts.files if key != "X_concat"
        }
    json_dump(cell_dir / "ts_inventory.json", {
        "path": str(cell["ts_path"].resolve()),
        "sha256": cell["source_hashes"][str(cell["ts_path"])],
        "arrays": arrays,
        "scope": "descriptors only for arrays other than X_concat; no array values are copied",
    })
    np.savez_compressed(cell_dir / "nonfinite_mask.npz", mask=qc["nonfinite_mask"])

    qc_frame = pd.DataFrame({
        "dataset_id": dataset,
        "sample_key": subjects["sample_key"],
        "atlas_id": atlas,
        "qc_status": qc["qc_status"],
        "reason_code": qc["reason_codes"],
        "available_edge_count": qc["usable_edge_count"],
        "invalid_edge_count": qc["invalid_edge_count"],
        "invalid_edge_ratio": qc["subject_invalid_edge_ratio"],
        "max_roi_invalid_ratio": qc["max_roi_invalid_ratio"],
        "max_invalid_roi_uid": qc["max_invalid_roi_uid"],
        "fc_source_hash": fc_hash,
        "roi_manifest_hash": roi_hash,
        "edge_manifest_hash": edge_hash,
    }, columns=QC_COLUMNS)
    qc_frame.to_csv(cell_dir / "qc_subject.csv", index=False)

    demographic_path = Path(subjects["demographic_source_file"].iloc[0])
    source_hashes = dict(cell["source_hashes"])
    source_hashes[str(demographic_path)] = sha256_file(demographic_path)
    source_files = {
        "fc": str(cell["fc_path"].resolve()),
        "ts": str(cell["ts_path"].resolve()),
        "manifest": str(cell["manifest_path"].resolve()),
        "roi_mask": str(cell["mask_path"].resolve()),
        "demographic": str(demographic_path),
    }
    payload = {
        "stage": "A", "status": "passed", "dataset_id": dataset, "atlas_id": atlas,
        "subject_count": int(len(subjects)),
        "theoretical_roi_count": int(cell["theoretical_roi_count"]),
        "available_roi_count": int(len(cell["roi_indices"])),
        "theoretical_edge_count": int(len(edge)),
        "available_edge_count": int(cell["X"].shape[1]),
        "fc_shape": list(cell["X"].shape), "fc_dtype": str(cell["X"].dtype),
        "source_files": source_files, "source_hashes": source_hashes,
        "identity_hashes": {"roi_manifest_sha256": roi_hash, "edge_manifest_sha256": edge_hash},
        "qc_summary": {
            "pass_count": int((qc_frame["qc_status"] == "pass").sum()),
            "fail_count": int((qc_frame["qc_status"] == "fail").sum()),
            "invalid_value_count": int(qc["invalid_value_count"]),
            "thresholds": config["qc"],
        },
        "artifacts": _inventory(cell_dir, CELL_ARTIFACTS),
    }
    json_dump(cell_dir / "cell_manifest.json", payload)
    (cell_dir / "_SUCCESS").write_text("stage_a_cell_ready\n", encoding="utf-8")
    return payload


def _write_common_spaces(config: dict, cells_root: Path, stage_dir: Path) -> dict[str, dict[str, int]]:
    counts = {}
    metadata_dir = PROJECT_ROOT / "config" / "atlas_metadata"
    for atlas in config["atlases"]:
        available = []
        for dataset in config["datasets"]:
            roi = pd.read_csv(cells_root / dataset / atlas / "roi_manifest.csv")
            available.append(set(roi.loc[roi["structural_status"] == "available", "roi_uid"]))
        common = set.intersection(*available)
        master_roi = pd.read_csv(metadata_dir / f"master_{atlas}.csv")
        common_roi = master_roi.loc[master_roi["roi_uid"].isin(common)].copy()
        common_roi["common_matrix_position"] = np.arange(len(common_roi))
        master_edge = pd.read_csv(metadata_dir / f"master_edges_{atlas}.csv")
        common_edge = master_edge.loc[
            master_edge["roi_uid_i"].isin(common) & master_edge["roi_uid_j"].isin(common)
        ].copy()
        common_edge["common_matrix_position"] = np.arange(len(common_edge))
        common_roi.to_csv(stage_dir / f"common_roi_{atlas}.csv", index=False)
        common_edge.to_csv(stage_dir / f"common_edge_{atlas}.csv", index=False)
        counts[atlas] = {"roi_count": len(common_roi), "edge_count": len(common_edge)}
    return counts


def _write_input_inventory(records: list[dict], cells_root: Path, stage_dir: Path) -> None:
    rows = []
    for record in records:
        dataset, atlas = record["dataset_id"], record["atlas_id"]
        files, hashes = record["source_files"], record["source_hashes"]
        cell_manifest = cells_root / dataset / atlas / "cell_manifest.json"
        rows.append({
            "dataset_id": dataset, "atlas_id": atlas,
            "subject_count": record["subject_count"],
            "theoretical_roi_count": record["theoretical_roi_count"],
            "available_roi_count": record["available_roi_count"],
            "theoretical_edge_count": record["theoretical_edge_count"],
            "available_edge_count": record["available_edge_count"],
            "fc_shape": "x".join(map(str, record["fc_shape"])), "fc_dtype": record["fc_dtype"],
            **{f"{kind}_source_path": path for kind, path in files.items()},
            **{f"{kind}_source_sha256": hashes[path] for kind, path in files.items()},
            "cell_manifest_path": f"outputs/cells/{dataset}/{atlas}/cell_manifest.json",
            "cell_manifest_sha256": sha256_file(cell_manifest),
        })
    pd.DataFrame(rows).to_csv(stage_dir / "input_inventory.csv", index=False)


def _write_atlas_sources(config: dict, stage_dir: Path) -> None:
    metadata_dir = PROJECT_ROOT / "config" / "atlas_metadata"
    source_manifest = metadata_dir / "sources" / "source_manifest.json"
    rows = []
    for atlas in config["atlases"]:
        roi_path = metadata_dir / f"master_{atlas}.csv"
        edge_path = metadata_dir / f"master_edges_{atlas}.csv"
        master = pd.read_csv(roi_path)
        rows.append({
            "atlas_id": atlas,
            "master_roi_path": _relative(roi_path), "master_roi_sha256": sha256_file(roi_path),
            "master_edge_path": _relative(edge_path), "master_edge_sha256": sha256_file(edge_path),
            "metadata_source": ";".join(master["metadata_source"].dropna().astype(str).unique()),
            "metadata_version": ";".join(master["metadata_version"].dropna().astype(str).unique()),
            "metadata_license": ";".join(master["metadata_license"].dropna().astype(str).unique()),
            "metadata_source_sha256": ";".join(master["metadata_sha256"].dropna().astype(str).unique()),
            "source_snapshot_manifest_path": _relative(source_manifest),
            "source_snapshot_manifest_sha256": sha256_file(source_manifest),
        })
    pd.DataFrame(rows).to_csv(stage_dir / "atlas_metadata_sources.csv", index=False)


def _write_stage(config: dict, staging_root: Path, config_path: Path) -> None:
    cells_root, stage_dir = staging_root / "cells", staging_root / "stage_a"
    stage_dir.mkdir(parents=True)
    records = []
    for dataset in config["datasets"]:
        for atlas in config["atlases"]:
            record = _write_cell(config, dataset, atlas, cells_root / dataset / atlas)
            records.append(record)
            print(
                f"prepared {dataset}/{atlas}: n={record['subject_count']}, "
                f"roi={record['available_roi_count']}, edge={record['available_edge_count']}, "
                f"qc_fail={record['qc_summary']['fail_count']}",
                flush=True,
            )
    if len(records) != 20:
        raise ValueError(f"Stage A requires 20 cells, got {len(records)}")

    common_counts = _write_common_spaces(config, cells_root, stage_dir)
    _write_input_inventory(records, cells_root, stage_dir)
    _write_atlas_sources(config, stage_dir)
    lines = [
        "# Stage A machine summary", "", "status: passed", f"cells: {len(records)}/20", "",
        "| dataset | atlas | subjects | available ROI | available edges | QC fail |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| {record['dataset_id']} | {record['atlas_id']} | {record['subject_count']} | "
            f"{record['available_roi_count']} | {record['available_edge_count']} | "
            f"{record['qc_summary']['fail_count']} |"
        )
    (stage_dir / "stage_a_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cells = []
    for record in records:
        dataset, atlas = record["dataset_id"], record["atlas_id"]
        manifest_path = cells_root / dataset / atlas / "cell_manifest.json"
        cells.append({
            "dataset_id": dataset, "atlas_id": atlas,
            "cell_manifest_path": f"outputs/cells/{dataset}/{atlas}/cell_manifest.json",
            "cell_manifest_sha256": sha256_file(manifest_path),
        })
    json_dump(stage_dir / "stage_a_manifest.json", {
        "stage": "A", "status": "passed", "cell_count": len(cells), "cells": cells,
        "config_path": _relative(config_path), "config_sha256": sha256_file(config_path),
        "implementation_files": {
            relative_path: sha256_file(PROJECT_ROOT / relative_path)
            for relative_path in IMPLEMENTATION_FILES
        },
        "common_spaces": common_counts, "artifacts": _inventory(stage_dir),
    })
    (stage_dir / "_SUCCESS").write_text("stage_a_ready\n", encoding="utf-8")


def _publish(staging_root: Path, output_root: Path, replace_existing: bool) -> Path | None:
    final_cells, final_stage = output_root / "cells", output_root / "stage_a"
    existing = [path for path in (final_cells, final_stage) if path.exists()]
    if existing and not replace_existing:
        raise FileExistsError("Stage A outputs exist; rerun with --replace-existing to archive and replace them")
    archive_dir = None
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = output_root / "archive" / f"stage_a_{stamp}_{uuid.uuid4().hex[:8]}"
        archive_dir.mkdir(parents=True)
        archive_info = {"created_utc": stamp, "replaced": []}
        for path in existing:
            old_manifest = path / "stage_a_manifest.json" if path.name == "stage_a" else None
            archive_info["replaced"].append({
                "original_path": str(path.resolve()),
                "archive_path": str((archive_dir / path.name).resolve()),
                "stage_manifest_sha256": sha256_file(old_manifest) if old_manifest and old_manifest.is_file() else "",
            })
            path.rename(archive_dir / path.name)
        json_dump(archive_dir / "archive_manifest.json", archive_info)
    try:
        (staging_root / "cells").rename(final_cells)
        (staging_root / "stage_a").rename(final_stage)
        staging_root.rmdir()
    except Exception:
        if final_cells.exists() and not (staging_root / "cells").exists():
            final_cells.rename(staging_root / "cells")
        if archive_dir:
            for name in ("cells", "stage_a"):
                archived = archive_dir / name
                if archived.exists() and not (output_root / name).exists():
                    archived.rename(output_root / name)
        raise
    return archive_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stage_a.yaml")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if args.data_root is not None:
        config["data_root"] = str(args.data_root.resolve())
    output_root = Path(config["project_root"]) / "outputs"
    final_exists = (output_root / "cells").exists() or (output_root / "stage_a").exists()
    if final_exists and not args.replace_existing:
        raise FileExistsError("Stage A outputs exist; use --replace-existing for recoverable replacement")
    staging_root = output_root / ".staging" / f"stage_a_{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True)
    try:
        _write_stage(config, staging_root, config_path)
        archive_dir = _publish(staging_root, output_root, args.replace_existing)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    print("Stage A published: 20/20 cells", flush=True)
    if archive_dir:
        print(f"Previous Stage A archived at: {archive_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
