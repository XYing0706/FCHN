# FCHN_20260825 已核验发现

## 输入数据

`C:\XY\FedTopo-Brain\SSL\data` 存在：

- `adhd`：包含 `manifest_adhd.csv`、`ADHD200_Phenotypic_ChaoganYan.csv`、`HO112/AAL116/Dosenbach160/CC200_{fc,ts}.npz`、`roi_mask_adhd.csv`。
- `abide`：包含 `manifest_abide.csv`、ABIDE phenotype 文件、四套 atlas 的 FC/时序和 `roi_mask_abide.csv`。
- `abide2`：包含 `manifest_abide2.csv`、ABIDE2 phenotype 文件、四套 atlas 的 FC/时序和 `roi_mask_abide2.csv`。
- `mdd`：包含 `manifest_mdd.csv`、REST-meta-MDD phenotype 文件、四套 atlas 的 FC/时序和 `roi_mask_mdd.csv`。
- `fcp`：包含 `manifest_FCP.csv`、`FCP_RfMRIMaps_Info.csv`、四套 atlas 的 FC/时序、`roi_mask_FCP.csv` 和 Beijing 子目录。

## 方案判断

- 跨数据集按稳定 ROI identity 建立 atlas 共同空间；结构性不存在 ROI 在共同空间建立时删除一次。
- 被试级 QC 不删除单个被试的 ROI，而是排除该 atlas 下整名被试，避免每名被试矩阵维度不同。
- 训练折内只对保留 edge 做逐 edge 中位数填补；训练折某 edge 全部无有限值则记录并删除该 edge，禁止填 0。
- 不把 fold-specific recurrent ROI 作为主流程，避免不同 fold 的特征空间和标志物难以对齐；若需要只能作为独立敏感性 variant。
- 所有删除原因、原始身份、稳定 ROI/edge ID 和来源哈希必须可审计。

## 原始 FCHN 脚本复核

- `scripts/25_run_fchn_latefusion.py` 的主调用链为：共同 ROI 对齐 → FC Base → HOFC Base → FCP normative transformer → normative Base → Meta stack → source-OOF Platt → 站点级指标和汇总。
- `src/chycr/fchn_core.py` 中 HOFC 是从 ROI profile 的行中心化/范数归一化后相关矩阵的上三角构造；Logistic view 在训练数据拟合 scaler/PCA/分类器；health-anchor 使用 FCP + source HC 的 KMeans 原型、局部/总体方差收缩和 residual summaries。
- 旧脚本只实现 source-only LOSO，C 选择基于 site-level mean AUC，Meta OOF 不是当前要求的 strict nested Meta；这些差异已在新手册中标注，不能原样作为 FCHN_20260825 的最终实现。

## 新读者测试

一个没有本次对话上下文的读者能够准确回答项目路径、输入数据、atlas×dataset×protocol 循环、LOSO/pooled10_site_label、5%/30% QC、FCP 规则、outer-test 边界、标志物汇总和 CSV/NPZ 身份契约。读者同时发现手册仍缺少若干实现冻结项；完整列表见手册第 13 节，正式编码前必须将这些项目写入 config/schema，不能靠实现者临时猜测。

## 2026-08-25 冻结的实现建议

- 当前 manifest 没有 session_id；原始 subject_id 在五个 dataset 间无重复，因此使用 `sample_key=subject_id`，用 dataset_id 作为强制命名空间。
- Inner 固定 5 折 site×label round-robin；validation 单类别保留并用 log-loss，training 单类别/每类少于10人不可训练；必要时仅一次 2 折 label-stratified fallback。
- FCP 使用 5-fold health-only cross-fit；全训练 edge 无有限值则 task invalid；prototype ID 不进模型；normative summaries 固定10个，方差 floor=1e-6、ddof=0、lambda=.10。
- 完整规则和理由见手册第14节，正式实现必须写入 resolved config/schema。

## 第一主线阶段 A 补充发现

- 5 个 manifest 行数分别为 ADHD 844、ABIDE 1085、ABIDE2 1027、MDD 2347、FCP 858；各自 subject_id 唯一且无空值。
- FC NPZ 使用 `X/subject_ids/roi_indices/view_missing/atlas_name/qc_version`；必须以 `allow_pickle=false` 读取。
- 实际 ROI 数因 dataset 的结构性缺失而变化，例如 ABIDE2 HO112 为 111 ROI/6105 edge，而非 112 ROI/6216 edge。
- 用户确认原始全列 1-based 区间：AAL116 1-116；Harvard-Oxford cortical 117-212、subcortical 213-228；CC200 229-428；Dosenbach160 1409-1568。
- 公开 atlas 元数据只有在 ROI 数、编号顺序、版本/空间、许可和本地 ROI identity 均核验通过后才可进入 master manifest；不得凭同名文件猜测。

## 2026-08-25 单元存储与 ROI 完整性核查

用户要求阶段 A 物理存储必须以单个 `dataset x atlas` 为最小加载单元；设计已改为 `outputs/cells/<dataset>/<atlas>/`，不生成跨 dataset 或跨 atlas 的大型 FC 文件。小型 subjects/manifest 在单元内重复，换取单元独立加载；重复通过 source hash 审计。

当前输入核查结论：20 个 `*_fc.npz` 全部是二维 `N x E` 上三角 edge 向量，不是 `N x R x R` 方阵；每个单元均满足 `E=R(R-1)/2`。FC 与 TS 的 `subject_ids`、`roi_indices` 在 20 个单元中全部一致；FC `roi_indices` 与 ROI mask 的 `kept=1` 顺序全部一致。

理论 ROI/实际 ROI/缺失 atlas-local ROI（1-based）如下：

| dataset | atlas | FC X shape | 理论/实际 ROI | 缺失 local ROI |
|---|---|---:|---:|---|
| adhd | HO112 | 844×6216 | 112/112 | - |
| adhd | AAL116 | 844×6555 | 116/115 | 102 |
| adhd | Dosenbach160 | 844×12561 | 160/159 | 155 |
| adhd | CC200 | 844×19900 | 200/200 | - |
| abide | HO112 | 1085×6216 | 112/112 | - |
| abide | AAL116 | 1085×6216 | 116/112 | 101,102,107,108 |
| abide | Dosenbach160 | 1085×11935 | 160/155 | 86,110,150,151,155 |
| abide | CC200 | 1085×19701 | 200/199 | 43 |
| abide2 | HO112 | 1027×6105 | 112/111 | 28 |
| abide2 | AAL116 | 1027×6328 | 116/113 | 102,107,108 |
| abide2 | Dosenbach160 | 1027×12403 | 160/158 | 151,155 |
| abide2 | CC200 | 1027×19900 | 200/200 | - |
| mdd | HO112 | 2347×6216 | 112/112 | - |
| mdd | AAL116 | 2347×6441 | 116/114 | 102,107 |
| mdd | Dosenbach160 | 2347×12561 | 160/159 | 155 |
| mdd | CC200 | 2347×19900 | 200/200 | - |
| fcp | HO112 | 858×6216 | 112/112 | - |
| fcp | AAL116 | 858×6328 | 116/113 | 102,104,107 |
| fcp | Dosenbach160 | 858×11935 | 160/155 | 110,140,150,151,155 |
| fcp | CC200 | 858×19900 | 200/200 | - |

缺失 ROI 的全局原始列号按 atlas 区间转换：AAL local+0、HO local+116、CC local+228、Dosenbach local+1408。所有缺失 ROI 必须在单元 ROI manifest 中保留 `roi_original_index`、`global_original_column`、`structural_unavailable`、`matrix_position=null` 和 reason code。

## 2026-08-26 阶段边界纠正与新增门禁

- 依据 `doc/FCHN_HANDOFF_MANUAL_20260825.md` 第 7 节，atlas metadata、稳定 ROI/edge identity、跨数据集共同空间、subjects 和 QC 全部属于阶段 A；阶段 B 只负责 split plan。
- 当前 stage manifest 仅按单元数和 dataset×atlas 集合判定完整，若单元内容重建但集合不变，旧 stage manifest 可能被误判为新鲜；最终门禁必须逐项回连当前 `cell_manifest.json` 或保存并核验其 hash。
- `site_id` 应规范为字符串以保留前导零；label、sex 和 age 必须有逐数据集 codebook/单位和来源合同，禁止根据数值猜测语义。
- `ts_inventory.json` 应明确只登记非 `X_concat` 数组的 shape/dtype 描述符，不等同于保存 subject/ROI 值。
- 最终安全审计必须覆盖全部四类源文件 hash、单元路径身份、数组计数和 stage/cell manifest 一致性；最小 FC 读取示例不能冒充完整审计。
- 原始身份换算固定为 `roi_original_index = roi_local_idx + 1` 和 `global_original_column = global_column_start_1based + roi_local_idx`，防止 off-by-one。
- 当前 `src/fchn_stage_a.py` 仍以 `<atlas>_ROI_###` 生成占位 `roi_label`，`description` 为空，尚未消费权威 atlas master。
- 当前 `scripts/01_prepare_final_inputs.py` 的 `subjects.csv` 只是从 manifest 选择已有列，未生成 `sample_key`、规范 `dataset_id/site_id`、`scan_length`、人口学来源/hash、`mean_fd_source` 和 `sex_encoding_rule`。
- 当前 `qc_subject.csv` 未保存逐被试 `max_roi_incident_invalid_ratio`；当前 `cell_manifest.json` 只保存单元总体最大值。
- 当前 `stage_a_manifest.json` 内嵌 cell payload，但不保存当前 `cell_manifest.json` 的路径/hash；必须修复陈旧汇总仍可通过的问题。
- 当前产物保持了正确的最小加载粒度：每个 `dataset × atlas` 独立目录，FC 只保存带 hash 的源引用而不复制大矩阵；后续补全不得破坏该结构。
- 已批准设计要求 `subjects.csv` 包含 `sample_key,dataset_id,subject_id,site_id,label,age,sex,scan_length,mean_fd,source_file,source_row_hash,demographic_source_file,demographic_source_row_hash,mean_fd_source,sex_encoding_rule`，当前实现未满足。
- 已批准设计要求逐被试 QC 保存 `available_edge_count,invalid_edge_count,invalid_edge_ratio,max_roi_invalid_ratio,max_invalid_roi_uid,fc_source_hash,roi_manifest_hash,edge_manifest_hash`，当前实现未满足。
- atlas 稳定 ID 固定为 `<atlas_id>:roi<三位编号>`；edge 固定为 `<atlas_id>:roi<三位编号>--roi<三位编号>`。当前实现的未补零 ROI ID 和 `edge###_###` 形式不符合已批准合同。
- 阶段 A stage 级设计还要求小型 `input_inventory.csv`、`atlas_metadata_sources.csv`、`stage_a_manifest.json`、`stage_a_summary.md` 和最终 `_SUCCESS`；当前缺前三者中的前两项及 stage `_SUCCESS`。
- 共同 ROI 空间应从 master universe 和五个数据集的结构性可用状态确定性求交；共同 edge 是共同 ROI 的两两组合。它是小型身份索引，不得合并或复制任何跨数据集 FC 数值。
- 父项目 `FACHN/resources/atlases` 当前只有 HO112 的 DPABI YCG cortical/subcortical NIfTI、MAT labels、XLSX、派生 112 labels、来源说明和 source manifest；未发现可直接复用的 AAL116/CC200/Dosenbach160 完整来源快照。
- 本地 Anaconda 的 Nilearn 实现包含 Harvard-Oxford、Craddock 2012 和 Dosenbach 2010 fetcher，可作为公开工具包来源线索；采用前仍必须核验与本项目 DPARSF 原始列顺序一致。
- 父项目存在 `mdd_demographics_enrichment_*` 结果和审计文件，可用于定位既有精确身份回填规则，但只有在核验生成脚本、来源 phenotype 和覆盖/冲突审计后才能借鉴。
- 扫描父项目时历史 `results/tmp/pytest-*` 目录出现访问拒绝；这些目录与目标 atlas/人口学资源无关，后续限定搜索路径避开，未修改任何文件。
- MDD phenotype XLSX 含 `MDD` 1276 行和 `Controls` 1104 行，字段含 `ID,Sex,Age`；目标 manifest 2347 行，必须做精确身份/诊断一致性审计并解释未进入目标的源行。
- FCP 信息表 895 行、目标 manifest 858 行，`(Site,Subject ID)` 无重复；Sex 原值为带引号的 `f/m/F/M`，规范化前必须去引号并显式映射，不能从数值猜测。
- 当前 manifest 缺失计数：MDD age/sex 各 2347；FCP sex 858、mean FD 176；ADHD sex 另有 1 个缺失值。FCP 176 个 mean FD 必须按合同保留为空。
- 父项目 MDD enrichment 采用原始 `subject_id == workbook ID` 精确匹配，并以 `MDD` sheet→label 1、`Controls` sheet→label 0 核对诊断；身份结果为 2347/2347 精确匹配、33 个 workbook-only ID。2026-08-26 对当前只读 XLSX 重新按匹配集、未匹配集和全表核验，三者 `Age/Sex` 数值缺失均为 0；先前沿用的“age 源缺失 3、sex 源缺失 1”结论已证伪，不得据此制造缺失。
- MDD workbook 的 sex codebook 已由既有 provenance 显式记录为 `1=male, 2=female`。当前 manifest 的 age/sex 2347 行均为字面 `nan`，canonical subjects 必须从精确匹配 workbook 取得完整 age/sex，并同时保留 manifest/workbook 来源和行哈希。
- 既有 FCP enrichment 将去引号后的 `m/male/1` 映射为 1、`f/female/2` 映射为 2，并按 `<Site>_<Subject ID>` 精确匹配 manifest `subject_id`。
- 既有 FCP enrichment 还可从北京 realignment 参数补 motion，但本项目冻结要求 176 个 FCP mean FD 保持为空；阶段 A 只借鉴人口学匹配，不采用 motion 回填逻辑。
- FCP 已在本机重新核验：目标 858/858 均能按 `<Site>_<Subject ID>` 精确匹配，manifest age 与 info age 858/858 一致，858 个 Sex 均可从 `m/f` 显式映射；来源表另有 37 行未进入目标 manifest。
- `RfMRIMaps_ABIDE2_Phenotypic.csv` 含非 UTF-8 字节；后续读取必须显式使用核验后的兼容编码，不能依赖平台默认编码。
- ABIDE phenotype 以 `SUB_ID` 补足 7 位后与目标 manifest 1085/1085 精确匹配；age/sex 1085/1085 一致，且 `label = 2 - DX_GROUP` 1085/1085 一致。
- ABIDE2 phenotype 使用 `latin1` 读取后，`SUB_LIST` 与目标 manifest 1027/1027 精确匹配；age/sex 1027/1027 一致，且 `label = 2 - DX_GROUP` 1027/1027 一致。
- ADHD manifest `subject_id` 与 phenotype `Participant ID` 不是直接同格式，裸 ID 精确交集为 0；必须沿用并核验原始 SSL 构建阶段的确定性 ID 规范化规则，禁止模糊匹配。
- `SSL/src/dgda/atlas.py` 明确记录 DPARSF `ROISignals` 的 0-based 半开区间：AAL `[0,116)`、HO cortical `[116,212)`、HO subcortical `[212,228)`、Craddock200 `[228,428)`、Dosenbach160 `[1408,1568)`，与用户提供的 1-based 全局列完全一致。
- `SSL/configs/adhd.yaml` 注释表明时间序列文件身份取完整 `ADHD200_<Site>_<ID>` token，而 phenotype 主键列是 `Participant ID`；必须核验其构造规则形成一对一 exact key，不可只截取数字或做模糊后缀匹配。
- `SSL/src/dgda/datasets.py` 与 `configs/adhd.yaml` 的正式构建规则是：phenotype `Participant ID` 转字符串、去首尾单引号和空白，然后与完整 manifest/file token 精确相等；label 为 `DX>0`，`pending` 排除。
- ABIDE/ABIDE2 源配置明确 `DX_GROUP 1=ASD, 2=HC`、`SEX` 原编码保留；MDD 源配置明确 ID group 1=MDD、group 2=HC，并排除重复站点 S4。
- 2026-08-26 浏览 DPABI 官方 GitHub `Templates` 普通页面，确认与 DPARSF 原始列来源一致的候选文件：AAL=`aal.nii, aal_Labels.mat`；CC200=`CC200ROI_tcorr05_2level_all.nii`；Dosenbach160=`Dosenbach_Science_160ROIs_Center.mat, Dosenbach_Science_160ROIs_Info.mat, Dosenbach_Science_160ROIs_Radius5_Mask.nii`；HO112=已核验 YCG cortical/subcortical 文件。
- DPABI Templates 页面没有给 CC200 单独的解剖名称表；按已批准设计，只能据实使用 parcel ID、模板 label value 和从模板计算的质心/可得网络字段，不能编造解剖学名称或 description。
- GitHub 普通页面是来源发现证据；最终采用仍需保存原始文件快照、仓库 commit/tree SHA、URL、访问日期、许可和每文件 SHA-256，并验证 label 数量/顺序与本地 ROI identity。
- DPABI 仓库根页明确显示 `LGPL-2.1` license，并引用 DPABI 2016 Neuroinformatics 论文 DOI `10.1007/s12021-016-9299-4`。
- 2026-08-26 首次用 `git ls-remote` 解析当前 master 时连接被重置；未下载任何文件。后续使用父项目已核验 source manifest 中固定的 DPABI tree SHA `8d4b16e46be65cce93662e34e1cfa22bd40d98dc`，避免浮动 master。
- 已从 DPABI 固定 SHA 下载并 hash：`aal.nii/aal_Labels.mat`、CC200 NIfTI、Dosenbach Center/Info MAT 与 Radius5 mask、LICENSE/README；已复制 HO112 的 8 个本地核验快照。全部位于 `config/atlas_metadata/sources/`。
- AAL `Reference` 为 117×3（背景+116），NIfTI 非背景值连续 1–116，包含官方短标签和 MNI 质心。
- CC200 NIfTI 非背景值连续 1–200、4 mm MNI-like affine；无独立名称表，master 中 name/description 应为空，`roi_label` 使用原始 parcel label value，质心从 NIfTI 计算。
- Dosenbach Radius5 mask 非背景值连续 1–160；`Dos160_WithName` 为 160×5，逐行给出 x/y/z、区域简称和原始功能网络，Center MAT 坐标与其可交叉验证。
- HO112 cortical/subcortical NIfTI 非背景 label 数分别 96/16；两个 Reference MAT 分别为背景+96/16，顺序与 `ho112_dpabi_labels.csv` 一致。
- metadata 内容审计发现 AAL 无 `_L/_R` 后缀的中线区域被通用坐标规则误分左右；应按 AAL 官方标签后缀确定：`_L→L`、`_R→R`、无侧别后缀→M`。
- ADHD-200 官方首页仅展示项目名和需登录的数据下载入口；限定官方站点的搜索未返回 Gender codebook。当前权威快照只能确认字段名 `Gender` 和原始 0/1，不能无猜测地指定男女语义。
- （已由 2026-08-26 官方 PDF 快照 supersede）ADHD raw 0/1 的语义现已核验为 0=female、1=male；阶段 A 保留 raw，阶段 C 映射为 canonical male=0/female=1。

## 2026-08-26 阶段 A/B 复审与阶段 C 启动

- A/B 初版新鲜复审为 `29 passed in 194.81s`；补充 nested lineage 后最终回归为 `31 passed`（含阶段 B 4 项门禁），阶段 A 六类检查仍全部为 True。
- 阶段 B 的 `_SUCCESS/status/32 groups/current group manifest hash/implementation hash/stage artifact hash/Stage A parent hash` 七类检查全部为 True；可以进入阶段 C。
- 阶段 C 的冻结闭环来自交接手册第 7、14 节：inner train-only 拟合，FC/HOFC/normative 三 base views，strict Meta OOF，Meta-OOF-only Platt，完整 outer-train 重拟合，outer-test 只 transform/predict。
- FCP 仅作为 normative 外部健康参考；需 5-fold site-aware health-only cross-fit，每名 FCP 不能参与自身 prototype/variance；FCP 不进入疾病分类标签训练。
- Normative KMeans 冻结为 `K_eff=min(8,max(1,floor(H/10)))`、H<10 invalid、cluster n<3 局部方差回退总体方差、ddof=0、floor=1e-6、lambda=0.10；prototype ID 只诊断，不进入 Meta。
- 主 Meta 固定输入维度 13：FC logit、HOFC logit、normative logit和10个 normative summaries；所有估计型预处理只能在当前实际 train 中拟合。
- 深入对照手册第 7 节发现现有阶段 B 只保存 outer 与一层 inner，未为 Base OOF、Base C-tuning、strict Meta OOF 分别固化 task/parent lineage；这不满足“split plan 一次生成、阶段 C 只读复用”的严格审计合同，阶段 B 需先补齐后才能进入 C。
- 父项目 `FCHN_20260805/doc/STAGE00_PARAMETERS.md` 与 `configs/base.yaml` 已明确冻结 Ridge `alpha=1.0`、带截距；连续协变量 train-only 标准化，只减中心化协变量效应并保留训练特征均值。这可作为当前 Stage C 非猜测的参数来源。

### 阶段 C 复核补充

- 通过下载并保存 ADHD-200 官方 PhenotypicKey PDF，确认 `Gender 0 Female, 1 Male`；此前“语义未确认”的记录被该新快照 supersede，但阶段 A raw subjects 不改写，canonical 映射只在阶段 C 派生。
- 阶段 C 首次 pilot 的 NaN 根因是 FCP 已 canonical 的 0/1 sex 被按 raw 1/2 重映射；已修复为单次映射并加入测试。
- 真实 pilot 仍未完成：高维 Logistic/KMeans 计算耗时过长，尚未生成有效 fold；因此当前只宣称 A/B 通过和 C runner/纯函数通过，不宣称 C 全量通过。
## 2026-08-26 阶段 C 计算复核

- 复核发现旧 runner 曾将 normative 逐 edge `edge_z` 误接入 Meta，造成约 6,000 维 Meta；已改为显式 `assemble_meta_features()`，强制 3 logits + 10 summaries = 13 维，并新增测试锁定。
- 已加入 FCP site-aware 5-fold cross-fit 折分配；每个 outer fold 的最终 normative 状态拟对 FCP 留出被试拟合 anchor 并记录自排除 hash/计数，输出 `fcp_crossfit_audit.csv`。
- 真实数据计时显示单个 normative training boundary 的 common-space 健康锚点拟合约 8 秒；完整 strict nested pilot 的 meta-base tuning task 数量为 125，故单 fold 计算达到几十分钟是可解释的计算量，不应通过降低冻结 KMeans/C 网格来掩盖。
- 当前阶段 C 仍未通过：真实 pilot 未成功写出 `stage_c_fold_ready`，阶段级 `_SUCCESS` 不存在；阶段 D/E 禁止启动。

## 2026-08-29 阶段 C 性能根因继续核验

- 对 HO112/ADHD/LOSO outer000 的 nested 任务按实际重建成员计算 hash：25 个 `base_c_tuning`、125 个 `meta_base_c_tuning`、25 个 `meta_base_oof` 的训练成员 hash 均全部唯一，train+validation hash 也全部唯一。
- 因此不能通过“不同 task_id 实际成员相同”的缓存复用来缩短计算；这样做不会命中且只会增加复杂度。当前瓶颈仍是严格 nested 计划要求的真实独立训练边界数量。
- 4 个真实 normative tuning boundary 的顺序准备耗时 31.276 秒；2 线程为 21.757 秒（1.437×），4 线程为 18.905 秒（约 1.65×）。并行只改变调度，不改变 task membership、seed、预处理或模型参数；2 线程收益明确且更节制，适合作为最小工程优化候选。
- 成功 pilot 的基础文件、尺寸、有限性、label 回连、FCP 自排除和 artifact hash 均通过；但 `model_state.npz` 当前只有 selected/meta C，predictions 也缺 task/status 字段，尚未满足手册的完整审计合同。
- 更关键的是，当前 `meta_final` 使用 `np.vstack(meta_feature_rows)`：这些行来自 5 个 meta fold 各自的 meta-train，同一 outer-train 被试会在多个 meta-train 中重复。最终 Meta 应改为使用顶层 `base_oof` 5 折为完整 outer-train 生成每名样本恰好一次的 OOF base logits/summaries；meta folds 只用于 Meta C 选择与 Platt OOF。

## 2026-08-29 阶段 C 收口核验结论

- 顶层 base OOF 是最终 Meta 唯一正确的训练特征来源：各 view 验证片段先按 `sample_key` 组装并拒绝重复，再取三视图精确交集并回连权威 label；不能拼接 5 个 meta-train 的 OOF 行。
- FCP/疾病 common-edge 数值列切片可以在单 outer fold 内缓存，因为它只是当前 cell 的确定性 `edge_uid→matrix_position` 变换；任何 imputer、Ridge、scaler、KMeans、PCA、Logistic 或概率结果均不得跨训练边界缓存。
- `np.savez` 接收 Pandas 字符串 `.to_numpy()` 时可能得到 object dtype；稳定身份轴必须显式 `np.asarray(list, dtype=str)`，并以 `allow_pickle=false` 做真实回读门禁。
- 单纯保存矩阵行序/列序而不保存 `sample_key`/`edge_uid` 不能满足解释回连要求；`normative_scores.npz` 必须自带两条轴身份。
- fold 的 `_SUCCESS` 不是充分的新鲜度证据。resume 与阶段级计数都必须要求 marker、manifest 和当前 config/runner/src/A/B hash 完全相等；否则旧结果会被新代码静默接受。
- 最终 pilot 的 manifest/artifact/label/identity/state/FCP 自排除全部通过；阶段 C 的剩余门禁只有 428 个 expected outer folds 全部 fresh 及 stage manifest/_SUCCESS，不得以 1-fold pilot 代替。

## 2026-08-29 阶段 C 缺失协变量根因

- `_view_predict()` 已会为 view-required covariate 非有限的 test 行保留原位置并返回 NaN；原缺口在最终 `test_meta` 无有限行分流，直接将含 NaN 的 13 维矩阵送入 Meta Logistic。
- outer003 的直接根因是 1 个 test 行 canonical sex 缺失，FC/HOFC/normative 都不合格；不是 mean FD 缺失，也不是 edge imputer、KMeans 或 Logistic 数值不稳定。
- 不能用 sex 中位数/众数填补，也不能删除该身份后让输出行序错位。冻结的 `exclude_with_reason` 要求保留全部 test identity，对不合格 view 写稳定 reason，并只在有限子集预测。
- 最小正确修复是 `_predict_finite_rows(model, features)`：计算全有限 mask，只预测 mask=True 行，再按原始行序回填 logits/probabilities；mask=False 保持 NaN。输出层据此写 `ineligible/MISSING_REQUIRED_COVARIATE`。
- normative score 的不合格行同样保持 `sample_key` 与 `edge_uid` 轴，summary/edge_z 为非有限、nearest 为诊断缺省；阶段 D 必须按 `task_status` 排除预测指标，但仍保留身份与原因审计。

## 2026-08-30 ABIDE 词法身份根因

- ABIDE 的权威 `sample_key/subject_id` 与 FC `subject_ids` 都是 7 位、带前导零的字符串；Stage A 文件内容和 FC 行序完全一致。
- pandas 在未指定 dtype 时会把这一列推断为整数。旧 Stage B 因此把 7 位身份写成 5 位，旧门禁又以同样方式读取两侧，形成“共同错误后仍相等”的盲区。
- 去前导零后虽可无歧义对应，但在 Stage C 做模糊匹配会破坏稳定身份合同并掩盖上游错误；正确修复必须在 CSV 入口明确 `dtype={'sample_key': str, 'subject_id': str}`，并以原始词法集合做门禁。
- 身份门禁必须使用字符串 dtype 读取权威侧和产物侧；只比较 pandas 默认推断后的值或只比较行数/hash，不能证明前导零、大小写或其他词法身份未被改写。
