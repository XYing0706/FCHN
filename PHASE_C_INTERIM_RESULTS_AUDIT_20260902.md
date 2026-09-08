# 阶段 C 服务器中间结果审计（2026-09-02）

## 1. 审计范围与状态

输入目录：`outputs/stage_c/folds/`。

本次固定快照包含 86 个 `predictions.csv`、86 个 `fold_manifest.json` 和 27,208 行预测。全部 manifest 的 Stage C source hash 为服务器 v2 补丁 `9ba10bacd018a1a05a4ad7b3242a6e47318a944fb54429d922a3e198be75f5a3`，runner hash 为 `7068bcf515265c534179149240007e58156916aed6b38e4d6849dfbdc9a11765`，server-rendered config hash 为 `fb4da941c13ab50b7558ac4231c94ab6638c4b7c89351edb18e175be0ee2ca06`。

这是 Stage C 未完成时的中间快照，不是阶段 D 正式评估。当前 group 完成数：

| Atlas | Dataset | Protocol | 已有 outer folds |
|---|---|---:|---:|
| AAL116 | abide | LOSO | 1 |
| HO112 | abide | LOSO | 20 |
| HO112 | abide | pooled10_site_label | 10 |
| HO112 | abide2 | LOSO | 16 |
| HO112 | abide2 | pooled10_site_label | 10 |
| HO112 | adhd | LOSO | 7 |
| HO112 | adhd | pooled10_site_label | 10 |
| HO112 | mdd | LOSO | 12 |

## 2. C 参数分布

| 参数 | 当前 86 折分布 |
|---|---|
| FC Base C | `0.003: 86` |
| HOFC Base C | `0.003: 86` |
| Normative Base C | `0.003: 59; 0.01: 10; 0.03: 2; 0.1: 14; 0.3: 1` |
| Meta C | `0.03: 50; 0.1: 31; 0.3: 2; 1: 2; 3: 1` |

`predictions.csv.selected_c` 只表示当前 Base view 的 C；`full_fchn` 行该列为空。三个 Base C 同时保存在 `selected_c_fc/selected_c_hofc/selected_c_normative`，Meta C 单独保存在 `meta_c`。

Base grid 为 `[0.003,0.01,0.03,0.1,0.3,1,3]`，Meta grid 为 `[0.03,0.1,0.3,1,3]`。C 是 Logistic L2 正则强度的倒数；C 越小，正则越强。FC 为 6,216 维、HOFC 为 128 维、Normative 为 10 维、Meta 为 13 维，高维 Base view 更容易偏向较强正则。

## 3. 是否为 fallback 或选择器错误

对两个已完成 outer fold 进行只读 OOF 重算。所有候选 C 均产生有限 loss，`fallback=false`；Normative 和 Meta 在现有结果中也能选择非首值。因此选择器没有被硬编码为第一个值。

但扩展 Base C 网格后，两个数据集的 FC/HOFC 最优值均落在 `0.003` 以下：

| Fold | View | 原 `C=0.003` OOF log-loss | 扩展网格最优 C | 最优 OOF log-loss |
|---|---|---:|---:|---:|
| HO112/ADHD/LOSO/outer000 | FC | 0.689989 | 0.0003 | 0.655998 |
| HO112/ADHD/LOSO/outer000 | HOFC | 0.685211 | 0.0003 | 0.651220 |
| HO112/ABIDE/LOSO/outer000 | FC | 0.658547 | 0.001 | 0.632124 |
| HO112/ABIDE/LOSO/outer000 | HOFC | 0.659325 | 0.0003 | 0.634505 |

结论：FC/HOFC 86/86 选择 `0.003` 的直接原因是原网格最小值为 `0.003`，而且 OOF loss 在该边界仍未达到真实最优；这是 Base C 网格下界截断，不是 CSV 展示问题或静默 fallback。Normative 有 59/86、Meta 有 50/86 落在各自下边界，也需要在正式重跑前做向下扩展审计。

当前 manifest 只保存最终 selected C，没有保存 Base/Meta 各候选 C 的 OOF loss；这使边界选择无法从产物直接审计。后续实现应保存每个 view 的候选 C、有效 OOF 样本数、loss 曲线和是否 fallback，并禁止无记录的静默 fallback。

## 4. 当前 Full FCHN 指标

计算口径：只使用 `view=full_fchn`、`task_status=passed`、有限的校准后 `probability`；每个 outer fold 独立计算 AUC、ACC 和 ECE，再对可用 folds 求均值与样本标准差（`ddof=1`）。ECE 暂按 10 个等宽概率箱计算 `sum_b n_b/N × |mean(p_b)-mean(y_b)|`，记作 ECE10。项目尚未在 Stage D 冻结 ECE 分箱合同，因此这里的 ECE 是中间审计值。

| Atlas | Dataset | Protocol | Folds（AUC有效） | AUC mean ± SD | ACC mean ± SD | ECE10 mean ± SD |
|---|---|---|---:|---:|---:|---:|
| AAL116 | abide | LOSO | 1 (1) | 0.687 ± NA | 0.622 ± NA | 0.126 ± NA |
| HO112 | abide | LOSO | 20 (20) | 0.722 ± 0.087 | 0.677 ± 0.076 | 0.153 ± 0.043 |
| HO112 | abide | pooled10_site_label | 10 (10) | 0.726 ± 0.034 | 0.643 ± 0.028 | 0.097 ± 0.032 |
| HO112 | abide2 | LOSO | 16 (15) | 0.658 ± 0.116 | 0.587 ± 0.154 | 0.201 ± 0.131 |
| HO112 | abide2 | pooled10_site_label | 10 (10) | 0.685 ± 0.066 | 0.639 ± 0.048 | 0.105 ± 0.035 |
| HO112 | adhd | LOSO | 7 (6) | 0.459 ± 0.045 | 0.677 ± 0.176 | 0.249 ± 0.104 |
| HO112 | adhd | pooled10_site_label | 10 (10) | 0.649 ± 0.029 | 0.631 ± 0.033 | 0.079 ± 0.035 |
| HO112 | mdd | LOSO | 12 (12) | 0.657 ± 0.109 | 0.636 ± 0.080 | 0.149 ± 0.052 |

单类别 LOSO fold 的 AUC 按合同记 NA，因此 `HO112/abide2/LOSO` 和 `HO112/adhd/LOSO` 的 AUC 有效 fold 数分别为 15/16 和 6/7；ACC/ECE 仍保留。AAL116/ABIDE 只有 1 折，不能计算折间标准差。

作为辅助检查，按当前所有可用 held-out 行直接 pooled 的 Full FCHN 指标为：

| Atlas | Dataset | Protocol | N | pooled AUC | pooled ACC | pooled ECE10 |
|---|---|---|---:|---:|---:|---:|
| AAL116 | abide | LOSO | 37 | 0.687 | 0.622 | 0.126 |
| HO112 | abide | LOSO | 1,077 | 0.711 | 0.666 | 0.032 |
| HO112 | abide | pooled10_site_label | 1,077 | 0.723 | 0.642 | 0.051 |
| HO112 | abide2 | LOSO | 1,022 | 0.617 | 0.592 | 0.041 |
| HO112 | abide2 | pooled10_site_label | 1,022 | 0.680 | 0.637 | 0.020 |
| HO112 | adhd | LOSO | 842 | 0.399 | 0.601 | 0.183 |
| HO112 | adhd | pooled10_site_label | 842 | 0.643 | 0.631 | 0.030 |
| HO112 | mdd | LOSO | 881 | 0.669 | 0.635 | 0.036 |

Pooled 指标不能替代按 site/fold 汇总，特别是 site 与 label 淬杂时。正式结果必须等所有 outer folds 完成后由阶段 D 按已冻结合同计算 site macro、worst-site、bootstrap CI 和 ECE。

## 5. 产物完整性与结论

86 个 fold 中不存在重复 `fold × sample_key × view`；每个测试身份严格有 4 个 view 行。参数记录在 CSV、manifest 和 `model_state.npz` 中一致。

当前结果不能作为最终 Stage C 结果继续积累，原因是 Base C 网格已经被实证为下界截断。若修改 grid，config hash 会变化，现有 86 folds 会全部成为 stale，必须归档后重跑。科学上应先暂停新增计算，冻结经 pilot 验证的新 Base/Normative/Meta C 网格，并把完整 tuning loss 记录加入 fold manifest，再恢复全量。

> 2026-09-08 更正：本文最后一段关于必须暂停并全部重跑的建议过强。两折训练内扩展网格的loss改善只支持敏感性分析，不证明全部现有结果无效或重跑后测试AUC必然改善。最新214折审计见 ../../FCHN_20260825/FCHN_server/analysis_20260908/REPORT.md；后续调整需独立版本并避免根据已查看的测试表现调参。
