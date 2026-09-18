"""
====================================================================
Part 4 主入口 — run_adaptive.py
====================================================================

用法：
    python run_adaptive.py

运行：
  1. Fixed High QoS baseline
  2. Fixed Balanced baseline
  3. Fixed Survival baseline
  4. Adaptive scheduling (prediction-driven)
  5. Sensitivity analysis (threshold variation)
  6. 生成所有图 + CSV + 总结表
  7. 回答四个核心研究问题

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

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
import matplotlib.patches as mpatches

from simulation.config import (
    OUTPUT_FIGURES,
    OUTPUT_ADAPTIVE_CSV,
    OUTPUT_SCHEDULING_SUMMARY,
    SCHEDULING_MODES,
    BATTERY_Q_NOMINAL_AH,
    BATTERY_R0,
    BATTERY_INITIAL_SOC,
    OCV_SOC_POINTS,
    V_TERMINAL_CUTOFF,
    BATTERY_V_CHARGE,
    BATTERY_V_NOMINAL,
    T_S_ACTIVE,
    T_TX_ACTIVE,
    I_SLEEP,
    I_SAMPLING,
    I_TX,
    QOS_W_SAMPLE,
    QOS_W_TX,
)
from simulation.predictor import (
    compute_expected_average_power,
    compute_t_actual,
    find_dead_time,
)
from simulation.battery_model import simulate_battery, build_ocv_interpolator
from simulation.scheduler import (
    simulate_adaptive,
    run_fixed_baseline,
    get_mode_params,
    decide_next_mode,
)


def main():
    print("=" * 70)
    print("  Part 4: Prediction-Driven Adaptive Energy Scheduling")
    print("=" * 70)

    os.makedirs(OUTPUT_FIGURES, exist_ok=True)

    # --- Current function for adaptive simulation (fixed hardware) ---
    def current_fn(mode_name, t_s, t_tx):
        """Fixed hardware currents for all modes."""
        return I_SLEEP, 0.050, 0.200

    # --- Predictor C function with fixed currents ---
    def predictor_c_fn(battery_df_subset, t_s, t_tx):
        """Predictor C with fixed hardware currents."""
        if len(battery_df_subset) == 0:
            return 0.0
        e_remain = battery_df_subset["energy_remaining_Wh"].iloc[-1]
        p_model = compute_expected_average_power(
            t_s=t_s, t_tx=t_tx,
            t_s_active=T_S_ACTIVE, t_tx_active=T_TX_ACTIVE,
            i_sleep=I_SLEEP, i_sampling=0.050, i_tx=0.200,
            v_bus=BATTERY_V_NOMINAL,
        )
        if p_model <= 0:
            return 0.0
        return e_remain / p_model * 3600.0

    # ============================================================
    # Step 1: Fixed Baselines
    # ============================================================
    print("\n--- Step 1: Fixed Scheduling Baselines ---")

    duration = 144000  # 40 hours — enough for even SURVIVAL to reach cutoff
    dt = 1.0

    # --- Build heavy load profiles for each mode ---
    # The default Part 1 currents are too small (µA-mA range).
    # For Part 4 we need currents that meaningfully drain the 2000 mAh battery.
    # Using the same heavy load design as Part 3 evaluator:
    #   30s cycle: 20s SLEEP (15µA), 8s SAMPLING (500mA), 2s TX (1000mA)
    #   Average ≈ 200mA → 2000mAh / 200mA = 10h
    #
    # But each mode has different T_s / T_tx, so we need different duty cycles.
    def build_heavy_load(mode_name, dur, dt_val):
        """
        Build load profile with FIXED hardware currents (same sensor, same LoRa).
        Different modes have different duty cycles, so average power differs.
        """
        t_s, t_tx = get_mode_params(mode_name)
        t_s_act = T_S_ACTIVE
        t_tx_act = T_TX_ACTIVE

        from simulation.node_model import _build_schedule
        states = _build_schedule(
            dur, dt_val, t_s, t_tx, t_s_act, t_tx_act,
            ["LORA_TX", "SAMPLING", "SLEEP"]
        )

        # Fixed hardware currents (same sensor and LoRa for all modes)
        i_sleep = I_SLEEP
        i_sampling = 0.050   # 50 mA (realistic sensor)
        i_tx = 0.200          # 200 mA (realistic LoRa TX)

        current_map = {"SLEEP": i_sleep, "SAMPLING": i_sampling, "LORA_TX": i_tx}
        currents = [current_map[s] for s in states]
        timestamps = np.arange(0, dur, dt_val)

        avg_i = np.mean(currents)
        print(f"    [{mode_name}] avg_I={avg_i*1000:.2f}mA")

        return pd.DataFrame({
            "timestamp_s": timestamps,
            "node_state": states,
            "sampling_interval_s": t_s,
            "transmission_interval_s": t_tx,
            "current_load_A": currents,
            "voltage_bus_V": BATTERY_V_NOMINAL,
            "power_load_W": [BATTERY_V_NOMINAL * i for i in currents],
        })

    fixed_results = {}
    fixed_dfs = {}

    for mode_name in ["HIGH_QoS", "BALANCED", "SURVIVAL"]:
        print(f"\n  Running Fixed {mode_name}...")
        load_df = build_heavy_load(mode_name, duration, dt)
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

        # Count samples and TX up to cutoff
        if battery_df["cutoff_reached"].sum() > 0:
            cutoff_idx = int(battery_df["cutoff_reached"].idxmax())
        else:
            cutoff_idx = len(battery_df)

        states_list = load_df["node_state"].iloc[:cutoff_idx].tolist()
        sample_count = sum(1 for s in states_list if s == "SAMPLING")
        tx_count = sum(1 for s in states_list if s == "LORA_TX")
        avg_power = np.mean([c * BATTERY_V_NOMINAL for c in load_df["current_load_A"].iloc[:cutoff_idx] if c > 0])

        summary = {
            "strategy": f"Fixed {mode_name}",
            "t_dead": t_dead,
            "runtime_h": t_dead / 3600.0,
            "runtime_s": t_dead,
            "sample_count": sample_count,
            "tx_count": tx_count,
            "average_power_W": avg_power,
            "final_soc": battery_df["battery_soc"].iloc[-1],
            "cutoff_reached": battery_df["cutoff_reached"].sum() > 0,
        }

        fixed_results[mode_name] = summary
        fixed_dfs[mode_name] = battery_df

        soc_final = battery_df["battery_soc"].iloc[-1]
        cutoff = battery_df["cutoff_reached"].sum()
        print(f"    Runtime: {t_dead/3600:.2f} h, SOC final: {soc_final*100:.2f}%, Cutoff: {cutoff}")

    # High QoS reference for QoS calculation
    # QoS is defined as: actual count / (High QoS rate * actual runtime)
    # This means QoS = 1.0 means "equivalent to running High QoS for the same duration"
    high_runtime = fixed_results["HIGH_QoS"]["t_dead"]
    high_t_s, high_t_tx = get_mode_params("HIGH_QoS")
    high_sample_rate = fixed_results["HIGH_QoS"]["sample_count"] / high_runtime  # samples/s
    high_tx_rate = fixed_results["HIGH_QoS"]["tx_count"] / high_runtime  # tx/s
    print(f"\n  Reference (Fixed High QoS): {high_sample_rate:.4f} samples/s, {high_tx_rate:.4f} tx/s, runtime={high_runtime/3600:.2f} h")

    # ============================================================
    # Step 2: Adaptive Scheduling
    # ============================================================
    print(f"\n--- Step 2: Adaptive Scheduling ---")

    # 使用 High QoS 的电池轨迹作为 predictor 输入
    # （adaptive 会动态改变调度，但 predictor 基于当前电池状态预测）
    adapt_battery_df = fixed_dfs["HIGH_QoS"].copy()

    # --- Current scaling function for adaptive simulation ---
    def current_fn(mode_name, t_s, t_tx):
        """Compute scaled currents for a given mode."""
        duty_s = T_S_ACTIVE / t_s
        duty_tx_val = T_TX_ACTIVE / t_tx
        i_samp = 0.200 / (duty_s + 2 * duty_tx_val)
        i_tx_val = 2 * i_samp
        return I_SLEEP, i_samp, i_tx_val

    adapt_df, adapt_summary, mode_log_df = simulate_adaptive(
        adapt_battery_df,
        predictor_fn=predictor_c_fn,
        current_fn=current_fn,
        initial_mode="HIGH_QoS",
        check_interval=60.0,
        fixed_high_runtime=high_runtime,
    )

    adapt_runtime = adapt_df[adapt_df["battery_power"] > 0]["timestamp_s"].max()
    if pd.isna(adapt_runtime):
        adapt_runtime = 0

    # Compute QoS using rates
    adapt_sample_count = adapt_summary["sample_count"]
    adapt_tx_count = adapt_summary["tx_count"]
    adapt_qos_sampling = adapt_sample_count / (high_sample_rate * adapt_runtime) if adapt_runtime > 0 and high_sample_rate > 0 else 0
    adapt_qos_tx = adapt_tx_count / (high_tx_rate * adapt_runtime) if adapt_runtime > 0 and high_tx_rate > 0 else 0
    adapt_qos_composite = QOS_W_SAMPLE * adapt_qos_sampling + QOS_W_TX * adapt_qos_tx

    # Update summary with corrected QoS
    adapt_summary["sampling_qos"] = adapt_qos_sampling
    adapt_summary["communication_qos"] = adapt_qos_tx
    adapt_summary["composite_qos"] = adapt_qos_composite

    print(f"  Adaptive runtime: {adapt_runtime/3600:.2f} h")
    print(f"  Samples: {adapt_summary['sample_count']}, TX: {adapt_summary['tx_count']}")
    print(f"  Composite QoS: {adapt_summary['composite_qos']:.4f}")
    print(f"  Mode switches: {adapt_summary['mode_switches']}")

    # 保存 adaptive CSV
    adapt_df.to_csv(OUTPUT_ADAPTIVE_CSV, index=False)
    print(f"  Saved: {OUTPUT_ADAPTIVE_CSV}")

    # ============================================================
    # Step 3: Sensitivity Analysis
    # ============================================================
    print(f"\n--- Step 3: Sensitivity Analysis ---")

    sensitivity_results = []
    thresholds = [
        (1800, 900),    # 激进的切换（更早降级）
        (3600, 1800),   # 默认
        (7200, 3600),   # 保守的切换（更晚降级）
        (10800, 5400),  # 非常保守
    ]

    for th_hb, th_bs in thresholds:
        adapt_df_s, summary_s, _ = simulate_adaptive(
            adapt_battery_df,
            predictor_fn=predictor_c_fn,
            current_fn=current_fn,
            initial_mode="HIGH_QoS",
            check_interval=60.0,
            threshold_high_to_balanced=th_hb,
            threshold_balanced_to_survival=th_bs,
            fixed_high_runtime=high_runtime,
        )

        rt = adapt_df_s[adapt_df_s["battery_power"] > 0]["timestamp_s"].max()
        if pd.isna(rt):
            rt = 0

        # Compute QoS for sensitivity point
        sc = summary_s["sample_count"]
        tc = summary_s["tx_count"]
        qos_s = sc / (high_sample_rate * rt) if rt > 0 and high_sample_rate > 0 else 0
        qos_t = tc / (high_tx_rate * rt) if rt > 0 and high_tx_rate > 0 else 0
        summary_s["sampling_qos"] = qos_s
        summary_s["communication_qos"] = qos_t
        summary_s["composite_qos"] = QOS_W_SAMPLE * qos_s + QOS_W_TX * qos_t

        sensitivity_results.append({
            "threshold_H→B_s": th_hb,
            "threshold_B→S_s": th_bs,
            "runtime_h": rt / 3600.0,
            "sample_count": summary_s["sample_count"],
            "tx_count": summary_s["tx_count"],
            "composite_qos": summary_s["composite_qos"],
            "mode_switches": summary_s["mode_switches"],
        })
        print(f"  H→B={th_hb/3600:.1f}h, B→S={th_bs/3600:.1f}h: "
              f"RT={rt/3600:.2f}h, QoS={summary_s['composite_qos']:.3f}, "
              f"Switches={summary_s['mode_switches']}")

    sens_df = pd.DataFrame(sensitivity_results)

    # ============================================================
    # Step 4: Summary Table
    # ============================================================
    print(f"\n--- Step 4: Summary Table ---")

    summary_rows = []

    for mode_name in ["HIGH_QoS", "BALANCED", "SURVIVAL"]:
        s = fixed_results[mode_name]
        t_d = s["t_dead"]
        sample_c = s["sample_count"]
        tx_c = s["tx_count"]
        # QoS relative to High QoS rate * actual runtime
        qos_s = sample_c / (high_sample_rate * t_d) if t_d > 0 and high_sample_rate > 0 else 0
        qos_t = tx_c / (high_tx_rate * t_d) if t_d > 0 and high_tx_rate > 0 else 0
        qos_c = QOS_W_SAMPLE * qos_s + QOS_W_TX * qos_t

        summary_rows.append({
            "strategy": f"Fixed {mode_name}",
            "runtime_h": t_d / 3600.0,
            "runtime_extension %": 0.0,  # baseline
            "sample_count": sample_c,
            "tx_count": tx_c,
            "sampling_qos": qos_s,
            "communication_qos": qos_t,
            "composite_qos": qos_c,
            "average_power_W": s["average_power_W"],
            "MAE": np.nan,
            "RMSE": np.nan,
            "relative_error": np.nan,
            "overestimation_rate": np.nan,
        })

    # Adaptive row
    adapt_t_dead = adapt_runtime
    rt_ext = (adapt_t_dead - high_runtime) / high_runtime * 100 if high_runtime > 0 else 0

    summary_rows.append({
        "strategy": "Adaptive (C-based)",
        "runtime_h": adapt_t_dead / 3600.0,
        "runtime extension %": rt_ext,
        "sample_count": adapt_summary["sample_count"],
        "tx_count": adapt_summary["tx_count"],
        "sampling_qos": adapt_summary["sampling_qos"],
        "communication_qos": adapt_summary["communication_qos"],
        "composite_qos": adapt_summary["composite_qos"],
        "average_power_W": adapt_summary["average_power_W"],
        "MAE": adapt_summary["MAE"],
        "RMSE": adapt_summary["RMSE"],
        "relative_error": adapt_summary["relative_error"],
        "overestimation_rate": adapt_summary["overestimation_rate"],
    })

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUTPUT_SCHEDULING_SUMMARY, index=False)
    print(f"  Saved: {OUTPUT_SCHEDULING_SUMMARY}")

    # 打印总结
    print(f"\n  {'Strategy':<25} {'Runtime(h)':>10} {'Extension%':>12} {'Samples':>8} {'TX':>6} "
          f"{'QoS':>6} {'AvgP(mW)':>10}")
    print(f"  {'-'*80}")
    for _, row in summary_df.iterrows():
        print(f"  {row['strategy']:<25} {row['runtime_h']:>10.2f} {row['runtime extension %']:>11.1f}% "
              f"{row['sample_count']:>8} {row['tx_count']:>6} {row['composite_qos']:>6.3f} "
              f"{row['average_power_W']*1000:>10.2f}")

    # ============================================================
    # Step 5: 绘图
    # ============================================================
    print(f"\n--- Step 5: Generating Figures ---")

    _plot_scheduling_mode(adapt_df, os.path.join(OUTPUT_FIGURES, "fig12_scheduling_mode.png"))
    _plot_battery_power_comparison(fixed_dfs, adapt_df, os.path.join(OUTPUT_FIGURES, "fig13_battery_power.png"))
    _plot_energy_comparison(fixed_dfs, adapt_df, os.path.join(OUTPUT_FIGURES, "fig14_energy_remaining.png"))
    _plot_runtime_prediction(adapt_df, os.path.join(OUTPUT_FIGURES, "fig15_runtime_prediction.png"))
    _plot_runtime_comparison(summary_df, os.path.join(OUTPUT_FIGURES, "fig16_runtime_comparison.png"))
    _plot_runtime_qos_tradeoff(summary_df, sens_df, os.path.join(OUTPUT_FIGURES, "fig17_runtime_qos_tradeoff.png"))

    print(f"  Figures saved: fig12-17")

    # ============================================================
    # Step 6: 回答研究问题
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  RESEARCH QUESTIONS")
    print(f"{'='*70}")

    # RQ1
    print(f"\n  RQ1: Different Predictor accuracy for duty-cycled sensor nodes?")
    print(f"    Predictor C (state-based) MAE = {adapt_summary['MAE']:.1f} s "
          f"({adapt_summary['MAE']/3600:.2f} h)")
    print(f"    RelErr = {adapt_summary['relative_error']:.4f}")
    print(f"    Overestimation Rate = {adapt_summary['overestimation_rate']:.1%}")
    print(f"    → C 始终高估，因为使用固定 V_bus 而非 V_ocv(SOC)")

    # RQ2
    print(f"\n  RQ2: Can Adaptive extend runtime vs Fixed High-QoS?")
    print(f"    Fixed High QoS: {high_runtime/3600:.2f} h")
    print(f"    Adaptive:       {adapt_runtime/3600:.2f} h")
    if adapt_runtime > high_runtime:
        print(f"    → YES: +{rt_ext:.1f}% runtime extension")
    else:
        print(f"    → NO: {abs(rt_ext):.1f}% shorter")

    # RQ3
    print(f"\n  RQ3: What QoS cost for runtime extension?")
    print(f"    Adaptive Sampling QoS: {adapt_summary['sampling_qos']:.3f}")
    print(f"    Adaptive Communication QoS: {adapt_summary['communication_qos']:.3f}")
    print(f"    Adaptive Composite QoS: {adapt_summary['composite_qos']:.3f}")
    print(f"    → QoS 代价 = {1 - adapt_summary['composite_qos']:.1%}")

    # RQ4
    print(f"\n  RQ4: Do prediction errors cause premature/late mode switches?")
    if adapt_summary['overestimation_rate'] > 0.5:
        print(f"    Overestimation Rate = {adapt_summary['overestimation_rate']:.1%} > 50%")
        print(f"    → Predictor C 倾向于高估，导致模式切换可能偏晚")
    else:
        print(f"    Overestimation Rate = {adapt_summary['overestimation_rate']:.1%}")
        print(f"    → 预测误差在可接受范围内")

    print(f"\n{'='*70}")
    print(f"  Limitations")
    print(f"{'='*70}")
    print(f"  - 当前结果基于 digital prototype，非真实硬件")
    print(f"  - 电池模型使用恒定 R0，无温度/老化模型")
    print(f"  - OCV-SOC 使用手动提取的 27 个点")
    print(f"  - 结论仅适用于 Samsung INR18650-20R + synthetic node load 条件")
    print(f"  - 需要真实硬件验证：INA226 电流 + 电池放电实验")


def _plot_scheduling_mode(adapt_df, save_path):
    """Figure 12: Scheduling Mode vs Time"""
    modes = adapt_df["mode"].values
    timestamps = adapt_df["timestamp_s"].values

    mode_map = {"HIGH_QoS": 2, "BALANCED": 1, "SURVIVAL": 0}
    mode_colors = {"HIGH_QoS": "#40a070", "BALANCED": "#e0a040", "SURVIVAL": "#e07070"}

    fig, ax = plt.subplots(figsize=(14, 3))
    ax.step(timestamps, [mode_map.get(m, 1) for m in modes], where="post", color="#333", linewidth=0.8)

    # 填充颜色
    for mode_name, level in mode_map.items():
        mask = np.array([m == mode_name for m in modes])
        ax.fill_between(timestamps, level, where=mask, step="post",
                        color=mode_colors[mode_name], alpha=0.4)

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["SURVIVAL", "BALANCED", "HIGH QoS"])
    ax.set_xlabel("Time (s)")
    ax.set_title("Figure 12: Scheduling Mode vs Time")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def _plot_battery_power_comparison(fixed_dfs, adapt_df, save_path):
    """Figure 13: Battery Power vs Time (Fixed vs Adaptive)"""
    fig, ax = plt.subplots(figsize=(14, 4))

    colors = {"HIGH_QoS": "#e07070", "BALANCED": "#e0a040", "SURVIVAL": "#40a070"}
    for mode_name, color in colors.items():
        df = fixed_dfs[mode_name]
        ax.step(df["timestamp_s"], df["battery_power_W"], where="post",
                color=color, linewidth=0.6, alpha=0.5, label=f"Fixed {mode_name}")

    ax.step(adapt_df["timestamp_s"], adapt_df["battery_power"], where="post",
            color="#2070a0", linewidth=1.0, label="Adaptive")

    ax.set_xlabel("Time (s)"); ax.set_ylabel("Battery Power (W)")
    ax.set_title("Figure 13: Battery Power vs Time — Fixed vs Adaptive")
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def _plot_energy_comparison(fixed_dfs, adapt_df, save_path):
    """Figure 14: Energy Remaining vs Time"""
    fig, ax = plt.subplots(figsize=(14, 4))

    colors = {"HIGH_QoS": "#e07070", "BALANCED": "#e0a040", "SURVIVAL": "#40a070"}
    for mode_name, color in colors.items():
        df = fixed_dfs[mode_name]
        e_total = df["energy_remaining_Wh"].iloc[0]
        ax.step(df["timestamp_s"], df["energy_remaining_Wh"], where="post",
                color=color, linewidth=0.8, alpha=0.5, label=f"Fixed {mode_name}")

    ax.step(adapt_df["timestamp_s"], adapt_df["energy_remaining"], where="post",
            color="#2070a0", linewidth=1.2, label="Adaptive")

    ax.set_xlabel("Time (s)"); ax.set_ylabel("Energy Remaining (Wh)")
    ax.set_title("Figure 14: Energy Remaining vs Time — Fixed vs Adaptive")
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def _plot_runtime_prediction(adapt_df, save_path):
    """Figure 15: Actual vs Predicted Remaining Runtime"""
    fig, ax = plt.subplots(figsize=(14, 4))

    ts = adapt_df["timestamp_s"]
    t_act = adapt_df["actual_remaining_runtime"]
    t_pred = adapt_df["predicted_remaining_runtime"]

    ax.plot(ts, t_act, color="#333", linewidth=1.5, label="T_actual")
    ax.step(ts, t_pred, where="post", color="#2070a0", linewidth=0.8, alpha=0.7, label="T_hat_C")

    ax.set_xlabel("Time (s)"); ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 15: Actual vs Predicted Remaining Runtime (Adaptive)")
    ax.grid(True, alpha=0.3); ax.legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def _plot_runtime_comparison(summary_df, save_path):
    """Figure 16: Fixed vs Adaptive Actual Runtime"""
    fig, ax = plt.subplots(figsize=(8, 5))

    strategies = summary_df["strategy"].tolist()
    runtimes = summary_df["runtime_h"].tolist()

    colors = ["#e07070", "#e0a040", "#40a070", "#2070a0"]
    bars = ax.bar(strategies, runtimes, color=colors[:len(strategies)], alpha=0.7)

    for bar, rt in zip(bars, runtimes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"{rt:.2f} h", ha="center", va="bottom", fontsize=10)

    ax.set_ylabel("Runtime (h)")
    ax.set_title("Figure 16: Fixed vs Adaptive Actual Runtime")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def _plot_runtime_qos_tradeoff(summary_df, sens_df, save_path):
    """Figure 17: Runtime vs QoS Trade-off"""
    fig, ax = plt.subplots(figsize=(8, 6))

    # Main strategies
    strategies = ["Fixed HIGH_QoS", "Fixed BALANCED", "Fixed SURVIVAL", "Adaptive"]
    runtimes = summary_df["runtime_h"].tolist()
    qos_vals = summary_df["composite_qos"].tolist()

    for i, (rt, q) in enumerate(zip(runtimes, qos_vals)):
        color = ["#e07070", "#e0a040", "#40a070", "#2070a0"][i]
        marker = "o" if i < 3 else "s"
        ax.scatter(rt, q, color=color, s=150, marker=marker, zorder=5)
        ax.annotate(strategies[i], (rt, q), textcoords="offset points",
                    xytext=(10, 5), fontsize=9)

    # Sensitivity analysis points
    if sens_df is not None and len(sens_df) > 0:
        ax.scatter(sens_df["runtime_h"], sens_df["composite_qos"],
                   color="#808080", s=50, alpha=0.5, label="Sensitivity points")

    ax.set_xlabel("Runtime (h)")
    ax.set_ylabel("Composite QoS")
    ax.set_title("Figure 17: Runtime vs QoS Trade-off")
    ax.grid(True, alpha=0.3)
    if sens_df is not None and len(sens_df) > 0:
        ax.legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


if __name__ == "__main__":
    main()
