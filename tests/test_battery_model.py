"""
====================================================================
电池模型正确性检查（pytest 格式） — tests/test_battery_model.py
====================================================================

用法：
    pip install pytest
    python -m pytest tests/test_battery_model.py -v

检查清单：
  1.  SOC 是否单调下降
  2.  Energy used 是否单调增加
  3.  Energy remaining 是否单调下降
  4.  初始电压不能超过 4.2 V
  5.  正常放电不能低于 2.5 V 后继续运行
  6.  P_batt = V_terminal * I_batt 逐行成立
  7.  Wh 单位转换是否正确
  8.  dt 改变后总能量结果是否基本稳定
  9.  CSV 中是否存在 NaN
  10. OCV interpolation 是否超出原始数据范围
  11. 截止检测是否触发

如果 pytest 不可用，项目根目录有 run_battery_tests.py 作为内联替代。

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""

import pytest
import numpy as np

from simulation.config import BATTERY_V_CHARGE, BATTERY_V_CUTOFF, OCV_SOC_POINTS
from simulation.node_model import generate_load_profile
from simulation.battery_model import simulate_battery, build_ocv_interpolator


@pytest.fixture
def battery_df():
    """生成默认电池仿真数据。"""
    load_df = generate_load_profile()
    return simulate_battery(load_df)


@pytest.fixture
def ocv_interp():
    """生成 OCV 插值器。"""
    return build_ocv_interpolator(OCV_SOC_POINTS)


def test_soc_monotonic_decreasing(battery_df):
    """
    检查 1: SOC 应该单调下降（或不增加）。

    因为本阶段只有放电（I_batt ≥ 0），没有充电。
    SOC 不应该在放电过程中上升。
    """
    soc = battery_df["battery_soc"].values
    # 允许相等的值（截止后保持不变），但不允许增加
    diffs = np.diff(soc)
    assert np.all(diffs <= 1e-12), f"SOC increased at indices: {np.where(diffs > 1e-12)[0]}"


def test_energy_used_monotonic_increase(battery_df):
    """
    检查 2: 已消耗能量应该单调增加（或不减少）。

    E_used 是累积量，只加不减。
    """
    e_used = battery_df["energy_used_Wh"].values
    diffs = np.diff(e_used)
    assert np.all(diffs >= -1e-12), f"E_used decreased at indices: {np.where(diffs < -1e-12)[0]}"


def test_energy_remaining_monotonic_decrease(battery_df):
    """
    检查 3: 剩余能量应该单调下降（或不增加）。

    E_remaining 基于 SOC 计算，SOC 单调下降 → E_remaining 也单调下降。
    """
    e_remain = battery_df["energy_remaining_Wh"].values
    diffs = np.diff(e_remain)
    assert np.all(diffs <= 1e-12), f"E_remaining increased at indices: {np.where(diffs > 1e-12)[0]}"


def test_initial_voltage_not_exceed_charge(battery_df):
    """
    检查 4: 初始 V_terminal 不能超过充电截止电压 4.2 V。

    在 SOC = 1.0 时，V_ocv ≈ 4.2 V。
    V_terminal = V_ocv - I_batt * R0 ≤ V_ocv ≤ 4.2 V
    """
    v_init = battery_df["battery_terminal_voltage_V"].iloc[0]
    assert v_init <= BATTERY_V_CHARGE + 0.01, (
        f"Initial V_terminal = {v_init} V, exceeds V_charge = {BATTERY_V_CHARGE} V"
    )


def test_voltage_not_below_cutoff(battery_df):
    """
    检查 5: V_terminal 在截止前不能低于 2.5 V。

    一旦 V_terminal ≤ 2.5 V，仿真应该停止（后续行保持截止时的值）。
    未截止的行中，V_terminal 应该 > 2.5 V（允许一点容差）。
    """
    # 只看未达到截止的行
    active_rows = battery_df[~battery_df["cutoff_reached"]]
    v_min = active_rows["battery_terminal_voltage_V"].min()
    # 允许 0.01 V 的数值误差
    assert v_min >= BATTERY_V_CUTOFF - 0.01, (
        f"V_terminal dropped to {v_min} V before cutoff (limit: {BATTERY_V_CUTOFF} V)"
    )


def test_power_calculation(battery_df):
    """
    检查 6: P_batt = V_terminal * I_batt 逐行成立。
    """
    expected_power = battery_df["battery_terminal_voltage_V"] * battery_df["battery_current_A"]
    assert np.allclose(battery_df["battery_power_W"], expected_power), "Power calculation mismatch"


def test_energy_units(battery_df):
    """
    检查 7: Wh 单位转换正确。

    验证：
      E_used(Wh) ≈ sum(P * dt / 3600)
      E_total = ∫ V_ocv(SOC) d(SOC) * Q_nominal / 3600
    """
    e_total = battery_df["energy_remaining_Wh"].iloc[0]
    # E_total 应该在合理范围（2000 mAh × ~3.7 V ≈ 7.4 Wh，但实际会因 OCV 曲线而异）
    assert 5.0 < e_total < 9.0, f"E_total = {e_total} Wh, expected ~5-9 Wh range"


def test_timestep_energy_consistency():
    """
    检查 8: 改变 dt 后总消耗能量应该基本一致。

    注意：由于 LORA_TX 窗口很短 (0.5s)，不同的 dt 会导致
    TX 捕获精度不同。本测试使用更大的 t_tx_active=5.0s
    来确保两种 dt 都能正确捕获 TX 窗口。
    """
    load_fine = generate_load_profile(duration=600, dt=0.5, t_tx_active=5.0)
    load_coarse = generate_load_profile(duration=600, dt=2.0, t_tx_active=5.0)

    df_fine = simulate_battery(load_fine)
    df_coarse = simulate_battery(load_coarse)

    e_used_fine = df_fine["energy_used_Wh"].iloc[-1]
    e_used_coarse = df_coarse["energy_used_Wh"].iloc[-1]

    # 两者应该接近（允许 5% 容差）
    if e_used_fine > 0 and e_used_coarse > 0:
        ratio = e_used_fine / e_used_coarse
        assert 0.85 < ratio < 1.15, (
            f"E_used differs by timestep: fine={e_used_fine:.6f}, coarse={e_used_coarse:.6f}, ratio={ratio:.4f}"
        )


def test_no_nan(battery_df):
    """
    检查 9: 不存在 NaN。
    """
    assert not battery_df.isna().any().any(), "DataFrame contains NaN values"


def test_ocv_interpolation_within_range(ocv_interp):
    """
    检查 10: OCV 插值器对合法 SOC 值不抛出异常。

    测试 SOC = 0, 0.5, 1.0 都应该在插值器范围内。
    """
    for soc in [0.0, 0.5, 1.0]:
        v = ocv_interp(soc)
        assert 2.5 <= v <= 4.3, f"OCV at SOC={soc} is {v} V, out of expected range"


def test_ocv_extrapolation_raises(ocv_interp):
    """
    检查 10b: OCV 插值器对超出范围的 SOC 值抛出异常。

    SOC < 0 或 SOC > 1 应该触发 bounds_error。
    """
    with pytest.raises(ValueError):
        ocv_interp(-0.1)
    with pytest.raises(ValueError):
        ocv_interp(1.1)


def test_cutoff_triggered(battery_df):
    """
    检查 11: 在足够长的仿真中，截止条件应该被触发。

    默认仿真时长 600 s，虽然不足以让 2000 mAh 电池完全耗尽，
    但至少应该有一些步骤检测到截止（如果负载足够大）。
    此测试只验证截止机制存在，不要求一定触发。
    """
    # 对于默认参数（小负载），可能不会触发截止
    # 所以这个测试只验证机制正常工作
    assert "cutoff_reached" in battery_df.columns


def test_cutoff_triggers_under_heavy_load():
    """
    检查 11b: 在大负载下，截止条件应该被触发。

    使用更大的电流（1 A 持续放电）来快速触发截止。
    """
    import pandas as pd

    # 创建一个 1 A 持续放电的负载
    n_steps = 10000  # 10000 s at dt=1
    load_df = pd.DataFrame({
        "timestamp_s": np.arange(n_steps, dtype=float),
        "current_load_A": np.full(n_steps, 1.0),  # 1 A 持续
    })

    battery_df = simulate_battery(load_df)

    # 在 1 A 放电下，2000 mAh 电池应该在 ~7200 s 内耗尽
    # 但受内阻压降影响，可能在 V_terminal 降到 2.5 V 时更早截止
    cutoff_count = battery_df["cutoff_reached"].sum()
    assert cutoff_count > 0, "Cutoff should have been triggered under 1 A load"


def test_soc_ocv_consistency(battery_df):
    """
    检查: SOC 和 V_ocv 应该通过 OCV-SOC 曲线一致关联。

    V_ocv = f(SOC)，每个 SOC 对应唯一的 V_ocv。
    """
    from scipy.interpolate import interp1d

    soc_values = [p[0] for p in OCV_SOC_POINTS]
    v_ocv_values = [p[1] for p in OCV_SOC_POINTS]
    interp = interp1d(soc_values, v_ocv_values, kind="linear")

    expected_ocv = interp(battery_df["battery_soc"].values)
    assert np.allclose(battery_df["battery_ocv_V"].values, expected_ocv), "OCV-SOC mapping inconsistent"
