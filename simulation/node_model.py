"""
====================================================================
节点负载模型 — simulation/node_model.py
====================================================================

本文件是仿真系统的核心计算引擎，负责将时序参数转换为：

    T_S, T_TX, t_s, t_tx  →  state(t)  →  I(t)  →  P_load(t)

具体流程：
  1. _build_schedule():  根据采样间隔 T_S 和发送间隔 T_TX，
     在每个时间步 dt 上判断当前应该处于哪个状态（SLEEP / SAMPLING / LORA_TX）
     当多个状态同时 active 时，按 STATE_PRIORITY 仲裁。

  2. generate_load_profile():  将 state(t) 映射为电流 I(t)，
     再乘以总线电压 V_bus 得到负载功率 P_load(t)，
     最终输出为一个包含所有列的 DataFrame。

状态优先级（详见 config.py）：
    LORA_TX > SAMPLING > SLEEP

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import numpy as np
import pandas as pd

from simulation.config import (
    SIM_DURATION_S,     # 仿真总时长 (s)
    DT,                 # 时间步长 (s)
    T_S,                # 采样间隔 (s)
    T_TX,               # 发送间隔 (s)
    T_S_ACTIVE,         # 单次采样持续时长 (s)
    T_TX_ACTIVE,        # 单次 TX 持续时长 (s)
    I_SLEEP,            # SLEEP 状态电流 (A)
    I_SAMPLING,         # SAMPLING 状态电流 (A)
    I_TX,               # LORA_TX 状态电流 (A)
    BATTERY_V_NOMINAL,  # 标称电压 (V) — 用于 Part 1 简化功率计算
    STATE_PRIORITY,     # 状态优先级列表 ["LORA_TX", "SAMPLING", "SLEEP"]
)


def _build_schedule(
    duration: float,
    dt: float,
    t_s: float,
    t_tx: float,
    t_s_active: float,
    t_tx_active: float,
    state_priority: list[str],
) -> list[str]:
    """
    构建整个仿真周期的状态调度序列 state(t)。

    原理：
      对每个时间步 step（t = step * dt），判断此时有哪些状态应该是 active 的：

        - 如果 t % t_s < t_s_active  →  处于采样窗口内  →  SAMPLING 想 active
        - 如果 t % t_tx < t_tx_active →  处于发送窗口内  →  LORA_TX 想 active
        - 否则 →  SLEEP 是默认状态

      当多个状态同时想 active 时，按 state_priority 从高到低遍历，
      第一个 active 的状态胜出（优先级仲裁）。

    参数：
        duration:      仿真总时长 (s)
        dt:            时间步长 (s)
        t_s:           采样间隔 (s)
        t_tx:          发送间隔 (s)
        t_s_active:    单次采样持续时长 (s)
        t_tx_active:   单次 TX 持续时长 (s)
        state_priority: 状态优先级列表，从高到低排列

    返回：
        states: 长度为 duration/dt 的字符串列表，每个元素为 "SLEEP" / "SAMPLING" / "LORA_TX"

    示例（t_s=30, t_s_active=2, t_tx=120, t_tx_active=0.5, dt=1）：
        t=0:    0%30=0<2 → SAMPLING;  0%120=0<0.5 → LORA_TX
                → 优先级仲裁: LORA_TX 胜出
        t=1:    1%30=1<2 → SAMPLING;   1%120=1>0.5 → 不在 TX 窗口
                → SAMPLING 胜出
        t=2~29: 不在任何窗口 → SLEEP
        t=30:   30%30=0<2 → SAMPLING  → SAMPLING 胜出
        t=120:  120%30=0<2 → SAMPLING;  120%120=0<0.5 → LORA_TX
                → LORA_TX 胜出（重叠时 TX 优先）
    """
    n_steps = int(duration / dt)  # 总步数
    states = []

    for step in range(n_steps):
        t = step * dt

        # --- 初始：默认状态永远是 SLEEP ---
        active_states = {"SLEEP"}

        # --- 判断是否在采样窗口内 ---
        # 模运算：t 对 t_s 取余，如果余数小于 t_s_active，说明处于某个采样周期中
        time_since_last_sample = t % t_s
        if time_since_last_sample < t_s_active:
            active_states.add("SAMPLING")

        # --- 判断是否在 TX 窗口内 ---
        # 同理：t 对 t_tx 取余，如果余数小于 t_tx_active，说明处于某个发送周期中
        time_since_last_tx = t % t_tx
        if time_since_last_tx < t_tx_active:
            active_states.add("LORA_TX")

        # --- 优先级仲裁 ---
        # 按优先级从高到低遍历，第一个在 active_states 中的状态即为当前状态
        for prio_state in state_priority:
            if prio_state in active_states:
                states.append(prio_state)
                break
        else:
            # 理论上不应到达此处（因为 active_states 至少包含 "SLEEP"）
            states.append("SLEEP")

    return states


def generate_load_profile(
    duration: float | None = None,
    dt: float | None = None,
    t_s: float | None = None,
    t_tx: float | None = None,
    t_s_active: float | None = None,
    t_tx_active: float | None = None,
    i_sleep: float | None = None,
    i_sampling: float | None = None,
    i_tx: float | None = None,
    v_bus: float | None = None,
    state_priority: list[str] | None = None,
) -> pd.DataFrame:
    """
    生成完整的负载特性 DataFrame。

    这是外部调用的主入口。所有参数都有默认值（来自 config.py），
    但可以显式传入覆盖值——主要用于正确性测试和参数扫描。

    调用链路：
        generate_load_profile()
          → _build_schedule()    # 生成 state(t) 序列
          → 电流映射             # state → current
          → 功率计算             # P = V * I
          → DataFrame 构建

    参数（全部可选，默认取 config.py 中的值）：
        duration:       仿真总时长 (s)，默认 SIM_DURATION_S = 600
        dt:             时间步长 (s)，默认 DT = 1.0
        t_s:            采样间隔 (s)，默认 T_S = 30.0
        t_tx:           发送间隔 (s)，默认 T_TX = 120.0
        t_s_active:     单次采样持续时长 (s)，默认 T_S_ACTIVE = 2.0
        t_tx_active:    单次 TX 持续时长 (s)，默认 T_TX_ACTIVE = 0.5
        i_sleep:        SLEEP 电流 (A)，默认 I_SLEEP = 15 µA
        i_sampling:     SAMPLING 电流 (A)，默认 I_SAMPLING = 8 mA
        i_tx:           LORA_TX 电流 (A)，默认 I_TX = 120 mA
        v_bus:          总线电压 (V)，默认 V_BUS = 3.7
        state_priority: 优先级列表，默认 ["LORA_TX", "SAMPLING", "SLEEP"]

    返回：
        DataFrame，包含以下列：
            timestamp_s:          时间戳 (s)，从 0 到 duration-dt，步长 dt
            node_state:           当前状态 ("SLEEP" / "SAMPLING" / "LORA_TX")
            sampling_interval_s:  采样间隔 T_S (s)，常量列
            transmission_interval_s: 发送间隔 T_TX (s)，常量列
            current_load_A:       当前负载电流 (A)，由 state 映射得到
            voltage_bus_V:        总线电压 (V)，当前为常量 3.7V
            power_load_W:         负载功率 (W)，P = V_bus * I_load

    注意：
        - 本阶段 P_load 是"节点负载功率"，不代表电池端实际输出功率
        - 下一阶段引入 Battery Model 后，V_bus 将变为 V_bus(t) 动态值
        - current_load_A 永远 >= 0（传感器节点只消耗电能，不发电）
    """
    # --- 参数解析：未传入时使用 config 默认值 ---
    duration = duration if duration is not None else SIM_DURATION_S
    dt = dt if dt is not None else DT
    t_s = t_s if t_s is not None else T_S
    t_tx = t_tx if t_tx is not None else T_TX
    t_s_active = t_s_active if t_s_active is not None else T_S_ACTIVE
    t_tx_active = t_tx_active if t_tx_active is not None else T_TX_ACTIVE
    i_sleep = i_sleep if i_sleep is not None else I_SLEEP
    i_sampling = i_sampling if i_sampling is not None else I_SAMPLING
    i_tx = i_tx if i_tx is not None else I_TX
    v_bus = v_bus if v_bus is not None else BATTERY_V_NOMINAL
    state_priority = state_priority if state_priority is not None else STATE_PRIORITY

    # --- 状态 → 电流映射表 ---
    current_map = {
        "SLEEP": i_sleep,
        "SAMPLING": i_sampling,
        "LORA_TX": i_tx,
    }

    # --- 生成状态序列 state(t) ---
    states = _build_schedule(
        duration, dt, t_s, t_tx, t_s_active, t_tx_active, state_priority
    )

    # --- 由 state(t) 计算 I(t) ---
    currents = [current_map[s] for s in states]

    # --- 由 I(t) 计算 P_load(t) = V_bus * I(t) ---
    powers = [v_bus * i for i in currents]

    # --- 时间序列 ---
    timestamps = np.arange(0, duration, dt)

    # --- 组装为 DataFrame ---
    df = pd.DataFrame(
        {
            "timestamp_s": timestamps,
            "node_state": states,
            "sampling_interval_s": t_s,           # 常量列，方便后续分析
            "transmission_interval_s": t_tx,      # 常量列，方便后续分析
            "current_load_A": currents,
            "voltage_bus_V": v_bus,
            "power_load_W": powers,
        }
    )

    return df
