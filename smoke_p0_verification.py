"""P0/P1 修复的端到端 smoke 验证。"""
import sys
import json
from pathlib import Path

# 设置 UTF-8 输出避免 Windows GBK 编码问题
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from sram_beol.config import load_wire_config as load_config
from sram_beol.optimizer import WLInterconnectOptimizer
from sram_beol.plot import Plotter
from sram_beol.rpt_generator import RptGenerator

ROOT = Path(__file__).parent
CFG = ROOT / "samples" / "config_demo.yaml"
OUT = ROOT / "samples" / "smoke_p0_out"
OUT.mkdir(exist_ok=True)

# 1) 运行 optimizer
cfg = load_config(str(CFG))
print(f"[1] loaded config: metals={getattr(cfg, 'metals', None)}, max_patterns={cfg.max_patterns}")

opt = WLInterconnectOptimizer(config=cfg)
result = opt.run()
print(f"[2] optimizer: total={len(result.all_records)}, pareto={len(result.pareto_front)}")

# 2) 验证 P0-1: per_segment_ps / segment_positions_um / device_positions_um 不再为空
rec0 = result.all_records[0]
print(f"[3] P0-1 check on record 0:")
print(f"  per_segment_ps: len={len(rec0.get('per_segment_ps', []))}, first={rec0.get('per_segment_ps', [None])[0]}")
print(f"  segment_positions_um: len={len(rec0.get('segment_positions_um', []))}, first={rec0.get('segment_positions_um', [None])[0]}")
print(f"  device_positions_um: len={len(rec0.get('device_positions_um', [])) if rec0.get('device_positions_um') else 'NONE'}")

assert len(rec0.get('per_segment_ps', [])) > 0, "P0-1 FAIL: per_segment_ps still empty"
assert len(rec0.get('segment_positions_um', [])) > 0, "P0-1 FAIL: segment_positions_um still empty"
assert rec0.get('device_positions_um') is not None, "P0-1 FAIL: device_positions_um still None"
print("[3] P0-1 PASS")

# 3) 验证 P0-3: rpt_generator 不再崩溃 (静态 API)
md = RptGenerator.generate_string(result, cfg)
out_rpt = OUT / "smoke.rpt"
out_rpt.write_text(md, encoding='utf-8')
print(f"[4] P0-3: .rpt generated, {len(md)} chars, file={out_rpt}")
assert "BEOL INTERCONNECT" in md.upper() or "SUMMARY" in md.upper(), "rpt content sanity check"
# 同时验证 P1-1: Pareto 维度已对齐到 far_prop vs avg_prop (在 rpt 报告里体现)
assert "far_prop vs avg_prop" in md, "P1-1 FAIL: Pareto dimension not aligned to far vs avg"
print("[4] P0-3 PASS / [5] P1-1 PASS (Pareto dim aligned in .rpt)")

# 5) 验证 P0-1 plot 路径 (Plotter 实例)
plotter = Plotter(OUT)
p_pareto = plotter.plot_pareto_scatter(result)
p_delay = plotter.plot_delay_profiles(result)
import os
print(f"[6] P0-1 plots: pareto={os.path.getsize(p_pareto)} bytes ({p_pareto.name}), delay={os.path.getsize(p_delay)} bytes ({p_delay.name})")
assert os.path.getsize(p_delay) > 5000, "delay_profile.png suspiciously small"
print("[6] P0-1 PASS (delay plot has content)")

# 6) 验证 P1-3: max_patterns
cfg2 = load_config(str(CFG))
from dataclasses import replace
cfg2 = replace(cfg2, max_patterns=3)
opt2 = WLInterconnectOptimizer(config=cfg2)
result2 = opt2.run()
print(f"[7] P1-3: with max_patterns=3, evaluated={len(result2.all_records)}")
assert len(result2.all_records) <= 3, f"P1-3 FAIL: max_patterns not honored, got {len(result2.all_records)}"
print("[7] P1-3 PASS")

print("\n=== ALL P0/P1 SMOKE CHECKS PASSED ===")
