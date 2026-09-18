"""
====================================================================
自适应能量调度器 — simulation/scheduler.py
====================================================================

本文件实现 Part 4 — Prediction-Driven Adaptive Energy Scheduling。

核心思想：
  利用 Remaining Runtime Prediction (Predictor C) 的预测值，
  在三个 QoS 模式之间动态切换：

    High QoS   →  T_s=10s, T_tx=60s   （最佳数据质量）
    Balanced   →  T_s=30s, T_tx=180s  （折中）
    Survival   →  T_s=60s, T_tx=300s  （最低功耗）

切换规则（rule-based，无 ML）：
  1. 当 predicted_remaining < threshold 时，降级到更低功耗模式
  2. 使用 hysteresis / minimum dwell time 防止频繁切换
  3. 所有阈值集中在 config.py

QoS 定义：
  - Sampling QoS: 实际 sample 数 / High QoS reference sample 数
  - Communication QoS: 实际 tx 数 / High QoS reference tx 数
  - Composite QoS: w_sample * QoS_sampling + w_tx * QoS_tx

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from simulation.config import (
    SCHEDULING_MODES,                # 模式定义 {"HIGH_QoS": (T_s, T_tx), ...}
    ADAPT_THRESHOLD_HIGH_TO_BALANCED,  # High → Balanced 阈值
    ADAPT_THRESHOLD_BALANCED_TO_SURVIVAL,  # Balanced → Survival 阈值
    ADAPT_MIN_DWELL_TIME_S,          # 最小驻留时间
    QOS_W_SAMPLE,                    # Sampling QoS 权重
    QOS_W_TX,                        # Communication QoS 权重
    T_S_ACTIVE,                      # 单次采样持续时长
    T_TX_ACTIVE,                     # 单次 TX 持续时长
    I_SLEEP,                         # SLEEP 电流
    I_SAMPLING,                      # SAMPLING 电流
    I_TX,                            # LORA_TX 电流
    BATTERY_V_NOMINAL,               # 标称电压
)
from simulation.predictor import (
    compute_expected_average_power,
    compute_t_actual,
    find_dead_time,
)


def get_mode_params(mode_name: str) -> tuple[float, float]:
    """
    获取指定模式的调度参数。

    参数：
        mode_name: "HIGH_QoS", "BALANCED", 或 "SURVIVAL"

    返回：
        (T_s, T_tx) 元组
    """
    params = SCHEDULING_MODES[mode_name]
    return params[0], params[1]


def decide_next_mode(
    predicted_remaining: float,
    current_mode: str,
    time_since_last_switch: float,
    threshold_high_to_balanced: float = ADAPT_THRESHOLD_HIGH_TO_BALANCED,
    threshold_balanced_to_survival: float = ADAPT_THRESHOLD_BALANCED_TO_SURVIVAL,
    min_dwell_time: float = ADAPT_MIN_DWELL_TIME_S,
) -> str:
    """
    决定下一个调度模式。

    规则（rule-based，无 ML）：
      1. 如果 predicted_remaining < threshold_balanced_to_survival
         且 current_mode 不是 SURVIVAL
         且已驻留足够久 → 切换到 SURVIVAL

      2. 如果 predicted_remaining < threshold_high_to_balanced
         且 current_mode 是 HIGH_QoS
         且已驻留足够久 → 切换到 BALANCED

      3. 如果 predicted_remaining 回升（不适用，因为电池只放电）
         本系统只降级不升级（一旦电量减少，不会回到高 QoS）

      4. 否则保持当前模式

    Hysteresis 实现：
      通过 min_dwell_time 强制在切换后等待一段时间才能再次切换。
      这防止了在阈值附近的频繁震荡。

    参数：
        predicted_remaining:      预测剩余运行时间 (s)
        current_mode:             当前模式名
        time_since_last_switch:   距上次切换的时间 (s)
        threshold_high_to_balanced:  High → Balanced 阈值
        threshold_balanced_to_survival: Balanced → Survival 阈值
        min_dwell_time:           最小驻留时间 (s)

    返回：
        next_mode: 下一个模式名
    """
    # 如果驻留时间不足，保持当前模式
    if time_since_last_switch < min_dwell_time:
        return current_mode

    # 降级决策
    if predicted_remaining < threshold_balanced_to_survival:
        return "SURVIVAL"
    elif predicted_remaining < threshold_high_to_balanced:
        if current_mode == "HIGH_QoS":
            return "BALANCED"

    # 否则保持当前模式
    return current_mode


def build_schedule_adaptive(
    duration_steps: int,
    dt: float,
    mode_sequence: list[tuple[int, str, float, float]],
    t_s_active: float = T_S_ACTIVE,
    t_tx_active: float = T_TX_ACTIVE,
    state_priority: list[str] | None = None,
) -> tuple[list[str], list[tuple[int, str]]]:
    """
    根据模式序列构建状态调度。

    参数：
        duration_steps:   总步数
        dt:               时间步长 (s)
        mode_sequence:    [(start_step, mode_name, T_s, T_tx), ...]
                         按 start_step 排序
        t_s_active:       单次采样持续时长
        t_tx_active:      单次 TX 持续时长
        state_priority:   状态优先级

    返回：
        (states, mode_log)
        states:     状态列表 ["SLEEP", "SAMPLING", "LORA_TX", ...]
        mode_log:   [(step, mode_name), ...] 模式切换日志
    """
    from simulation.node_model import _build_schedule
    if state_priority is None:
        state_priority = ["LORA_TX", "SAMPLING", "SLEEP"]

    states = []
    mode_log = []
    mode_idx = 0

    for step in range(duration_steps):
        # 检查是否进入新模式
        if mode_idx < len(mode_sequence) and step >= mode_sequence[mode_idx][0]:
            start_step, mode_name, t_s, t_tx = mode_sequence[mode_idx]
            mode_log.append((step, mode_name))
            mode_idx += 1

        # 获取当前模式
        if mode_idx > 0:
            _, mode_name, t_s, t_tx = mode_sequence[mode_idx - 1]
        else:
            # 默认从 High QoS 开始
            mode_name, t_s, t_tx = "HIGH_QoS", *get_mode_params("HIGH_QoS")

        # 计算当前步在模式内的相对时间
        # 找到当前模式的起始步
        if mode_idx > 0:
            mode_start_step = mode_sequence[mode_idx - 1][0]
        else:
            mode_start_step = 0

        t_in_mode = (step - mode_start_step) * dt

        # 在当前模式下判断状态
        time_since_last_sample = t_in_mode % t_s
        time_since_last_tx = t_in_mode % t_tx

        active_states = {"SLEEP"}
        if time_since_last_sample < t_s_active:
            active_states.add("SAMPLING")
        if time_since_last_tx < t_tx_active:
            active_states.add("LORA_TX")

        for prio_state in state_priority:
            if prio_state in active_states:
                states.append(prio_state)
                break
        else:
            states.append("SLEEP")

    return states, mode_log


def simulate_adaptive(
    battery_df: pd.DataFrame,
    predictor_fn,  # 预测函数，接收 (battery_df_subset) → predicted_remaining
    initial_mode: str = "HIGH_QoS",
    check_interval: float = 60.0,  # 每 60s 检查一次调度决策
    threshold_high_to_balanced: float = ADAPT_THRESHOLD_HIGH_TO_BALANCED,
    threshold_balanced_to_survival: float = ADAPT_THRESHOLD_BALANCED_TO_SURVIVAL,
    min_dwell_time: float = ADAPT_MIN_DWELL_TIME_S,
    t_s_active: float = T_S_ACTIVE,
    t_tx_active: float = T_TX_ACTIVE,
    i_sleep: float = I_SLEEP,
    i_sampling: float = I_SAMPLING,
    i_tx: float = I_TX,
    current_fn=None,  # 可选：根据模式返回 (i_sleep, i_sampling, i_tx) 的函数
    v_bus: float = BATTERY_V_NOMINAL,
    state_priority: list[str] | None = None,
    dt: float = 1.0,
    fixed_high_runtime: float | None = None,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """
    完整的自适应调度仿真。

    这是 Part 4 的核心函数。

    流程：
      1. 初始化：从 HIGH_QoS 模式开始
      2. 每 check_interval 秒：
         a. 使用 Predictor C 计算 predicted_remaining
         b. 调用 decide_next_mode() 决定下一个模式
         c. 如果模式改变，记录切换事件
      3. 根据当前模式的 T_s / T_tx 生成 state(t)
      4. 根据 state(t) 计算电流和功率
      5. 更新电池 SOC 和能量
      6. 重复直到电池耗尽

    参数：
        battery_df:         电池仿真 DataFrame（用于 predictor 输入）
        predictor_fn:       预测函数，接收 (battery_df, current_T_s, current_T_tx)
                           返回 predicted_remaining (s)
        initial_mode:       初始模式
        check_interval:     调度决策检查间隔 (s)
        threshold_high_to_balanced:  High → Balanced 阈值
        threshold_balanced_to_survival: Balanced → Survival 阈值
        min_dwell_time:     最小驻留时间 (s)
        t_s_active:         单次采样持续时长
        t_tx_active:        单次 TX 持续时长
        i_sleep:            SLEEP 电流
        i_sampling:         SAMPLING 电流
        i_tx:               LORA_TX 电流
        v_bus:              总线电压
        state_priority:     状态优先级
        dt:                 时间步长
        fixed_high_runtime: Fixed High QoS 的运行时间（用于 QoS reference）

    返回：
        (adaptive_df, summary_dict, mode_switch_log_df)
    """
    if state_priority is None:
        state_priority = ["LORA_TX", "SAMPLING", "SLEEP"]

    current_mode = initial_mode
    current_t_s, current_t_tx = get_mode_params(current_mode)

    timestamps = battery_df["timestamp_s"].values
    n = len(battery_df)

    # 输出数组
    modes = []
    t_s_arr = []
    t_tx_arr = []
    states_arr = []
    v_batt_arr = []
    i_batt_arr = []
    p_batt_arr = []
    soc_arr = []
    e_remain_arr = []
    t_pred_arr = []
    t_act_arr = []
    sampling_events = []
    tx_events = []

    # 调度决策状态
    last_switch_step = 0
    last_switch_time = 0.0

    # 统计
    sample_count = 0
    tx_count = 0
    mode_switches = []  # [(time, from_mode, to_mode), ...]

    # 模式切换日志
    mode_log = [(0, initial_mode)]

    # 逐步骤仿真
    from simulation.battery_model import build_ocv_interpolator, soc_to_ocv, compute_terminal_voltage
    from simulation.config import (
        BATTERY_Q_NOMINAL_AH, BATTERY_R0, BATTERY_INITIAL_SOC,
        OCV_SOC_POINTS, V_TERMINAL_CUTOFF, BATTERY_V_CHARGE,
    )

    ocv_interp = build_ocv_interpolator(OCV_SOC_POINTS)
    soc = BATTERY_INITIAL_SOC
    e_total_Wh = trapezoid(ocv_interp(np.linspace(0, 1, 1000)), np.linspace(0, 1, 1000)) * BATTERY_Q_NOMINAL_AH
    e_used_wh = 0.0

    cutoff_reached = False
    t_dead = None

    # 预先计算 Fixed High QoS 的 reference
    if fixed_high_runtime is None:
        # 如果没有提供，使用一个估计值
        p_high = compute_expected_average_power(
            t_s=10.0, t_tx=60.0,
            t_s_active=t_s_active, t_tx_active=t_tx_active,
            i_sleep=i_sleep, i_sampling=i_sampling, i_tx=i_tx, v_bus=v_bus,
        )
        fixed_high_runtime = e_total_Wh / p_high * 3600.0 if p_high > 0 else 36000.0

    # High QoS reference counts
    high_t_s, high_t_tx = get_mode_params("HIGH_QoS")
    ref_samples = int(fixed_high_runtime / high_t_s)
    ref_tx = int(fixed_high_runtime / high_t_tx)

    for step in range(n):
        t = timestamps[step]

        if cutoff_reached:
            modes.append(current_mode)
            t_s_arr.append(current_t_s)
            t_tx_arr.append(current_t_tx)
            states_arr.append("SLEEP")
            v_batt_arr.append(battery_df["battery_terminal_voltage_V"].iloc[-1])
            i_batt_arr.append(0.0)
            p_batt_arr.append(0.0)
            soc_arr.append(soc)
            e_remain_arr.append(soc * e_total_Wh)
            t_pred_arr.append(0.0)
            t_act_arr.append(0.0)
            sampling_events.append(False)
            tx_events.append(False)
            continue

        # --- 调度决策 ---
        time_since_switch = t - last_switch_time

        # 每 check_interval 检查一次
        if (step % int(check_interval / dt) == 0 or step == 0) and not cutoff_reached:
            # 使用 Predictor C 计算 predicted_remaining
            predicted_remaining = predictor_fn(battery_df.iloc[:step+1], current_t_s, current_t_tx)
            t_actual = fixed_high_runtime - t  # 简化 ground truth
            if t_actual < 0:
                t_actual = 0.0

            # 决定下一个模式
            next_mode = decide_next_mode(
                predicted_remaining,
                current_mode,
                time_since_switch,
                threshold_high_to_balanced,
                threshold_balanced_to_survival,
                min_dwell_time,
            )

            if next_mode != current_mode:
                mode_switches.append((t, current_mode, next_mode))
                mode_log.append((step, next_mode))
                current_mode = next_mode
                current_t_s, current_t_tx = get_mode_params(current_mode)
                last_switch_step = step
                last_switch_time = t

        # --- 根据当前模式生成状态 ---
        # 找到当前模式的起始时间
        if mode_log:
            mode_start_step_idx = mode_log[-1][0]
            t_in_mode = (step - mode_start_step_idx) * dt
        else:
            mode_start_step_idx = 0
            t_in_mode = step * dt

        time_since_sample = t_in_mode % current_t_s
        time_since_tx = t_in_mode % current_t_tx

        active_states = {"SLEEP"}
        if time_since_sample < t_s_active:
            active_states.add("SAMPLING")
        if time_since_tx < t_tx_active:
            active_states.add("LORA_TX")

        for prio_state in state_priority:
            if prio_state in active_states:
                current_state = prio_state
                break
        else:
            current_state = "SLEEP"

        # 记录事件
        is_sample = (current_state == "SAMPLING")
        is_tx = (current_state == "LORA_TX")
        if is_sample:
            sample_count += 1
        if is_tx:
            tx_count += 1

        # --- 电流映射 ---
        if current_fn is not None:
            # 使用自定义电流函数（根据模式动态计算）
            ci_sleep, ci_sampling, ci_tx = current_fn(current_mode, current_t_s, current_t_tx)
            current_map = {"SLEEP": ci_sleep, "SAMPLING": ci_sampling, "LORA_TX": ci_tx}
        else:
            current_map = {"SLEEP": i_sleep, "SAMPLING": i_sampling, "LORA_TX": i_tx}
        i_batt = current_map[current_state]

        # --- 电池更新 ---
        delta_soc = i_batt * dt / (3600.0 * BATTERY_Q_NOMINAL_AH)
        soc = max(0.0, min(1.0, soc - delta_soc))

        v_ocv = soc_to_ocv(soc, ocv_interp)
        v_term = compute_terminal_voltage(v_ocv, i_batt, BATTERY_R0)
        p_batt = v_term * i_batt

        e_used_wh += p_batt * dt / 3600.0
        e_remain = soc * e_total_Wh

        # --- Predictor 和 Ground Truth ---
        # 使用 Predictor C 的预测值
        t_pred = predictor_fn(battery_df.iloc[:step+1], current_t_s, current_t_tx)

        # Ground truth: 基于当前放电率的估计
        if p_batt > 0:
            t_actual_est = e_remain / p_batt * 3600.0
        else:
            t_actual_est = e_total_Wh / (compute_expected_average_power(
                t_s=current_t_s, t_tx=current_t_tx,
                t_s_active=t_s_active, t_tx_active=t_tx_active,
                i_sleep=i_sleep, i_sampling=i_sampling, i_tx=i_tx, v_bus=v_bus,
            ) * 3600.0) if compute_expected_average_power(
                t_s=current_t_s, t_tx=current_t_tx,
                t_s_active=t_s_active, t_tx_active=t_tx_active,
                i_sleep=i_sleep, i_sampling=i_sampling, i_tx=i_tx, v_bus=v_bus,
            ) > 0 else 0.0

        # --- 截止检测 ---
        if v_term <= V_TERMINAL_CUTOFF or soc <= 0.0:
            cutoff_reached = True
            t_dead = t

        # --- 记录 ---
        modes.append(current_mode)
        t_s_arr.append(current_t_s)
        t_tx_arr.append(current_t_tx)
        states_arr.append(current_state)
        v_batt_arr.append(v_term)
        i_batt_arr.append(i_batt)
        p_batt_arr.append(p_batt)
        soc_arr.append(soc)
        e_remain_arr.append(e_remain)
        t_pred_arr.append(t_pred)
        t_act_arr.append(t_actual_est)
        sampling_events.append(is_sample)
        tx_events.append(is_tx)

    # 如果没有触发 cutoff
    if t_dead is None:
        t_dead = timestamps[-1]

    # --- 组装 DataFrame ---
    adaptive_df = pd.DataFrame({
        "timestamp_s": timestamps,
        "mode": modes,
        "T_s": t_s_arr,
        "T_tx": t_tx_arr,
        "state": states_arr,
        "battery_voltage": v_batt_arr,
        "battery_current": i_batt_arr,
        "battery_power": p_batt_arr,
        "SOC": soc_arr,
        "energy_remaining": e_remain_arr,
        "predicted_remaining_runtime": t_pred_arr,
        "actual_remaining_runtime": t_act_arr,
        "sampling_event": sampling_events,
        "transmission_event": tx_events,
    })

    # --- 计算 QoS ---
    qos_sampling = sample_count / ref_samples if ref_samples > 0 else 0.0
    qos_tx = tx_count / ref_tx if ref_tx > 0 else 0.0
    qos_composite = QOS_W_SAMPLE * qos_sampling + QOS_W_TX * qos_tx

    # --- 计算 Predictor 指标 ---
    active_mask = np.array(t_act_arr) > 60.0  # RELATIVE_ERROR_MIN_T_ACTUAL
    if np.any(active_mask):
        t_act_np = np.array(t_act_arr)[active_mask]
        t_pred_np = np.array(t_pred_arr)[active_mask]
        mae = np.mean(np.abs(t_pred_np - t_act_np))
        rmse = np.sqrt(np.mean((t_pred_np - t_act_np) ** 2))
        rel_err = np.mean(np.abs(t_pred_np - t_act_np) / t_act_np)
        overest_rate = np.mean(t_pred_np > t_act_np)
    else:
        mae = rmse = rel_err = overest_rate = np.nan

    runtime_h = t_dead / 3600.0
    avg_power = np.mean([p for p in p_batt_arr if p > 0]) if any(p > 0 for p in p_batt_arr) else 0.0

    summary = {
        "runtime_h": runtime_h,
        "runtime_s": t_dead,
        "sample_count": sample_count,
        "tx_count": tx_count,
        "sampling_qos": qos_sampling,
        "communication_qos": qos_tx,
        "composite_qos": qos_composite,
        "average_power_W": avg_power,
        "MAE": mae,
        "RMSE": rmse,
        "relative_error": rel_err,
        "overestimation_rate": overest_rate,
        "mode_switches": len(mode_switches),
        "final_soc": soc,
        "cutoff_reached": cutoff_reached,
    }

    mode_log_df = pd.DataFrame(mode_log, columns=["step", "mode"])

    return adaptive_df, summary, mode_log_df


def run_fixed_baseline(
    mode_name: str,
    duration: float = 72000,
    dt: float = 1.0,
) -> tuple[pd.DataFrame, dict]:
    """
    运行 Fixed Scheduling Baseline。

    参数：
        mode_name:  "HIGH_QoS", "BALANCED", 或 "SURVIVAL"
        duration:   仿真时长 (s)，默认 72000 s = 20 h
        dt:         时间步长 (s)

    返回：
        (df, summary_dict)
    """
    t_s, t_tx = get_mode_params(mode_name)

    # 生成状态序列
    from simulation.node_model import _build_schedule
    states = _build_schedule(
        duration, dt, t_s, t_tx, T_S_ACTIVE, T_TX_ACTIVE,
        ["LORA_TX", "SAMPLING", "SLEEP"]
    )

    current_map = {"SLEEP": I_SLEEP, "SAMPLING": I_SAMPLING, "LORA_TX": I_TX}
    currents = [current_map[s] for s in states]
    timestamps = np.arange(0, duration, dt)

    load_df = pd.DataFrame({
        "timestamp_s": timestamps,
        "node_state": states,
        "sampling_interval_s": t_s,
        "transmission_interval_s": t_tx,
        "current_load_A": currents,
        "voltage_bus_V": BATTERY_V_NOMINAL,
        "power_load_W": [BATTERY_V_NOMINAL * i for i in currents],
    })

    # 电池仿真
    from simulation.battery_model import simulate_battery
    from simulation.config import (
        BATTERY_Q_NOMINAL_AH, BATTERY_R0, BATTERY_INITIAL_SOC,
        OCV_SOC_POINTS, V_TERMINAL_CUTOFF, BATTERY_V_CHARGE,
    )

    battery_df = simulate_battery(
        load_df,
        q_nominal=BATTERY_Q_NOMINAL_AH,
        r0=BATTERY_R0,
        initial_soc=BATTERY_INITIAL_SOC,
        v_cutoff=V_TERMINAL_CUTOFF,
        v_charge=BATTERY_V_CHARGE,
        ocv_points=OCV_SOC_POINTS,
    )

    # 统计
    t_dead = find_dead_time(battery_df)
    sample_count = sum(1 for s in states if s == "SAMPLING")
    tx_count = sum(1 for s in states if s == "LORA_TX")
    avg_power = np.mean([c * BATTERY_V_NOMINAL for c in currents if c > 0])
    soc_final = battery_df["battery_soc"].iloc[-1]

    summary = {
        "strategy": f"Fixed {mode_name}",
        "runtime_h": t_dead / 3600.0,
        "runtime_s": t_dead,
        "sample_count": sample_count,
        "tx_count": tx_count,
        "average_power_W": avg_power,
        "final_soc": soc_final,
        "cutoff_reached": battery_df["cutoff_reached"].sum() > 0,
    }

    return battery_df, summary
