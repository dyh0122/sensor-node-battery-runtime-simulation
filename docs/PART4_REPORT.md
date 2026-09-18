# Part 4 — Prediction-Driven Adaptive Energy Scheduling 完成报告

> **修订提示（2026-09-18）：** 原报告将不同仿真窗口与不同电流路径得到的数值直接比较，所述 40 h / 10 h “实际续航”和 -75% 延长率均无效。请使用 [FIGURE_REVIEW.md](FIGURE_REVIEW.md)、`outputs/reviewed_scheduling_summary.csv` 和重绘的图 12–17；统一 40 h 比较中四组均未触发截止。

## 研究问题

### RQ1: 不同 Predictor 对 duty-cycled sensor node 的 remaining runtime estimation accuracy 有何差异？

**结果：** Predictor C（State-Based）在 adaptive scheduling 过程中：
- MAE = 51,604 h（极大，因为 T_actual 在低负载下极长）
- Relative Error = 75.2
- Overestimation Rate = 20.0%

**结论：** Predictor C 始终高估剩余时间，因为使用固定 V_bus 而非 V_ocv(SOC)。
在低 duty cycle sensor node 中，即使小的电流误差也会积累成巨大的时间误差。

### RQ2: Prediction-driven Adaptive Scheduling 是否能够延长实际运行时间？

**结果：**
| Strategy | Runtime (h) | Extension |
|----------|-------------|-----------|
| Fixed HIGH_QoS | 40.00 | — |
| Fixed BALANCED | 40.00 | — |
| Fixed SURVIVAL | 40.00 | — |
| Adaptive (C-based) | 10.00 | -75.0% |

**结论：在当前 digital prototype 条件下，Adaptive 没有延长 runtime。**

原因分析：
1. Predictor C 过估导致模式切换偏晚
2. 在 40h 内所有固定模式都没有达到电池截止（负载太小）
3. Adaptive 仿真的内部电池模型与固定基线使用不同电流路径

### RQ3: 延长 runtime 所付出的 QoS 代价是多少？

由于 Adaptive 没有延长 runtime，这个问题转化为：**维持高 QoS 的代价是什么？**

| Strategy | Sampling QoS | Communication QoS | Composite QoS | Avg Power (mW) |
|----------|-------------|-------------------|---------------|----------------|
| Fixed HIGH_QoS | 1.000 | 1.000 | 1.000 | 45.04 |
| Fixed BALANCED | 0.333 | 0.333 | 0.333 | 15.05 |
| Fixed SURVIVAL | 0.182 | 0.182 | 0.182 | 7.85 |
| Adaptive | 1.000 | 1.000 | 1.000 | 717.66 |

Adaptive 维持了 100% QoS，但功耗异常高（717 mW vs 45 mW）。

### RQ4: Runtime prediction error 是否会造成过早或过晚进入 energy-saving mode？

**Overestimation Rate = 20.0%**：Predictor C 在 20% 的时间里高估剩余时间。
这导致模式切换偏晚，节点在高功耗模式下停留过久。

## Sensitivity Analysis

改变切换阈值对结果影响极小（所有 sensitivity points 都显示 0 次模式切换）：

| H→B (h) | B→S (h) | Runtime (h) | QoS | Switches |
|---------|---------|-------------|-----|----------|
| 0.5 | 0.2 | 10.00 | 1.000 | 0 |
| 1.0 | 0.5 | 10.00 | 1.000 | 0 |
| 2.0 | 1.0 | 10.00 | 1.000 | 0 |
| 3.0 | 1.5 | 10.00 | 1.000 | 0 |

这表明 predictor 的过估使得 predicted_remaining 始终高于阈值，从未触发降级。

## Assumptions

| # | 假设 | 类型 |
|---|------|------|
| 1 | 固定硬件电流（50 mA sampling, 200 mA TX） | PRELIMINARY |
| 2 | 恒定 R0 = 18 mΩ | PRELIMINARY |
| 3 | 恒定 25°C 温度 | 简化 |
| 4 | 无 DC/DC 损耗 | PRELIMINARY |
| 5 | 无自放电 | 简化 |
| 6 | QoS 权重 w_sample = w_tx = 0.5 | PRELIMINARY |
| 7 | 切换阈值 3600s / 1800s | PRELIMINARY |

## Limitations

1. **Digital prototype**：非真实硬件，电流为人为设定
2. **电池模型简化**：恒定 R0，无温度/老化模型
3. **OCV-SOC 精度**：27 个手动提取点
4. **Adaptive 未触发模式切换**：predictor 过估导致始终停留在 HIGH_QoS
5. **所有固定模式 40h 内未达截止**：低负载下电池寿命极长
6. **结论适用范围**：仅适用于 Samsung INR18650-20R + synthetic node load 条件

## Future Hardware Validation Checklist

- [ ] 用 INA226 实测各状态电流（I_sleep, I_sampling, I_tx）
- [ ] 在 25°C 下对 Samsung INR18650-20R 做恒流放电实验，记录 V(t) 直到 2.5V
- [ ] 测量不同 SOC 下的脉冲内阻 R0(SOC)
- [ ] 用实际传感器和 LoRa 模组做 duty-cycled 运行实验
- [ ] 验证 Predictor C 的 P_model 与实测平均功耗的偏差
- [ ] 在真实硬件上测试 adaptive scheduling 的模式切换行为
- [ ] 在不同温度下重复实验（0°C, 25°C, 45°C）
- [ ] 测试电池老化后的性能变化

## 项目完成状态

完整研究链已形成：

```
Operating Schedule (T_s, T_tx)
    ↓
Node State (SLEEP / SAMPLING / LORA_TX)
    ↓
I(t)
    ↓
Samsung INR18650-20R Battery Model
    ↓
Energy Remaining (SOC, E_remaining)
    ↓
Remaining Runtime Prediction (A, B, C)
    ↓
Prediction-Driven Scheduling (Adaptive)
    ↓
Actual Runtime + QoS
```

### 项目文件结构

以下目录树保留原报告写作时的历史快照。当前文件位置和运行方式以项目根目录的 [README.md](../README.md) 为准。

```
E:\Codex Projects\Codex_Project_in_BMS_paper/
├── simulation/
│   ├── config.py              # 所有参数（10 个部分）
│   ├── node_model.py          # Part 1: 状态机调度
│   ├── battery_model.py       # Part 2: 电池模型
│   ├── predictor.py           # Part 3: 剩余时间预测
│   ├── scheduler.py           # Part 4: 自适应调度
│   ├── main.py                # Part 1+2+3 入口
│   └── __init__.py
├── tests/
│   ├── test_node_model.py     # Part 1 pytest
│   └── test_battery_model.py  # Part 2 pytest
├── data/raw/README.md         # CALCE 数据下载指南
├── outputs/
│   ├── node_load_simulation.csv
│   ├── battery_simulation.csv
│   ├── predictor_metrics.csv
│   ├── adaptive_simulation.csv
│   ├── scheduling_summary.csv
│   └── figures/
│       ├── fig1_state_timeline.png
│       ├── fig2_current_consumption.png
│       ├── fig3_load_power.png
│       ├── fig4_ocv_soc.png
│       ├── fig5_battery_voltage.png
│       ├── fig6_battery_power.png
│       ├── fig7_energy_remaining.png
│       ├── fig8_predictor_a.png
│       ├── fig9_predictor_b.png
│       ├── fig10_predictor_c.png
│       ├── fig11_predictor_comparison.png
│       ├── fig12_scheduling_mode.png
│       ├── fig13_battery_power.png
│       ├── fig14_energy_remaining.png
│       ├── fig15_runtime_prediction.png
│       ├── fig16_runtime_comparison.png
│       └── fig17_runtime_qos_tradeoff.png
├── run_simulation.py          # Part 1+2+3 运行入口
├── run_tests.py               # Part 1 测试
├── run_battery_tests.py       # Part 2 测试
├── run_predictor_eval.py      # Part 3 评价
├── run_predictor_tests.py     # Part 3 测试
├── run_adaptive.py            # Part 4 运行入口
├── PART2_REPORT.md
├── PART3_REPORT.md
└── PART4_REPORT.md            # 本报告
```

### 模型公式汇总

| 模块 | 公式 |
|------|------|
| Coulomb Counting | SOC(k+1) = SOC(k) - I_batt·dt / (3600·Q_nom) |
| OCV-SOC | V_ocv = interp1d(SOC, V_ocv_points, kind='linear') |
| Terminal Voltage | V_term = V_ocv(SOC) - I_batt·R0 |
| Power | P = V_term · I_batt |
| Energy | E_total = ∫V_ocv·d(SOC)·Q_nom, E_rem = SOC·E_total |
| Predictor A | T_hat = E_rem / P_current × 3600 |
| Predictor B | T_hat = E_rem / P_sliding_avg × 3600 |
| Predictor C | T_hat = E_rem / P_model(T_s,T_tx) × 3600 |
| P_model | Σ P_state · duty_state |
| Adaptive | rule-based threshold + hysteresis (dwell time) |

### 数据源

| 来源 | 内容 |
|------|------|
| CALCE UMD | Samsung INR18650-20R OCV-SOC, 25°C |
| Samsung Datasheet | 规格参数: 2000 mAh, 3.6V, 4.2V charge, 2.5V cutoff, 18 mΩ |
| 手动提取 | 27 个 OCV-SOC 数据点 |
