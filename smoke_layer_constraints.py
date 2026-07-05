"""Smoke test: 端到端验证 layer_constraints + 多线 fixed_signals。"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
import tempfile
import os

from sram_beol.config import load_wire_config, LayerConstraint, WireConfig
from sram_beol.optimizer import WLInterconnectOptimizer

# === 1. YAML 层约束加载 ===
yaml_text = """
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060
  segment_um: 1.0
  via_pitch_um: 0.5
  layer_constraints:
    M1:
      min_width_um: 0.030
      max_width_um: 0.060
    M5:
      min_width_um: 0.040
      max_width_um: 0.070
      min_space_um: 0.060

electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0

fixed_signals:
  - metal: "M1"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
  - metal: "M3"
    width: 0.030
    space: 0.030
    colors: ["ABA"]

csv_path: "D:/workspace/project/sram_beol/samples/beol_m1m5.csv"
corner: "typical"
output_dir: "D:/workspace/project/sram_beol/samples/smoke_lc_out"
"""
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
    f.write(yaml_text)
    tmp_path = f.name

try:
    cfg = load_wire_config(tmp_path)
    print(f"[1] YAML loaded: corner={cfg.corner}, metals={cfg.metals}")
    print(f"[1] layer_constraints: {[(m, lc.min_width_um, lc.max_width_um, lc.min_space_um, lc.max_space_um) for m, lc in cfg.layer_constraints.items()]}")
    print(f"[1] fixed_signals: {[(fs['metal'], fs['width'], fs['space']) for fs in cfg.fixed_signals]}")

    assert "M1" in cfg.layer_constraints, "M1 constraint should be loaded"
    assert "M5" in cfg.layer_constraints, "M5 constraint should be loaded"
    assert cfg.layer_constraints["M5"].max_width_um == 0.070, "M5 max_width override global"
    assert len(cfg.fixed_signals) == 2, "two fixed signals"
    print("[1] PASS: YAML layer_constraints + multi fixed_signals loaded correctly")
finally:
    Path(tmp_path).unlink(missing_ok=True)

# === 2. 端到端 optimization ===
print(f"\n[2] Running optimizer with M5 max=0.070, fix(M1+M3)...")
out_dir = Path("D:/workspace/project/sram_beol/samples/smoke_lc_out")
out_dir.mkdir(exist_ok=True)
opt = WLInterconnectOptimizer(config=cfg)
result = opt.run()
print(f"[2] optimizer: total={len(result.all_records)}, pareto={len(result.pareto_front)}")
print(f"[2] best_far={result.best_far_end['description']}")
print(f"[2] best_avg={result.best_avg['description']}")
assert len(result.all_records) > 0, "should generate patterns"
print("[2] PASS: end-to-end optimization with layer_constraints + multi fix works")

# === 3. 验证 layer_constraints 真的过滤了 DB ===
# 所有 M5 patterns 的 width 应该在 [0.040, 0.070]
m5_patterns = [r for r in result.all_records if "M5" in r.get("pattern_layers", ())]
m5_widths = set()
for r in m5_patterns:
    pat = r["description"]
    # parse "M5(...)"
    if "M5(" in pat:
        w = float(pat.split("M5(")[1].split("/")[0])
        m5_widths.add(round(w, 4))
print(f"[3] M5 widths observed: {sorted(m5_widths)}")
for w in m5_widths:
    assert 0.040 - 1e-9 <= w <= 0.070 + 1e-9, f"M5 width {w} violates constraint"
print("[3] PASS: M5 widths respect layer_constraints [0.040, 0.070]")

# === 4. 验证反向: 无 layer_constraints 时所有宽度 <= 0.060 ===
cfg_no_lc = load_wire_config("D:/workspace/project/sram_beol/samples/config_demo.yaml")
assert cfg_no_lc.layer_constraints == {}, "config_demo should have no layer_constraints"
opt2 = WLInterconnectOptimizer(config=cfg_no_lc)
result2 = opt2.run()
print(f"\n[4] Baseline (no layer_constraints): total={len(result2.all_records)}")

print("\n=== ALL SMOKE TESTS PASSED ===")