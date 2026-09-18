"""
====================================================================
Predictor 专用仿真 — run_predictor_eval.py
====================================================================

用法：
    python run_predictor_eval.py

说明：
    默认的 600s 仿真对 2000 mAh 电池来说负载太小，
    电池几乎不放电，无法有效评价 Predictor 性能。

    本脚本使用自定义放电曲线来让电池在仿真期间明显放电。
    设计一个 duty-cycled 负载，但平均电流足够大（~200 mA），
    使 2000 mAh 电池在约 10 小时内放空。

    仿真时长 36000 s (10 h)，观察到电池从 100% 放到 ~0%。

====================================================================
"""
import sys
sys.path.insert(0, ".")

import os
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulation.config import (
    OUTPUT_PREDICTOR_METRICS,
    OUTPUT_FIGURES,
    SLIDING_WINDOWS_S,
    BATTERY_Q_NOMINAL_AH,
    BATTERY_R0,
    BATTERY_INITIAL_SOC,
    BATTERY_V_NOMINAL,
    OCV_SOC_POINTS,
    V_TERMINAL_CUTOFF,
    BATTERY_V_CHARGE,
    STATE_PRIORITY,
)
from simulation.battery_model import simulate_battery
from simulation.predictor import (
    run_all_predictors,
    find_dead_time,
    compute_t_actual,
    compute_metrics,
)


def build_heavy_load_profile(duration=36000, dt=1.0):
    """
    构建一个能明显放电的 duty-cycled 负载曲线。

    设计：
      - 每 60 s 一个周期
      - 其中 50 s SLEEP (15 µA)
      - 其中 8 s ACTIVE (200 mA) — 模拟传感器采集+处理
      - 其中 2 s TX (500 mA) — 模拟 LoRa 发送

    平均电流 ≈ 15µA * 50/60 + 200mA * 8/60 + 500mA * 2/60
             ≈ 0 + 26.7 + 16.7 ≈ 43.4 mA

    2000 mAh / 43.4 mA ≈ 46 h → 仍然太长。

    改为更激进的方案：
      - 每 30 s 一个周期
      - 其中 20 s SLEEP (15 µA)
      - 其中 8 s ACTIVE (500 mA)
      - 其中 2 s TX (1000 mA)

    平均电流 ≈ 500mA * 8/30 + 1000mA * 2/30 ≈ 133 + 67 ≈ 200 mA

    2000 mAh / 200 mA = 10 h = 36000 s

    这正是我们想要的。
    """
    n_steps = int(duration / dt)
    timestamps = np.arange(0, duration, dt)
    states = []
    currents = []

    t_cycle = 30.0
    t_active = 8.0   # 500 mA active phase
    t_tx = 2.0       # 1000 mA TX phase
    t_sleep = t_cycle - t_active - t_tx  # 20 s sleep

    i_sleep = 0.000_015
    i_active = 0.500
    i_tx = 1.000

    for step in range(n_steps):
        t_in_cycle = (step * dt) % t_cycle

        if t_in_cycle < t_sleep:
            states.append("SLEEP")
            currents.append(i_sleep)
        elif t_in_cycle < t_sleep + t_active:
            states.append("SAMPLING")
            currents.append(i_active)
        else:
            states.append("LORA_TX")
            currents.append(i_tx)

    load_df = pd.DataFrame({
        "timestamp_s": timestamps,
        "node_state": states,
        "sampling_interval_s": 30.0,
        "transmission_interval_s": 30.0,
        "current_load_A": currents,
        "voltage_bus_V": BATTERY_V_NOMINAL,
        "power_load_W": [BATTERY_V_NOMINAL * i for i in currents],
    })

    return load_df


def main():
    print("=" * 60)
    print("  Predictor Evaluation — Heavy Load, Long Duration")
    print("=" * 60)

    duration = 36000  # 10 hours
    dt = 1.0

    # --- 构建重负载 ---
    load_df = build_heavy_load_profile(duration=duration, dt=dt)

    avg_i = load_df["current_load_A"].mean()
    print(f"\n  Load: {len(load_df)} steps, avg current = {avg_i*1000:.2f} mA")
    print(f"  Duration: {duration} s = {duration/3600:.1f} h")
    print(f"  Expected discharge: ~{avg_i * duration / 3600 * 1000:.0f} mAh")

    # --- 电池仿真 ---
    battery_df = simulate_battery(
        load_df,
        q_nominal=BATTERY_Q_NOMINAL_AH,
        r0=BATTERY_R0,
        initial_soc=BATTERY_INITIAL_SOC,
        v_cutoff=V_TERMINAL_CUTOFF,
        v_charge=BATTERY_V_CHARGE,
        ocv_points=OCV_SOC_POINTS,
    )

    t_dead = find_dead_time(battery_df)
    soc_final = battery_df["battery_soc"].iloc[-1]
    cutoff_steps = battery_df["cutoff_reached"].sum()

    print(f"\n  Battery:")
    print(f"    t_dead = {t_dead:.1f} s")
    print(f"    SOC final = {soc_final*100:.2f}%")
    print(f"    Cutoff steps = {cutoff_steps}")

    # --- 运行 Predictor ---
    # 注意：这里的 T_s/T_tx 与实际负载周期匹配
    predictions, metrics_df = run_all_predictors(
        battery_df, t_s=30.0, t_tx=30.0, windows=SLIDING_WINDOWS_S
    )
    t_actual = compute_t_actual(battery_df, t_dead)

    print(f"\n  T_actual(0) = {t_actual[0]:.1f} s = {t_actual[0]/3600:.2f} h")

    # 保存指标
    metrics_df.to_csv(OUTPUT_PREDICTOR_METRICS, index=False)
    print(f"\n  Metrics saved: {OUTPUT_PREDICTOR_METRICS}")

    # 打印详细指标
    print(f"\n  {'='*90}")
    print(f"  {'Predictor':<20} {'MAE (s)':>10} {'RMSE (s)':>10} {'RelErr':>10} {'OverMean (s)':>12} {'OverRate':>10}")
    print(f"  {'='*90}")
    for _, row in metrics_df.iterrows():
        pred = row["predictor"]
        window = row["window_s"]
        label = f"{pred} ({int(window)}s)" if pred == "B" else f"{pred}"
        rel_str = f"{row['relative_error']:.4f}" if not np.isnan(row['relative_error']) else "N/A"
        print(f"  {label:<20} {row['MAE_s']:>10.1f} {row['RMSE_s']:>10.1f} {rel_str:>10} "
              f"{row['overestimation_mean_s']:>12.1f} {row['overestimation_rate']:>10.2%}")
    print(f"  {'='*90}")

    # --- 绘图 ---
    os.makedirs(OUTPUT_FIGURES, exist_ok=True)

    _plot_a(predictions, t_actual, battery_df, os.path.join(OUTPUT_FIGURES, "fig8_predictor_a.png"))
    _plot_b(predictions, t_actual, battery_df, os.path.join(OUTPUT_FIGURES, "fig9_predictor_b.png"))
    _plot_c(predictions, t_actual, battery_df, os.path.join(OUTPUT_FIGURES, "fig10_predictor_c.png"))
    _plot_comparison(predictions, t_actual, battery_df, os.path.join(OUTPUT_FIGURES, "fig11_predictor_comparison.png"))

    print(f"\n  Figures saved: fig8-11")

    # --- 分析 ---
    _print_analysis(metrics_df)


def _print_analysis(metrics_df):
    print(f"\n{'='*60}")
    print(f"  ANALYSIS")
    print(f"{'='*60}")

    # Predictor A
    row_a = metrics_df[metrics_df["predictor"] == "A"].iloc[0]
    print(f"\n  Predictor A (Instantaneous Power):")
    print(f"    MAE = {row_a['MAE_s']:.1f} s = {row_a['MAE_s']/3600:.2f} h")
    print(f"    Overestimation Rate = {row_a['overestimation_rate']:.1%}")
    print(f"    在 duty-cycled sensor node 中表现极差。")
    print(f"    原因：SLEEP 时 P ≈ 0 → T_hat → 巨大值；")
    print(f"          ACTIVE/TX 时 P 突增 → T_hat → 极小值。")
    print(f"    瞬时功率不代表平均趋势，对占空比极度敏感。")
    print(f"    这是 instantaneous-power predictor 的根本缺陷。")

    # Predictor B
    print(f"\n  Predictor B (Sliding Average):")
    for _, row in metrics_df[metrics_df["predictor"] == "B"].iterrows():
        w = int(row["window_s"])
        print(f"    {w}s: MAE={row['MAE_s']:.1f}s ({row['MAE_s']/3600:.2f}h), "
              f"RelErr={row['relative_error']:.4f}, OverRate={row['overestimation_rate']:.1%}")

    best_b = metrics_df[metrics_df["predictor"] == "B"].nsmallest(1, "MAE_s")
    if len(best_b) > 0:
        best_w = best_b.iloc[0]["window_s"]
        print(f"\n    Best window: {int(best_w)}s (lowest MAE)")

    print(f"    Window 太短 → 仍然敏感于功率波动，预测不稳定。")
    print(f"    Window 太长 → 对放电趋势响应迟钝，不能及时反映变化。")
    print(f"    最佳 window 应该与 duty cycle 周期匹配。")

    # Predictor C
    row_c = metrics_df[metrics_df["predictor"] == "C"].iloc[0]
    print(f"\n  Predictor C (State-Based Model):")
    print(f"    MAE = {row_c['MAE_s']:.1f} s = {row_c['MAE_s']/3600:.2f} h")
    print(f"    RelErr = {row_c['relative_error']:.4f}")
    print(f"    优点：不依赖瞬时波动，能根据 T_s/T_tx 自动调整。")
    print(f"    缺点：假设功耗恒定，不能反映电池内阻随 SOC 的变化。")
    print(f"    适合未来 scheduling policy change（Adaptive Scheduler）。")

    print(f"\n  误差来源：")
    print(f"    - Predictor 误差：A/B 对功率波动的敏感性")
    print(f"    - Battery 模型误差：恒定 R0、无温度模型、OCV-SOC 手动提取")
    print(f"    - 未来需要真实硬件验证：INA226 实测电流 + 电池放电实验")


def _plot_a(predictions, t_actual, battery_df, save_path):
    t_hat_a = predictions["A"]
    max_display = np.percentile(t_actual[t_actual > 0], 95) * 3 if np.any(t_actual > 0) else 10000
    max_display = min(max_display, 1e7)

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(battery_df["timestamp_s"], t_actual, color="#333", linewidth=1.5, label="T_actual")
    ax.step(battery_df["timestamp_s"], np.clip(t_hat_a, 0, max_display), where="post",
            color="#e07070", linewidth=0.8, alpha=0.8,
            label=f"T_hat_A (clipped at {max_display:.0f}s)")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 8: T_actual vs T_hat_A (Instantaneous Power)"); ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right"); plt.tight_layout(); plt.savefig(save_path, dpi=150); plt.close()


def _plot_b(predictions, t_actual, battery_df, save_path):
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(battery_df["timestamp_s"], t_actual, color="#333", linewidth=1.5, label="T_actual")
    colors_b = ["#2070a0", "#40a070", "#e0a040", "#a040a0", "#e07070"]
    for i, key in enumerate(predictions):
        if key.startswith("B_"):
            ax.step(battery_df["timestamp_s"], predictions[key], where="post",
                    color=colors_b[i % len(colors_b)], linewidth=0.8, alpha=0.7,
                    label=f"T_hat_B ({key.replace('B_', 'window=')})")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 9: T_actual vs T_hat_B (Sliding Average)"); ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=7); plt.tight_layout(); plt.savefig(save_path, dpi=150); plt.close()


def _plot_c(predictions, t_actual, battery_df, save_path):
    t_hat_c = predictions["C"]
    active = t_actual > 0
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(t_actual[active], t_hat_c[active], alpha=0.3, s=10, color="#2070a0")
    max_val = max(np.max(t_actual[active]), np.max(t_hat_c[active]))
    ax.plot([0, max_val], [0, max_val], "--", color="#888", linewidth=1.0, label="Perfect")
    ax.set_xlabel("T_actual (s)"); ax.set_ylabel("T_hat_C (s)")
    ax.set_title("Figure 10: T_actual vs T_hat_C (State-Based)"); ax.grid(True, alpha=0.3)
    ax.legend(); ax.set_aspect("equal"); plt.tight_layout(); plt.savefig(save_path, dpi=150); plt.close()


def _plot_comparison(predictions, t_actual, battery_df, save_path):
    best_b_key = None
    best_b_mae = float("inf")
    for key in predictions:
        if key.startswith("B_"):
            mae = compute_metrics(t_actual, predictions[key])["MAE_s"]
            if mae < best_b_mae:
                best_b_mae = mae
                best_b_key = key

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(battery_df["timestamp_s"], t_actual, color="#333", linewidth=1.5, label="T_actual")
    ax.step(battery_df["timestamp_s"], predictions["A"], where="post",
            color="#e07070", linewidth=0.6, alpha=0.6, label="T_hat_A")
    if best_b_key:
        ax.step(battery_df["timestamp_s"], predictions[best_b_key], where="post",
                color="#2070a0", linewidth=1.0, label=f"T_hat_B ({best_b_key.replace('B_', '')})")
    ax.step(battery_df["timestamp_s"], predictions["C"], where="post",
            color="#40a070", linewidth=1.0, label="T_hat_C")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 11: Predictor Comparison"); ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right"); plt.tight_layout(); plt.savefig(save_path, dpi=150); plt.close()


if __name__ == "__main__":
    main()
