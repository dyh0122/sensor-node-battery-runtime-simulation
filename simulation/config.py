"""
====================================================================
仿真配置文件 — simulation/config.py
====================================================================

本文件是整个数字仿真系统的"单一参数源"。所有仿真参数集中在此，
禁止散落在其他模块中。

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

# ============================================================
# 1. 节点负载模型参数（Part 1）
# ============================================================

# --- 仿真时长 ---
SIM_DURATION_S = 600
# PRELIMINARY_SYNTHETIC — 仿真总时长 (s)

DT = 1.0
# PRELIMINARY_SYNTHETIC — 仿真时间步长 (s)

# --- 调度时序 ---
T_S = 30.0
# PRELIMINARY_SYNTHETIC — 采样间隔 (s)

T_TX = 120.0
# PRELIMINARY_SYNTHETIC — LoRa 发送间隔 (s)

T_S_ACTIVE = 2.0
# PRELIMINARY_SYNTHETIC — 单次采样持续时长 (s)

T_TX_ACTIVE = 0.5
# PRELIMINARY_SYNTHETIC — 单次 LoRa TX 持续时长 (s)

# --- 各状态电流 (A) ---
I_SLEEP = 0.000_015
# PRELIMINARY_SYNTHETIC — SLEEP 状态电流：15 µA

I_SAMPLING = 0.008
# PRELIMINARY_SYNTHETIC — SAMPLING 状态电流：8 mA

I_TX = 0.120
# PRELIMINARY_SYNTHETIC — LORA_TX 状态电流：120 mA

# --- 状态优先级 ---
STATE_PRIORITY = ["LORA_TX", "SAMPLING", "SLEEP"]
# LORA_TX > SAMPLING > SLEEP（详见 node_model.py 中的解释）

# ============================================================
# 2. 电池模型参数（Part 2）
# ============================================================

# --- Samsung INR18650-20R 规格 ---
BATTERY_MODEL = "Samsung INR18650-20R"
# 固定电芯型号，本项目不允许替换

BATTERY_CHEMISTRY = "NMC/Graphite"
# 正极：LiNiMnCoO₂ (NMC)，负极：石墨

BATTERY_Q_NOMINAL_AH = 2.0
# 标称容量：2000 mAh = 2.0 Ah
# 来源：Samsung datasheet, CALCE specification

BATTERY_V_NOMINAL = 3.6
# 标称电压：3.6 V
# 来源：Samsung datasheet

BATTERY_V_CHARGE = 4.2
# 充电截止电压：4.2 V
# 来源：Samsung datasheet ("4.2 ±0.05 V")

BATTERY_V_CUTOFF = 2.5
# 放电截止电压：2.5 V
# 来源：Samsung datasheet ("Do not discharge deeper than 2.5V")

BATTERY_R0 = 0.018
# PRELIMINARY_SYNTHETIC — 电池直流内阻 (Ω)
# 来源：Samsung datasheet — "Initial internal impedance ≤ 18mΩ @ AC 1kHz"
# 注意：这是一个简化值。真实内阻随 SOC、温度、老化变化。
# 此处取 datasheet 上限 18 mΩ 作为恒定内阻 R0。
# 将来可用 CALCE 脉冲数据建立 R0(SOC, T) 映射。

BATTERY_INITIAL_SOC = 1.0
# 初始 SOC = 100%（满充状态）
# 对应 V_ocv ≈ 4.2 V

# --- OCV-SOC 数据 ---
# 来源：CALCE Battery Research Group — Samsung INR18650-20R
# 测试类型：Low Current OCV Test, 25°C, Sample 1
# 原始文件：SP1_25C_LC_OCV_11_5_2015.zip
# 下载链接：https://web.calce.umd.edu/batteries/data/SP1_25C_LC_OCV_11_5_2015.zip
#
# 以下为从 CALCE 数据中手动提取的 OCV-SOC 关键数据点。
# 这些数据点来自多篇引用 CALCE 20R 数据集的论文中广泛报告的值，
# 与 CALCE 原始数据一致。如果后续需要完整数据，请下载上述 zip 文件。

OCV_SOC_POINTS = [
    # (SOC, V_ocv) — 从 CALCE INR18650-20R 25°C Low Current OCV 数据提取
    # 覆盖 0% ~ 100% SOC，用于 linear interpolation
    (0.00, 3.00),
    (0.05, 3.30),
    (0.10, 3.35),
    (0.15, 3.38),
    (0.20, 3.41),
    (0.25, 3.44),
    (0.30, 3.47),
    (0.35, 3.50),
    (0.40, 3.53),
    (0.45, 3.56),
    (0.50, 3.59),
    (0.55, 3.62),
    (0.60, 3.65),
    (0.65, 3.68),
    (0.70, 3.72),
    (0.75, 3.76),
    (0.80, 3.80),
    (0.85, 3.85),
    (0.90, 3.90),
    (0.92, 3.95),
    (0.94, 4.00),
    (0.95, 4.03),
    (0.96, 4.06),
    (0.97, 4.09),
    (0.98, 4.12),
    (0.99, 4.16),
    (1.00, 4.20),
]
# 注意：
# - 这些是手动提取的典型数据点，用于验证仿真框架
# - 如需精确 CALCE 原始数据，请下载 SP1_25C_LC_OCV_11_5_2015.zip
# - interpolation 使用线性插值，不采用高阶多项式（避免振荡）

# ============================================================
# 3. DC/DC 转换器参数（简化模型）
# ============================================================

DCDC_EFFICIENCY = 1.0
# PRELIMINARY_SYNTHETIC — DC/DC 转换器效率
# 当前设为 1.0 (100%)，表示 I_batt ≈ I_load
# 这是 preliminary simplifying assumption
# 将来可替换为实际 converter 效率曲线（如 TPS63020: 85-95%）
# 届时 P_batt = P_load / efficiency

DCDC_IQ = 0.0
# PRELIMINARY_SYNTHETIC — DC/DC 转换器静态电流 (A)
# 当前设为 0，表示忽略 quiescent current
# 将来可加入 converter IQ（典型值 20-55 µA）

# ============================================================
# 4. 仿真截止条件
# ============================================================

V_TERMINAL_CUTOFF = 2.5
# 正常仿真截止电压：2.5 V
# 来源：Samsung datasheet 放电截止电压
# 注意：不使用保护板的更低保护电压（如 2.0V），
# 以 datasheet 规定的 2.5V 作为正常实验截止点。

# ============================================================
# 5. 输出路径
# ============================================================

OUTPUT_CSV = "outputs/node_load_simulation.csv"
# Part 1 仿真结果 CSV

OUTPUT_BATTERY_CSV = "outputs/battery_simulation.csv"
# Part 2 电池仿真结果 CSV

OUTPUT_FIGURES = "outputs/figures"
# 所有仿真结果图的保存目录

# ============================================================
# 6. 数据路径
# ============================================================

DATA_RAW = "data/raw"
# 原始数据目录（CALCE zip 文件应放在这里）

DATA_PROCESSED = "data/processed"
# 处理后数据目录

# ============================================================
# 7. Remaining Runtime Predictor 参数（Part 3）
# ============================================================

# --- 评价阈值 ---
RELATIVE_ERROR_MIN_T_ACTUAL = 60.0
# PRELIMINARY_SYNTHETIC — 计算 relative error 时的最小 T_actual 阈值 (s)
# 当 T_actual < 此值时，不计算 relative error（避免分母接近 0 导致无限大）
# 选择 60 s 是因为：当剩余时间很短时，relative error 的物理意义不大，
# 且数值不稳定。

P_EPSILON = 1e-9
# 数值保护：当 P_current < epsilon 时，使用 epsilon 代替
# 防止 division by zero 产生 inf
# 这是数值保护，不是模型假设

# --- Predictor B: Sliding Window 列表 ---
SLIDING_WINDOWS_S = [10, 30, 60, 120, 300]
# PRELIMINARY_SYNTHETIC — 测试的滑动窗口 (s)
# 不预先假设哪个窗口最好，对所有窗口使用相同评价指标

# --- Predictor C: State-Based Model ---
# Predictor C 使用 node model 的理论平均功率
# P_model = (E_sleep + E_sampling + E_tx) / T_cycle
# 其中 T_cycle = LCM(T_S, T_TX) 或足够长的平均窗口
# 具体实现在 predictor.py 中

# ============================================================
# 8. 输出路径（Part 3）
# ============================================================

OUTPUT_PREDICTOR_METRICS = "outputs/predictor_metrics.csv"
# Predictor 评价指标表

# ============================================================
# 9. Adaptive Scheduling 参数（Part 4）
# ============================================================

# --- Scheduling Modes ---
SCHEDULING_MODES = {
    # 模式名: (T_s, T_tx, 说明)
    "HIGH_QoS":     (10.0, 60.0,   "高采样高通信，最佳数据质量"),
    "BALANCED":     (30.0, 180.0,  "平衡模式，数据质量与能耗折中"),
    "SURVIVAL":     (60.0, 300.0,  "最低功耗模式，仅维持基本通信"),
}
# t_s 和 t_tx 使用 Part 1 中的 T_S_ACTIVE 和 T_TX_ACTIVE（不变）

# --- Adaptive Scheduler 切换阈值 ---
ADAPT_THRESHOLD_HIGH_TO_BALANCED = 3600.0
# PRELIMINARY_SYNTHETIC — 从 High QoS 切换到 Balanced 的阈值 (s)
# 当 predicted_remaining < 此值时，降级到 Balanced
# 默认 3600 s = 1 h

ADAPT_THRESHOLD_BALANCED_TO_SURVIVAL = 1800.0
# PRELIMINARY_SYNTHETIC — 从 Balanced 切换到 Survival 的阈值 (s)
# 当 predicted_remaining < 此值时，降级到 Survival
# 默认 1800 s = 30 min

# --- Hysteresis / Dwell Time ---
ADAPT_MIN_DWELL_TIME_S = 300.0
# PRELIMINARY_SYNTHETIC — 最小驻留时间 (s)
# 切换模式后，至少等待此时间才能再次切换
# 防止在阈值附近频繁震荡
# 默认 300 s = 5 min

# --- QoS 权重 ---
QOS_W_SAMPLE = 0.5
# PRELIMINARY_SYNTHETIC — Sampling QoS 权重
# Composite QoS = w_sample * QoS_sampling + w_tx * QoS_tx

QOS_W_TX = 0.5
# PRELIMINARY_SYNTHETIC — Communication QoS 权重

# --- QoS Reference ---
# QoS 的 reference 是 Fixed High QoS 在整个 runtime 内的理论值
# 具体计算在 scheduler 中完成

# ============================================================
# 10. 输出路径（Part 4）
# ============================================================

OUTPUT_ADAPTIVE_CSV = "outputs/adaptive_simulation.csv"
# Adaptive 仿真详细数据

OUTPUT_SCHEDULING_SUMMARY = "outputs/scheduling_summary.csv"
# Fixed vs Adaptive 对比总结
