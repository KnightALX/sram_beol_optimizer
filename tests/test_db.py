"""
Comprehensive unit tests for BEOLModelDB (design Sections 3/4).

Covers:
- Strict CSV loading + column validation (missing/extra -> BEOLDataError)
- Exact corner validation (global + per-structure) with available corners in error
- get_available_grid in both calling conventions (enumeration + full), filtering
- get_rc_params at exact data points (accuracy), interpolation, shape fallback
- No extrapolation (convex hull + sparse point tolerance)
- Physical monotonicity post-processing (Rsh non-inc with W, C* non-inc with S)
  tested both on sample data (already mono) and on synthetic violation data
- Stub mode (no-arg ctor) compatibility for other modules/tests
- Error messages and exception attributes
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import pytest

from sram_beol.db import BEOLModelDB
from sram_beol.exceptions import BEOLDataError


SAMPLE_CSV = Path("D:/workspace/project/sram_beol/samples/beol_sample.csv")


def _write_temp_csv(df: pd.DataFrame) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    p = Path(tmp.name)
    tmp.close()
    df.to_csv(p, index=False)
    return p


@pytest.fixture(scope="module")
def real_db() -> BEOLModelDB:
    """Real DB loaded from the project sample (rich typical data for M3/M4)."""
    assert SAMPLE_CSV.exists(), f"Sample CSV missing: {SAMPLE_CSV}"
    return BEOLModelDB(SAMPLE_CSV)


def test_stub_mode_noarg_ctor_and_methods():
    """No-arg construction must still work for PatternEnumerator / test_pattern.py"""
    db = BEOLModelDB()
    assert db.csv_path is None
    # enum style used by pattern
    w, s = db.get_available_grid("M3", 0.040)
    assert isinstance(w, list) and isinstance(s, list)
    assert 0.015 <= min(w) and max(w) <= 0.040
    # rc returns plausible dict
    rc = db.get_rc_params("M3", "any", "A", 0.025, 0.02)
    assert set(rc.keys()) == {"Rsh", "Ctotal", "Cc", "Cbottom"}
    assert rc["Rsh"] > 0
    # validate is no-op
    db.validate_corner("nonexistent", structures=["M1", "M2"])
    # other helpers
    assert "M3" in db.get_available_structures()
    assert isinstance(db.get_available_corners(), list)


def test_strict_csv_column_validation(tmp_path: Path):
    # missing columns
    bad = tmp_path / "missing.csv"
    pd.DataFrame({"Width": [0.02]}).to_csv(bad, index=False)
    with pytest.raises(BEOLDataError) as exc:
        BEOLModelDB(bad)
    msg = str(exc.value).lower()
    assert "column" in msg or "strict" in msg or "missing" in msg

    # extra columns (strict)
    extra = tmp_path / "extra.csv"
    df = pd.DataFrame({
        "Structure": ["M3"], "Corner": ["typical"], "ShapeColor": ["single"],
        "Width": [0.02], "Space": [0.02], "Rsh": [0.3], "Ctotal": [0.2],
        "Cc": [0.1], "Cbottom": [0.05], "ExtraJunk": ["x"]
    })
    df.to_csv(extra, index=False)
    with pytest.raises(BEOLDataError) as exc:
        BEOLModelDB(extra)
    msg = str(exc.value).lower()
    assert "extra" in msg or "unexpected" in msg or "exact" in msg


def test_file_not_found_raises():
    with pytest.raises(BEOLDataError) as exc:
        BEOLModelDB("/this/does/not/exist_12345.csv")
    assert "not found" in str(exc.value).lower()


def test_real_load_groups_and_metadata(real_db: BEOLModelDB):
    assert len(real_db.get_available_corners()) >= 3
    assert "typical" in real_db.get_available_corners()
    structs = real_db.get_available_structures()
    assert "M3" in structs and "M4" in structs
    # groups built (10 in sample: 3 sc *2 metals for typical + a few for fast/slow)
    assert hasattr(real_db, "_interpolators")
    assert len(real_db._interpolators) >= 8


def test_validate_corner_exact_and_per_structure(real_db: BEOLModelDB):
    # success global + per struct
    real_db.validate_corner("typical")
    real_db.validate_corner("typical", structures=["M3", "M4"])
    real_db.validate_corner("fast", structures=["M3"])
    real_db.validate_corner("slow", structures=["M4"])

    # missing corner (global)
    with pytest.raises(BEOLDataError) as exc:
        real_db.validate_corner("nonexistent_corner_zzz")
    assert "not found exactly" in str(exc.value)
    assert getattr(exc.value, "available_corners", None)
    assert "typical" in exc.value.available_corners

    # bogus structure (exercises the per-structure not-present path)
    with pytest.raises(BEOLDataError) as exc2:
        real_db.validate_corner("typical", structures=["M9_never"])
    assert "Structure" in str(exc2.value) or "not present" in str(exc2.value).lower() or "M9_never" in str(exc2.value)


def test_get_available_grid_both_styles_and_filter(real_db: BEOLModelDB):
    # full explicit
    w_full, s_full = real_db.get_available_grid("M3", "typical", "ABA")
    assert isinstance(w_full, list)
    assert 0.020 in w_full and 0.040 in w_full
    assert 0.020 in s_full and 0.030 in s_full

    # union when shape=None
    w_u, s_u = real_db.get_available_grid("M3", "typical", None)
    assert set(w_full) == set(w_u)

    # enum style + max_width filter (used by PatternEnumerator)
    w_f, s_f = real_db.get_available_grid("M3", 0.030)
    assert max(w_f) <= 0.030 + 1e-9
    assert all(ww >= 0.020 for ww in w_f)

    # also kw form
    w_kw, _ = real_db.get_available_grid("M4", max_width_um=0.025)
    assert max(w_kw) <= 0.025 + 1e-9


def test_get_rc_params_exact_accuracy(real_db: BEOLModelDB):
    """At known CSV points the returned values must match data within float tol."""
    # From sample row: M3,typical,single,0.030,0.025,0.265,0.288,0.125,0.092
    rc = real_db.get_rc_params("M3", "typical", "single", 0.030, 0.025)
    assert abs(rc["Rsh"] - 0.265) < 1e-6
    assert abs(rc["Ctotal"] - 0.288) < 1e-6
    assert abs(rc["Cc"] - 0.125) < 1e-6
    assert abs(rc["Cbottom"] - 0.092) < 1e-6

    # Another for ABA (C's are larger)
    rc_aba = real_db.get_rc_params("M3", "typical", "ABA", 0.030, 0.025)
    assert abs(rc_aba["Rsh"] - 0.265) < 1e-6  # Rsh identical
    assert rc_aba["Ctotal"] > rc["Ctotal"] + 0.1  # parallel colors have higher C


def test_get_rc_params_shape_fallback_for_ranking(real_db: BEOLModelDB):
    """Internal calls use shape_color='A' which does not exist; must fallback without error."""
    rc = real_db.get_rc_params("M3", "typical", "A", 0.035, 0.020)  # 'A' not in data
    assert rc["Rsh"] > 0
    # should have used single or ABA etc, Rsh same
    rc2 = real_db.get_rc_params("M3", "typical", "single", 0.035, 0.020)
    assert abs(rc["Rsh"] - rc2["Rsh"]) < 1e-9


def test_no_extrapolation_outside_hull_or_points(real_db: BEOLModelDB):
    # outside width
    with pytest.raises(BEOLDataError) as exc:
        real_db.get_rc_params("M3", "typical", "single", 0.005, 0.025)
    assert "outside" in str(exc.value).lower() or "hull" in str(exc.value).lower() or "range" in str(exc.value).lower()

    # outside space
    with pytest.raises(BEOLDataError) as exc:
        real_db.get_rc_params("M3", "typical", "ABA", 0.030, 0.010)
    assert "outside" in str(exc.value).lower()

    # 1-pt group (fast) - only exact point allowed
    # From sample: M3,fast,single,0.030,0.025,...
    rc_ok = real_db.get_rc_params("M3", "fast", "single", 0.030, 0.025)
    assert rc_ok["Rsh"] > 0
    with pytest.raises(BEOLDataError) as exc:
        real_db.get_rc_params("M3", "fast", "single", 0.030, 0.026)  # off
    assert "outside" in str(exc.value).lower() or "point" in str(exc.value).lower()


def test_monotonicity_on_sample_data(real_db: BEOLModelDB):
    """Sample data already obeys the laws; after post-proc the returned surface must too."""
    # Rsh non-increasing with Width (fixed space)
    fixed_s = 0.025
    ws = [0.020, 0.025, 0.030, 0.035, 0.040]
    rsh_seq: List[float] = []
    for ww in ws:
        rsh_seq.append(real_db.get_rc_params("M3", "typical", "ABA", ww, fixed_s)["Rsh"])
    for i in range(1, len(rsh_seq)):
        assert rsh_seq[i] <= rsh_seq[i-1] + 1e-9, f"Rsh increased with width: {rsh_seq}"

    # Ctotal (and others) non-increasing with Space (fixed width)
    fixed_w = 0.030
    ss = [0.020, 0.025, 0.030]
    ctot_seq = [real_db.get_rc_params("M3", "typical", "BAB", fixed_w, s)["Ctotal"] for s in ss]
    for i in range(1, len(ctot_seq)):
        assert ctot_seq[i] <= ctot_seq[i-1] + 1e-9, f"Ctotal increased with space: {ctot_seq}"

    cc_seq = [real_db.get_rc_params("M4", "typical", "single", fixed_w, s)["Cc"] for s in ss]
    for i in range(1, len(cc_seq)):
        assert cc_seq[i] <= cc_seq[i-1] + 1e-9


def test_monotonicity_postproc_enforces_on_violation_data(tmp_path: Path):
    """
    Create data with deliberate violations in raw table.
    After loading, queried values must still be monotonic (post-proc lowered violators).
    """
    # Build a small but >=3 pt grid with violation
    rows = []
    # Rsh violation: at w=0.03 Rsh higher than at 0.02 (for same s)
    base = {"Structure": "M3", "Corner": "viol", "ShapeColor": "X"}
    for w, r in [(0.020, 0.500), (0.030, 0.520), (0.040, 0.480)]:  # 0.520 violation
        rows.append({**base, "Width": w, "Space": 0.020, "Rsh": r, "Ctotal": 0.200 - 0.01*(w-0.02), "Cc": 0.100, "Cbottom": 0.050})
    # C violation: at larger space C higher
    for s, c in [(0.020, 0.180), (0.025, 0.190), (0.030, 0.170)]:  # 0.190 violation
        rows.append({**base, "Width": 0.025, "Space": s, "Rsh": 0.490, "Ctotal": c, "Cc": c*0.6, "Cbottom": 0.040})

    df = pd.DataFrame(rows)
    viol_csv = _write_temp_csv(df)
    try:
        db = BEOLModelDB(viol_csv)

        # Rsh at w=0.03 (and 0.04) must now be <= Rsh at 0.02
        r02 = db.get_rc_params("M3", "viol", "X", 0.020, 0.020)["Rsh"]
        r03 = db.get_rc_params("M3", "viol", "X", 0.030, 0.020)["Rsh"]
        r04 = db.get_rc_params("M3", "viol", "X", 0.040, 0.020)["Rsh"]
        assert r03 <= r02 + 1e-9, f"Post-proc failed to enforce Rsh mono: {r02} -> {r03}"
        assert r04 <= r03 + 1e-9

        # Ctotal at s=0.025 must be <= at s=0.020 (fixed w)
        c020 = db.get_rc_params("M3", "viol", "X", 0.025, 0.020)["Ctotal"]
        c025 = db.get_rc_params("M3", "viol", "X", 0.025, 0.025)["Ctotal"]
        c030 = db.get_rc_params("M3", "viol", "X", 0.025, 0.030)["Ctotal"]
        assert c025 <= c020 + 1e-9, f"Post-proc failed for Ctotal: {c020} -> {c025}"
        assert c030 <= c025 + 1e-9
    finally:
        try:
            viol_csv.unlink()
        except Exception:
            pass


def test_get_rc_params_returns_positive_and_sane(real_db: BEOLModelDB):
    rc = real_db.get_rc_params("M4", "typical", "BAB", 0.035, 0.025)
    assert rc["Rsh"] > 0
    assert rc["Ctotal"] > 0
    assert rc["Cc"] >= 0
    assert rc["Cbottom"] >= 0


def test_available_grid_for_1pt_corner(real_db: BEOLModelDB):
    # fast has only 1pt per structure
    w, s = real_db.get_available_grid("M3", "fast", "single")
    assert len(w) == 1 and len(s) == 1
    assert abs(w[0] - 0.030) < 1e-9
    assert abs(s[0] - 0.025) < 1e-9


if __name__ == "__main__":
    pytest.main([__file__, "-q", "--tb=short"])
