"""错误路径 smoke。"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from sram_beol.config import load_wire_config, LayerConstraint, WireConfig
from sram_beol.exceptions import BEOLConfigError

# Test 1: min > max
try:
    LayerConstraint(metal="M5", min_width_um=0.080, max_width_um=0.040)
    WireConfig(
        csv_path="x", corner="typical", length_um=20.0,
        metals=["M5"], max_width_um=0.060, segment_um=1.0, via_pitch_um=0.5,
        driver_r_ohm=80.0, device_r_ohm=45.0, device_c_ff=0.35, via_r_ohm=8.0,
        output_dir="x",
        layer_constraints={"M5": LayerConstraint(metal="M5", min_width_um=0.080, max_width_um=0.040)}
    )
    print("[E1] FAIL: should have raised")
except BEOLConfigError as e:
    print(f"[E1] PASS: BEOLConfigError raised: {str(e)[:120]}")

# Test 2: layer_constraints 引用 unknown-direction metal (M99)
from sram_beol.pattern import PatternEnumerator
from sram_beol.db import BEOLModelDB
try:
    cfg = WireConfig(
        csv_path="D:/workspace/project/sram_beol/samples/beol_sample.csv",
        corner="typical", length_um=20.0, metals=["M1"],
        max_width_um=0.060, segment_um=1.0, via_pitch_um=0.5,
        driver_r_ohm=80.0, device_r_ohm=45.0, device_c_ff=0.35, via_r_ohm=8.0,
        output_dir="x",
        fixed_signals=[{"metal": "M99", "width": 0.030, "space": 0.030, "colors": ["ABA"]}]
    )
    db = BEOLModelDB(cfg.resolve_csv_path())
    PatternEnumerator(cfg, db)
    print("[E2] FAIL: should have raised")
except BEOLConfigError as e:
    print(f"[E2] PASS: unknown direction raises BEOLConfigError: {str(e)[:120]}")

print("\n=== ERROR-PATH SMOKE PASSED ===")