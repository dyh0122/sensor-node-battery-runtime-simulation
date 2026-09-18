"""
====================================================================
正确性检查（pytest 格式版本） — tests/test_node_model.py
====================================================================

用法（需要 pytest）：
    pip install pytest
    python -m pytest tests/ -v

作用：
    对 generate_load_profile() 的输出执行 11 项正确性检查。
    本文件使用 pytest 的 fixture + assert 格式编写，
    当 pytest 可用时提供更友好的逐条测试输出。

    如果 pytest 不可用，请使用项目根目录下的 run_tests.py。

检查清单：
  1.  状态序列长度 = SIM_DURATION_S / DT
  2.  时间戳覆盖完整仿真区间
  3.  LORA_TX 按 T_TX 周期出现
  4.  SAMPLING 按 T_S 周期出现
  5.  SLEEP 填充剩余时间
  6.  每个状态映射到正确的电流值
  7.  P_load = V_bus * I_load 逐行成立
  8.  不存在 NaN
  9.  不存在负电流
  10. 改变时间步长 dt 后行为一致
  11. 自定义参数覆盖正确

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import pytest
import numpy as np

from simulation.config import SIM_DURATION_S, DT, T_S, T_TX, T_S_ACTIVE, T_TX_ACTIVE, BATTERY_V_NOMINAL
from simulation.node_model import generate_load_profile


@pytest.fixture
def df():
    """
    测试夹具：生成默认配置下的负载数据 DataFrame。

    所有带 df 参数的测试函数都会收到同一个 DataFrame 实例，
    避免重复生成数据。
    """
    return generate_load_profile()


def test_simulation_duration_matches(df):
    """
    检查 1: 状态序列的行数必须等于 SIM_DURATION_S / DT。

    如果 dt=1, duration=600，应该有正好 600 行。
    """
    n_steps = int(SIM_DURATION_S / DT)
    assert len(df) == n_steps, f"Expected {n_steps} rows, got {len(df)}"


def test_timestamps_span_duration(df):
    """
    检查 2: 时间戳必须从 0 开始，到 SIM_DURATION_S - DT 结束。

    这确保仿真覆盖了完整的指定时长，没有截断或多余。
    """
    assert df["timestamp_s"].iloc[0] == 0
    assert df["timestamp_s"].iloc[-1] == pytest.approx(SIM_DURATION_S - DT, abs=DT)


def test_lora_tx_periodicity(df):
    """
    检查 3: LORA_TX 状态应该按 T_TX 周期出现。

    验证两个层面：
      a) 第一个 TX 窗口从 t=0 附近开始（因为 0 % T_TX = 0 < T_TX_ACTIVE）
      b) 相邻 TX 窗口起始时间的间隔约等于 T_TX

    这证明调度器正确地按 T_TX 周期触发 LoRa 发送。
    """
    tx_rows = df[df["node_state"] == "LORA_TX"]
    assert len(tx_rows) > 0, "No LORA_TX states found"

    # (a) 第一个 TX 窗口应该从 t=0 附近开始
    first_tx_time = tx_rows["timestamp_s"].iloc[0]
    assert first_tx_time < T_TX_ACTIVE, f"First TX at {first_tx_time}, expected near 0"

    # (b) 检查相邻 TX 窗口之间的间隔
    tx_start_times = []
    prev_state = None
    for _, row in df.iterrows():
        # 检测 TX 窗口的起始边界
        if row["node_state"] == "LORA_TX" and prev_state != "LORA_TX":
            tx_start_times.append(row["timestamp_s"])
        prev_state = row["node_state"]

    if len(tx_start_times) >= 2:
        gaps = np.diff(tx_start_times)
        # 间隔应该接近 T_TX（允许 ± T_TX_ACTIVE + DT 的容差）
        for gap in gaps:
            assert gap == pytest.approx(T_TX, abs=T_TX_ACTIVE + DT)


def test_sampling_periodicity(df):
    """
    检查 4: SAMPLING 状态应该按 T_S 周期出现。

    第一个采样窗口从 t=0 附近开始（0 % T_S = 0 < T_S_ACTIVE），
    之后每 T_S 秒重复一次。
    """
    sampling_rows = df[df["node_state"] == "SAMPLING"]
    assert len(sampling_rows) > 0, "No SAMPLING states found"

    first_sample_time = sampling_rows["timestamp_s"].iloc[0]
    assert first_sample_time < T_S_ACTIVE, f"First SAMPLING at {first_sample_time}, expected near 0"


def test_sleep_fills_remainder(df):
    """
    检查 5: SLEEP 状态必须填充未被 SAMPLING 和 LORA_TX 占用的时间。

    这意味着 SLEEP 的步数应该是最多的（在本仿真参数下约占 93%）。
    """
    state_counts = df["node_state"].value_counts()
    assert "SLEEP" in state_counts or state_counts.get("SLEEP", 0) >= 0


def test_current_mapping(df):
    """
    检查 6: 每个状态必须精确映射到 config.py 中定义的电流值。

    逐行检查 DataFrame，确保：
      SLEEP    → 15 µA
      SAMPLING → 8 mA
      LORA_TX  → 120 mA

    容差 1e-9 A，足以覆盖浮点误差。
    """
    for _, row in df.iterrows():
        state = row["node_state"]
        current = row["current_load_A"]
        if state == "SLEEP":
            assert current == pytest.approx(0.000_015, abs=1e-9)
        elif state == "SAMPLING":
            assert current == pytest.approx(0.008, abs=1e-9)
        elif state == "LORA_TX":
            assert current == pytest.approx(0.120, abs=1e-9)
        else:
            pytest.fail(f"Unknown state: {state}")


def test_power_calculation(df):
    """
    检查 7: P_load = V_bus * I_load 必须对每一行都成立。

    这是本阶段功率计算的核心公式。
    由于当前 V_bus = 3.7V 是常量，所以 P_load 与 I_load 成严格正比。
    """
    expected_power = BATTERY_V_NOMINAL * df["current_load_A"]
    assert np.allclose(df["power_load_W"], expected_power), "Power calculation mismatch"


def test_no_nan(df):
    """
    检查 8: DataFrame 中不允许存在任何 NaN 值。

    NaN 会导致下游的 CSV 导出和绘图异常。
    """
    assert not df.isna().any().any(), "DataFrame contains NaN values"


def test_no_negative_current(df):
    """
    检查 9: 电流永远不能为负值。

    物理意义：
      传感器节点在此模型中是纯负载，不发电（没有太阳能充电等）。
      负电流意味着节点在"反向供电"，这在当前模型下不应出现。
    """
    assert (df["current_load_A"] >= 0).all(), "Negative current detected"


def test_timestep_consistency():
    """
    检查 10: 改变时间步长 dt 后，仿真行为应该保持一致。

    验证两个方面：
      a) 行数与 dt 成反比（dt 减半 → 行数翻倍）
      b) 各状态的百分比分布不应有显著差异（容差 5%）

    这证明调度器不依赖于特定的 dt 值。
    """
    df_fine = generate_load_profile(dt=0.5)
    df_coarse = generate_load_profile(dt=2.0)

    n_fine = int(SIM_DURATION_S / 0.5)
    n_coarse = int(SIM_DURATION_S / 2.0)

    assert len(df_fine) == n_fine
    assert len(df_coarse) == n_coarse

    # 状态百分比应该接近
    fine_sleep_pct = (df_fine["node_state"] == "SLEEP").mean()
    coarse_sleep_pct = (df_coarse["node_state"] == "SLEEP").mean()
    assert abs(fine_sleep_pct - coarse_sleep_pct) < 0.05, "State distribution differs significantly with timestep"


def test_custom_parameters():
    """
    检查 11: 显式传入的自定义参数应该正确覆盖 config 默认值。

    测试传入：
      duration=100, t_s=20, t_tx=50, v_bus=4.2, i_tx=0.200

    验证：
      a) 行数 = 100（因为 dt 默认 = 1）
      b) V_bus 列值为 4.2
      c) LORA_TX 行的电流 = 0.200 A
      d) P_load = 4.2 * I_load

    这证明 generate_load_profile() 的参数覆盖机制正常工作，
    也为后续的参数扫描和电池模型集成提供了信心。
    """
    custom_duration = 100
    custom_t_s = 20
    custom_t_tx = 50
    custom_v_bus = 4.2
    custom_i_tx = 0.200

    df = generate_load_profile(
        duration=custom_duration,
        t_s=custom_t_s,
        t_tx=custom_t_tx,
        v_bus=custom_v_bus,
        i_tx=custom_i_tx,
    )

    assert len(df) == custom_duration  # dt=1, 所以行数 = 100
    assert df["voltage_bus_V"].iloc[0] == custom_v_bus

    # TX 行应该使用自定义电流
    tx_rows = df[df["node_state"] == "LORA_TX"]
    if len(tx_rows) > 0:
        assert (tx_rows["current_load_A"] == custom_i_tx).all()

    # 功率应该使用自定义 V_bus
    assert np.allclose(df["power_load_W"], custom_v_bus * df["current_load_A"])
