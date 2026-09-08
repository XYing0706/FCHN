"""Generate Stage A atlas master ROI/edge tables from pinned source snapshots."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_a_metadata import (  # noqa: E402
    build_master_edges,
    build_master_rois,
    write_source_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "stage_a.yaml")
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    metadata_dir = PROJECT_ROOT / "config" / "atlas_metadata"
    source_root = metadata_dir / "sources"
    masters = build_master_rois(source_root, config)
    for atlas in config["atlases"]:
        roi = masters[atlas]
        edge = build_master_edges(roi)
        roi.to_csv(metadata_dir / f"master_{atlas}.csv", index=False)
        edge.to_csv(metadata_dir / f"master_edges_{atlas}.csv", index=False)
    write_source_manifest(source_root, config["atlases"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
