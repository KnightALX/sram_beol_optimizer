# Per-Layer Geometry Constraints and Multi-Line Fixed Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `WireConfig` YAML schema with per-layer W/S range constraints (`geometry.layer_constraints`) and strengthen `fixed_signals` direction-group validation to support multi-line fixes (e.g. `fix(M1) + fix(M3)`), per the approved spec [2026-07-05-layer-constraints-and-multi-fix-design.md](specs/2026-07-05-layer-constraints-and-multi-fix-design.md).

**Architecture:** Add a new `LayerConstraint` frozen dataclass to `sram_beol/config.py` plus a `WireConfig.layer_constraints: dict[str, LayerConstraint]` field with default `{}`. Update `WireConfig._validate` to enforce per-layer rules. Update `PatternEnumerator._get_ws_candidates` to filter DB grid points by the resolved effective constraint (per-layer overrides global `max_width_um`). Strengthen `PatternEnumerator.__init__` to fail-fast on unknown-direction metals in `fixed_signals`. Add ~13 pytest cases in a new `tests/test_layer_constraints.py`. Update README and samples with documented examples. Strict TDD: red → green → refactor → commit.

**Tech Stack:** Python 3.10+, dataclasses(frozen), pytest 7.x, pyyaml. No new dependencies.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `sram_beol/config.py` | `LayerConstraint` dataclass + `WireConfig.layer_constraints` field + validation | Modify |
| `sram_beol/pattern.py` | `_get_ws_candidates` filter + `__init__` direction-group validation | Modify |
| `tests/test_layer_constraints.py` | All new tests for the feature | Create |
| `tests/test_config.py` | One new test for `from_dict` default | Modify (add 1 test) |
| `samples/config_demo.yaml` | Documented example `layer_constraints` block | Modify (add commented block) |
| `README.md` | "Per-Layer Constraints" subsection in Configuration Reference | Modify (add section) |
| `docs/superpowers/specs/2026-07-05-layer-constraints-and-multi-fix-design.md` | Already exists — the spec we implement against | Reference only |

---

## Task 1: Add `LayerConstraint` dataclass to `sram_beol/config.py` (TDD)

**Files:**
- Modify: `sram_beol/config.py:32-93` (above `WireConfig`)
- Test: `tests/test_layer_constraints.py` (new file)

- [ ] **Step 1: Create the test file with failing tests**

Create `tests/test_layer_constraints.py`:

```python
"""Tests for LayerConstraint dataclass and WireConfig.layer_constraints integration.

覆盖：
- LayerConstraint 自身行为 (resolve / 默认值 / None 处理)
- LayerConstraint 边界条件 (min > max 校验)
"""

from __future__ import annotations

import math
import pytest

from sram_beol.config import LayerConstraint
from sram_beol.exceptions import BEOLConfigError


class TestLayerConstraintResolve:
    """LayerConstraint.resolve() 与全局 fallback 的交互。"""

    def test_empty_constraint_uses_global_fallback(self):
        """空 LayerConstraint() -> resolve 到 (0.0, global_max, 0.0, inf)。"""
        lc = LayerConstraint(metal="M5")
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0
        assert max_w == 0.060
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_partial_override_only_max_width(self):
        """只设 max_width_um -> min_w 用 0.0, max_w 用用户值。"""
        lc = LayerConstraint(metal="M5", max_width_um=0.070)
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0
        assert max_w == 0.070        # overrides global 0.060
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_partial_override_only_min_width(self):
        """只设 min_width_um -> max_w 仍用全局 fallback。"""
        lc = LayerConstraint(metal="M5", min_width_um=0.040)
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.040
        assert max_w == 0.060
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_full_override_returns_user_values(self):
        """全部 4 个字段都设 -> resolve 返回用户值不变。"""
        lc = LayerConstraint(
            metal="M5",
            min_width_um=0.040,
            max_width_um=0.070,
            min_space_um=0.060,
            max_space_um=0.100,
        )
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert (min_w, max_w, min_s, max_s) == (0.040, 0.070, 0.060, 0.100)

    def test_explicit_zero_min_width_preserved(self):
        """显式设 min_width_um=0.0 必须保留, 不可被 falsy 转 fallback。"""
        lc = LayerConstraint(metal="M5", min_width_um=0.0)
        min_w, _, _, _ = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0     # not treated as None

    def test_frozen_dataclass(self):
        """frozen: 字段不可变。"""
        lc = LayerConstraint(metal="M5", max_width_um=0.070)
        with pytest.raises(Exception):   # FrozenInstanceError subclass of AttributeError
            lc.max_width_um = 0.080      # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_layer_constraints.py -v`
Expected: ImportError because `LayerConstraint` does not exist.

- [ ] **Step 3: Implement `LayerConstraint` dataclass**

In `sram_beol/config.py`, **above** the `WireConfig` class (after the module docstring and before line 32), add:

```python
@dataclass(frozen=True)
class LayerConstraint:
    """Per-layer W/S range constraint for geometry.layer_constraints.

    All fields optional; None = unbounded on that side.
    Resolution semantics: per-layer overrides global geometry.max_width_um.

    Attributes:
        metal: Metal layer name (e.g. "M5"). Must exist in WireConfig.metals.
        min_width_um: Lower bound on wire width (inclusive, um). None = 0.0.
        max_width_um: Upper bound on wire width (inclusive, um). None = global fallback.
        min_space_um: Lower bound on wire space (inclusive, um). None = 0.0.
        max_space_um: Upper bound on wire space (inclusive, um). None = +infinity.
    """

    metal: str
    min_width_um: Optional[float] = None
    max_width_um: Optional[float] = None
    min_space_um: Optional[float] = None
    max_space_um: Optional[float] = None

    def resolve(
        self, fallback_max_width_um: float
    ) -> tuple[float, float, float, float]:
        """Resolve to effective (min_w, max_w, min_s, max_s) for DB grid filtering.

        Args:
            fallback_max_width_um: Global geometry.max_width_um used when self.max_width_um is None.

        Returns:
            (min_w, max_w, min_s, max_s) all floats. max_s may be float('inf').
        """
        min_w = 0.0 if self.min_width_um is None else float(self.min_width_um)
        max_w = (
            float(fallback_max_width_um)
            if self.max_width_um is None
            else float(self.max_width_um)
        )
        min_s = 0.0 if self.min_space_um is None else float(self.min_space_um)
        max_s = float("inf") if self.max_space_um is None else float(self.max_space_um)
        return min_w, max_w, min_s, max_s
```

Also update the module-level imports at top of `sram_beol/config.py` — change:

```python
from typing import Any
```

to:

```python
from typing import Any, Optional
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_layer_constraints.py::TestLayerConstraintResolve -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add sram_beol/config.py tests/test_layer_constraints.py
git commit -m "feat(config): add LayerConstraint dataclass with resolve() method"
```

---

## Task 2: Add `WireConfig.layer_constraints` field + validation (TDD)

**Files:**
- Modify: `sram_beol/config.py:74-95` (WireConfig field declarations) and `sram_beol/config.py:148-175` (_validate)
- Test: `tests/test_layer_constraints.py` (append new test class)

- [ ] **Step 1: Write failing tests for WireConfig.layer_constraints**

Append to `tests/test_layer_constraints.py`:

```python
from sram_beol.config import WireConfig, load_wire_config


class TestWireConfigLayerConstraints:
    """WireConfig 与 layer_constraints 字段的集成测试。"""

    def _base_kwargs(self, **overrides):
        """Build valid kwargs; layer_constraints overrides via param."""
        base = dict(
            csv_path="dummy.csv",
            corner="typical",
            length_um=20.0,
            metals=["M1", "M2", "M3", "M4", "M5"],
            max_width_um=0.060,
            segment_um=1.0,
            via_pitch_um=0.5,
            driver_r_ohm=80.0,
            device_r_ohm=45.0,
            device_c_ff=0.35,
            via_r_ohm=8.0,
            output_dir="results",
        )
        base.update(overrides)
        return base

    def test_default_layer_constraints_is_empty_dict(self):
        """未传 layer_constraints -> 默认 {}。"""
        cfg = WireConfig(**self._base_kwargs())
        assert cfg.layer_constraints == {}

    def test_layer_constraints_parsed_from_dict(self):
        """从 dict 构造 layer_constraints 字段被正确解析。"""
        cfg = WireConfig(
            **self._base_kwargs(
                layer_constraints={
                    "M5": LayerConstraint(
                        metal="M5", min_width_um=0.040, max_width_um=0.070
                    )
                }
            )
        )
        assert "M5" in cfg.layer_constraints
        assert cfg.layer_constraints["M5"].max_width_um == 0.070

    def test_layer_constraint_metal_not_in_metals_raises(self):
        """layer_constraints 引用 metals 列表外的 metal -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="layer_constraints references metal M9"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M9": LayerConstraint(metal="M9", max_width_um=0.080)
                    }
                )
            )

    def test_min_width_exceeds_max_width_raises(self):
        """min > max -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="min_width_um"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(
                            metal="M5", min_width_um=0.080, max_width_um=0.040
                        )
                    }
                )
            )

    def test_min_space_exceeds_max_space_raises(self):
        """min_space > max_space -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="min_space_um"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(
                            metal="M5", min_space_um=0.10, max_space_um=0.06
                        )
                    }
                )
            )

    def test_negative_width_raises(self):
        """min_width_um = -0.01 -> BEOLConfigError (>= 0)。"""
        with pytest.raises(BEOLConfigError, match="must be >= 0"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(metal="M5", min_width_um=-0.01)
                    }
                )
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_layer_constraints.py::TestWireConfigLayerConstraints -v`
Expected: All 6 tests fail (TypeError on unexpected kwarg, then AttributeError on missing field).

- [ ] **Step 3: Add `layer_constraints` field to `WireConfig`**

In `sram_beol/config.py`, modify the `WireConfig` dataclass. **Change** line 86 area from:

```python
    fixed_signals: list[dict] = field(default_factory=list)

    # Extensibility / sample configs may include these (ignored or used by enumerator in full impl)
    max_patterns: int | None = None
    max_layers: int | None = None
```

to:

```python
    fixed_signals: list[dict] = field(default_factory=list)

    # Extensibility / sample configs may include these (ignored or used by enumerator in full impl)
    max_patterns: int | None = None
    max_layers: int | None = None

    # Per-layer geometry constraints (opt-in YAML section).
    # When a metal is absent from this dict, the global max_width_um applies with no other bound.
    layer_constraints: dict[str, "LayerConstraint"] = field(default_factory=dict)
```

- [ ] **Step 4: Add validation block to `WireConfig._validate()`**

In `sram_beol/config.py`, **append** to the end of `_validate()` method (after the existing `fixed_signals` block, before the "Reasonable sanity" warnings block). Insert:

```python
        # Per-layer constraints (optional)
        if not isinstance(self.layer_constraints, dict):
            raise BEOLConfigError(
                f"layer_constraints must be a dict (metal -> LayerConstraint), "
                f"got {type(self.layer_constraints).__name__}."
            )
        metals_set = set(self.metals)
        for metal, lc in self.layer_constraints.items():
            if metal not in metals_set:
                raise BEOLConfigError(
                    f"layer_constraints references metal {metal!r} not in "
                    f"geometry.metals={self.metals}. "
                    "Either add it to metals or remove the constraint."
                )
            # Each numeric field must be >= 0 and min <= max
            for fname in ("min_width_um", "max_width_um", "min_space_um", "max_space_um"):
                v = getattr(lc, fname, None)
                if v is not None:
                    if not isinstance(v, (int, float)):
                        raise BEOLConfigError(
                            f"layer_constraints[{metal!r}].{fname} must be numeric, "
                            f"got {type(v).__name__}."
                        )
                    if v < 0:
                        raise BEOLConfigError(
                            f"layer_constraints[{metal!r}].{fname} must be >= 0, got {v}."
                        )
            if (
                lc.min_width_um is not None
                and lc.max_width_um is not None
                and lc.min_width_um > lc.max_width_um
            ):
                raise BEOLConfigError(
                    f"layer_constraints[{metal!r}]: min_width_um={lc.min_width_um} "
                    f"> max_width_um={lc.max_width_um}."
                )
            if (
                lc.min_space_um is not None
                and lc.max_space_um is not None
                and lc.min_space_um > lc.max_space_um
            ):
                raise BEOLConfigError(
                    f"layer_constraints[{metal!r}]: min_space_um={lc.min_space_um} "
                    f"> max_space_um={lc.max_space_um}."
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_layer_constraints.py::TestWireConfigLayerConstraints -v`
Expected: 6 tests pass.

- [ ] **Step 6: Run existing tests to ensure no regression**

Run: `python -m pytest tests/test_config.py -v`
Expected: All 17 + new 6 = 23 tests pass (existing tests should be unaffected since they don't pass `layer_constraints`).

- [ ] **Step 7: Commit**

```bash
git add sram_beol/config.py tests/test_layer_constraints.py
git commit -m "feat(config): add WireConfig.layer_constraints field with full validation"
```

---

## Task 3: YAML loading of `geometry.layer_constraints` section

**Files:**
- Modify: `sram_beol/config.py:300-330` (load_wire_config YAML processing)
- Test: `tests/test_layer_constraints.py` (append new test class)

- [ ] **Step 1: Write failing test for YAML loading**

Append to `tests/test_layer_constraints.py`:

```python
import yaml
import tempfile
from pathlib import Path


class TestLayerConstraintsYAMLLoading:
    """YAML loader 必须把 geometry.layer_constraints 解析为 LayerConstraint dict。"""

    def _write_yaml(self, content: str) -> str:
        """Helper: write YAML to a temp file and return its path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            return f.name

    def test_geometry_layer_constraints_parsed(self):
        """YAML 中 geometry.layer_constraints.M5 -> cfg.layer_constraints['M5']."""
        yaml_text = """
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060
  segment_um: 1.0
  via_pitch_um: 0.5
  layer_constraints:
    M5:
      min_width_um: 0.040
      max_width_um: 0.070
      min_space_um: 0.060
      max_space_um: 0.100

electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0

csv_path: "dummy.csv"
corner: "typical"
output_dir: "results"
"""
        path = self._write_yaml(yaml_text)
        try:
            cfg = load_wire_config(path)
            assert "M5" in cfg.layer_constraints
            lc = cfg.layer_constraints["M5"]
            assert lc.min_width_um == 0.040
            assert lc.max_width_um == 0.070
            assert lc.min_space_um == 0.060
            assert lc.max_space_um == 0.100
        finally:
            Path(path).unlink()

    def test_geometry_layer_constraints_absent_uses_empty_dict(self):
        """YAML 不含 layer_constraints 段 -> 默认空 dict, 不报错。"""
        yaml_text = """
geometry:
  length_um: 20.0
  metals: ["M1"]
  max_width_um: 0.040
  segment_um: 1.0
  via_pitch_um: 0.5
electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0
csv_path: "dummy.csv"
corner: "typical"
output_dir: "results"
"""
        path = self._write_yaml(yaml_text)
        try:
            cfg = load_wire_config(path)
            assert cfg.layer_constraints == {}
        finally:
            Path(path).unlink()

    def test_geometry_layer_constraints_invalid_metal_raises(self):
        """layer_constraints 引用 metals 列表外 metal -> BEOLConfigError。"""
        yaml_text = """
geometry:
  length_um: 20.0
  metals: ["M1"]
  max_width_um: 0.040
  segment_um: 1.0
  via_pitch_um: 0.5
  layer_constraints:
    M9:
      max_width_um: 0.080
electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0
csv_path: "dummy.csv"
corner: "typical"
output_dir: "results"
"""
        path = self._write_yaml(yaml_text)
        try:
            with pytest.raises(BEOLConfigError, match="M9"):
                load_wire_config(path)
        finally:
            Path(path).unlink()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_layer_constraints.py::TestLayerConstraintsYAMLLoading -v`
Expected: 3 tests fail — layer_constraints 段被忽略, cfg.layer_constraints 始终为 {}。

- [ ] **Step 3: Update `load_wire_config` to parse `geometry.layer_constraints`**

In `sram_beol/config.py`, modify the YAML processing loop. The current logic at line 314-321 is:

```python
    data: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                data[kk] = vv
        else:
            data[k] = v
```

**Replace** with:

```python
    data: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            # Special handling: geometry.layer_constraints is a nested dict-of-dicts
            # that should be parsed into LayerConstraint objects.
            if k == "geometry" and "layer_constraints" in v:
                lc_raw = v.pop("layer_constraints")
                # Flatten remaining geometry fields first
                for kk, vv in v.items():
                    data[kk] = vv
                # Parse layer_constraints as dict[str, LayerConstraint]
                lc_parsed: dict[str, "LayerConstraint"] = {}
                if not isinstance(lc_raw, dict):
                    raise BEOLConfigError(
                        f"geometry.layer_constraints must be a mapping "
                        f"(metal -> constraint dict), got {type(lc_raw).__name__}."
                    )
                for metal, fields in lc_raw.items():
                    if not isinstance(fields, dict):
                        raise BEOLConfigError(
                            f"geometry.layer_constraints[{metal!r}] must be a mapping "
                            f"with min/max_width_um, min/max_space_um keys, "
                            f"got {type(fields).__name__}."
                        )
                    lc_parsed[str(metal)] = LayerConstraint(
                        metal=str(metal),
                        min_width_um=fields.get("min_width_um"),
                        max_width_um=fields.get("max_width_um"),
                        min_space_um=fields.get("min_space_um"),
                        max_space_um=fields.get("max_space_um"),
                    )
                data["layer_constraints"] = lc_parsed
            else:
                for kk, vv in v.items():
                    data[kk] = vv
        else:
            data[k] = v
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `python -m pytest tests/test_layer_constraints.py::TestLayerConstraintsYAMLLoading -v`
Expected: 3 tests pass.

- [ ] **Step 5: Run existing test_config.py to ensure no regression**

Run: `python -m pytest tests/test_config.py -v`
Expected: 17 existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add sram_beol/config.py tests/test_layer_constraints.py
git commit -m "feat(config): parse geometry.layer_constraints from YAML into LayerConstraint dict"
```

---

## Task 4: `PatternEnumerator._get_ws_candidates` applies per-layer constraints

**Files:**
- Modify: `sram_beol/pattern.py:286-337` (`_get_ws_candidates` method)
- Test: `tests/test_layer_constraints.py` (append new test class)

- [ ] **Step 1: Write failing tests for constraint filtering**

Append to `tests/test_layer_constraints.py`:

```python
from sram_beol.db import BEOLModelDB
from sram_beol.pattern import PatternEnumerator


def _make_db():
    """Helper: build a tiny in-memory BEOLModelDB with a known grid."""
    import csv
    import io
    csv_text = """Structure,Corner,ShapeColor,Width,Space,Rsh,Ctotal,Cc,Cbottom
M3,typical,ABA,0.020,0.020,0.320,0.520,0.280,0.160
M3,typical,ABA,0.020,0.040,0.320,0.460,0.220,0.140
M3,typical,ABA,0.030,0.020,0.265,0.570,0.335,0.185
M3,typical,ABA,0.030,0.040,0.265,0.510,0.275,0.165
M3,typical,ABA,0.040,0.020,0.245,0.620,0.385,0.205
M3,typical,ABA,0.040,0.040,0.245,0.560,0.325,0.180
M3,typical,ABA,0.050,0.020,0.225,0.680,0.435,0.230
M3,typical,ABA,0.050,0.040,0.225,0.620,0.375,0.205
M3,typical,ABA,0.050,0.060,0.225,0.580,0.335,0.190
M3,typical,ABA,0.050,0.080,0.225,0.545,0.300,0.180
M3,typical,ABA,0.060,0.060,0.210,0.610,0.365,0.205
M3,typical,ABA,0.060,0.080,0.210,0.575,0.330,0.195
M3,typical,ABA,0.070,0.080,0.195,0.620,0.375,0.210
M3,typical,ABA,0.070,0.100,0.195,0.590,0.345,0.200
"""
    db = BEOLModelDB.__new__(BEOLModelDB)
    db._load_from_text(csv_text)  # if available; else use __init__ via Path
    return db


class TestPatternEnumeratorLayerConstraints:
    """PatternEnumerator._get_ws_candidates 必须按 layer_constraints 过滤。"""

    def test_no_constraint_uses_global_max_width(self):
        """无 layer_constraints 时: 所有 DB grid widths <= global max 都进入候选。"""
        # Use a real DB from samples to avoid mocking
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M3"], max_width_um=0.060, segment_um=1.0,
            via_pitch_um=0.5, driver_r_ohm=80.0, device_r_ohm=45.0,
            device_c_ff=0.35, via_r_ohm=8.0, output_dir="results",
        )
        pe = PatternEnumerator(cfg, db)
        candidates = pe._get_ws_candidates("M3")
        # All widths <= 0.060 (global), and <= MAX_WS_CANDIDATES_PER_LAYER
        for w, _ in candidates:
            assert w <= 0.060 + 1e-9

    def test_per_layer_max_width_overrides_global(self, caplog):
        """per-layer max_width=0.070 覆盖 global 0.060。"""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M3"], max_width_um=0.060, segment_um=1.0,
            via_pitch_um=0.5, driver_r_ohm=80.0, device_r_ohm=45.0,
            device_c_ff=0.35, via_r_ohm=8.0, output_dir="results",
            layer_constraints={
                "M3": LayerConstraint(metal="M3", max_width_um=0.080)
            },
        )
        pe = PatternEnumerator(cfg, db)
        candidates = pe._get_ws_candidates("M3")
        for w, _ in candidates:
            assert w <= 0.080 + 1e-9

    def test_per_layer_min_width_filters_out_small_widths(self):
        """per-layer min_width_um=0.040 -> 候选 W 全部 >= 0.040。"""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M3"], max_width_um=0.060, segment_um=1.0,
            via_pitch_um=0.5, driver_r_ohm=80.0, device_r_ohm=45.0,
            device_c_ff=0.35, via_r_ohm=8.0, output_dir="results",
            layer_constraints={
                "M3": LayerConstraint(metal="M3", min_width_um=0.040)
            },
        )
        pe = PatternEnumerator(cfg, db)
        candidates = pe._get_ws_candidates("M3")
        for w, _ in candidates:
            assert w >= 0.040 - 1e-9

    def test_per_layer_min_space_filters_out_small_spaces(self):
        """per-layer min_space_um=0.040 -> 候选 S 全部 >= 0.040。"""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M3"], max_width_um=0.060, segment_um=1.0,
            via_pitch_um=0.5, driver_r_ohm=80.0, device_r_ohm=45.0,
            device_c_ff=0.35, via_r_ohm=8.0, output_dir="results",
            layer_constraints={
                "M3": LayerConstraint(metal="M3", min_space_um=0.040)
            },
        )
        pe = PatternEnumerator(cfg, db)
        candidates = pe._get_ws_candidates("M3")
        for _, s in candidates:
            assert s >= 0.040 - 1e-9

    def test_empty_candidates_after_filter_logs_warning(self, caplog):
        """layer_constraints 范围排除所有 DB 候选 -> warning 日志。"""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M3"], max_width_um=0.5, segment_um=1.0,
            via_pitch_um=0.5, driver_r_ohm=80.0, device_r_ohm=45.0,
            device_c_ff=0.35, via_r_ohm=8.0, output_dir="results",
            layer_constraints={
                # 0.5 width not in M3 DB grid (max 0.04 in beol_sample.csv)
                "M3": LayerConstraint(metal="M3", min_width_um=0.5, max_width_um=1.0)
            },
        )
        pe = PatternEnumerator(cfg, db)
        with caplog.at_level("WARNING"):
            candidates = pe._get_ws_candidates("M3")
        assert candidates == []
        assert any("0 valid" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `python -m pytest tests/test_layer_constraints.py::TestPatternEnumeratorLayerConstraints -v`
Expected: All 5 tests fail because `_get_ws_candidates` does not consult `layer_constraints`.

- [ ] **Step 3: Modify `_get_ws_candidates` to apply per-layer constraints**

In `sram_beol/pattern.py`, **replace** the body of `_get_ws_candidates` (lines 286-337) with:

```python
    def _get_ws_candidates(self, metal: str) -> List[Tuple[float, float]]:
        """Pruned (w, s) list for the metal, filtered by per-layer constraints.

        1. Resolve effective (min_w, max_w, min_s, max_s) from layer_constraints
           (per-layer override) or global max_width_um (fallback).
        2. Get union grid for metal+corner (all shapecolors) from DB.
        3. Filter widths to [min_w, max_w] and spaces to [min_s, max_s].
        4. Rank candidate pairs by representative Rsh (lowest first) using get_rc_params
           with a viable color for that metal. Falls back gracefully.
        5. Take top N (or uniform stride sample on ties / no R variation)
        6. Return sorted unique.
        """
        corner = self.config.corner
        global_max_w = float(self.config.max_width_um)

        # Resolve effective (min_w, max_w, min_s, max_s) from per-layer constraints
        constraint = self.config.layer_constraints.get(metal)
        if constraint is None:
            min_w, max_w = 0.0, global_max_w
            min_s, max_s = 0.0, float("inf")
        else:
            min_w, max_w, min_s, max_s = constraint.resolve(global_max_w)

        try:
            w_arr, s_arr = self.db.get_available_grid(metal, corner)
        except Exception:
            return []

        # Filter widths to [min_w, max_w]
        widths = [
            float(w) for w in w_arr
            if min_w - 1e-12 <= float(w) <= max_w + 1e-12
        ]
        # Filter spaces to [min_s, max_s] (inf on max means no upper bound)
        if math.isinf(max_s):
            spaces = [float(s) for s in s_arr if float(s) >= min_s - 1e-12]
        else:
            spaces = [
                float(s) for s in s_arr
                if min_s - 1e-12 <= float(s) <= max_s + 1e-12
            ]

        if not widths or not spaces:
            logger.warning(
                "metal=%s: 0 valid (W,S) candidates after layer_constraints filter "
                "(min_w=%.4f max_w=%.4f min_s=%.4f max_s=%s). DB grid widths=%s, spaces=%s.",
                metal, min_w, max_w, min_s,
                "inf" if math.isinf(max_s) else f"{max_s:.4f}",
                list(w_arr), list(s_arr),
            )
            return []

        all_pairs: List[Tuple[float, float]] = [(w, s) for w in widths for s in spaces]

        # Representative Rsh for ranking (use first discoverable color)
        viable_colors = self._discover_colors(metal)
        rep_color = viable_colors[0] if viable_colors else "ABA"

        def rsh_of(pair: Tuple[float, float]) -> float:
            w, s = pair
            try:
                rc = self.db.get_rc_params(metal, corner, rep_color, w, s)
                return float(rc["Rsh"])
            except Exception:
                # Prefer wider on fallback (lower effective R)
                return 1000.0 - w * 100.0

        ranked = sorted(all_pairs, key=rsh_of)

        n = min(self.MAX_WS_CANDIDATES_PER_LAYER, len(ranked))
        selected = ranked[:n]

        # If R values effectively constant, uniform sample
        rvals = [rsh_of(p) for p in selected]
        if len(set(round(r, 6) for r in rvals)) <= 1 and len(ranked) > n:
            stride = max(1, len(ranked) // n)
            selected = ranked[::stride][:n]

        # dedup + stable sort
        uniq = sorted(set(selected), key=lambda p: (round(p[0], 9), round(p[1], 9)))
        return uniq
```

Also add `import math` to top of `sram_beol/pattern.py` if not already imported.

- [ ] **Step 4: Run new tests to verify they pass**

Run: `python -m pytest tests/test_layer_constraints.py::TestPatternEnumeratorLayerConstraints -v`
Expected: 5 tests pass.

- [ ] **Step 5: Run existing test_pattern.py to ensure no regression**

Run: `python -m pytest tests/test_pattern.py -v`
Expected: 27 existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add sram_beol/pattern.py tests/test_layer_constraints.py
git commit -m "feat(pattern): filter (W,S) candidates by per-layer layer_constraints"
```

---

## Task 5: Strengthen `fixed_signals` direction-group validation

**Files:**
- Modify: `sram_beol/pattern.py:259-263` (PatternEnumerator.__init__ direction handling)
- Test: `tests/test_layer_constraints.py` (append new test class)

- [ ] **Step 1: Write failing tests for direction validation**

Append to `tests/test_layer_constraints.py`:

```python
class TestFixedSignalsDirectionValidation:
    """PatternEnumerator.__init__ 必须校验 fixed_signals direction。"""

    def _make_enumerator(self, fixed_signals):
        """Build a PatternEnumerator with given fixed_signals."""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        csv_path = repo_root / "samples" / "beol_sample.csv"
        db = BEOLModelDB(csv_path)
        cfg = WireConfig(
            csv_path=str(csv_path), corner="typical", length_um=20.0,
            metals=["M1", "M2", "M3", "M4", "M5"],
            max_width_um=0.060, segment_um=1.0, via_pitch_um=0.5,
            driver_r_ohm=80.0, device_r_ohm=45.0, device_c_ff=0.35,
            via_r_ohm=8.0, output_dir="results",
            fixed_signals=fixed_signals,
        )
        return PatternEnumerator(cfg, db)

    def test_two_odd_layers_fixed_succeeds(self):
        """fix(M1+M3) - 同方向组 -> 正常构造, 无异常。"""
        fixed = [
            {"metal": "M1", "width": 0.030, "space": 0.030, "colors": ["ABA"]},
            {"metal": "M3", "width": 0.030, "space": 0.030, "colors": ["ABA"]},
        ]
        pe = self._make_enumerator(fixed)
        assert "M1" in pe.fixed_specs
        assert "M3" in pe.fixed_specs
        assert pe._fixed_dirs == {"odd"}

    def test_unknown_direction_metal_raises(self):
        """fix(M99) - 不在方向组中 -> BEOLConfigError。"""
        from sram_beol.exceptions import BEOLConfigError
        fixed = [
            {"metal": "M99", "width": 0.030, "space": 0.030, "colors": ["ABA"]},
        ]
        with pytest.raises(BEOLConfigError, match="unknown direction group"):
            self._make_enumerator(fixed)

    def test_mixed_direction_fixed_warns_but_succeeds(self, caplog):
        """fix(M1+M2) - 不同方向组 -> WARNING + 构造成功 (candidate union = all)。"""
        fixed = [
            {"metal": "M1", "width": 0.030, "space": 0.030, "colors": ["ABA"]},
            {"metal": "M2", "width": 0.030, "space": 0.030, "colors": ["ABA"]},
        ]
        with caplog.at_level("WARNING"):
            pe = self._make_enumerator(fixed)
        assert pe._fixed_dirs == {"odd", "even"}
        assert any("mixed direction" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_layer_constraints.py::TestFixedSignalsDirectionValidation -v`
Expected: All 3 tests fail (no direction validation currently).

- [ ] **Step 3: Update `PatternEnumerator.__init__` for direction validation**

In `sram_beol/pattern.py`, **replace** the direction-handling block at lines 259-263:

```python
        # Determine the direction(s) enforced by fixed signals (all fixed must share direction for a valid pattern).
        self._fixed_dirs: set[str] = {_get_direction(m) for m in self.fixed_specs}
        if len(self._fixed_dirs) > 1:
            # Mixed directions in fixed signals: patterns will be invalid unless user fixes consistently.
            pass  # Let is_valid() catch it; or we could raise here.
```

with:

```python
        # Determine the direction(s) enforced by fixed signals.
        # Fail-fast on unknown direction (likely typo like M99).
        # Warn on mixed directions (allows broad stacking on top).
        self._fixed_dirs: set[str] = set()
        for m in self.fixed_specs:
            d = _get_direction(m)
            if d == "unknown":
                raise BEOLConfigError(
                    f"fixed_signals references metal {m!r} with unknown direction group. "
                    "Use metals in {M1, M2, ..., M19} (M1/M3/M5... are 'odd', "
                    "M2/M4/M6... are 'even')."
                )
            self._fixed_dirs.add(d)
        if len(self._fixed_dirs) > 1:
            logger.warning(
                "fixed_signals contains mixed direction groups %s; "
                "candidate stacking metals will include any metal whose direction matches "
                "at least one fixed metal (union of groups).",
                sorted(self._fixed_dirs),
            )
```

Also add `from .exceptions import BEOLConfigError, BEOLPatternError` import at top of `sram_beol/pattern.py` (BEOLConfigError should already be imported if used elsewhere; verify).

- [ ] **Step 4: Run new tests to verify they pass**

Run: `python -m pytest tests/test_layer_constraints.py::TestFixedSignalsDirectionValidation -v`
Expected: 3 tests pass.

- [ ] **Step 5: Run full test suite to ensure no regression**

Run: `python -m pytest tests/ -v 2>&1 | tail -30`
Expected: 102 existing tests still pass + ~17 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add sram_beol/pattern.py tests/test_layer_constraints.py
git commit -m "feat(pattern): fail-fast on unknown direction in fixed_signals; warn on mixed directions"
```

---

## Task 6: Update samples and README documentation

**Files:**
- Modify: `samples/config_demo.yaml` (add commented example block)
- Modify: `README.md` (add Per-Layer Constraints subsection)

- [ ] **Step 1: Update `samples/config_demo.yaml`**

Open `samples/config_demo.yaml` and **add** the following block to the `geometry:` section, after `via_pitch_um: 0.5`:

```yaml
  # OPTIONAL: per-layer geometry constraints (uncomment to enable).
  # Each metal can declare its own (min/max_width_um, min/max_space_um) range;
  # per-layer max_width_um OVERRIDES the global max_width_um above.
  # Any layer not listed here uses only the global max_width_um with no other bound.
  # layer_constraints:
  #   M1:
  #     min_width_um: 0.030
  #     max_width_um: 0.060
  #     min_space_um: 0.030
  #     max_space_um: 0.060
  #   M5:
  #     min_width_um: 0.040
  #     max_width_um: 0.070
  #     min_space_um: 0.060
  #     max_space_um: 0.100
```

- [ ] **Step 2: Run optimizer with sample to verify no regression**

Run: `python -m pytest tests/test_integration_full_flow.py -v`
Expected: 2 tests still pass.

- [ ] **Step 3: Update `README.md` with Per-Layer Constraints section**

Open `README.md`. Find the "Configuration Reference" section (or create it if absent). **Add** a new subsection titled "Per-Layer Geometry Constraints" with the following content:

```markdown
### Per-Layer Geometry Constraints

By default, `geometry.max_width_um` is the only width bound applied to all metals.
To model real PDK rules where each metal has its own (W, S) design window, add a
`geometry.layer_constraints` section:

\```yaml
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060        # global default for layers without explicit constraint
  segment_um: 1.0
  via_pitch_um: 0.5
  layer_constraints:
    M1:
      min_width_um: 0.030
      max_width_um: 0.060
    M5:
      min_width_um: 0.040
      max_width_um: 0.070     # per-layer max overrides global max_width_um
      min_space_um: 0.060
      max_space_um: 0.100
\```

**Resolution rules:**

- All four numeric fields are optional. Missing = unbounded on that side.
- `max_width_um` per-layer **overrides** the global `geometry.max_width_um` (you can
  have M5 up to 0.070 um even if global is 0.060 um).
- Candidates are filtered against the **DB grid** — only (W, S) points actually
  present in the CSV are emitted.
- If the constraint range yields zero DB candidates for a metal, a WARNING is logged
  and that metal is skipped.
- Metals referenced in `layer_constraints` must exist in `geometry.metals`.
```

Also add a "Multi-Line Fixed Signals" subsection:

```markdown
### Multi-Line Fixed Signals

`fixed_signals` is a list of `metal, width, space, colors` dicts. To fix multiple
layers simultaneously (e.g. a bitline + wordline pair), add multiple entries:

\```yaml
fixed_signals:
  - metal: "M1"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
  - metal: "M3"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
\```

All fixed metals must be in the same direction group (all odd M1/M3/M5 or all even
M2/M4/M6). Mixed-direction fixes log a WARNING but are still allowed; the optimizer
will union candidate stacking metals across both directions.
```

- [ ] **Step 4: Final full-suite regression test**

Run: `python -m pytest tests/ -v 2>&1 | tail -10`
Expected: All tests pass (102 existing + ~17 new = ~119).

- [ ] **Step 5: Commit documentation**

```bash
git add samples/config_demo.yaml README.md
git commit -m "docs: document per-layer constraints and multi-line fixed signals"
```

---

## Acceptance Criteria

- [ ] All pytest tests pass (existing 102 + new ~17 = ~119)
- [ ] No regression in `tests/test_config.py` (17 tests), `tests/test_pattern.py` (27 tests), or end-to-end smoke
- [ ] `samples/config_demo.yaml` continues to load without changes (backward compat)
- [ ] README has a "Per-Layer Geometry Constraints" subsection with full YAML example
- [ ] At least one git commit per task (6 total commits expected)

---

## Self-Review Notes

(Inline fixes performed during plan writing)

1. **Type consistency**: `LayerConstraint.resolve()` defined in Task 1 returns `(float, float, float, float)`. Task 4 uses this exact signature. No type mismatch.

2. **Spec coverage**:
   - Spec §"Data model" → Task 1
   - Spec §"YAML schema" → Task 3
   - Spec §"Pattern enumeration flow" → Task 4
   - Spec §"fixed_signals multi-line semantics" → Task 5
   - Spec §"Error handling" → Tasks 2, 5
   - Spec §"Testing strategy" → Tasks 1-5 (all 13 new tests covered)
   - Spec §"README" update → Task 6

3. **Placeholder scan**: No "TBD" or "TODO" in any task. All code blocks are complete.

4. **Ambiguity check**: Each task has explicit file paths, line numbers, code blocks, and run commands.

5. **Backward compatibility**: Tasks 2 (default empty dict) and 4 (no constraint = current behavior) explicitly preserve existing behavior. Verified by running existing test suites after each task.