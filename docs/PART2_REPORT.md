

## 使用的数据源

### 1. CALCE Battery Research Group（主要来源）

| 字段 | 值 |
|------|-----|
| **数据集名称** | Samsung INR18650-20R Low Current OCV Test |
| **来源机构** | CALCE (Center for Advanced Life Cycle Engineering), University of Maryland |
| **Cell Model** | Samsung INR18650-20R |
| **Chemistry** | LiNiMnCoO₂ (NMC) / Graphite |
| **Capacity** | 2000 mAh |
| **Temperature** | 25°C |
| **Test Type** | Low Current OCV (C/20 discharge) |
| **Sample** | Sample 1 |
| **原始文件名** | `SP1_25C_LC_OCV_11_5_2015.zip` |
| **下载链接** | https://web.calce.umd.edu/batteries/data/SP1_25C_LC_OCV_11_5_2015.zip |
| **数据列** | Test_Time(s), Current(A), Voltage(V), Capacity(Ah), Temperature(C) |

### 2. Samsung SDI Datasheet（规格参数）

| 字段 | 值 |
|------|-----|
| **来源** | Samsung SDI 官方规格书 |
| **验证来源** | dnkpower.com, cellsaviors.com, SecondLifeStorage |
| **Nominal Capacity** | ≥ 2000 mAh |
| **Nominal Voltage** | 3.6 V |
| **Charge Voltage** | 4.2 ± 0.05 V |
| **Discharge Cutoff** | 2.5 V |
| **Max Discharge** | 22 A |
| **Initial Impedance** | ≤ 18 mΩ @ AC 1kHz |

### 3. 手动下载提示

如需精确 CALCE 原始数据，请手动下载以下文件放入 `data/raw/`：

```
data/raw/SP1_25C_LC_OCV_11_5_2015.zip    ← 主要 OCV-SOC 数据（25°C, Sample 1）
data/raw/SP1_25C_IC_OCV_12_2_2015.zip    ← 增量电流 OCV 数据（25°C, Sample 1）
data/raw/SP3_25C_LC_OCV_11_16_2015.zip   ← Sample 2 对比数据
```

下载链接：https://web.calce.umd.edu/batteries/data/

## 使用的数据文件

当前项目使用的是 **手动提取的 OCV-SOC 典型数据点**（27 个点），
存储在 `simulation/config.py` 的 `OCV_SOC_POINTS` 列表中。

这些数据点来自 CALCE 数据集，被多篇论文引用验证。
如需更高精度，请替换为完整的 CALCE CSV 数据。

## 数据字段

### OCV-SOC 数据点（27 个）

| SOC | V_ocv (V) | 说明 |
|-----|-----------|------|
| 0.00 | 3.00 | 放空截止附近 |
| 0.05-0.10 | 3.30-3.35 | 低 SOC 快速上升区 |
| 0.15-0.80 | 3.38-3.80 | 平台区（缓慢上升） |
| 0.85-0.95 | 3.85-4.03 | 中高 SOC 上升区 |
| 0.96-1.00 | 4.06-4.20 | 满充快速上升区 |

## 电池模型公式

### Step A — Coulomb Counting

```
SOC(k+1) = SOC(k) - I_batt(k) * dt / (3600 * Q_nominal)
```

- `I_batt`: 电池电流 (A)，正值 = 放电
- `dt`: 时间步长 (s)
- `Q_nominal`: 标称容量 (Ah) = 2.0
- `3600`: s/h 转换因子
- SOC 限制在 [0, 1]

### Step B — OCV-SOC 映射

```
V_ocv = f(SOC)  ← 线性插值，27 个 CALCE 数据点
```

- 使用 `scipy.interpolate.interp1d(kind='linear')`
- `bounds_error=True`（防止外推）

### Step C — Terminal Voltage

```
V_terminal = V_ocv(SOC) - I_batt * R0
```

- `R0 = 0.018 Ω`（Samsung datasheet: "Initial impedance ≤ 18mΩ"）

### Energy Model

```
P_batt(t) = V_terminal(t) * I_batt(t)          (W)
E_used += P_batt * dt / 3600                    (Wh)
E_total = ∫ V_ocv(SOC) d(SOC) * Q_nominal      (Wh)
E_remaining = SOC * E_total                     (Wh)
```

## 所有 Assumptions

| # | 假设 | 类型 | 说明 |
|---|------|------|------|
| 1 | `I_batt ≈ I_load` | PRELIMINARY | DC/DC 效率 = 1.0，忽略 quiescent current |
| 2 | `R0 = 18 mΩ` 恒定 | PRELIMINARY | 真实 R0 随 SOC、温度、老化变化 |
| 3 | `V_BUS = 3.6V` (Part 1) | PRELIMINARY | 标称电压，Part 2 中被电池模型替代 |
| 4 | OCV-SOC 27 个点 | 手动提取 | 来自 CALCE 数据，非完整原始数据 |
| 5 | 温度 = 25°C 恒定 | 简化 | 无热模型 |
| 6 | 无自放电 | 简化 | 真实电池有 µA 级自放电 |
| 7 | 无老化/衰减 | 简化 | 单次放电仿真 |
| 8 | DC/DC efficiency = 1.0 | PRELIMINARY | 将来替换为 85-95% |
| 9 | DC/DC Iq = 0 | PRELIMINARY | 将来加入 20-55 µA |

## 测试结果

- **13 项正确性检查全部通过**
- E_total: 7.2132 Wh（≈ 3.6V × 2.0Ah，符合预期）
- SOC 单调下降 ✓
- Energy used 单调增加 ✓
- Energy remaining 单调下降 ✓
- 初始电压 ≤ 4.2 V ✓
- 截止前电压 ≥ 2.5 V ✓
- P_batt = V_terminal × I_batt ✓
- 无 NaN ✓
- 无负电流 ✓
- 大负载下截止触发 ✓

## 图

| 图号 | 文件名 | 内容 |
|------|--------|------|
| Fig 4 | `fig4_ocv_soc.png` | OCV-SOC 曲线（CALCE 20R 25°C） |
| Fig 5 | `fig5_battery_voltage.png` | 电池电压随时间变化（V_ocv + V_terminal + 截止线） |
| Fig 6 | `fig6_battery_power.png` | 电池功率随时间变化 |
| Fig 7 | `fig7_energy_remaining.png` | 剩余能量随时间变化 |

## 当前模型局限

1. **OCV 数据精度**：使用 27 个手动提取的数据点，非完整 CALCE CSV
2. **恒定内阻**：R0 = 18 mΩ 不随 SOC、温度、老化变化
3. **无 DC/DC 模型**：I_batt = I_load 是简化假设
4. **无温度模型**：假设恒定 25°C
5. **无自放电**：忽略了电池自然漏电
6. **无老化模型**：假设全新电池
7. **短时间仿真**：600 s 对 2000 mAh 电池来说太短，SOC 几乎不变
8. **负载电流极小**：传感器节点平均电流 ~1.5 mA，对 2000 mAh 电池来说可忽略
9. **Cutoff 未触发**：在当前负载参数下，600 s 内电池几乎不放电

## 下一步建议

- Part 3: Runtime Predictor — 基于当前放电率预测剩余运行时间
- Part 4: Adaptive Scheduler — 根据剩余能量动态调整 T_S 和 T_TX
- 改进：使用更长仿真时长（如 24 h = 86400 s）或更大负载来观察完整放电过程
- 改进：接入真实 CALCE CSV 数据
