"""Build and atomically publish the 32 independent Stage B split groups."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_b import build_nested_task_plan, build_split_group  # noqa: E402


IMPLEMENTATION_FILES = [
    "config/stage_b.yaml",
    "config/stage_b.schema.json",
    "src/fchn_stage_b.py",
    "scripts/02_prepare_split_plans.py",
    "tests/test_stage_b.py",
    "tests/test_stage_b_gates.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def inventory(directory: Path, names: list[str]) -> dict[str, dict[str, object]]:
    return {
        name: {
            "bytes": (directory / name).stat().st_size,
            "sha256": sha256_file(directory / name),
        }
        for name in names
    }


def validate_stage_a(config: dict) -> tuple[Path, dict, dict[tuple[str, str], dict]]:
    manifest_path = PROJECT_ROOT / config["stage_a_manifest"]
    success_path = PROJECT_ROOT / config["stage_a_success"]
    if success_path.read_text(encoding="utf-8") != "stage_a_ready\n":
        raise ValueError("Stage A _SUCCESS is absent or invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != "A" or manifest.get("status") != "passed":
        raise ValueError("Stage A manifest is not passed")
    cells = {}
    for record in manifest["cells"]:
        key = (record["dataset_id"], record["atlas_id"])
        cell_manifest_path = PROJECT_ROOT / record["cell_manifest_path"]
        if sha256_file(cell_manifest_path) != record["cell_manifest_sha256"]:
            raise ValueError(f"stale Stage A cell manifest: {key[0]}/{key[1]}")
        cells[key] = record
    expected = {
        (dataset, atlas)
        for dataset in config["disease_datasets"]
        for atlas in config["atlases"]
    }
    if not expected.issubset(cells):
        raise ValueError("Stage A does not contain all 16 disease dataset-atlas cells")
    return manifest_path, manifest, cells


def load_current_cell(
    dataset: str,
    atlas: str,
    cell_record: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, str]]]:
    cell_manifest_path = PROJECT_ROOT / cell_record["cell_manifest_path"]
    cell_manifest = json.loads(cell_manifest_path.read_text(encoding="utf-8"))
    cell_dir = cell_manifest_path.parent
    if (cell_dir / "_SUCCESS").read_text(encoding="utf-8") != "stage_a_cell_ready\n":
        raise ValueError(f"invalid Stage A cell _SUCCESS: {dataset}/{atlas}")
    subjects_path = cell_dir / "subjects.csv"
    qc_path = cell_dir / "qc_subject.csv"
    for name, path in (("subjects.csv", subjects_path), ("qc_subject.csv", qc_path)):
        expected_hash = cell_manifest["artifacts"][name]["sha256"]
        if sha256_file(path) != expected_hash:
            raise ValueError(f"stale Stage A artifact: {dataset}/{atlas}/{name}")
    sources = {
        "stage_a_cell_manifest": {
            "path": relative(cell_manifest_path),
            "sha256": sha256_file(cell_manifest_path),
        },
        "subjects": {"path": relative(subjects_path), "sha256": sha256_file(subjects_path)},
        "qc_subject": {"path": relative(qc_path), "sha256": sha256_file(qc_path)},
    }
    subjects = pd.read_csv(
        subjects_path,
        keep_default_na=False,
        dtype={"sample_key": str, "subject_id": str},
    )
    qc = pd.read_csv(
        qc_path, keep_default_na=False, dtype={"sample_key": str}
    )
    return subjects, qc, sources


def write_group(
    config: dict,
    config_path: Path,
    stage_a_manifest_path: Path,
    cell_record: dict,
    staging_splits: Path,
    atlas: str,
    dataset: str,
    protocol: str,
) -> dict:
    subjects, qc, sources = load_current_cell(dataset, atlas, cell_record)
    result = build_split_group(subjects, qc, atlas, dataset, protocol, config)
    nested = build_nested_task_plan(
        subjects, qc, atlas, dataset, protocol, config, group=result
    )
    group_dir = staging_splits / atlas / dataset / protocol
    group_dir.mkdir(parents=True)
    result["tasks"].to_csv(group_dir / "tasks.csv", index=False)
    result["membership"].to_csv(group_dir / "split_membership.csv", index=False)
    nested.to_csv(group_dir / "nested_tasks.csv", index=False)

    tasks = result["tasks"]
    outer = tasks.loc[tasks["task_level"] == "outer"]
    inner = tasks.loc[tasks["task_level"] == "inner"]
    sources["stage_a_manifest"] = {
        "path": relative(stage_a_manifest_path),
        "sha256": sha256_file(stage_a_manifest_path),
    }
    artifacts = inventory(
        group_dir, ["tasks.csv", "split_membership.csv", "nested_tasks.csv"]
    )
    nested_level_counts = {
        level: int(count)
        for level, count in nested["task_level"].value_counts().sort_index().items()
    }
    group_manifest = {
        "stage": "B",
        "status": "passed",
        "atlas_id": atlas,
        "dataset_id": dataset,
        "protocol": protocol,
        "variant": config["variant"],
        "seed": int(config["seed"]),
        "config_path": relative(config_path),
        "config_sha256": sha256_file(config_path),
        "sources": sources,
        "counts": {
            "qc_pass": result["qc_pass_count"],
            "qc_fail_excluded": result["qc_fail_count"],
            "outer_folds": result["outer_fold_count"],
            "outer_tasks": int(len(outer)),
            "inner_tasks": int(len(inner)),
            "ready_tasks": int((tasks["task_status"] == "ready").sum()),
            "invalid_untrainable_tasks": int(
                (tasks["task_status"] == "invalid_untrainable").sum()
            ),
            "fallback_outer_tasks": int(
                (outer["inner_policy"] == "label_stratified_2fold_fallback").sum()
            ),
            "nested_tasks": int(len(nested)),
            "nested_invalid_untrainable_tasks": int(
                (nested["task_status"] == "invalid_untrainable").sum()
            ),
            "nested_task_levels": nested_level_counts,
        },
        "artifacts": artifacts,
    }
    json_dump(group_dir / "split_manifest.json", group_manifest)
    (group_dir / "_SUCCESS").write_text("stage_b_split_ready\n", encoding="utf-8")
    return {
        "atlas_id": atlas,
        "dataset_id": dataset,
        "protocol": protocol,
        "group_dir": f"outputs/splits/{atlas}/{dataset}/{protocol}",
        "split_manifest_path": f"outputs/splits/{atlas}/{dataset}/{protocol}/split_manifest.json",
        "counts": group_manifest["counts"],
        "artifacts": artifacts,
    }


def write_stage(
    config: dict,
    config_path: Path,
    staging_root: Path,
) -> None:
    stage_a_manifest_path, _, cells = validate_stage_a(config)
    staging_splits = staging_root / "splits"
    stage_dir = staging_root / "stage_b"
    stage_dir.mkdir(parents=True)
    records = []
    for atlas in config["atlases"]:
        for dataset in config["disease_datasets"]:
            for protocol in config["protocols"]:
                record = write_group(
                    config,
                    config_path,
                    stage_a_manifest_path,
                    cells[(dataset, atlas)],
                    staging_splits,
                    atlas,
                    dataset,
                    protocol,
                )
                records.append(record)
                counts = record["counts"]
                print(
                    f"prepared {atlas}/{dataset}/{protocol}: pass={counts['qc_pass']}, "
                    f"outer={counts['outer_tasks']}, inner={counts['inner_tasks']}, "
                    f"invalid={counts['invalid_untrainable_tasks']}",
                    flush=True,
                )
    if len(records) != 32:
        raise ValueError(f"Stage B requires 32 groups, got {len(records)}")

    inventory_rows = []
    stage_groups = []
    for record in records:
        atlas, dataset, protocol = (
            record["atlas_id"], record["dataset_id"], record["protocol"]
        )
        staged_manifest = staging_splits / atlas / dataset / protocol / "split_manifest.json"
        final_manifest_path = record["split_manifest_path"]
        counts = record["counts"]
        inventory_rows.append({
            "atlas_id": atlas,
            "dataset_id": dataset,
            "protocol": protocol,
            "group_dir": record["group_dir"],
            "split_manifest_path": final_manifest_path,
            "split_manifest_sha256": sha256_file(staged_manifest),
            **counts,
            "tasks_bytes": record["artifacts"]["tasks.csv"]["bytes"],
            "tasks_sha256": record["artifacts"]["tasks.csv"]["sha256"],
            "membership_bytes": record["artifacts"]["split_membership.csv"]["bytes"],
            "membership_sha256": record["artifacts"]["split_membership.csv"]["sha256"],
            "nested_tasks_bytes": record["artifacts"]["nested_tasks.csv"]["bytes"],
            "nested_tasks_sha256": record["artifacts"]["nested_tasks.csv"]["sha256"],
        })
        stage_groups.append({
            "atlas_id": atlas,
            "dataset_id": dataset,
            "protocol": protocol,
            "split_manifest_path": final_manifest_path,
            "split_manifest_sha256": sha256_file(staged_manifest),
        })
    inventory_frame = pd.DataFrame(inventory_rows)
    inventory_frame.to_csv(stage_dir / "split_inventory.csv", index=False)

    total_outer = int(inventory_frame["outer_tasks"].sum())
    total_inner = int(inventory_frame["inner_tasks"].sum())
    total_invalid = int(inventory_frame["invalid_untrainable_tasks"].sum())
    total_fallback = int(inventory_frame["fallback_outer_tasks"].sum())
    total_nested = int(inventory_frame["nested_tasks"].sum())
    total_nested_invalid = int(inventory_frame["nested_invalid_untrainable_tasks"].sum())
    lines = [
        "# Stage B machine summary",
        "",
        "status: passed",
        "groups: 32/32",
        f"outer tasks: {total_outer}",
        f"inner tasks: {total_inner}",
        f"nested tasks: {total_nested}",
        f"nested invalid_untrainable tasks: {total_nested_invalid}",
        f"fallback outer tasks: {total_fallback}",
        f"invalid_untrainable tasks: {total_invalid}",
        "",
        "| atlas | dataset | protocol | QC pass | QC fail excluded | outer | inner | nested | fallback outer | invalid tasks | nested invalid |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in inventory_frame.itertuples(index=False):
        lines.append(
            f"| {row.atlas_id} | {row.dataset_id} | {row.protocol} | {row.qc_pass} | "
            f"{row.qc_fail_excluded} | {row.outer_tasks} | {row.inner_tasks} | "
            f"{row.nested_tasks} | {row.fallback_outer_tasks} | "
            f"{row.invalid_untrainable_tasks} | {row.nested_invalid_untrainable_tasks} |"
        )
    (stage_dir / "stage_b_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    json_dump(stage_dir / "stage_b_manifest.json", {
        "stage": "B",
        "status": "passed",
        "group_count": len(stage_groups),
        "stage_a_manifest_path": relative(stage_a_manifest_path),
        "stage_a_manifest_sha256": sha256_file(stage_a_manifest_path),
        "config_path": relative(config_path),
        "config_sha256": sha256_file(config_path),
        "implementation_files": {
            path: sha256_file(PROJECT_ROOT / path) for path in IMPLEMENTATION_FILES
        },
        "totals": {
            "outer_tasks": total_outer,
            "inner_tasks": total_inner,
            "nested_tasks": total_nested,
            "nested_invalid_untrainable_tasks": total_nested_invalid,
            "fallback_outer_tasks": total_fallback,
            "invalid_untrainable_tasks": total_invalid,
        },
        "groups": stage_groups,
        "artifacts": inventory(stage_dir, ["split_inventory.csv", "stage_b_summary.md"]),
    })
    (stage_dir / "_SUCCESS").write_text("stage_b_ready\n", encoding="utf-8")


def publish(staging_root: Path, output_root: Path, replace_existing: bool) -> Path | None:
    final_splits, final_stage = output_root / "splits", output_root / "stage_b"
    existing = [path for path in (final_splits, final_stage) if path.exists()]
    if existing and not replace_existing:
        raise FileExistsError(
            "Stage B outputs exist; rerun with --replace-existing to archive and replace them"
        )
    archive_dir = None
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = output_root / "archive" / f"stage_b_{stamp}_{uuid.uuid4().hex[:8]}"
        archive_dir.mkdir(parents=True)
        archive_info = {"created_utc": stamp, "replaced": []}
        for path in existing:
            old_manifest = path / "stage_b_manifest.json" if path.name == "stage_b" else None
            archive_info["replaced"].append({
                "original_path": str(path.resolve()),
                "archive_path": str((archive_dir / path.name).resolve()),
                "stage_manifest_sha256": (
                    sha256_file(old_manifest) if old_manifest and old_manifest.is_file() else ""
                ),
            })
            path.rename(archive_dir / path.name)
        json_dump(archive_dir / "archive_manifest.json", archive_info)
    try:
        (staging_root / "splits").rename(final_splits)
        (staging_root / "stage_b").rename(final_stage)
        staging_root.rmdir()
    except Exception:
        if final_splits.exists() and not (staging_root / "splits").exists():
            final_splits.rename(staging_root / "splits")
        if archive_dir:
            for name in ("splits", "stage_b"):
                archived = archive_dir / name
                if archived.exists() and not (output_root / name).exists():
                    archived.rename(output_root / name)
        raise
    return archive_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "stage_b.yaml"
    )
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    configured_root = Path(config["project_root"]).resolve()
    if configured_root != PROJECT_ROOT.resolve():
        raise ValueError("stage_b project_root must equal this project directory")
    output_root = PROJECT_ROOT / "outputs"
    if ((output_root / "splits").exists() or (output_root / "stage_b").exists()) and not args.replace_existing:
        raise FileExistsError("Stage B outputs exist; use --replace-existing for recoverable replacement")
    staging_root = output_root / ".staging" / f"stage_b_{uuid.uuid4().hex}"
    staging_root.mkdir(parents=True)
    try:
        write_stage(config, config_path, staging_root)
        archive_dir = publish(staging_root, output_root, args.replace_existing)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    print("Stage B published: 32/32 groups", flush=True)
    if archive_dir:
        print(f"Previous Stage B archived at: {archive_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
