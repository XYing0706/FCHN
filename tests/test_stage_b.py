from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "stage_b.yaml"
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_b import (
    build_split_group,
    build_nested_task_plan,
    make_inner_assignments,
    make_outer_assignments,
    split_hash,
    training_status,
    reconstruct_nested_task_membership,
)


def test_stage_b_config_is_frozen():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["atlases"] == ["HO112", "AAL116", "Dosenbach160", "CC200"]
    assert config["disease_datasets"] == ["adhd", "abide", "abide2", "mdd"]
    assert "fcp" not in config["disease_datasets"]
    assert config["protocols"] == ["LOSO", "pooled10_site_label"]
    assert config["seed"] == 20260625
    assert config["outer"]["pooled_splits"] == 10
    assert config["inner"]["requested_splits"] == 5
    assert config["inner"]["fallback_splits"] == 2
    assert config["inner"]["minimum_train_per_class"] == 10
    assert config["identity"]["fold_index_base"] == 0
    assert config["nested_plan"] == {
        "base_oof": True,
        "base_c_tuning": True,
        "strict_meta_oof": True,
        "membership_storage": "hash_reconstruct",
    }


def _subjects(per_stratum: int = 12) -> pd.DataFrame:
    rows = []
    for site in ["d::A", "d::B", "d::C"]:
        for label in [0, 1]:
            for index in range(per_stratum):
                rows.append({
                    "sample_key": f"{site}_{label}_{index:02d}",
                    "site_id": site,
                    "label": label,
                })
    return pd.DataFrame(rows)


def test_loso_outer_assignment_is_site_exclusive_and_complete():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = _subjects()
    assignment = make_outer_assignments(subjects, "LOSO", config)
    assert assignment["sample_key"].is_unique
    assert assignment["outer_fold"].nunique() == subjects["site_id"].nunique()
    joined = subjects.merge(assignment, on="sample_key", validate="one_to_one")
    assert joined.groupby("site_id")["outer_fold"].nunique().eq(1).all()


def test_pooled_outer_assignment_is_order_invariant_and_balanced_by_site_label():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = _subjects(per_stratum=23)
    first = make_outer_assignments(subjects, "pooled10_site_label", config)
    shuffled = make_outer_assignments(subjects.sample(frac=1, random_state=7), "pooled10_site_label", config)
    assert first.sort_values("sample_key").reset_index(drop=True).equals(
        shuffled.sort_values("sample_key").reset_index(drop=True)
    )
    joined = subjects.merge(first, on="sample_key", validate="one_to_one")
    for _, group in joined.groupby(["site_id", "label"]):
        counts = group["outer_fold"].value_counts().reindex(range(10), fill_value=0)
        assert counts.max() - counts.min() <= 1


def test_inner_uses_label_fallback_when_site_label_fivefold_is_untrainable():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = [
        {"sample_key": f"hc_{i:02d}", "site_id": "d::HC", "label": 0}
        for i in range(20)
    ]
    rows.extend(
        {"sample_key": f"case_{i:02d}", "site_id": f"d::case_site_{i:02d}", "label": 1}
        for i in range(20)
    )
    result = make_inner_assignments(pd.DataFrame(rows), "outer_task", config)
    assert result["inner_policy"] == "label_stratified_2fold_fallback"
    assert result["task_status"] == "ready"
    assert result["assignments"]["inner_fold"].nunique() == 2


def test_inner_marks_invalid_when_fallback_training_has_fewer_than_ten_per_class():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = pd.DataFrame([
        {"sample_key": f"s{label}_{i:02d}", "site_id": f"d::S{i:02d}", "label": label}
        for label in [0, 1] for i in range(10)
    ])
    result = make_inner_assignments(subjects, "outer_task", config)
    assert result["inner_policy"] == "label_stratified_2fold_fallback"
    assert result["task_status"] == "invalid_untrainable"
    assert result["reason_code"] == "INNER_FALLBACK_UNTRAINABLE"


def test_training_status_exposes_frozen_low_class_diagnostic():
    status, reason = training_status([0] * 10 + [1] * 9, 10)
    assert status == "invalid_untrainable"
    assert reason == "TRAIN_CLASS_COUNT_LT_10"
    status, reason = training_status([0] * 10 + [1] * 10, 10)
    assert status == "ready"
    assert reason == ""


def test_split_hash_is_order_invariant_but_role_sensitive():
    membership = pd.DataFrame({
        "sample_key": ["s2", "s1"],
        "role": ["test", "fit"],
    })
    assert split_hash(membership) == split_hash(membership.iloc[::-1])
    changed = membership.copy()
    changed.loc[0, "role"] = "fit"
    assert split_hash(membership) != split_hash(changed)


def test_group_contract_filters_qc_and_preserves_parent_child_boundaries():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = _subjects()
    qc = pd.DataFrame({
        "dataset_id": "adhd",
        "sample_key": subjects["sample_key"],
        "atlas_id": "HO112",
        "qc_status": "pass",
    })
    failed_key = subjects.iloc[0]["sample_key"]
    qc.loc[qc["sample_key"] == failed_key, "qc_status"] = "fail"

    result = build_split_group(subjects, qc, "HO112", "adhd", "LOSO", config)
    tasks = result["tasks"]
    membership = result["membership"]
    assert failed_key not in set(membership["sample_key"])
    assert set(membership.columns) == {
        "dataset_id", "atlas_id", "protocol", "task_id", "sample_key", "role", "split_hash"
    }
    outer_tasks = tasks.loc[tasks["task_level"] == "outer"]
    outer_membership = membership.loc[membership["task_id"].isin(outer_tasks["task_id"])]
    assert outer_membership.loc[outer_membership["role"] == "test", "sample_key"].value_counts().eq(1).all()

    for inner in tasks.loc[tasks["task_level"] == "inner"].itertuples(index=False):
        child = membership.loc[membership["task_id"] == inner.task_id]
        parent = membership.loc[membership["task_id"] == inner.parent_task_id]
        assert set(child.loc[child["role"] == "test", "sample_key"]) == set(
            parent.loc[parent["role"] == "test", "sample_key"]
        )
        assert set(child.loc[child["role"] == "train", "sample_key"]).isdisjoint(
            child.loc[child["role"].isin(["validation", "test"]), "sample_key"]
        )
        assert set(child.loc[child["role"] == "validation", "sample_key"]).isdisjoint(
            child.loc[child["role"] == "test", "sample_key"]
        )
        assert split_hash(child) == inner.split_hash


def test_group_contract_rejects_subject_qc_identity_mismatch():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = _subjects()
    qc = pd.DataFrame({
        "dataset_id": "adhd",
        "sample_key": subjects["sample_key"].iloc[:-1],
        "atlas_id": "HO112",
        "qc_status": "pass",
    })
    try:
        build_split_group(subjects, qc, "HO112", "adhd", "LOSO", config)
    except ValueError as error:
        assert "sample_key sets differ" in str(error)
    else:
        raise AssertionError("identity mismatch was not rejected")


def test_nested_plan_has_strict_parent_lineage_and_reconstructable_hashes():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    subjects = _subjects()
    qc = pd.DataFrame({
        "dataset_id": "adhd",
        "sample_key": subjects["sample_key"],
        "atlas_id": "HO112",
        "qc_status": "pass",
    })
    group = build_split_group(subjects, qc, "HO112", "adhd", "LOSO", config)
    nested = build_nested_task_plan(
        subjects, qc, "HO112", "adhd", "LOSO", config, group
    )
    assert set(nested["task_level"]) == {
        "outer", "base_oof", "base_c_tuning", "meta_oof",
        "meta_base_oof", "meta_base_c_tuning",
    }
    assert len(nested) == 3 * 186
    indexed = nested.set_index("task_id", drop=False)
    for task in nested.loc[nested["task_level"] != "outer"].itertuples(index=False):
        assert task.parent_task_id in indexed.index
    target = nested.loc[nested["task_level"] == "meta_base_c_tuning"].iloc[0]
    member = reconstruct_nested_task_membership(
        target["task_id"], nested, subjects, group["membership"], config
    )
    assert split_hash(member) == target["split_hash"]
    meta_task = indexed.loc[target["meta_task_id"]]
    meta_member = reconstruct_nested_task_membership(
        meta_task["task_id"], nested, subjects, group["membership"], config
    )
    assert set(member.loc[member["role"] == "train", "sample_key"]).isdisjoint(
        meta_member.loc[meta_member["role"] == "validation", "sample_key"]
    )
