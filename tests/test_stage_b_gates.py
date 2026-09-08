from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "stage_b.yaml"
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fchn_stage_b import reconstruct_nested_task_membership, split_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_digest(values) -> str:
    payload = "".join(f"{value}\n" for value in sorted(map(str, values)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_same_identities(left, right, context: str) -> None:
    left_values, right_values = list(left), list(right)
    if len(left_values) != len(right_values) or _identity_digest(left_values) != _identity_digest(right_values):
        raise AssertionError(
            f"{context}: identity mismatch; left_count={len(left_values)}, "
            f"right_count={len(right_values)}, left_hash={_identity_digest(left_values)}, "
            f"right_hash={_identity_digest(right_values)}"
        )


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _expected_groups(config: dict) -> set[tuple[str, str, str]]:
    return {
        (atlas, dataset, protocol)
        for atlas in config["atlases"]
        for dataset in config["disease_datasets"]
        for protocol in config["protocols"]
    }


def test_stage_b_has_exactly_32_current_groups_and_fresh_stage_manifest():
    config = _load_config()
    stage_dir = PROJECT_ROOT / "outputs" / "stage_b"
    assert (stage_dir / "_SUCCESS").read_text(encoding="utf-8") == "stage_b_ready\n"
    manifest = json.loads((stage_dir / "stage_b_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stage"] == "B" and manifest["status"] == "passed"
    assert manifest["group_count"] == 32
    assert _sha256(PROJECT_ROOT / manifest["stage_a_manifest_path"]) == manifest["stage_a_manifest_sha256"]
    assert _sha256(PROJECT_ROOT / manifest["config_path"]) == manifest["config_sha256"]
    for relative, expected_hash in manifest["implementation_files"].items():
        assert _sha256(PROJECT_ROOT / relative) == expected_hash

    actual = {
        (record["atlas_id"], record["dataset_id"], record["protocol"])
        for record in manifest["groups"]
    }
    assert actual == _expected_groups(config)
    for record in manifest["groups"]:
        group_manifest = PROJECT_ROOT / record["split_manifest_path"]
        assert _sha256(group_manifest) == record["split_manifest_sha256"]


def test_every_group_has_fresh_sources_artifacts_and_success_marker():
    config = _load_config()
    for atlas, dataset, protocol in sorted(_expected_groups(config)):
        group_dir = PROJECT_ROOT / config["storage"]["group_pattern"].format(
            atlas=atlas, dataset=dataset, protocol=protocol
        )
        assert (group_dir / "_SUCCESS").read_text(encoding="utf-8") == "stage_b_split_ready\n"
        manifest = json.loads((group_dir / "split_manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "passed"
        assert (manifest["atlas_id"], manifest["dataset_id"], manifest["protocol"]) == (
            atlas, dataset, protocol
        )
        for source in manifest["sources"].values():
            assert _sha256(PROJECT_ROOT / source["path"]) == source["sha256"]
        for name, artifact in manifest["artifacts"].items():
            path = group_dir / name
            assert path.stat().st_size == artifact["bytes"]
            assert _sha256(path) == artifact["sha256"]


def test_split_membership_preserves_stage_a_sample_key_lexemes():
    config = _load_config()
    for atlas, dataset, protocol in sorted(_expected_groups(config)):
        cell_path = (
            PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "subjects.csv"
        )
        group_dir = PROJECT_ROOT / config["storage"]["group_pattern"].format(
            atlas=atlas, dataset=dataset, protocol=protocol
        )
        subjects = pd.read_csv(
            cell_path, keep_default_na=False, dtype={"sample_key": str}
        )
        membership = pd.read_csv(
            group_dir / "split_membership.csv",
            keep_default_na=False,
            dtype={"sample_key": str},
        )
        assert set(membership["sample_key"]) <= set(subjects["sample_key"]), (
            atlas, dataset, protocol
        )


def test_every_group_has_reconstructable_strict_nested_task_lineage():
    config = _load_config()
    expected_levels = {
        "outer", "base_oof", "base_c_tuning", "meta_oof",
        "meta_base_oof", "meta_base_c_tuning",
    }
    for atlas, dataset, protocol in sorted(_expected_groups(config)):
        group_dir = PROJECT_ROOT / config["storage"]["group_pattern"].format(
            atlas=atlas, dataset=dataset, protocol=protocol
        )
        nested = pd.read_csv(group_dir / "nested_tasks.csv", keep_default_na=False)
        membership = pd.read_csv(
            group_dir / "split_membership.csv",
            keep_default_na=False,
            dtype={"sample_key": str},
        )
        subjects = pd.read_csv(
            PROJECT_ROOT / "outputs" / "cells" / dataset / atlas / "subjects.csv",
            keep_default_na=False,
            dtype={"sample_key": str, "subject_id": str},
        )
        assert set(nested["task_level"]) == expected_levels
        assert nested["task_id"].is_unique
        task_ids = set(nested["task_id"])
        assert set(nested.loc[nested["task_level"] != "outer", "parent_task_id"]) <= task_ids

        deepest = nested.loc[nested["task_level"] == "meta_base_c_tuning"]
        for outer_id, outer_rows in deepest.groupby("outer_task_id", sort=False):
            leaf = outer_rows.iloc[0]
            rebuilt = reconstruct_nested_task_membership(
                leaf["task_id"], nested, subjects, membership, config
            )
            assert split_hash(rebuilt) == leaf["split_hash"]

            meta = nested.loc[nested["task_id"] == leaf["meta_task_id"]].iloc[0]
            meta_members = reconstruct_nested_task_membership(
                meta["task_id"], nested, subjects, membership, config
            )
            meta_validation = set(
                meta_members.loc[meta_members["role"] == "validation", "sample_key"]
            )
            leaf_train = set(rebuilt.loc[rebuilt["role"] == "train", "sample_key"])
            assert leaf_train.isdisjoint(meta_validation), outer_id


def test_qc_pass_outer_coverage_and_protocol_invariants():
    config = _load_config()
    minimum = int(config["inner"]["minimum_train_per_class"])
    for atlas, dataset, protocol in sorted(_expected_groups(config)):
        cell_dir = PROJECT_ROOT / "outputs" / "cells" / dataset / atlas
        subjects = pd.read_csv(
            cell_dir / "subjects.csv", dtype={"sample_key": str, "subject_id": str}
        )
        qc = pd.read_csv(cell_dir / "qc_subject.csv", dtype={"sample_key": str})
        passed = set(qc.loc[qc["qc_status"] == "pass", "sample_key"].astype(str))
        failed = set(qc.loc[qc["qc_status"] == "fail", "sample_key"].astype(str))
        group_dir = PROJECT_ROOT / config["storage"]["group_pattern"].format(
            atlas=atlas, dataset=dataset, protocol=protocol
        )
        tasks = pd.read_csv(group_dir / "tasks.csv", keep_default_na=False)
        membership = pd.read_csv(
            group_dir / "split_membership.csv",
            keep_default_na=False,
            dtype={"sample_key": str},
        )
        outer_ids = set(tasks.loc[tasks["task_level"] == "outer", "task_id"])
        outer = membership.loc[membership["task_id"].isin(outer_ids)]
        outer_test = outer.loc[outer["role"] == "test", "sample_key"].astype(str)
        _assert_same_identities(outer_test, passed, f"{atlas}/{dataset}/{protocol} outer-test")
        assert outer_test.value_counts().eq(1).all()
        assert not membership["sample_key"].astype(str).isin(failed).any()

        subject_index = subjects.set_index(subjects["sample_key"].astype(str))
        outer_tasks = tasks.loc[tasks["task_level"] == "outer"]
        if protocol == "LOSO":
            for task in outer_tasks.itertuples(index=False):
                member = membership.loc[membership["task_id"] == task.task_id]
                test_keys = member.loc[member["role"] == "test", "sample_key"].astype(str)
                fit_keys = member.loc[member["role"] == "fit", "sample_key"].astype(str)
                test_sites = set(subject_index.loc[test_keys, "site_id"].astype(str))
                fit_sites = set(subject_index.loc[fit_keys, "site_id"].astype(str))
                assert len(test_sites) == 1
                assert task.held_out_site_id in test_sites and task.held_out_site_id not in fit_sites
        else:
            sample_to_fold = {}
            for task in outer_tasks.itertuples(index=False):
                member = membership.loc[
                    (membership["task_id"] == task.task_id) & (membership["role"] == "test")
                ]
                sample_to_fold.update({str(key): int(task.outer_fold) for key in member["sample_key"]})
            assigned = subjects.loc[subjects["sample_key"].astype(str).isin(passed), [
                "sample_key", "site_id", "label"
            ]].copy()
            assigned["outer_fold"] = assigned["sample_key"].astype(str).map(sample_to_fold)
            for _, stratum in assigned.groupby(["site_id", "label"]):
                counts = stratum["outer_fold"].value_counts().reindex(range(10), fill_value=0)
                assert counts.max() - counts.min() <= 1

        for task in tasks.itertuples(index=False):
            member = membership.loc[membership["task_id"] == task.task_id]
            assert split_hash(member) == task.split_hash
            assert member["split_hash"].eq(task.split_hash).all()
            if task.task_level == "outer":
                assert set(member["role"]) == {"fit", "test"}
                continue
            assert set(member["role"]) == {"train", "validation", "test"}
            parent = membership.loc[membership["task_id"] == task.parent_task_id]
            _assert_same_identities(
                member.loc[member["role"] == "test", "sample_key"],
                parent.loc[parent["role"] == "test", "sample_key"],
                f"{atlas}/{dataset}/{protocol} child-test",
            )
            _assert_same_identities(
                member.loc[member["role"].isin(["train", "validation"]), "sample_key"],
                parent.loc[parent["role"] == "fit", "sample_key"],
                f"{atlas}/{dataset}/{protocol} child-fit",
            )
            assert member.groupby("sample_key").size().eq(1).all()
            if task.task_status == "ready":
                assert task.train_label0_count >= minimum and task.train_label1_count >= minimum
            else:
                assert task.task_status == "invalid_untrainable"
                assert task.reason_code == "INNER_FALLBACK_UNTRAINABLE"
