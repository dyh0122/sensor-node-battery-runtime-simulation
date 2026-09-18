"""Rebuild the 17 manuscript figures with explicit observation limits.

Run from the repository root: python rebuild_reviewed_figures.py
The model is illustrative; the OCV table and hardware currents require validation.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from simulation.config import (
    BATTERY_Q_NOMINAL_AH, BATTERY_R0, I_SLEEP, OCV_SOC_POINTS,
    T_S_ACTIVE, T_TX_ACTIVE, V_TERMINAL_CUTOFF,
)

OUT = Path("outputs/figures")
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.facecolor": "white"})
COL = {"High QoS": "#1261a0", "Balanced": "#c88719",
       "Survival": "#27805c", "Adaptive": "#9b4aa3"}
SOC_POINTS = np.array(OCV_SOC_POINTS, dtype=float)
SOC_GRID = np.linspace(0, 1, 10001)
OCV_GRID = np.interp(SOC_GRID, SOC_POINTS[:, 0], SOC_POINTS[:, 1])
ENERGY_GRID = np.r_[0, np.cumsum((OCV_GRID[1:] + OCV_GRID[:-1]) / 2 *
                                      np.diff(SOC_GRID) * BATTERY_Q_NOMINAL_AH)]


def finish(fig, ax, number, name, xlabel, ylabel, note=None, legend=True):
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.grid(alpha=.2)
    if legend:
        ax.legend(frameon=False, fontsize=9)
    if note:
        fig.text(.1, .025, note, fontsize=8, color="#555555")
        fig.subplots_adjust(bottom=.23)
    else:
        fig.tight_layout()
    fig.savefig(OUT / f"fig{number}_{name}.png", dpi=180)
    plt.close(fig)


def battery_from_current(current):
    soc = np.clip(1 - np.cumsum(current) / (3600 * BATTERY_Q_NOMINAL_AH), 0, 1)
    ocv = np.interp(soc, SOC_POINTS[:, 0], SOC_POINTS[:, 1])
    voltage = ocv - current * BATTERY_R0
    power = voltage * current
    energy = np.interp(soc, SOC_GRID, ENERGY_GRID)
    return {"soc": soc, "ocv": ocv, "voltage": voltage,
            "power": power, "energy": energy,
            "cutoff": np.flatnonzero((voltage <= V_TERMINAL_CUTOFF) | (soc <= 0))}


def part_one():
    load = pd.read_csv("outputs/node_load_simulation.csv")
    batt = pd.read_csv("outputs/battery_simulation.csv")
    zoom = load.timestamp_s < 120
    time = load.loc[zoom, "timestamp_s"].to_numpy()
    states = load.loc[zoom, "node_state"].map({"SLEEP": 0, "SAMPLING": 1, "LORA_TX": 2})
    fig, ax = plt.subplots(figsize=(10, 3.4))
    ax.step(time, states, where="post", color=COL["High QoS"])
    ax.set_yticks([0, 1, 2], ["Sleep", "Sampling", "LoRa TX"])
    ax.set_ylim(-.2, 2.25)
    finish(fig, ax, 1, "state_timeline", "Time (s)", "Node state",
           "First 120 s of the 600 s synthetic load trace.", False)

    for n, name, column, scale, ylabel in [
        (2, "current_consumption", "current_load_A", 1000, "Current (mA)"),
        (3, "load_power", "power_load_W", 1000, "Nominal bus power (mW)"),
    ]:
        fig, ax = plt.subplots(figsize=(10, 3.4))
        ax.step(time, load.loc[zoom, column].to_numpy() * scale,
                where="post", color=COL["High QoS"])
        ax.set_xlim(0, 120)
        finish(fig, ax, n, name, "Time (s)", ylabel,
               "First 120 s; fixed 3.6 V bus is used for Figure 3.", False)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(SOC_GRID * 100, OCV_GRID, color=COL["High QoS"], label="Linear interpolation")
    ax.scatter(SOC_POINTS[:, 0] * 100, SOC_POINTS[:, 1], s=16, color="#cc5b49",
               label="Configured points")
    finish(fig, ax, 4, "ocv_soc", "State of charge (%)", "Open-circuit voltage (V)",
           "Illustrative configured OCV table; raw cell measurements are not present in this repository.")

    t = batt.timestamp_s.to_numpy() / 60
    fig, (ax, detail) = plt.subplots(2, 1, figsize=(10, 5), sharex=True,
                                      gridspec_kw={"height_ratios": [1, 1.4]})
    for panel in (ax, detail):
        panel.plot(t, batt.battery_ocv_V, color="#888888", label="Open-circuit voltage")
        panel.plot(t, batt.battery_terminal_voltage_V, color=COL["High QoS"],
                   label="Terminal voltage")
        panel.grid(alpha=.2)
    ax.axhline(V_TERMINAL_CUTOFF, color="#c64242", linestyle="--", label="2.5 V cutoff")
    ax.set_ylim(2.4, 4.25)
    ax.set_ylabel("Voltage (V)")
    ax.legend(frameon=False, fontsize=9, ncol=3, loc="lower right")
    detail.set_ylim(4.194, 4.202)
    detail.set(xlabel="Time (min)", ylabel="Voltage (V), detail")
    fig.text(.1, .018, "Lower panel magnifies the pulses; SOC changes by less than 0.02% in 10 min.",
             fontsize=8, color="#555555")
    fig.subplots_adjust(hspace=.12, bottom=.16)
    fig.savefig(OUT / "fig5_battery_voltage.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.step(t, batt.battery_power_W * 1000, where="post", color=COL["Adaptive"])
    finish(fig, ax, 6, "battery_power", "Time (min)", "Terminal battery power (mW)",
           "Pulse power = terminal voltage × battery current; first 10 min only.", False)

    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(t, batt.energy_remaining_Wh * 1000, color=COL["Survival"],
            label="SOC-scaled nominal energy")
    ax.set_ylim(batt.energy_remaining_Wh.min() * 1000 - .15,
                batt.energy_remaining_Wh.max() * 1000 + .15)
    finish(fig, ax, 7, "energy_remaining", "Time (min)", "Nominal remaining energy (mWh)",
           "Magnified y-axis; this is a SOC-based estimate, not measured deliverable energy.")


def predictor_figures():
    # The original 10 h run ends just before cutoff and treated that horizon as failure.
    # Extend the same synthetic 30 s load until an actual simulated cutoff appears.
    t = np.arange(0, 39000, dtype=float)
    phase = t % 30
    current = np.where(phase < 20, I_SLEEP, np.where(phase < 28, .5, 1.0))
    b = battery_from_current(current)
    if not len(b["cutoff"]):
        raise RuntimeError("Predictor evaluation did not reach a simulated cutoff")
    stop = int(b["cutoff"][0])
    t = t[:stop + 1]
    current = current[:stop + 1]
    b = {k: (v[:stop + 1] if k != "cutoff" else v) for k, v in b.items()}
    actual = (stop - t) / 3600
    positive_power = np.maximum(b["power"], 1e-9)
    a = b["energy"] / positive_power
    b_preds = {}
    for window in [10, 30, 60, 120, 300]:
        avg = pd.Series(b["power"]).rolling(window, min_periods=1).mean().to_numpy()
        b_preds[window] = b["energy"] / np.maximum(avg, 1e-9)
    # Match the 20/8/2 s state fractions and currents actually used here.
    model_current = (20 * I_SLEEP + 8 * .5 + 2 * 1.0) / 30
    c = b["energy"] / (3.6 * model_current)
    t_h = t / 3600

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_h, actual, color="#222222", label="Simulated actual")
    sample = np.flatnonzero(np.isin(phase[:stop + 1], [0, 20, 28]))
    ax.plot(t_h[sample], a[sample], ".", ms=2, alpha=.3, color="#bb5545",
            label="A: instantaneous power (three states per cycle)")
    ax.set_yscale("log")
    ax.set_ylim(.005, 1e6)
    finish(fig, ax, 8, "predictor_a", "Elapsed time (h)", "Remaining time estimate (h, log scale)",
           "Log scale reveals large sleep-state estimates without clipping them.")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_h, actual, color="#222222", lw=2, label="Simulated actual")
    after_warmup = t >= 30
    for w, color in [(30, COL["High QoS"]), (60, COL["Balanced"]),
                     (300, COL["Survival"])]:
        ax.plot(t_h[after_warmup][::10], b_preds[w][after_warmup][::10], color=color, alpha=.7, lw=1,
                label=f"B: {w} s window")
    ax.set_ylim(0, 15)
    finish(fig, ax, 9, "predictor_b", "Elapsed time (h)", "Remaining time (h)",
           "Complete-cycle windows shown after 30 s warm-up; 10 s estimates exceed this scale during sleep.")

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(actual[::60], c[::60], s=9, alpha=.5, color=COL["High QoS"])
    lim = max(actual.max(), c.max()) * 1.05
    ax.plot([0, lim], [0, lim], "--", color="#666666", label="Perfect estimate")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim); ax.set_aspect("equal")
    finish(fig, ax, 10, "predictor_c", "Simulated actual (h)", "Predictor C estimate (h)",
           "Predictor C uses the same 20/8/2 s duty cycle and currents as the load.")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_h, actual, color="#222222", lw=2, label="Simulated actual")
    ax.plot(t_h[::10], b_preds[30][::10], color=COL["Balanced"], alpha=.7,
            label="B: 30 s rolling power")
    ax.plot(t_h, c, color=COL["High QoS"], label="C: matched state model")
    ax.set_ylim(0, 15)
    finish(fig, ax, 11, "predictor_comparison", "Elapsed time (h)", "Remaining time (h)",
           "Predictor A is shown separately on a logarithmic scale in Figure 8.")
    valid = (t >= 30) & (t < stop)
    pd.DataFrame({"method": ["B (30 s)", "C (matched)"],
                  "MAE_h_after_30s_warmup": [np.mean(np.abs(b_preds[30][valid] - actual[valid])),
                                             np.mean(np.abs(c[valid] - actual[valid]))],
                  "cutoff_h": stop / 3600}).to_csv("outputs/reviewed_predictor_metrics.csv", index=False)


def mode_current(t_s, t_tx, duration=144000):
    t = np.arange(duration)
    state = np.where((t % t_tx) < T_TX_ACTIVE, 2,
                     np.where((t % t_s) < T_S_ACTIVE, 1, 0))
    current = np.select([state == 2, state == 1], [.2, .05], default=I_SLEEP)
    return state, current


def scheduling_figures():
    duration = 144000
    hours = np.arange(duration) / 3600
    modes = {"High QoS": (10, 60), "Balanced": (30, 180),
             "Survival": (60, 300)}
    runs = {}
    for name, (t_s, t_tx) in modes.items():
        state, current = mode_current(t_s, t_tx, duration)
        runs[name] = {**battery_from_current(current), "state": state,
                      "current": current}
    # Under the current one-way 1 h threshold, no switch occurs in 40 h.
    # Adaptive therefore follows the fixed high-QoS trace exactly.
    runs["Adaptive"] = runs["High QoS"]
    high = runs["High QoS"]
    # At 1 s resolution the nominal 0.5 s transmission occupies one full step.
    # Match Predictor C's mean power to that discrete state schedule.
    p_model = 3.6 * high["current"].mean()
    predicted_h = high["energy"] / p_model
    assert predicted_h.min() > 1.0
    assert all(len(run["cutoff"]) == 0 for run in runs.values())

    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.axhline(2, color=COL["Adaptive"], lw=5)
    ax.set_yticks([0, 1, 2], ["Survival", "Balanced", "High QoS"])
    ax.set_ylim(-.3, 2.4); ax.set_xlim(0, 40)
    finish(fig, ax, 12, "scheduling_mode", "Elapsed time (h)", "Adaptive mode",
           f"No transition in 40 h; minimum C prediction is {predicted_h.min():.1f} h (> 1 h threshold).", False)

    fig, ax = plt.subplots(figsize=(10, 4))
    for name, run in runs.items():
        avg = pd.Series(run["power"]).rolling(900, min_periods=900).mean().to_numpy()
        ax.plot(hours[899::300], avg[899::300] * 1000, color=COL[name],
                linestyle="--" if name == "Adaptive" else "-",
                lw=2 if name == "Adaptive" else 1.4, label=name)
    finish(fig, ax, 13, "battery_power", "Elapsed time (h)", "15 min mean battery power (mW)",
           "All strategies use the same 15 µA / 50 mA / 200 mA state currents; Adaptive overlaps High QoS.")

    fig, ax = plt.subplots(figsize=(10, 4))
    for name, run in runs.items():
        ax.plot(hours[::300], run["energy"][::300], color=COL[name],
                linestyle="--" if name == "Adaptive" else "-", label=name)
    finish(fig, ax, 14, "energy_remaining", "Elapsed time (h)", "SOC-derived nominal energy (Wh)",
           "Same OCV table and battery model for every strategy; Adaptive overlaps High QoS.")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(hours[::300], predicted_h[::300], color=COL["Adaptive"],
            label="Predictor C, High QoS mode")
    ax.axhline(1, color="#bb5545", ls="--", label="High → Balanced threshold")
    finish(fig, ax, 15, "runtime_prediction", "Elapsed time (h)", "Predicted remaining time (h)",
           "No simulated cutoff within 40 h; an actual remaining-runtime curve is unavailable.")

    names = list(runs)
    soc_end = [runs[n]["soc"][-1] * 100 for n in names]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, soc_end, color=[COL[n] for n in names], alpha=.85)
    for bar, value in zip(bars, soc_end):
        ax.text(bar.get_x() + bar.get_width() / 2, value + .7,
                f"{value:.1f}%", ha="center")
    ax.set_ylim(0, 110)
    finish(fig, ax, 16, "runtime_comparison", "Strategy", "SOC after 40 h (%)",
           "All four runs are right-censored: cutoff was not reached; actual runtime is > 40 h.", False)

    fig, ax = plt.subplots(figsize=(8, 5))
    summary = []
    high_samples = np.count_nonzero(high["state"] == 1)
    high_tx = np.count_nonzero(high["state"] == 2)
    points = {}
    for name, run in runs.items():
        qos = .5 * np.count_nonzero(run["state"] == 1) / high_samples + \
              .5 * np.count_nonzero(run["state"] == 2) / high_tx
        mean_mw = run["power"].mean() * 1000
        points[name] = (mean_mw, qos)
        summary.append({"strategy": name, "observed_h": 40,
                        "cutoff_reached": False, "end_soc_pct": run["soc"][-1] * 100,
                        "mean_battery_power_mW": mean_mw, "composite_qos": qos})
    for name in ("Balanced", "Survival"):
        x, y = points[name]
        ax.scatter(x, y, color=COL[name], s=105, zorder=4)
        ax.annotate(name, (x, y), xytext=(9, 5), textcoords="offset points", fontsize=9)
    high_xy = points["High QoS"]
    adaptive_xy = points["Adaptive"]
    if np.allclose(high_xy, adaptive_xy, rtol=0, atol=1e-10):
        # Both strategies really occupy one coordinate. Draw one compound glyph
        # and one attached label; separate offset labels imply false separation.
        ax.scatter(*high_xy, color=COL["High QoS"], s=115, zorder=5)
        ax.scatter(*high_xy, facecolors="none", edgecolors=COL["Adaptive"],
                   marker="s", s=240, linewidths=2, zorder=6)
        ax.annotate("High QoS = Adaptive\n(no mode switch)", high_xy,
                    xytext=(12, -5), textcoords="offset points", va="center",
                    fontsize=9)
    else:
        for name in ("High QoS", "Adaptive"):
            x, y = points[name]
            ax.scatter(x, y, color=COL[name], s=105,
                       marker="s" if name == "Adaptive" else "o", zorder=5)
            ax.annotate(name, (x, y), xytext=(9, 5),
                        textcoords="offset points", fontsize=9)
    ax.set_xlim(left=0)
    ax.set_xlim(right=max(p[0] for p in points.values()) * 1.29)
    ax.set_ylim(0, 1.1)
    finish(fig, ax, 17, "runtime_qos_tradeoff", "Mean battery power in 40 h (mW)",
           "Composite QoS in 40 h",
           "Adaptive and High QoS coincide; runtime trade-off cannot be measured before cutoff.", False)
    pd.DataFrame(summary).to_csv("outputs/reviewed_scheduling_summary.csv", index=False)


if __name__ == "__main__":
    part_one()
    predictor_figures()
    scheduling_figures()
    print("Rebuilt 17 figures in", OUT)
