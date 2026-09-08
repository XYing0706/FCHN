# FCHN_20260825 阶段 C outer-fold FCHN 实施说明

- 文档更新：2026-09-01
- 项目根目录：`C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`
- 阶段状态：`in_progress`
- 完成判据：428/428 个 outer fold 均为 exact-fresh，`outputs/stage_c/stage_c_manifest.json.status=passed`，且 `outputs/stage_c/_SUCCESS` 内容为 `stage_c_ready`

## 1. 阶段定位与结论

阶段 C 读取阶段 A 已发布的独立 `dataset × atlas` 单元和阶段 B 已冻结的 split plan，按 outer fold 完成 FC、HOFC、normative、strict Meta late fusion 与 Platt 校准。阶段 C 不重新划分被试、不修改 QC、不跨数据集合并 FC、不汇总跨 fold 指标，也不选择 biomarker；跨 fold 评估和 biomarker 分析属于阶段 D。

全量合同为 4 图谱 × 4 疾病数据集 × 2 protocol，共 32 个 group、428 个 outer task、2,140 个 inner task、79,608 条 nested task。当前服务器首批只启用 `HO112,AAL116`，共 16 个 group、214 个 outer task、1,070 个 inner task、39,804 条 nested task。每个图谱均为 8 个 group、107 个 outer task。

截至 2026-09-01 本地复核：15/428 exact-fresh，413 missing，无 stale、partial 或 staging；首批两图谱口径为 15/214 exact-fresh，199 missing。这 15 个均属于 HO112。`stage_c_manifest.json` 和阶段级 `_SUCCESS` 均不存在，符合尚未完成的状态。

服务器最近一次用户回报为：首批两图谱 4/214 exact-fresh、210 missing，canary 尾部仍有 1 个 AAL116 worker，`first_error=no_error`，正式 `run` driver 尚未启动。该服务器快照与本地 15 折来自不同主机和不同实现 hash，不能相加，也不能据此宣称 Stage C 已完成。

## 2. 输入、只读边界与最小计算单元

### 2.1 直接输入

| 输入 | 形式与粒度 | 用途与约束 |
|---|---|---|
| `outputs/cells/<dataset>/<atlas>/fc_source.json` | 单 cell JSON 引用 | 指向只读源 FC NPZ；不复制 FC；以 `allow_pickle=false` 读取 `X[N,E]`、`subject_ids[N]`、`roi_indices[R]` |
| 同目录 `subjects.csv` | `N × 15` CSV | 以字符串 `sample_key` 回连 label、site、age、sex、scan length、mean FD 和 provenance |
| 同目录 `roi_manifest.csv`、`edge_manifest.csv` | 稳定身份 CSV | 以 `edge_uid → matrix_position` 精确回连矩阵列；结构性缺失 ROI/edge 不重编号 |
| `outputs/stage_a/common_edge_<atlas>.csv` | atlas 级共同 edge 表 | normative 分支的共同列空间；只保存 edge 身份，不保存跨数据集 FC |
| `outputs/splits/<atlas>/<dataset>/<protocol>/tasks.csv` | group 任务表 | outer/inner task、fold、状态、reason 和 split hash |
| 同目录 `split_membership.csv` | 成员表 | outer fit/test 和 nested task 的 `sample_key` 身份 |
| 同目录 `nested_tasks.csv` | 六级 lineage 表 | Base OOF、Base C-tuning、Meta OOF、Meta-base OOF/C-tuning；阶段 C 只读重建，不重新随机 split |
| `outputs/cells/fcp/<atlas>/` | 独立 FCP cell | 只作 normative 健康参照，不进入疾病 label 训练，不属于 4 个疾病任务数据集 |
| `outputs/stage_a/stage_a_manifest.json` | 阶段 A 发布合同 | 必须为 `passed`；其 hash 进入 Stage C run hash |
| `outputs/stage_b/stage_b_manifest.json` | 阶段 B 发布合同 | 必须为 `passed`；其 hash 进入 Stage C run hash |
| `config/stage_c.yaml` | 冻结 YAML | 图谱、疾病数据集、protocol、seed、协变量、模型网格、执行和存储合同 |
| `config/stage_c.schema.json` | JSON Schema | 要求关键配置字段存在，禁止静默猜测缺省配置 |

### 2.2 最小计算与发布单元

最小科学计算单元是一个 `atlas × disease dataset × protocol × outer_task_id`。每个 outer fold 独立加载所需 cell 和 split 身份，独立拟合所有预处理器与模型，独立写 staging 目录，成功后原子发布为 fold 目录。任何 fold 的估计量均不得复用于另一 fold。

最小服务器调度单元仍是一个 outer fold。并行度只是同时运行多个相互独立的 outer fold，不改变每个 fold 的训练/测试边界、方法或输出。

### 2.3 只读、隐私与身份边界

- 阶段 A/B 产物只读；Stage C 不修改 `outputs/cells/`、`outputs/stage_a/` 或 `outputs/splits/`。
- `sample_key`、`edge_uid` 和 task lineage 都按字符串读取；不得让 CSV 自动类型推断破坏前导零身份。
- 日志只打印 task、计数、shape、状态和 hash；不打印被试列表或逐人 phenotype。
- 结果不复制 age、sex、site、mean FD 等人口学列；label 以 `sample_key` 从阶段 A 权威 subjects 回连。

## 3. 配置合同

### 3.1 `config/stage_c.yaml`

当前任务轴为：

```yaml
atlases: [HO112, AAL116, Dosenbach160, CC200]
disease_datasets: [adhd, abide, abide2, mdd]
protocols: [LOSO, pooled10_site_label]
variant: full_fchn
seed: 20260625
```

核心方法和执行参数为：

```yaml
preprocessing:
  imputation: edgewise_train_median
  ridge_alpha: 1.0
  discriminative_covariates: [age, age_squared, sex, mean_fd, log_scan_length]
  normative_covariates: [age, age_squared, sex, log_scan_length]
  missing_covariate_policy: exclude_with_reason
views:
  fc_pca_max: 0
  hofc_pca_max: 128
  normative_residual_pca_max: 32
  normative_summary_count: 10
normative:
  max_prototypes: 8
  minimum_health_reference: 10
  k_rule_divisor: 10
  fcp_crossfit_splits: 5
models:
  solver: liblinear
  base_c_grid: [0.003, 0.01, 0.03, 0.1, 0.3, 1, 3]
  meta_c_grid: [0.03, 0.1, 0.3, 1, 3]
  selection_metric: pooled_log_loss
  tie_break: smaller_c
  platt_c: 1.0
execution:
  minimum_train_per_class: 10
  tuning_workers: 2
  resume: true
  overwrite: false
```

配置中的 4 个 atlas 是完整阶段合同。服务器 `ACTIVE_ATLASES=HO112,AAL116` 只限制当前调度批次，不修改 Stage C 科学配置，也不把 214 折伪装成完整 428 折。

### 3.2 当前配置与实现指纹

| 文件 | SHA-256 |
|---|---|
| `config/stage_c.yaml` | `7c66f94a1e15354820de33f637535018af99c92da568af28d59314f198adecc3` |
| `config/stage_c.schema.json` | `d643c4e70f112a4557b4dced0d8eb8c73ba5b8cacd65cdd9075ad867ae9cb614` |
| `scripts/03_run_stage_c.py` | `7068bcf515265c534179149240007e58156916aed6b38e4d6849dfbdc9a11765` |
| 本地 `src/fchn_stage_c.py` | `7e5cbd517ba92b28df8e4b4236a70b38916ce55653bb051a7fba6e02bc383f82` |
| `outputs/stage_a/stage_a_manifest.json` | `185f8a2aa4f0eadcf42790f87cf629e11bec01df1dfcbfba177df22b0b0e0859` |
| `outputs/stage_b/stage_b_manifest.json` | `f1a5412474809a7720ca0e9819d385a958b8f71597d09b4d55b48a12a9297f15` |

这些 hash 是 2026-09-01 本地复核值。任一上游 manifest、配置、runner 或 src 变化后，已有 fold 必须按新 run hash 重新分类；stale fold 不得被 `resume` 静默复用。

服务器为解决 Pandas 跨平台读取 `matrix_position` 的兼容问题，当前应安装 `FCHN_server/server_patch_stage_c_matrix_position/src/fchn_stage_c.py`，SHA-256 为 `9ba10bacd018a1a05a4ad7b3242a6e47318a944fb54429d922a3e198be75f5a3`。这是服务器专用 v2 补丁，原始本地源码未修改。服务器 fold 必须以服务器实际 src hash 审计，不能与本地 fold 混算为同一 run。

## 4. 方法细节

### 4.1 资格与协变量

疾病 FC/HOFC 分支使用 `age, age², canonical sex, mean_fd, log(scan_length)`；normative 分支不使用 mean FD。缺失所需协变量的样本只在对应 view 排除，不猜测填补。输出仍保留该 `sample_key`，对应 view 写 `task_status=ineligible`、`reason_code=MISSING_REQUIRED_COVARIATE`，预测值为空；最终 Meta 只对三视图特征全部有限的 test 行预测，并按原始行序回填。

ADHD 官方 codebook 冻结快照 `config/demographic_metadata/ADHD-200_PhenotypicKey.pdf` 规定 raw `0=female,1=male`，映射为 canonical `male=0,female=1`；其他数据集 raw `1=male,2=female` 映射为 `0,1`。

### 4.2 Fold-local 预处理

每个真实训练边界独立拟合：逐 edge 训练中位数填补、Ridge `alpha=1.0` 带截距残差化、训练集 StandardScaler、必要的 PCA、KMeans 健康原型、局部/总体收缩方差和 Logistic。outer validation/test 只执行 transform/predict。唯一可复用缓存是同一 cell 内确定性的 common-edge 列切片，不缓存或跨 fold 复用任何估计量。

### 4.3 三个 Base view

- FC：处理后的原始 FC edge；主配置不做 PCA。
- HOFC：将 FC edge 还原 ROI 对称矩阵，对 ROI profile 行中心化和归一化，计算 profile correlation 并取上三角；PCA 最大 128。
- Normative：在 common-edge 空间对 `FCP HC + 当前训练边界的疾病 HC` 拟合健康 anchor。`K_eff=min(8,max(1,floor(H/10)))`；健康参考少于 10 时 invalid；cluster 少于 3 人时局部方差回退总体方差；收缩为 0.10，方差下限为 `1e-6`。输出逐 edge residual z 和固定 10 个 summary；prototype 编号只用于 fold 内诊断。

Base C 在 `[0.003,0.01,0.03,0.1,0.3,1,3]` 上按 C-tuning OOF pooled log-loss 选择，精确平局取较小 C。相互独立的 tuning task 使用有界两线程；外层并发和 fold 内 tuning 线程是两级不同的并行控制。

### 4.4 Strict Meta 与 Platt 校准

Meta 特征固定 13 维：FC logit、HOFC logit、normative logit和 10 个 normative summary。Meta folds 只用于 Meta C 网格 `[0.03,0.1,0.3,1,3]` 的 OOF pooled log-loss 选择和 Platt strict OOF logit。最终 Meta 训练使用顶层 Base OOF 对完整 outer-train 生成的每人一次 OOF 三视图特征；不能拼接五个 meta-train。三视图按唯一 `sample_key` 精确取交集并回连权威 label，重复身份直接失败。

选择完成后，三个 Base view 在完整 outer-train 重拟合并预测 outer-test；Meta 在一次性顶层 OOF 特征上拟合；Platt 只用 strict Meta-OOF logit 拟合，再校准 outer-test raw Meta probability。

### 4.5 FCP 自排除审计

每个 outer fold 对 FCP 建立 site-aware 5-fold health-only cross-fit 审计。每名 FCP 在自身 score 的 prototype、局部方差和收缩向量拟合中必须被排除。日志只保存 cross-fit fold、参考计数、拟合/留出身份 hash、`self_excluded` 和 `score_finite`。

## 5. 任务矩阵与实际执行顺序

### 5.1 本地原生 `--all` 顺序

`scripts/03_run_stage_c.py` 的实际循环为：

```python
for atlas in config["atlases"]:
    for dataset in config["disease_datasets"]:
        for protocol in config["protocols"]:
            for outer_id in tasks.csv 中 outer 行的文件顺序:
                执行一个 outer fold
```

因此，对“当前执行顺序是否是 for each 图谱，执行每个数据集”的回答是：**是，本地原生串行 `--all` 确实以图谱为最外层，逐个疾病数据集、逐个 protocol、逐个 outer fold 执行。** 精确顺序为：

1. atlas：`HO112 → AAL116 → Dosenbach160 → CC200`；
2. 每个 atlas 内 dataset：`adhd → abide → abide2 → mdd`；
3. 每个 dataset 内 protocol：`LOSO → pooled10_site_label`；
4. 每个 group 内 outer task：按 `tasks.csv` 中 outer 行顺序。

FCP 不在 dataset 循环中。它是每个图谱的 normative 健康参照，会在相应疾病 outer fold 内被读取。

### 5.2 服务器首批顺序与并行含义

服务器只调度 `ACTIVE_ATLASES=HO112,AAL116`。正式任务按以下 key 排序：

```text
(atlas 固定序号, dataset 字典序, protocol 字典序, task_id 字典序)
```

所以服务器首批 atlas 仍是 `HO112 → AAL116`，但每个 atlas 内的 dataset 顺序为 `abide → abide2 → adhd → mdd`，与本地 YAML 顺序不同；protocol 为 `LOSO → pooled10_site_label`，outer task 因编号补零而按 `outer000, outer001, ...` 递增。

默认 `PARALLEL_FOLDS=4` 表示调度器从这个有序队列取前 4 个缺失 fold 并行执行；任一 fold 完成后立刻补入下一个。因此进程列表中的 worker 数可在 4、3、2、1 之间短暂变化。出现第一个失败后不再启动新任务，但已在运行的 worker 会被收尾并记录，`first_error.json` 保存首个失败。

排序差异只影响先后和吞吐，不改变 task 身份、split、模型或结果合同。若希望本地与服务器完成顺序也完全一致，应统一排序器；当前科学正确性只要求同一 task 的输入、实现 hash 和输出合同一致。

### 5.3 Canary 不是正式全批次

服务器 canary 优先选择尚未 exact-fresh 的既定真实门禁：

- `HO112__adhd__LOSO__outer000__main`；
- `HO112__adhd__LOSO__outer003__main`；
- `HO112__abide__LOSO__outer000__main`；
- 再为每个 active atlas 选择首个尚未选中的缺失任务。

已 fresh 的 canary 会跳过，因此实际 worker 数和任务数随已有产物变化。canary 全部成功并通过 `tests/test_stage_c_pilot_gate.py` 后，才运行正式 `run` 补齐当前 active batch。

## 6. 源码、脚本、测试与服务器薄部署层

| 文件 | 职责 |
|---|---|
| `src/fchn_stage_c.py` | Ridge 状态、HOFC、C 选择、13 维 Meta、canonical sex、health anchor、FCP folds、cell/common-edge 读取和 Logistic；不负责阶段调度 |
| `scripts/03_run_stage_c.py` | 本地唯一 Stage C 科学执行入口；执行单 fold/pilot/all，fresh 判断、staging 原子发布、fold/stage manifest |
| `tests/test_stage_c.py` | Ridge、HOFC、summary、Meta、sex、FCP、并行确定性、身份、前导零、数值状态、resume 和非有限行分流门禁 |
| `tests/test_stage_c_pilot_gate.py` | ADHD 常规 fold、outer003 缺失协变量、ABIDE 前导零身份的真实产物门禁 |
| `FCHN_server/fchn_contracts.py` | 服务器配置、任务 inventory、语义 reference、preflight、fold fresh 分类 |
| `FCHN_server/fchn_runtime.py` | canary、P-fold 调度、任务计时、首错、批次发布和 finalize |
| `FCHN_server/fchn_server.py` | 薄命令行入口；不实现模型、QC 或 split |
| `FCHN_server/bootstrap_server.sh` | 加载 `server.env`、冻结 BLAS 线程并调用部署入口 |
| `FCHN_server/README_SERVER_DEPLOYMENT.md` | 上传、配置、预检、canary、run、status、后续图谱和 finalize 操作手册 |

部署到 Linux 后，`FCHN_server` 包内容安装为项目根的 `server_deployment/`。服务器薄部署层只调用已有 A/B/C runner，不复制一套模型实现。

## 7. 每个 outer fold 的输出

目录：`outputs/stage_c/folds/<atlas>/<dataset>/<protocol>/<outer_task_id>/`。

### 7.1 `predictions.csv`

每个 outer-test sample 有 `fc`、`hofc`、`normative`、`full_fchn` 4 行。关键字段包括：

- 身份：`sample_key,task_id,outer_fold,split_path,variant,view,prediction_level`；
- 预测：`prediction,logit,probability,raw_probability,true_label`；
- 参数：`selected_c,selected_c_fc,selected_c_hofc,selected_c_normative,meta_c`；
- 边界 hash：`train_subject_hash,validation_subject_hash,test_subject_hash,roi_manifest_hash,edge_manifest_hash`；
- 状态 hash：`imputer_state_hash,ridge_state_hash,scaler_pca_state_hash,normative_state_hash`；
- 资格：`task_status,reason_code`。

### 7.2 `normative_scores.npz`

必须用 `allow_pickle=false` 读取：

- `sample_key[N_test]`：字符串行身份；
- `edge_uid[common_E]`：与阶段 A common-edge 表逐项一致；
- `summary[N_test,10]`：Meta 使用的 10 个 summary；
- `edge_z[N_test,common_E]`：阶段 D 连续异常分布和 biomarker 统计输入；
- `nearest_prototype[N_test]`：fold 内诊断编号。

### 7.3 `model_state.npz`

保存三视图 imputer、Ridge、scaler、PCA、Base Logistic、normative anchor、Meta 和 Platt 的非 object 数值状态。它用于恢复、hash 和阶段 D 审计，不作为跨 fold 共享模型。

### 7.4 `fcp_crossfit_audit.csv`

每个 FCP sample 一行，保存 cross-fit fold、参考计数、拟合/留出身份 hash、`self_excluded` 与 `score_finite`，不保存逐人人口学值。

### 7.5 `fold_manifest.json` 与 `_SUCCESS`

manifest 保存 task、状态、selected C、训练/验证/测试 hash、run hashes、上游输入 hashes、strict Meta train count、state keys 及 artifact bytes/SHA-256。fold `_SUCCESS` 内容只能是 `stage_c_fold_ready`。resume 同时核验 marker、manifest 和当前 run hash，不能只看目录或文件存在。

## 8. 阶段级与服务器部署输出

| 输出 | 产生时机与含义 |
|---|---|
| `outputs/stage_c/stage_c_manifest.json` | 仅完整 `--all` 扫描并确认 428/428 fresh 后发布；保存 expected/ready、run/A/B/config hashes 和 fold manifest hashes |
| `outputs/stage_c/_SUCCESS` | 仅完整阶段通过后写 `stage_c_ready` |
| `outputs/stage_c/stage_c_summary.md` | 阶段简要状态；不能替代 manifest 和 marker |
| `outputs/stage_c/logs/<task_id>.out/.err` | 服务器每个 task 独立日志 |
| `outputs/deployment/preflight_report.json` | 服务器依赖、配置、A/B 语义一致性和测试报告 |
| `outputs/deployment/task_timing.jsonl` | 每个服务器 task 的开始、结束、耗时、退出码和 marker 状态 |
| `outputs/deployment/first_error.json` | 当前调度批次首个失败；旧失败在重启前必须归档，不能把历史文件当当前错误 |
| `outputs/deployment/batches/<active_atlases>/batch_manifest.json` | 214/214 active folds exact-fresh 后的批次发布；`stage_c_complete=false`、`stage_d_allowed=false` |
| 同批次 `_SUCCESS` | 内容为 `stage_c_batch_ready`，仅代表当前两图谱批次完成 |

批次 marker 与阶段 marker 语义不同：214 折首批完成后仍不能进入阶段 D；四图谱 428 折完成并执行 `finalize` 后才发布阶段级 marker。

## 9. 发布、恢复与信任边界

### 9.1 正常发布

1. 每个 fold 先写同级 `.staging`。
2. 所有产物写完并完成 hash/shape 校验后，原子 rename 为正式 fold 目录。
3. 最后写 fold `_SUCCESS`。
4. 完整 428 折均 exact-fresh 后，`finalize` 调用原 runner `--all` 扫描并发布阶段 manifest 和阶段 `_SUCCESS`。

### 9.2 恢复与首错

- `resume=true` 只跳过 exact-fresh fold。
- stale、partial、staging 必须先定位原因并归档；默认 `overwrite=false`，不得覆盖证据。
- 服务器调度锁 `outputs/deployment/stage_c_scheduler.lock` 防止两个调度器同时写同一任务集。
- driver 消失时先检查 worker、`first_error.json`、task `.err` 和 `task_timing.jsonl`，再决定是否续跑。
- `nohup: ignoring input` 是正常提示，不是 Stage C 错误。
- `first_error.json` 只代表当前未归档的首错；修复并重新开始批次前应连同相关日志归档，否则监控会持续显示历史错误。

### 9.3 跨平台已确认问题及根因修复

1. **Launcher 缺失**：服务器曾调用未上传的脚本，根因是交付集合不完整。现统一上传并安装完整 `server_deployment/`，预检时验证所需文件。
2. **语义 reference mismatch**：实现、FC、subjects、ROI/edge/common-edge 和 split 一致，仅服务器重建的 20 个 `qc_subject` 摘要不同。现保留差异报告并使用服务器实际语义 reference；不以复制大量 A/B 文件掩盖差异。
3. **ABIDE 前导零身份**：CSV 自动推断把 7 位身份转成整数。现相关读取入口固定字符串 dtype，防止跨数据集回连失败。
4. **AAL116 `matrix_position='0.0'`**：Linux 服务器 Pandas 将位置列呈现为浮点字符串，本地路径曾直接接受数值。v1 错误地校验整个 edge manifest，遇到非共同 edge 的合法空位置而失败；v2 先选择 common edges，再要求所选位置为有限整数并转换。v2 已通过 3 项补丁测试及真实 AAL116/ABIDE 对齐：`X=(1085,6216)`，common space 为 `(1085,6105)`。服务器最近 canary 未再产生 `first_error`，但仍需等待 canary 和正式批次完成后才能确认全流程通过。

这些问题均来自部署合同、CSV dtype 和路径/文件集合的跨平台差异，不是 Stage C 数学流程不同。根本解决原则是：明确文件清单、路径只在配置层重写、身份和索引列固定 dtype、run hash 绑定实际实现、先 canary 后批量。

## 10. 门禁与验证记录

阶段 C 完成必须同时满足：

1. `tests/test_stage_c.py` 全部通过；
2. `tests/test_stage_c_pilot_gate.py` 对真实产物全部通过；
3. A/B manifest 为 `passed` 且语义 reference 预检通过；
4. 428 个 expected fold 均为 exact-fresh，无 missing/stale/partial/staging；
5. 每个 fold 的 marker、manifest、artifact hash、NPZ dtype/shape 和身份回连通过；
6. `stage_c_manifest.json.status=passed` 且 expected=ready=428；
7. 阶段 `_SUCCESS` 内容为 `stage_c_ready`。

已验证的关键回归包括：missing-covariate 行保留并标记 ineligible、ABIDE 前导零身份、strict Meta OOF、FCP self-exclusion、workers=1/2 概率确定性、AAL116 common-edge 位置 v2 转换。当前尚未满足第 4–7 项，所以阶段状态仍为 `in_progress`。

## 11. 执行命令

### 11.1 本地验证和原生全量

在项目根目录执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
python -m pytest tests/test_stage_c.py tests/test_stage_c_pilot_gate.py -q -p no:cacheprovider
python scripts/03_run_stage_c.py --pilot
python scripts/03_run_stage_c.py --all
```

### 11.2 服务器首批 HO112+AAL116

部署目录在服务器项目根中名为 `server_deployment/`。先停止旧 launcher/worker并完成 `server.env`，再依次执行：

```bash
bash server_deployment/bootstrap_server.sh verify-existing
bash server_deployment/bootstrap_server.sh canary
bash server_deployment/bootstrap_server.sh status
nohup bash server_deployment/bootstrap_server.sh run \
  > outputs/deployment/HO112_AAL116_driver.out \
  2> outputs/deployment/HO112_AAL116_driver.err &
echo $! > outputs/deployment/HO112_AAL116_driver.pid
```

实时检查：

```bash
bash server_deployment/bootstrap_server.sh status
cat outputs/deployment/first_error.json 2>/dev/null || echo no_error
tail -n 20 outputs/deployment/task_timing.jsonl
pgrep -af '03_run_stage_c.py|fchn_server.py'
```

`status` 的主判断字段是 active `exact_fresh/missing/stale/partial/staging`。worker 数只是瞬时并发状态；driver PID、单个日志为空或 `nohup` 提示都不能替代 fold fresh 计数。

### 11.3 后续两图谱与最终发布

首批 214 折发布后，将服务器 `ACTIVE_ATLASES` 改为 `Dosenbach160,CC200`，再次依次执行 `verify-existing → canary → run`。四图谱合计达到 428 exact-fresh 后执行：

```bash
bash server_deployment/bootstrap_server.sh finalize
```

少于 428 时 `finalize` 必须拒绝，不会补跑缺失任务。

## 12. 当前结果、时间口径与限制

本地当前完成率为 15/428=`3.50%`；按首批两图谱口径为 15/214=`7.01%`。本地已观察到的 13 个连续 fold 间隔约为 25.79–39.95 分钟，中位数 32.21 分钟；若该速度稳定，首批剩余 199 折串行约需 102.8–132.7 小时，即约 4.3–5.5 天。服务器 4-fold 并行的理论估计约为本地串行时间的四分之一，但只有服务器 `task_timing.jsonl` 积累足够成功样本后才能给出实测 ETA。

当前不可确认：Stage C 全量完成、跨 fold pooled/site/worst-site 性能、bootstrap/置换、校准汇总、biomarker 频率与方向一致性。运行期间严禁根据中间表现修改 QC、split、C 网格、KMeans、protocol 或 biomarker 规则。

## 13. 阶段 A → B → C → D 字段级接口

### 13.1 A/B 输出进入 C

- A `fc_source.json` 和 NPZ → C 的 `X,subject_ids,roi_indices`；
- A `subjects.csv` → C 的权威 label、site、协变量和 `sample_key`；
- A `roi_manifest.csv/edge_manifest.csv/common_edge_<atlas>.csv` → C 的 ROI/edge 身份和 normative 共同列；
- B `tasks.csv` → C 的 outer/inner task 合同；
- B `split_membership.csv/nested_tasks.csv` → C 的训练、测试和 strict nested lineage；
- A/B manifest hashes → C fold fresh 与恢复合同。

### 13.2 C 输出进入 D

- 各 fold `predictions.csv` → pooled/site/worst-site、校准、bootstrap 和置换评估；
- `normative_scores.npz` 的 `sample_key/edge_uid/edge_z/summary` → 连续异常分布和稳定 edge 统计；
- `model_state.npz` 与 state hash → 系数、方向和状态一致性审计；
- fold/stage manifest 与 `_SUCCESS` → 阶段 D 完整性和新鲜度门禁。

只有 428 个 fold 全部 exact-fresh 且阶段级发布完成后，阶段 D 才允许启动。