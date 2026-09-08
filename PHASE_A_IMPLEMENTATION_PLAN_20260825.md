# FCHN 第一主线阶段 A 实施计划

**目标：** 为 4 个 atlas × 5 个 dataset 建立 20 个可独立加载、可审计、保留完整 ROI/edge 身份的最终输入单元。

**架构：** 每个 `outputs/cells/<dataset>/<atlas>/` 是最小物理加载单元，内部保存该单元的小型 subjects、完整理论 ROI/edge manifest、FC 源引用、TS inventory、nonfinite mask、subject-self QC、cell manifest 和 `_SUCCESS`。原始 FC 大矩阵默认不复制，只通过绝对源路径、输入 hash、shape、dtype 和顺序摘要冻结；若需要副本也只能是一单元一个 NPZ。

**技术栈：** Python 3.13 bundled runtime、NumPy（`allow_pickle=false`）、Pandas、PyYAML、pytest、标准库 `hashlib/json/pathlib`。不引入数据库、工作流框架或对象序列化模型。

---

## 文件职责

- Create: `config/stage_a.yaml`：项目根、输入根、dataset/atlas 顺序、理论 ROI 区间、字段映射、QC 阈值、输出策略。
- Create: `config/stage_a.schema.json`：对配置结构做最小 JSON Schema 校验。
- Create: `config/atlas_metadata/master_<atlas>.csv`：四套 atlas 理论完整 ROI metadata；每个 `roi_uid` 一行。
- Create: `config/atlas_metadata/master_edges_<atlas>.csv`：四套 atlas 理论完整 edge universe；每个 `edge_uid` 一行。
- Create: `config/atlas_metadata/sources/`：公开来源快照、来源记录和 SHA-256；来源顺序未核验前不得发布。
- Create: `src/fchn_stage_a.py`：纯函数和数据结构，负责读取、identity、ROI/edge 映射、QC、hash、cell manifest。
- Create: `scripts/01_prepare_final_inputs.py`：命令行入口、20 单元循环、staging、原子发布、最终 stage manifest。
- Create: `tests/test_stage_a.py`：合成输入、真实输入契约、20 单元扫描和 round-trip 测试。
- Create: `doc/PHASE_A_IMPLEMENTATION_20260825.md`：执行完成后的输入/输出、来源、命令、测试、计数、hash、限制和下一步说明。
- Modify: `doc/PHASE_A_DESIGN_20260825.md`：只在实现事实与已批准设计产生差异时更新，并记录差异原因。

## Task 1: 写配置和最小 schema

**Files:**
- Create: `config/stage_a.yaml`
- Create: `config/stage_a.schema.json`
- Test: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试，锁定 20 单元、路径和阈值**

```python
import yaml

def test_stage_a_config_has_20_cells_and_frozen_thresholds():
    config = yaml.safe_load(TEST_CONFIG.read_text(encoding="utf-8"))
    assert len(config["datasets"]) == 5
    assert len(config["atlases"]) == 4
    assert config["qc"]["subject_invalid_edge_ratio"] == 0.05
    assert config["qc"]["roi_incident_invalid_ratio"] == 0.30
    assert config["storage"]["unit_pattern"] == "outputs/cells/{dataset}/{atlas}"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
$py = "C:\Users\CQQ\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m pytest "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\tests\test_stage_a.py::test_stage_a_config_has_20_cells_and_frozen_thresholds" -q
```

预期：因配置文件和加载函数尚未存在而失败。

- [ ] **Step 3: 写最小配置**

配置固定：

```yaml
project_root: C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825
data_root: C:\XY\FedTopo-Brain\SSL\data
datasets: [adhd, abide, abide2, mdd, fcp]
atlases: [HO112, AAL116, Dosenbach160, CC200]
theoretical_roi_count: {HO112: 112, AAL116: 116, Dosenbach160: 160, CC200: 200}
global_column_start_1based: {HO112: 117, AAL116: 1, Dosenbach160: 1409, CC200: 229}
manifest_files: {adhd: manifest_adhd.csv, abide: manifest_abide.csv, abide2: manifest_abide2.csv, mdd: manifest_mdd.csv, fcp: manifest_FCP.csv}
roi_mask_files: {adhd: roi_mask_adhd.csv, abide: roi_mask_abide.csv, abide2: roi_mask_abide2.csv, mdd: roi_mask_mdd.csv, fcp: roi_mask_FCP.csv}
qc: {subject_invalid_edge_ratio: 0.05, roi_incident_invalid_ratio: 0.30}
storage: {unit_pattern: outputs/cells/{dataset}/{atlas}, copy_fc: false, allow_pickle: false}
```

- [ ] **Step 4: 运行测试确认配置测试通过**

预期：配置结构、20 单元数量和阈值测试通过。

## Task 2: 实现单元读取、shape 和身份校验

**Files:**
- Create: `src/fchn_stage_a.py`
- Modify: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试**

测试以下真实事实：`X.ndim == 2`、`X.shape[1] == R*(R-1)/2`、FC/TS subject IDs 相等、FC/TS `roi_indices` 相等、FC `roi_indices` 与 mask `kept=1` 相等。

- [ ] **Step 2: 运行测试确认失败**

```powershell
& $py -m pytest "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\tests\test_stage_a.py" -q
```

- [ ] **Step 3: 写最小实现**

实现 `load_cell_inputs(data_root, dataset, atlas)`，只读取当前 dataset/atlas 的 manifest、FC、TS、ROI mask；使用 `np.load(..., allow_pickle=False)`；拒绝 object array；返回当前单元的 `X`、subject IDs、ROI indices、mask rows 和源文件 hash。

- [ ] **Step 4: 运行真实 20 单元契约测试**

预期：20 个单元全部满足 `X.ndim == 2`、edge 数公式和 FC/TS/mask identity 对齐；任何失败都阻止继续。

## Task 3: 实现理论 ROI universe 和缺失 ROI 身份保留

**Files:**
- Create: `config/atlas_metadata/master_<atlas>.csv`
- Create: `src/fchn_stage_a.py`
- Modify: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试**

```python
def test_missing_roi_keeps_original_identity():
    rows = build_cell_roi_manifest("abide", "AAL116", synthetic_mask_without=[101, 102])
    row = rows.loc[rows["roi_original_index"] == 102].iloc[0]
    assert row["global_original_column"] == 102
    assert row["structural_status"] == "structural_unavailable"
    assert pd.isna(row["matrix_position"])
```

- [ ] **Step 2: 运行测试确认失败**

预期：理论 manifest 生成函数尚不存在而失败。

- [ ] **Step 3: 写最小实现**

实现 `build_cell_roi_manifest(cell_inputs, atlas_metadata, config)`。理论编号固定为 atlas-local 1-based；`global_original_column = roi_local_0based + global_column_start_1based`；每个单元复制完整理论 ROI universe，并用 ROI mask/FC `roi_indices` 写 `structural_status`、`matrix_position`、`reason_code`。不删除理论缺失行。

- [ ] **Step 4: 验证 20 单元缺失编号**

预期：缺失编号与已核查清单一致；例如 `abide/AAL116` 为 101、102、107、108，`abide2/HO112` 为 28。

## Task 4: 实现完整 edge universe 和单元列映射

**Files:**
- Create: `config/atlas_metadata/master_edges_<atlas>.csv`
- Modify: `src/fchn_stage_a.py`
- Modify: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试**

测试理论 edge 数 `R*(R-1)/2`、端点原始编号稳定、缺失 ROI 相关 edge 为 `structural_unavailable` 且 `matrix_position` 为空、保留 edge 的矩阵位置连续且与 FC 列一一对应。

- [ ] **Step 2: 运行测试确认失败**

预期：edge manifest 构建函数尚不存在而失败。

- [ ] **Step 3: 写最小实现**

实现 `build_cell_edge_manifest(cell_inputs, cell_roi_manifest, config)`。对理论 ROI 两两组合生成 `edge_uid`；按当前 FC `roi_indices` 生成保留 edge 顺序；用 `(roi_uid_i, roi_uid_j)` 映射到完整 edge universe；禁止按删除后列号重新解释端点。

- [ ] **Step 4: 运行 20 单元 edge round-trip**

预期：所有当前 FC 列均能唯一回连两个 ROI 原始编号；结构性 edge 身份仍保留。

## Task 5: 实现 subject-self QC 和 nonfinite mask

**Files:**
- Modify: `src/fchn_stage_a.py`
- Modify: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试**

覆盖 `invalid_edge_ratio >= 0.05`、`max_roi_incident_invalid_ratio >= 0.30`、结构性 edge 不入分母、多原因 reason code 稳定排序、原本有限值不改变。

- [ ] **Step 2: 运行测试确认失败**

预期：QC 函数尚不存在或边界断言失败。

- [ ] **Step 3: 写最小实现**

实现 `compute_cell_qc(cell_inputs, cell_edge_manifest, config)`。对当前单元 `X` 生成 nonfinite bool mask；仅在结构性可用 edge 上计算比例；输出 `qc_status`、完整 reason code、计数和 hash；不做填补、不删除矩阵列。

- [ ] **Step 4: 运行 QC 合成和真实测试**

预期：边界测试和 20 单元真实 QC 计算通过。

## Task 6: 实现单元输出、源引用和原子发布

**Files:**
- Create: `scripts/01_prepare_final_inputs.py`
- Modify: `src/fchn_stage_a.py`
- Modify: `tests/test_stage_a.py`

- [ ] **Step 1: 写失败测试**

测试 `outputs/cells/<dataset>/<atlas>/` 独立存在；每单元有 subjects、ROI/edge manifest、`fc_source.json`、TS inventory、mask、QC、cell manifest 和 `_SUCCESS`；第二次运行拒绝覆盖。

- [ ] **Step 2: 运行测试确认失败**

预期：发布入口尚不存在而失败。

- [ ] **Step 3: 写最小实现**

每个单元先写随机 staging 目录；完成 CSV/JSON/NPZ round-trip、artifact bytes/SHA-256、源文件 hash、cell manifest 后 rename 为最终单元目录。`copy_fc=false` 时不复制源 FC 大矩阵；只写 `fc_source.json`。任何单元失败都不写 stage `_SUCCESS`。

- [ ] **Step 4: 运行一次完整 20 单元发布**

```powershell
& $py "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\scripts\01_prepare_final_inputs.py" `
  --config "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\config\stage_a.yaml" `
  --data-root "C:\XY\FedTopo-Brain\SSL\data"
```

预期：20/20 cell manifests 和 `_SUCCESS` 生成；原始输入 hash/mtime 不变。

## Task 7: 生成阶段 A 实施说明和最终审计

**Files:**
- Create: `doc/PHASE_A_IMPLEMENTATION_20260825.md`
- Modify: `outputs/stage_a/stage_a_summary.md`
- Modify: `outputs/stage_a/stage_a_manifest.json`

- [ ] **Step 1: 写失败审计测试**

测试说明文档中包含主线任务、20 单元输入/输出、shape、理论/实际 ROI、缺失编号、方法、命令、路径、测试结果、hash、限制、失败恢复和阶段 B/C 衔接。

- [ ] **Step 2: 运行审计确认失败**

预期：实施说明尚不存在而失败。

- [ ] **Step 3: 生成实施说明**

从实际 cell manifests、input inventory 和测试输出生成，不手填计数；明确写出 FC 是 `N x E` edge 向量而非方阵。

- [ ] **Step 4: 完成最终验证**

```powershell
& $py -m pytest "C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825\tests\test_stage_a.py" -q
```

验收条件：20 个独立单元可单独读取；理论 ROI/缺失 ROI/edge 端点可回溯；所有 hash 和 `_SUCCESS` 通过；无跨单元大 FC 文件；说明文档可指导阶段 B。
