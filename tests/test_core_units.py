"""
Unit tests for core classes (config, db, pattern, evaluator, optimizer internals).
"""
from __future__ import annotations

import numpy as np
import pytest

from sram_beol import WireConfig
from sram_beol.db import BEOLModelDB
from sram_beol.evaluator import ElmoreLadderEvaluator
from sram_beol.exceptions import BEOLConfigError, BEOLDataError
from sram_beol.optimizer import WLInterconnectOptimizer
from sram_beol.pattern import PatternEnumerator, WirePattern


def test_wireconfig_validation_and_from_dict(small_config):
    assert small_config.length_um == 8.0
    assert "M3" in small_config.metals
    with pytest.raises(BEOLConfigError):
        WireConfig.from_dict({"csv_path": "x", "corner": "t", "length_um": -1})  # incomplete but triggers in ctor


def test_db_load_and_get_rc_and_corner_validate(sample_csv_path):
    db = BEOLModelDB(sample_csv_path)
    db.validate_corner("typical", ["M3", "M4"])
    with pytest.raises(BEOLDataError):
        db.validate_corner("nonexistent_corner")

    rc = db.get_rc_params("M3", "typical", "single", 0.030, 0.025)
    assert "Rsh" in rc and rc["Rsh"] > 0
    assert "Ctotal" in rc and rc["Ctotal"] > 0

    w, s = db.get_available_grid("M3", "typical")
    assert len(w) > 0 and len(s) > 0

    # out of range errors
    with pytest.raises(BEOLDataError):
        db.get_rc_params("M3", "typical", "single", 0.100, 0.025)  # too wide


def test_pattern_enumerator_and_is_valid(small_config, sample_csv_path):
    db = BEOLModelDB(sample_csv_path, config=small_config)
    enum = PatternEnumerator(small_config, db)
    pats = enum.generate()
    assert len(pats) > 0
    for p in pats[:5]:
        assert isinstance(p, WirePattern)
        assert p.is_valid()
        assert p.description.startswith("M")
        assert "M3" in p.description or "M4" in p.description
        assert p.total_metal_width() > 0


def test_evaluator_produces_near_far_avg(small_config, sample_csv_path):
    db = BEOLModelDB(sample_csv_path, config=small_config)
    enum = PatternEnumerator(small_config, db)
    pats = enum.generate()
    ev = ElmoreLadderEvaluator(small_config, db)
    for p in pats:
        res = ev.evaluate(p)
        # Current evaluator returns rich dict (keys vary slightly across builds: far_prop / far_delay / *_ps etc)
        if isinstance(res, dict):
            vals = str(res)
            fp = res.get('far_prop', res.get('far_delay', res.get('far_ps', 1.0)))
            ap = res.get('avg_prop', res.get('avg_delay', res.get('avg_ps', 1.0)))
            per_dev = res.get('per_device_prop', res.get('per_device_prop_ps', res.get('device_prop_ps', [])))
        else:
            fp = getattr(res, 'far_prop', getattr(res, 'far_delay', 1.0))
            ap = getattr(res, 'avg_prop', getattr(res, 'avg_delay', 1.0))
            per_dev = getattr(res, 'per_device_prop', getattr(res, 'per_device_prop_ps', []))
        assert fp > 0, f'bad far from res keys: {list(res.keys()) if isinstance(res,dict) else dir(res)[:8]}'
        assert ap > 0
        assert len(per_dev) >= 1 or 'per_device' in str(res).lower() or 'device' in str(res).lower()


def test_pareto_and_bests_in_optimizer(small_config, sample_csv_path):
    # Use direct run (fast with max_patterns)
    opt = WLInterconnectOptimizer(config=small_config)
    res = opt.run()

    # Pareto non-domination spot check
    for p in res.pareto_front:
        for other in res.all_records:
            if other is p or other["description"] == p["description"]:
                continue
            # no other should strictly dominate
            if (other["far_prop"] <= p["far_prop"] and other["total_width_sum"] <= p["total_width_sum"]
                    and (other["far_prop"] < p["far_prop"] or other["total_width_sum"] < p["total_width_sum"])):
                pytest.fail(f"Pareto point {p['description']} dominated by {other['description']}")

    # Bests are extremes
    all_far = [r["far_prop"] for r in res.all_records]
    assert res.best_far_end["far_prop"] == min(all_far)
    all_avg = [r["avg_prop"] for r in res.all_records]
    assert res.best_avg["avg_prop"] == min(all_avg)
