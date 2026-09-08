# FCHN_20260825 阶段 A 实施说明

日期：2026-08-26  
项目根：`C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`  
阶段状态：**passed**  
阶段级完成标记：`outputs/stage_a/_SUCCESS`，内容为 `stage_a_ready`

## 1. 阶段定位与结论

阶段 A 是五条实施主线中的第一条，任务是：权威脑图谱元数据核验、稳定 ROI/edge 身份、人口学精确回连、被试级 FC 有限性 QC、跨数据集共同空间，以及 20 个独立 `dataset × atlas` 最终输入单元的可审计发布。

阶段 A **不生成 split**。LOSO 和 `pooled10_site_label` 的 split plan 属于阶段 B。阶段 A 当前 17 项自动门禁全部通过；只有在该状态下，阶段 B 才能读取本阶段输出。

本阶段没有合并不同数据集或不同图谱的大型 FC。每个 `dataset × atlas` 仍是最小加载、审计和恢复单元。默认只保存原始 FC 的路径、shape、dtype 和 SHA-256，不复制大矩阵。

## 2. 输入及只读边界

### 2.1 主要输入

- 数据根：`C:\XY\FedTopo-Brain\SSL\data`
- 数据集：`adhd, abide, abide2, mdd, fcp`
- 图谱：`HO112, AAL116, Dosenbach160, CC200`
- 每个数据集包含 manifest、ROI mask、四套 `*_fc.npz`、四套 `*_ts.npz` 和人口学源文件。
- 父项目 `C:\XY\FedTopo-Brain\CHyCR_20260621` 仅用于读取历史实现和已核验资源，不写入、不覆盖。

### 2.2 原始 FC/TS 数据形式

源 FC `X` 是 `N × E` 的二维上三角 edge 向量，不是 `N × R × R` 方阵；必须满足：

```text
E = R × (R - 1) / 2
```

这里 `R_theoretical` 是 atlas 理论 ROI 数；`R_cell=len(roi_indices)=#mask_kept`；源 FC 的 `R=R_cell`，因此 `E_source=R_cell(R_cell-1)/2`。源列顺序是 `roi_indices` 给出的 0-based atlas-local ROI 顺序所形成的严格上三角：先固定第一个 ROI，按后续 ROI 顺序枚举，再固定第二个 ROI，以此类推。`fc_source.json.roi_indices` 保存的就是这个 0-based 顺序。理论 master edge 不因 cell 压缩而删除；`edge_manifest.matrix_position` 将源 FC 每列回连到理论 edge。

源 FC 与 TS 的 `subject_ids`、`roi_indices` 必须完全对应；`roi_indices` 还必须与 ROI mask 的 `kept=1` 顺序完全一致。所有 NPZ 固定 `allow_pickle=false`，禁止 object array。

### 2.3 图谱原始列合同

| atlas | 理论 ROI | 原始全列 1-based 区间 | `global_column_start_1based` |
|---|---:|---:|---:|
| AAL116 | 116 | 1–116 | 1 |
| HO112 | 112 | 117–228 | 117 |
| CC200 | 200 | 229–428 | 229 |
| Dosenbach160 | 160 | 1409–1568 | 1409 |

429–1408 的空档来自用户确认的原始全列布局，属于本项目未纳入的其他 atlas/列；阶段 A 有意保留该空档，不填充、不重编号。四个已纳入区间必须互不重叠。

身份换算固定为：

```text
roi_original_index = roi_local_idx + 1
global_original_column = global_column_start_1based + roi_local_idx
matrix_position = 当前单元 FC/TS 内的 0-based 位置
```

这三个坐标不能混用。结构性缺失 ROI 保留前两种原始身份，`matrix_position` 为空。

CSV 中 `roi_original_index/global_original_column` 为 1-based integer，`source_roi_index/matrix_position/common_matrix_position` 为 0-based integer；结构性缺失时只有 `matrix_position` 为空，`source_roi_index=roi_original_index-1` 仍保留且不为空。

## 3. 方法细节

### 3.1 权威 atlas metadata

与本地 DPARSF/DPABI 列顺序一致的 DPABI tree 固定为：

```text
8d4b16e46be65cce93662e34e1cfa22bd40d98dc
```

来源快照保存在 `config/atlas_metadata/sources/`，逐文件大小和 SHA-256 记录在 `source_manifest.json`。采用的来源为：

- AAL116：`dpabi/aal_Labels.mat`，116 个连续 label；
- HO112：已核验的 DPABI/YCG cortical 96 + subcortical 16 顺序；
- CC200：`CC200ROI_tcorr05_2level_all.nii`，连续 label 1–200；公开快照无可靠解剖名称表，因此名称、description、network 保持空，不编造；
- Dosenbach160：Info/Center MAT 与 mask，160 行顺序和坐标交叉核对。

稳定身份固定为：

```text
roi_uid  = <atlas_lower>:roi<三位 roi_original_index>
edge_uid = <roi_uid_i>--roi<三位 roi_original_index_j>
```

例如 `aal116:roi001`、`aal116:roi001--roi002`。edge 端点始终按 `roi_original_index` 升序。

### 3.2 单元 ROI/edge manifest

每个 cell 的 `roi_manifest.csv` 复制完整 atlas master ROI 小表，再追加：

```text
structural_status,matrix_position,reason_code,source_roi_index,
mask_kept,mask_valid_rate
```

缺失 ROI 的 `structural_status=structural_unavailable`、`reason_code=ROI_MASK_NOT_KEPT`、`matrix_position` 为空。原始编号、全局列、名称、label 和 description 不删除。

可用 ROI 的 `structural_status=available`、`reason_code` 为空 CSV field、`matrix_position` 为非负 0-based integer。`mask_kept` 为 0/1 integer；`mask_valid_rate` 为 `[0,1]` float，源缺失时为空。CSV 中 nullable integer 的缺失写为空 field，读取后通常表现为 NaN。

每个 cell 的 `edge_manifest.csv` 复制完整理论 edge universe，再追加：

```text
structural_status,matrix_position,reason_code
```

任一端点结构性缺失时，edge 标记 `structural_unavailable`、`reason_code=ROI_ENDPOINT_NOT_KEPT`、`matrix_position` 为空；可用 edge 的 `matrix_position` 与源 FC 列从 0 连续一一对应。

可用 edge 的 `structural_status=available`、`reason_code` 为空 CSV field；`matrix_position` 为 `0..E_source-1` 的连续 integer。

### 3.3 subjects 精确回连

`sample_key=subject_id`，每一行强制带 `dataset_id`。`site_id` 规范为：

```text
<dataset_id>::<source_site_as_string>
```

因此 site 始终按字符串解释并保留源表示，避免前导零或数值/字符串混型。age 单位是 years；scan length 单位是 timepoints。

人口学规则：

- ADHD：`Participant ID` 去首尾引号后精确匹配；`DX>0 → label=1`；官方 `ADHD-200_PhenotypicKey.pdf`（阶段 C 配置快照）核验 `Gender 0=Female, 1=Male`。阶段 A 的 `subjects.csv` 仍保留 raw 0/1，canonical sex 只在阶段 C 按 `0→1,1→0` 派生。
- ABIDE：`SUB_ID` 规范为 7 位后精确匹配；`label=2-DX_GROUP`；`SEX 1=male, 2=female`。
- ABIDE2：phenotype 使用 latin1；按 `SUB_LIST` 精确匹配；`label=2-DX_GROUP`。
- MDD：`subject_id == workbook ID`；MDD sheet→1、Controls sheet→0。2347/2347 精确匹配；当前 XLSX 的匹配集、未匹配集和全表 `Age/Sex` 数值缺失均为 0。manifest 中 age/sex 全为字面 `nan`，canonical 值来自精确匹配 XLSX。
- FCP：按 `<Site>_<Subject ID>` 精确匹配；Sex 的 `m/M→1`、`f/F→2`；176 个 mean FD 缺失保持为空，不从 realignment 文件补造。

每行同时保存 manifest 原始行哈希与 demographic 原始行哈希。程序内部以下划线开头的派生核验字段不进入原始行哈希。

行哈希不是原 CSV/XLSX 字节哈希。可复现规范为：Pandas 解析得到一行字典 → 删除 key 以下划线开头的内部字段 → key 转 string → value 规范为去首尾空白的 string，`None/float NaN` 规范为空串 → 按 key 排序 → `json.dumps(ensure_ascii=false, sort_keys=true, separators=(",",":"))` → 对 UTF-8 bytes 计算 SHA-256。原始文件本身另有文件级 SHA-256，二者职责不同。

### 3.4 被试级 QC

只在当前 cell 结构性可用 edge 上计算。非有限值包括 NaN、+Inf、-Inf。

```text
invalid_edge_ratio
  = 被试非有限可用 edge 数 / 结构性可用 edge 总数

roi_incident_invalid_ratio
  = 被试在某 ROI 上非有限 incident edge 数 / 该 ROI 结构性可用 incident edge 数
```

冻结阈值使用 `>=`：

- `invalid_edge_ratio >= 0.05` → `TOTAL_EDGE_INVALID_GE_5PCT`
- 任一 ROI `incident_invalid_ratio >= 0.30` → `ROI_INCIDENT_INVALID_GE_30PCT`

达到任一阈值则该被试在该 atlas 下 `qc_status=fail`；不删除单个 ROI，不改变该 cell 的矩阵列数。阶段 B 只使用 `qc_status=pass`。QC 不做填补；训练折内填补属于阶段 C。

### 3.5 跨数据集共同空间

对每个 atlas，以稳定 `roi_uid` 计算五个数据集结构性可用 ROI 的精确交集，再按 master ROI 顺序排列；共同 edge 仅保留两个端点都在共同 ROI 集合中的 master edge，并保持 master edge 顺序。

| atlas | 共同 ROI | 共同 edge |
|---|---:|---:|
| HO112 | 111 | 6105 |
| AAL116 | 111 | 6105 |
| Dosenbach160 | 154 | 11781 |
| CC200 | 199 | 19701 |

### 3.6 staging、发布和恢复

完整 20 单元先写入 `outputs/.staging/stage_a_<uuid>/`。全部单元、共同空间、inventory 和 stage manifest 成功后，才发布到正式目录。

默认拒绝覆盖。显式 `--replace-existing` 时，旧 `outputs/cells` 与 `outputs/stage_a` 整体移动到 `outputs/archive/stage_a_<UTC>_<suffix>/`，并保存 `archive_manifest.json`。本轮产生的两个可恢复 archive：

- `outputs/archive/stage_a_20260826T070129Z_c2ef880f`：原始初版；
- `outputs/archive/stage_a_20260826T071101Z_35fdab86`：第一次候选版。

## 4. 配置、src、脚本和测试文件

| 文件 | 任务 | 输入 | 输出/作用 |
|---|---|---|---|
| `config/stage_a.yaml` | 阶段 A resolved config | 已确认数据路径、atlas 区间、人口学规则、QC 阈值 | 冻结 5×4 单元、identity、单位、label/sex 语义和存储策略 |
| `config/stage_a.schema.json` | 配置结构门禁 | `stage_a.yaml` | 约束必需字段、类型、阈值范围和坐标基准 |
| `config/atlas_metadata/sources/` | 权威来源快照 | DPABI 固定 tree 和父项目已核验 HO112 资源 | 原始 NIfTI/MAT/CSV/XLSX、许可证、commit、来源清单和 hash |
| `config/atlas_metadata/master_<atlas>.csv` | atlas 理论完整 ROI master | 固定来源快照 | 4 个 ROI master：112、116、160、200 行 |
| `config/atlas_metadata/master_edges_<atlas>.csv` | atlas 理论完整 edge master | 对应 ROI master | 6216、6670、12720、19900 行 |
| `src/fchn_stage_a_metadata.py` | metadata 纯函数 | 固定来源文件和 config | 解析/核验 AAL、HO112、CC200、Dosenbach160，构建 master ROI/edge |
| `src/fchn_stage_a.py` | cell 纯函数 | 单个 dataset×atlas 源、master、config | identity、subjects、ROI/edge 映射、QC、SHA-256、JSON 写出 |
| `scripts/00_prepare_atlas_metadata.py` | metadata CLI | sources + stage A config | 写四套 master ROI/edge 和 source manifest |
| `scripts/01_prepare_final_inputs.py` | 阶段 A 主 CLI | 20 个 cell、master、config | staging 构建、共同空间、inventory、manifest、archive 和发布 |
| `tests/test_stage_a.py` | 单元/真实输入合同测试 | config、合成 cell、20 个真实源 | 9 项 identity、shape、QC 分母、缺失标记和行哈希测试 |
| `tests/test_stage_a_gates.py` | 阶段级发布门禁 | 当前正式输出和全部只读源 | 8 项 metadata、共同空间、subjects、QC、source/artifact/code hash 和 `_SUCCESS` 测试 |

Python 环境：Python 3.13.9、NumPy 2.3.5、Pandas 2.3.3、PyYAML 6.0.3、SciPy 1.16.3、NiBabel 5.4.2、openpyxl 3.1.5。

## 5. 输出目录和每种文件的含义

### 5.1 单元输出

位置：`outputs/cells/<dataset>/<atlas>/`

| 文件 | 数据形式和尺寸 | 表示什么 | 下一步用途 |
|---|---|---|---|
| `subjects.csv` | CSV，`N×15` | canonical identity、site、label、age、sex、scan length、mean FD、两类来源和行哈希 | 阶段 B 的 sample/site/label 输入；阶段 C 的人口学权威表 |
| `roi_manifest.csv` | CSV，理论 `R×22` | 完整 ROI metadata + 当前 cell 结构状态和 FC 行列位置 | 阶段 C 回连 ROI 解释；结构性缺失不会错位 |
| `edge_manifest.csv` | CSV，`R(R-1)/2 × 11` | 完整 edge identity、两个稳定端点和当前 FC 列位置 | 阶段 C 特征/标志物回连 |
| `fc_source.json` | JSON，小型 descriptor | 源 FC 绝对路径、`N×E` shape、dtype、0-based ROI 顺序、hash、读取规则 | 阶段 C 只加载当前一个 cell 的 FC |
| `ts_inventory.json` | JSON，小型 descriptor | 只登记除 `X_concat` 外各数组的 shape/dtype；不复制数组值 | 审计 TS 身份和结构；不是 TS 数据副本 |
| `nonfinite_mask.npz` | NPZ，bool `N×E` | 源 FC 非有限位置 | QC round-trip；不保存人口学，不用于填 0 |
| `qc_subject.csv` | CSV，`N×13` | 每名被试的可用 edge 数、无效数/比例、最差 ROI/比例、status/reason 和三类 hash | 阶段 B 只选择 pass；阶段 C 审计输入人群 |
| `cell_manifest.json` | JSON，小型清单 | dataset/atlas、实际计数、5 个源文件 hash、7 个工件 hash、identity hash、QC 汇总 | stage manifest 的直接 hash 引用；单元独立审计入口 |
| `_SUCCESS` | 文本一行 | `stage_a_cell_ready` | 仅表示该 cell 完整写出；不能替代阶段级 `_SUCCESS` |

`subjects.csv` 15 列固定为：

```text
sample_key,dataset_id,subject_id,site_id,label,age,sex,scan_length,
mean_fd,source_file,source_row_hash,demographic_source_file,
demographic_source_row_hash,mean_fd_source,sex_encoding_rule
```

`sample_key/dataset_id/subject_id/site_id/source paths/hash/rule` 为 string；`label/scan_length` 为 integer；`age/sex/mean_fd` 为 numeric，缺失写为空 CSV field，Pandas 默认读取为 NaN。CSV 统一带 header、UTF-8 编码；文本 hash 针对脚本实际写出的 bytes。

`roi_manifest.csv` 22 列固定顺序为：

```text
atlas_id,roi_uid,roi_original_index,global_original_column,roi_name,roi_label,
description,hemisphere,network,x,y,z,metadata_source,metadata_version,
metadata_license,metadata_sha256,structural_status,matrix_position,reason_code,
source_roi_index,mask_kept,mask_valid_rate
```

`edge_manifest.csv` 11 列固定顺序为：

```text
atlas_id,edge_uid,roi_uid_i,roi_uid_j,roi_original_index_i,
roi_original_index_j,global_original_column_i,global_original_column_j,
structural_status,matrix_position,reason_code
```

`edge_uid` 的规范形式只在开头保存一次 atlas namespace：`aal116:roi001--roi002`；完整端点仍分别保存在 `roi_uid_i=aal116:roi001`、`roi_uid_j=aal116:roi002`，解释 edge 时必须使用端点列，不能拆字符串猜测。

`qc_subject.csv` 13 列固定为：

```text
dataset_id,sample_key,atlas_id,qc_status,reason_code,
available_edge_count,invalid_edge_count,invalid_edge_ratio,
max_roi_invalid_ratio,max_invalid_roi_uid,fc_source_hash,
roi_manifest_hash,edge_manifest_hash
```

### 5.2 阶段级输出

位置：`outputs/stage_a/`

| 文件 | 形式/尺寸 | 含义 |
|---|---|---|
| `common_roi_<atlas>.csv` | 4 个 CSV，111/111/154/199 行 | 五数据集共同 ROI，master 顺序，含 `common_matrix_position` |
| `common_edge_<atlas>.csv` | 4 个 CSV，6105/6105/11781/19701 行 | 五数据集共同 edge，master 顺序，含稳定端点 |
| `input_inventory.csv` | CSV，20 行 | 每个 cell 的计数、FC shape/dtype、FC/TS/manifest/mask/demographic 路径与 hash、cell manifest hash |
| `atlas_metadata_sources.csv` | CSV，4 行 | 每个 atlas 的 master 路径/hash、metadata 来源/version/license/hash 和来源快照 manifest hash |
| `stage_a_summary.md` | Markdown，20 行结果表 | 机器构建产生的聚合计数摘要，不含被试级记录 |
| `stage_a_manifest.json` | JSON | 当前 20 个 cell manifest 的路径/hash、config hash、8 个实施文件 hash、共同空间计数、阶段工件 hash |
| `_SUCCESS` | 文本一行 | `stage_a_ready`，阶段 B 允许启动的必要标志之一 |

`stage_a_manifest.json` 不内嵌 20 份巨大 cell payload，而是逐项保存当前 `cell_manifest.json` 的 SHA-256。发布门禁重新读取磁盘文件并比较，防止单元重建后旧 stage manifest 误判通过。

阶段级 schema：`common_roi_<atlas>.csv` 等于 master ROI 16 列加 `common_matrix_position`；`common_edge_<atlas>.csv` 等于 master edge 8 列加 `common_matrix_position`。`input_inventory.csv` 固定 21 列：

```text
dataset_id,atlas_id,subject_count,theoretical_roi_count,available_roi_count,
theoretical_edge_count,available_edge_count,fc_shape,fc_dtype,
fc_source_path,ts_source_path,manifest_source_path,roi_mask_source_path,
demographic_source_path,fc_source_sha256,ts_source_sha256,
manifest_source_sha256,roi_mask_source_sha256,demographic_source_sha256,
cell_manifest_path,cell_manifest_sha256
```

`atlas_metadata_sources.csv` 固定 11 列：

```text
atlas_id,master_roi_path,master_roi_sha256,master_edge_path,master_edge_sha256,
metadata_source,metadata_version,metadata_license,metadata_source_sha256,
source_snapshot_manifest_path,source_snapshot_manifest_sha256
```

`stage_a_manifest.json` 顶层字段固定为 `stage,status,cell_count,cells,config_path,config_sha256,implementation_files,common_spaces,artifacts`；JSON object 不承诺字段显示顺序，语义按 key。`config/stage_a.schema.json` 是 `stage_a.yaml` 必需字段树的机器可读权威；主要顶层 key 为 `project_root,data_root,datasets,atlases,theoretical_roi_count,global_column_start_1based,manifest_files,roi_mask_files,demographic_files,demographic_encoding,label_semantics,sex_encoding_rule,identity,units,qc,storage`，实际值以 resolved YAML 为准，无隐式默认值。

每个 cell 的 5 个源文件明确为 FC、TS、dataset manifest、ROI mask、demographic；7 个被 hash 工件明确为 `subjects.csv,roi_manifest.csv,edge_manifest.csv,fc_source.json,ts_inventory.json,nonfinite_mask.npz,qc_subject.csv`。`cell_manifest.json` 不能包含自身 hash，`_SUCCESS` 在 manifest 后写出，因此二者不在 `artifacts` 中，而由 stage manifest hash 和内容门禁分别校验。

stage 的被 hash 工件明确为 4 个 common ROI、4 个 common edge、`input_inventory.csv`、`atlas_metadata_sources.csv`、`stage_a_summary.md`。`stage_a_manifest.json` 不能自哈希；stage `_SUCCESS` 在其后写出，只校验固定内容。JSON 文本由 UTF-8、2 空格缩进、key 排序写出；CSV/NPZ hash 针对磁盘实际 bytes。源路径在 cell manifest 中保存绝对路径；项目内工件路径在 stage manifest 中保存相对项目根路径。

`cell_manifest.status` 和 `stage_a_manifest.status` 当前唯一允许发布值均为 `passed`。有效性判定顺序为：先验证 stage `_SUCCESS` 固定内容 → stage manifest `status/cell_count/config/code hash` → 20 个 cell manifest hash → 每个 cell `status/identity/count/source/artifact hash` → cell `_SUCCESS`。任何一步失败均视为阶段 A 无效；不能只看遗留 `_SUCCESS`。

当前信任边界是本机项目目录和只读源快照，没有外部签名、远程时间戳或第三方 run hash。manifest 无法自哈希，`_SUCCESS` 是发布激活标记而不是防篡改签名；对本地文件的非授权整体篡改不在本阶段威胁模型内。需要跨主机发布时，阶段 E 应再生成外部校验清单或签名，不能把当前 `_SUCCESS` 当作密码学证明。

## 6. 20 个最终单元的实际结果

| dataset | atlas | subjects | available ROI | available edge | QC pass | QC fail |
|---|---|---:|---:|---:|---:|---:|
| adhd | HO112 | 844 | 112 | 6216 | 843 | 1 |
| adhd | AAL116 | 844 | 115 | 6555 | 839 | 5 |
| adhd | Dosenbach160 | 844 | 159 | 12561 | 837 | 7 |
| adhd | CC200 | 844 | 200 | 19900 | 840 | 4 |
| abide | HO112 | 1085 | 112 | 6216 | 1077 | 8 |
| abide | AAL116 | 1085 | 112 | 6216 | 1079 | 6 |
| abide | Dosenbach160 | 1085 | 155 | 11935 | 1077 | 8 |
| abide | CC200 | 1085 | 199 | 19701 | 1076 | 9 |
| abide2 | HO112 | 1027 | 111 | 6105 | 1022 | 5 |
| abide2 | AAL116 | 1027 | 113 | 6328 | 1023 | 4 |
| abide2 | Dosenbach160 | 1027 | 158 | 12403 | 1017 | 10 |
| abide2 | CC200 | 1027 | 200 | 19900 | 1016 | 11 |
| mdd | HO112 | 2347 | 112 | 6216 | 2344 | 3 |
| mdd | AAL116 | 2347 | 114 | 6441 | 2335 | 12 |
| mdd | Dosenbach160 | 2347 | 159 | 12561 | 2333 | 14 |
| mdd | CC200 | 2347 | 200 | 19900 | 2341 | 6 |
| fcp | HO112 | 858 | 112 | 6216 | 858 | 0 |
| fcp | AAL116 | 858 | 113 | 6328 | 852 | 6 |
| fcp | Dosenbach160 | 858 | 155 | 11935 | 850 | 8 |
| fcp | CC200 | 858 | 200 | 19900 | 851 | 7 |

QC fail 是 atlas-specific：不能把某被试在一个 atlas 下的 fail 状态扩展到其他 atlas。

## 7. 执行命令

在项目根目录执行：

```powershell
Set-Location 'C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825'
$env:PYTHONDONTWRITEBYTECODE='1'

# 仅当来源快照或 metadata 构建逻辑改变时重建 master
python scripts\00_prepare_atlas_metadata.py

# 默认拒绝覆盖；需要替换时先自动归档旧版
python scripts\01_prepare_final_inputs.py --replace-existing

# 全量阶段 A 门禁
python -m pytest tests -q -p no:cacheprovider
```

本次全量门禁新鲜结果：

```text
17 passed in 70.28s
```

当前脚本不支持只重建某一个正式 cell，也不支持从半成品 staging 续跑；这是为了避免部分新旧版本混合。失败时脚本只清理本次 UUID staging，正式输出保持不动。若进程被强制终止并留下 orphan staging，确认路径严格位于 `outputs/.staging/stage_a_<uuid>` 且正式输出未切换后，才可删除该 orphan，再完整重跑 20 单元。

发布事务顺序固定为：完整 staging 内先写 20 个 cell `_SUCCESS` 和 stage `_SUCCESS` → 旧 `cells/stage_a` 同时移入同一 archive → 新 `cells` 先 rename 到正式位置 → 新 `stage_a` 最后 rename，stage `_SUCCESS` 因此是最后可见的激活标记 → 删除空 staging。两个 rename 不是文件系统单一原子事务；若进程在中间被强制终止，正式根可能只有新 `cells` 而没有 `stage_a`，此时阶段 A 必因缺少 stage `_SUCCESS` 失败，禁止下游启动。下一次 `--replace-existing` 会归档这个不完整候选并完整重建两目录。

恢复 archive 时先核对 `archive_manifest.json` 的 `original_path/archive_path/stage_manifest_sha256`；将当前 `outputs/cells` 和 `outputs/stage_a` 另行移动到新的人工备份目录，再把目标 archive 内的 `cells` 与 `stage_a` 整体移回 `outputs/`，最后重新运行全部阶段 A 门禁。禁止只恢复其中一个目录。archive manifest 锁定旧 stage manifest，但不递归重复保存所有旧文件 hash；旧 stage manifest/cell manifest 负责逐层审计。

## 8. 门禁覆盖

1. 四套 atlas master ROI/edge 的数量、列、顺序和稳定 ID；
2. atlas 来源快照逐文件 SHA-256；
3. AAL hemisphere 与官方名称后缀一致；
4. 20 个真实 FC/TS/mask/manifest 的身份和 shape；
5. 缺失 ROI/edge 保留原始编号、全局列和空 matrix position；
6. ROI incident 分母是 incident edge 数，不随被试数改变；
7. subjects 15 列、exact demographic match、source row hash、site string 和编码合同；
8. QC 13 列、逐被试指标、稳定最差 ROI UID、状态和 hash；
9. 4 个共同 ROI/edge 空间是精确交集且顺序等于 master 子序列；
10. 每个 cell 的 5 个源文件和 7 个工件 hash/bytes 当前有效；
11. stage manifest 指向当前 20 个 cell manifest，而非陈旧内嵌副本；
12. config/schema/src/scripts/tests 的实施文件 SHA-256 当前有效；
13. 20 个 cell `_SUCCESS` 和阶段 `_SUCCESS` 内容正确。

## 9. 重要限制与已处理异常

- CC200 没有从当前权威快照取得可靠解剖名称表，相关文字字段按事实留空。
- ADHD Gender 源 0/1 的男女语义已由官方 `ADHD-200_PhenotypicKey.pdf` 核验；阶段 A 不改写 raw 字段，阶段 C 才生成 canonical male=0/female=1。
- ADHD phenotype 有 1 个 `Gender=[]`，聚合核验确认对应 manifest 的唯一 sex 缺失；`[]` 只作为该源缺失标记处理。
- FCP 176 个 mean FD 缺失保留为空。
- openpyxl 读取 MDD XLSX 时报告“未知扩展不支持”警告；身份 2347/2347、诊断、age/sex 聚合和门禁均用实际单元格值验证。警告不被静默删除，也未用于推断缺失。
- `ts_inventory.json` 仅是非 `X_concat` 数组描述符，不保存 subject/ROI 数组值；实际值仍由源 TS hash 锁定。
- TS 源当前包含 `X_concat,subject_ids,roi_indices,lengths,offsets,roi_valid,roi_valid_rate,atlas_name,qc_version`。阶段 A 只门禁 `subject_ids[N]` 与 FC/manifest 一致、`roi_indices[R_cell]` 与 FC/mask 一致，并登记非 `X_concat` key 的实际 shape/dtype；常见关系为 `lengths[N]`、`offsets[N+1]`、`roi_valid[N,R_cell]`，但这些辅助数组关系当前不是阶段 A 发布门禁。为控制内存，阶段 A 有意不读取/登记 `X_concat` shape/dtype，因此“TS shape 核验”仅指已列出的 identity/descriptor key，不包括 `X_concat`。Stage C 若使用 TS，必须先单独冻结并测试 `X_concat` 的布局合同，再以 `allow_pickle=false` 打开当前 cell 源 TS并核对 source hash；不能把 inventory 当数组数据。
- `fc_source.json` 是单 cell 的最小 FC 消费入口，不等价于完整审计；完整审计必须从 `cell_manifest.json` 和 `stage_a_manifest.json` 检查全部源/工件/代码 hash。
- 当前没有单独环境 lock 文件，也没有自动安装依赖；本文记录的是实际通过门禁的精确版本。更换 Python/NumPy/Pandas/SciPy/NiBabel/openpyxl 后必须完整重跑 metadata 和阶段 A 门禁，不能沿用现有 `_SUCCESS` 作为兼容证明。
- 本阶段不填补 FC、不训练模型、不生成 split、不修改原始 SSL 数据。

## 10. 阶段 A 到阶段 B 的输入输出关系

阶段 B 的 split plan 只允许在以下条件全部满足时启动：

```text
outputs/stage_a/_SUCCESS == stage_a_ready
stage_a_manifest.status == passed
20 个 cell manifest hash 当前有效
阶段 A 全量 pytest 为 0 failure
```

逐字段接口：

| 阶段 A 输出 | 阶段 B 输入用途 |
|---|---|
| `subjects.csv: dataset_id,sample_key,site_id,label` | 构造疾病数据的 LOSO 和 pooled10_site_label 成员 |
| `qc_subject.csv: qc_status,reason_code` | 仅 `pass` 样本进入 split；fail 保留审计但不分配 role |
| `cell_manifest.json` | 锁定 dataset/atlas、被试计数和输入工件 hash |
| `stage_a_manifest.json` | 锁定 20 个单元及实施版本，是阶段 B 的父 manifest |
| `roi_manifest.csv/edge_manifest.csv` | 阶段 B 不改变其顺序；阶段 C 按 split 加载 FC 时使用 |
| `common_roi/edge_<atlas>.csv` | 阶段 C normative-common 空间输入；阶段 B 只记录其 hash，不重新计算 |

阶段 B 还从路径和 cell manifest 取得 `atlas_id/dataset_id`，并以 `subject_id==sample_key` 作为审计回连；不会复制 age/sex/mean FD。阶段 B 不得重算共同空间、改变 ROI/edge 顺序或把 QC fail 样本加入任何 role。本文的 `passed` 不是人工声明：它由上述 `python -m pytest tests -q -p no:cacheprovider` 的 0 failure 结果和当前 manifest/hash 门禁共同验证。

阶段 B 对每个 `dataset×atlas` 只能读取该 cell 自己的 `subjects.csv` 和 `qc_subject.csv`，不得跨 atlas 复用 QC pass 集合。单数据集内 `sample_key` 必须唯一；跨数据集的唯一键始终是 `(dataset_id,sample_key)`，即使当前 6161 个原始 subject_id 未发现跨数据集重复，也不能依赖这一偶然事实省略 dataset namespace。

阶段 B 将只处理四个疾病数据集 `adhd, abide, abide2, mdd`；FCP 不进入疾病 split。计划输出应为 `4 atlas × 4 disease dataset × 2 protocol = 32` 组 split plan，并成为阶段 C 每个 outer-fold FCHN 闭环的成员输入。
