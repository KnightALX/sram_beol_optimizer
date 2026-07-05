"""
Tests for WireConfig.max_patterns behavior in WLInterconnectOptimizer.run().

Verify that when max_patterns is set, the optimizer only evaluates that many
patterns; when None, it evaluates everything (limited only by the enumerator).
"""
from __future__ import annotations

import pytest

from sram_beol import WLInterconnectOptimizer, WireConfig


def test_max_patterns_evaluated_when_set(small_config: WireConfig, tmp_path):
    """max_patterns=2 must limit evaluation to exactly 2 patterns.

    中文：max_patterns=2 时只评估 2 个 pattern。
    """
    object.__setattr__(small_config, "max_patterns", 2)
    object.__setattr__(small_config, "output_dir", str(tmp_path / "max_patterns_2"))

    opt = WLInterconnectOptimizer(config=small_config)
    result = opt.run()

    assert result.summary["num_patterns_evaluated"] == 2
    assert len(result.all_records) == 2
    # Pareto and bests may still be valid on the (small) eval set
    assert len(result.pareto_front) >= 1
    assert result.best_far_end is not None
    assert result.best_avg is not None


def test_max_patterns_none_evaluates_all(small_config: WireConfig, tmp_path):
    """max_patterns=None (default) should evaluate all enumerator output.

    中文：max_patterns=None 时不截断，评估枚举器产生的全部 candidate。
    """
    object.__setattr__(small_config, "max_patterns", None)
    object.__setattr__(small_config, "output_dir", str(tmp_path / "max_patterns_none"))

    # Confirm enumerator baseline by temporarily capping then uncapping
    from sram_beol.pattern import PatternEnumerator
    from sram_beol.db import BEOLModelDB

    db = BEOLModelDB(small_config.resolve_csv_path(), config=small_config)
    full_n = len(PatternEnumerator(small_config, db).generate())
    assert full_n > 0, "Sample CSV/enumerator should produce at least one pattern"

    opt = WLInterconnectOptimizer(config=small_config)
    result = opt.run()

    assert result.summary["num_patterns_evaluated"] == full_n
    assert len(result.all_records) == full_n


def test_max_patterns_default_is_none(small_config: WireConfig):
    """WireConfig.max_patterns default must be None (no implicit cap).

    中文：max_patterns 的默认值应为 None（不隐式截断）。
    """
    # Build a fresh config without the max_patterns field
    cfg = WireConfig.from_dict({
        "csv_path": small_config.csv_path,
        "corner": small_config.corner,
        "length_um": small_config.length_um,
        "metals": list(small_config.metals),
        "max_width_um": small_config.max_width_um,
        "segment_um": small_config.segment_um,
        "via_pitch_um": small_config.via_pitch_um,
        "driver_r_ohm": small_config.driver_r_ohm,
        "device_r_ohm": small_config.device_r_ohm,
        "device_c_ff": small_config.device_c_ff,
        "via_r_ohm": small_config.via_r_ohm,
        "output_dir": small_config.output_dir,
    })
    assert cfg.max_patterns is None
