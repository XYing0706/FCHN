# FCHN_20260825 阶段 B Split Plan 实施计划

> **执行要求：** 使用 TDD 逐项实施；项目不是 Git 仓库，以 config/code/artifact SHA-256、staging、archive 和门禁作为版本/恢复边界。

**目标：** 在阶段 A 全部门禁通过的前提下，为 `4 atlas × 4 disease dataset × 2 protocol` 生成 32 个互相独立、无泄漏、可回连、可恢复的 split plan。

**架构：** `src/fchn_stage_b.py` 只做确定性 split 纯函数；`scripts/02_prepare_split_plans.py` 负责读取每个 Stage A cell、staging、32 组发布和 stage manifest；CSV 保存任务/成员，JSON 保存 hash/来源，不复制 FC 或人口学。每个 group 是最小加载单元。

**技术栈：** Python 3.13、Pandas、PyYAML、标准库 `hashlib/json/pathlib`、pytest。

---

## 文件职责

- Create `config/stage_b.yaml`：疾病数据集、atlas、protocol、seed、fold、fallback、最小类别数、输出模式。
- Create `config/stage_b.schema.json`：Stage B resolved config 的最小结构门禁。
- Create `src/fchn_stage_b.py`：稳定排序、LOSO/pooled outer、inner 5-fold/fallback、任务表、成员表和 split hash。
- Create `scripts/02_prepare_split_plans.py`：32 group staging、manifest、archive、stage 发布。
- Create `tests/test_stage_b.py`：纯函数、边界和确定性测试。
- Create `tests/test_stage_b_gates.py`：32 个真实 group、成员覆盖、泄漏、hash 和 `_SUCCESS` 门禁。
- Create `doc/PHASE_B_IMPLEMENTATION_20260826.md`：完成后的完整实施说明。
- Output `outputs/splits/<atlas>/<dataset>/<protocol>/`：每组独立 `tasks.csv,split_membership.csv,split_manifest.json,_SUCCESS`。
- Output `outputs/stage_b/`：`split_inventory.csv,stage_b_summary.md,stage_b_manifest.json,_SUCCESS`。

## Task 1：冻结配置合同

- [ ] 写失败测试，要求 4 atlas、4 disease dataset、2 protocol、`seed=20260625`、outer 10、inner 5、fallback 2、每类最少 10、fold 0-based、FCP 不在 disease dataset。
- [ ] 运行：

```powershell
python -m pytest tests\test_stage_b.py::test_stage_b_config_is_frozen -q -p no:cacheprovider
```

- [ ] 写 `stage_b.yaml/schema.json`，使测试通过。seed 来源必须记录为父项目正式 `configs/fchn_latefusion.toml`，不能伪称用户另行指定。

## Task 2：实现 outer split 纯函数

- [ ] 写 LOSO RED：每个排序后 site 一次 outer-test；test 只有该 site；fit 无该 site；每个样本恰好 test 一次。
- [ ] 写 pooled RED：在每个 `site_id×label` 层内，以 `sha256(seed|context|sample_key)` 稳定排序并 round-robin 到 10 个 test fold；输入行重排不改变结果；每层 fold 计数差不超过 1。
- [ ] 实现最小函数：

```python
def stable_round_robin(frame, strata, n_splits, seed, context): ...
def make_outer_assignments(subjects, protocol, config): ...
```

- [ ] 每次只运行对应 RED，再运行整个 `test_stage_b.py`。

## Task 3：实现 inner 5-fold 与一次 fallback

- [ ] 写 RED：inner 输入只能是当前 outer-fit；requested 5 折按 `site_id×label` round-robin；每个 inner train/validation 不重叠且并集等于 outer-fit。
- [ ] 写 RED：任一 requested inner-train 单类别或任一类少于 10 时，整组改为一次 2 折 label-stratified fallback。
- [ ] 写 RED：fallback 仍不合格时，outer/inner task 均为 `invalid_untrainable`，不生成常数分类器状态。
- [ ] 实现：

```python
def make_inner_assignments(outer_fit, outer_task_id, config): ...
def training_status(labels, minimum_per_class): ...
```

- [ ] 固定 reason code：`INNER_REQUESTED_UNTRAINABLE_FALLBACK_USED`、`INNER_FALLBACK_UNTRAINABLE`、`TRAIN_CLASS_COUNT_LT_10`。

## Task 4：建立任务与成员合同

- [ ] 写 RED，要求每个 outer task 用 `fit/test` role；每个 inner task用 `train/validation/test` role；inner test 精确等于 parent outer-test；inner train/validation 只来自 parent fit。
- [ ] `task_id` 固定为：

```text
<atlas>__<dataset>__<protocol>__outer<3位fold>__main
<outer_task_id>__inner<2位fold>
```

- [ ] `split_hash=sha256`，输入为按 `(role,sample_key)` 排序后的 UTF-8 文本 `role<TAB>sample_key<LF>`。
- [ ] `tasks.csv` 只保存 task 元数据、role 计数、label 计数、site×label 聚合 JSON、seed、policy、status/reason 和 split hash；不复制逐被试人口学。
- [ ] `split_membership.csv` 只保存 group/task/sample/role/split hash；每个 group 单独存储。

## Task 5：32 组 staging 发布

- [ ] 写真实输入 RED：每个 group 只能读取对应 `outputs/cells/<dataset>/<atlas>/subjects.csv` 和 `qc_subject.csv`；两者按 sample_key 一一对应，只保留该 atlas 的 QC pass；FCP 拒绝进入。
- [ ] 实现 `scripts/02_prepare_split_plans.py`：默认拒绝覆盖；`--replace-existing` 将旧 `outputs/splits` 与 `outputs/stage_b` 移入同一 archive；全部 32 组先 staging，stage `_SUCCESS` 最后可见。
- [ ] 每个 `split_manifest.json` 保存 Stage A stage/cell/subjects/QC hash、config/code hash、task/membership hash和计数。
- [ ] `stage_b_manifest.json` 逐组保存 current split manifest path/hash，并保存 Stage A parent manifest hash和实施文件 hash。

## Task 6：真实门禁

- [ ] 验证 32/32 group，目录集合精确等于 4×4×2。
- [ ] 验证 QC pass 全覆盖且每名样本 outer-test 恰好一次；QC fail 不出现。
- [ ] 验证 LOSO site 隔离和 pooled site×label 计数平衡。
- [ ] 验证所有 inner 子集、parent、status、fallback 和 split hash。
- [ ] 验证所有 source/artifact/implementation hash 当前有效，两级 `_SUCCESS` 固定内容正确。
- [ ] 运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests -q -p no:cacheprovider
```

只有 0 failure 后写 stage B `passed` 结论并进入说明文档。

## Task 7：阶段 B 实施说明

- [ ] 逐文件解释 config、schema、src、script、tests、每组输出、stage 输出、字段、尺寸、命令、实际 task/group 计数、fallback/invalid 统计、hash、恢复和限制。
- [ ] 明确 `Stage A subjects+QC → Stage B membership/tasks → Stage C outer-fold FCHN` 的字段级关系。
- [ ] 用独立 reader 只读新文档，修复会导致 Stage C 泄漏或成员误读的歧义。

## 自检

- 无 `TBD/TODO`；
- FCP 只作为 Stage A/C normative reference，不进入 Stage B；
- split 不读取 FC/TS 数值；
- 每个 group 独立加载，不合并跨 dataset/atlas 大文件；
- 任何 test/validation sample 不得出现在同一 task 的 fit/train；
- 不因小 site 或单类别 test/validation 删除样本；
- 不训练模型、不计算性能、不根据结果修改 split。
