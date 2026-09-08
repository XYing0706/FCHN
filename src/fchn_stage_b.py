"""Deterministic split primitives for FCHN stage B."""

from __future__ import annotations

import hashlib
import json

import pandas as pd


REQUIRED_SUBJECT_COLUMNS = ("sample_key", "site_id", "label")
MEMBERSHIP_COLUMNS = (
    "dataset_id", "atlas_id", "protocol", "task_id", "sample_key", "role", "split_hash",
)
TASK_COLUMNS = (
    "task_id", "parent_task_id", "task_level", "dataset_id", "atlas_id", "protocol",
    "variant", "outer_fold", "inner_fold", "held_out_site_id", "inner_policy",
    "task_status", "reason_code", "seed", "fit_count", "train_count",
    "validation_count", "test_count", "fit_label0_count", "fit_label1_count",
    "train_label0_count", "train_label1_count", "validation_label0_count",
    "validation_label1_count", "test_label0_count", "test_label1_count",
    "fit_site_label_counts", "train_site_label_counts", "validation_site_label_counts",
    "test_site_label_counts", "split_hash",
)


def _validate_subjects(subjects: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_SUBJECT_COLUMNS if column not in subjects]
    if missing:
        raise ValueError(f"missing subject columns: {missing}")
    frame = subjects.loc[:, REQUIRED_SUBJECT_COLUMNS].copy()
    if frame.empty:
        raise ValueError("subjects must not be empty")
    if frame["sample_key"].isna().any() or frame["sample_key"].duplicated().any():
        raise ValueError("sample_key must be non-missing and unique")
    if frame["site_id"].isna().any() or frame["site_id"].astype(str).str.strip().eq("").any():
        raise ValueError("site_id must be non-missing and non-empty")
    if frame["label"].isna().any() or not set(frame["label"].unique()).issubset({0, 1}):
        raise ValueError("label must contain only 0 and 1")
    frame["sample_key"] = frame["sample_key"].astype(str)
    frame["site_id"] = frame["site_id"].astype(str)
    frame["label"] = frame["label"].astype(int)
    return frame


def _stable_round_robin(
    subjects: pd.DataFrame,
    strata: list[str],
    n_splits: int,
    seed: int,
    context: str,
    fold_column: str,
) -> pd.DataFrame:
    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")
    frame = _validate_subjects(subjects)
    frame["_rank"] = frame["sample_key"].map(
        lambda value: hashlib.sha256(f"{seed}|{context}|{value}".encode("utf-8")).hexdigest()
    )
    frame = frame.sort_values([*strata, "_rank", "sample_key"], kind="mergesort")
    frame[fold_column] = frame.groupby(strata, sort=True, dropna=False).cumcount() % n_splits
    return frame[["sample_key", fold_column]].sort_values("sample_key").reset_index(drop=True)


def training_status(labels, minimum_per_class: int) -> tuple[str, str]:
    """Return the frozen trainability status and low-class diagnostic code."""
    counts = pd.Series(list(labels), dtype="int64").value_counts()
    if any(int(counts.get(label, 0)) < minimum_per_class for label in (0, 1)):
        return "invalid_untrainable", "TRAIN_CLASS_COUNT_LT_10"
    return "ready", ""


def make_outer_assignments(
    subjects: pd.DataFrame,
    protocol: str,
    config: dict,
) -> pd.DataFrame:
    """Assign each QC-passing sample to exactly one outer-test fold."""
    frame = _validate_subjects(subjects)
    if protocol == "LOSO":
        site_to_fold = {
            site_id: fold for fold, site_id in enumerate(sorted(frame["site_id"].unique()))
        }
        result = frame[["sample_key", "site_id"]].copy()
        result["outer_fold"] = result["site_id"].map(site_to_fold).astype(int)
        return result[["sample_key", "outer_fold"]].sort_values("sample_key").reset_index(drop=True)
    if protocol == "pooled10_site_label":
        return _stable_round_robin(
            frame,
            list(config["outer"]["pooled_strata"]),
            int(config["outer"]["pooled_splits"]),
            int(config["seed"]),
            protocol,
            "outer_fold",
        )
    raise ValueError(f"unsupported protocol: {protocol}")


def _all_training_folds_ready(
    subjects: pd.DataFrame,
    assignments: pd.DataFrame,
    fold_column: str,
    n_splits: int,
    minimum_per_class: int,
) -> bool:
    joined = subjects.merge(assignments, on="sample_key", validate="one_to_one")
    for fold in range(n_splits):
        status, _ = training_status(joined.loc[joined[fold_column] != fold, "label"], minimum_per_class)
        if status != "ready":
            return False
    return True


def make_inner_assignments(
    outer_fit: pd.DataFrame,
    outer_task_id: str,
    config: dict,
) -> dict:
    """Build requested inner folds, applying the single allowed fallback if needed."""
    frame = _validate_subjects(outer_fit)
    inner = config["inner"]
    minimum = int(inner["minimum_train_per_class"])
    requested_splits = int(inner["requested_splits"])
    requested = _stable_round_robin(
        frame,
        list(inner["requested_strata"]),
        requested_splits,
        int(config["seed"]),
        f"{outer_task_id}|inner_requested",
        "inner_fold",
    )
    if _all_training_folds_ready(frame, requested, "inner_fold", requested_splits, minimum):
        return {
            "assignments": requested,
            "inner_policy": "site_label_5fold",
            "task_status": "ready",
            "reason_code": "",
            "partition_context": f"{outer_task_id}|inner_requested",
            "partition_strata": list(inner["requested_strata"]),
            "n_splits": requested_splits,
        }

    fallback_splits = int(inner["fallback_splits"])
    fallback = _stable_round_robin(
        frame,
        list(inner["fallback_strata"]),
        fallback_splits,
        int(config["seed"]),
        f"{outer_task_id}|inner_fallback",
        "inner_fold",
    )
    ready = _all_training_folds_ready(frame, fallback, "inner_fold", fallback_splits, minimum)
    return {
        "assignments": fallback,
        "inner_policy": "label_stratified_2fold_fallback",
        "task_status": "ready" if ready else "invalid_untrainable",
        "reason_code": (
            "INNER_REQUESTED_UNTRAINABLE_FALLBACK_USED"
            if ready
            else "INNER_FALLBACK_UNTRAINABLE"
        ),
        "partition_context": f"{outer_task_id}|inner_fallback",
        "partition_strata": list(inner["fallback_strata"]),
        "n_splits": fallback_splits,
    }


def split_hash(membership: pd.DataFrame) -> str:
    """Hash canonical ``role<TAB>sample_key<LF>`` membership records."""
    missing = [column for column in ("role", "sample_key") if column not in membership]
    if missing:
        raise ValueError(f"missing membership columns: {missing}")
    rows = membership[["role", "sample_key"]].astype(str)
    if rows.duplicated().any():
        raise ValueError("duplicate role/sample_key membership")
    rows = rows.sort_values(["role", "sample_key"], kind="mergesort")
    payload = "".join(
        f"{row.role}\t{row.sample_key}\n" for row in rows.itertuples(index=False)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _site_label_counts(frame: pd.DataFrame) -> str:
    counts = frame.groupby(["site_id", "label"], sort=True).size()
    records = [
        {"site_id": str(site_id), "label": int(label), "count": int(count)}
        for (site_id, label), count in counts.items()
    ]
    return json.dumps(records, ensure_ascii=False, separators=(",", ":"))


def _label_count(frame: pd.DataFrame, label: int) -> int:
    return int((frame["label"] == label).sum())


def _task_row(
    task_id: str,
    parent_task_id: str,
    task_level: str,
    dataset: str,
    atlas: str,
    protocol: str,
    outer_fold: int,
    inner_fold: int | str,
    held_out_site_id: str,
    inner_policy: str,
    task_status: str,
    reason_code: str,
    config: dict,
    roles: dict[str, pd.DataFrame],
    task_split_hash: str,
) -> dict:
    row = {
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "task_level": task_level,
        "dataset_id": dataset,
        "atlas_id": atlas,
        "protocol": protocol,
        "variant": config["variant"],
        "outer_fold": outer_fold,
        "inner_fold": inner_fold,
        "held_out_site_id": held_out_site_id,
        "inner_policy": inner_policy,
        "task_status": task_status,
        "reason_code": reason_code,
        "seed": int(config["seed"]),
        "split_hash": task_split_hash,
    }
    for role in ("fit", "train", "validation", "test"):
        frame = roles.get(role)
        row[f"{role}_count"] = 0 if frame is None else len(frame)
        row[f"{role}_label0_count"] = 0 if frame is None else _label_count(frame, 0)
        row[f"{role}_label1_count"] = 0 if frame is None else _label_count(frame, 1)
        row[f"{role}_site_label_counts"] = "[]" if frame is None else _site_label_counts(frame)
    return row


def _membership_rows(
    roles: dict[str, pd.DataFrame],
    dataset: str,
    atlas: str,
    protocol: str,
    task_id: str,
) -> pd.DataFrame:
    records = [
        {
            "dataset_id": dataset,
            "atlas_id": atlas,
            "protocol": protocol,
            "task_id": task_id,
            "sample_key": sample_key,
            "role": role,
        }
        for role, frame in roles.items()
        for sample_key in frame["sample_key"]
    ]
    membership = pd.DataFrame(records)
    task_hash = split_hash(membership)
    membership["split_hash"] = task_hash
    return membership.loc[:, MEMBERSHIP_COLUMNS]


def _validate_group_inputs(
    subjects: pd.DataFrame,
    qc: pd.DataFrame,
    atlas: str,
    dataset: str,
) -> tuple[pd.DataFrame, int]:
    frame = _validate_subjects(subjects)
    if "dataset_id" in subjects and not subjects["dataset_id"].eq(dataset).all():
        raise ValueError("subjects dataset_id does not match requested dataset")
    required_qc = {"dataset_id", "sample_key", "atlas_id", "qc_status"}
    missing = sorted(required_qc - set(qc.columns))
    if missing:
        raise ValueError(f"missing QC columns: {missing}")
    if qc["sample_key"].isna().any() or qc["sample_key"].duplicated().any():
        raise ValueError("QC sample_key must be non-missing and unique")
    if set(frame["sample_key"]) != set(qc["sample_key"].astype(str)):
        raise ValueError("subjects and QC sample_key sets differ")
    if not qc["dataset_id"].eq(dataset).all() or not qc["atlas_id"].eq(atlas).all():
        raise ValueError("QC dataset_id/atlas_id does not match requested group")
    if not set(qc["qc_status"].unique()).issubset({"pass", "fail"}):
        raise ValueError("QC status must contain only pass or fail")
    passed_keys = set(qc.loc[qc["qc_status"] == "pass", "sample_key"].astype(str))
    passed = frame.loc[frame["sample_key"].isin(passed_keys)].copy()
    if passed.empty:
        raise ValueError("no QC-passing subjects")
    return passed, int(len(frame) - len(passed))


def build_split_group(
    subjects: pd.DataFrame,
    qc: pd.DataFrame,
    atlas: str,
    dataset: str,
    protocol: str,
    config: dict,
) -> dict:
    """Build task and membership tables for one dataset-atlas-protocol group."""
    passed, qc_fail_count = _validate_group_inputs(subjects, qc, atlas, dataset)
    outer_assignment = make_outer_assignments(passed, protocol, config)
    assigned = passed.merge(outer_assignment, on="sample_key", validate="one_to_one")
    task_rows: list[dict] = []
    memberships: list[pd.DataFrame] = []
    separator = config["identity"]["task_id_separator"]

    for outer_fold in sorted(assigned["outer_fold"].unique()):
        test = assigned.loc[assigned["outer_fold"] == outer_fold, REQUIRED_SUBJECT_COLUMNS].copy()
        fit = assigned.loc[assigned["outer_fold"] != outer_fold, REQUIRED_SUBJECT_COLUMNS].copy()
        outer_task_id = separator.join([
            atlas, dataset, protocol, f"outer{int(outer_fold):03d}", config["variant"],
        ])
        inner = make_inner_assignments(fit, outer_task_id, config)
        held_out_site = ""
        if protocol == "LOSO":
            held_out_site = str(test["site_id"].iloc[0])

        outer_roles = {"fit": fit, "test": test}
        outer_membership = _membership_rows(
            outer_roles, dataset, atlas, protocol, outer_task_id
        )
        outer_hash = str(outer_membership["split_hash"].iloc[0])
        memberships.append(outer_membership)
        task_rows.append(_task_row(
            outer_task_id, "", "outer", dataset, atlas, protocol, int(outer_fold), "",
            held_out_site, inner["inner_policy"], inner["task_status"], inner["reason_code"],
            config, outer_roles, outer_hash,
        ))

        inner_joined = fit.merge(inner["assignments"], on="sample_key", validate="one_to_one")
        for inner_fold in sorted(inner_joined["inner_fold"].unique()):
            validation = inner_joined.loc[
                inner_joined["inner_fold"] == inner_fold, REQUIRED_SUBJECT_COLUMNS
            ].copy()
            train = inner_joined.loc[
                inner_joined["inner_fold"] != inner_fold, REQUIRED_SUBJECT_COLUMNS
            ].copy()
            inner_task_id = f"{outer_task_id}{separator}inner{int(inner_fold):02d}"
            inner_roles = {"train": train, "validation": validation, "test": test}
            inner_membership = _membership_rows(
                inner_roles, dataset, atlas, protocol, inner_task_id
            )
            inner_hash = str(inner_membership["split_hash"].iloc[0])
            memberships.append(inner_membership)
            task_rows.append(_task_row(
                inner_task_id, outer_task_id, "inner", dataset, atlas, protocol,
                int(outer_fold), int(inner_fold), held_out_site, inner["inner_policy"],
                inner["task_status"], inner["reason_code"], config, inner_roles, inner_hash,
            ))

    tasks = pd.DataFrame(task_rows, columns=TASK_COLUMNS)
    membership = pd.concat(memberships, ignore_index=True).loc[:, MEMBERSHIP_COLUMNS]
    return {
        "tasks": tasks,
        "membership": membership,
        "qc_pass_count": int(len(passed)),
        "qc_fail_count": qc_fail_count,
        "outer_fold_count": int(assigned["outer_fold"].nunique()),
    }


NESTED_TASK_COLUMNS = (
    "task_id", "parent_task_id", "outer_task_id", "meta_task_id", "task_level",
    "purpose", "outer_fold", "validation_fold", "partition_context",
    "partition_policy", "partition_strata", "n_splits", "task_status", "reason_code",
    "train_count", "validation_count", "test_count", "train_label0_count",
    "train_label1_count", "validation_label0_count", "validation_label1_count",
    "train_subject_hash", "validation_subject_hash", "test_subject_hash", "split_hash",
)


def _identity_hash(values) -> str:
    payload = "".join(f"{value}\n" for value in sorted(map(str, values)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _nested_row(
    task_id: str,
    parent_task_id: str,
    outer_task_id: str,
    meta_task_id: str,
    task_level: str,
    purpose: str,
    outer_fold: int,
    validation_fold: int | str,
    partition: dict | None,
    status: str,
    reason: str,
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> dict:
    if task_level == "outer":
        roles = {"fit": train, "test": test}
    else:
        roles = {"train": train, "validation": validation, "test": test}
    membership = pd.DataFrame([
        {"role": role, "sample_key": key}
        for role, frame in roles.items()
        for key in frame["sample_key"]
    ])
    return {
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "outer_task_id": outer_task_id,
        "meta_task_id": meta_task_id,
        "task_level": task_level,
        "purpose": purpose,
        "outer_fold": outer_fold,
        "validation_fold": validation_fold,
        "partition_context": "" if partition is None else partition["partition_context"],
        "partition_policy": "" if partition is None else partition["inner_policy"],
        "partition_strata": "[]" if partition is None else json.dumps(
            partition["partition_strata"], separators=(",", ":")
        ),
        "n_splits": 0 if partition is None else int(partition["n_splits"]),
        "task_status": status,
        "reason_code": reason,
        "train_count": len(train),
        "validation_count": len(validation),
        "test_count": len(test),
        "train_label0_count": _label_count(train, 0),
        "train_label1_count": _label_count(train, 1),
        "validation_label0_count": _label_count(validation, 0),
        "validation_label1_count": _label_count(validation, 1),
        "train_subject_hash": _identity_hash(train["sample_key"]),
        "validation_subject_hash": _identity_hash(validation["sample_key"]),
        "test_subject_hash": _identity_hash(test["sample_key"]),
        "split_hash": split_hash(membership),
    }


def _partition_tasks(
    rows: list[dict],
    parent_train: pd.DataFrame,
    test: pd.DataFrame,
    parent_task_id: str,
    outer_task_id: str,
    meta_task_id: str,
    task_level: str,
    purpose: str,
    task_label: str,
    context: str,
    outer_fold: int,
    config: dict,
) -> list[tuple[str, pd.DataFrame]]:
    partition = make_inner_assignments(parent_train, context, config)
    joined = parent_train.merge(partition["assignments"], on="sample_key", validate="one_to_one")
    children = []
    separator = config["identity"]["task_id_separator"]
    for fold in sorted(joined["inner_fold"].unique()):
        validation = joined.loc[
            joined["inner_fold"] == fold, REQUIRED_SUBJECT_COLUMNS
        ].copy()
        train = joined.loc[
            joined["inner_fold"] != fold, REQUIRED_SUBJECT_COLUMNS
        ].copy()
        task_id = f"{parent_task_id}{separator}{task_label}{int(fold):02d}"
        rows.append(_nested_row(
            task_id, parent_task_id, outer_task_id, meta_task_id, task_level, purpose,
            outer_fold, int(fold), partition, partition["task_status"],
            partition["reason_code"], train, validation, test,
        ))
        children.append((task_id, train))
    return children


def build_nested_task_plan(
    subjects: pd.DataFrame,
    qc: pd.DataFrame,
    atlas: str,
    dataset: str,
    protocol: str,
    config: dict,
    group: dict | None = None,
) -> pd.DataFrame:
    """Freeze Base OOF, C-tuning, and strict Meta OOF parent lineages."""
    passed, _ = _validate_group_inputs(subjects, qc, atlas, dataset)
    if group is None:
        group = build_split_group(subjects, qc, atlas, dataset, protocol, config)
    rows: list[dict] = []
    tasks = group["tasks"]
    membership = group["membership"]
    for outer in tasks.loc[tasks["task_level"] == "outer"].itertuples(index=False):
        member = membership.loc[membership["task_id"] == outer.task_id]
        fit_keys = set(member.loc[member["role"] == "fit", "sample_key"].astype(str))
        test_keys = set(member.loc[member["role"] == "test", "sample_key"].astype(str))
        fit = passed.loc[passed["sample_key"].isin(fit_keys)].copy()
        test = passed.loc[passed["sample_key"].isin(test_keys)].copy()
        rows.append(_nested_row(
            outer.task_id, "", outer.task_id, "", "outer", "outer_final",
            int(outer.outer_fold), "", None, outer.task_status, outer.reason_code,
            fit, passed.iloc[0:0].copy(), test,
        ))

        base_children = _partition_tasks(
            rows, fit, test, outer.task_id, outer.task_id, "", "base_oof", "base_oof",
            "inner", outer.task_id, int(outer.outer_fold), config,
        )
        for base_id, base_train in base_children:
            _partition_tasks(
                rows, base_train, test, base_id, outer.task_id, "",
                "base_c_tuning", "base_c_tuning", "c_tune",
                f"{base_id}|c_tuning", int(outer.outer_fold), config,
            )

        meta_children = _partition_tasks(
            rows, fit, test, outer.task_id, outer.task_id, "", "meta_oof", "strict_meta_oof",
            "meta", f"{outer.task_id}|meta_oof", int(outer.outer_fold), config,
        )
        for meta_id, meta_train in meta_children:
            meta_base_children = _partition_tasks(
                rows, meta_train, test, meta_id, outer.task_id, meta_id,
                "meta_base_oof", "strict_meta_base_oof", "base",
                f"{meta_id}|base_oof", int(outer.outer_fold), config,
            )
            for meta_base_id, meta_base_train in meta_base_children:
                _partition_tasks(
                    rows, meta_base_train, test, meta_base_id, outer.task_id, meta_id,
                    "meta_base_c_tuning", "strict_meta_base_c_tuning", "c_tune",
                    f"{meta_base_id}|c_tuning", int(outer.outer_fold), config,
                )
    return pd.DataFrame(rows, columns=NESTED_TASK_COLUMNS)


def reconstruct_nested_task_membership(
    task_id: str,
    nested_tasks: pd.DataFrame,
    subjects: pd.DataFrame,
    outer_membership: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Rebuild one nested task from its parent and verify the stored split hash."""
    indexed = nested_tasks.set_index("task_id", drop=False)
    if task_id not in indexed.index:
        raise KeyError(f"unknown nested task: {task_id}")
    row = indexed.loc[task_id]
    frame = _validate_subjects(subjects)
    outer_id = str(row["outer_task_id"])
    outer = outer_membership.loc[outer_membership["task_id"] == outer_id]
    test_keys = set(outer.loc[outer["role"] == "test", "sample_key"].astype(str))
    test = frame.loc[frame["sample_key"].isin(test_keys)].copy()
    if row["task_level"] == "outer":
        train_keys = set(outer.loc[outer["role"] == "fit", "sample_key"].astype(str))
        train = frame.loc[frame["sample_key"].isin(train_keys)].copy()
        roles = {"fit": train, "test": test}
    else:
        parent = reconstruct_nested_task_membership(
            str(row["parent_task_id"]), nested_tasks, frame, outer_membership, config
        )
        parent_keys = set(parent.loc[parent["role"].isin(["train", "fit"]), "sample_key"])
        parent_train = frame.loc[frame["sample_key"].isin(parent_keys)].copy()
        assignments = _stable_round_robin(
            parent_train,
            list(json.loads(str(row["partition_strata"]))),
            int(row["n_splits"]),
            int(config["seed"]),
            str(row["partition_context"]),
            "inner_fold",
        )
        joined = parent_train.merge(assignments, on="sample_key", validate="one_to_one")
        fold = int(row["validation_fold"])
        validation = joined.loc[joined["inner_fold"] == fold, REQUIRED_SUBJECT_COLUMNS]
        train = joined.loc[joined["inner_fold"] != fold, REQUIRED_SUBJECT_COLUMNS]
        roles = {"train": train, "validation": validation, "test": test}
    result = pd.DataFrame([
        {"role": role, "sample_key": key}
        for role, role_frame in roles.items()
        for key in role_frame["sample_key"]
    ])
    if split_hash(result) != str(row["split_hash"]):
        raise ValueError("reconstructed nested membership hash mismatch")
    return result
