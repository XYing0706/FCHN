# 阶段 C 实施计划

1. `completed`：用 `tests/test_stage_c.py` 锁定纯函数、唯一身份、完整状态和 fresh resume，再实现单 fold runner。
2. `completed`：运行 `--pilot` 生成一个真实 outer fold，以 `tests/test_stage_c_pilot_gate.py` 回读 source/input/artifact hash、稳定两轴身份、任务/标签回连、三视图、13 维 Meta、完整数值状态和 FCP cross-fit 自排除审计。
3. `in_progress`：通过 pilot 门禁后运行 `--all`；每 fold 原子写入并支持 exact-fresh resume。2026-08-29 启动时为 1/428 fresh，后台 PID 30876。
4. `pending`：全部 428 outer folds 完成后写阶段 C manifest/_SUCCESS并重跑联合门禁；若任一 fold missing/stale/invalid，保留原因并禁止宣称阶段 C 全绿，阶段 D 不启动。

验证命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest tests/test_stage_c.py -q -p no:cacheprovider
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest tests/test_stage_c_pilot_gate.py -q -p no:cacheprovider
$env:PYTHONDONTWRITEBYTECODE='1'; python scripts/03_run_stage_c.py --pilot
$env:PYTHONDONTWRITEBYTECODE='1'; python scripts/03_run_stage_c.py --all
```
