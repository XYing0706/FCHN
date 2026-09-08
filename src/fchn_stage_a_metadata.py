"""Build authoritative atlas ROI and edge masters from pinned source files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pandas as pd
from scipy.io import loadmat

from fchn_stage_a import sha256_file


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
DPABI_COMMIT = "8d4b16e46be65cce93662e34e1cfa22bd40d98dc"
DPABI_REPOSITORY = "https://github.com/Chaogan-Yan/DPABI"


def _hemisphere(name: str, x: float | int | None) -> str:
    if name.endswith("_L") or name.endswith("(L)"):
        return "L"
    if name.endswith("_R") or name.endswith("(R)"):
        return "R"
    if x is None or not np.isfinite(float(x)):
        return ""
    return "L" if float(x) < 0 else "R" if float(x) > 0 else "M"


def _row(
    atlas: str,
    index: int,
    start: int,
    name: str,
    label: object,
    description: str,
    network: str,
    xyz: tuple[float, float, float],
    source: str,
    source_hash: str,
) -> dict[str, Any]:
    x, y, z = xyz
    return {
        "atlas_id": atlas,
        "roi_uid": f"{atlas.lower()}:roi{index:03d}",
        "roi_original_index": index,
        "global_original_column": start + index - 1,
        "roi_name": name,
        "roi_label": str(label),
        "description": description,
        "hemisphere": _hemisphere(name, x),
        "network": network,
        "x": float(x), "y": float(y), "z": float(z),
        "metadata_source": source,
        "metadata_version": f"DPABI tree {DPABI_COMMIT}",
        "metadata_license": "LGPL-2.1; redistributed atlas files retain original citations",
        "metadata_sha256": source_hash,
    }


def _reference(path: Path) -> np.ndarray:
    rows = np.asarray(loadmat(path, squeeze_me=True, struct_as_record=False)["Reference"], dtype=object)
    if rows.ndim != 2 or rows.shape[1] != 3:
        raise ValueError(f"Unexpected Reference shape in {path}: {rows.shape}")
    return rows[1:]


def _aal(source_root: Path, start: int) -> pd.DataFrame:
    path = source_root / "dpabi" / "aal_Labels.mat"
    rows = _reference(path)
    if len(rows) != 116 or [int(v) for v in rows[:, 1]] != list(range(1, 117)):
        raise ValueError("AAL source order is not 1..116")
    digest = sha256_file(path)
    data = []
    for i, r in enumerate(rows, 1):
        name = str(r[0])
        item = _row(
            "AAL116", i, start, name, int(r[1]), "", "",
            tuple(np.asarray(r[2], dtype=float)), "dpabi/aal_Labels.mat", digest,
        )
        if not name.endswith(("_L", "_R")):
            item["hemisphere"] = "M"
        data.append(item)
    return pd.DataFrame(data, columns=ROI_COLUMNS)


def _ho112(source_root: Path, start: int) -> pd.DataFrame:
    folder = source_root / "ho112_verified_local"
    labels_path = folder / "ho112_dpabi_labels.csv"
    labels = pd.read_csv(labels_path).sort_values("roi_index")
    cortical = _reference(folder / "HarvardOxford-cort-maxprob-thr25-2mm_YCG_Labels.mat")
    subcortical = _reference(folder / "HarvardOxford-sub-maxprob-thr25-2mm_YCG_Labels.mat")
    reference = np.vstack([cortical, subcortical])
    if len(labels) != 112 or labels["roi_index"].tolist() != list(range(112)):
        raise ValueError("HO112 label order is not 0..111")
    if labels["atlas_value"].astype(int).tolist() != [int(v) for v in reference[:, 1]]:
        raise ValueError("HO112 CSV and MAT label order differ")
    digest = sha256_file(labels_path)
    data = []
    for i, (label_row, ref_row) in enumerate(zip(labels.itertuples(), reference), 1):
        data.append(_row(
            "HO112", i, start, str(label_row.roi_name), int(label_row.atlas_value),
            str(label_row.anatomical_class), "", tuple(np.asarray(ref_row[2], dtype=float)),
            "ho112_verified_local/ho112_dpabi_labels.csv", digest,
        ))
    return pd.DataFrame(data, columns=ROI_COLUMNS)


def _cc200(source_root: Path, start: int) -> pd.DataFrame:
    path = source_root / "dpabi" / "CC200ROI_tcorr05_2level_all.nii"
    image = nib.load(str(path))
    values = np.asanyarray(image.dataobj).astype(int)
    labels = np.unique(values)
    labels = labels[labels != 0]
    if labels.tolist() != list(range(1, 201)):
        raise ValueError("CC200 source labels are not 1..200")
    digest = sha256_file(path)
    data = []
    for i in labels:
        voxels = np.argwhere(values == i)
        xyz = nib.affines.apply_affine(image.affine, voxels).mean(axis=0)
        data.append(_row(
            "CC200", int(i), start, "", int(i), "", "", tuple(xyz),
            "dpabi/CC200ROI_tcorr05_2level_all.nii", digest,
        ))
        data[-1]["hemisphere"] = ""
    return pd.DataFrame(data, columns=ROI_COLUMNS)


def _dosenbach(source_root: Path, start: int) -> pd.DataFrame:
    path = source_root / "dpabi" / "Dosenbach_Science_160ROIs_Info.mat"
    info = np.asarray(loadmat(path, squeeze_me=True, struct_as_record=False)["Dos160_WithName"], dtype=object)
    center_path = source_root / "dpabi" / "Dosenbach_Science_160ROIs_Center.mat"
    centers = np.asarray(loadmat(center_path, squeeze_me=True)["Dosenbach_Science_160ROIs_Center"], dtype=float)
    if info.shape != (160, 5) or centers.shape != (160, 3):
        raise ValueError("Dosenbach source does not contain 160 ordered ROIs")
    if not np.array_equal(info[:, :3].astype(float), centers):
        raise ValueError("Dosenbach Info and Center coordinate orders differ")
    digest = sha256_file(path)
    data = [
        _row("Dosenbach160", i, start, str(r[3]), i, "", str(r[4]),
             tuple(np.asarray(r[:3], dtype=float)),
             "dpabi/Dosenbach_Science_160ROIs_Info.mat", digest)
        for i, r in enumerate(info, 1)
    ]
    return pd.DataFrame(data, columns=ROI_COLUMNS)


def build_master_rois(source_root: Path, config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    starts = config["global_column_start_1based"]
    return {
        "HO112": _ho112(source_root, int(starts["HO112"])),
        "AAL116": _aal(source_root, int(starts["AAL116"])),
        "Dosenbach160": _dosenbach(source_root, int(starts["Dosenbach160"])),
        "CC200": _cc200(source_root, int(starts["CC200"])),
    }


def build_master_edges(master: pd.DataFrame) -> pd.DataFrame:
    rows = []
    atlas = str(master["atlas_id"].iloc[0])
    records = list(master.itertuples(index=False))
    for left_index, left in enumerate(records):
        for right in records[left_index + 1:]:
            rows.append({
                "atlas_id": atlas,
                "edge_uid": f"{left.roi_uid}--{right.roi_uid.split(':', 1)[1]}",
                "roi_uid_i": left.roi_uid,
                "roi_uid_j": right.roi_uid,
                "roi_original_index_i": left.roi_original_index,
                "roi_original_index_j": right.roi_original_index,
                "global_original_column_i": left.global_original_column,
                "global_original_column_j": right.global_original_column,
            })
    return pd.DataFrame(rows, columns=EDGE_COLUMNS)


def write_source_manifest(source_root: Path, atlases: list[str]) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in source_root.rglob("*") if p.is_file() and p.name != "source_manifest.json"):
        files.append({
            "relative_path": path.relative_to(source_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    payload = {
        "access_date": "2026-08-26",
        "atlases": atlases,
        "dpabi_repository": DPABI_REPOSITORY,
        "dpabi_tree_sha": DPABI_COMMIT,
        "license": "LGPL-2.1; see dpabi/LICENSE",
        "citations": {
            "AAL116": "Tzourio-Mazoyer et al. 2002, doi:10.1006/nimg.2001.0978",
            "HO112": "Harvard-Oxford distributed via DPABI/FSL; project order is YCG 96+16",
            "CC200": "Craddock et al. 2012, doi:10.1002/hbm.21333",
            "Dosenbach160": "Dosenbach et al. 2010, doi:10.1126/science.1185718",
            "DPABI": "Yan et al. 2016, doi:10.1007/s12021-016-9299-4",
        },
        "files": files,
    }
    (source_root / "source_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
