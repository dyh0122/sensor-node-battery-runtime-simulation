"""
====================================================================
电池模型正确性检查（无 pytest 依赖） — run_battery_tests.py
====================================================================

用法：
    python run_battery_tests.py

检查清单（13 项）：
  1.  SOC 单调下降
  2.  Energy used 单调增加
  3.  Energy remaining 单调下降
  4.  初始电压 ≤ 4.2 V
  5.  截止前电压 ≥ 2.5 V
  6.  P_batt = V_terminal * I_batt
  7.  E_total 在合理范围
  8.  dt 改变后能量一致
  9.  无 NaN
  10. OCV 插值在范围内
  11. OCV 超出范围抛异常
  12. 截止机制触发（大负载）
  13. SOC-OCV 一致性

====================================================================
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

from simulation.config import BATTERY_V_CHARGE, BATTERY_V_CUTOFF, OCV_SOC_POINTS
from simulation.node_model import generate_load_profile
from simulation.battery_model import simulate_battery, build_ocv_interpolator

errors = []

# ============================================================
# 生成数据
# ============================================================
load_df = generate_load_profile()
battery_df = simulate_battery(load_df)
ocv_interp = build_ocv_interpolator(OCV_SOC_POINTS)

# ============================================================
# 1. SOC 单调下降
# ============================================================
soc = battery_df["battery_soc"].values
diffs = np.diff(soc)
if not np.all(diffs <= 1e-12):
    errors.append(f"SOC increased at indices: {np.where(diffs > 1e-12)[0]}")

# ============================================================
# 2. Energy used 单调增加
# ============================================================
e_used = battery_df["energy_used_Wh"].values
diffs_e = np.diff(e_used)
if not np.all(diffs_e >= -1e-12):
    errors.append(f"E_used decreased at indices: {np.where(diffs_e < -1e-12)[0]}")

# ============================================================
# 3. Energy remaining 单调下降
# ============================================================
e_remain = battery_df["energy_remaining_Wh"].values
diffs_er = np.diff(e_remain)
if not np.all(diffs_er <= 1e-12):
    errors.append(f"E_remaining increased at indices: {np.where(diffs_er > 1e-12)[0]}")

# ============================================================
# 4. 初始电压 ≤ 4.2 V
# ============================================================
v_init = battery_df["battery_terminal_voltage_V"].iloc[0]
if v_init > BATTERY_V_CHARGE + 0.01:
    errors.append(f"Initial V_terminal = {v_init:.4f} V > V_charge = {BATTERY_V_CHARGE} V")

# ============================================================
# 5. 截止前电压 ≥ 2.5 V
# ============================================================
active_rows = battery_df[~battery_df["cutoff_reached"]]
v_min = active_rows["battery_terminal_voltage_V"].min()
if v_min < BATTERY_V_CUTOFF - 0.01:
    errors.append(f"V_terminal dropped to {v_min:.4f} V before cutoff (limit: {BATTERY_V_CUTOFF} V)")

# ============================================================
# 6. P_batt = V_terminal * I_batt
# ============================================================
expected_power = battery_df["battery_terminal_voltage_V"] * battery_df["battery_current_A"]
if not np.allclose(battery_df["battery_power_W"], expected_power):
    errors.append("Power calculation mismatch")

# ============================================================
# 7. E_total 在合理范围
# ============================================================
e_total = battery_df["energy_remaining_Wh"].iloc[0]
if not (5.0 < e_total < 9.0):
    errors.append(f"E_total = {e_total:.4f} Wh, expected 5-9 Wh range")

# ============================================================
# 8. dt 改变后能量一致
# ============================================================
# 注意：由于 LORA_TX 窗口很短 (0.5s)，不同的 dt 会导致
# TX 捕获精度不同，因此总能量会有差异。
# 本测试验证：当 TX 窗口远大于 dt 时，能量应该一致。
# 使用更大的 T_TX_ACTIVE 来测试。
load_fine = generate_load_profile(duration=600, dt=0.5, t_tx_active=5.0)
load_coarse = generate_load_profile(duration=600, dt=2.0, t_tx_active=5.0)
df_fine = simulate_battery(load_fine)
df_coarse = simulate_battery(load_coarse)

e_used_fine = df_fine["energy_used_Wh"].iloc[-1]
e_used_coarse = df_coarse["energy_used_Wh"].iloc[-1]

if e_used_fine > 0 and e_used_coarse > 0:
    ratio = e_used_fine / e_used_coarse
    if not (0.85 < ratio < 1.15):
        errors.append(f"E_used differs by timestep: fine={e_used_fine:.6f}, coarse={e_used_coarse:.6f}, ratio={ratio:.4f}")

# ============================================================
# 9. 无 NaN
# ============================================================
if battery_df.isna().any().any():
    errors.append("DataFrame contains NaN values")

# ============================================================
# 10. OCV 插值在范围内
# ============================================================
for soc_test in [0.0, 0.5, 1.0]:
    v = ocv_interp(soc_test)
    if not (2.5 <= v <= 4.3):
        errors.append(f"OCV at SOC={soc_test} is {v} V, out of expected range")

# ============================================================
# 11. OCV 超出范围抛异常
# ============================================================
try:
    ocv_interp(-0.1)
    errors.append("OCV interp did not raise for SOC=-0.1")
except ValueError:
    pass  # expected

try:
    ocv_interp(1.1)
    errors.append("OCV interp did not raise for SOC=1.1")
except ValueError:
    pass  # expected

# ============================================================
# 12. 截止机制触发（大负载）
# ============================================================
n_steps = 10000
heavy_load_df = pd.DataFrame({
    "timestamp_s": np.arange(n_steps, dtype=float),
    "current_load_A": np.full(n_steps, 1.0),
})
heavy_battery_df = simulate_battery(heavy_load_df)
cutoff_count = heavy_battery_df["cutoff_reached"].sum()
if cutoff_count == 0:
    errors.append("Cutoff not triggered under 1 A load")

# ============================================================
# 13. SOC-OCV 一致性
# ============================================================
soc_values = [p[0] for p in OCV_SOC_POINTS]
v_ocv_values = [p[1] for p in OCV_SOC_POINTS]
soc_ocv_interp = interp1d(soc_values, v_ocv_values, kind="linear")
expected_ocv = soc_ocv_interp(battery_df["battery_soc"].values)
if not np.allclose(battery_df["battery_ocv_V"].values, expected_ocv):
    errors.append("OCV-SOC mapping inconsistent")

# ============================================================
# 汇总
# ============================================================
if errors:
    print(f"FAILURES ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
else:
    e_used = battery_df["energy_used_Wh"].iloc[-1]
    print(f"ALL 13 TESTS PASSED")
    print(f"  Rows: {len(battery_df)}")
    print(f"  E_total: {e_total:.4f} Wh")
    print(f"  E_used:  {e_used:.4f} Wh")
    print(f"  SOC final: {soc[-1]*100:.2f}%")
    print(f"  V_terminal final: {battery_df['battery_terminal_voltage_V'].iloc[-1]:.4f} V")
    print(f"  Cutoff steps: {int(cutoff_count)}")
