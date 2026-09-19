# 输出文件说明

本目录包含历史仿真输出与修订后的图表结果。**两组指标不能混用。**

| 文件 | 用途与状态 |
| --- | --- |
| `node_load_simulation.csv` | 10 分钟节点负载轨迹，供修订图 1–3 使用。 |
| `battery_simulation.csv` | 上述负载的电池轨迹，供修订图 5–7 使用。 |
| `figures/fig1_*.png` 至 `figures/fig17_*.png` | 已审核并重绘的 17 张图；逐图说明见 [`figures/README.md`](figures/README.md)，修订依据见 [`../docs/FIGURE_REVIEW.md`](../docs/FIGURE_REVIEW.md)。 |
| `reviewed_predictor_metrics.csv` | 修订后的预测器结果；30 秒窗口预热后计算 MAE。 |
| `reviewed_scheduling_summary.csv` | 统一 40 小时观察窗口的调度比较；四组均未截止。 |
| `predictor_metrics.csv` | **历史输出，结论失效**；旧预测脚本可能覆盖。 |
| `scheduling_summary.csv` | **历史输出，结论失效**；旧调度脚本可能覆盖。 |
| `adaptive_simulation.csv` | **历史轨迹，使用了不一致的电流缩放**；不应与修订图表合并分析。 |

从项目根目录运行 `python rebuild_reviewed_figures.py` 会重建全部 PNG 和两个 `reviewed_*.csv`。运行旧脚本 `run_simulation.py`、`run_predictor_eval.py` 或 `run_adaptive.py` 可能覆盖同名图；之后需再次运行重绘脚本。
