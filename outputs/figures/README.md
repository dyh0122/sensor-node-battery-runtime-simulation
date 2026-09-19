# 图表说明（Figures 1–17）

本目录保存项目当前**已审核重绘**的 17 张 PNG。它们是数字仿真结果，不是实测电池曲线。图 1–7、图 8–11、图 12–17 分别使用不同的负载场景；跨组比较数值前，请先看下方的实验设置。图表问题与修订依据见 [图表审查记录](../../docs/FIGURE_REVIEW.md)，项目安装和运行方法见[项目 README](../../README.md)。

## 三组实验如何区分

| 图号 | 场景 | 观察范围 | 主要输入 |
| --- | --- | --- | --- |
| 1–7 | 节点状态和短时电池响应演示 | 原始轨迹 600 s；图 1–3 放大前 120 s | `../node_load_simulation.csv`、`../battery_simulation.csv`；睡眠/采样/发送电流 15 µA / 8 mA / 120 mA。 |
| 8–11 | 剩余运行时间预测器评估 | 同一重负载运行到**仿真**截止，约 10 h | 30 s 周期：睡眠 20 s（15 µA）、采样 8 s（500 mA）、发送 2 s（1 A）；由重绘脚本重新计算。 |
| 12–17 | 固定模式与自适应模式比较 | 同一 40 h 窗口；**均未到截止** | 三种状态电流统一为 15 µA / 50 mA / 200 mA；调度模式改变采样与发送间隔。结果表为 `../reviewed_scheduling_summary.csv`。 |

三组都使用简化电池模型和配置中的 27 个 OCV–SOC 点。仓库中没有可核查的原始电芯测量数据，OCV 表应视为示意性模型输入。

## 逐图索引

| 图 | 文件 | 图中展示的内容与读图要点 |
| --- | --- | --- |
| 1 | [fig1_state_timeline.png](fig1_state_timeline.png) | 前 120 s 的 Sleep、Sampling、LoRa TX 状态序列；纵轴为离散状态，不是连续测量值。 |
| 2 | [fig2_current_consumption.png](fig2_current_consumption.png) | 同一时间段的节点负载电流脉冲，单位 mA。 |
| 3 | [fig3_load_power.png](fig3_load_power.png) | 由固定 3.6 V 总线电压乘负载电流得到的标称功率，单位 mW。 |
| 4 | [fig4_ocv_soc.png](fig4_ocv_soc.png) | 配置 OCV–SOC 点及其线性插值；不能当作仓库内原始 CALCE 数据的拟合结果。 |
| 5 | [fig5_battery_voltage.png](fig5_battery_voltage.png) | 10 分钟开路电压、端电压及 2.5 V 截止线；下半图放大毫伏级脉冲压降。 |
| 6 | [fig6_battery_power.png](fig6_battery_power.png) | 端电压 × 电池电流得到的短时电池功率脉冲，单位 mW。 |
| 7 | [fig7_energy_remaining.png](fig7_energy_remaining.png) | 根据 SOC 推算的标称剩余能量；纵轴放大，数值不是实测可释放能量。 |
| 8 | [fig8_predictor_a.png](fig8_predictor_a.png) | 瞬时功率预测器 A 与仿真剩余时间；纵轴为**对数刻度**，展示睡眠时极大的估计值。 |
| 9 | [fig9_predictor_b.png](fig9_predictor_b.png) | 滑动平均预测器 B 的 30、60、300 s 窗口；图示范围限制在 0–15 h，短窗口睡眠估计可能超出该范围。 |
| 10 | [fig10_predictor_c.png](fig10_predictor_c.png) | 状态模型预测器 C 的预测值对仿真实际剩余时间散点；虚线表示两者相等。C 使用与该重负载一致的状态比例和电流。 |
| 11 | [fig11_predictor_comparison.png](fig11_predictor_comparison.png) | 仿真剩余时间、B 的 30 s 窗口和匹配参数的 C；A 因量级差异单独放在图 8。 |
| 12 | [fig12_scheduling_mode.png](fig12_scheduling_mode.png) | 自适应模式在 40 h 内始终为 High QoS，没有发生模式切换。 |
| 13 | [fig13_battery_power.png](fig13_battery_power.png) | 四种策略的 15 分钟平均电池功率；Adaptive 与固定 High QoS 曲线重合。 |
| 14 | [fig14_energy_remaining.png](fig14_energy_remaining.png) | 四种策略的 SOC 推算标称剩余能量；Adaptive 与固定 High QoS 重合。 |
| 15 | [fig15_runtime_prediction.png](fig15_runtime_prediction.png) | 40 h 内 Predictor C 的**预测**剩余时间及 1 h 降级阈值；没有观测到截止，因此没有可验证的实际剩余时间曲线。 |
| 16 | [fig16_runtime_comparison.png](fig16_runtime_comparison.png) | 四种策略在 40 h 末的 SOC。文件名沿用旧命名，图中**不是实际续航柱状图**；所有实际续航只能表述为大于 40 h。 |
| 17 | [fig17_runtime_qos_tradeoff.png](fig17_runtime_qos_tradeoff.png) | 同一 40 h 内的平均电池功率与综合 QoS。High QoS 和 Adaptive 用一个复合标记表示，因为两者数值完全重合；文件名沿用旧命名，图中**没有测出续航–QoS 折中**。 |

## 关键数值与解释

图 8–11 的重负载在约 **10.00 h** 达到仿真截止。排除滚动窗口最初 30 s 的预热期后，B（30 s）的 MAE 为 **0.320 h**，匹配参数的 C 为 **0.168 h**。完整数值见 [`../reviewed_predictor_metrics.csv`](../reviewed_predictor_metrics.csv)。这些误差只衡量对**同一简化仿真**的拟合，不能直接推广到真实硬件。

图 12–17 的四组策略在 40 h 内均未截止。末端 SOC 依次为 High QoS **75.0%**、Balanced **91.6%**、Survival **95.6%**、Adaptive **75.0%**。Adaptive 在该窗口没有降级，因此其平均功率约 **48.9 mW**、综合 QoS **1.00**，均与固定 High QoS 相同。综合 QoS 是采样事件率与发送事件率相对 High QoS 的比值各取 0.5 权重；完整数值见 [`../reviewed_scheduling_summary.csv`](../reviewed_scheduling_summary.csv)。这些数字**不能**用来计算实际续航延长率。

## 重新生成与引用

在项目根目录运行：

```powershell
python rebuild_reviewed_figures.py
```

脚本会重建本目录 17 张 PNG，以及 `outputs/reviewed_predictor_metrics.csv`、`outputs/reviewed_scheduling_summary.csv`。它需要已有的 `outputs/node_load_simulation.csv` 与 `outputs/battery_simulation.csv`；若两者缺失，先运行 `python run_simulation.py`，再运行上面的重绘命令。旧脚本可能覆盖同名图，**最后一步应始终是重绘命令**。

写论文图注时，请注明“仿真”“负载场景”“时间窗口”“单位”与图中放大或截断的坐标轴。不要将旧的 `../predictor_metrics.csv`、`../scheduling_summary.csv`、`../adaptive_simulation.csv` 与本目录图表合并引用；这些历史输出的已知问题见[审查记录](../../docs/FIGURE_REVIEW.md)。
