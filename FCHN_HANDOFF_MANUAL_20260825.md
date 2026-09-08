# FCHN 项目交接手册

**版本：** 2026-08-25  
**项目根目录：** `C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`  
**输入数据根目录：** `C:\XY\FedTopo-Brain\SSL\data`

本手册是新窗口开始实现 FCHN 时的唯一快速入口。旧项目 `FCHN_20260805` 仅作为历史参考，不得继续写入，也不得把新结果保存到 `C:\Users\CQQ\Documents\DA-DG`。

## 1. 项目背景与意义

多站点静息态 fMRI 的功能连接存在扫描协议、站点、样本量和质量差异。直接合并数据容易把站点差异误学为疾病信号，单一 FC 视图也难以同时表达一阶连接、高阶关系和相对健康状态的异常。

FCHN（Functional Connectivity + Higher-order + Healthy-anchor）旨在建立一个可复现、抗站点偏移、具有健康参照和严格验证边界的多视图分类流程。项目意义不只在于提高 AUC，还在于把数据身份、QC、nested CV、预测、异常连接生物标志物和个体连续异常评分放进同一条可审计链路。

## 2. 方法思路与亮点

### 2.1 三类视图

1. **FC**：ROI 两两 Pearson 相关，经 Fisher-z 后取上三角 edge，作为一阶连接主干。
2. **HOFC**：由 FC 派生的高阶连接关系；在训练边界内标准化并用 PCA 压缩，默认最大 128 维。PCA 只用于模型输入，不替换原始 edge identity；标志物解释仍回到原始 FC edge。
3. **FCP/healthy-anchor**：以 FCP 健康参考和当前疾病 outer-train 中的健康样本建立健康原型、方差和逐 edge 偏离，产生规范化残差及个体连续异常评分。FCP 只做健康参考，不进入疾病标签模型的训练成员。

### 2.2 融合与验证亮点

- 主 protocol 固定为 `LOSO` 和 `pooled10_site_label`。
- `LOSO`：每次留一站点作为 outer-test，其余站点为 outer-train。
- `pooled10_site_label`：在每个 `site × label` 层内确定性分成 10 折；9 折 outer-train，1 折 outer-test。
- 移除 `global_pooled10`，不再维护第三套全局随机分层协议。
- 所有估计型步骤在当前 inner-train 拟合；最终模型在完整 outer-train 重新拟合一次，outer-test 只 transform/predict。
- 多视图使用严格 OOF late fusion；Platt 校准只读取严格 Meta-OOF，不能使用 outer-test。
- 异常连接标志物和个体连续异常评分先在每个 outer fold 产生，全部 outer folds 完成后再汇总选择频率、方向一致性和跨站点验证。

## 3. 正式输入位置与数据集

所有原始输入均位于：

```text
C:\XY\FedTopo-Brain\SSL\data
```

| dataset_id | 目录 | 关键人口学/manifest | 主图谱输入 |
|---|---|---|---|
| `adhd` | `...\data\adhd` | `manifest_adhd.csv`、`ADHD200_Phenotypic_ChaoganYan.csv` | `HO112/AAL116/Dosenbach160/CC200_{fc,ts}.npz`、`roi_mask_adhd.csv` |
| `abide` | `...\data\abide` | `manifest_abide.csv`、ABIDE phenotype 文件 | 四套 atlas 的 FC/ts、`roi_mask_abide.csv` |
| `abide2` | `...\data\abide2` | `manifest_abide2.csv`、ABIDE2 phenotype 文件 | 四套 atlas 的 FC/ts、`roi_mask_abide2.csv` |
| `mdd` | `...\data\mdd` | `manifest_mdd.csv`、REST-meta-MDD phenotype 文件 | 四套 atlas 的 FC/ts、`roi_mask_mdd.csv` |
| `fcp` | `...\data\fcp` | `manifest_FCP.csv`、`FCP_RfMRIMaps_Info.csv` | 四套 atlas 的 FC/ts、`roi_mask_FCP.csv`、`Beijing\` |

四套 atlas 的执行顺序固定为 `HO112 → AAL116 → Dosenbach160 → CC200`。疾病数据集顺序固定为 `adhd → abide → abide2 → mdd`；FCP 是外部健康参考，不是第五个疾病数据集。

## 4. 身份、对齐和防止错位

### 4.1 被试身份

本项目当前五个 manifest 均没有 `session_id` 字段，且 6161 个原始 `subject_id` 在五个 dataset 之间没有重复。因此不人为引入不存在的 session 身份：`sample_key` 直接等于原始 `subject_id`，所有表同时强制保存 `dataset_id`。跨数据集连接时使用组合主键 `(dataset_id, sample_key)`，不能只依靠裸 `sample_key`。所有 ID 以字符串读写，禁止依赖 CSV 行号、NumPy 行号或数组位置。若未来输入出现多 session，必须另建 session-aware variant，不得静默覆盖当前身份规则。

人口学主表每个被试一行，至少包含：

```text
sample_key,dataset_id,subject_id,site_id,label,age,sex,scan_length,mean_fd,source_file,source_row_hash
```

FCP 的 176 名 mean FD 缺失保持为空，不填补、不伪造、不因该字段缺失删除；FCP 仍可参加 FC QC 和健康参考流程。

### 4.2 ROI 身份

每个 atlas 建立一个稳定的 ROI 清单。`roi_uid` 是不可变身份，`roi_original_index`、`roi_name`、`roi_label` 和解释来自原始脑图谱，删除 ROI 后不得重新编号。`matrix_position` 只是当前矩阵位置。

删除 ROI 后，剩余 ROI 的原始编号不变。例如原始 ROI 3 删除后，原始 ROI 4 仍记录为 `roi_original_index=4`，不能改写为新的 ROI 3。

### 4.3 Edge 身份

每条 edge 使用稳定的 `edge_uid`，并保存两个端点 `roi_uid_i`、`roi_uid_j`。矩阵列通过 edge manifest 解释，不允许仅凭列号猜测连接端点。每个 edge 必须能回溯到两个 ROI 的原始编号、label 和解释。

## 5. 极简 QC 方案（主分析）

QC 只处理有限性和身份/结构完整性，不使用标签或模型性能决定删除。主分析冻结以下参数：

```text
subject invalid_edge_ratio >= 0.05
    -> 排除该 atlas 下被试

任一 ROI 的 incident invalid edge ratio >= 0.30
    -> 排除该 atlas 下被试

两项均未触发
    -> 保留；训练折内对少量无效 edge 做逐 edge 中位数填补
```

`ROI incident invalid ratio` 是与该 ROI 相连的 edge 中无效边的比例，不是全脑 edge 比例。30% 是整名被试排除阈值，避免一个 ROI 大量依赖人为补齐后仍被当作可靠观测。

### 5.1 结构性 ROI

某 ROI 在数据集中不存在、mask 无法解析或无法按 identity 对齐时，在该 atlas 的共同 ROI 空间建立阶段统一标记为 `structural_unavailable` 并删除。不能对结构性不存在 ROI 插补。

### 5.2 零散 edge

通过被试级 QC 的样本仍可能有少量无效 edge。对当前 fit task：

- 逐 edge 中位数只在实际训练集合的有限值上拟合；
- validation、outer-test 和 FCP 只能使用已保存的训练 median transform；
- 训练集合中某 edge 没有任何有限值时，当前任务标记 `invalid_untrainable`，记录两个 ROI 端点，禁止删除列或填 0；
- 原本有限的观测值必须保持不变。

主流程不按每名被试删除不同 ROI，也不采用 fold-specific recurrent ROI 删除。后者如需研究，必须是独立 sensitivity variant，并保持原始 edge identity 对齐。

### 5.3 QC 记录

每个 atlas 一个 `qc_subject_<atlas>.csv`，每个被试一行：

```text
sample_key,atlas_id,qc_status,reason_code,invalid_edge_count,invalid_edge_ratio,
max_roi_invalid_ratio,max_invalid_roi_uid
```

`qc_status` 为 `pass` 或 `fail`。删除原因至少包括：

```text
TOTAL_EDGE_INVALID_GE_5PCT
ROI_INCIDENT_INVALID_GE_30PCT
STRUCTURAL_ROI_UNAVAILABLE
MISSING_REQUIRED_IDENTITY
```

被试删除是 atlas-specific：同一被试可在一个 atlas fail、另一个 atlas pass，但 `sample_key`、原始 subject_id、人口学和 label 永远不变。

## 6. 头动协变量规则

用户已确认：FCP 不执行头动协变量回归，其他疾病数据集执行头动回归。

### 6.1 疾病诊断分支

疾病 FC 的 Ridge 残差化协变量为：

```text
age + age^2 + sex + mean FD + log(scan_length)
```

Ridge、协变量标准化和残差化都只在当前实际训练集合拟合；validation、outer-test 和 FCP 只能 transform。疾病样本缺少 Ridge 必需协变量时标记为不合格并记录，不使用 FC Imputer 填补人口学字段。

### 6.2 Normative/FCP 共同分支

FCP 缺少完整 mean FD，不能把“疾病已去 mean FD”与“FCP 未去 mean FD”直接当作同一个健康参考空间。为保持疾病与 FCP 的共同可比性，默认 normative-common 分支使用两者都可获得的共同协变量：

```text
age + age^2 + sex + log(scan_length)
```

这意味着“其他疾病数据集做头动回归”主要适用于疾病诊断分支；normative-common 是为 FCP 可比性而定义的显式例外，不能在代码中悄悄把 mean FD 加回去。若未来要让 normative 分支也控制 mean FD，必须另建可用 FD 的 FCP 子集 variant，不能删除主分析中的 176 名 FCP 被试。

## 7. 实际执行流程（不是 20 个独立步骤）

必须区分两件事：旧规划中的 20 个 Stage 是代码模块、审计门禁和恢复边界；它们不是要求用户按 1–20 逐步执行的实验步骤，也不意味着每个 Stage 都要单独保存一套全量数据。真实实验按下面的外层闭环运行。

### 阶段 A：一次性准备全部最终输入（不按 protocol 重复）

必须先完成所有 `atlas × dataset` 单元的最终输入准备，再开始任何疾病 protocol 的模型训练。实际循环为：

```text
for atlas in [HO112, AAL116, Dosenbach160, CC200]:
    for dataset in [adhd, abide, abide2, mdd, fcp]:
        prepare_final_input(atlas, dataset)
```

对每个 `atlas × dataset` 单元完成一次：

1. 读取 `C:\XY\FedTopo-Brain\SSL\data` 中的 manifest、人口学、FC/时序和 ROI mask，建立 `subjects.csv`。
2. 按稳定 `roi_uid` 对齐四套 atlas，建立共同 ROI manifest 和 edge manifest；保存原始 nonfinite mask。
3. 执行只依赖被试自身数据的 subject-self QC：总体 invalid edge `>=5%` 或任一 ROI incident invalid `>=30%` 即在该 atlas 下排除被试。
4. 保存 QC 状态、删除原因和固定身份 hash。该 QC 结果可被 LOSO 与 `pooled10_site_label` 共同复用，因为它不使用标签、其他被试统计量或模型性能。

这一阶段不划分 outer fold，不拟合 imputer、Ridge、Scaler、PCA、KMeans 或分类器，也不产生模型结果。只有全部 20 个 `atlas × dataset` 单元均通过身份、ROI/edge、有限性和 QC 产物检查后，才进入阶段 B；“通过”不等于所有被试都必须保留。

### 阶段 B：为每个 protocol 建立一次 split plan

最终输入准备完成后，按疾病数据集进入模型循环。FCP 已在阶段 A 准备完成，但不作为疾病 dataset 执行分类 protocol。实际循环为：

```text
for atlas in [HO112, AAL116, Dosenbach160, CC200]:
    for disease_dataset in [adhd, abide, abide2, mdd]:
        for protocol in [LOSO, pooled10_site_label]:
            run_complete_protocol(atlas, disease_dataset, protocol)
```

其中 `run_complete_protocol(...)` 包含本节阶段 B 的 split plan、阶段 C 的全部 outer-fold 闭环和阶段 D 的该 protocol 汇总；不能只运行其中一个中间模块后把它当作 protocol 结果。

对每个 `atlas × disease dataset × protocol` 建立一次 split plan。outer split 规则见第 8 节；inner 统一采用 5 折，具体规则如下：

- `LOSO`：依次将一个站点作为 outer-test，其余站点作为 outer-train；
- `pooled10_site_label`：在每个 `site × label` 层内确定性分 10 折，每折 1 折 outer-test、9 折 outer-train。

FCP 不进入疾病 outer split；它只在需要 normative view 的 outer fold 中作为外部健康参考。split plan 保存 `task_id`、`sample_key`、fold role 和 split hash，不保存重复的人口学表。换言之，完整方法的最外层是 `atlas → disease dataset → protocol`，每个组合都独立完成全部 outer folds 后再进入下一个组合；FCP 的最终输入由阶段 A 共享复用。

#### Inner 5-fold 规则

每个 outer-train 内固定请求 5 个 inner folds，在每个 `site × label` 层内按稳定排序和固定 seed round-robin 分配。这样同时尽量保持 site 和 label 组成，且不需要为 inner 调参拆散 outer-test。

- validation fold 即使只有一个 label 也保留，使用逐样本 log-loss，不计算该 fold AUC；
- 每个实际 inner-train 必须包含两类且每类至少 10 人；
- 若 5 折分配导致某个 inner-train 单类别或低于每类 10 人，改用同一 parent train 的 2 折 label-stratified fallback，并记录 `inner_policy=label_stratified_2fold_fallback`；
- fallback 仍无法形成合格训练集合时，任务标记 `invalid_untrainable`，不训练常数分类器；
- 不删除小 site、不合并不同 site、不根据中间性能改变折数。

#### 阶段 B 的任务对象

一个可执行任务由以下字段唯一确定：

```text
task_id = atlas + disease_dataset + protocol + outer_fold + variant
```

每个任务保存 `fit/train/validation/test` 的 `sample_key` 集合、site×label 计数、父任务、随机种子和 split hash。QC fail 的被试不进入该 atlas 的训练或测试；QC pass 的单类别 site 不被静默删除，若它是 test/validation 则照常产生预测，但 AUC 记为 NA；实际 train 若只剩一个类别，则任务标记 `invalid_untrainable`，不训练常数分类器。

inner fold 只从当前 outer-train 产生。Base OOF、C-tuning 和 strict Meta OOF 都有自己的 `parent_task_id`，任何 validation/test 被试不得进入该任务的估计型预处理或模型拟合。这样 LOSO 和 `pooled10_site_label` 只改变 outer 成员，FCHN 的内部方法链保持一致。

### 阶段 C：真正反复执行的 outer-fold 闭环

对每一个 outer fold 执行以下完整闭环；完成当前 fold 后释放临时矩阵，只保留必要状态和 fold 结果：

```text
outer-train / outer-test 确定
    ↓
inner nested CV（只在 outer-train 内）
    ├─ inner-train 拟合 imputation、Ridge、Scaler、PCA、KMeans/variance
    ├─ 选择 base 超参数并生成无泄漏 OOF logits
    ├─ normative 健康参考 cross-fit
    └─ strict Meta OOF（如启用多视图融合）
    ↓
在完整 outer-train 上用已选参数重拟合最终链
    ↓
outer-test 只 transform → predict → score
    ↓
保存该 outer fold 的预测、真实 label、fold 身份、状态 hash、标志物和连续评分
```

具体地，imputation、协变量回归、标准化、PCA、KMeans、原型方差和特征选择均只能在当前实际训练集合拟合。最终 outer 模型不是直接使用某个 inner-train，而是在 inner 选择完成后用完整 outer-train 重新拟合。outer-test、validation 和 FCP 只能使用冻结参数 transform。

Normative 分支在每个 outer fold 使用 FCP 和该 fold 允许的 outer-train 健康样本建立参考；FCP 被试不能参与自身的健康 cross-fit 原型和方差估计。FCP 不进入疾病分类器的标签训练集合。

#### 阶段 C 的 FCHN 方法链

下面是每个 `atlas × disease dataset × protocol × outer fold` 内真正执行的 FCHN 细节。所有“拟合”均指当前任务允许的训练集合；validation、outer-test 和 FCP 只能使用对应冻结状态 transform。

**1. 建立两个特征空间**

- `discriminative`：使用当前 atlas 通过 QC 后的疾病 ROI/edge 空间；默认 FC/HOFC 可保留疾病 atlas 的 ROI 空间。
- `normative_common`：疾病数据与 FCP 的稳定 ROI 交集，按 `roi_uid` 和 `edge_uid` 精确排列；用于 FCP 健康锚定，不能按数组位置直接拼接。

**2. FC 视图**

```text
当前训练集合的 edge median imputation
    -> 疾病诊断分支 Ridge 残差化
    -> train-only StandardScaler
    -> 可选 train-only PCA（FC 主配置为 0）
    -> L2 Logistic Regression
```

Base C 在 inner/C-tuning OOF 上按 pooled log-loss 选择，平局选择较小 C；选定 C 后在完整 outer-train 重拟合，再预测 outer-test。主 C 网格为 `[0.003, 0.01, 0.03, 0.1, 0.3, 1, 3]`，主分类器不使用 class weighting；`balanced` 只能作为独立 variant。

**3. HOFC 视图**

原始脚本 `fchn_core.py::high_order_fc_from_fc_vectors` 的高阶构造为：

1. 将每名被试的上三角 FC edge 还原成 ROI×ROI 对称矩阵；
2. 对每个 ROI 的连接 profile 做行中心化；
3. 按行范数归一化；
4. 计算 ROI profile 两两相关的矩阵；
5. 取其上三角作为 HOFC edge 特征。

最终实现必须在当前 fold 的合法 FC 输入上执行该确定性变换，随后只在训练集合拟合 StandardScaler 和 PCA。主 HOFC PCA 最大 128 维，实际维数受训练样本数和特征数限制。PCA 只改变模型输入维度，不改变原始 `edge_uid`，因此 HOFC 结果不能直接冒充原始 FC edge 标志物。

**4. FCP normative/healthy-anchor 视图**

在 `normative_common` 空间内：

1. 用当前任务训练集合的共同协变量处理结果拟合 scaler；FCP 使用相同 scaler transform，FCP 不执行 mean FD 回归。
2. 健康参考为 `FCP HC + 当前 outer-train 的疾病 HC`；outer-test HC 不得进入。
3. 对健康参考执行 KMeans，主配置 `K=8`、`n_init=10`；若有效健康样本不足，K 必须降低并记录原因。
4. 对每个原型估计局部方差，并与健康总体方差按 `lambda=0.10` 收缩；方差设下限，禁止零方差除法。
5. 对每名被试分配最近原型，生成逐 edge standardized residual `z_edge`。
6. 由 residual/distance 生成 10 个固定 normative summaries：最近距离、平均距离、距离标准差、最近与次近原型 margin、距离倒数、RMS residual、绝对 residual 均值、绝对 residual 标准差、top 5% absolute residual 均值和正向 residual 比例。prototype ID 只作为诊断字段，不进入模型，因为 KMeans 编号跨 fold 没有稳定语义。
7. residual PCA 最大 32 维，只在当前训练 residual 上拟合；主 Meta 使用 10 个显式 summaries，可按预注册 variant 加入 residual PCs。

Normative base classifier 使用与 FC 相同的 L2 Logistic 训练边界。FCP 健康 cross-fit 时，某个 FCP 被试不能参与其自身原型、局部方差或收缩向量的估计。

**5. Strict late fusion 与校准**

Meta 输入由各 Base view 的 OOF logit 加上 normative summaries 组成：

```text
FC logit
+ HOFC logit（启用时）
+ Normative logit
+ 10 个预定义 normative summaries
```

Meta logistic 使用独立的 train-only 标准化和 Meta C 网格 `[0.03, 0.1, 0.3, 1, 3]`；最终 outer-test 只接收由完整 outer-train 拟合的各视图预测。Platt calibrator 只能用 strict Meta-OOF logit 拟合，再应用于 outer-test raw probability。

**6. 每个 outer fold 的最小结果**

至少保存：

```text
sample_key
outer_fold / task_id / split_path
view / prediction_level
prediction / probability / true_label
selected_c、meta_c
train/validation/test subject hash
roi_manifest_hash / edge_manifest_hash
imputer、Ridge、Scaler/PCA、normative state hash
task_status / reason_code
```

异常 edge、生物标志物和个体连续评分也按 outer fold 保存，但最终选择频率、方向一致性和跨站点结果必须等全部 outer folds 完成后再计算。

#### 原始脚本与最终方案的关系

阶段 C 的函数级参考来自：

```text
C:\XY\FedTopo-Brain\CHyCR_20260621\scripts\25_run_fchn_latefusion.py
C:\XY\FedTopo-Brain\CHyCR_20260621\src\chycr\fchn_core.py
C:\XY\FedTopo-Brain\CHyCR_20260621\src\chycr\health_anchor.py
C:\XY\FedTopo-Brain\CHyCR_20260621\scripts\01_build_features.py
C:\XY\FedTopo-Brain\CHyCR_20260621\configs\fchn_latefusion.toml
```

这些脚本是历史实现参考，不是新项目的直接运行入口。旧 `25_run_fchn_latefusion.py` 只实现 source-only LOSO、按 site-level mean AUC 选 C、非严格 Meta OOF，并且早期版本可在 split 前预计算 HOFC；新项目必须按本手册的 `LOSO + pooled10_site_label`、inner train-only 估计、pooled log-loss 选参和 strict nested Meta 规则重写。旧脚本的函数结构可复用，旧脚本的泄漏边界和协议不能原样复制。

### 阶段 D：全部 outer folds 完成后统一汇总

只有当前 `atlas × dataset × protocol × variant` 的全部 outer folds 完成后，才进行：

- pooled 与 site-level 指标汇总；
- worst-site、有效 fold/site 数和 NA reason；
- 标志物选择频率、方向一致性和跨站点复现；
- 个体连续异常评分的总体及站点分布；
- bootstrap CI、置换检验和校准指标。

不能在尚未完成全部 outer folds 时根据中间结果修改 QC 阈值、选择标志物或更换 protocol。

### 阶段 E：统一审计与发布

最后对整个 run 做一次身份、ROI/edge 顺序、fit boundary、有限性、OOF 覆盖、结果 schema 和 hash 的 round-trip 检查。staging 验收通过后原子发布，并写入 `_SUCCESS`。因此，实际执行是“准备一次 → protocol split → outer fold 闭环 → 全部 fold 汇总 → 发布”，而不是按 20 个 Stage 逐个手工运行。

## 8. Protocol 与评估

### 8.1 主 protocol

- **LOSO**：每个站点一次 outer-test；报告跨站点 macro、pooled 和 worst-site 结果。
- **pooled10_site_label**：每个 site×label 层内 10 折；每折 9/10 outer-train、1/10 outer-test。

训练集合必须同时包含两类且每类达到预设最小样本数；不能训练时退化成常数分类器。outer-test 或 validation 单类别仍生成预测，但 AUC 记为 NA，同时保留 log-loss、Brier、ACC 和存在类别的召回指标。

### 8.2 对比方法

公平比较至少包含：`logistic`、`refine_fc`、`refine_fc_brain`、`blockfusion_fc_brain`、`hanc_health_anchor` 和 FCHN 主模型。所有方法使用相同输入身份、QC 后人群、outer splits 和评估指标；方法特有预处理必须在各自训练边界拟合。

### 8.3 指标

主指标为按站点汇总的 AUC，同时报告 pooled AUC、worst-site AUC、ACC、BACC、敏感度、特异度、log-loss、Brier 和 ECE。比较使用按站点配对 bootstrap，保存 CI、经验 p 值和有效站点数。不得只报告 pooled AUC，因为站点与 label 混杂时 pooled ranking 可能包含站点比例信息。

### 8.4 标志物与连续异常评分

每个 outer fold 产生 held-out 预测、真实 label、异常 edge、方向和个体分数。全部 outer folds 完成后才汇总：

- edge/ROI 选择频率；
- 方向一致性；
- 有效 fold/site 分母；
- 跨站点复现；
- 健康 OOF 参考分布和置信区间。

主个体评分可使用 `NCDP_RMS = sqrt(mean(z_edge^2))`，再由健康 OOF mid-rank 转换为百分位。评分必须是 held-out 或 cross-fitted，不能用同一被试参与自身健康原型和方差估计。

## 9. 极简、可查看的存储方案

表格统一使用 **CSV**，便于 Excel 和文本工具查看；大型数值矩阵使用非 object **NPZ**，读取时固定 `allow_pickle=false`。不使用 pickle/joblib 保存模型状态。每个文件只保存本职责所需字段，不重复复制人口学、label 或 ROI 解释。

### 9.1 推荐目录

```text
FCHN_20260825/
├─ config/                 # resolved config、参数和 hash
├─ doc/                    # 本手册及正式规范
├─ src/                    # 身份、QC、预处理、模型库
├─ scripts/                # Stage/outer-fold 入口脚本
├─ tests/                  # 单元、合成、边界和 round-trip 测试
├─ outputs/
│  ├─ canonical/
│  ├─ splits/
│  ├─ qc/
│  ├─ fold_artifacts/
│  ├─ predictions/
│  ├─ biomarkers/
│  └─ reports/
└─ _SUCCESS               # 全部验收通过后的发布标记
```

### 9.2 最小文件集合

```text
canonical/subjects.csv
canonical/roi_manifest_<atlas>.csv
canonical/edge_manifest_<atlas>.csv
canonical/fc_<atlas>_<dataset>.npz
qc/qc_subject_<atlas>.csv
splits/splits_<protocol>.csv
predictions/predictions_<run_id>.csv
biomarkers/biomarkers_<run_id>.csv
reports/metrics_<run_id>.csv
```

各文件含义：

| 文件 | 内容 | 不应重复保存 |
|---|---|---|
| `subjects.csv` | `sample_key`、原始 subject、site、label、人口学、来源哈希 | 不重复保存到每个预测文件 |
| `roi_manifest_<atlas>.csv` | `roi_uid`、原始编号、name、label、description、status、删除原因、matrix_position | 不用位置代替身份 |
| `edge_manifest_<atlas>.csv` | `edge_uid`、两个 `roi_uid`、位置、状态、删除原因 | 不重复复制 ROI 解释 |
| `fc_*.npz` | 数值 FC、`sample_key_order`、manifest hash、shape | 不嵌入人口学和 label |
| `qc_subject_*.csv` | 每个被试的 QC 指标和 reason | 不再建立重复被试删除表 |
| `splits_*.csv` | `task_id`、fold、`sample_key`、role、split hash | 不复制完整人口学 |
| `predictions_*.csv` | `sample_key`、task、view、prediction、truth、状态、state hashes | `label` 从 subjects 回连，或仅保存审计副本但不作为主键 |
| `biomarkers_*.csv` | `edge_uid/roi_uid`、方向、频率、fold/site 分母、效应 | 不用列号解释 edge |
| `metrics_*.csv` | 每 fold/site/pooled 指标、有效样本和 NA reason | 不覆盖原始预测 |

### 9.3 必须通过的对应关系检查

发布前必须验证：

1. 每个 `sample_key` 在 `subjects.csv` 唯一存在，并与原始人口学一对一匹配。
2. 每个 `roi_uid` 在 ROI manifest 唯一存在，并能回连原始编号、label 和解释。
3. 每个 `edge_uid` 的两个端点 `roi_uid` 都存在。
4. NPZ 的行顺序与 `sample_key_order` 一致，列顺序与 edge manifest 一致。
5. 删除或排序不会改变任何 ID 到 label/ROI label 的映射。
6. QC、split、prediction、biomarker 的 `sample_key` 不得出现未知或重复身份。
7. 训练状态 hash 与实际 fit IDs、ROI/edge manifest hash 相符。

## 10. 历史结果的使用边界

旧项目曾在 ABIDE1/ABIDE2 的 HO112、较早配置下得到：ABIDE1 FC base 平均 AUC 约 0.718、FCHN calibrated 平均 AUC 约 0.728；ABIDE2 FC base 约 0.669、FCHN 约 0.675。ABIDE1 的改进较稳定，ABIDE2 的置信区间跨 0。

这些数值是历史参考，不代表 `FCHN_20260825` 在新 QC（5%/30%）、新主 protocol（LOSO + pooled10_site_label）和新极简存储方案下的最终结果。新实现必须重新生成结果，并在报告中区分 `legacy_reference` 与 `FCHN_20260825`。

## 11. 新窗口接手顺序

1. 先读取本手册和项目根目录的 `task_plan.md`、`findings.md`、`progress.md`。
2. 确认当前工作目录不是结果写入位置；所有 FCHN 文件只写入 `C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`。
3. 读取 `C:\XY\FedTopo-Brain\SSL\data` 的 manifest 和 ROI mask，先完成身份审计，不直接训练。
4. 建立 `subjects.csv`、四套 ROI/edge manifest 和固定 hash。
5. 先跑一个 atlas × dataset × protocol 的 QC/单 outer fold pilot，完成 round-trip 和身份检查后再扩大矩阵。
6. 所有科学参数改变都生成新的 config/run ID，不覆盖旧产物。

## 12. 当前未绕过的门禁

- FCP 的 mean FD 缺失不能通过伪造填补解决。
- 若实现要求 normative 分支控制 mean FD，必须显式创建独立 FCP 可用子集 variant；不得把疾病残差和 FCP 原始空间静默混合。
- 任一训练 edge 无有限值时必须删除并记录，不能用 0 或全局统计量替代。
- 任一身份、ROI label、edge endpoint 或 split 成员校验失败时停止发布，不带错误结果继续训练。

## 13. 新读者接手测试结论（2026-08-25）

已让一个不继承本次讨论上下文的新读者只阅读本手册，测试其能否回答：项目/输入路径、atlas×dataset×protocol 循环、两个主 protocol、QC、FCP 规则、FC/HOFC/normative/Meta 顺序、outer-test 边界、标志物汇总和最小存储方案。

测试结果：研究目标、主循环、protocol、QC、FCP 角色、outer-test 禁止事项、汇总时点和 ID 存储契约均能被准确复述。手册已经可以作为新会话的主要上下文入口，但目前还不能宣称“无需任何实现前确认即可精准编码”，因为以下参数尚未在 `FCHN_20260825` 中单独冻结：

1. `sample_key` 的确切分隔符、session 缺失值和重复 session 处理；
2. `pooled10_site_label` 中样本少于 10 的 site×label 层如何降折或标记不可训练；
3. inner/Base OOF/C-tuning 的确切折数、site grouping 和动态降折规则；
4. FCP health-only cross-fit 的具体成员划分、状态复用和每个 outer fold 的保存边界；
5. 训练折全无效 edge 删除后的 fold-specific edge schema、hash 和 biomarker 对齐方式；
6. structural ROI/common ROI manifest 的粒度，以及 `qc_subject_<atlas>.csv` 是否按 dataset 分文件或合并并强制包含 `dataset_id`；
7. KMeans 有效健康样本不足时的最低样本数和降 K 规则；
8. ROI incident ratio 在结构性 ROI/edge 删除后的分母定义；
9. 疾病 mean FD 缺失样本是否可以保留在不使用 mean FD 的 normative-common 分支，以及对应的 reason code；
10. variance floor、prototype assignment 字段和 predictions 表中 `true_label` 是否作为主字段还是只从 `subjects.csv` 回连。
11. `FCHN_20260825` 当前是文档、目录和方案冻结阶段，`src/`、`scripts/`、`tests/` 尚未形成可用于正式实验的完整实现；旧 `CHyCR_20260621/scripts` 和 `src/chycr` 只能作为函数级参考，不能直接当作新项目正式入口运行。

这些不是研究主线不清楚，而是新读者测试当时识别出的实现门禁；本节第 1–10 项已经由第 14 节给出最终规则，第 11 项仍然有效。新会话应先检查第 14 节；在正式代码和 schema 尚未建立前，不得声称已完成正式实现或生成最终结果。

## 14. 已确认的最终实现建议（以本节为准）

以下决定由 2026-08-25 讨论冻结，用于替代第 13 节测试时列出的前 10 项实现疑问：

| 项目 | 最终规则 | 选择理由 |
|---|---|---|
| 被试身份 | `sample_key = subject_id`；所有表强制带 `dataset_id`；跨数据集使用 `(dataset_id, sample_key)` | 当前 manifest 无 session_id，原始 ID 已在 6161 个样本中全局不重复；避免人为创造身份字段 |
| Inner CV | 固定 5 折 `site × label` round-robin；训练不合格时使用一次 2 折 label-stratified fallback | 比 10 折更简洁、计算量更小；保留 site/label 组成；适合 inner 调参 |
| Inner 单类别 | validation 单类别保留，用 log-loss；train 单类别或任一类少于 10 人则该折不可训练；fallback 仍失败则 task invalid | 不删除数据、不训练常数模型，规则可审计 |
| 小 `site × label` 层 | 仍分配到全局 5/10 个 fold 的前若干折，不合并 site/label | 保留全部样本，避免隐式改变研究人群 |
| FCP cross-fit | 5-fold、site-aware、health-only；每个 FCP 被试不进入自身 prototype/variance；outer-test 只用 outer-train+FCP final state transform | 计算量适中，健康参考不自泄漏 |
| 全训练 edge 无有限值 | `invalid_untrainable`，不删除列、不填 0 | 保持所有 fold 的 edge universe、HOFC 维度和 biomarker identity 一致 |
| ROI/manifest | 一个 atlas master ROI manifest；结构性可用性按 dataset 记录；QC 表按 atlas 合并且必须有 dataset_id | 减少重复文件，仍能追溯原始 ROI identity |
| incident ratio 分母 | 结构性 ROI/edge 对齐后固定；结构性不可用 edge 不计入分母 | 避免先删后算造成 QC 阈值漂移 |
| KMeans | `K_eff=min(8,max(1,floor(H/10)))`；cluster n<3 时局部方差回退总体方差；H<10 使 normative task invalid | 防止小健康簇产生不稳定方差，同时保持规则简洁 |
| 方差与 prototype | `ddof=0`，`variance_floor=1e-6`，`lambda=0.10`；prototype ID 只作诊断字段 | 数值稳定；KMeans 编号不具有跨 fold 语义 |
| Meta summaries | 固定 10 个 summaries；不把 prototype ID 作为特征；Full Meta 主维度为 13 | 避免 fold 间 prototype label switching，保持 Meta 输入可解释 |
| predictions | 保存 `true_label` 作为审计快照；`subjects.csv` 的 label 是权威值，发布前强制逐行比对 | 同时满足结果绘图和身份审计，避免重复字段成为第二主表 |

正式代码必须把上述规则写入 resolved config、schema 和 task manifest；不能只存在于注释或口头约定中。
