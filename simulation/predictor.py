"""
====================================================================
剩余运行时间预测器 — simulation/predictor.py
====================================================================

本文件实现 Part 3 — Remaining Runtime Prediction，包含三个 Predictor：

  Predictor A — Instantaneous Power
      T_hat = E_remaining / P_current

  Predictor B — Sliding Average Power
      T_hat = E_remaining / P_sliding_average(window)
      测试窗口：10s, 30s, 60s, 120s, 300s

  Predictor C — State-Based Power Model
      T_hat = E_remaining / P_model(T_s, T_tx)
      基于节点状态模型的理论平均功率

以及评价体系：
  MAE, RMSE, Relative Error, Overestimation Mean, Overestimation Rate

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import numpy as np
import pandas as pd

from simulation.config import (
    RELATIVE_ERROR_MIN_T_ACTUAL,  # relative error 的最小 T_actual 阈值
    P_EPSILON,                     # 数值保护 epsilon
    SLIDING_WINDOWS_S,             # Predictor B 的滑动窗口列表
    T_S,                           # 采样间隔
    T_TX,                          # 发送间隔
    T_S_ACTIVE,                    # 单次采样持续时长
    T_TX_ACTIVE,                   # 单次 TX 持续时长
    I_SLEEP,                       # SLEEP 电流
    I_SAMPLING,                    # SAMPLING 电流
    I_TX,                          # LORA_TX 电流
    BATTERY_V_NOMINAL,             # 标称电压（用于理论功率计算）
)


def find_dead_time(battery_df: pd.DataFrame) -> float:
    """
    从电池仿真数据中找到 cutoff 时间 t_dead。

    定义：第一个 cutoff_reached == True 的时间戳。
    如果整个仿真都没有触发 cutoff，则使用最后一个时间戳 + dt。

    参数：
        battery_df: simulate_battery() 输出的 DataFrame

    返回：
        t_dead: 电池耗尽时间 (s)
    """
    cutoff_rows = battery_df[battery_df["cutoff_reached"]]
    if len(cutoff_rows) > 0:
        return cutoff_rows["timestamp_s"].iloc[0]
    else:
        # 没有触发 cutoff，使用最后一个时间步 + dt 作为估计
        return battery_df["timestamp_s"].iloc[-1] + 1.0


def compute_t_actual(battery_df: pd.DataFrame, t_dead: float) -> np.ndarray:
    """
    计算 Ground Truth：真实剩余运行时间 T_actual(t)。

    公式：
        T_actual(t) = max(t_dead - t, 0)

    当 t >= t_dead 时，T_actual = 0。

    参数：
        battery_df: 电池仿真 DataFrame
        t_dead:     电池耗尽时间 (s)

    返回：
        T_actual 数组 (s)
    """
    timestamps = battery_df["timestamp_s"].values
    return np.maximum(t_dead - timestamps, 0.0)


# ============================================================
# Predictor A — Instantaneous Power
# ============================================================

def predictor_instantaneous(battery_df: pd.DataFrame) -> np.ndarray:
    """
    Predictor A：基于瞬时功率的剩余时间预测。

    公式：
        T_hat_A(t) = E_remaining(t) / P_current(t)

    数值保护：
        当 P_current < P_EPSILON 时，使用 P_EPSILON 代替
        （防止 SLEEP 状态下 P ≈ 0 导致 T_hat → inf）

    参数：
        battery_df: 电池仿真 DataFrame，包含
                    battery_power_W, energy_remaining_Wh

    返回：
        T_hat_A 数组 (s)

    重要说明：
        这个 Predictor 在 duty-cycled sensor node 中会表现很差，
        因为：
          1. SLEEP 时 P ≈ 0 → T_hat → 极大值（看似还有很久才耗尽）
          2. LORA_TX 时 P 突增 → T_hat → 极小值（看似即将耗尽）
          3. 瞬时功率不代表平均功耗趋势

        这些"异常"不是 bug，而是 instantaneous-power predictor
        的根本缺陷。保留它们用于分析。
    """
    e_remaining = battery_df["energy_remaining_Wh"].values
    p_current = battery_df["battery_power_W"].values

    # 数值保护：防止除以接近 0 的值
    p_safe = np.maximum(p_current, P_EPSILON)

    # T_hat = E_remaining / P_current
    # E_remaining 单位：Wh, P_current 单位：W
    # Wh / W = h → 乘以 3600 得到 s
    t_hat = e_remaining / p_safe * 3600.0

    # 死亡后预测为 0
    t_dead = find_dead_time(battery_df)
    timestamps = battery_df["timestamp_s"].values
    t_hat[timestamps >= t_dead] = 0.0

    return t_hat


# ============================================================
# Predictor B — Sliding Average Power
# ============================================================

def predictor_sliding_window(
    battery_df: pd.DataFrame,
    window_s: float,
) -> np.ndarray:
    """
    Predictor B：基于滑动平均功率的剩余时间预测。

    公式：
        P_avg(t) = mean(P_batt(t - window : t))
        T_hat_B(t) = E_remaining(t) / P_avg(t)

    参数：
        battery_df:  电池仿真 DataFrame
        window_s:    滑动窗口大小 (s)

    返回：
        T_hat_B 数组 (s)

    注意：
        - 窗口越大，预测越平滑，但对变化的响应越慢
        - 窗口越小，预测越敏感，但噪声越大
        - 在仿真开始的前 window_s 秒内，使用可用数据计算均值
    """
    p_batt = battery_df["battery_power_W"].values
    e_remaining = battery_df["energy_remaining_Wh"].values
    timestamps = battery_df["timestamp_s"].values
    dt = timestamps[1] - timestamps[0] if len(timestamps) > 1 else 1.0

    window_steps = int(np.ceil(window_s / dt))
    t_dead = find_dead_time(battery_df)
    n = len(battery_df)
    t_hat = np.zeros(n)

    for k in range(n):
        if timestamps[k] >= t_dead:
            t_hat[k] = 0.0
            continue

        # 滑动窗口：取最近 window_steps 个点的功率均值
        start = max(0, k - window_steps + 1)
        p_window = p_batt[start:k + 1]
        p_avg = np.mean(p_window)

        # 数值保护
        p_safe = max(p_avg, P_EPSILON)

        # Wh / W = h → × 3600 → s
        t_hat[k] = e_remaining[k] / p_safe * 3600.0

    return t_hat


# ============================================================
# Predictor C — State-Based Power Model
# ============================================================

def compute_expected_average_power(
    t_s: float = T_S,
    t_tx: float = T_TX,
    t_s_active: float = T_S_ACTIVE,
    t_tx_active: float = T_TX_ACTIVE,
    i_sleep: float = I_SLEEP,
    i_sampling: float = I_SAMPLING,
    i_tx: float = I_TX,
    v_bus: float = BATTERY_V_NOMINAL,
) -> float:
    """
    计算理论平均功耗 P_model(T_s, T_tx)。

    基于节点状态模型的周期性分析：

    在一个足够长的时间窗口内（≥ LCM(T_S, T_TX)），
    平均功耗为各状态功耗的时间加权平均。

    公式：
        P_model = (P_sleep * t_sleep + P_sampling * t_sampling + P_tx * t_tx) / T_cycle

    其中：
        P_sleep    = V_bus * I_sleep
        P_sampling = V_bus * I_sampling
        P_tx       = V_bus * I_tx
        t_sampling = T_cycle * (T_S_ACTIVE / T_S)    # 采样占总时间的比例
        t_tx       = T_cycle * (T_TX_ACTIVE / T_TX)  # TX 占总时间的比例
        t_sleep    = T_cycle - t_sampling - t_tx     # 剩余为 SLEEP

    简化后：
        P_model = P_sleep + (P_sampling - P_sleep) * (T_S_ACTIVE / T_S)
                         + (P_tx - P_sleep) * (T_TX_ACTIVE / T_TX)

    参数（全部可选，默认取 config 值）：
        t_s:         采样间隔 (s)
        t_tx:        发送间隔 (s)
        t_s_active:  单次采样持续时长 (s)
        t_tx_active: 单次 TX 持续时长 (s)
        i_sleep:     SLEEP 电流 (A)
        i_sampling:  SAMPLING 电流 (A)
        i_tx:        LORA_TX 电流 (A)
        v_bus:       总线电压 (V)

    返回：
        P_model：理论平均功率 (W)

    重要：
        这个函数必须能够在 T_s 或 T_tx 改变后自动重新计算。
        这是为了支持下一阶段的 Adaptive Scheduler，
        当调度策略修改 T_s / T_tx 时，Predictor C 可以
        立即反映新的平均功耗。
    """
    # 各状态功率
    p_sleep = v_bus * i_sleep
    p_sampling = v_bus * i_sampling
    p_tx = v_bus * i_tx

    # 占空比
    duty_sampling = t_s_active / t_s  # 采样占总时间的比例
    duty_tx = t_tx_active / t_tx      # TX 占总时间的比例
    duty_sleep = 1.0 - duty_sampling - duty_tx  # SLEEP 占总时间的比例

    # 理论平均功率
    p_model = (
        p_sleep * duty_sleep
        + p_sampling * duty_sampling
        + p_tx * duty_tx
    )

    return p_model


def predictor_state_based(
    battery_df: pd.DataFrame,
    t_s: float = T_S,
    t_tx: float = T_TX,
) -> np.ndarray:
    """
    Predictor C：基于状态模型的剩余时间预测。

    公式：
        P_model = compute_expected_average_power(T_s, T_tx)
        T_hat_C(t) = E_remaining(t) / P_model

    参数：
        battery_df: 电池仿真 DataFrame
        t_s:        采样间隔 (s)
        t_tx:       发送间隔 (s)

    返回：
        T_hat_C 数组 (s)

    优点：
        - 不依赖瞬时功率波动
        - 能根据 T_s / T_tx 的改变自动调整
        - 适合未来 scheduling policy change
    """
    e_remaining = battery_df["energy_remaining_Wh"].values
    timestamps = battery_df["timestamp_s"].values
    t_dead = find_dead_time(battery_df)

    # 计算理论平均功率
    p_model = compute_expected_average_power(t_s=t_s, t_tx=t_tx)

    # 数值保护
    p_safe = max(p_model, P_EPSILON)

    n = len(battery_df)
    t_hat = np.zeros(n)

    for k in range(n):
        if timestamps[k] >= t_dead:
            t_hat[k] = 0.0
        else:
            # Wh / W = h → × 3600 → s
            t_hat[k] = e_remaining[k] / p_safe * 3600.0

    return t_hat


# ============================================================
# 评价体系
# ============================================================

def compute_metrics(
    t_actual: np.ndarray,
    t_hat: np.ndarray,
    min_t_actual: float = RELATIVE_ERROR_MIN_T_ACTUAL,
) -> dict:
    """
    计算单个 Predictor 的评价指标。

    指标：
        MAE:              mean absolute error (s)
        RMSE:             root mean squared error (s)
        relative_error:   mean(|T_hat - T_actual| / T_actual)，
                          仅在 T_actual > min_t_actual 时计算
        overestimation_mean: mean(max(T_hat - T_actual, 0)) (s)
        overestimation_rate: fraction(T_hat > T_actual)

    参数：
        t_actual:       Ground truth 剩余时间数组 (s)
        t_hat:          预测剩余时间数组 (s)
        min_t_actual:   计算 relative error 的最小 T_actual 阈值

    返回：
        指标字典
    """
    # 只评价未达到截止点的行
    active_mask = t_actual > 0

    if not np.any(active_mask):
        return {
            "MAE_s": np.nan,
            "RMSE_s": np.nan,
            "relative_error": np.nan,
            "overestimation_mean_s": np.nan,
            "overestimation_rate": np.nan,
        }

    t_act = t_actual[active_mask]
    t_pred = t_hat[active_mask]

    # MAE
    mae = np.mean(np.abs(t_pred - t_act))

    # RMSE
    rmse = np.sqrt(np.mean((t_pred - t_act) ** 2))

    # Relative Error（仅在 T_actual > min_t_actual 时计算）
    rel_mask = t_act > min_t_actual
    if np.any(rel_mask):
        rel_errors = np.abs(t_pred[rel_mask] - t_act[rel_mask]) / t_act[rel_mask]
        relative_error = np.mean(rel_errors)
    else:
        relative_error = np.nan

    # Overestimation Mean
    overestimation = np.maximum(t_pred - t_act, 0.0)
    overestimation_mean = np.mean(overestimation)

    # Overestimation Rate
    overestimation_rate = np.mean(t_pred > t_act)

    return {
        "MAE_s": mae,
        "RMSE_s": rmse,
        "relative_error": relative_error,
        "overestimation_mean_s": overestimation_mean,
        "overestimation_rate": overestimation_rate,
    }


# ============================================================
# 主流程：运行所有 Predictor + 评价
# ============================================================

def run_all_predictors(
    battery_df: pd.DataFrame,
    t_s: float = T_S,
    t_tx: float = T_TX,
    windows: list[float] | None = None,
) -> tuple[dict, pd.DataFrame]:
    """
    运行所有 Predictor 并生成评价表。

    参数：
        battery_df: 电池仿真 DataFrame
        t_s:        采样间隔 (s)
        t_tx:       发送间隔 (s)
        windows:    Predictor B 的滑动窗口列表，默认 SLIDING_WINDOWS_S

    返回：
        (predictions_dict, metrics_df)
        predictions_dict: {"A": t_hat_A, "B_{window}": t_hat_B, "C": t_hat_C}
        metrics_df:       评价指标 DataFrame
    """
    if windows is None:
        windows = SLIDING_WINDOWS_S

    # Ground Truth
    t_dead = find_dead_time(battery_df)
    t_actual = compute_t_actual(battery_df, t_dead)

    predictions = {}
    metrics_rows = []

    # --- Predictor A: Instantaneous ---
    t_hat_a = predictor_instantaneous(battery_df)
    predictions["A"] = t_hat_a
    metrics_a = compute_metrics(t_actual, t_hat_a)
    metrics_a["predictor"] = "A"
    metrics_a["window_s"] = np.nan
    metrics_rows.append(metrics_a)

    # --- Predictor B: Sliding Window ---
    for w in windows:
        key = f"B_{int(w)}s"
        t_hat_b = predictor_sliding_window(battery_df, window_s=w)
        predictions[key] = t_hat_b
        metrics_b = compute_metrics(t_actual, t_hat_b)
        metrics_b["predictor"] = "B"
        metrics_b["window_s"] = w
        metrics_rows.append(metrics_b)

    # --- Predictor C: State-Based ---
    t_hat_c = predictor_state_based(battery_df, t_s=t_s, t_tx=t_tx)
    predictions["C"] = t_hat_c
    metrics_c = compute_metrics(t_actual, t_hat_c)
    metrics_c["predictor"] = "C"
    metrics_c["window_s"] = np.nan
    metrics_rows.append(metrics_c)

    # 组装评价表
    metrics_df = pd.DataFrame(metrics_rows)
    # 确保列顺序
    col_order = ["predictor", "window_s", "MAE_s", "RMSE_s",
                 "relative_error", "overestimation_mean_s", "overestimation_rate"]
    metrics_df = metrics_df[[c for c in col_order if c in metrics_df.columns]]

    return predictions, metrics_df
