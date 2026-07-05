# SRAM BEOL Interconnect Optimizer

Long-wire (>20 µm) interconnect optimizer for SRAM WordLine (WL) structures in the back-end-of-line (BEOL).

**Goal**: Find the optimal combination of metal layers (M1–M5+), widths, spaces, and colors (for multi-patterning) that minimizes distributed Elmore delay on a long WL with periodic poly device loads. The tool respects real BEOL stacking rules and supports user-pinned (fixed) routes.

This is a complete, commercial-grade, class-based Python package with a thin CLI. YAML is the primary configuration mechanism.

## Key Features

- **Accurate physical model**: Elmore delay on a distributed RC ladder. Device loads (R + C to ground) every `segment_um`. Vias for strapping scaled by independent `via_pitch_um`.
- **Realistic routing rules**:
  - Same-layer parallel (`并线`): multiple colors (ABA/BAB) on one metal with identical W/S.
  - Cross-layer stacking (`叠线`): only allowed within the same direction group (odd layers M1/M3/M5... vs even layers M2/M4/M6...).
- **Fixed signals support**: Pin specific layers with exact W/S/Color (e.g. already-routed M1 at 0.06/0.54/ABA). The optimizer finds the best additional same-direction parallel/stacking on top.
- **Grouped YAML configuration**: Clean sections (`geometry:`, `electrical:`, `fixed_signals:`) for readability.
- **Systematic search + Pareto**: Explores valid patterns (pruned for practicality). Pareto front on the two objectives that matter: **far-end delay** and **average delay** (both minimized). Always highlights the absolute best-far and best-average patterns.
- **Commercial-grade outputs**:
  - Detailed Markdown + CSV report with full pattern descriptions, metrics, Pareto membership, and relative improvements.
  - Proof-of-optimality plots: Pareto scatter (every point labeled with the exact "M3(0.040/0.020/ABA+BAB)+M5(...)" description), sensitivity curves, delay profiles along the WL, top-N comparisons.
  - Optional interactive Dash dashboard on `http://localhost:8050` (opt-in via `--dashboard`; OFF by default so batch / CI runs don't block).
- **Easy to use**: Thin CLI + clean public Python API. Fully importable.

## Installation

```bash
cd D:\workspace\project\sram_beol
pip install -e ".[test]"
```

This registers the `sram-beol-optimizer` console script and enables `from sram_beol import ...`.

## Quick Start

### Command Line

```bash
# Run with your config (output_dir etc. come from YAML)
sram-beol-optimizer --config config.yaml

# Override output dir or CSV for quick experiments
sram-beol-optimizer --config config.yaml --output-dir my_results --csv-override other.csv

# Skip plots or reports
sram-beol-optimizer --config config.yaml --no-plot --no-report

# Launch the interactive Dash dashboard (opens http://localhost:8050, blocks until Ctrl+C).
# Default: dashboard is OFF (safe for batch / CI / pipelines runs).
sram-beol-optimizer --config config.yaml --dashboard

# Batch / pipeline usage (recommended — same as just running without --dashboard):
sram-beol-optimizer --config config.yaml --no-dashboard
```

### Python API (recommended for integration / notebooks)

```python
from sram_beol import WLInterconnectOptimizer

opt = WLInterconnectOptimizer(config_path="config.yaml")
result = opt.run()

print("Best far-end pattern:", result.best_far_end["description"])
print("Best avg pattern    :", result.best_avg["description"])

opt.generate_report(result)
opt.plot(result)          # writes report.md + results.csv + 4 proof plots into output_dir
```

## Configuration

YAML is the single source of truth. It supports clean grouping:

```yaml
geometry:
  length_um: 20.0
  metals: ["M1", "M2", "M3", "M4", "M5"]
  max_width_um: 0.060
  segment_um: 1.0
  via_pitch_um: 0.5

electrical:
  driver_r_ohm: 80.0
  device_r_ohm: 45.0
  device_c_ff: 0.35
  via_r_ohm: 8.0

# Optional: force-include already-routed wires (locked W/S/Color)
fixed_signals:
  - metal: "M1"
    width: 0.060
    space: 0.540
    colors: ["ABA"]

csv_path: "backmodel.csv"
corner: "typical"          # must exist exactly in the CSV
output_dir: "results"
```

### Per-Layer Geometry Constraints

By default, `geometry.max_width_um` is the only width bound applied to all metals.
To model real PDK rules where each metal has its own (W, S) design window, add a
`geometry.layer_constraints` section:

```yaml
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
```

**Resolution rules:**

- All four numeric fields are optional. Missing = unbounded on that side.
- `max_width_um` per-layer **overrides** the global `geometry.max_width_um` (you can
  have M5 up to 0.070 um even if global is 0.060 um).
- Candidates are filtered against the **DB grid** — only (W, S) points actually
  present in the CSV are emitted.
- If the constraint range yields zero DB candidates for a metal, a WARNING is logged
  and that metal is skipped.
- Metals referenced in `layer_constraints` must exist in `geometry.metals`.

### Multi-Line Fixed Signals

`fixed_signals` is a list of `metal, width, space, colors` dicts. To fix multiple
layers simultaneously (e.g. a bitline + wordline pair), add multiple entries:

```yaml
fixed_signals:
  - metal: "M1"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
  - metal: "M3"
    width: 0.030
    space: 0.030
    colors: ["ABA"]
```

All fixed metals must be in the same direction group (all odd M1/M3/M5 or all even
M2/M4/M6). Mixed-direction fixes log a WARNING but are still allowed; the optimizer
will union candidate stacking metals across both directions.

See the full design document for the complete schema and rationale.

## Output

All artifacts are written under the `output_dir` you specify:

- `report.md` – commercial-style report with key conclusions, highlighted best patterns, full ranked table, Pareto membership, and config echo.
- `results.csv` – machine-readable table of every evaluated pattern.
- `pareto_scatter.png` – far-end vs average delay Pareto front (every evaluated point labeled with the exact layer combo).
- `sensitivity_width.png`, `delay_profile_top.png`, `top_n_comparison.png` – additional plots that prove why the chosen solution is optimal.

## How It Works (High Level)

1. Load BEOL RC model (CSV) + validate corner.
2. Generate valid `WirePattern`s (respecting direction groups + any fixed signals).
3. For each pattern compute equivalent R/C (parallel metals + via density) and run the Elmore ladder.
4. Collect near/far/average delay (both τ and 0.69*τ propagation estimate).
5. Compute Pareto front on (far delay, avg delay).
6. Emit rich report + plots.

The design document (`docs/superpowers/specs/2025-06-10-sram-beol-interconnect-optimizer-design.md`) contains the complete approved specification, including all interfaces, physical model details, and proof-plot requirements.

## Testing

```bash
pytest -q
# or just the units created/updated for the current feature set
pytest tests/test_config.py tests/test_pattern.py tests/test_evaluator.py -q
```

## Design Document

The authoritative design (all sections approved) lives at:

```
docs/superpowers/specs/2025-06-10-sram-beol-interconnect-optimizer-design.md
```

It is the single source of truth for requirements, interfaces, and acceptance criteria.

## License

Proprietary (see pyproject.toml).
