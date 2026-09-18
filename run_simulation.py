"""
====================================================================
项目根入口 — run_simulation.py
====================================================================

用法：
    python run_simulation.py

作用：
    - 将项目根目录添加到 sys.path，使 Python 能找到 simulation 包
    - 调用 simulation.main() 执行完整的仿真流程

如果不通过此脚本运行，也可以直接：
    python -m simulation.main
（但需要确保当前工作目录是项目根目录）

论文：《面向无人值守传感节点的剩余运行时间预测与自适应能量调度方法研究》

====================================================================
"""
import sys
import os

# 将项目根目录（本脚本所在目录）加入模块搜索路径
# 这样 import simulation.config 等语句才能正确解析
sys.path.insert(0, os.path.dirname(__file__))

from simulation.main import main

if __name__ == "__main__":
    main()
