"""
====================================================================
仿真主入口 — simulation/main.py
====================================================================

本文件负责：
  Part 1 — 调用 node_model.generate_load_profile() 生成负载数据
           保存 CSV + 绘制三张图（state, current, power）

  Part 2 — 调用 battery_model.simulate_battery() 生成电池数据
           保存 CSV + 绘制四张图（OCV-SOC, voltage, power, energy）

  统计摘要 — 打印节点状态分布、平均电流/功率、电池总能量、仿真截止点

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import os

# --- 使用 Agg 后端：无 GUI 环境下也能保存图片 ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from simulation.config import (
    OUTPUT_CSV,
    OUTPUT_BATTERY_CSV,
    OUTPUT_PREDICTOR_METRICS,
    OUTPUT_FIGURES,
    T_S,
    T_TX,
    BATTERY_V_CHARGE,
    BATTERY_V_CUTOFF,
    OCV_SOC_POINTS,
    SLIDING_WINDOWS_S,
)
from simulation.node_model import generate_load_profile
from simulation.battery_model import simulate_battery
from simulation.predictor import run_all_predictors, find_dead_time, compute_t_actual


# ============================================================
# Part 1 绘图函数（节点负载模型）
# ============================================================

def plot_state_timeline(df, save_path):
    """
    绘制 Figure 1：节点状态时间线 state(t)。

    可视化方法：
      - 将三个状态映射到数值层级 (SLEEP=0, SAMPLING=1, LORA_TX=2)
      - 用 step 图展示状态跳变
      - 用 fill_between 填充颜色区分各状态

    颜色方案：
      - SLEEP:    #a0c4a0（淡绿色）
      - SAMPLING: #f0c060（淡黄色）
      - LORA_TX:  #e07070（淡红色）
    """
    state_map = {"SLEEP": 0, "SAMPLING": 1, "LORA_TX": 2}
    colors = {0: "#a0c4a0", 1: "#f0c060", 2: "#e07070"}

    fig, ax = plt.subplots(figsize=(14, 3))

    ax.step(
        df["timestamp_s"],
        df["node_state"].map(state_map),
        where="post",
        color="#333",
        linewidth=0.8,
    )
    ax.fill_between(
        df["timestamp_s"],
        df["node_state"].map(state_map),
        step="post",
        color=df["node_state"].map(state_map).map(colors),
        alpha=0.6,
    )

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["SLEEP", "SAMPLING", "LORA_TX"])
    ax.set_xlabel("Time (s)")
    ax.set_title("Figure 1: Node State Timeline — state(t)")
    ax.set_ylim(-0.3, 2.5)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_current(df, save_path):
    """
    绘制 Figure 2：电流消耗曲线 I(t)。
    """
    fig, ax = plt.subplots(figsize=(14, 3))

    ax.step(
        df["timestamp_s"],
        df["current_load_A"],
        where="post",
        color="#2070a0",
        linewidth=0.8,
    )
    ax.fill_between(
        df["timestamp_s"],
        df["current_load_A"],
        alpha=0.3,
        color="#2070a0",
        step="post",
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Current (A)")
    ax.set_title("Figure 2: Current Consumption — I(t)")
    ax.grid(True, alpha=0.3)

    handles = [
        mpatches.Patch(color="#a0c4a0", alpha=0.4, label="SLEEP"),
        mpatches.Patch(color="#f0c060", alpha=0.4, label="SAMPLING"),
        mpatches.Patch(color="#e07070", alpha=0.4, label="LORA_TX"),
    ]
    ax.legend(handles=handles, loc="upper right")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_node_power(df, save_path):
    """
    绘制 Figure 3：节点负载功率曲线 P_load(t) = V_bus × I(t)。
    """
    fig, ax = plt.subplots(figsize=(14, 3))

    ax.step(
        df["timestamp_s"],
        df["power_load_W"],
        where="post",
        color="#a040a0",
        linewidth=0.8,
    )
    ax.fill_between(
        df["timestamp_s"],
        df["power_load_W"],
        alpha=0.3,
        color="#a040a0",
        step="post",
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Power (W)")
    ax.set_title("Figure 3: Load Power — P_load(t) = V_bus × I(t)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


# ============================================================
# Part 2 绘图函数（电池模型）
# ============================================================

def plot_ocv_soc(save_path):
    """
    绘制 Figure 4（Part 2-Fig1）：OCV-SOC 曲线。

    展示 CALCE INR18650-20R 25°C 的 OCV-SOC 关系。
    - 散点：原始数据点
    - 连线：线性插值曲线
    """
    soc_values = [p[0] for p in OCV_SOC_POINTS]
    v_ocv_values = [p[1] for p in OCV_SOC_POINTS]

    # 生成平滑插值曲线
    soc_fine = np.linspace(0, 1, 500)
    from scipy.interpolate import interp1d
    interp = interp1d(soc_values, v_ocv_values, kind="linear")
    v_ocv_fine = interp(soc_fine)

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(soc_fine, v_ocv_fine, color="#2070a0", linewidth=1.5, label="Interpolation")
    ax.scatter(soc_values, v_ocv_values, color="#e07070", s=30, zorder=5, label="Data points")

    ax.set_xlabel("SOC (State of Charge)")
    ax.set_ylabel("OCV (V)")
    ax.set_title("Figure 4: OCV-SOC Curve — Samsung INR18650-20R (25°C, CALCE)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(2.8, 4.3)
    ax.grid(True, alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_battery_voltage(df, save_path):
    """
    绘制 Figure 5（Part 2-Fig2）：电池电压随时间变化。

    包含两条线：
      - V_ocv(SOC)：开路电压（虚线）
      - V_terminal：终端电压（实线，含内阻压降）
      - 水平红线：2.5 V 截止线
    """
    fig, ax = plt.subplots(figsize=(14, 3))

    ax.plot(
        df["timestamp_s"],
        df["battery_ocv_V"],
        "--",
        color="#80a0c0",
        linewidth=0.8,
        label="V_ocv(SOC)",
    )
    ax.step(
        df["timestamp_s"],
        df["battery_terminal_voltage_V"],
        where="post",
        color="#2070a0",
        linewidth=0.8,
        label="V_terminal",
    )

    # 截止电压线
    ax.axhline(y=BATTERY_V_CUTOFF, color="#e04040", linewidth=1.0, linestyle="--", label="Cutoff (2.5 V)")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.set_title("Figure 5: Battery Voltage vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_battery_power(df, save_path):
    """
    绘制 Figure 6（Part 2-Fig3）：电池功率随时间变化。

    P_batt(t) = V_terminal(t) × I_batt(t)
    注意与 Part 1 的 P_load(t) 不同：
      - P_load 使用固定 V_bus = 3.7V
      - P_batt 使用动态 V_terminal(SOC)
    """
    fig, ax = plt.subplots(figsize=(14, 3))

    ax.step(
        df["timestamp_s"],
        df["battery_power_W"],
        where="post",
        color="#a040a0",
        linewidth=0.8,
    )
    ax.fill_between(
        df["timestamp_s"],
        df["battery_power_W"],
        alpha=0.3,
        color="#a040a0",
        step="post",
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Power (W)")
    ax.set_title("Figure 6: Battery Power vs Time — P_batt(t) = V_terminal(t) × I_batt(t)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_energy_remaining(df, save_path):
    """
    绘制 Figure 7（Part 2-Fig4）：剩余能量随时间变化。

    显示：
      - E_remaining(t)：剩余可用能量 (Wh)
      - E_used(t)：已消耗能量 (Wh)
      - E_total：初始总能量（水平参考线）
    """
    fig, ax = plt.subplots(figsize=(14, 3))

    e_total = df["energy_remaining_Wh"].iloc[0]

    ax.step(
        df["timestamp_s"],
        df["energy_remaining_Wh"],
        where="post",
        color="#20a070",
        linewidth=1.2,
        label="E_remaining",
    )
    ax.step(
        df["timestamp_s"],
        df["energy_used_Wh"],
        where="post",
        color="#e07070",
        linewidth=0.8,
        label="E_used",
    )
    ax.axhline(y=e_total, color="#808080", linewidth=0.8, linestyle="--", label=f"E_total ({e_total:.2f} Wh)")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Energy (Wh)")
    ax.set_title("Figure 7: Energy Remaining vs Time")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


# ============================================================
# Part 3 绘图函数（Remaining Runtime Predictor）
# ============================================================

def plot_predictor_a(predictions, t_actual, battery_df, save_path):
    """
    绘制 Figure 8（Part 3-Fig1）：T_actual vs T_hat_A。

    展示 Predictor A（瞬时功率）的预测值与真实值的对比。
    注意 SLEEP 状态下 P ≈ 0 导致 T_hat 异常巨大的现象。
    """
    t_hat_a = predictions["A"]

    # 为了可视化效果，对 T_hat 做 clip（保留异常但限制显示范围）
    max_display = np.percentile(t_actual[t_actual > 0], 95) * 5 if np.any(t_actual > 0) else 100
    max_display = min(max_display, 1e6)  # 上限

    fig, ax = plt.subplots(figsize=(14, 4))

    ax.plot(
        battery_df["timestamp_s"],
        t_actual,
        color="#333",
        linewidth=1.5,
        label="T_actual (ground truth)",
    )
    ax.step(
        battery_df["timestamp_s"],
        np.clip(t_hat_a, 0, max_display),
        where="post",
        color="#e07070",
        linewidth=0.8,
        alpha=0.8,
        label=f"T_hat_A (instantaneous, clipped at {max_display:.0f}s)",
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 8: T_actual vs T_hat_A (Instantaneous Power Predictor)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_predictor_b(predictions, t_actual, battery_df, save_path):
    """
    绘制 Figure 9（Part 3-Fig2）：不同 sliding window 的 T_hat_B。

    每个窗口一条线，展示 window size 对预测平滑度的影响。
    """
    fig, ax = plt.subplots(figsize=(14, 4))

    ax.plot(
        battery_df["timestamp_s"],
        t_actual,
        color="#333",
        linewidth=1.5,
        label="T_actual",
    )

    colors_b = ["#2070a0", "#40a070", "#e0a040", "#a040a0", "#e07070"]
    for i, key in enumerate(predictions):
        if key.startswith("B_"):
            color = colors_b[i % len(colors_b)]
            ax.step(
                battery_df["timestamp_s"],
                predictions[key],
                where="post",
                color=color,
                linewidth=0.8,
                alpha=0.7,
                label=f"T_hat_B ({key.replace('B_', 'window=')})",
            )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 9: T_actual vs T_hat_B (Sliding Average Power, various windows)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=7)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_predictor_c_scatter(predictions, t_actual, battery_df, save_path):
    """
    绘制 Figure 10（Part 3-Fig3）：T_actual vs T_hat_C 散点对比图。

    理想情况下所有点应该在 y=x 对角线上。
    偏离对角线的程度反映预测误差。
    """
    t_hat_c = predictions["C"]

    # 只取未达到截止的行
    active = t_actual > 0

    fig, ax = plt.subplots(figsize=(6, 6))

    ax.scatter(
        t_actual[active],
        t_hat_c[active],
        alpha=0.3,
        s=10,
        color="#2070a0",
    )

    # 对角线
    max_val = max(np.max(t_actual[active]), np.max(t_hat_c[active]))
    ax.plot([0, max_val], [0, max_val], "--", color="#888", linewidth=1.0, label="Perfect prediction")

    ax.set_xlabel("T_actual (s)")
    ax.set_ylabel("T_hat_C (s)")
    ax.set_title("Figure 10: T_actual vs T_hat_C (State-Based Model)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_aspect("equal")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_predictor_comparison(predictions, t_actual, battery_df, save_path):
    """
    绘制 Figure 11（Part 3-Fig4）：A / B(best) / C 统一对比图。

    选择 B 中 MAE 最低的窗口作为 best window。
    """
    # 找到 best B window
    best_b_key = None
    best_b_mae = float("inf")
    from simulation.predictor import compute_metrics
    for key in predictions:
        if key.startswith("B_"):
            mae = compute_metrics(t_actual, predictions[key])["MAE_s"]
            if mae < best_b_mae:
                best_b_mae = mae
                best_b_key = key

    fig, ax = plt.subplots(figsize=(14, 4))

    ax.plot(
        battery_df["timestamp_s"],
        t_actual,
        color="#333",
        linewidth=1.5,
        label="T_actual",
    )
    ax.step(
        battery_df["timestamp_s"],
        predictions["A"],
        where="post",
        color="#e07070",
        linewidth=0.6,
        alpha=0.6,
        label="T_hat_A (instantaneous)",
    )
    if best_b_key:
        ax.step(
            battery_df["timestamp_s"],
            predictions[best_b_key],
            where="post",
            color="#2070a0",
            linewidth=1.0,
            label=f"T_hat_B ({best_b_key.replace('B_', 'window=')})",
        )
    ax.step(
        battery_df["timestamp_s"],
        predictions["C"],
        where="post",
        color="#40a070",
        linewidth=1.0,
        label="T_hat_C (state-based)",
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Remaining Runtime (s)")
    ax.set_title("Figure 11: Predictor Comparison — A vs B(best) vs C")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


# ============================================================
# 主函数
# ============================================================

def main():
    """
    主函数：运行 Part 1 + Part 2 仿真，生成 CSV + 所有图 + 统计摘要。

    运行方式：
        python run_simulation.py
    """
    print("=" * 60)
    print("  Sensor Node Load & Battery Simulation")
    print("=" * 60)

    # --- 确保输出目录存在 ---
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    os.makedirs(OUTPUT_FIGURES, exist_ok=True)

    # ============================================================
    # Part 1: 节点负载模型
    # ============================================================
    print("\n--- Part 1: Node Load Model ---")
    print(f"  T_S = {T_S} s, T_TX = {T_TX} s")

    load_df = generate_load_profile()
    load_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  CSV saved: {OUTPUT_CSV}  ({len(load_df)} rows)")

    fig_state = os.path.join(OUTPUT_FIGURES, "fig1_state_timeline.png")
    fig_current = os.path.join(OUTPUT_FIGURES, "fig2_current_consumption.png")
    fig_power = os.path.join(OUTPUT_FIGURES, "fig3_load_power.png")

    plot_state_timeline(load_df, fig_state)
    plot_current(load_df, fig_current)
    plot_node_power(load_df, fig_power)
    print(f"  Figures saved: fig1, fig2, fig3")

    state_counts = load_df["node_state"].value_counts()
    print(f"\n  State distribution:")
    for state, count in state_counts.items():
        pct = count / len(load_df) * 100
        print(f"    {state}: {count} steps ({pct:.1f}%)")

    avg_current = load_df["current_load_A"].mean()
    avg_power = load_df["power_load_W"].mean()
    print(f"  Average current: {avg_current*1000:.3f} mA")
    print(f"  Average power:   {avg_power*1000:.3f} mW")

    # ============================================================
    # Part 2: 电池模型
    # ============================================================
    print(f"\n--- Part 2: Battery Model ---")
    print(f"  Cell: Samsung INR18650-20R (NMC/Graphite, 2000 mAh)")
    print(f"  V_charge = {BATTERY_V_CHARGE} V, V_cutoff = {BATTERY_V_CUTOFF} V")

    battery_df = simulate_battery(load_df)

    # 保存电池 CSV
    battery_df.to_csv(OUTPUT_BATTERY_CSV, index=False)
    print(f"  CSV saved: {OUTPUT_BATTERY_CSV}  ({len(battery_df)} rows)")

    # 绘制电池相关图
    fig_ocv = os.path.join(OUTPUT_FIGURES, "fig4_ocv_soc.png")
    fig_voltage = os.path.join(OUTPUT_FIGURES, "fig5_battery_voltage.png")
    fig_batt_power = os.path.join(OUTPUT_FIGURES, "fig6_battery_power.png")
    fig_energy = os.path.join(OUTPUT_FIGURES, "fig7_energy_remaining.png")

    plot_ocv_soc(fig_ocv)
    plot_battery_voltage(battery_df, fig_voltage)
    plot_battery_power(battery_df, fig_batt_power)
    plot_energy_remaining(battery_df, fig_energy)
    print(f"  Figures saved: fig4 (OCV-SOC), fig5 (voltage), fig6 (power), fig7 (energy)")

    # 电池统计
    e_total = battery_df["energy_remaining_Wh"].iloc[0]
    e_used_final = battery_df["energy_used_Wh"].iloc[-1]
    soc_final = battery_df["battery_soc"].iloc[-1]
    v_final = battery_df["battery_terminal_voltage_V"].iloc[-1]
    cutoff_count = battery_df["cutoff_reached"].sum()

    print(f"\n  Energy summary:")
    print(f"    E_total:    {e_total:.4f} Wh")
    print(f"    E_used:     {e_used_final:.4f} Wh")
    print(f"    E_remaining:{e_total - e_used_final:.4f} Wh (by SOC: {soc_final * e_total:.4f} Wh)")
    print(f"    SOC final:  {soc_final*100:.2f}%")
    print(f"    V_terminal final: {v_final:.4f} V")
    print(f"    Cutoff reached: {cutoff_count} steps")

    # 查找截止点
    cutoff_idx = battery_df["cutoff_reached"].idxmax() if cutoff_count > 0 else None
    if cutoff_idx is not None:
        cutoff_row = battery_df.loc[cutoff_idx]
        print(f"    Cutoff at t = {cutoff_row['timestamp_s']} s")

    # ============================================================
    # Part 3: Remaining Runtime Predictor
    # ============================================================
    print(f"\n--- Part 3: Remaining Runtime Predictor ---")

    predictions, metrics_df = run_all_predictors(battery_df, t_s=T_S, t_tx=T_TX)
    t_dead = find_dead_time(battery_df)
    t_actual = compute_t_actual(battery_df, t_dead)

    print(f"  t_dead = {t_dead:.1f} s")
    print(f"  T_actual(0) = {t_actual[0]:.1f} s")

    # 保存指标 CSV
    metrics_df.to_csv(OUTPUT_PREDICTOR_METRICS, index=False)
    print(f"  Metrics saved: {OUTPUT_PREDICTOR_METRICS}")

    # 打印指标
    print(f"\n  Predictor Metrics:")
    for _, row in metrics_df.iterrows():
        pred = row["predictor"]
        window = row["window_s"]
        w_str = f" ({int(window)}s)" if pred == "B" else ""
        print(f"    {pred}{w_str}:  MAE={row['MAE_s']:.1f}s  RMSE={row['RMSE_s']:.1f}s  "
              f"RelErr={row['relative_error']:.4f}  OverMean={row['overestimation_mean_s']:.1f}s  "
              f"OverRate={row['overestimation_rate']:.2%}")

    # 绘制 Predictor 图
    fig_a = os.path.join(OUTPUT_FIGURES, "fig8_predictor_a.png")
    fig_b = os.path.join(OUTPUT_FIGURES, "fig9_predictor_b.png")
    fig_c = os.path.join(OUTPUT_FIGURES, "fig10_predictor_c.png")
    fig_comparison = os.path.join(OUTPUT_FIGURES, "fig11_predictor_comparison.png")

    plot_predictor_a(predictions, t_actual, battery_df, fig_a)
    plot_predictor_b(predictions, t_actual, battery_df, fig_b)
    plot_predictor_c_scatter(predictions, t_actual, battery_df, fig_c)
    plot_predictor_comparison(predictions, t_actual, battery_df, fig_comparison)
    print(f"\n  Figures saved: fig8 (A), fig9 (B), fig10 (C), fig11 (comparison)")


if __name__ == "__main__":
    main()
