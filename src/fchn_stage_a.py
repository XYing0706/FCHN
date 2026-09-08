"""Stage A: independent dataset x atlas input cells."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(value: np.ndarray) -> str:
    return str(value.item()) if np.asarray(value).ndim == 0 else str(value)


def _subject_ids_match(left: np.ndarray, right: np.ndarray) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left.astype(str), right.astype(str)):
        if a == b:
            continue
        if a.isdigit() and b.isdigit() and int(a) == int(b):
            continue
        return False
    return True


SUBJECT_COLUMNS = [
    "sample_key", "dataset_id", "subject_id", "site_id", "label", "age",
    "sex", "scan_length", "mean_fd", "source_file", "source_row_hash",
    "demographic_source_file", "demographic_source_row_hash",
    "mean_fd_source", "sex_encoding_rule",
]


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _row_hash(row: dict[str, Any]) -> str:
    normalized = {
        str(key): _text(value)
        for key, value in row.items()
        if not str(key).startswith("_")
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _records_csv(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
    return frame.to_dict(orient="records")


def _unique_by(rows: list[dict[str, Any]], key_fn, source: Path) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = key_fn(row)
        if not key or key in indexed:
            raise ValueError(f"missing or duplicate demographic identity in {source}")
        indexed[key] = row
    return indexed


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text or text.lower() in {"nan", "none", "na", "n/a", "-9999", "[]"}:
        return None
    number = float(text)
    return number if np.isfinite(number) else None


def _same_number(left: Any, right: Any) -> bool:
    a, b = _number(left), _number(right)
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6)


def _demographic_index(dataset: str, path: Path, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if dataset == "mdd":
        sheets = pd.read_excel(path, sheet_name=["MDD", "Controls"])
        rows = []
        for sheet, label in (("MDD", 1), ("Controls", 0)):
            for row in sheets[sheet].to_dict(orient="records"):
                row["_expected_label"] = label
                row["_sheet"] = sheet
                rows.append(row)
        return _unique_by(rows, lambda row: _text(row.get("ID")), path)
    encoding = config["demographic_encoding"].get(dataset, "utf-8")
    rows = _records_csv(path, encoding)
    if dataset == "adhd":
        return _unique_by(rows, lambda row: _text(row.get("Participant ID")).strip("'").strip(), path)
    if dataset == "abide":
        return _unique_by(rows, lambda row: _text(row.get("SUB_ID")).removesuffix(".0").zfill(7), path)
    if dataset == "abide2":
        return _unique_by(rows, lambda row: _text(row.get("SUB_LIST")), path)
    if dataset == "fcp":
        return _unique_by(
            rows,
            lambda row: f"{_text(row.get('Site')).strip(chr(39) + chr(34))}_{_text(row.get('Subject ID')).strip(chr(39) + chr(34))}",
            path,
        )
    raise ValueError(f"unsupported dataset: {dataset}")


def build_subjects_table(cell_inputs: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    """Build the canonical subject contract and verify exact demographic identity."""
    dataset = cell_inputs["dataset"]
    manifest_path = Path(cell_inputs["manifest_path"])
    demographic_path = manifest_path.parent / config["demographic_files"][dataset]
    manifest_rows = _records_csv(manifest_path)
    demographic = _demographic_index(dataset, demographic_path, config)
    output = []
    for source in manifest_rows:
        subject_id = _text(source.get("subject_id"))
        phenotype = demographic.get(subject_id)
        if phenotype is None:
            raise ValueError(f"demographic exact match failed for {dataset}")
        label = int(float(_text(source.get("label"))))
        age, sex = _number(source.get("age")), _number(source.get("sex"))
        if dataset == "adhd":
            dx = _number(phenotype.get("DX"))
            expected = 1 if dx is not None and dx > 0 else 0
            if label != expected or not _same_number(age, phenotype.get("Age")) or not _same_number(sex, phenotype.get("Gender")):
                raise ValueError("ADHD manifest and phenotype conflict")
        elif dataset in {"abide", "abide2"}:
            expected = 2 - int(float(_text(phenotype.get("DX_GROUP"))))
            age_field = "AGE_AT_SCAN" if dataset == "abide" else "AGE_AT_SCAN "
            if label != expected or not _same_number(age, phenotype.get(age_field)) or not _same_number(sex, phenotype.get("SEX")):
                raise ValueError(f"{dataset} manifest and phenotype conflict")
        elif dataset == "mdd":
            if label != int(phenotype["_expected_label"]):
                raise ValueError("MDD diagnosis sheet conflicts with manifest")
            age, sex = _number(phenotype.get("Age")), _number(phenotype.get("Sex"))
        elif dataset == "fcp":
            if label != 0 or not _same_number(age, phenotype.get("Age")):
                raise ValueError("FCP manifest and info conflict")
            raw_sex = _text(phenotype.get("Sex")).strip("'\"").lower()
            sex = 1.0 if raw_sex == "m" else 2.0 if raw_sex == "f" else None
            if sex is None:
                raise ValueError("unrecognized FCP sex code")
        mean_fd = _number(source.get("meanFD_Power"))
        site = _text(source.get("site"))
        output.append({
            "sample_key": subject_id,
            "dataset_id": dataset,
            "subject_id": subject_id,
            "site_id": f"{dataset}::{site}",
            "label": label,
            "age": age,
            "sex": sex,
            "scan_length": int(float(_text(source.get("T")))),
            "mean_fd": mean_fd,
            "source_file": str(manifest_path.resolve()),
            "source_row_hash": _row_hash(source),
            "demographic_source_file": str(demographic_path.resolve()),
            "demographic_source_row_hash": _row_hash(phenotype),
            "mean_fd_source": manifest_path.name if mean_fd is not None else "",
            "sex_encoding_rule": config["sex_encoding_rule"][dataset],
        })
    frame = pd.DataFrame(output, columns=SUBJECT_COLUMNS)
    if frame["sample_key"].duplicated().any():
        raise ValueError(f"duplicate sample_key in {dataset}")
    return frame


def load_cell_inputs(data_root: Path | str, dataset: str, atlas: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read exactly one dataset/atlas cell and validate source identities."""
    root = Path(data_root)
    ds_dir = root / dataset
    manifest_name = (config or {}).get("manifest_files", {}).get(dataset, f"manifest_{dataset}.csv")
    mask_name = (config or {}).get("roi_mask_files", {}).get(dataset, f"roi_mask_{dataset}.csv")
    if dataset == "fcp" and not config:
        manifest_name, mask_name = "manifest_FCP.csv", "roi_mask_FCP.csv"
    fc_path, ts_path = ds_dir / f"{atlas}_fc.npz", ds_dir / f"{atlas}_ts.npz"
    manifest_path, mask_path = ds_dir / manifest_name, ds_dir / mask_name
    fc = np.load(fc_path, allow_pickle=False)
    ts = np.load(ts_path, allow_pickle=False)
    if "X" not in fc or fc["X"].ndim != 2:
        raise ValueError(f"{fc_path} must contain a two-dimensional X edge matrix")
    if any(np.asarray(fc[key]).dtype == object for key in fc.files):
        raise TypeError(f"object array is forbidden in {fc_path}")
    x = np.asarray(fc["X"])
    subject_ids = np.asarray(fc["subject_ids"]).astype(str)
    roi_indices = np.asarray(fc["roi_indices"], dtype=int)
    ts_subject_ids = np.asarray(ts["subject_ids"]).astype(str)
    ts_roi_indices = np.asarray(ts["roi_indices"], dtype=int)
    if not _subject_ids_match(subject_ids, ts_subject_ids):
        raise ValueError(f"FC/TS subject_ids mismatch for {dataset}/{atlas}")
    if not np.array_equal(roi_indices, ts_roi_indices):
        raise ValueError(f"FC/TS roi_indices mismatch for {dataset}/{atlas}")
    mask = pd.read_csv(mask_path)
    mask_atlas = mask.loc[mask["atlas"].astype(str) == atlas].copy()
    kept = mask_atlas.loc[mask_atlas["kept"].astype(bool), "roi_local_idx"].to_numpy(dtype=int)
    if not np.array_equal(roi_indices, kept):
        raise ValueError(f"FC/ROI mask roi_indices mismatch for {dataset}/{atlas}")
    manifest = pd.read_csv(manifest_path)
    if "subject_id" not in manifest or not _subject_ids_match(subject_ids, manifest["subject_id"].astype(str).to_numpy()):
        raise ValueError(f"FC/manifest subject_id mismatch for {dataset}/{atlas}")
    manifest = manifest.copy()
    manifest["subject_id"] = subject_ids
    theoretical = int((config or {}).get("theoretical_roi_count", {}).get(atlas, len(roi_indices)))
    expected_edges = theoretical * (theoretical - 1) // 2
    if x.shape[1] != len(roi_indices) * (len(roi_indices) - 1) // 2:
        raise ValueError(f"FC edge count is inconsistent with retained ROI count for {dataset}/{atlas}")
    source_hashes = {str(p): sha256_file(p) for p in [fc_path, ts_path, manifest_path, mask_path]}
    fc.close()
    ts.close()
    return {
        "dataset": dataset, "atlas": atlas, "X": x, "subject_ids": subject_ids,
        "roi_indices": roi_indices, "mask": mask_atlas, "manifest": manifest,
        "fc_path": fc_path, "ts_path": ts_path, "manifest_path": manifest_path,
        "mask_path": mask_path,
        "theoretical_roi_count": theoretical, "expected_theoretical_edges": expected_edges,
        "source_hashes": source_hashes,
    }


def build_cell_roi_manifest(cell_inputs: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    atlas = cell_inputs["atlas"]
    count = int(config["theoretical_roi_count"][atlas])
    master_path = Path(config["project_root"]) / "config" / "atlas_metadata" / f"master_{atlas}.csv"
    master = pd.read_csv(master_path)
    if len(master) != count or master["roi_original_index"].tolist() != list(range(1, count + 1)):
        raise ValueError(f"invalid atlas master ROI order: {master_path}")
    present = {int(v) + 1: i for i, v in enumerate(cell_inputs["roi_indices"])}
    mask = cell_inputs["mask"].set_index("roi_local_idx")
    rows: list[dict[str, Any]] = []
    for master_row in master.to_dict(orient="records"):
        local = int(master_row["roi_original_index"])
        local0 = local - 1
        matrix_position = present.get(local)
        available = matrix_position is not None
        row = mask.loc[local0] if local0 in mask.index else None
        rows.append({**master_row,
            "structural_status": "available" if available else "structural_unavailable",
            "matrix_position": matrix_position, "reason_code": "" if available else "ROI_MASK_NOT_KEPT",
            "source_roi_index": local0,
            "mask_kept": int(row["kept"]) if row is not None else 0,
            "mask_valid_rate": float(row["valid_rate"]) if row is not None else np.nan,
        })
    return pd.DataFrame(rows)


def build_cell_edge_manifest(cell_inputs: dict[str, Any], roi_manifest: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    atlas = cell_inputs["atlas"]
    count = int(config["theoretical_roi_count"][atlas])
    master_path = Path(config["project_root"]) / "config" / "atlas_metadata" / f"master_edges_{atlas}.csv"
    master = pd.read_csv(master_path)
    expected_count = count * (count - 1) // 2
    if len(master) != expected_count:
        raise ValueError(f"invalid atlas master edge count: {master_path}")
    positions = dict(zip(roi_manifest["roi_uid"], roi_manifest["matrix_position"]))
    rows: list[dict[str, Any]] = []
    available_pos = 0
    for master_row in master.to_dict(orient="records"):
        usable = (
            not pd.isna(positions[master_row["roi_uid_i"]])
            and not pd.isna(positions[master_row["roi_uid_j"]])
        )
        rows.append({**master_row,
            "structural_status": "available" if usable else "structural_unavailable",
            "matrix_position": available_pos if usable else None,
            "reason_code": "" if usable else "ROI_ENDPOINT_NOT_KEPT",
        })
        if usable:
            available_pos += 1
    if available_pos != cell_inputs["X"].shape[1]:
        raise ValueError("edge manifest does not match FC columns")
    return pd.DataFrame(rows)


def compute_cell_qc(cell_inputs: dict[str, Any], edge_manifest: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    x = np.asarray(cell_inputs["X"])
    invalid = ~np.isfinite(x)
    usable = edge_manifest["structural_status"].eq("available").to_numpy()
    usable_positions = edge_manifest.loc[usable, "matrix_position"].to_numpy(dtype=int)
    usable_invalid = invalid[:, usable_positions]
    subject_ratio = usable_invalid.mean(axis=1) if usable.any() else np.ones(x.shape[0])
    incident_total = np.zeros(len(cell_inputs["roi_indices"]), dtype=int)
    incident_invalid = np.zeros((x.shape[0], len(cell_inputs["roi_indices"])), dtype=int)
    pos_by_local = {int(v): i for i, v in enumerate(cell_inputs["roi_indices"])}
    for row in edge_manifest.loc[edge_manifest["structural_status"].eq("available")].itertuples():
        i = pos_by_local[row.roi_original_index_i - 1]
        j = pos_by_local[row.roi_original_index_j - 1]
        values = invalid[:, int(row.matrix_position)]
        incident_total[i] += 1; incident_total[j] += 1
        incident_invalid[:, i] += values.astype(int); incident_invalid[:, j] += values.astype(int)
    incident_ratio = np.divide(incident_invalid, incident_total[None, :], out=np.zeros_like(incident_invalid, dtype=float), where=incident_total[None, :] > 0)
    max_roi_position = incident_ratio.argmax(axis=1)
    max_roi_ratio = incident_ratio[np.arange(x.shape[0]), max_roi_position]
    max_roi_uid = [
        f"{cell_inputs['atlas'].lower()}:roi{int(cell_inputs['roi_indices'][position]) + 1:03d}"
        for position in max_roi_position
    ]
    threshold_s = float(config["qc"]["subject_invalid_edge_ratio"])
    threshold_r = float(config["qc"]["roi_incident_invalid_ratio"])
    bad_subject = subject_ratio >= threshold_s
    bad_roi_subject = max_roi_ratio >= threshold_r
    reasons = []
    for idx in range(x.shape[0]):
        code = []
        if bad_subject[idx]: code.append("TOTAL_EDGE_INVALID_GE_5PCT")
        if bad_roi_subject[idx]: code.append("ROI_INCIDENT_INVALID_GE_30PCT")
        reasons.append(";".join(sorted(code)))
    return {
        "qc_status": ["fail" if v else "pass" for v in (bad_subject | bad_roi_subject)],
        "subject_invalid_edge_ratio": subject_ratio.tolist(),
        "invalid_edge_count": usable_invalid.sum(axis=1).astype(int).tolist(),
        "max_roi_invalid_ratio": max_roi_ratio.tolist(),
        "max_invalid_roi_uid": max_roi_uid,
        "max_roi_incident_invalid_ratio": float(incident_ratio.max(initial=0.0)),
        "bad_subject_count": int((bad_subject | bad_roi_subject).sum()), "invalid_value_count": int(usable_invalid.sum()),
        "usable_edge_count": int(usable.sum()), "nonfinite_mask": invalid,
        "reason_codes": reasons,
    }


def json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)
