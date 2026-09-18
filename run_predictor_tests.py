"""
====================================================================
Predictor 正确性检查（无 pytest 依赖） — run_predictor_tests.py
====================================================================

用法：
    python run_predictor_tests.py

检查清单（11 项）：
  1.  T_actual 线性趋近于 0
  2.  所有 Predictor 单位一致（秒）
  3.  E_remaining / P 的 dimensional analysis 正确
  4.  Sleep period 造成 Predictor A 大幅波动
  5.  Sliding window 越大使用越多历史数据
  6.  Predictor C 能根据 T_s / T_tx 重新计算
  7.  死亡之后 predictor 停止
  8.  无 inf / NaN（除了 A 的已知异常）
  9.  Relative error 正确处理接近 0 的 ground truth
  10. T_hat 在 t >= t_dead 后为 0
  11. MAE / RMSE 计算正确

====================================================================
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from simulation.config import RELATIVE_ERROR_MIN_T_ACTUAL
from simulation.node_model import generate_load_profile
from simulation.battery_model import simulate_battery
from simulation.predictor import (
    find_dead_time,
    compute_t_actual,
    predictor_instantaneous,
    predictor_sliding_window,
    predictor_state_based,
    compute_expected_average_power,
    compute_metrics,
    run_all_predictors,
    P_EPSILON,
)

errors = []

# ============================================================
# 生成数据（使用较短但能明显放电的仿真）
# ============================================================
# 构建一个能放电的负载
duration = 36000
dt = 1.0
n_steps = int(duration / dt)
timestamps = np.arange(0, duration, dt)

# Duty cycle: 30s period, 20s sleep, 8s sampling, 2s TX
states = []
currents = []
for step in range(n_steps):
    t_in_cycle = (step * dt) % 30.0
    if t_in_cycle < 20.0:
        states.append("SLEEP")
        currents.append(0.000_015)
    elif t_in_cycle < 28.0:
        states.append("SAMPLING")
        currents.append(0.500)
    else:
        states.append("LORA_TX")
        currents.append(1.000)

load_df = pd.DataFrame({
    "timestamp_s": timestamps,
    "node_state": states,
    "sampling_interval_s": 30.0,
    "transmission_interval_s": 30.0,
    "current_load_A": currents,
    "voltage_bus_V": 3.6,
    "power_load_W": [3.6 * i for i in currents],
})

battery_df = simulate_battery(load_df)
t_dead = find_dead_time(battery_df)
t_actual = compute_t_actual(battery_df, t_dead)

predictions, metrics_df = run_all_predictors(battery_df, t_s=30.0, t_tx=30.0)

# ============================================================
# 1. T_actual 线性趋近于 0
# ============================================================
# T_actual(t) = t_dead - t，应该严格线性下降
active = t_actual > 0
if np.any(active):
    t_active = t_actual[active]
    diffs = np.diff(t_active)
    # 相邻差应该接近 -dt（因为 T_actual = t_dead - t）
    if not np.allclose(diffs, -dt, atol=0.01):
        errors.append(f"T_actual not linear: diffs mean={np.mean(diffs):.4f}, expected -{dt}")

# ============================================================
# 2. 所有 Predictor 单位一致（秒）
# ============================================================
for key, t_hat in predictions.items():
    if np.any(t_hat < 0):
        errors.append(f"Predictor {key} has negative values (unit error?)")
    # C 始终高估（这是已知的模型缺陷）
    if key == "C":
        if np.any(t_hat > t_dead * 1000):
            errors.append(f"Predictor {key} has extremely large values (possible unit error)")

# ============================================================
# 3. E_remaining / P 的 dimensional analysis
# ============================================================
# Wh / W = h, h * 3600 = s
# 验证：T_hat ≈ E_remaining / P * 3600
e_rem = battery_df["energy_remaining_Wh"].values
p_batt = battery_df["battery_power_W"].values
p_safe = np.maximum(p_batt, P_EPSILON)
expected_t = e_rem / p_safe * 3600.0

# A predictor 应该等于这个值（除了 cutoff 后）
t_hat_a = predictions["A"]
before_cutoff = battery_df["timestamp_s"] < t_dead
if np.any(before_cutoff):
    a_before = t_hat_a[before_cutoff]
    expected_before = expected_t[before_cutoff]
    # 允许一些数值误差
    if not np.allclose(a_before, expected_before, rtol=1e-6):
        errors.append(f"Predictor A dimensional analysis failed")

# ============================================================
# 4. Sleep period 造成 Predictor A 大幅波动
# ============================================================
t_hat_a = predictions["A"]
sleep_mask = np.array(battery_df["node_state"] == "SLEEP")
active_mask = np.array(battery_df["node_state"] != "SLEEP")

if np.any(sleep_mask) and np.any(active_mask):
    a_sleep = t_hat_a[sleep_mask & before_cutoff]
    a_active = t_hat_a[active_mask & before_cutoff]

    sleep_median = np.median(a_sleep[a_sleep < 1e10])  # 排除 inf
    active_median = np.median(a_active)

    # SLEEP 时的预测应该远大于 ACTIVE 时
    if sleep_median < active_median * 2:
        errors.append(f"Predictor A: sleep median ({sleep_median:.1f}s) not >> active median ({active_median:.1f}s)")

# ============================================================
# 5. Sliding window 越大使用越多历史数据
# ============================================================
# 验证：当有足够数据时（t > 300s），不同 window 的预测结果不同
t_hat_10s = predictions.get("B_10s")
t_hat_300s = predictions.get("B_300s")
if t_hat_10s is not None and t_hat_300s is not None:
    # 在 t > 300s 后，10s window 使用最近 10s 数据
    # 而 300s window 使用最近 300s 数据
    # 由于 duty cycle 的功率波动，它们应该给出不同结果
    late = (battery_df["timestamp_s"] > 300) & (battery_df["timestamp_s"] < t_dead)
    if np.any(late):
        diff_late = np.abs(t_hat_10s[late] - t_hat_300s[late])
        # 应该有一定差异（> 1% of median prediction）
        median_pred = np.median(t_hat_300s[late])
        if np.all(diff_late < median_pred * 0.01):
            errors.append("Sliding windows produce nearly identical results (should differ)")

# ============================================================
# 6. Predictor C 能根据 T_s / T_tx 重新计算
# ============================================================
from simulation.predictor import compute_expected_average_power

p1 = compute_expected_average_power(t_s=30.0, t_tx=30.0)
p2 = compute_expected_average_power(t_s=60.0, t_tx=60.0)
if p1 == p2:
    # 如果占空比相同，功率可能相同。检查参数改变是否有影响
    p3 = compute_expected_average_power(t_s=30.0, t_tx=30.0, t_s_active=4.0)
    if p1 == p3:
        errors.append("Predictor C does not respond to parameter changes")

# ============================================================
# 7. 死亡之后 predictor 停止
# ============================================================
after_cutoff = battery_df["timestamp_s"] >= t_dead
if np.any(after_cutoff):
    for key, t_hat in predictions.items():
        if np.any(t_hat[after_cutoff] != 0):
            errors.append(f"Predictor {key} non-zero after t_dead")

# ============================================================
# 8. 无 inf / NaN（除了 A 的已知异常）
# ============================================================
for key, t_hat in predictions.items():
    if key == "A":
        # A 可能有 inf，这是已知的
        continue
    if np.any(np.isnan(t_hat)):
        errors.append(f"Predictor {key} contains NaN")
    if np.any(np.isinf(t_hat)):
        errors.append(f"Predictor {key} contains inf")

# 检查 metrics 是否有意外的 NaN
for _, row in metrics_df.iterrows():
    pred = row["predictor"]
    if pred != "A":
        for col in ["MAE_s", "RMSE_s", "relative_error", "overestimation_mean_s", "overestimation_rate"]:
            if pd.isna(row[col]):
                errors.append(f"Predictor {pred} metric {col} is NaN")

# ============================================================
# 9. Relative error 正确处理接近 0 的 ground truth
# ============================================================
# 手动计算 relative error 并验证
t_hat_c = predictions["C"]
active_mask = t_actual > 0
rel_mask = t_actual[active_mask] > RELATIVE_ERROR_MIN_T_ACTUAL

if np.any(rel_mask):
    rel_errors_manual = np.abs(t_hat_c[active_mask][rel_mask] - t_actual[active_mask][rel_mask]) / t_actual[active_mask][rel_mask]
    manual_rel_err = np.mean(rel_errors_manual)

    reported_rel_err = metrics_df[metrics_df["predictor"] == "C"].iloc[0]["relative_error"]
    if not np.isclose(manual_rel_err, reported_rel_err, rtol=1e-6):
        errors.append(f"Relative error mismatch: manual={manual_rel_err:.4f}, reported={reported_rel_err:.4f}")

# ============================================================
# 10. T_hat 在 t >= t_dead 后为 0
# ============================================================
for key, t_hat in predictions.items():
    after = t_hat[battery_df["timestamp_s"].values >= t_dead]
    if len(after) > 0 and not np.all(after == 0):
        errors.append(f"Predictor {key} non-zero after t_dead")

# ============================================================
# 11. MAE / RMSE 计算正确
# ============================================================
for _, row in metrics_df.iterrows():
    pred = row["predictor"]
    if pred == "A":
        t_hat = predictions["A"]
    elif pred == "B":
        w = int(row["window_s"])
        t_hat = predictions.get(f"B_{w}s")
    elif pred == "C":
        t_hat = predictions["C"]
    else:
        continue

    if t_hat is None:
        continue

    active_mask = t_actual > 0
    if np.any(active_mask):
        t_act = t_actual[active_mask]
        t_pred = t_hat[active_mask]

        mae_manual = np.mean(np.abs(t_pred - t_act))
        rmse_manual = np.sqrt(np.mean((t_pred - t_act) ** 2))

        if not np.isclose(mae_manual, row["MAE_s"], rtol=1e-6):
            errors.append(f"Predictor {pred} MAE mismatch: manual={mae_manual:.4f}, reported={row['MAE_s']:.4f}")
        if not np.isclose(rmse_manual, row["RMSE_s"], rtol=1e-6):
            errors.append(f"Predictor {pred} RMSE mismatch: manual={rmse_manual:.4f}, reported={row['RMSE_s']:.4f}")

# ============================================================
# 汇总
# ============================================================
if errors:
    print(f"FAILURES ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
else:
    print(f"ALL 11 TESTS PASSED")
    print(f"  t_dead = {t_dead:.1f} s")
    print(f"  T_actual(0) = {t_actual[0]:.1f} s")
    print(f"  SOC final = {battery_df['battery_soc'].iloc[-1]*100:.2f}%")
    print(f"  Predictors evaluated: {list(predictions.keys())}")
