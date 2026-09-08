# 阶段 C 设计：outer-fold FCHN 闭环

## 1. 目标与门禁

阶段 C 在阶段 A 的单一 `dataset×atlas` 输入单元和阶段 B 的 32 个 split group 上逐 outer fold 执行完整 FCHN。每个 fold 独立保存结果和状态哈希；不合并 FC 数值，不修改 A/B 产物。阶段 C 只在 `outputs/stage_a/_SUCCESS`、`outputs/stage_b/_SUCCESS`、父 manifest/hash 和 nested task lineage 通过时启动。

## 2. 输入

* `outputs/cells/<dataset>/<atlas>/`：`fc_source.json`（源 NPZ 路径和 hash）、`subjects.csv`、`qc_subject.csv`、`edge_manifest.csv`、`cell_manifest.json`。
* `outputs/stage_a/common_edge_<atlas>.csv`：跨五个数据集稳定 edge UID 交集；只作为列索引，不复制 FC。
* `outputs/splits/<atlas>/<dataset>/<protocol>/`：`tasks.csv`、`split_membership.csv`、`nested_tasks.csv`、group manifest 和 `_SUCCESS`。
* FCP 同一 atlas cell 仅用于 normative healthy anchor，不进入疾病标签训练。
* `config/stage_c.yaml`：全部科学参数、sex codebook 快照和存储合同。

FC 源为非 object NPZ 的 `X[N,E]` edge 向量；阶段 C 按 `edge_uid→matrix_position` 精确回连。结构性缺失 ROI/edge 不被重编号。被试级缺失协变量不猜测填补：保留 `sample_key` 和原始行序，对应 view 标为 `ineligible/MISSING_REQUIRED_COVARIATE`，最终 Meta 只预测三视图特征全部有限的行。

## 3. 单 outer fold 方法

1. 从 nested task 递归重建 Base OOF、Base C-tuning、strict Meta OOF 的 train/validation/test，并核对 `split_hash`。
2. 疾病 discriminative 分支使用 `age, age², sex, mean_fd, log(scan_length)`；共同 normative 分支使用 `age, age², sex, log(scan_length)`。连续协变量仅在当前训练集合标准化，ADHD 使用官方 PDF `0=female,1=male`→`1,0`，其余数据集使用 `1=male,2=female`→`0,1`。
3. 每个实际训练集合逐 edge 中位数填补；Ridge `alpha=1` 带截距，只减中心化协变量效应并保留训练特征均值；Scaler/PCA/KMeans/方差均只在该训练边界拟合。
4. FC 使用原始疾病 edge；HOFC 从当前已处理 FC 重建 ROI 矩阵、行中心化/归一化并计算 profile correlation，PCA 最大 128；normative 在 common edge 上用 FCP + outer-train HC 建立 KMeans anchor，`K_eff=min(8,floor(H/10))`，H<10 invalid，局部 n<3 回退总体方差，收缩 0.10，输出固定 10 summaries。
5. Base Logistic 为 L2、无 class weight；Base C 网格 `[0.003,0.01,0.03,0.1,0.3,1,3]`，按 pooled OOF log-loss 选 C，平局取小 C。Meta 输入严格为 3 logits + 10 normative summaries=13 维；Meta C 网格 `[0.03,0.1,0.3,1,3]`，仅用 strict Meta OOF 选择；Platt 只在 strict Meta OOF logit 上拟合。
6. 选参后在完整 outer-train 重拟合，outer-test 只 transform/predict。保存 predictions、normative edge deviation/summary、模型数组状态和 fold manifest；释放临时矩阵。

## 4. 输出与尺寸

目录：`outputs/stage_c/folds/<atlas>/<dataset>/<protocol>/<outer_task_id>/`。

* `predictions.csv`：每个 outer-test sample×view（FC/HOFC/normative/full_fchn）一行，含 hard prediction、label、raw/calibrated probability、logit、三视图 selected C、Meta C、task/status/reason、train/validation/test hash 和 ROI/edge/state hash；不写人口学。
* `normative_scores.npz`：固定宽度 Unicode `sample_key[test]`、`edge_uid[common_E]`，以及 `edge_z[test,common_E]`、`summary[test,10]`、`nearest_prototype[test]`；非 object、`allow_pickle=false`。
* `fcp_crossfit_audit.csv`：每名 FCP 被试的 site-aware 5-fold health-only 自排除审计（fold、参考计数、身份 hash、`self_excluded`、分数有限性），不含人口学字段。
* `model_state.npz`：本 fold 必要的数值系数/均值/尺度/PCA/anchor 数组；不跨 fold 复用。
* `fold_manifest.json`：A/B/config/source/ROI/edge/task hash、C 数值状态 hash、shape/count/status。
* `_SUCCESS`：`stage_c_fold_ready`。所有 outer folds 完成后才写 stage 级 manifest；阶段 D 才汇总指标、bootstrap 和 biomarker 频率。

## 5. 执行与恢复

`scripts/03_run_stage_c.py --pilot` 只运行一个可指定 group 的 outer fold，作为计算和边界验收；`--all` 按 428 个 outer task 独立运行，已完成 fold 自动跳过，默认拒绝覆盖。失败只清理当前 staging fold；不得删除既有 fold。所有阶段 C 新增文件均在本项目根目录，源 `SSL/data` 只读。

阶段 C 输出是阶段 D 的逐 fold predictions、normative score 和状态 hash 输入；不得在阶段 C 中根据中间结果改 QC、split、C 网格或选择 biomarker。
