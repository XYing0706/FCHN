# FCHN_20260825 会话进度

## 2026-08-25

- 只读复核旧项目 `FCHN_20260805/doc`，提取背景、方法、strict nested CV、QC、评估和既有结果。
- 核验输入根目录 `C:\XY\FedTopo-Brain\SSL\data` 及五个数据集的 manifest、人口学文件、四套 atlas FC/时序和 ROI mask。
- 在指定新根目录创建 `doc/config/src/scripts/tests/outputs`。
- 已写入 `doc/FCHN_HANDOFF_MANUAL_20260825.md`，覆盖背景、方法、方案、执行流程、QC、评估、存储格式和新窗口接手顺序。
- 已通过关键词核验：输入路径、`LOSO + pooled10_site_label`、移除 `global_pooled10`、5%/30% QC、FCP 头动规则和稳定 ROI/edge identity 均已记录。
- 未在 `DA-DG` 创建本项目新文件；该目录中已有的旧压缩包未修改。
- 根据用户纠正，修订手册第 7 节：删除“20 个实际步骤”的表述，改为真实的五层执行结构，并明确 20 个 Stage 仅用于模块、审计和恢复。
- 进一步明确全局执行边界：先完成 4 个 atlas × 5 个 dataset 的全部最终输入；随后按 `atlas → disease dataset → protocol` 执行完整 protocol，FCP 不作为疾病分类 protocol 单元。
- 只读核验原始脚本 `25_run_fchn_latefusion.py`、`fchn_core.py`、`health_anchor.py`、`01_build_features.py` 和 `fchn_latefusion.toml`，并将 FC/HOFC/normative/late-fusion 的函数级细节及旧脚本与 strict 最终方案的差异写入手册阶段 B/C。
- 使用无上下文新读者完成交接手册测试：核心研究细节均可准确复述，但发现 10 类实现前门禁（ID、small stratum、inner folds、FCP cross-fit、edge schema、KMeans 降 K、缺失 mean FD view eligibility 等），已写入手册第 13 节；因此当前文档可作为主要入口，但尚未达到无需确认即可正式编码的程度。
- 测试结论补充：`FCHN_20260825` 当前只有文档/目录/方案，尚无完整正式实现；旧 `CHyCR_20260621/scripts` 与 `src/chycr` 明确标记为参考，不可直接作为新项目入口。
- 根据用户确认，冻结最终实现建议：直接使用原始 subject_id（dataset_id 为命名空间）、Inner 5 折及 2 折 fallback、FCP 5-fold health-only cross-fit、全无效 edge task invalid、10 个 normative summaries 和 prototype ID 不进模型；已写入手册第14节。
- 用户确认第一主线为阶段 A：一次性准备 4 atlas × 5 dataset 的 20 个最终输入单元。
- 已核验真实 manifest 行数和 FC NPZ 结构；多个 atlas/dataset 存在结构性缺失 ROI，设计明确按 `roi_indices` 和 ROI mask 保留原始身份。
- 用户提供四套 atlas 的原始全列区间，并批准公开权威元数据检索、版本/顺序/许可/hash 门禁。
- 已完成并写入 `doc/PHASE_A_DESIGN_20260825.md`；项目目录不是 Git 仓库，设计版本改由文件 hash 和 manifest 管理。
- 设计文档自检通过：324 行、无占位符、关键输入/QC/身份/发布/衔接条款齐全；SHA-256=`16CE8994A84D8DBE7D64F7A6834A3A0E2CB6EC05F4D2B4C7B83004BD746B5814`。
- 根据用户反馈，阶段 A 存储设计改为单元隔离：`outputs/cells/<dataset>/<atlas>/`，不生成跨 dataset/atlas 大 FC 文件；单元内独立 subjects、ROI/edge manifest、source reference、mask、QC 和 cell manifest。
- 已核查 20 个 FC/TS 单元：均为 `N x R(R-1)/2` edge 向量；FC/TS identity 和 FC/ROI mask 保留顺序全部一致；已记录每单元理论/实际 ROI 与缺失编号。
- 已将结构性缺失 ROI 的完整身份保留规则写入设计：缺失 ROI/edge 不删除身份，只将状态标为 `structural_unavailable` 并设置 `matrix_position=null`。
- 已写入 `doc/PHASE_A_IMPLEMENTATION_PLAN_20260825.md`，计划采用单元独立输出、源 FC 引用、测试先行和 20 单元原子发布。
- 已实现 `config/stage_a.yaml`、`config/stage_a.schema.json`、`src/fchn_stage_a.py`、`scripts/01_prepare_final_inputs.py` 和 `tests/test_stage_a.py`。
- 已按 TDD 完成配置、真实 20 单元 shape/identity、缺失 ROI、理论 edge universe、结构性 edge 和逐被试 QC 阈值测试；最终 `pytest` 结果为 6 passed。
- 已发布 `outputs/cells/<dataset>/<atlas>/` 的 20 个独立单元及 `outputs/stage_a/stage_a_manifest.json`、`stage_a_summary.md`；20/20 `_SUCCESS`，FC 大矩阵复制数为 0。
- 已生成 `doc/PHASE_A_IMPLEMENTATION_20260825.md`，说明主线任务、输入输出、数据形式、方法、脚本命令、存放位置、QC、失败恢复、限制和阶段 B 衔接。
- 纠正阶段映射：公开 atlas metadata 核验、稳定 ROI/edge 共同空间、名称/description 回连、完整 subjects/QC 均属于阶段 A；现有 20 个 `_SUCCESS` 仅代表初版打包流程完成，不能作为阶段 A 整体通过标记。
- 阶段 A 全部门禁通过后，阶段 B 才生成 LOSO 与 pooled10_site_label 的 split plan；FCP 不进入疾病 split。

## 2026-08-26

- 恢复并复核 `task_plan.md`、`findings.md`、`progress.md`；确认项目不是 Git 仓库，继续使用 source/config/artifact SHA-256 和 manifest 作为版本与恢复边界。
- 将阶段 A 状态从错误的整体完成改为：初版打包完成，权威 metadata/稳定身份/共同空间进行中，subjects/QC/最终重建待完成。
- 逐项对照交接手册、阶段 A 设计、实施计划、当前配置、源码、测试和样例产物；确认现有实现仍缺 atlas master/common space、完整 subjects/QC 和 stage manifest 新鲜度审计。
- 确认 `doc/PHASE_A_IMPLEMENTATION_20260825.md` 中 metadata/common space→阶段 B、split→阶段 C 的映射与交接手册第 7 节冲突；待真实产物重建和验证后按正确五阶段整体重写。
- 新增 `tests/test_stage_a_gates.py`，锁定 atlas master/edge、来源快照 hash、共同空间、subjects provenance、逐被试 QC 和 stage manifest 新鲜度六类门禁。
- RED 验证命令：`python -m pytest tests/test_stage_a_gates.py -q -p no:cacheprovider`；结果 `6 failed`，均因目标文件/字段/状态缺失而按预期失败。
- 保存 DPABI 固定 tree SHA `8d4b16e...` 的 AAL/CC200/Dosenbach 原始文件与 LGPL-2.1 LICENSE/README，并复制父项目已核验的 HO112 来源快照；已逐文件计算 SHA-256。
- 只读解析 MAT/NIfTI：四套 atlas 理论 label 数分别为 116/112/200/160，来源字段和顺序足以生成不猜测的 master metadata。
- 新增 `src/fchn_stage_a_metadata.py` 与 `scripts/00_prepare_atlas_metadata.py`，从固定快照生成四套 master ROI/edge 和来源 manifest；未读取或复制 FC。
- 运行 metadata 脚本后，针对 master 数量/列/稳定 ID 和来源文件 hash 的两项测试结果为 `2 passed`。
- 完成 QC incident 分母修复：分母改为结构性可用 incident edge 数；逐被试输出 invalid edge 数、最大 ROI 比例和稳定 ROI UID；QC 状态统一为 `pass/fail`，reason code 使用冻结值。
- 完成人口学精确回连和 provenance；ADHD 的 `Gender=[]` 经聚合核验为唯一缺失表示；MDD 当前 XLSX 的匹配/未匹配/全表 Age/Sex 缺失均为 0，纠正了历史审计的错误缺失结论。
- 20 个最终 cell 已经 staging 构建并可恢复发布；旧初版和第一次候选分别归档在 `outputs/archive/stage_a_20260826T070129Z_c2ef880f` 与 `stage_a_20260826T071101Z_35fdab86`。
- 生成四套 master ROI/edge、共同空间、完整 subjects/QC、input inventory、atlas source inventory，以及含 20 个 current cell manifest hash 和 8 个实施文件 hash 的 stage manifest。
- 阶段 A 全量新鲜门禁结果：`17 passed in 70.28s`。
- 整体重写 `doc/PHASE_A_IMPLEMENTATION_20260825.md`，纠正阶段映射并解释全部 config/src/scripts/tests/output、尺寸、字段、命令、hash、恢复、限制和 A→B 接口；独立 reader test 复核通过。
- 阶段 A 已完成，开始阶段 B split plan；固定 seed 采用父项目正式 `fchn_latefusion.toml` 中已有值 `20260625`，并将在阶段 B resolved config 中显式冻结。

## 待完成

- 阶段 B split plan 已生成并通过全部门禁：32/32 group，428 outer task，2140 inner task，2568 task ready，fallback/invalid 均为 0。
- 全项目验证：`python -m pytest tests -q -p no:cacheprovider` → `29 passed in 197.45s`。
- 生成阶段 B 实施说明，逐项解释配置、src、脚本、测试、结果、命令、格式、尺寸、字段、恢复和阶段 C 依赖。
- 阶段 B 实施说明已完成：`doc/PHASE_B_IMPLEMENTATION_20260826.md`；静态检查 411 行、无 `TODO/TBD`、无阶段映射错误；stage manifest 新鲜度复核通过。
- 用户要求复审阶段 A/B 后进入阶段 C；A/B 新鲜复审已通过，开始阶段 C 设计与旧实现差异审计。
- 方法级复审发现阶段 B 缺少 Base OOF/C-tuning/strict Meta OOF 的独立 parent-task lineage；停止直接进入 C，先按 TDD 补齐阶段 B 嵌套 split 合同并重建门禁。

## 2026-08-26 阶段 B 修订与阶段 C 启动

- 阶段 B 新增 `nested_tasks.csv`：outer、base_oof、base_c_tuning、meta_oof、meta_base_oof、meta_base_c_tuning 六层任务及直接父任务、partition 上下文和 split hash。
- 阶段 B 旧产物已可恢复归档于 `outputs/archive/stage_b_20260826T091619Z_985e445a`；新版 32/32 原子发布。
- 阶段 B 专项门禁 `4 passed`；全套阶段 A/B 测试 `31 passed in 392.28s`。
- 官方 ADHD-200 PhenotypicKey PDF 已保存至 `config/demographic_metadata/ADHD-200_PhenotypicKey.pdf`，SHA-256=`fdf5f577b376027e5191182eb69d58864005c9a116553da4128139f0b48206e9`；确认 `Gender 0 Female, 1 Male`，阶段 C 统一映射为 male=0/female=1。
- 阶段 C 已新增 config、schema 规划、设计/实施计划、纯函数模块和 5 项测试；纯函数测试 `5 passed`。
- 真实 pilot 暴露并正在处理两个边界：Windows/MKL KMeans 输入隔离，以及 tuning OOF 为空时必须明确 invalid/跳过，不得静默填补；当前尚未产生有效 fold 结果，不能宣称阶段 C 完成。
- 最终 A/B/C 回归命令共 `37 passed in 215.54s`；A/B 产物门禁保持通过，C 纯函数/编码门禁 6 项通过。阶段 C 仍无 `_SUCCESS`，因为真实 pilot 未完成，严格 FCP health-only cross-fit 审计仍待补齐。

## 2026-08-26 阶段 C 继续实现

- 修正 normative→Meta 数据流：Meta 现在强制使用 3 个 base logits + 10 个 normative summaries，固定输入维度为 13；逐 edge `edge_z` 不再进入分类器。
- `normative_scores.npz` 输出合同更新为 `summary[test,10]`、`edge_z[test,common_E]`、`nearest_prototype[test]`。
- 新增确定性的 site-aware FCP 5-fold cross-fit 折分配和逐被试 `fcp_crossfit_audit.csv` 设计；审计记录拟合/留出身份 hash、计数、自排除状态和分数有限性。
- 阶段 C 测试新增 Meta 13 维和 FCP 自排除合同；阶段 C 单元测试 `8 passed`，全项目回归 `39 passed in 428.01s`。
- 两次真实 pilot 均安全停止于 nested normative C-tuning，未产生有效 fold；当前不存在 `outputs/stage_c/_SUCCESS`。原因是冻结的 125 个 normative meta-base tuning task 需要逐任务 KMeans/模型拟合，计算量大，不是门禁失败或数据错误。
- 下一步先完成真实数据上的单 fold 可复核执行，再决定是否对 runner 做保持统计定义不变的缓存/并行优化；阶段 D/E 仍不得启动。

## 2026-08-26 阶段 A/B/C 门禁复核

- A manifest：`status=passed`、20 cells；A 专项门禁当前 `8 passed`。
- B manifest：`status=passed`、32 groups；总计 428 outer、2,140 inner、79,608 nested，fallback/invalid 均为 0；B 专项门禁 `4 passed`。
- C：`outputs/stage_c/_SUCCESS` 和 `stage_c_manifest.json` 均不存在，fold ready 数为 0；因此阶段 C 尚未通过，阶段 D 汇总不得启动。
- C 代码测试 `8 passed`；A/B/C 全项目回归 `39 passed in 428.01s`。测试通过仅证明代码合同和已有 A/B 产物，不替代真实 Stage C fold 验收。

## 2026-08-27 阶段 A/B/C 再核查

- 新鲜核查结果：A 专项门禁 `8 passed`，B 专项门禁 `4 passed`，C 单元测试 `8 passed`。
- A/B manifest 和 `_SUCCESS` 均保持新鲜、状态为 `passed`；A=20 cells，B=32 groups/428 outer/2,140 inner/79,608 nested，fallback/invalid=0。
- 阶段 C 真实 pilot 再次沿 FC→HOFC→normative 顺序启动；FC 与 HOFC 选参完成，normative nested C-tuning 仍未在可接受窗口内完成，已安全停止，staging 自动清理。
- 当前 `outputs/stage_c` 不存在有效 fold、`stage_c_manifest.json` 不存在、`_SUCCESS` 不存在；阶段 D 继续禁止启动。

## 2026-08-29 阶段 C 有界并行优化

- 真实成员 hash 核验否定了缓存复用方案：25/125/25 个相关 nested task 的训练边界均唯一。
- 4 个真实 normative task 基准：顺序 31.276 秒、2 线程 21.757 秒、4 线程 18.905 秒；选择更节制的 `tuning_workers=2`。
- 按 TDD 新增并行顺序和配置冻结测试：RED 为 2 failed/8 passed；最小实现后阶段 C 测试 `10 passed`。
- 两个真实 normative task 的 workers=1 与 workers=2 比较：标签顺序和 7 个 C 候选概率在 `atol=1e-10` 下全部一致。
- 有界并行 pilot 运行至 strict Meta OOF 后失败：`ValueError: inconsistent numbers of samples [474,475]`。根因是 FC/HOFC 按 mean FD 资格排除 1 名样本，但 Meta 标签仍从未过滤的 `meta_train` 全表取得；staging 已自动清理，未发布错误 fold。
- 修复共同 sample_key/label 对齐后，获批写权限的真实 pilot 成功生成 1 个 `stage_c_fold_ready`。基础 round-trip：predictions=980 行（4 views×245）、summary=(245,10)、edge_z=(245,6105)、FCP audit=858 行且 self_excluded/score_finite 全 True、artifact hash 全匹配。
- 深入方法复核发现当前最终 Meta 训练错误地纵向拼接 5 个 meta-train 的 OOF 特征，同一 outer-train 被试可能重复进入最终 Meta；冻结方案要求使用顶层 `base_oof` 对完整 outer-train 生成一次性 OOF 特征。当前 pilot 因此只作为接口/边界证据，不作为阶段 C 方法门禁通过。

## 2026-08-29 阶段 C 方法与产物合同收口

- 最终 Meta 已改为使用顶层 `base_oof` 为每名有效 outer-train 被试生成恰好一条 FC/HOFC/normative OOF 记录；Meta folds 仅用于 Meta C 选择和 Platt strict OOF，重复 `sample_key` 会直接报错。
- `model_state.npz` 现保存三视图 imputer、Ridge、scaler/PCA、分类器、normative common scaler/anchor、Meta、Platt 和 `n_roi` 等全部必要数值状态；全部数组为非 object。
- `predictions.csv` 现含 task/outer_fold/split_path/variant、hard prediction、logit、raw/calibrated probability、三视图独立 selected C、Meta C、train/validation/test identity hash、ROI/edge hash、状态 hash 和 task status/reason。
- `normative_scores.npz` 现内嵌固定宽度 Unicode `sample_key[test]` 和 `edge_uid[common_E]`，并保存 `summary[test,10]`、`edge_z[test,common_E]`、`nearest_prototype[test]`；已在 `allow_pickle=false` 下回读。
- fold manifest 现保存 config/runner/src/A/B manifest 的 `run_hashes`、group/cell/ROI/edge/common-edge 输入 hash、全部 artifact hash 和数值状态键；resume 仅跳过 exact fresh fold，stale fold 必须先归档。
- 最终真实 pilot `HO112/adhd/LOSO/outer000` 通过：980 条预测、245 个 test identity、6105 common edges、858 条 FCP cross-fit audit、42+ 数值状态键；完整回读门禁与阶段 C 单测合计 `17 passed`。
- A/B/C 联合门禁使用项目内 basetemp 和 JUnit 报告重跑，最终 `48 passed in 216.81s`；报告位于 `outputs/stage_c/abc_verification_report.xml`。首次提权重跑的唯一 error 是系统 pytest 临时目录 ACL，与项目逻辑无关，已通过项目内 basetemp 消除。
- 旧 pilot 均可恢复归档于 `outputs/archive/stage_c_pilot_*_20260829`，分别保留 Meta 身份修复前、score 轴身份补齐前、Unicode dtype 修复前和最终字段合同前的证据。
- 2026-08-29 已以隐藏后台进程启动 `scripts/03_run_stage_c.py --all`：PID 30876；stdout/stderr 为 `outputs/stage_c/stage_c_full_stdout.log` 和 `stage_c_full_stderr.log`。启动时 fresh=1/428；只有达到 428/428 且 stage manifest/_SUCCESS fresh 后才可进入阶段 D。

## 2026-08-29 阶段 C missing-covariate 边界修复与重启

- 首次全量 PID 30876 完成 outer000–002 后，在 outer003 的最终 outer-test Meta Logistic 处因 `Input X contains NaN` 停止；无 staging 残留，stage manifest/_SUCCESS 均未生成。
- 聚合诊断比较 outer000–003：前三个 fold 的 discriminative/normative test ineligible 均为 0；outer003 的 257 个 test 中恰有 1 个 canonical sex 缺失，导致三个 Base view 都不合格。mean FD、age 和 scan length 不是本次根因。
- 冻结配置是 `missing_covariate_policy=exclude_with_reason`。正确处理为保留身份，不填补 sex、不删除整 fold；只把三视图均有限的 test 行送入最终 Meta，非有限行在四个 view 中标记 `task_status=ineligible`、`reason_code=MISSING_REQUIRED_COVARIATE`，预测数值留空。
- TDD：新增有限行保持顺序的回归测试，首次按预期失败（缺 `_predict_finite_rows`）；最小实现后该测试通过，阶段 C 单元测试 `17 passed`。
- 真实 outer003 使用修复后的 runner 重跑并通过。回读结果：1028 行=`257×4`；1024 行 passed、4 行 ineligible，4 行对应同一身份的四个 view；256 个 normative summary 有限、1 个明确不合格；label、artifact hash和run hash均通过。
- 新增 outer003 实体回归门禁并单独运行 `1 passed`；不打印被试身份，只验证计数、状态、reason、有限性、shape 和 hash。
- runner hash 变化后，旧 outer000–002 被核验为 stale，outer003 为 fresh。三个 stale fold 与旧失败日志已移动到 `outputs/archive/stage_c_pre_missing_covariate_fix_20260829/`，未删除。
- 修复后全量 `--all` 已从 1/428 fresh 起点重新启动：PID 16736；新日志仍为 `outputs/stage_c/stage_c_full_stdout.log` 与 `stage_c_full_stderr.log`。runner 将重算 outer000–002、跳过 fresh outer003并继续后续 folds。
- 修复后新鲜联合验证：`tests/test_stage_c.py` 17 项 + outer003 实体门禁 1 项，共 `18 passed in 9.04s`。17:28 状态检查：PID 16736 正在 outer000 HOFC，ready=1/428，stderr=0。
- 18:05 心跳核验：修复后的 `HO112/adhd/LOSO/outer000` 已重新完成并发布，fresh folds 增至 2/428；PID 16736 正在 `outer001` normative 选参，staging=0、stderr=0，stage manifest 与 `_SUCCESS` 仍按未完成状态保持不存在。
- 18:37 心跳核验：`HO112/adhd/LOSO/outer001` 已完成并发布，fresh folds 增至 3/428；PID 16736 已进入 `outer002` normative 选参，staging=0、stderr=0，阶段级发布门禁仍未提前生成。
- 19:09 心跳核验：`HO112/adhd/LOSO/outer002` 已完成并发布，fresh folds 增至 4/428；runner 正确跳过既有 fresh `outer003` 并进入 `outer004`，PID 16736 正常，staging=0、stderr=0。
- 19:56 心跳核验：`HO112/adhd/LOSO/outer004` 已完成并发布，fresh folds 增至 5/428；PID 16736 正在 `outer005` normative 选参，staging=0、stderr=0，stage manifest 与 `_SUCCESS` 仍未提前生成。
- 20:28 心跳核验：`HO112/adhd/LOSO/outer005` 已完成并发布，fresh folds 增至 6/428；PID 16736 正在 `outer006` normative 选参，staging=0、stderr=0，阶段级门禁保持未发布。
- 21:18 低频边界核验：`HO112/adhd/LOSO` 的 7/7 folds 已全部完成，fresh 总数为 7/428；runner 已正常切换至 `HO112/adhd/pooled10_site_label/outer000` normative 选参，PID 16736 正常、stderr=0。后续监控改为每小时，仅关注 protocol/dataset/atlas 首折、每 25-fold 里程碑、异常和最终门禁。
- 22:19 protocol 首折门禁：`HO112/adhd/pooled10_site_label` 的首两个 folds 已完成，说明 LOSO→pooled10 切换及 pooled10 首折路径通过；fresh 总数 9/428，runner 正在 pooled10 `outer002` normative 选参，PID 16736 正常、staging=0、stderr=0。

## 2026-08-30 ABIDE 稳定身份根因修复

- 首次完成 `HO112/adhd` 的 LOSO 7/7 与 pooled10 10/10 后，runner 在切换至 `HO112/abide/LOSO/outer000` 时停止，完整 traceback 为 `split sample_key is absent from FC source`；进程无 staging 残留，阶段级 manifest/_SUCCESS 未生成。
- 三方聚合核验确认：ABIDE Stage A 原始 `subjects.csv` 与 FC `subject_ids` 均为 1,085 个 7 位字符串、逐行完全一致；旧 Stage B membership 的 1,077 个 QC-pass 身份被 pandas 整数推断改写为 5 位，和 FC 精确交集为 0，但去前导零后为无歧义子集。根因位于 Stage B/Stage C CSV 读取边界，不是 FC 缺失或 split 成员错误。
- 禁止在 Stage C 用去零模糊匹配掩盖。按 TDD 新增“membership 是 Stage A 原始 identity 精确词法子集”和“Stage C loader 保留前导零”门禁；RED 分别按预期暴露 ABIDE 词法错位和 `[50002] != ['0050002']`。
- 最小修复：Stage B 读取 `subjects/qc`、Stage C 读取 `subjects/qc/split_membership` 时对 `sample_key/subject_id` 显式使用字符串 dtype；未改变 Stage A、QC、fold 分配、C 网格、KMeans、protocol 或模型方法。
- 旧 17 个 Stage C folds、失败日志和旧 JUnit 报告已移动至 `outputs/archive/stage_c_pre_subject_identity_fix_20260830T0229/`；旧 Stage B 两次发布均由脚本自动归档，未删除。
- Stage B 32/32 组按最终源码重新原子发布；新增身份门禁 2/2 通过，Stage B 全门禁 + Stage C 单元回归最终 `23 passed in 172.41s`。
- 原失败的真实 `HO112/abide/LOSO/outer000` 完整复跑通过：test=37、predictions=148=`37×4`、所有 identity 为 7 位且与 split test 精确相等、`summary=(37,10)`、`edge_z=(37,6105)`、strict Meta train=1,040、4 个 artifact hash 与 run hash 全部新鲜；实体门禁 `1 passed`。
- 修复后的全量 `scripts/03_run_stage_c.py --all` 已以隐藏进程 PID 3644 从 1/428 fresh 边界重新启动；stdout/stderr 仍位于 `outputs/stage_c/`，启动核验 stderr=0。Stage D 继续禁止。
- 08:07 低频边界核验：新身份链下 `HO112/adhd/LOSO` 已完成 7/7，runner 正常切换至 `HO112/adhd/pooled10_site_label/outer000` normative；加上已验证的 ABIDE 首折，fresh 总数 8/428，PID 3644 正常、staging=0、stderr=0。

## 2026-08-31 阶段 C 外部中断核验与恢复

- 08:54 核验发现 PID 3644 已停止，fresh=12/428、staging=0、stderr=0，stage manifest 与 `_SUCCESS` 均未生成；stdout 最后停在 `HO112/adhd/pooled10_site_label/outer004` 的 normative 选参之前。
- 机器自 2026-08-25 持续运行，停止时段的 Windows Application/System 日志无 Critical/Error/Warning，Python 也未留下 traceback，因此没有证据表明阶段 C 算法报错；精确外部终止来源不可从现有日志恢复，不作猜测。
- 12 个已完成 fold 的 config、runner、Stage C source、Stage B source、Stage A manifest、Stage B manifest 六项 SHA-256 与当前文件逐项一致，均为 exact fresh；无需归档或重算 fold。
- 中断前日志已保存于 `outputs/archive/stage_c_external_stop_20260831T085224/`。一次 PATH 中不存在 `python` 的启动尝试立即以 9009 结束，未进入脚本、未改动 fold；随后使用文档已验证的 `C:\Users\CQQ\anaconda3\python.exe` 成功恢复。
- 新后台 PID 3212 已从 12/428 fresh 边界继续执行 `HO112/adhd/pooled10_site_label/outer004`，启动核验 stderr=0。
- HO112 已完成 fold 的观测耗时约 26–35 分钟/折，平均约 1.9 折/小时；按该速率串行完成剩余 416 折约需 220 小时，且更高维 atlas 可能更慢。当前 runner 仅在 C 调参任务内部使用 2 个线程，outer folds 仍串行；CPU 多核服务器只有在按互斥 outer fold 并行调度时才能获得主要加速，GPU 本身不能直接加速当前 scikit-learn 实现。
- 11:50 再次核验发现恢复进程 PID 3212 已在 15/428 fresh 后停止，最后日志为 `HO112/adhd/pooled10_site_label/outer007` normative；staging=0、stderr=0，机器未重启，停止时段 Application/System 无 Critical/Error/Warning，因此仍无代码 traceback 或系统故障证据。服务器已开始阶段 C 实体门禁，暂不盲目重启本机，避免双端重复执行；待服务器三项实体门禁全绿后由服务器并行任务作为唯一主执行。
