# FCHN_20260825 文档与项目初始化计划

## 目标

在 `C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825` 建立唯一项目根目录，并完成一份可供新窗口直接接手的中文交接手册。手册覆盖背景、方法、protocol、执行顺序、QC、评估、身份映射和极简存储契约。

## 阶段

| 阶段 | 状态 | 验收 |
|---|---|---|
| 核验旧文档与输入数据路径 | complete | 旧项目只读参考；SSL/data 五个数据集和四套 atlas 已确认 |
| 建立新项目目录 | complete | doc/config/src/scripts/tests/outputs 已创建 |
| 编写交接手册与存储契约 | complete | 手册覆盖背景、方法、protocol、QC、评估、存储和接手顺序 |
| 文档一致性复核 | complete | 第14节已冻结实现规则；第一主线设计进一步落实输入、元数据、QC、输出和发布契约 |
| 第一主线阶段 A 设计 | complete | 用户已确认设计；正式设计写入 `doc/PHASE_A_DESIGN_20260825.md` |
| 第一主线实施计划 | complete | `doc/PHASE_A_IMPLEMENTATION_PLAN_20260825.md` 已写入并完成占位符/一致性自检 |
| 阶段 A 初版打包实现 | complete | 已形成 20 个独立 atlas×dataset 单元和 6 项基础测试；该状态不代表阶段 A 全部门禁通过 |
| 阶段 A 权威元数据、稳定身份与共同空间 | complete | 四套 atlas 的来源快照、master ROI/edge、跨数据集共同空间全部可追溯并通过测试 |
| 阶段 A subjects、QC 与最终重建 | complete | 20 个单元满足完整字段合同、manifest 新鲜度；17 项门禁通过，实施说明通过独立 reader test |
| 阶段 B split plan | complete | ABIDE 前导零身份读取缺口已从源头修复；32/32 组原子重建，5 项 Stage B 门禁及 B/C 联合 23 项回归通过 |
| 阶段 C outer-fold FCHN 闭环 | in_progress | missing-covariate 与 ABIDE 词法身份边界均已修复；真实 `HO112/abide/LOSO/outer000` 通过端到端门禁，旧 17 folds 已归档，按新 A/B/C hash 从 1/428 fresh 边界重跑，未完成前禁止阶段 D |

## 已确认的核心决定

- 项目唯一根目录：`C:\XY\FedTopo-Brain\CHyCR_20260621\FCHN_20260825`。
- 输入根目录：`C:\XY\FedTopo-Brain\SSL\data`。
- 主 protocol：`LOSO` 与 `pooled10_site_label`；移除 `global_pooled10`。
- 主 QC：总体非有限 edge 比例 `>=5%` 或任一 ROI incident edge 无效比例 `>=30%`，排除该 atlas 下被试。
- 不因 FCP 缺失 mean FD 删除被试；FCP 不做头动协变量回归。
- 疾病诊断分支做 mean FD 回归；normative 共同空间必须保持共同协变量定义，默认不把 mean FD 放入共同分支。
- 表格使用 CSV，数组使用非 object `NPZ`；ID、label、ROI label 通过唯一键回连，不重复复制。
- 20 个 Stage 仅是模块、审计和恢复边界，不是实际按 1–20 手工执行的实验步骤；实际执行采用“数据准备一次 + protocol split + outer-fold 闭环 + 全部 outer folds 汇总”。
- 所有 20 个 `atlas × dataset` 最终输入单元必须先全部准备并通过 QC；随后按 `atlas → disease dataset → protocol` 循环执行每个 protocol 的完整方法，FCP 只作为已准备好的 normative 外部参考。
- 新读者测试确认核心研究细节可掌握，但未确认的 ID、small-stratum、inner-fold、FCP cross-fit、edge schema 和缺失 mean FD 资格规则必须先写入 config/schema。
- 2026-08-25 已冻结上述实现建议；下一步先将第14节规则转为 resolved config/schema，再开始正式代码。
- 阶段 A 采用专用简洁实现，不复制旧版含废弃 protocol/XLSX 契约的 Stage 01/02 框架。
- atlas 原始全列 1-based 区间由用户确认：AAL116 1-116、HO112 117-228、CC200 229-428、Dosenbach160 1409-1568。
- atlas 元数据必须从公开权威文件核验 ROI 数量、顺序、版本和许可；无法确认顺序时阻止阶段发布。
- 阶段 A 存储最小单元冻结为单一 `dataset × atlas`；禁止跨 dataset/atlas 合并 FC 大文件。
- 阶段 A 必须按理论 ROI universe 保存缺失 ROI 的原始编号、全局列号、结构性状态和空 matrix position。
- 阶段 A 还必须完成权威 atlas metadata、master ROI/edge、跨数据集共同空间、完整 subjects/QC 合同和 stage manifest 新鲜度审计；现有 `_SUCCESS` 仅表示初版单元打包完成。
- 阶段 B 只负责 LOSO 与 pooled10_site_label split plan；FCP 不进入疾病 split。
- 阶段 B 已完成：4 atlas × 4 disease dataset × 2 protocol 共 32 个独立 group；新增 Base/Meta 严格 nested lineage 后，阶段 B 专项门禁 4 项和全项目测试 31 项均通过。
- 阶段 B 说明文档已写入 `doc/PHASE_B_IMPLEMENTATION_20260826.md`，包含所有输出/脚本/config 的字段、尺寸、hash、命令、恢复和 Stage C 接口。

## 实施准备错误记录

| 错误 | 影响 | 处理 |
|---|---|---|
| 旧目录 `.pytest_cache` 访问拒绝 | 不影响目标脚本/schema 读取 | 避开缓存目录 |
| 首次在线 atlas 检索连接超时 | 未取得或采用任何元数据 | 正式实施改用可验证下载源并保存 hash |
| 设计验证命令的 PowerShell 正则解析失败 | 未修改文件、未产生验证结论 | 改为逐词扫描，重新验证通过 |
| 父项目历史 `results/tmp/pytest-*` 访问拒绝 | 不影响 atlas 和人口学资源核验 | 后续限制搜索到明确资源/源码目录，避开历史临时目录 |
| 首次读取父项目 enrichment 源码少了 `FACHN` 路径层 | 两个只读读取失败，数据统计成功，未修改文件 | 将工作目录改为 `CHyCR_20260621\FACHN` 后重新读取 |
| ABIDE2 phenotype 按 UTF-8 读取失败 | ADHD/ABIDE/ABIDE2 联合统计在 ABIDE2 中断，未写文件 | 按数据集拆分统计；ABIDE2 使用兼容编码读取并记录编码 |
| GitHub API 递归 tree 被浏览器策略拦截 | 未取得或采用任何 atlas 文件 | 改用 GitHub 普通仓库页面/原始链接和工具包端点交叉核验 |
| `git ls-remote` 解析 DPABI master 时连接重置 | 只创建了空来源目录，未下载/采用文件 | 使用父项目已核验的固定 tree SHA `8d4b16e...` 访问 raw 固定链接，先小文件验证 |
| Google 检索 ADHD-200 Gender codebook 超时并重置浏览器 | 未取得或采用性别语义证据 | 改查 ADHD-200 官方数据字典/仓库文件；无权威证据则保留原码并标记语义未确认 |
