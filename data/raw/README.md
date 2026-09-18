# 原始数据目录 — data/raw/

本目录用于存放 CALCE 电池研究原始数据文件。

## 需要下载的文件

请将以下文件从 CALCE 网站下载后放入此目录：

### 主要文件（25°C OCV-SOC 数据）

| 文件名 | 说明 | 下载链接 |
|--------|------|----------|
| `SP1_25C_LC_OCV_11_5_2015.zip` | Low Current OCV, Sample 1, 25°C | [下载](https://web.calce.umd.edu/batteries/data/SP1_25C_LC_OCV_11_5_2015.zip) |
| `SP1_25C_IC_OCV_12_2_2015.zip` | Incremental Current OCV, Sample 1, 25°C | [下载](https://web.calce.umd.edu/batteries/data/SP1_25C_IC_OCV_12_2_2015.zip) |

### 可选文件（对比数据）

| 文件名 | 说明 | 下载链接 |
|--------|------|----------|
| `SP3_25C_LC_OCV_11_16_2015.zip` | Low Current OCV, Sample 2, 25°C | [下载](https://web.calce.umd.edu/batteries/data/SP3_25C_LC_OCV_11_16_2015.zip) |
| `SP3_25C_IC_OCV_12_2_2015.zip` | Incremental Current OCV, Sample 2, 25°C | [下载](https://web.calce.umd.edu/batteries/data/SP3_25C_IC_OCV_12_2_2015.zip) |

### 全部温度数据（可选）

| 文件名 | 温度 | 下载链接 |
|--------|------|----------|
| `SP1_0C_LC_OCV_02_24_2016.zip` | 0°C | [下载](https://web.calce.umd.edu/batteries/data/SP1_0C_LC_OCV_02_24_2016.zip) |
| `SP1_45C_LC_OCV_11_21_2015.zip` | 45°C | [下载](https://web.calce.umd.edu/batteries/data/SP1_45C_LC_OCV_11_21_2015.zip) |

## CALCE 数据主页

https://calce.umd.edu/battery-data

## 当前状态

当前仿真使用的是从 CALCE 数据手动提取的 27 个 OCV-SOC 典型数据点，
存储在 `simulation/config.py` 的 `OCV_SOC_POINTS` 列表中。

如果需要完整原始数据，请下载上述 zip 文件。
