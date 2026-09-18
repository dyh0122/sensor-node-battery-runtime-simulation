"""
====================================================================
电池模型 — simulation/battery_model.py
====================================================================

本文件实现 Part 2 — Battery / Energy Model，包含：

  Step A — Coulomb Counting（库仑计）
      SOC(k+1) = SOC(k) - I_batt(k) * dt / (3600 * Q_nominal)

  Step B — OCV-SOC 映射
      V_ocv = f(SOC)，使用 CALCE INR18650-20R 25°C 数据的线性插值

  Step C — Terminal Voltage
      V_terminal = V_ocv(SOC) - I_batt * R0

  Energy Model
      P_batt(t) = V_terminal(t) * I_batt(t)
      E_used += P_batt * dt
      E_remaining = E_total - E_used

  Cutoff
      V_terminal <= 2.5 V 或 SOC <= 0 时停止仿真

数据源：
  CALCE Battery Research Group
  Samsung INR18650-20R, 25°C, Low Current OCV Test, Sample 1
  原始文件：SP1_25C_LC_OCV_11_5_2015.zip
  下载：https://web.calce.umd.edu/batteries/data/SP1_25C_LC_OCV_11_5_2015.zip

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.integrate import trapezoid

from simulation.config import (
    BATTERY_Q_NOMINAL_AH,     # 标称容量 (Ah)
    BATTERY_V_CHARGE,         # 充电截止电压 (V)
    BATTERY_V_CUTOFF,         # 放电截止电压 (V)
    BATTERY_R0,               # 直流内阻 (Ω)
    BATTERY_INITIAL_SOC,      # 初始 SOC
    BATTERY_V_NOMINAL,        # 标称电压 (V)
    OCV_SOC_POINTS,           # OCV-SOC 数据点列表 [(SOC, V_ocv), ...]
    DCDC_EFFICIENCY,          # DC/DC 效率
    DCDC_IQ,                  # DC/DC 静态电流 (A)
    V_TERMINAL_CUTOFF,        # 终端电压截止值 (V)
)


def build_ocv_interpolator(ocv_points: list[tuple[float, float]]) -> interp1d:
    """
    构建 OCV-SOC 线性插值器。

    参数：
        ocv_points: [(SOC, V_ocv), ...] 列表，SOC ∈ [0, 1]

    返回：
        scipy.interpolate.interp1d 对象，输入 SOC ∈ [0, 1]，输出 V_ocv ∈ [V]

    注意：
        - 使用线性插值 (kind='linear')，不采用高阶多项式
        - fill_value='extrapolate' 被禁用，防止超出数据范围
        - 如果 SOC 超出 [0, 1]，会抛出 ValueError
    """
    soc_values = [p[0] for p in ocv_points]
    v_ocv_values = [p[1] for p in ocv_points]

    # 验证 SOC 值单调递增
    for i in range(1, len(soc_values)):
        assert soc_values[i] > soc_values[i - 1], (
            f"OCV-SOC 数据点 SOC 值非单调: {soc_values[i-1]} -> {soc_values[i]}"
        )

    interpolator = interp1d(
        soc_values,
        v_ocv_values,
        kind="linear",
        bounds_error=True,   # SOC 超出范围时抛出异常
        assume_sorted=True,  # 数据已排序，提升性能
    )
    return interpolator


def soc_to_ocv(soc: float | np.ndarray, interpolator: interp1d) -> float | np.ndarray:
    """
    将 SOC 映射为 OCV 电压。

    参数：
        soc:          SOC 值或数组，范围 [0, 1]
        interpolator: build_ocv_interpolator() 返回的插值器

    返回：
        V_ocv：对应的开路电压 (V)

    异常：
        ValueError：如果 SOC 超出插值器范围
    """
    return float(interpolator(soc))


def compute_terminal_voltage(v_ocv: float, i_batt: float, r0: float) -> float:
    """
    计算终端电压（含内阻压降）。

    公式：
        V_terminal = V_ocv(SOC) - I_batt * R0

    参数：
        v_ocv:  开路电压 (V)，由 soc_to_ocv() 给出
        i_batt: 电池放电电流 (A)，正值表示放电
        r0:     直流内阻 (Ω)

    返回：
        V_terminal：终端电压 (V)

    注意：
        - 放电时 I_batt > 0，内阻压降使 V_terminal < V_ocv
        - 充电时 I_batt < 0，内阻压降使 V_terminal > V_ocv
        - 本阶段 I_batt ≥ 0（纯放电），所以 V_terminal ≤ V_ocv
    """
    return v_ocv - i_batt * r0


def simulate_battery(
    load_df: pd.DataFrame,
    q_nominal: float | None = None,
    r0: float | None = None,
    initial_soc: float | None = None,
    v_cutoff: float | None = None,
    v_charge: float | None = None,
    dcdc_efficiency: float | None = None,
    dcdc_iq: float | None = None,
    ocv_points: list[tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """
    完整的电池仿真流程：I(t) → SOC(t) → OCV(t) → V_terminal(t) → P_batt(t) → E(t)

    调用链路：
        1. 从 load_df 提取 I_load(t)
        2. 应用 DC/DC 简化：I_batt ≈ I_load（当前效率 = 1.0）
        3. Coulomb Counting：逐步骤更新 SOC
        4. OCV-SOC 插值：V_ocv = f(SOC)
        5. 终端电压：V_terminal = V_ocv - I_batt * R0
        6. 功率和能量：P_batt, E_used, E_remaining
        7. 截止检测：V_terminal <= V_cutoff 时停止

    参数（全部可选，默认取 config.py）：
        load_df:        上一阶段 node_model.generate_load_profile() 的输出 DataFrame
                        必须包含列：timestamp_s, current_load_A
        q_nominal:      标称容量 (Ah)，默认 2.0
        r0:             直流内阻 (Ω)，默认 0.018
        initial_soc:    初始 SOC，默认 1.0
        v_cutoff:       放电截止电压 (V)，默认 2.5
        v_charge:       充电截止电压 (V)，默认 4.2
        dcdc_efficiency: DC/DC 效率，默认 1.0
        dcdc_iq:        DC/DC 静态电流 (A)，默认 0.0
        ocv_points:     OCV-SOC 数据点，默认 config.OCV_SOC_POINTS

    返回：
        DataFrame，在 load_df 基础上新增列：
            battery_soc:              电池 SOC (0~1)
            battery_ocv_V:            开路电压 (V)
            battery_terminal_voltage_V: 终端电压 (V)
            battery_current_A:        电池电流 (A)
            battery_power_W:          电池功率 (W)
            energy_used_Wh:           已消耗能量 (Wh)
            energy_remaining_Wh:      剩余能量 (Wh)
            cutoff_reached:           是否达到截止条件 (bool)

    注意：
        - 本阶段 I_batt ≈ I_load 是 preliminary simplifying assumption
        - 将来可替换为：I_batt = I_load / efficiency + Iq
        - E_total = Q_nominal * V_avg（近似总能量），
          更准确的做法是对 OCV-SOC 曲线积分
    """
    # --- 参数解析 ---
    q_nominal = q_nominal if q_nominal is not None else BATTERY_Q_NOMINAL_AH
    r0 = r0 if r0 is not None else BATTERY_R0
    initial_soc = initial_soc if initial_soc is not None else BATTERY_INITIAL_SOC
    v_cutoff = v_cutoff if v_cutoff is not None else V_TERMINAL_CUTOFF
    v_charge = v_charge if v_charge is not None else BATTERY_V_CHARGE
    dcdc_efficiency = dcdc_efficiency if dcdc_efficiency is not None else DCDC_EFFICIENCY
    dcdc_iq = dcdc_iq if dcdc_iq is not None else DCDC_IQ
    ocv_points = ocv_points if ocv_points is not None else OCV_SOC_POINTS

    # --- 构建 OCV 插值器 ---
    ocv_interp = build_ocv_interpolator(ocv_points)

    # --- 提取负载数据 ---
    timestamps = load_df["timestamp_s"].values
    i_load = load_df["current_load_A"].values
    dt = timestamps[1] - timestamps[0] if len(timestamps) > 1 else 1.0

    # --- 初始化输出数组 ---
    n = len(timestamps)
    soc_arr = np.zeros(n)
    v_ocv_arr = np.zeros(n)
    v_term_arr = np.zeros(n)
    i_batt_arr = np.zeros(n)
    p_batt_arr = np.zeros(n)
    e_used_arr = np.zeros(n)
    e_remain_arr = np.zeros(n)
    cutoff_arr = np.zeros(n, dtype=bool)

    # --- 初始状态 ---
    soc_arr[0] = initial_soc
    v_ocv_arr[0] = soc_to_ocv(initial_soc, ocv_interp)

    # --- PRELIMINARY_SIMPLIFYING_ASSUMPTION: I_batt ≈ I_load ---
    # 当前 DC/DC 效率 = 1.0，静态电流 = 0
    # 因此 I_batt(t) = I_load(t)
    # 将来可改为：I_batt = I_load / efficiency + Iq
    i_batt_arr = i_load.copy()

    # --- 计算电池总能量（Wh）---
    # 通过对 OCV-SOC 曲线从 SOC=0 到 SOC=1 积分得到
    # E_total = ∫ V_ocv(SOC) * Q_nominal d(SOC)  (Wh)
    #   因为 ∫ V_ocv d(SOC) 的单位是 V，乘以 Q_nominal (Ah) 得到 Wh
    # 使用梯形数值积分
    soc_full = np.linspace(0, 1, 1000)
    v_ocv_full = ocv_interp(soc_full)
    e_total_Wh = trapezoid(v_ocv_full, soc_full) * q_nominal
    # 注意：这是理想可用能量，不含内阻损耗
    # 对于 Samsung 20R: ~3.6V 平均 × 2.0 Ah ≈ 7.2 Wh

    e_used_wh = 0.0

    # --- 逐步骤仿真 ---
    cutoff_reached = False
    for k in range(1, n):
        if cutoff_reached:
            # 达到截止条件后，保持最后一个状态
            soc_arr[k:] = soc_arr[k - 1]
            v_ocv_arr[k:] = v_ocv_arr[k - 1]
            v_term_arr[k:] = v_term_arr[k - 1]
            i_batt_arr[k:] = 0.0
            p_batt_arr[k:] = 0.0
            e_used_arr[k:] = e_used_arr[k - 1]
            e_remain_arr[k:] = e_remain_arr[k - 1]
            cutoff_arr[k:] = True
            break

        # --- Step A: Coulomb Counting ---
        # SOC(k+1) = SOC(k) - I_batt(k) * dt / (3600 * Q_nominal)
        # 注意单位：
        #   I_batt: A (C/s)
        #   dt:     s
        #   Q:      Ah
        #   3600:   s/h 转换因子
        delta_soc = i_batt_arr[k] * dt / (3600.0 * q_nominal)
        soc_arr[k] = soc_arr[k - 1] - delta_soc

        # SOC 限制在 [0, 1]
        soc_arr[k] = np.clip(soc_arr[k], 0.0, 1.0)

        # --- Step B: OCV-SOC ---
        v_ocv_arr[k] = soc_to_ocv(soc_arr[k], ocv_interp)

        # --- Step C: Terminal Voltage ---
        v_term_arr[k] = compute_terminal_voltage(v_ocv_arr[k], i_batt_arr[k], r0)

        # --- 功率 ---
        p_batt_arr[k] = v_term_arr[k] * i_batt_arr[k]

        # --- 能量累计 (Wh) ---
        # E += P * dt / 3600  (Wh)
        e_used_wh += p_batt_arr[k] * dt / 3600.0
        e_used_arr[k] = e_used_wh

        # --- 剩余能量 ---
        # 基于 SOC 的剩余可用能量：E_remaining = SOC * E_total_Wh
        # 这是"理想"剩余能量（不含内阻损耗修正）
        e_remain_arr[k] = soc_arr[k] * e_total_Wh

        # --- 截止检测 ---
        if v_term_arr[k] <= v_cutoff or soc_arr[k] <= 0.0:
            cutoff_reached = True
            cutoff_arr[k] = True

    # --- 第 0 行的补充计算 ---
    v_term_arr[0] = compute_terminal_voltage(v_ocv_arr[0], i_batt_arr[0], r0)
    p_batt_arr[0] = v_term_arr[0] * i_batt_arr[0]
    e_remain_arr[0] = initial_soc * e_total_Wh

    # --- 组装 DataFrame ---
    df = load_df.copy()
    df["battery_soc"] = soc_arr
    df["battery_ocv_V"] = v_ocv_arr
    df["battery_terminal_voltage_V"] = v_term_arr
    df["battery_current_A"] = i_batt_arr
    df["battery_power_W"] = p_batt_arr
    df["energy_used_Wh"] = e_used_arr
    df["energy_remaining_Wh"] = e_remain_arr
    df["cutoff_reached"] = cutoff_arr

    return df
