# Per-Layer Geometry Constraints and Multi-Line Fixed Signals

**Date:** 2026-07-05
**Status:** Approved (pending plan)
**Author:** Brainstorming session with user
**Related spec:** [2025-06-10-sram-beol-interconnect-optimizer-design.md](2025-06-10-sram-beol-interconnect-optimizer-design.md)

## Purpose

Extend the SRAM BEOL Interconnect Optimizer's `WireConfig` schema with two new capabilities:

1. **Per-layer geometry constraints** (`geometry.layer_constraints`): allow each metal to declare its own `(min_width_um, max_width_um, min_space_um, max_space_um)` range, overriding the global `geometry.max_width_um`. The global value remains the fallback / sanity-check for layers without explicit constraints.

2. **Multi-line fixed signals** (already partially supported): allow `fixed_signals` to contain multiple entries, e.g. `fix(M1) + fix(M3)`, that are all locked into every generated pattern. Strengthen direction-group consistency validation (currently only implicit).

Both capabilities are needed for realistic SRAM DTCO studies where different metal layers have different process design rules (e.g. thicker upper metals permit wider wires).

## Scope

### In scope

- New `geometry.layer_constraints` YAML section with optional per-metal `min/max_width_um` and `min/max_space_um`.
- New `LayerConstraint` frozen dataclass in `sram_beol/config.py`.
- `WireConfig.layer_constraints: dict[str, LayerConstraint]` field with default `{}`.
- New validation rules in `WireConfig._validate()`:
  - metals referenced in `layer_constraints` must exist in `geometry.metals`
  - `min_width_um <= max_width_um`, `min_space_um <= max_space_um` for each entry
  - all numeric values >= 0
- `PatternEnumerator._get_ws_candidates(metal)` filters DB grid points by the resolved effective constraint:
  - `min_width_um = layer_constraints[metal].min_width_um if specified else 0.0`
  - `max_width_um = layer_constraints[metal].max_width_um if specified else config.max_width_um`
  - `min_space_um / max_space_um` from layer_constraints if specified, else unbounded (0.0 and +inf respectively)
  - **Note**: "if specified" means `is not None`, NOT truthiness check (`or 0.0`), so explicitly setting `min_width_um=0.0` is preserved.
- `PatternEnumerator.__init__` validates `fixed_signals` direction groups and raises `BEOLConfigError` for unknown-direction metals.
- Mixed-direction `fixed_signals` (e.g. M1 + M2): allowed but log a warning and restrict candidate metals accordingly (current implicit behavior preserved).
- New pytest module `tests/test_layer_constraints.py`.
- Updated `samples/config_demo.yaml` and `samples/config_small.yaml` may be extended with example `layer_constraints` blocks (optional, for documentation).
- Update `README.md` Quick Start / Configuration Reference section to document the new YAML keys.

### Out of scope (YAGNI)

- Per-layer color constraints (e.g. allow ABA only on M5)
- Per-layer electrical parameters (per-metal driver_r_ohm, via_r_ohm, device_r_ohm, etc.)
- Per-layer `max_patterns` or `max_layers` overrides
- DR/LVS rule checks beyond W/S ranges
- Persistent storage of `layer_constraints` in DB CSV
- Runtime / interactive UI for editing constraints
- Backward-incompatible changes to existing YAML keys

## Design

### Data model

```python
@dataclass(frozen=True)
class LayerConstraint:
    """Per-layer W/S range constraint. All fields optional; None = unbounded on that side.
    
    Defaults make LayerConstraint() valid (no constraint); resolves to global fallback only.
    """
    metal: str
    min_width_um: Optional[float] = None
    max_width_um: Optional[float] = None
    min_space_um: Optional[float] = None
    max_space_um: Optional[float] = None
    
    def resolve(self, fallback_max_width_um: float) -> tuple[float, float, float, float]:
        """Return effective (min_w, max_w, min_s, max_s) tuple.
        
        - min_width_um: None -> 0.0
        - max_width_um: None -> fallback_max_width_um (global geometry.max_width_um)
        - min_space_um: None -> 0.0
        - max_space_um: None -> +infinity represented by a large finite sentinel (1e6)
        """
```

`WireConfig` gains one new field:

```python
@dataclass(frozen=True)
class WireConfig:
    # ... existing fields ...
    layer_constraints: dict[str, LayerConstraint] = field(default_factory=dict)
```

### YAML schema

```yaml
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060            # global fallback for layers without explicit max_width_um
  segment_um: 1.0
  via_pitch_um: 0.5
  layer_constraints:
    M1:
      min_width_um: 0.030
      max_width_um: 0.060
      min_space_um: 0.030
      max_space_um: 0.060
    M5:
      min_width_um: 0.040
      max_width_um: 0.070       # exceeds global max_width_um; explicitly allowed
      min_space_um: 0.060
      max_space_um: 0.100
```

All four numeric fields are optional. Missing key = no constraint on that side.

### Resolution priority (decided with user)

Per-layer constraints **override** the global `max_width_um` when both are specified. Rationale: in real PDK design rules each metal has its own (W_min, W_max, S_min, S_max) bounds; the global `max_width_um` exists only as a sanity-check / default for layers that have no explicit constraint. Example: M5 explicitly allows up to 0.070 um; the global 0.060 um is the conservative default but does not block it.

### Loading flow

```
YAML file
  └─> raw dict (load_wire_config)
        └─> extract "geometry.layer_constraints" if present
              └─> for each metal entry:
                    * parse numeric values (float)
                    * build LayerConstraint dataclass
                    * validate: min <= max, all >= 0
                    * validate: metal in geometry.metals
                    * collect into dict[str, LayerConstraint]
        └─> pass dict to WireConfig(layer_constraints=...)
              └─> __post_init__ _validate():
                    * existing field checks
                    * for each (metal, constraint) in layer_constraints:
                          if metal not in self.metals: BEOLConfigError
                          if constraint.min_width_um > constraint.max_width_um: BEOLConfigError
                          if constraint.min_space_um > constraint.max_space_um: BEOLConfigError
                          if any negative: BEOLConfigError
```

### Pattern enumeration flow

`PatternEnumerator._get_ws_candidates(metal)` is updated to:

```python
def _get_ws_candidates(self, metal: str) -> List[Tuple[float, float]]:
    corner = self.config.corner
    global_max_w = float(self.config.max_width_um)
    
    # Resolve effective bounds
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
    
    widths = [float(w) for w in w_arr 
              if min_w - 1e-12 <= float(w) <= max_w + 1e-12]
    spaces = [float(s) for s in s_arr
              if min_s - 1e-12 <= float(s) <= max_s + 1e-12]
    
    if not widths or not spaces:
        logger.warning(
            "metal=%s: 0 valid (W,S) candidates after layer_constraints filter "
            "(min_w=%.4f max_w=%.4f min_s=%.4f max_s=%s). DB grid has widths=%s, spaces=%s.",
            metal, min_w, max_w, min_s, 
            "inf" if max_s == float("inf") else f"{max_s:.4f}",
            list(w_arr), list(s_arr),
        )
        return []
    
    # ... existing ranking/pruning logic unchanged ...
```

### fixed_signals multi-line semantics

`fixed_signals` is already a `list[dict]`; multi-element lists already work in principle. The change is **strengthening validation**:

```python
# PatternEnumerator.__init__
self._fixed_dirs: set[str] = set()
for m in self.fixed_specs:
    d = _get_direction(m)
    if d == "unknown":
        raise BEOLConfigError(
            f"fixed_signals references metal {m!r} with unknown direction group. "
            "Use metals in {M1, M2, M3, ..., M19}."
        )
    self._fixed_dirs.add(d)

if len(self._fixed_dirs) > 1:
    logger.warning(
        "fixed_signals contains mixed direction groups %s; "
        "candidate stacking metals will be restricted to metals matching at least one fixed metal's group.",
        self._fixed_dirs,
    )
```

`fix(M1, M3)` (both odd): valid. Candidate stacking metals are filtered to odd-only (M5). Same behavior as current implementation but with explicit warning if no fixed_signals would otherwise be a confusing failure mode.

`fix(M1, M2)` (mixed odd/even): valid with WARNING. Candidate stacking metals must match at least one fixed direction (i.e. union of odd ∪ even = all metals, so no restriction). This preserves current implicit behavior.

### Error handling

| Error | Exception | Message format |
|---|---|---|
| `layer_constraints` metal not in `geometry.metals` | `BEOLConfigError` | `layer_constraints references metal {M} not in geometry.metals={...}` |
| `min_width > max_width` | `BEOLConfigError` | `layer_constraints.{M}: min_width_um={a} > max_width_um={b}` |
| `min_space > max_space` | `BEOLConfigError` | `layer_constraints.{M}: min_space_um={a} > max_space_um={b}` |
| Negative numeric value | `BEOLConfigError` | `layer_constraints.{M}.{field} must be >= 0, got {value}` |
| Range yields 0 DB candidates | (log warning, no exception) | `metal={M}: 0 valid (W,S) candidates after layer_constraints filter ...` |
| `fixed_signals` references unknown-direction metal | `BEOLConfigError` | `fixed_signals references metal {M} with unknown direction group. Use metals in {M1...M19}.` |
| `fixed_signals` mixed-direction | (log warning, no exception) | `fixed_signals contains mixed direction groups {odd, even}; candidate metals may stack on top of any fixed direction.` |

## Components

### Files to modify

1. **`sram_beol/config.py`** — add `LayerConstraint` dataclass, `WireConfig.layer_constraints` field, `_validate` rules.
2. **`sram_beol/pattern.py`** — update `_get_ws_candidates` to apply resolved constraints; add direction-group validation in `__init__`.
3. **`sram_beol/exceptions.py`** — no new exception needed; reuse `BEOLConfigError`, `BEOLPatternError`.
4. **`tests/test_layer_constraints.py`** — new file with ~10 unit tests.
5. **`tests/test_config.py`** — existing tests must continue to pass; add 1-2 cases for `layer_constraints` parsing via `WireConfig.from_dict`.
6. **`samples/config_demo.yaml`** — extend `geometry` block with example `layer_constraints` for M1 and M5 (commented as "example - uncomment to enable").
7. **`README.md`** — add a "Per-Layer Constraints" subsection in the Configuration Reference section.

### Files NOT modified

- `db.py` — DB grid is read-only; no change.
- `evaluator.py` — receives already-filtered `WirePattern`; no change.
- `optimizer.py` — calls PatternEnumerator; no change.
- `report.py`, `plot.py`, `rpt_generator.py`, `dashboard/*` — no change.

## Data flow (end-to-end)

```
samples/config_demo.yaml
   │
   │ load_wire_config("samples/config_demo.yaml")
   ▼
WireConfig(layer_constraints={
   "M1": LayerConstraint(min_w=0.030, max_w=0.060, min_s=0.030, max_s=0.060),
   "M5": LayerConstraint(min_w=0.040, max_w=0.070, min_s=0.060, max_s=0.100),
})
   │
   │ WLInterconnectOptimizer(config).run()
   │   └─> PatternEnumerator(cfg, db).generate()
   │         └─> for each metal in cfg.metals:
   │               _get_ws_candidates(metal):
   │                 widths = filter DB grid by min_w / max_w
   │                 spaces = filter DB grid by min_s / max_s
   │                 rank by Rsh, take top MAX_WS_CANDIDATES_PER_LAYER=4
   │         └─> for each (W, S, color) combination:
   │               build WirePattern, check is_valid(), emit
   ▼
List[WirePattern] (filtered by layer_constraints)
   │
   │ evaluator.evaluate(pattern) per pattern
   ▼
OptimizationResult (unchanged structure)
```

## Testing strategy

### New tests (`tests/test_layer_constraints.py`)

1. `test_layer_constraint_resolve_uses_global_fallback` — `LayerConstraint()` (empty) → `(0.0, global_max_w, 0.0, inf)`.
2. `test_layer_constraint_resolve_with_partial_overrides` — only `max_width_um` set → uses global max for fallback.
3. `test_layer_constraint_resolve_full_overrides` — all fields set → returns user values verbatim.
4. `test_layer_constraint_min_exceeds_max_raises` — `min_width > max_width` → `BEOLConfigError` on `__post_init__`.
5. `test_layer_constraint_metal_not_in_metals_raises` — constraint references M9 but metals=[M1..M5] → `BEOLConfigError`.
6. `test_layer_constraint_yaml_load_success` — load a small YAML fixture with constraints and assert parsed dict.
7. `test_layer_constraint_missing_section_uses_global_only` — no `layer_constraints` in YAML → behavior unchanged (existing tests cover this).
8. `test_pattern_filters_widths_by_per_layer_constraint` — generate patterns with M5 constraint; assert all M5 widths in [0.04, 0.07].
9. `test_pattern_filters_spaces_by_per_layer_constraint` — same with min_space_um=0.06; assert all S >= 0.06.
10. `test_pattern_empty_candidates_logs_warning` — M5 constraint range outside DB grid → `caplog` captures warning.
11. `test_fixed_signals_two_odd_layers_valid` — fix M1 + M3; assert pattern includes both and candidate metals limited to odd.
12. `test_fixed_signals_unknown_direction_raises` — fix metal "M99" → `BEOLConfigError`.
13. `test_fixed_signals_mixed_direction_warns` — fix M1 + M2 → `caplog` shows warning; patterns still generated.

### Regression

- Existing `tests/test_config.py` (17 tests) must continue to pass.
- Existing `tests/test_pattern.py` (27 tests) must continue to pass.
- Existing `tests/test_evaluator.py` (24 tests) must continue to pass.
- Existing `tests/test_core_units.py` (5 tests) must continue to pass.
- Existing `tests/test_integration_full_flow.py` (2 tests) must continue to pass.
- Existing `tests/test_db.py` (13 tests) must continue to pass.
- Existing `tests/test_cli.py` (11 tests) must continue to pass.
- Existing `tests/test_max_patterns.py` (3 tests) must continue to pass.
- **Total: 102 + ~13 = ~115 tests, all green.**

### End-to-end smoke

After implementation, run a manual smoke using `samples/config_demo.yaml` (with example `layer_constraints` uncommented) and verify:

- Number of generated patterns decreases (fewer candidates per layer → fewer combinations).
- All M5 patterns have width <= 0.070 and >= 0.040 (per-layer constraint).
- All M1 patterns have width <= 0.060 (its own max) and >= 0.030 (its own min).
- `report.md` and `plot_pareto.png` render correctly with fewer points.

## Risks and trade-offs

### Maintainability

- New `LayerConstraint` dataclass adds a small surface; mitigated by clear docstrings and a single `resolve()` method.
- YAML schema is extended but backward-compatible (new optional section).
- `pattern.py` `_get_ws_candidates` grows from ~25 to ~40 lines; still under 50-line complexity budget.

### Performance

- Per-layer filtering adds O(W+S) per metal, negligible compared to existing DB query and ranking.
- If a layer's constraint range is large and DB has many grid points, candidate count can grow beyond `MAX_WS_CANDIDATES_PER_LAYER=4`; existing top-N-by-Rsh ranking still applies, so no regression.

### Compatibility

- YAML without `layer_constraints` → identical behavior to before. Verified by existing `test_config.py` suite.
- `WireConfig.from_dict()` callers passing dicts without `layer_constraints` key → default empty dict; verified.
- Sample YAML files do not currently use `layer_constraints`; user may opt in by uncommenting example block.

### EDA flow alignment

- Per-layer constraints model real PDK design rules (per-metal W/S bounds); aligns with industry practice.
- Multi-line fixed signals support commonly-used SRAM DTCO scenarios (e.g. fix bitline + wordline).
- Direction-group validation surfaces configuration mistakes earlier (currently fails silently deep in `is_valid()`).

## Migration

- No migration steps.
- Existing sample configs work unchanged.
- New optional `layer_constraints` section is purely additive.

## Further follow-ups (YAGNI for this iteration)

1. **Per-layer electrical parameters** (driver_r_ohm, via_r_ohm overrides per metal) — would be a similar YAML extension but requires evaluator changes.
2. **Per-layer color constraints** (e.g. only ABA allowed on M5) — small extension to LayerConstraint.
3. **CSV-driven constraints** — load per-layer ranges from a separate CSV instead of inline YAML.
4. **Constraint validation against PDK** — automatic check that per-layer max_width_um does not exceed DB's available max grid point.

These are explicitly out of scope for this iteration.