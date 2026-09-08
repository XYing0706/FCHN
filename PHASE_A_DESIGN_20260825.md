# FCHN 第一主线（阶段 A）设计

**状态：** 已批准，待实施  
**日期：** 2026-08-25  
**项目根目录：** `C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`  
**输入根目录：** `C:\XY\FedTopo-Brain\SSL\data`

## 1. 目标与边界

阶段 A 一次性准备四套 atlas 与五个 dataset 的全部 20 个最终输入单元。每个单元是独立可加载、独立可校验的物理目录；不得把一个 dataset 的四套 atlas 合并成一个大文件，也不得把一个 atlas 的五个 dataset 合并成一个大文件：

```text
atlas:   HO112 -> AAL116 -> Dosenbach160 -> CC200
dataset: adhd -> abide -> abide2 -> mdd -> fcp
```

本阶段建立可审计的被试、ROI、edge、FC、nonfinite mask 和 subject-self QC 产物。它不划分 protocol/fold，不做 imputation、Ridge、Scaler、PCA、KMeans、分类、选参或性能评估。

物理隔离规则：单元目录 `outputs/cells/<dataset>/<atlas>/` 内的任何算法输入只能读取本目录文件和对应的只读源文件；调用 `abide/AAL116` 不得加载 `abide` 的其他 atlas，也不得加载其他 dataset 的 AAL116。小型 `subjects.csv` 在单元目录内允许重复，以保证单元可独立迁移和加载；这类重复必须由 `subjects_source_hash` 标识并在审计中核对。

## 2. 设计原则

1. 原始输入只读，所有生成文件只写入项目根目录。
2. 以稳定 ID 对齐，禁止依赖 CSV 行号、NPZ 行号或数组列号猜测身份。
3. 删除 ROI 后保留原始编号，不重新编号。
4. 结构性不可用与观测 nonfinite 分开记录。
5. QC 只使用被试自身数据，不读取标签或模型性能决定删除。
6. CSV 保存表格，非 object NPZ 保存矩阵；读取 NPZ 固定 `allow_pickle=false`。
7. 候选输出先写 staging，完成 round-trip 和 hash 验证后原子发布；禁止覆盖既有成功结果。
8. 当前目录不是 Git 仓库，阶段版本追踪使用 source file SHA-256、resolved config hash、输入快照 hash 和 stage manifest。

## 3. 输入契约

每个 `dataset x atlas` 单元必须提供：

- manifest CSV；
- 正式人口学/phenotype 文件：ADHD200 phenotype、ABIDE phenotype、ABIDE2 phenotype、REST-meta-MDD phenotype 和 `FCP_RfMRIMaps_Info.csv`；
- `roi_mask_<dataset>.csv`（FCP 为 `roi_mask_FCP.csv`）；
- 当前 atlas 的 `<atlas>_fc.npz`；
- 当前 atlas 的 `<atlas>_ts.npz`。

FC NPZ 至少包含：

```text
X, subject_ids, roi_indices, view_missing, atlas_name, qc_version
```

其中 `X` 是按 `roi_indices` 顺序展开的上三角 FC edge，不是完整 `R x R` 方阵。阶段 A 对每个独立单元验证：

- manifest、FC、TS 的 subject identity 一对一；
- `X.shape[0] == len(subject_ids)`；
- `X.ndim == 2`；
- `X.shape[1] == R*(R-1)/2`，`R=len(roi_indices)`；
- 不把 `X.shape[1]` 误解释为 `R*R`，也不在本阶段强行恢复和保存完整方阵；
- `roi_indices` 唯一、严格递增并能与 ROI mask 对齐；
- atlas 名称、文件名和配置一致；
- `view_missing` 长度与被试数一致。

TS 仅用于存在性、subject ID、ROI identity、shape 和输入 hash 库存核验；本阶段不从 TS 重算 FC，避免无必要的大规模重复计算。

## 4. 被试身份

- `sample_key = subject_id`；所有 ID 按字符串读写并保留前导零。
- 所有输出表强制包含 `dataset_id`。
- 跨 dataset 唯一键为 `(dataset_id, sample_key)`。
- `subjects.csv` 每名被试一行，权威字段为：

```text
sample_key,dataset_id,subject_id,site_id,label,age,sex,scan_length,
mean_fd,source_file,source_row_hash
```

manifest 中 `T` 映射为 `scan_length`，`meanFD_Power` 映射为 `mean_fd`；`meanFD_Jenkinson` 作为原始审计字段保留在输入 inventory，不替代主字段。该选择与旧版已验证 Stage 01 一致，并明确写入 resolved config。

ADHD/ABIDE/ABIDE2 以 manifest 人口学为主并核验 phenotype 文件；MDD 的 age/sex 使用 REST-meta-MDD phenotype 按精确 subject identity 回填；FCP 使用 `FCP_RfMRIMaps_Info.csv` 按精确 identity 核验/补充 age/sex。任何模糊匹配、多对一或 label 冲突都使阶段失败。sex 的原始编码和规范化映射必须按 dataset 在 config 中显式声明并保存 provenance，不由数值范围自动猜测。FCP mean FD 缺失保持为空，不填补、不删除。

除手册规定字段外，`subjects.csv` 增加必要 provenance：

```text
demographic_source_file,demographic_source_row_hash,
mean_fd_source,sex_encoding_rule
```

## 5. ROI 元数据与原始列映射

用户确认的原始全列 1-based 区间为：

| atlas | 原始全列 | ROI 数 | 来源定义 |
|---|---:|---:|---|
| AAL116 | 1-116 | 116 | Automated Anatomical Labeling atlas |
| HO112 cortical | 117-212 | 96 | Harvard-Oxford cortical areas |
| HO112 subcortical | 213-228 | 16 | Harvard-Oxford subcortical areas |
| CC200 | 229-428 | 200 | Craddock 200 parcellation |
| Dosenbach160 | 1409-1568 | 160 | Dosenbach 160 functional ROIs |

`global_original_column` 使用上述 1-based 全列编号；`roi_original_index` 是 atlas 内 1-based 编号；`matrix_position` 仅表示当前 NPZ 中的位置。结构性缺失或 QC 删除都不能改变前两者。

本地输入已核验：FC/TS NPZ 的 `roi_indices` 是 atlas-local 0-based，ROI mask 的 `orig_col_0idx` 是原始全列 0-based。因此转换固定为：

```text
roi_original_index = roi_indices + 1
global_original_column = orig_col_0idx + 1
```

同时使用 atlas 起始列交叉验证：AAL116=`roi_indices+1`，HO112=`roi_indices+117`，CC200=`roi_indices+229`，Dosenbach160=`roi_indices+1409`。两条计算路径不一致时阶段失败，禁止用位置修补。

### 5.1 公开元数据来源门禁

每套 atlas 的元数据按以下优先级核验：

1. 原始论文及其正式补充材料；
2. atlas 官方/维护方发布文件；
3. 被广泛使用且注明来源和版本的神经影像工具包。

只有同时满足以下条件才可进入 master ROI manifest：

- ROI 数量符合 116/112/200/160；
- 编号和左右半球顺序与本项目原始列顺序一致；
- cortical/subcortical 组合规则明确；
- 空间、阈值或版本差异已记录；
- 文件来源、访问日期、许可证和 SHA-256 已保存；
- 与本地 `roi_indices`/ROI mask 的保留顺序可逆映射。

不能仅因文件名包含 atlas 名称就采用。任何顺序歧义都使阶段 A 失败，不发布 `_SUCCESS`。

### 5.2 元数据字段

`config/atlas_metadata/master_<atlas>.csv` 保存 atlas 理论完整 ROI universe，每个 `roi_uid` 只出现一次，至少包含：

```text
atlas_id,roi_uid,roi_original_index,global_original_column,
roi_name,roi_label,description,hemisphere,network,x,y,z,
metadata_source,metadata_version,metadata_license,metadata_sha256
```

每个单元自己的 `outputs/cells/<dataset>/<atlas>/roi_manifest.csv` 都复制该 atlas 的完整 ROI universe，并增加该单元状态列；这份小型表的复制是有意的，用于单元独立加载。状态列为：

```text
structural_status,matrix_position,source_roi_index,reason_code
```

缺失 ROI 必须保留完整身份，示例：

```text
roi_uid=aal116:roi102
roi_original_index=102
global_original_column=102
structural_status=structural_unavailable
matrix_position=null
reason_code=ROI_MASK_NOT_KEPT
```

不虚构不存在的字段。CC200 若权威来源只提供 parcel ID、质心或网络信息，则据实保存；不得编造解剖学名称。英文权威名称为主字段，中文翻译若生成只能作为独立辅助字段并记录翻译来源。

## 6. Edge 身份

对每个 atlas 的完整 master ROI universe 建立稳定 edge universe：

`roi_uid` 固定为 `<atlas_id>:roi<三位编号>`；`edge_uid` 固定为 `<atlas_id>:roi<三位编号>--roi<三位编号>`，端点按 `roi_original_index` 升序。

`config/atlas_metadata/master_edges_<atlas>.csv` 每个 `edge_uid` 只出现一次；每个单元复制一份小型 `edge_manifest.csv`，至少包含：

```text
atlas_id,edge_uid,roi_uid_i,roi_uid_j,
roi_original_index_i,roi_original_index_j,
global_original_column_i,global_original_column_j,
structural_status,matrix_position
```

单元 FC edge 列必须由其 `roi_indices` 确定性重建并映射到该单元完整 edge universe。结构性不存在的 edge 标记 `structural_unavailable`，`matrix_position=null`，不作为 NaN 测量值参与 QC；保留端点 `roi_uid_i/roi_uid_j` 和两端原始编号，禁止删除后按新列号解释。

## 7. Subject-self QC

对每个 `atlas x dataset x subject`，仅在该 dataset 实际结构性可用 edge 上计算：

```text
invalid_edge_ratio = invalid_edge_count / available_edge_count
roi_incident_invalid_ratio = invalid incident edges / available incident edges
```

冻结规则：

```text
invalid_edge_ratio >= 0.05
    -> fail / TOTAL_EDGE_INVALID_GE_5PCT

max_roi_incident_invalid_ratio >= 0.30
    -> fail / ROI_INCIDENT_INVALID_GE_30PCT

otherwise
    -> pass
```

结构性不可用 edge 不计分母。被试 fail 只影响该 atlas，不改变其 `sample_key`、人口学或其他 atlas 状态。本阶段保存 nonfinite mask，但不插补数据；原本有限值必须逐元素保持不变。

每个单元的 `qc_subject.csv` 只包含当前 `dataset x atlas`，并强制包含：

```text
dataset_id,sample_key,atlas_id,qc_status,reason_code,
available_edge_count,invalid_edge_count,invalid_edge_ratio,
max_roi_invalid_ratio,max_invalid_roi_uid,
fc_source_hash,roi_manifest_hash,edge_manifest_hash
```

多个失败条件同时存在时，`reason_code` 使用稳定分号分隔顺序；不得只保留最后一个原因。

## 8. 输出结构：一个单元一个目录

```text
FCHN_20260825/
├─ config/
│  ├─ stage_a.yaml
│  ├─ stage_a.schema.json
│  └─ atlas_metadata/
│     ├─ sources/              # 官方/维护方原始文件只读快照
│     └─ master_<atlas>.csv    # 经核验的完整 atlas 元数据
├─ doc/
│  ├─ PHASE_A_DESIGN_20260825.md
│  └─ PHASE_A_IMPLEMENTATION_20260825.md
├─ src/
│  └─ fchn_stage_a.py
├─ scripts/
│  └─ 01_prepare_final_inputs.py
├─ tests/
│  └─ test_stage_a.py
└─ outputs/
   ├─ cells/
   │  ├─ adhd/HO112/
   │  │  ├─ subjects.csv
   │  │  ├─ roi_manifest.csv
   │  │  ├─ edge_manifest.csv
   │  │  ├─ fc_source.json       # 源 FC 文件、shape、hash、读取契约
   │  │  ├─ fc.npz               # 可选规范化副本，默认不复制大矩阵
   │  │  ├─ ts_inventory.json
   │  │  ├─ nonfinite_mask.npz
   │  │  ├─ qc_subject.csv
   │  │  ├─ cell_manifest.json
   │  │  └─ _SUCCESS
   │  └─ <other 19 dataset/atlas cells>/
   └─ stage_a/
      ├─ input_inventory.csv       # 仅为小型索引，不承载 FC 矩阵
      ├─ atlas_metadata_sources.csv
      ├─ stage_a_manifest.json
      ├─ stage_a_summary.md
      └─ _SUCCESS
```

每个单元的 `fc_source.json` 必须保存该 `dataset x atlas` 的源 FC 路径、只读 hash、shape、dtype、`roi_indices` 摘要和读取方式。若需要规范化副本，单元 `fc.npz` 使用非 object 数组，至少包含：

```text
X, sample_key_order, roi_original_index_order,
edge_master_position_order,
source_fc_sha256, roi_manifest_sha256, edge_manifest_sha256
```

`edge_master_position_order` 将当前 FC 列映射到该单元 `edge_manifest.csv` 的唯一 edge 行。不得在 NPZ 内重复保存其他 dataset/atlas 的数据，也不得在 NPZ 内重复保存人口学或 label。默认不复制原始大矩阵，阶段 A 通过 `fc_source.json` + hash + cell manifest 将现有单元源文件冻结为下游输入；若后续需要规范化副本，也必须仍是一单元一个独立 `fc.npz`。

## 9. 实现结构

保持三层最小结构：

1. `src/fchn_stage_a.py`：纯函数，负责读取验证、身份映射、manifest、QC 和 hash。
2. `scripts/01_prepare_final_inputs.py`：参数解析、20 单元循环、staging 和原子发布。
3. `tests/test_stage_a.py`：合成数据单元测试、真实输入只读契约测试和发布 round-trip 测试。

不为单次用途建立额外框架、插件系统或多级类层次。

## 10. 错误处理与发布门禁

以下任一条件阻止 `_SUCCESS`：

- 输入文件缺失、hash 读取失败或 NPZ object array；
- manifest/FC/TS 被试身份不一一对应；
- ROI mask、`roi_indices` 和 FC edge 数无法一致解释；
- atlas 元数据数量或顺序无法确认；
- `(dataset_id, sample_key)` 重复，或任一 master manifest 中 `roi_uid`/`edge_uid` 重复；
- 输出 round-trip 后 ID、shape、顺序、有限值或 hash 不一致；
- 任一输出路径越出项目根目录；
- 20 个输入单元未全部完成。

QC fail 被试是有效审计结果，不等同于阶段失败。阶段 A 成功表示所有单元被正确处理并记录，不表示所有被试均通过 QC。

## 11. 测试与验收

采用测试先行。测试至少覆盖：

- 四套 atlas 原始列区间的数量、无重叠和可逆映射；
- 删除 ROI 后原始编号不变；
- 结构性 edge 不进入 QC 分母；
- `>=0.05` 和 `>=0.30` 边界行为；
- 多原因 reason code 稳定排序；
- FC 列数与上三角 edge 身份一致；
- nonfinite mask round-trip；
- 原始有限 FC 值逐元素不变；
- CSV/NPZ ID 和顺序 round-trip；
- 文件大小、SHA-256、config hash、输入快照 hash 和 `_SUCCESS` 一致；
- 第二次运行拒绝覆盖已成功产物。

最终验收必须确认：20/20 单元完成，20 个独立 `cell_manifest.json` 和 `_SUCCESS` 存在，全部 artifact hash 通过，单元级 ROI/edge/FC/QC 可独立读取，原始输入修改时间和 hash 未变化。不得用一个跨单元大文件替代上述 20 个单元。

## 12. 执行命令

```powershell
$py = "C:\Users\CQQ\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $py -m pytest `
  "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\tests\test_stage_a.py"

& $py `
  "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\scripts\01_prepare_final_inputs.py" `
  --config "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\config\stage_a.yaml" `
  --data-root "C:\XY\FedTopo-Brain\SSL\data"
```

## 13. 与下一主线衔接

阶段 A 输出是阶段 B/C 的冻结输入：

| 阶段 A 输出 | 下游用途 |
|---|---|
| 单元 `subjects.csv` | 阶段 B 按该 dataset/site/label 建立 split plan |
| 单元 `qc_subject.csv` | 阶段 B 确定该 dataset/atlas 的 eligible 成员 |
| 单元 ROI/edge manifest | 阶段 C 对该 atlas/dataset 精确对齐 |
| 单元 `fc_source.json` 或独立 FC NPZ | 阶段 C 仅加载当前 outer/inner task 所需的一个单元 |
| 单元 nonfinite mask | 阶段 C 当前单元 train-only median imputation 的缺失身份依据 |
| 单元 manifest + stage_a 索引 | 阶段 B/C 验证该单元输入未漂移 |

下一主线先读取 `_SUCCESS` 和 `stage_a_manifest.json`；任何 hash 不匹配都必须停止 split 生成。

## 14. 阶段说明文档要求

实施完成后生成 `doc/PHASE_A_IMPLEMENTATION_20260825.md`，记录：

- 主线目标和范围；
- 实际输入文件、版本、许可和 hash；
- 实际输出、schema、shape、行数和解释；
- 方法和实现细节；
- QC 通过/失败计数与 reason code；
- 执行环境、依赖版本、脚本和完整命令；
- 测试、验收和 round-trip 结果；
- 已知限制、失败恢复和重跑规则；
- 阶段 A 输出如何成为阶段 B/C 输入；
- 下一主线的前置条件和任务清单。
