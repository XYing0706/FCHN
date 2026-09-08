# FCHN_20260825 阶段 B Split Plan 实施说明

> 2026-08-26 修订：本说明以当前正式产物为准。旧版仅含 `tasks.csv`/`split_membership.csv` 的版本已归档；当前版本新增严格 nested task lineage，阶段 B 门禁和全项目测试均重新运行通过。

日期：2026-08-26  
项目根：`C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`  
阶段状态：**passed**  
阶段级完成标记：`outputs/stage_b/_SUCCESS`，内容为 `stage_b_ready`

## 1. 阶段定位与结论

阶段 B 是五条实施主线中的第二条，唯一任务是把阶段 A 的 canonical subjects 和逐 atlas QC pass 集合转换为可审计、无泄漏、可确定性重建的 split plan。它不读取 FC/TS 数值，不改变 ROI/edge 身份，不复制人口学，也不训练模型。

本阶段完成并通过门禁：

- `4 atlas × 4 disease dataset × 2 protocol = 32` 个独立 group；
- `428` 个 outer task、`2140` 个 inner task，共 `2568` 个 task，全部 `ready`；
- QC fail 被排除，未进入任何 membership；
- `LOSO` 每个 outer-test 只含一个 site；
- `pooled10_site_label` 在每个 `site_id × label` 层内按稳定 hash round-robin 到 10 折；
- inner requested 5 折全部满足每个 inner-train 两类各至少 10 个样本，因此本次真实数据没有使用 fallback，也没有 `invalid_untrainable`；
- 全部项目测试：原版 `29 passed`；补充严格 nested lineage 后当前全套为 `31 passed`。

阶段 B 的 `passed` 表示 split 文件、来源引用、代码 hash 和门禁链均通过；它不表示模型性能，也不表示任何数据已被填补或训练。

## 2. 输入、只读边界与最小加载单元

### 2.1 直接输入

每个 group 只读取自己的阶段 A cell：

```text
outputs/cells/<dataset>/<atlas>/subjects.csv
outputs/cells/<dataset>/<atlas>/qc_subject.csv
outputs/cells/<dataset>/<atlas>/cell_manifest.json
outputs/cells/<dataset>/<atlas>/_SUCCESS
outputs/stage_a/stage_a_manifest.json
outputs/stage_a/_SUCCESS
```

阶段 A 的 `subjects.csv` 固定 15 列，阶段 B 只消费：

```text
dataset_id, sample_key, site_id, label
```

阶段 A 的 `qc_subject.csv` 固定 13 列，阶段 B 只消费：

```text
dataset_id, sample_key, atlas_id, qc_status
```

两张表按 `sample_key` 必须一一对应；dataset、atlas 也必须与请求的 group 一致。输入身份集合不一致、重复 `sample_key`、未知 QC 状态、缺少 QC pass 样本都会硬失败，不静默补齐。

### 2.2 只读和隐私边界

- `C:\XY\FedTopo-Brain\CHyCR_20260621` 及 `SSL\data` 只读借鉴；本阶段新增文件只在 FCHN_20260825 内。
- Stage B 不打开 `fc_source.json` 指向的 FC 数组，不打开 TS 数值，不读取 ROI/edge 大表；因此不会把一个数据集或一个图谱的大矩阵合并到 split 文件。
- `split_membership.csv` 必须包含 `sample_key` 才能回连，但不包含 age、sex、mean FD 或其他人口学字段。脚本日志和阶段摘要只输出计数、状态和 hash，不输出被试级记录。
- FCP 是 Stage A 已准备的 normative 参考，不属于四个疾病 split 数据集，故没有 FCP Stage B group。

### 2.3 32 个 group

| 维度 | 值 |
|---|---|
| atlas | `HO112`, `AAL116`, `Dosenbach160`, `CC200` |
| disease dataset | `adhd`, `abide`, `abide2`, `mdd` |
| protocol | `LOSO`, `pooled10_site_label` |
| variant | `main` |
| group 目录 | `outputs/splits/<atlas>/<dataset>/<protocol>/` |

单个 group 是 Stage C 的最小 split 加载单元。不同 atlas、dataset、protocol 的任务和 membership 不合并。

## 3. 配置合同

### 3.1 `config/stage_b.yaml`

该文件是 resolved config，实际使用值不依赖隐式默认值：

| 配置 | 实际值和含义 |
|---|---|
| `stage_a_manifest/success` | 阶段 A 父 manifest 与成功标记的相对路径；启动前检查内容和 hash |
| `atlases` | 四套 atlas；决定 16 个疾病 `dataset × atlas` cell |
| `disease_datasets` | `adhd, abide, abide2, mdd`；明确排除 FCP |
| `protocols` | `LOSO`, `pooled10_site_label` |
| `variant` | `main`，写入 task 与 group manifest |
| `seed` | `20260625` |
| `seed_source` | 父项目正式 `C:\XY\FedTopo-Brain\CHyCR_20260621\configs\fchn_latefusion.toml`；这是已有正式配置中的值，不是本阶段猜测的新随机数 |
| `outer.pooled_splits` | 10 |
| `outer.pooled_strata` | `[site_id, label]` |
| `inner.requested_splits` | 5 |
| `inner.requested_strata` | `[site_id, label]` |
| `inner.fallback_splits` | 2 |
| `inner.fallback_strata` | `[label]` |
| `inner.minimum_train_per_class` | 10；只检查 train，不因小 validation/test 删除样本 |
| `identity.fold_index_base` | 0；所有 fold 编号从 0 开始 |
| `identity.cross_dataset_key` | `[dataset_id, sample_key]`；跨数据集不得把相同 subject 字符串当成同一人 |
| `identity.task_id_separator` | `__` |
| `storage.copy_demographics/copy_fc` | 均为 `false`；split 只保存身份和角色，不复制大数据或人口学 |

### 3.2 `config/stage_b.schema.json`

该 JSON 是配置结构门禁，要求上述 atlas/dataset/protocol 数组、seed、outer/inner 参数、identity 和 storage 字段存在，并约束数值类型、最小折数和 fold 基准。它不重新解释数据，也不覆盖 YAML 中的实际值。

当前实施文件 SHA-256（小写）为：

```text
config/stage_b.yaml          7458041435d9272d5b780446cbb9d78054e929ec64b8e5757b6589fc26b42240
config/stage_b.schema.json   cae578fd728e45fd5d67c803d41bdba4531982ab9b0f98a207d719598f705cbc
```

## 4. Split 方法细节

### 4.1 稳定排序和 round-robin

对每个样本构造：

```text
rank_key = SHA256(f"{seed}|{context}|{sample_key}")
```

在指定 strata 内按 `rank_key, sample_key` 的稳定顺序排列，再将第 `k` 个样本分配到 `k mod n_splits`。输入 CSV 行重排不会改变结果；同一 sample、seed、context 和 strata 得到同一 fold。

### 4.2 Outer protocol

**LOSO**：将 `site_id` 按字典序映射为 `outer_fold=0..S-1`。该 fold 的 test 只含一个 site，其余 site 为 fit；每个 pass sample 恰好成为 test 一次。

**pooled10_site_label**：在每个 `site_id × label` 层内用上述稳定排序，round-robin 到 `outer_fold=0..9`。每一层的 10 个 fold 计数最大差不超过 1；不因小 strata 删除样本。

### 4.3 Inner protocol 和唯一 fallback

每个 outer task 只用自己的 outer-fit 构造 inner 分配。先按 `site_id × label` 请求 5 折；对每个 inner fold 检查：

```text
inner_train = outer_fit - inner_validation
label 0 count >= 10 且 label 1 count >= 10
```

只要任一 requested inner-train 不满足，就整一个 outer task 触发一次 label-stratified 2-fold fallback。fallback 仍不满足时，相关 outer/inner task 标记：

```text
task_status = invalid_untrainable
reason_code = INNER_FALLBACK_UNTRAINABLE
```

不训练常数分类器，不再进行第三次回退。训练类别不足的纯函数诊断码固定为 `TRAIN_CLASS_COUNT_LT_10`；group 层在 fallback 仍失败时使用 `INNER_FALLBACK_UNTRAINABLE`。若 fallback 成功，reason code 为 `INNER_REQUESTED_UNTRAINABLE_FALLBACK_USED`，policy 为 `label_stratified_2fold_fallback`。本次真实 32 组没有触发任何 fallback。

### 4.4 Task 和 role

outer task ID 固定为：

```text
<atlas>__<dataset>__<protocol>__outer<3位fold>__main
```

outer task roles 只有：

```text
fit  = 当前 outer-test 之外的全部 QC pass 样本
test = 当前 outer fold 的 QC pass 样本
```

inner task ID 固定为：

```text
<outer_task_id>__inner<2位fold>
```

inner task roles 只有：

```text
train      = 当前 inner validation 之外的 outer-fit 样本
validation = 当前 inner fold 的 outer-fit 样本
test       = 精确重复 parent outer-test
```

`test` 重复写入 inner membership 是有意的审计设计：Stage C 可以只加载一个 inner task，仍能知道最终 outer test 边界；它不代表 test 参与训练。

### 4.5 Split hash

每一个 task 独立计算：先取该 task 的 `(role, sample_key)`，按 role、sample_key 排序，拼接 UTF-8 文本：

```text
role<TAB>sample_key<LF>
```

对完整文本计算 SHA-256。`split_hash` 对成员行重排不敏感，对 role 改变敏感；task 表、membership 表和 manifest 必须引用同一个值。

## 5. 源码、脚本和测试

| 文件 | 任务 | 输入 | 输出/作用 | 执行命令 |
|---|---|---|---|---|
| `src/fchn_stage_b.py` | 阶段 B 纯函数 | subjects 三列、配置 | 验证身份；生成 outer/inner fold；组装 task/membership；计算 split hash | 被脚本和测试导入，不单独写数据 |
| `scripts/02_prepare_split_plans.py` | 阶段 B 主 CLI | Stage A 当前 cell、Stage B config | staging 生成 32 组、group manifest、inventory、stage manifest、`_SUCCESS`，并支持 archive | `$env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Users\CQQ\anaconda3\python.exe' scripts\02_prepare_split_plans.py` |
| `config/stage_b.yaml` | resolved 参数 | 已冻结路径/协议/折数/seed | 提供唯一运行参数 | 由 CLI 读取 |
| `config/stage_b.schema.json` | 配置结构门禁 | YAML 结构 | 防止缺字段或类型漂移 | 由 `test_stage_b.py` 检查关键合同 |
| `tests/test_stage_b.py` | 纯函数 TDD | 合成 subjects/config | 9 项配置、LOSO、pooled、fallback、trainability、hash、组合同测试 | `... -m pytest tests/test_stage_b.py -q -p no:cacheprovider` |
| `tests/test_stage_b_gates.py` | 真实发布门禁 | 当前 Stage A、32 组 CSV/JSON | 3 项聚合门禁：stage/group/hash、QC/outer、inner parent-child | `... -m pytest tests/test_stage_b_gates.py -q -p no:cacheprovider` |

当前 SHA-256：

```text
src/fchn_stage_b.py                 0a212208d12ec2cca1bac66c7ec2d62af7f33d805145853bce90b60e2256eef6
scripts/02_prepare_split_plans.py  9de2afd10d8b55985ca108953d62d8734672297712c1062b8d2e6c1a65c815cc
tests/test_stage_b.py              2212ca2247aeb93de9ca6925ce999953182bf05b5c788007f64cc67452ed4c31
tests/test_stage_b_gates.py        10b880b351dcdb395d57f7771ebd59c869128eff4f0845943ff7b19eec3b7412
```

脚本没有复制 FC/TS。它先验证 Stage A `_SUCCESS`、stage manifest 和 cell manifest/artifact hash，再读取 subjects/QC；全部结果写入 `outputs/.staging/stage_b_<uuid>/`，成功后才 rename 到正式目录。

## 6. Group 输出文件

位置：`outputs/splits/<atlas>/<dataset>/<protocol>/`，每个目录独立包含：

| 文件 | 数据形式/尺寸 | 含义 | 下一步用途 |
|---|---|---|---|
| `tasks.csv` | UTF-8 CSV，31 列；行数为该 group 的 outer task + inner task | task 层级、parent、fold、policy/status/reason、各 role 计数、label 计数、site×label 聚合 JSON、seed、split hash | Stage C 选择 outer task/inner task，决定合法 train/validation/test 集合 |
| `split_membership.csv` | UTF-8 CSV，7 列；每个 task-role-sample 一行 | dataset/atlas/protocol/task/sample/role 的可回连成员表及 hash | Stage C 按 task 加载当前 cell 的 FC 和对应成员 |
| `split_manifest.json` | 小型 JSON | group 来源、配置 hash、任务/成员 artifact hash、聚合计数 | 审计单个 group 是否由当前 Stage A 和当前代码生成 |
| `_SUCCESS` | 一行文本 | `stage_b_split_ready` | 表示该 group 的两个 CSV 和 manifest 已完整写出 |

`tasks.csv` 的固定 31 列为：

```text
task_id,parent_task_id,task_level,dataset_id,atlas_id,protocol,variant,
outer_fold,inner_fold,held_out_site_id,inner_policy,task_status,reason_code,seed,
fit_count,train_count,validation_count,test_count,
fit_label0_count,fit_label1_count,train_label0_count,train_label1_count,
validation_label0_count,validation_label1_count,test_label0_count,test_label1_count,
fit_site_label_counts,train_site_label_counts,validation_site_label_counts,
test_site_label_counts,split_hash
```

不存在的 role 计数写 0；site×label 字段是按 site、label 排序的聚合 JSON 数组，不是逐被试记录。`inner_fold` 对 outer 行为空，`held_out_site_id` 仅 LOSO 有值；pooled outer 不伪造 held-out site。

`split_membership.csv` 固定 7 列：

```text
dataset_id,atlas_id,protocol,task_id,sample_key,role,split_hash
```

它不包含 age、sex、mean FD、label 或 site，也不复制 FC。需要 label/site 时必须回连同一 dataset×atlas 的 Stage A `subjects.csv`，不能从另一个 atlas 借用。

`split_manifest.json` 顶层关键字段为：

```text
stage,status,atlas_id,dataset_id,protocol,variant,seed,
config_path,config_sha256,sources,counts,artifacts
```

`sources` 包含当前 `stage_a_manifest.json`、当前 cell `cell_manifest.json`、`subjects.csv`、`qc_subject.csv` 的相对项目路径和 SHA-256；`artifacts` 包含 `tasks.csv` 与 `split_membership.csv` 的 bytes/hash。manifest 不自哈希；group `_SUCCESS` 在 manifest 之后写出。

## 7. 阶段级输出

位置：`outputs/stage_b/`

| 文件 | 形式/尺寸 | 表示什么 |
|---|---|---|
| `split_inventory.csv` | CSV，32 行 | 每个 group 的 QC pass/fail、outer/inner task 数、ready/invalid/fallback 数、group manifest、CSV bytes/hash |
| `stage_b_summary.md` | Markdown，32 行 group 聚合表 + 总计 | 仅输出计数和状态，便于人工快速核验 |
| `stage_b_manifest.json` | JSON | 32 个当前 group manifest 路径/hash、Stage A 父 manifest hash、config hash、实施文件 hash、总计和 stage artifact hash |
| `_SUCCESS` | 一行文本 | `stage_b_ready`；Stage C 允许启动的必要发布标记 |

本次实际总计：

```text
groups                       32
outer tasks                 428
inner tasks                2140
ready tasks                2568
fallback outer tasks          0
invalid_untrainable tasks    0
```

每个 pooled group 恒为 10 outer + 50 inner；LOSO group 的 outer 数等于该 atlas 下 QC pass 样本实际出现的 site 数，inner 数为 outer 数 × 5。示例 `HO112/adhd/LOSO` 为 7 outer、35 inner、843 QC pass、1 fail；`HO112/adhd/pooled10_site_label` 为 10 outer、50 inner、843 pass、1 fail。所有其他实际值以 `split_inventory.csv` 为准，不通过手工摘要替代机器清单。

`stage_b_manifest.json` 的实施文件 hash 为：

```text
config/stage_b.yaml          7458041435d9272d5b780446cbb9d78054e929ec64b8e5757b6589fc26b42240
config/stage_b.schema.json   cae578fd728e45fd5d67c803d41bdba4531982ab9b0f98a207d719598f705cbc
src/fchn_stage_b.py          ab17f2692ebd0bc111ad994abe13f4fe233cf62ab0f2c13daaa510bb0e73fd3a
scripts/02_prepare_split_plans.py
                              9de2afd10d8b55985ca108953d62d8734672297712c1062b8d2e6c1a65c815cc
tests/test_stage_b.py         b8270ecef0002a842685ff42b88361cef79c10ad19e85d77b96582710314ddbd
tests/test_stage_b_gates.py   10b880b351dcdb395d57f7771ebd59c869128eff4f0845943ff7b19eec3b7412
```

当前 stage manifest 文件本身 SHA-256 为：

```text
outputs/stage_b/stage_b_manifest.json
3fa2bad88bc1e68500bed9d920805effb78a6cd18c50ea20d555969e4a0f9432
```

该 hash 是外部核对值；manifest 内不嵌入自身 hash。JSON 使用 UTF-8、2 空格缩进和 key 排序；CSV hash 针对脚本实际写出的磁盘 bytes。

## 8. 发布、恢复与信任边界

### 8.1 正常发布

1. CLI 验证阶段 A stage/cell `_SUCCESS` 和 manifest/artifact hash；
2. 在 `outputs/.staging/stage_b_<uuid>/` 生成全部 32 group；
3. 每个 group 先写 `tasks.csv`、`split_membership.csv`、`split_manifest.json`，最后写 group `_SUCCESS`；
4. 全部 group 完成后写 `split_inventory.csv`、summary、stage manifest，最后写 stage `_SUCCESS`；
5. 将 staging 的 `splits` 和 `stage_b` 目录移动到正式 `outputs/`。

默认命令若发现正式输出已存在会拒绝覆盖：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\CQQ\anaconda3\python.exe' scripts\02_prepare_split_plans.py
```

显式需要重建时才使用：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\CQQ\anaconda3\python.exe' scripts\02_prepare_split_plans.py --replace-existing
```

旧的 `outputs/splits` 与 `outputs/stage_b` 会整体移动到 `outputs/archive/stage_b_<UTC>_<suffix>/`，并写 `archive_manifest.json` 记录原路径、归档路径和旧 stage manifest hash。恢复时必须整体恢复两目录，先核对 archive manifest，再重新运行全部 Stage B 门禁；不能只恢复一个 group 或只恢复 stage manifest。

### 8.2 中断和篡改处理

staging 失败会清理本次新建的 staging 目录，正式目录不应出现 `stage_b_ready`。发布中断若只留下 `splits` 或只留下 `stage_b`，由于阶段 `_SUCCESS` 或 32 组集合不完整，门禁会拒绝启动 Stage C；下一次使用 `--replace-existing` 完整重建。

manifest/hash 是本机目录内的可复现审计边界，不是远程签名。`_SUCCESS` 是“完整写出后可见”的激活标记，不是密码学防篡改证明。跨主机发布和签名属于阶段 E，不能把当前标记当作签名。

## 9. 门禁与验证记录

阶段 B 专项命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\CQQ\anaconda3\python.exe' -m pytest tests\test_stage_b.py -q -p no:cacheprovider
& 'C:\Users\CQQ\anaconda3\python.exe' -m pytest tests\test_stage_b_gates.py -q -p no:cacheprovider
```

结果分别为 `9 passed`、`3 passed`。全项目命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\CQQ\anaconda3\python.exe' -m pytest tests -q -p no:cacheprovider
```

结果：修订前为 `29 passed`；补充 nested lineage 后当前全套为 `31 passed`。

门禁覆盖：

1. 配置的四 atlas、四 disease dataset、两 protocol、seed、折数、每类最少 10 和 0-based fold；
2. 纯函数 LOSO site-exclusive、pooled10 分层平衡和输入顺序不变；
3. requested inner 5 折、一次 fallback、fallback 失败的 `invalid_untrainable` 语义；
4. 32 个 group 集合精确匹配，stage/group `_SUCCESS` 内容精确；
5. 每组 Stage A source hash、tasks/membership artifact bytes/hash 当前有效；
6. QC pass 全覆盖 outer-test 恰好一次，QC fail 不进入 membership；
7. LOSO fit/test site 隔离，pooled 每个 site×label 的 10 折计数差不超过 1；
8. inner train/validation 并集等于 parent fit，inner test 精确等于 parent outer-test，角色不重叠；
9. 每 task 的 membership hash 与 task 表一致；ready task 的 train 两类各至少 10；
10. stage manifest 的父 Stage A hash、config hash、代码/测试 hash 和逐组 manifest hash 当前有效。

## 10. 阶段 A → 阶段 B → 阶段 C 字段级接口

### 10.1 阶段 A 输出是本阶段输入

| Stage A 文件/字段 | Stage B 使用 |
|---|---|
| `subjects.csv: dataset_id,sample_key,site_id,label` | 构造 outer/inner；`sample_key` 是唯一成员身份，跨 dataset 回连键为 `(dataset_id,sample_key)` |
| `qc_subject.csv: sample_key,qc_status` | 当前 atlas 只保留 `pass`；fail 只在计数和审计中保留 |
| `cell_manifest.json` | 验证 subjects/QC 当前 hash，并锁定 Stage A cell 来源 |
| `stage_a_manifest.json` | 父版本边界；Stage B manifest 逐 group 回连其 hash |
| `roi_manifest.csv/edge_manifest.csv` | Stage B 不改变、不复制；Stage C 读取时仍按稳定 ROI/edge identity 回连 |
| `fc_source.json` | Stage B 不打开；Stage C 依据 cell manifest 和 source hash 加载单一 dataset×atlas FC |

### 10.2 本阶段输出是下一阶段输入

本阶段每个 `outputs/splits/<atlas>/<dataset>/<protocol>/` group 的：

- `tasks.csv` 是 Stage C 的 task 元数据输入：选择 `task_id`、`outer_fold`、`inner_fold`、`task_status`、`seed` 和角色计数；
- `split_membership.csv` 是 Stage C 的成员输入：按 `task_id` 取 `train/validation/test` 或 `fit/test` 的 `sample_key`；
- `split_manifest.json` 是 Stage C 启动前的来源/代码/hash 审计输入；
- `outputs/stage_b/stage_b_manifest.json` 和 `_SUCCESS` 是 Stage C 允许启动的阶段级父边界。

Stage C 必须：

1. 对每一个 task 重新回连同一 `dataset × atlas` 的 Stage A subjects；不得把另一个 atlas 的 QC 集合借来；
2. 按 `sample_key` 从当前 cell 的 FC 源加载，并用 Stage A `edge_manifest.csv` 解释 edge；不得依据 membership 行顺序猜测 FC 列；
3. 对 outer task 只在 fit/train 内拟合预处理，不能用 outer test 或 inner validation 统计量；
4. 对 `invalid_untrainable` 任务停止训练并记录原因，不创建常数分类器；本次无此类 task，但接口保留该状态；
5. 保持 `dataset_id` namespace，不把跨 dataset 的同名 `sample_key` 合并；
6. 不重新生成或排序当前 split；若 task/membership hash 不匹配，先停机并回到 Stage B 审计。

因此，Stage B 输出的核心关系是：

```text
Stage A subjects + QC
        ↓  (pass filter, stable identity, deterministic fold)
Stage B tasks.csv + split_membership.csv + hashes
        ↓  (one task at a time, train-only fitting)
Stage C outer-fold FCHN closed loop
```

## 11. 限制和明确不做的事情

- 本阶段不执行 FC 清洗、缺失值填补、头动回归、模型训练、性能评估或跨 atlas 特征融合。
- 本阶段不因小 site、单类别 validation/test 或 FCP mean FD 缺失删除额外样本；只有阶段 A 已定义的 atlas-specific QC fail 被排除。
- 本次实际数据没有触发 fallback；fallback 规则仍以代码和测试固定，不能因为本次为 0 就从配置或文档删除。
- 任务 CSV 的 site×label JSON 是聚合摘要；需要具体成员时必须读取 membership 并回连 Stage A，而不是从聚合字段反推。
- 任务和 manifest 不自哈希；新鲜度由外部读取比较、artifact hash 和 `_SUCCESS` 顺序共同保证。
- `outputs/archive` 是可恢复边界，不是无限历史版本库；跨主机审计签名留给阶段 E。

阶段 B 已通过全部门禁，下一步是阶段 C：在不改变本阶段 split 的前提下，按每个 group 的 outer task 执行 FCHN 闭环。当前 group 还包含 `nested_tasks.csv` 的 Base OOF、Base C-tuning、strict Meta OOF、Meta Base OOF、Meta Base C-tuning 六层父子任务索引；成员按索引和 `partition_*` 字段确定性重建，不复制第二份大型成员表。

## 11. 严格 nested 补充

每个 non-root nested task 都有直接 `parent_task_id`，并保存 `outer_task_id`、`meta_task_id`、目的、分层、折数、train/validation/test 计数、各角色身份 hash 与 `split_hash`。正常 5 折情况下每个 outer 为 1 outer + 5 Base OOF + 25 Base C-tuning + 5 Meta OOF + 25 Meta Base OOF + 125 Meta Base C-tuning，共 186 个 nested rows；LOSO/pooled 的实际 outer 数以 `tasks.csv` 为准。`reconstruct_nested_task_membership()` 从父任务递归重建并核对 hash；阶段 C 不得自行重新划分。

新增文件说明：

| 文件 | 形式/尺寸 | 作用与阶段 C 输入 |
|---|---|---|
| `nested_tasks.csv` | UTF-8 CSV，固定 25 列；每行一个 nested task | 保存 Base/Meta 严格父子血缘、partition 上下文、折号、计数和身份哈希；不保存重复 sample 行 |
| `split_manifest.json` | JSON | `artifacts` 现在同时登记 `tasks.csv`、`split_membership.csv`、`nested_tasks.csv` 的 bytes/SHA-256；`counts` 增加 nested 总数和各层计数 |
| `split_inventory.csv` | CSV，32 行 | 增加 `nested_tasks`、`nested_invalid_untrainable_tasks`、nested artifact bytes/hash |

## 12. 当前复核命令与结果

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest tests/test_stage_b.py -q -p no:cacheprovider
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest tests/test_stage_b_gates.py -q -p no:cacheprovider
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest tests -q -p no:cacheprovider
```

结果分别为 `10 passed`、`4 passed`、`31 passed`。当前正式 stage manifest 为新版代码/配置/Stage A 父 manifest 的 hash；旧版可从 `outputs/archive/stage_b_20260826T091619Z_985e445a/` 整体恢复，但恢复后必须重新运行以上三条命令。

## 13. 2026-08-30 稳定身份修订

ABIDE 的 Stage A `sample_key` 和 FC `subject_ids` 是 7 位带前导零字符串。旧 `02_prepare_split_plans.py` 未指定 CSV dtype，pandas 将其推断为整数并在 membership 中写成 5 位；旧门禁也以默认推断读取两侧，因此未发现词法身份损失。该问题不改变成员数量或分折统计，但违反稳定身份回连合同，必须修复。

修订内容仅有三项：Stage B 读取 `subjects.csv/qc_subject.csv` 时强制 `sample_key/subject_id` 为字符串；新增 `test_split_membership_preserves_stage_a_sample_key_lexemes`；所有 Stage B 身份门禁同样以字符串读取。32/32 组已原子重建，外层 428、内层 2,140、nested 79,608、fallback/invalid 均保持原值。最终 Stage B 全门禁与 Stage C 单元联合回归为 `23 passed in 172.41s`；旧版保存在 `outputs/archive/stage_b_20260829T184749Z_3ddff9bf/` 和 `outputs/archive/stage_b_20260829T190946Z_2ab9d9ea/`。

Stage C 必须以字符串 dtype 读取 `split_membership.csv`，并与 Stage A/FC 做精确 identity 回连；禁止使用去前导零、数值转换或模糊匹配。
