# SRAM BEOL Interconnect Optimizer Design Document

**Date**: 2025-06-10
**Project**: sram_beol - Long Wire Optimizer for SRAM WordLine (WL) >20um
**Version**: 1.0
**Status**: Approved (all sections)

## 1. Introduction and Goals

This tool optimizes physical implementation of long interconnects (>20um) in SRAM BEOL, specifically for WordLine (WL) structures with periodic poly load devices (R and C).

**Core Goals**:
- Find the optimal wire pattern (layer selection + per-layer Width/Space/Color) to minimize line delay.
- Support multi-layer parallel routing (同层并线 and 不同层叠线) with via strapping.
- Use provided BEOL CSV database for accurate RC per unit length.
- Provide commercial-grade EDA style reporting and visualizations to prove optimality.
- Fully class-based, importable, with argparse CLI.

**Key Constraints from User**:
- Use Elmore delay model on distributed ladder.
- segment (device tap spacing) and via_pitch (strapping density) are independent.
- CSV: exact columns, corner must exactly match in CSV (error if not).
- Interpolation: highest precision + physically consistent (monotonic).
- YAML is primary config (driver_R, device_R, device_C, via_R, corner, length, metals, max_width, segment, via_pitch, csv_path, etc.).
- Pareto is now defined on the two primary objectives the user cares about: **min far-end delay** and **min average delay** (both to be minimized). No separate "cost" axis for Pareto ranking (total_metal_width_sum is kept only as informational in reports/tables).
- Always highlight: the pattern achieving the absolute min far-end delay, and the pattern achieving the absolute min average delay (these two points are explicitly called out even if not on the Pareto front).
- Layer direction rules for stacking (叠线): Metals are grouped by routing direction. Odd layers (M1, M3, M5, ...) share one preferred direction; even layers (M2, M4, M6, ...) share the orthogonal direction. Only metals within the **same direction group** may be stacked/paralleled together in one pattern (cross-direction stacking is forbidden). Same-layer parallel (并线 on one metal with multiple colors) remains allowed.
- YAML supports logical grouping/sections for readability (e.g. `geometry:`, `electrical:`, `fixed_signals:`). The loader flattens groups into the flat WireConfig fields.
- Support for user-specified "fixed" signal lines that must be included in every candidate pattern. Fixed signals lock their metal + width + space + colors. The optimizer then searches for the best additional parallel/stacking (respecting direction rules) to combine with the fixed base. This enables "optimize around my already-fixed M1 route". Fixed signals are always part of the equivalent conductor calculation.
- Report near/far/avg for both τ and propagation delay estimate (0.69*τ).
- Plots must clearly prove why the chosen pattern is optimal.

## 2. Overall Architecture

Package: `sram_beol`

**Main Components** (high cohesion, low coupling):
- `config.py`: WireConfig (dataclass from YAML, thin argparse).
- `db.py`: BEOLModelDB (CSV loading, exact corner validation, high-precision physically-constrained 2D interpolation per (Structure, Corner, ShapeColor)).
- `pattern.py`: WirePattern (immutable representation of one routing combo) + PatternEnumerator (generates valid patterns respecting same-layer vs cross-layer rules, with pruning for practicality).
- `evaluator.py`: ElmoreLadderEvaluator (builds ladder per topology, computes equiv R/C for multi-layer + via scaling, full Elmore, returns near/far/avg τ + prop).
- `optimizer.py`: WLInterconnectOptimizer (orchestrates, systematic enumeration, Pareto, extracts two special points).
- `report.py`: ReportGenerator (commercial tables, markdown/CSV).
- `plot.py`: Plotter (Pareto scatter with pattern labels, sensitivity curves, delay profiles, top-N comparisons).
- `cli.py`: Thin argparse entrypoint.
- `exceptions.py`: Clear hierarchy (BEOLConfigError, BEOLDataError, etc.).
- `__init__.py`: Exposes main class and Config.

**Data Flow**:
Config (YAML) → BEOLModelDB (validate + interp) → PatternEnumerator (legal patterns) → ElmoreLadderEvaluator (per pattern delays) → Optimizer (Pareto + highlights) → Result → ReportGenerator + Plotter.

**Result Object** (OptimizationResult):
- all_patterns: list of full records (description, delays, equiv params, etc.)
- pareto_front
- best_far_end, best_avg
- summary stats

## 3. Configuration Model

YAML is the source of truth (because many electrical + geometric params).

**Required YAML fields** (example):
```yaml
csv_path: "backmodel.csv"
corner: "typical"          # MUST exist exactly in CSV
length_um: 20.0
metals: ["M1", "M2", "M3", "M4"]
max_width_um: 0.04
segment_um: 1.0
via_pitch_um: 0.5          # independent of segment
driver_r_ohm: 80.0
device_r_ohm: 45.0
device_c_ff: 0.35
via_r_ohm: 8.0
output_dir: "results"
```

**Argparse** (thin):
- --config (required)
- --output-dir
- --csv-override (debug)
- --log-level
- --no-plot / --no-report

Config loaded into immutable-ish `WireConfig` dataclass. Validation for types, ranges, non-negative.

## 4. BEOLModelDB

- Load CSV with strict column check.
- Group by (Structure, Corner, ShapeColor).
- On init or first use: validate that Config.corner exists exactly for the used Structures → raise BEOLDataError with available corners.
- Per group: build high-precision 2D interpolator (CloughTocher2DInterpolator preferred for accuracy).
- Post-interpolation monotonicity enforcement for physical laws:
  - Rsh non-increasing with Width
  - Ctotal/Cc non-increasing with Space
- API:
  - `get_rc_params(structure, corner, shape_color, width, space) → dict(Rsh, Ctotal, Cc, Cbottom)`
  - `get_available_grid(...) → (widths, spaces)` for enumeration
  - `validate_corner(corner, structures=None)`

No extrapolation outside data convex hull (error or strict clip + warning).

## 5. WirePattern and PatternEnumerator

**WirePattern** (frozen dataclass):
- layers: tuple of metals
- specs: dict[metal → {width, space, colors: tuple}]
- description: human readable string e.g. "M3(0.040/0.020/ABA+BAB)+M4(0.035/0.025/ABA)"
- is_valid() enforces rules
- key() for hashing/caching
- Support for "fixed" base signals (see Config).

**Layer Direction Rules for Stacking (叠线)**:
- Metals are partitioned into direction groups (standard BEOL practice):
  - Group "odd" / horizontal: M1, M3, M5, ...
  - Group "even" / vertical: M2, M4, M6, ...
- Same-layer 并线 (multiple colors on one metal) is always allowed (independent of direction).
- For multi-metal stacking (叠线 / parallel on different layers in one pattern): **only metals from the same direction group** may be combined. Cross-direction stacking is forbidden. The enumerator and is_valid() enforce this strictly.

**Rules** (enforced at generation + validation):
- Same-layer parallel (multiple colors on one metal): same width + space, colors can be ['ABA'], ['BAB'], or both.
- Cross-layer (stacking): independent width/space/color per metal **but only within same direction group**.
- All chosen (W,S,Color) must be valid in DB (or interpolatable).
- Fixed signals (see below) are always included and lock their (metal, W, S, colors).

**PatternEnumerator**:
- From config + db, for each metal: decide not-use or use with (W,S) from available grid (filtered by max_width) + color combinations.
- Cartesian product over metals → candidates.
- Filter is_valid() (including direction group check for multi-metal).
- **Fixed signals support**: If config.fixed_signals is non-empty, every generated pattern starts with the fixed base specs (locked W/S/Color for those metals). The enumerator then adds optional additional metals **only from the same direction group(s) as the fixed base**. Fixed metals are not "optional".
- Pruning for practicality: limit layers (1-3), limit (W,S) candidates per layer (top by R or uniform sample), prefer upper metals.
- Configurable via max_patterns or similar in future.

**Fixed Signals (user "fix")**:
- Config supports `fixed_signals: list[dict]` (or under a `fixed:` group in YAML).
- Each entry: {"metal": "M1", "width": 0.06, "space": 0.54, "colors": ["ABA"]}
- These are mandatory in every candidate pattern. The search optimizes what (if anything) to add in parallel/stacking with the fixed base (respecting direction).
- In equivalent R/C calculation (evaluator): fixed metals are always part of the parallel bundle.
- In reports: fixed parts are highlighted (e.g. "FIXED: M1(0.060/0.540/ABA) + optimized M3(...)").
- This allows "I have already routed M1 at these exact dimensions; find the best way to parallel/stack additional layers with it."

**Pareto**:
- Pareto front is computed on the two user objectives: **far_end_delay** (min) and **avg_end_delay** (min).
- No separate cost axis for the front itself (total_metal_width_sum and other proxies are kept in tables/records for information and future use).
- The two always-highlighted points are the absolute best far and the absolute best avg (even if not on the front). The front itself shows the trade-off between far and avg.

## 6. ElmoreLadderEvaluator

**Topology** (exact user spec):
driver_R → [wire_segment_R (len=segment)] → [via_eq (scaled by 1/via_pitch)] → device_R (series) → device_C (to gnd) → next segment...

**Per Pattern evaluation**:
- For each metal in pattern: query DB → compute metal contrib R_per_um = Rsh / (width * num_colors), C contrib.
- Parallel all metals for pattern equiv R_per_um = 1/sum(1/R_i), C_per_um ≈ sum(C_i).
- Add via series density: via_R * (1/via_pitch) added to equiv R.
- Build N ≈ length / segment segments.
- Run classic Elmore (prefix R * downstream C) to every device tap.
- Compute:
  - near (first device)
  - far (last device)
  - avg (mean over all devices)
- For both τ (raw Elmore) and prop ≈ 0.69 * τ (50% delay estimate).
- Return full dict + per_device list for profiles.

Via scaling is density-based and independent of segment.

## 7. Optimizer

**WLInterconnectOptimizer** (main orchestrator):
- __init__ from config_path or config object.
- run():
  1. Create DB, validate corner.
  2. Enumerator.generate() → list[WirePattern]
  3. For each: evaluator.evaluate() → record with description, all delays, equiv params, metal_count, total_width_sum (cost proxy).
  4. Collect all.
  5. Compute Pareto front (far_prop delay vs total_metal_width_sum). Simple non-dominated sort.
  6. Identify best_far_end (min far_prop), best_avg (min avg_prop).
  7. Return OptimizationResult (all_patterns, pareto_front, best_*, summary).

All patterns are evaluated (systematic, per approved approach 1). Pruning only in enumerator for feasibility.

## 8. Reporting and Plotting

**ReportGenerator**:
- write_markdown(): Commercial style
  - Header with config summary + key conclusions (two bests highlighted).
  - Main table: Rank | Pattern Description | far_prop | avg_prop | far_tau | ... | total_width_sum | is_pareto | Pareto Rank | relative improvement.
  - Two special point cards.
  - Full config echo.
  - Stats (num evaluated, time, etc.).
- write_csv(): flat all_patterns table for further analysis.

**Plotter** (matplotlib, high quality, saved to PNG):
- pareto_scatter.png: far delay vs total_width_sum, Pareto line, every point labeled with full "M3(...)+M4(...)", bests annotated with arrows + large text.
- sensitivity_width.png or similar: multiple curves (representative patterns) of far/avg delay vs Width.
- delay_profile_top.png: cumulative prop delay vs position along WL for best far, best avg, and 2-3 other interesting patterns. Vertical lines at device taps.
- top_n_comparison.png: bar or grouped bars for top patterns.
- Additional as needed (via/segment impact if relevant).

All artifacts in output_dir with clear names. Report.md embeds or references the plots with explanations like "This pattern has the lowest far-end delay among all 12k+ evaluated combinations and lies on the Pareto front."

## 9. CLI, Public API, Error Handling, Logging, Extensibility

**CLI** (argparse, thin):
- --config (required)
- --output-dir
- --log-level
- --no-plot etc.

**Public API** (import friendly):
```python
from sram_beol import WLInterconnectOptimizer
opt = WLInterconnectOptimizer(config_path="...")
result = opt.run()
opt.generate_report(result)
opt.plot(result)
```

**Error Handling**:
- Dedicated exceptions: BEOLConfigError, BEOLDataError (with available corners), etc.
- Clear messages with actionable suggestions.
- CLI catches top level and prints friendly message + exit 1.

**Logging**: stdlib logging, configurable, key milestones logged.

**Extensibility**:
- Config can accept custom pareto_cost_fn.
- Subclass Evaluator for future models.
- Hooks in Optimizer/Report for custom post-processing.
- Result object extensible.

**Usage Examples**:
- CLI as above.
- Python: full import example with result inspection.

## 10. Assumptions, Risks, Future Work

**Assumptions**:
- CSV data is per-unit-length for the given corner.
- Via resistance is provided as single via value; density scaling is sufficient.
- Ctotal linear sum is acceptable approximation for parallel conductors (Cc/Cbottom usage can be refined later).
- segment and via_pitch units are um.
- "Propagation delay" estimate via 0.69*τ is sufficient for correlation with SPICE (user can extend).

**Risks & Mitigations**:
- Combinatorial explosion: mitigated by enumerator pruning + config limits.
- Interpolation accuracy: high-order + monotonic enforcement + no extrapolation.
- User corner not in CSV: hard error with list of available.

**Future**:
- More accurate C modeling (Miller, layer proximity).
- Power/area as additional Pareto dimensions.
- Support for non-uniform via density or tapered widths.
- Integration with full net RC extraction flows.

---

This document compiles all approved design sections. All implementation must strictly follow the interfaces, rules, and behaviors described above.

## 11. Implementation Roadmap (High Level)

1. Project scaffolding (package, pyproject.toml, basic CLI skeleton).
2. Config + exceptions.
3. BEOLModelDB (CSV + interpolation with tests for physical constraints + corner validation).
4. WirePattern + PatternEnumerator (rules + generation + pruning).
5. ElmoreLadderEvaluator (topology + multi-layer equiv + via scaling + full Elmore + tests).
6. Optimizer (full flow + Pareto + two highlights).
7. Report + Plot (commercial output + all required proof plots).
8. CLI polish, public API, logging, docs, examples.
9. Comprehensive tests (unit for each class, integration for full run on sample data).
10. Packaging and verification on the target Windows environment.

All code must be clean, well-documented, and directly traceable to this design.