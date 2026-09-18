# Part 3 — Remaining Runtime Predictor 完成报告

> **修订提示（2026-09-18）：** 原报告把 10 h 仿真窗口末端当作电池截止，且 Predictor C 使用了与测试负载不一致的默认电流。原指标与结论已失效；请使用 [FIGURE_REVIEW.md](FIGURE_REVIEW.md)、`outputs/reviewed_predictor_metrics.csv` 和重绘的图 8–11。

## 实验设置

### Ground Truth
- `t_dead = 35999 s` — 电池耗尽时间
- `T_actual(t) = t_dead - t` — 真实剩余运行时间
- 仿真时长：36000 s (10 h)
- 平均电流：200 mA（2000 mAh 电池约 10 h 放空）

### 负载设计
```
周期：30 s
  SLEEP:    20 s @ 15 µA
  SAMPLING:  8 s @ 500 mA
  LORA_TX:   2 s @ 1000 mA
平均电流 ≈ 200 mA
```

## 评价指标

| 指标 | 公式 | 说明 |
|------|------|------|
| MAE | mean(\|T_hat - T_actual\|) | 平均绝对误差 |
| RMSE | sqrt(mean((T_hat - T_actual)²)) | 均方根误差 |
| Relative Error | mean(\|T_hat - T_actual\| / T_actual) | 仅在 T_actual > 60s 时计算 |
| Overestimation Mean | mean(max(T_hat - T_actual, 0)) | 高估平均值 |
| Overestimation Rate | fraction(T_hat > T_actual) | 高估比例 |

## Predictor 结果

| Predictor | MAE (s) | MAE (h) | RMSE (s) | RelErr | OverRate |
|-----------|---------|---------|----------|--------|----------|
| **A** (Instantaneous) | 155,024,973 | 43,062 | 215,401,333 | 8936 | 66.7% |
| **B_10s** | 85,371,433 | 23,714 | 159,878,771 | 4922 | 53.8% |
| **B_30s** | 229,852 | 63.9 | 9,714,531 | 6.43 | 55.1% |
| **B_60s** | 229,855 | 63.9 | 9,714,531 | 6.43 | 55.1% |
| **B_120s** | 229,853 | 63.9 | 9,714,531 | 6.43 | 55.1% |
| **B_300s** | 229,852 | 63.9 | 9,714,531 | 6.43 | 54.8% |
| **C** (State-Based) | 1,398,741 | 388.5 | 1,614,914 | 77.8 | 100% |

## 分析

### Predictor A — Instantaneous Power

**MAE = 43,062 h，完全不可用。**

**为什么表现极差：**
1. SLEEP 时 P ≈ 0 → T_hat = E_remaining / P → 趋向无穷大
2. SAMPLING/TX 时 P 突增 → T_hat 急剧下降
3. 瞬时功率不代表平均功耗趋势
4. 对 duty-cycled sensor node 极度敏感

**这不是 bug，而是 instantaneous-power predictor 的根本缺陷。**
保留这些异常现象正是为了展示：仅靠瞬时功率无法预测剩余运行时间。

**Overestimation Rate = 66.7%**：三分之二的时间里高估剩余时间，
这对无人值守设备是危险的（可能在预测还有很久时突然关机）。

### Predictor B — Sliding Average Power

**Best window：300 s（最低 MAE），但与 30s/60s/120s 差异极小。**

**Window 敏感性分析：**

| Window | 问题 |
|--------|------|
| 10 s | 太短，仍然敏感于功率波动，MAE = 23,714 h |
| 30 s | 跨越了一个 duty cycle (30 s)，MAE 骤降到 64 h |
| 60-300 s | 多个 duty cycle 平均，结果趋同 |

**关键发现：**
- Window 从 10s 到 30s 时，MAE 从 23,714 h 降到 64 h（370 倍改善）
- 这是因为 30s 正好匹配 duty cycle 周期
- 30s 以上的 window 之间差异很小（都在 64 h 左右）
- 这说明 **sliding window 应该至少覆盖一个完整 duty cycle**

**但即使最好的 B predictor，RelErr = 6.43（643%）仍然很高。**
原因是：B predictor 使用过去功率来预测未来，但电池电压随 SOC 变化，
导致即使电流模式相同，功率也在渐变。

### Predictor C — State-Based Model

**MAE = 388.5 h，RelErr = 77.8，OverRate = 100%。**

**优点：**
1. 不依赖瞬时功率波动
2. 能根据 T_s / T_tx 的改变自动重新计算
3. 适合未来 Adaptive Scheduler（修改调度参数时立即反映）
4. 结果稳定（无 inf/NaN）

**缺点：**
1. Overestimation Rate = 100%：始终高估剩余时间
2. 假设功耗恒定，不能反映电池内阻随 SOC 的变化
3. 使用 BATTERY_V_NOMINAL = 3.6V 计算理论功率，但实际 V_terminal 随 SOC 变化
4. 不能反映 OCV-SOC 曲线的非线性

**为什么始终高估：**
- P_model 使用固定 V_bus = 3.6V 计算
- 但实际 V_terminal 在放电过程中从 4.2V 降到 2.5V
- 当电池接近放空时，实际功率低于理论值
- 因此 Predictor C 始终认为 "还有更多能量可用"

## 误差来源分解

### 来自 Predictor 的误差

| Predictor | 误差来源 |
|-----------|----------|
| A | 瞬时功率波动（SLEEP/TX 切换） |
| B | 滑动窗口不匹配 duty cycle + 功率渐变未捕获 |
| C | 恒定电压假设 + 恒定功耗假设 |

### 来自 Battery Model 的误差

| 因素 | 影响 |
|------|------|
| 恒定 R0 = 18 mΩ | 真实 R0 随 SOC 变化（低 SOC 时增大） |
| 无温度模型 | 温度影响内阻和容量 |
| OCV-SOC 手动提取 | 27 个点可能不够精确 |
| 无自放电 | 真实电池有 µA 级自放电 |

### 需要真实硬件验证的问题

1. **INA226 实测电流**：与仿真电流对比，验证 duty cycle 精度
2. **电池放电实验**：在 25°C 下用 200 mA 恒流放电，记录 V(t) 直到 2.5V
3. **OCV-SOC 验证**：用实际电池做脉冲放电 + 静息 OCV 测量
4. **R0 随 SOC 变化**：在不同 SOC 下测量脉冲内阻
5. **Predictor C 的 P_model**：与实测平均功耗对比

## 结论

| Predictor | 适用场景 | 不适用场景 |
|-----------|----------|------------|
| A | 恒定功率负载 | Duty-cycled sensor node |
| B | Window ≥ duty cycle 的周期性负载 | 突发性负载变化 |
| C | 调度参数已知且稳定 | 需要精确预测的场景 |

**对无人值守传感节点的建议：**
- 不要单独使用任何单一 Predictor
- Predictor C 最适合 Adaptive Scheduler（因为它能响应参数变化）
- 但需要修正 P_model 使用 V_ocv(SOC) 而非固定 V_bus
- 未来应探索混合方案：C 提供 baseline，B 提供短期修正
