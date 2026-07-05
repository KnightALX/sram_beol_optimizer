#!/usr/bin/env python3
"""Quick-start script: run optimizer on sample data → launch Dashboard.
快速启动脚本：用 sample 数据运行优化器 → 启动 Dashboard。

Usage:
    cd D:\workspace\project\sram_beol
    python run_dashboard.py

This will:
  1. Load samples/config_small.yaml (M3/M4, 20μm WL)
  2. Load samples/beol_sample.csv (BEOL RC model for typical corner)
  3. Run WLInterconnectOptimizer → OptimizationResult
  4. Write report.md + results.csv + beol_optimization.rpt into samples/results_small/
  5. Launch Dash dashboard on http://localhost:8050

Press Ctrl+C in the terminal to stop the dashboard.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from sram_beol import WLInterconnectOptimizer
from sram_beol.config import configure_logging


def main() -> int:
    # Logging — 日志
    configure_logging("INFO")

    # Resolve sample paths relative to project root
    # 用相对路径解析 sample 文件路径
    config_path = PROJECT_ROOT / "samples" / "config_m1m5_fix_m1.yaml"
    csv_path = PROJECT_ROOT / "samples" / "beol_m1m5.csv"

    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}")
        return 1
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return 1

    print("=" * 70)
    print("  SRAM BEOL Optimizer — Dashboard Quick Start")
    print("=" * 70)
    print(f"  Config : {config_path}")
    print(f"  CSV    : {csv_path}")
    print(f"  Metals : M1-M5  (20 um WL, typical corner)")
    print()
    print("  Running optimization...")
    print("-" * 70)

    # Load config with corrected csv_path
    # 加载配置，修正 csv_path 为绝对路径
    from sram_beol.config import load_wire_config
    cfg = load_wire_config(config_path, overrides={
        "csv_path": str(csv_path.resolve()),
        "output_dir": str((PROJECT_ROOT / "samples" / "results_demo").resolve()),
    })

    # Create optimizer and run
    # 创建优化器并运行
    opt = WLInterconnectOptimizer(config=cfg)
    result = opt.run()

    # Generate report + .rpt + CSV
    # 生成报告 + .rpt + CSV
    opt.generate_report(result)

    print()
    print("=" * 70)
    print("  Optimization complete!")
    print(f"  Patterns evaluated : {len(result.all_records)}")
    print(f"  Pareto-optimal     : {len(result.pareto_front)}")
    print(f"  Best far-end       : {result.best_far_end['description']}")
    print(f"  Best avg           : {result.best_avg['description']}")
    print()
    print("  Reports written to : samples/results_small/")
    print("    - report.md")
    print("    - results.csv")
    print("    - beol_optimization.rpt")
    print()
    print("  Launching Dashboard on http://localhost:8050 ...")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 70)

    # Launch Dashboard
    # 启动 Dashboard
    opt.launch_dashboard(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
