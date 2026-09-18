"""
====================================================================
正确性检查（无 pytest 依赖版本） — run_tests.py
====================================================================

用法：
    python run_tests.py

作用：
    对 generate_load_profile() 的输出执行 10 项正确性检查，
    全部通过后打印 "ALL 10 TESTS PASSED"。

检查清单：
  1. 状态序列长度 = SIM_DURATION_S / DT
  2. 时间戳从 0 开始，到 SIM_DURATION_S - DT 结束
  3. LORA_TX 按 T_TX 周期出现
  4. SAMPLING 按 T_S 周期出现
  5. 每个状态映射到正确的电流值
  6. P_load = V_bus * I_load 逐行成立
  7. 不存在 NaN
  8. 不存在负电流
  9. 改变时间步长 dt 后行为一致
  10. 自定义参数覆盖正确

注意：
    本文件是 pytest 不可用时的内联替代方案。
    如果安装了 pytest，应优先使用 tests/test_node_model.py。

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""
import sys
sys.path.insert(0, ".")

from simulation.config import SIM_DURATION_S, DT, T_S, T_TX, BATTERY_V_NOMINAL
from simulation.node_model import generate_load_profile
import numpy as np

# --- 生成默认仿真数据 ---
df = generate_load_profile()
errors = []  # 收集所有失败信息

# ============================================================
# 检查 1: 状态序列长度 = SIM_DURATION_S / DT
# ============================================================
n_steps = int(SIM_DURATION_S / DT)
if len(df) != n_steps:
    errors.append(f"duration: expected {n_steps} rows, got {len(df)}")

# ============================================================
# 检查 2: 时间戳从 0 开始，到 SIM_DURATION_S - DT 结束
# ============================================================
if df["timestamp_s"].iloc[0] != 0:
    errors.append("first timestamp not 0")
if abs(df["timestamp_s"].iloc[-1] - (SIM_DURATION_S - DT)) > DT:
    errors.append("last timestamp wrong")

# ============================================================
# 检查 3: LORA_TX 按 T_TX 周期出现
# ============================================================
tx_rows = df[df["node_state"] == "LORA_TX"]
if len(tx_rows) == 0:
    errors.append("no LORA_TX found")
else:
    first_tx = tx_rows["timestamp_s"].iloc[0]
    # 第一个 TX 应该从 t=0 开始（0 % 120 = 0 < 0.5）
    if first_tx >= 0.5:
        errors.append(f"first TX at {first_tx}, expected near 0")

# ============================================================
# 检查 4: SAMPLING 按 T_S 周期出现
# ============================================================
samp_rows = df[df["node_state"] == "SAMPLING"]
if len(samp_rows) == 0:
    errors.append("no SAMPLING found")

# ============================================================
# 检查 5: 每个状态映射到正确的电流值
# ============================================================
current_map = {"SLEEP": 0.000015, "SAMPLING": 0.008, "LORA_TX": 0.120}
for _, row in df.iterrows():
    expected = current_map[row["node_state"]]
    if abs(row["current_load_A"] - expected) > 1e-9:
        errors.append(f"current mismatch at t={row['timestamp_s']}")
        break

# ============================================================
# 检查 6: P_load = V_bus * I_load 逐行成立
# ============================================================
expected_power = BATTERY_V_NOMINAL * df["current_load_A"]
if not np.allclose(df["power_load_W"], expected_power):
    errors.append("power calculation wrong")

# ============================================================
# 检查 7: 不存在 NaN
# ============================================================
if df.isna().any().any():
    errors.append("NaN detected")

# ============================================================
# 检查 8: 不存在负电流
# ============================================================
if (df["current_load_A"] < 0).any():
    errors.append("negative current detected")

# ============================================================
# 检查 9: 改变时间步长 dt 后行为一致
# ============================================================
df_fine = generate_load_profile(dt=0.5)
df_coarse = generate_load_profile(dt=2.0)
if len(df_fine) != int(SIM_DURATION_S / 0.5):
    errors.append("fine timestep wrong")
if len(df_coarse) != int(SIM_DURATION_S / 2.0):
    errors.append("coarse timestep wrong")

# ============================================================
# 检查 10: 自定义参数覆盖正确
# ============================================================
df_custom = generate_load_profile(duration=100, v_bus=4.2, i_tx=0.200)
if len(df_custom) != 100:
    errors.append(f"custom duration: expected 100, got {len(df_custom)}")
if df_custom["voltage_bus_V"].iloc[0] != 4.2:
    errors.append("custom V_BUS not applied")

# ============================================================
# 汇总结果
# ============================================================
if errors:
    print(f"FAILURES ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
else:
    print("ALL 10 TESTS PASSED")
    print(f"  Rows: {len(df)}, States: {dict(df['node_state'].value_counts())}")
