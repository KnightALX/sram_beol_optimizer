"""Unit tests for WirePattern and PatternEnumerator.

Covers:
- Frozen dataclass behavior, normalization, description formatting
- is_valid() strict rule enforcement (same-layer parallel W/S sharing + multi-color,
  cross-layer independence, invalid cases)
- key() hashability, equality, use in sets
- PatternEnumerator.generate():
  * Produces only valid patterns
  * Respects layer count pruning (1..MAX_LAYERS)
  * Respects per-layer WS candidate pruning (top-by-R)
  * Includes same-layer multi-color combos (ABA+BAB etc.)
  * Cross-layer patterns have independent specs
  * Uses only metals from config, grids filtered by max_width
  * Deterministic output
  * Empty / edge config cases
- Direct construction of "would-be-invalid" patterns to test is_valid False paths

All tests use the real (stub) DB and WireConfig so that grid + R-ranking code paths
are exercised without requiring a real CSV (per current phase; full DB in Sec 4).

Run with: python -m unittest tests.test_pattern -v
"""

import unittest
from typing import Any

from sram_beol.config import WireConfig
from sram_beol.db import BEOLModelDB
from sram_beol.pattern import WirePattern, PatternEnumerator
from sram_beol.exceptions import BEOLPatternError


class TestWirePatternBasics(unittest.TestCase):
    """Basic construction, properties, description, frozen behavior."""

    def setUp(self):
        self.valid_specs = {
            "M3": {"width": 0.040, "space": 0.020, "colors": ("ABA", "BAB")},
            "M4": {"width": 0.035, "space": 0.025, "colors": ("ABA",)},
        }

    def test_frozen_dataclass_and_normalization(self):
        # Accept list for layers, list for colors, non-tuple specs input
        p = WirePattern(
            layers=["M3", "M4"],
            specs={
                "M3": {"width": "0.040", "space": 0.020, "colors": ["ABA", "BAB"]},
                "M4": {"width": 0.035, "space": "0.025", "colors": ["ABA"]},
            },
        )
        self.assertIsInstance(p.layers, tuple)
        self.assertEqual(p.layers, ("M3", "M4"))
        self.assertIsInstance(p.specs["M3"]["colors"], tuple)
        self.assertEqual(p.specs["M3"]["colors"], ("ABA", "BAB"))
        self.assertEqual(p.specs["M3"]["width"], 0.040)
        self.assertEqual(p.specs["M4"]["space"], 0.025)

    def test_description_exact_format(self):
        p = WirePattern(layers=("M3", "M4"), specs=self.valid_specs)
        desc = p.description
        self.assertEqual(desc, "M3(0.040/0.020/ABA+BAB)+M4(0.035/0.025/ABA)")
        self.assertEqual(str(p), desc)

    def test_description_single_layer_single_color(self):
        p = WirePattern(
            layers=("M2",),
            specs={"M2": {"width": 0.018, "space": 0.012, "colors": ("A",)}},
        )
        self.assertEqual(p.description, "M2(0.018/0.012/A)")

    def test_frozen_prevents_field_rebind(self):
        p = WirePattern(layers=("M1",), specs={"M1": {"width": 0.01, "space": 0.01, "colors": ("A",)}})
        with self.assertRaises(Exception):  # frozen dataclass raises FrozenInstanceError (sub of AttributeError)
            p.layers = ("M2",)

    def test_hashable_and_equality_via_key(self):
        p1 = WirePattern(layers=("M3", "M4"), specs=self.valid_specs)
        p2 = WirePattern(layers=("M3", "M4"), specs=self.valid_specs)
        p3 = WirePattern(
            layers=("M3",),
            specs={"M3": {"width": 0.040, "space": 0.020, "colors": ("ABA", "BAB")}},
        )
        self.assertEqual(p1, p2)
        self.assertEqual(hash(p1), hash(p2))
        self.assertNotEqual(p1, p3)

        s = {p1, p2, p3}
        self.assertEqual(len(s), 2)


class TestWirePatternIsValidRules(unittest.TestCase):
    """Strict enforcement of same-layer vs cross-layer rules + other validity."""

    def test_valid_single_layer(self):
        p = WirePattern(
            layers=("M4",),
            specs={"M4": {"width": 0.03, "space": 0.02, "colors": ("ABA",)}},
        )
        self.assertTrue(p.is_valid())

    def test_valid_cross_layer_independent_ws_color(self):
        p = WirePattern(
            layers=("M2", "M4"),
            specs={
                "M2": {"width": 0.02, "space": 0.015, "colors": ("A",)},
                "M4": {"width": 0.035, "space": 0.025, "colors": ("BAB",)},
            },
        )
        self.assertTrue(p.is_valid())
        # Independence is structural: different entries may (and do) have different w/s/c
        self.assertNotEqual(p.specs["M2"]["width"], p.specs["M4"]["width"])
        self.assertNotEqual(p.specs["M2"]["colors"], p.specs["M4"]["colors"])

    def test_valid_same_layer_multiple_colors_same_ws(self):
        """Core same-layer parallel rule: same W/S + multiple colors allowed."""
        p = WirePattern(
            layers=("M3",),
            specs={"M3": {"width": 0.040, "space": 0.020, "colors": ("ABA", "BAB")}},
        )
        self.assertTrue(p.is_valid())
        self.assertEqual(len(p.specs["M3"]["colors"]), 2)
        self.assertEqual(p.specs["M3"]["width"], 0.040)  # shared

    def test_invalid_empty_layers(self):
        p = WirePattern(layers=(), specs={})
        self.assertFalse(p.is_valid())

    def test_invalid_duplicate_layers(self):
        p = WirePattern(
            layers=("M3", "M3"),
            specs={"M3": {"width": 0.03, "space": 0.02, "colors": ("A",)}},
        )
        self.assertFalse(p.is_valid())

    def test_invalid_inconsistent_layers_vs_specs(self):
        p = WirePattern(
            layers=("M3", "M4"),
            specs={"M3": {"width": 0.03, "space": 0.02, "colors": ("A",)}},
        )
        self.assertFalse(p.is_valid())

    def test_invalid_missing_color_or_empty_colors(self):
        p1 = WirePattern(
            layers=("M1",),
            specs={"M1": {"width": 0.02, "space": 0.01, "colors": ()}},
        )
        self.assertFalse(p1.is_valid())

        p2 = WirePattern(
            layers=("M1",),
            specs={"M1": {"width": 0.02, "space": 0.01, "colors": []}},
        )
        self.assertFalse(p2.is_valid())

    def test_invalid_non_positive_dimensions(self):
        p1 = WirePattern(
            layers=("M2",),
            specs={"M2": {"width": 0.0, "space": 0.02, "colors": ("A",)}},
        )
        self.assertFalse(p1.is_valid())

        p2 = WirePattern(
            layers=("M2",),
            specs={"M2": {"width": 0.02, "space": -0.01, "colors": ("A",)}},
        )
        self.assertFalse(p2.is_valid())

    def test_invalid_missing_keys_in_spec(self):
        p = WirePattern(
            layers=("M1",),
            specs={"M1": {"width": 0.02, "space": 0.02}},  # no colors
        )
        self.assertFalse(p.is_valid())

    def test_valid_allows_varied_color_patterns(self):
        for colors in [("A",), ("AB",), ("BA",), ("ABA",), ("BAB",), ("ABA", "BAB")]:
            p = WirePattern(
                layers=("M3",),
                specs={"M3": {"width": 0.03, "space": 0.02, "colors": colors}},
            )
            self.assertTrue(p.is_valid(), f"Should be valid for colors={colors}")


class TestPatternEnumeratorGeneration(unittest.TestCase):
    """Tests for generation logic, pruning, rule coverage, and determinism."""

    def setUp(self):
        # Use a small metal set for fast exhaustive tests + one with more metals
        self.cfg2 = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M3", "M5"], "max_width_um": 0.040,  # same odd direction for stacking tests
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        self.cfg4 = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M1", "M3", "M5", "M7"], "max_width_um": 0.040,  # all same odd dir to allow 3-layer under new stacking rules
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        self.db = BEOLModelDB()
        # Force aggressive pruning in tests for speed + to demonstrate pruning logic
        # (real runs in optimizer use the class defaults or future config)
        PatternEnumerator.MAX_WS_CANDIDATES_PER_LAYER = 2
        PatternEnumerator.MAX_LAYERS = 2

    def test_generate_returns_only_valid_patterns(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        pats = pe.generate()
        self.assertGreater(len(pats), 0)
        for p in pats:
            self.assertIsInstance(p, WirePattern)
            self.assertTrue(p.is_valid(), f"Invalid pattern generated: {p.description}")

    def test_same_layer_multi_color_pattern_is_generated(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        pats = pe.generate()
        has_multi = any(
            "+" in p.description and "ABA+BAB" in p.description for p in pats
        )
        self.assertTrue(has_multi, "Expected at least one pattern using ABA+BAB same-layer combo")

    def test_multi_metal_same_dir_patterns_have_independent_specs(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        pats = [p for p in pe.generate() if len(p.layers) == 2]
        self.assertGreater(len(pats), 0)
        for p in pats:
            m0, m1 = p.layers
            # Independence model: each layer has its own spec entry (W/S/Color chosen independently
            # even if numeric values happen to coincide after pruning). Same-dir multi-metal (stacking)
            # is enforced by direction groups in is_valid + enumerator.
            self.assertIn(m0, p.specs)
            self.assertIn(m1, p.specs)
            self.assertIsInstance(p.specs[m0].get("colors"), tuple)
            self.assertIsInstance(p.specs[m1].get("colors"), tuple)

    def test_layer_count_pruning_max_3_and_at_least_1(self):
        # Force small WS to keep count reasonable even on 4 metals
        pe = PatternEnumerator(self.cfg4, self.db)
        pe.MAX_WS_CANDIDATES_PER_LAYER = 1  # 1 ws * 7 colors = 7 choices per metal
        pe.MAX_LAYERS = 3
        pats = pe.generate()
        for p in pats:
            self.assertGreaterEqual(len(p.layers), 1)
            self.assertLessEqual(len(p.layers), 3)

        # Also confirm some 3-layer patterns exist under this pruning
        has_3 = any(len(p.layers) == 3 for p in pats)
        self.assertTrue(has_3, "With 4 metals + MAX_LAYERS=3 we should still produce 3-layer patterns")

    def test_ws_candidates_per_layer_pruning(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        pe.MAX_WS_CANDIDATES_PER_LAYER = 2
        pats = pe.generate()

        # Collect distinct (w,s) actually used for M3 across all generated patterns
        used_for_m3: set[tuple[float, float]] = set()
        for p in pats:
            if "M3" in p.specs:
                sp = p.specs["M3"]
                used_for_m3.add((sp["width"], sp["space"]))

        self.assertLessEqual(
            len(used_for_m3),
            2,
            "WS candidate pruning (MAX=2) should limit distinct (w,s) used for any single metal",
        )

    def test_only_config_metals_and_max_width_filtering(self):
        cfg_small = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M4"], "max_width_um": 0.025,
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        pe = PatternEnumerator(cfg_small, self.db)
        pats = pe.generate()
        self.assertGreater(len(pats), 0)
        for p in pats:
            self.assertEqual(p.layers, ("M4",))
            for sp in p.specs.values():
                self.assertLessEqual(sp["width"], 0.025 + 1e-9)

        # A metal not in config must never appear
        for p in pats:
            self.assertNotIn("M1", p.specs)

    def test_deterministic_generate(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        first = pe.generate()
        second = pe.generate()
        self.assertEqual([p.description for p in first], [p.description for p in second])
        self.assertEqual([p.key() for p in first], [p.key() for p in second])

    def test_empty_metals_yields_empty(self):
        # Real WireConfig forbids metals=[], so test degenerate case via max_width that yields no candidates
        cfg = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M3"], "max_width_um": 0.0001,
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        pe = PatternEnumerator(cfg, self.db)
        self.assertEqual(pe.generate(), [])

    def test_no_patterns_when_max_width_too_small(self):
        # Use a metal whose smallest w > this max
        cfg = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M4"], "max_width_um": 0.001,
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        pe = PatternEnumerator(cfg, self.db)
        pats = pe.generate()
        self.assertEqual(pats, [])

    def test_per_metal_choices_include_skip_and_all_combos(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        choices = pe._per_metal_choices("M3")
        # First is always the skip (None)
        self.assertIsNone(choices[0])
        # Rest are dicts
        use_choices = [c for c in choices if c is not None]
        self.assertGreater(len(use_choices), 0)
        for c in use_choices:
            self.assertIn("width", c)
            self.assertIn("space", c)
            self.assertIn("colors", c)
            self.assertIsInstance(c["colors"], tuple)

    def test_patterns_are_unique_by_key(self):
        pe = PatternEnumerator(self.cfg2, self.db)
        pats = pe.generate()
        keys = [p.key() for p in pats]
        self.assertEqual(len(keys), len(set(keys)))


class TestPatternEnumeratorWithMocks(unittest.TestCase):
    """Additional coverage using lightweight mocks to isolate enumerator logic."""

    def test_uses_get_available_grid_and_get_rc_params(self):
        from unittest.mock import MagicMock

        cfg = WireConfig.from_dict({
            "csv_path": "stub.csv", "corner": "typical", "length_um": 20.0,
            "metals": ["M2", "M5"], "max_width_um": 0.1,
            "segment_um": 1.0, "via_pitch_um": 0.5,
            "driver_r_ohm": 80.0, "device_r_ohm": 45.0, "device_c_ff": 0.35,
            "via_r_ohm": 8.0, "output_dir": "."
        })
        db = MagicMock(spec=BEOLModelDB)
        # Provide controlled small grids
        db.get_available_grid.side_effect = lambda m, mw: (
            [0.02, 0.03, 0.04],
            [0.02, 0.03],
        )
        # Rsh decreases with width so top-by-R prefers wider
        def fake_rc(structure, corner, shape, w, s):
            return {"Rsh": 0.5 - 10 * w}  # lower for larger w
        db.get_rc_params.side_effect = fake_rc

        pe = PatternEnumerator(cfg, db)
        pe.MAX_WS_CANDIDATES_PER_LAYER = 2
        pats = pe.generate()

        # Should have called grid for the metals
        self.assertTrue(db.get_available_grid.called)
        # All patterns valid and only use provided metals
        for p in pats:
            self.assertTrue(p.is_valid())
            for m in p.layers:
                self.assertIn(m, ("M2", "M5"))

        # Because we ranked by R, wider ones preferred; verify at least one pattern uses 0.04
        has_wide = any(
            any(sp["width"] >= 0.039 for sp in p.specs.values()) for p in pats
        )
        self.assertTrue(has_wide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
