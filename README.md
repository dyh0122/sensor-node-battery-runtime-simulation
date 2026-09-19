# 面向无人值守传感节点的电池与能量调度仿真

这是一个 Python 数字原型：生成传感节点的睡眠、采样、LoRa 发送状态；将状态映射为负载电流；计算电池 SOC、端电压和剩余能量；比较剩余运行时间预测器与三种固定调度模式。项目使用 Samsung INR18650-20R 的**配置参数与示意性 OCV–SOC 表**。仓库目前没有原始电池实验数据，因此图表代表模型仿真，不代表实测电芯性能。

**当前建议使用的结果**是 `outputs/figures/` 中经审核的 17 张图，以及 `outputs/reviewed_*.csv`。旧版预测和自适应调度输出存在建模不一致问题；详见 [图表审查记录](docs/FIGURE_REVIEW.md)。尤其不能把旧报告中的“固定策略 40 h、自适应 10 h”解释为测得的实际续航。

## 1. 项目结构

```text
Codex_Project_in_BMS_paper/
├── README.md                       本指南
├── requirements.txt                Python 依赖
├── rebuild_reviewed_figures.py     重建已审核的 17 张图及修订指标
├── run_simulation.py               初始节点/电池仿真入口（旧版绘图流程）
├── run_predictor_eval.py           旧版预测器评估，保留供研究历史追溯
├── run_adaptive.py                 旧版调度评估，保留供研究历史追溯
├── run_tests.py                    节点模型独立检查
├── run_battery_tests.py            电池模型独立检查
├── run_predictor_tests.py          预测器实现独立检查
├── simulation/                    模型及公共参数
│   ├── config.py                   仿真时长、电池、负载、调度等参数
│   ├── node_model.py               节点状态与负载曲线
│   ├── battery_model.py            SOC、OCV、端电压、功率
│   ├── predictor.py                预测器 A/B/C 与评价函数
│   ├── scheduler.py                自适应调度规则及旧版仿真
│   └── main.py                     初始仿真和旧版绘图逻辑
├── tests/                         pytest 单元测试
├── data/
│   ├── raw/README.md               原始数据获取说明；目前没有原始数据文件
│   └── processed/                  预留的处理后数据目录
├── docs/
│   ├── FIGURE_REVIEW.md             图表问题、修订方式及结果限制
│   ├── PART2_REPORT.md             历史电池模型报告
│   ├── PART3_REPORT.md             历史预测器报告，顶部有失效提示
│   └── PART4_REPORT.md             历史调度报告，顶部有失效提示
└── outputs/
    ├── README.md                   每个输出文件的状态说明
    ├── figures/                    17 张已审核 PNG 与逐图说明 README
    ├── reviewed_predictor_metrics.csv
    ├── reviewed_scheduling_summary.csv
    └── *.csv                       其他初始或历史仿真输出
```

`.idea/` 是本地 IDE 配置，`__pycache__/` 是 Python 自动生成的缓存；它们不是实验输入。空的误建目录 `data/data/raw` 已清理。

## 2. 安装环境

需要 Python 3.10 或更新版本。以下命令以 Windows PowerShell 为例，均在**项目根目录**执行。可在项目文件夹中打开终端；若从其他位置打开，请先用 `Set-Location` 切换到实际的项目目录（路径含空格时使用引号）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖为 NumPy、pandas、SciPy、Matplotlib 和 pytest。使用 `.venv` 中的 Python 运行后续命令，不需要激活虚拟环境：

```powershell
.\.venv\Scripts\python.exe --version
```

如系统使用 `py` 启动器，可把创建环境命令改为 `py -m venv .venv`。安装依赖需要可访问 Python 包索引；本项目本身不在运行时下载电池数据。

## 3. 最短复现流程

项目已经包含初始 CSV，直接运行下面的命令即可重建全部修订图表：

```powershell
.\.venv\Scripts\python.exe rebuild_reviewed_figures.py
```

从只含源码、尚无 `outputs/node_load_simulation.csv` 和 `outputs/battery_simulation.csv` 的目录开始时，先生成初始轨迹，再重绘图表：

```powershell
.\.venv\Scripts\python.exe run_simulation.py
.\.venv\Scripts\python.exe rebuild_reviewed_figures.py
```

**命令顺序很重要。** `run_simulation.py` 会写入部分旧版同名图，最后运行 `rebuild_reviewed_figures.py` 才能确保 `outputs/figures/` 保存的是修订版。

可用以下命令检查所有图是否生成：

```powershell
(Get-ChildItem outputs\figures\fig*.png).Count
```

预期为 **17**。

## 4. 如何阅读图表和表格

完整逐图说明见 [outputs/figures/README.md](outputs/figures/README.md)。

| 图号 | 内容 | 阅读要点 |
| --- | --- | --- |
| 1–3 | 节点状态、负载电流、标称总线功率 | 为使脉冲可辨，展示前 120 秒。 |
| 4 | OCV–SOC 曲线 | 点来自项目配置表，不是仓库中可核查的原始测量。 |
| 5–7 | 短时端电压、电池功率、SOC 推算能量 | 仅 10 分钟；图 5 下半部和图 7 使用放大纵轴。 |
| 8–11 | 预测器 A、B、C | 使用能真正到达仿真截止的重负载；A 的极大值使用对数轴；C 参数与该负载匹配。 |
| 12–15 | 40 小时调度模式、功率、能量、预测剩余时间 | 所有策略使用相同硬件电流；自适应在此窗口内没有切换。 |
| 16–17 | 40 小时后 SOC、平均功率与 QoS | 四组都未触发截止；图中没有声称实际续航。 |

修订指标：

- `outputs/reviewed_predictor_metrics.csv`：重负载实验的仿真截止时间与预测 MAE；滚动窗口的前 30 秒作为预热期剔除。
- `outputs/reviewed_scheduling_summary.csv`：每组的观察时长、是否截止、末端 SOC、平均功率和综合 QoS。`cutoff_reached=False` 时，实际续航仅能表述为 **大于 40 小时**。

`outputs/README.md` 标明其余 CSV 的来源与有效性。撰写论文图注或结论前，先阅读 [图表审查记录](docs/FIGURE_REVIEW.md)。

## 5. 运行测试

独立检查不依赖 pytest：

```powershell
.\.venv\Scripts\python.exe run_tests.py
.\.venv\Scripts\python.exe run_battery_tests.py
.\.venv\Scripts\python.exe run_predictor_tests.py
```

pytest 测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

这些检查主要验证状态映射、公式和边界行为；测试通过不等于模型已通过真实电池或传感器硬件验证。

## 6. 参数与工作流

模型参数集中在 `simulation/config.py`，主要包括：

| 参数 | 当前配置 | 作用 |
| --- | --- | --- |
| `BATTERY_Q_NOMINAL_AH` | 2.0 Ah | 标称容量 |
| `BATTERY_R0` | 0.018 Ω | 简化为恒定的电池内阻 |
| `V_TERMINAL_CUTOFF` | 2.5 V | 仿真截止端电压 |
| `OCV_SOC_POINTS` | 27 个配置点 | SOC 到开路电压的线性插值表 |
| `I_SLEEP`, `I_SAMPLING`, `I_TX` | 15 µA、8 mA、120 mA | 初始 10 分钟负载模型使用的电流 |
| `SCHEDULING_MODES` | High、Balanced、Survival | 三档采样与发送周期 |

`rebuild_reviewed_figures.py` 的预测实验另用 **15 µA / 500 mA / 1 A** 的 20/8/2 秒重负载；40 小时调度对比统一使用 **15 µA / 50 mA / 200 mA**。这些值是不同实验场景的假设，不能直接互换。修改配置或重绘脚本后，先运行相关检查，再按第 3 节重建图表，并检查图注与 CSV 是否仍一致。

旧版 `run_predictor_eval.py`、`run_adaptive.py` 和 `simulation/main.py` 保留供历史追溯。它们可能重写旧指标或同名图，且预测与调度结论中的已知问题尚未在这些旧入口中修复。正式报告应使用修订图表与 `reviewed_*.csv`。

## 7. 数据与研究边界

- `data/raw/` 当前只有说明文件，没有 CALCE 原始压缩包；项目不会自动下载或解析它。配置中的 OCV 点应视为示意性输入。若要宣称实验拟合精度，需要取得原始数据并重新标定。
- 电池模型采用固定内阻、固定温度、简化 DC/DC 效率与库仑计数；没有老化、自放电或实测负载噪声。
- 40 小时调度比较没有观察到任何截止，因此不能计算实际续航提升率，也不能根据当前图 17 声称“续航–QoS 折中”已经得到验证。
- 论文使用前应记录软件环境、参数版本、原始数据来源，并以真实电流与放电实验验证模型。

## 8. 常见问题

**`ModuleNotFoundError`：** 确认已在项目根目录运行，且使用同一个虚拟环境安装和执行命令。

**图表看起来又变成旧版：** 运行旧仿真脚本后，重新运行 `rebuild_reviewed_figures.py`。

**找不到原始电池数据：** 当前仓库本来没有该数据；参见 `data/raw/README.md`。现有图表可以作为示意仿真复现，但不能当作 CALCE 原始数据分析结果。

**为什么图 16 不显示“实际续航”：** 因为统一比较只观察了 40 小时，四组都没有达到截止。图 16 展示可观测的末端 SOC。
