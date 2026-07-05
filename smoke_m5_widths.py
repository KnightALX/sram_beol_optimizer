"""End-to-end smoke test: verify M5 widths strictly within [0.04, 0.07].

构造两类对比场景：
1. 含 M5 layer_constraints (min=0.04, max=0.07) - 应被严格过滤
2. 不含 layer_constraints - 对照组，使用全局 max_width_um=0.06
"""
from __future__ import annotations
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
import re
import tempfile
import statistics

from sram_beol.config import load_wire_config
from sram_beol.optimizer import WLInterconnectOptimizer


def parse_m5_width(desc: str) -> float | None:
    """Extract M5 width from a WirePattern description string."""
    m = re.search(r"M5\((\d+\.\d+)/", desc)
    return float(m.group(1)) if m else None


def make_yaml(with_constraint: bool, fix_m1_m3: bool) -> str:
    """Build a YAML config string for the smoke test."""
    lc_block = ""
    if with_constraint:
        lc_block = """  layer_constraints:
    M5:
      min_width_um: 0.040
      max_width_um: 0.070
"""
    fix_block = ""
    if fix_m1_m3:
        fix_block = """fixed_signals:
  - metal: "M1"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
  - metal: "M3"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
"""
    return f"""
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060
  segment_um: 1.0
  via_pitch_um: 0.5
{lc_block}
electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0

{fix_block}
csv_path: "D:/workspace/project/sram_beol/samples/beol_m1m5.csv"
corner: "typical"
output_dir: "D:/workspace/project/sram_beol/samples/smoke_m5_out"
"""


def run_scenario(name: str, yaml_text: str):
    """Run one scenario and report M5 width distribution."""
    print(f"\n{'=' * 70}")
    print(f"SCENARIO: {name}")
    print('=' * 70)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(yaml_text)
        tmp = f.name
    try:
        cfg = load_wire_config(tmp)
        opt = WLInterconnectOptimizer(config=cfg)
        result = opt.run()

        # Gather all M5 widths
        m5_widths = []
        all_widths = []
        m5_records = []
        for r in result.all_records:
            desc = r["description"]
            w = parse_m5_width(desc)
            if w is not None:
                m5_widths.append(w)
                m5_records.append(r)
            # Also collect any M* width for context
            for m_match in re.finditer(r"(M\d)\((\d+\.\d+)/", desc):
                all_widths.append((m_match.group(1), float(m_match.group(2))))

        print(f"  total patterns evaluated : {len(result.all_records)}")
        print(f"  patterns containing M5   : {len(m5_widths)}")
        print(f"  unique M5 widths         : {sorted(set(round(w, 4) for w in m5_widths))}")

        if m5_widths:
            w_min = min(m5_widths)
            w_max = max(m5_widths)
            print(f"  M5 width min            : {w_min:.4f}")
            print(f"  M5 width max            : {w_max:.4f}")
            print(f"  M5 width mean           : {statistics.mean(m5_widths):.4f}")

            # Show a few example descriptions
            print(f"\n  Sample M5-containing patterns (first 5):")
            for r in m5_records[:5]:
                print(f"    - {r['description']}")

        # Strict check against constraint
        if "M5 layer_constraints [0.04, 0.07]" in name:
            in_range = [w for w in m5_widths if 0.040 - 1e-9 <= w <= 0.070 + 1e-9]
            out_of_range = [w for w in m5_widths if not (0.040 - 1e-9 <= w <= 0.070 + 1e-9)]
            print(f"\n  CONSTRAINT CHECK [0.040, 0.070]:")
            print(f"    in-range  : {len(in_range)}")
            print(f"    out-of-range: {len(out_of_range)} {out_of_range}")
            if out_of_range:
                print(f"  [FAIL] M5 widths violate layer_constraints!")
                return False
            else:
                print(f"  [PASS] All M5 widths strictly within [0.040, 0.070]")
                return True
        elif "no layer_constraints" in name:
            # Baseline: expect widths <= global max 0.060
            over = [w for w in m5_widths if w > 0.060 + 1e-9]
            print(f"\n  BASELINE CHECK (no LC, expect w <= global max 0.060):")
            print(f"    over global max: {over}")
            if over:
                print(f"  [UNEXPECTED] M5 widths exceed global max_width_um=0.060")
                return False
            else:
                print(f"  [PASS] All M5 widths <= global max 0.060")
                return True
        return True
    finally:
        Path(tmp).unlink(missing_ok=True)


# =================== Run all scenarios ===================

# DB ground truth for M5 (typical corner)
print("\n[GROUND TRUTH] M5 widths available in DB:")
print("  M5 typical: {0.02, 0.025, 0.03, 0.04, 0.06}")
print("  Expected intersection with [0.04, 0.07] = {0.04, 0.06}")

# Scenario A: WITH M5 layer_constraints [0.04, 0.07], no fixed_signals (full search)
scenarios = [
    ("A: M5 layer_constraints [0.04, 0.07], NO fixed (full search)",
     make_yaml(with_constraint=True, fix_m1_m3=False)),
    # Scenario B: WITH M5 layer_constraints + fix(M1+M3)
    ("B: M5 layer_constraints [0.04, 0.07], FIX (M1+M3)",
     make_yaml(with_constraint=True, fix_m1_m3=True)),
    # Scenario C: BASELINE no layer_constraints, no fixed
    ("C: no layer_constraints, NO fixed (baseline)",
     make_yaml(with_constraint=False, fix_m1_m3=False)),
]

results = []
for name, yaml_text in scenarios:
    results.append(run_scenario(name, yaml_text))

print("\n" + "=" * 70)
print("FINAL VERDICT")
print("=" * 70)
all_pass = all(results)
print(f"All scenarios pass: {all_pass}")
if all_pass:
    print("[OK] M5 layer_constraints 严格生效 (all widths in [0.04, 0.07])")
else:
    print("[FAIL] 至少一个场景失败")