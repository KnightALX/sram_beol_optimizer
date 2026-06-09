# SRAM BEOL Interconnect Optimizer

Long wire (>20 µm) interconnect optimizer for SRAM WordLine (WL) structures in the back-end-of-line (BEOL).

**Goal**: Systematically find the optimal combination of metal layers, widths, spaces, and colors (for multi-patterning) that minimizes distributed Elmore delay on a long WL with periodic poly device taps. Supports same-layer parallel wires and cross-layer strapping with vias.

This is a commercial-grade, class-based, fully importable Python package with a thin command-line interface. YAML is the primary and complete configuration source.

> **Status**: Phase 2 complete (Config, exceptions, logging, thin argparse CLI, public API skeleton + unit tests).  
> Core algorithm, DB loader, evaluator, Pareto logic, reports and plots are under active implementation following the approved design.

## Installation (editable, for development)

```bash
cd D:\workspace\project\sram_beol
pip install -e ".[test]"
```

This installs the `sram-beol-optimizer` console script and makes `from sram_beol import ...` work.

## Quick Start - Command Line (Thin CLI)

The CLI is intentionally minimal. All real parameters live in the YAML file.

```bash
# Basic run (uses output_dir etc. from the YAML)
sram-beol-optimizer --config examples/config.yaml

# With overrides and more logging
sram-beol-optimizer \
  --config examples/config.yaml \
  --output-dir my_results \
  --log-level DEBUG

# Debug with a different CSV (no need to edit YAML)
sram-beol-optimizer --config config.yaml --csv-override /path/to/other_corner.csv

# Skip plots or reports
sram-beol-optimizer --config config.yaml --no-plot --no-report
```

The command is registered via `pyproject.toml` as `sram-beol-optimizer`.

## Quick Start - Python Public API (Recommended for integration)

```python
from sram_beol import WLInterconnectOptimizer, WireConfig, load_wire_config, configure_logging

# 1. Simple: point at your YAML (primary mechanism)
opt = WLInterconnectOptimizer(config_path="config.yaml")
result = opt.run()

# Inspect high-level outcome
print(result.summary)
print("Best far-end pattern:", result.best_far_end)
print("Best avg pattern   :", result.best_avg)

# Generate artifacts (report + plots) exactly as CLI would
opt.generate_report(result)
opt.plot(result)

# 2. Programmatic config + overrides (before optimizer)
configure_logging("DEBUG")          # optional, stdlib
cfg = load_wire_config(
    "config.yaml",
    overrides={"output_dir": "prog_results", "length_um": 30.0}
)
opt2 = WLInterconnectOptimizer(config=cfg)
result2 = opt2.run()
```

The public surface is re-exported cleanly from the top-level package (see `__init__.py`).

## Configuration (YAML is source of truth)

All electrical, geometric, and run-control parameters are supplied via YAML.
This matches the approved design (Section 3) exactly.

Minimal valid example (`config.yaml`):

```yaml
csv_path: "backmodel.csv"
corner: "typical"          # MUST exist exactly in the CSV
length_um: 20.0
metals: ["M1", "M2", "M3", "M4"]
max_width_um: 0.04
segment_um: 1.0
via_pitch_um: 0.5          # independent of segment_um
driver_r_ohm: 80.0
device_r_ohm: 45.0
device_c_ff: 0.35
via_r_ohm: 8.0
output_dir: "results"
```

See the design document for the rationale of every field (segment vs via_pitch independence, corner exact-match requirement, etc.).

`WireConfig` (frozen dataclass) is the in-memory representation. It performs strict validation (positive values, non-empty metals list, etc.) and raises `BEOLConfigError` with actionable messages on problems.

## Error Handling & Logging

- Dedicated exception hierarchy (see `sram_beol.exceptions`):
  - `BEOLConfigError`
  - `BEOLDataError` (corner not found includes available corners)
  - `BEOLRuntimeError`
  - Base `BEOLBaseError`
- CLI always catches at top level, prints a friendly message to stderr, and exits 1.
- Logging uses the Python standard library. Configure via `--log-level` (CLI) or `configure_logging("DEBUG")` (API). All key milestones are logged under the `sram_beol` logger.

## Design & Implementation

The complete approved design lives at:

```
docs/superpowers/specs/2025-06-10-sram-beol-interconnect-optimizer-design.md
```

Key architectural points (strictly followed):
- YAML primary config → `WireConfig`
- Thin argparse (only `--config`, a few overrides + flags)
- Clean public class-based API (`WLInterconnectOptimizer`)
- Future extensibility hooks noted in design (custom cost fn, subclassable evaluator, etc.)
- All reporting/plotting artifacts go under `output_dir`
- Strict physical constraints and exact corner matching enforced in data layer

## Current Implementation Scope (this phase)

Implemented (per task):
- `exceptions.py` – full hierarchy
- `config.py` – `WireConfig` dataclass + YAML loader + validation + `configure_logging`
- `cli.py` – thin argparse + `main()` + error handling
- `optimizer.py` – `WLInterconnectOptimizer` + `OptimizationResult` skeletons with exact `__init__` / `run` / `generate_report` / `plot` entry points
- `sram_beol/__init__.py` – clean re-exports
- `pyproject.toml` already present and wired (console script, deps, pytest)
- Unit tests for config loading/validation + CLI argument parsing
- README with usage examples (explicitly requested)

Remaining (future phases per roadmap):
- BEOLModelDB, interpolation, corner validation
- WirePattern + PatternEnumerator
- ElmoreLadderEvaluator
- Full optimizer logic + Pareto + two highlighted points
- ReportGenerator + Plotter (all required tables and figures)
- Integration tests on sample data
- Polish

## Testing

```bash
# All tests
pytest -q

# Just the config + CLI units created in this phase
pytest tests/test_config.py tests/test_cli.py -q --tb=short
```

## License

Proprietary (as declared in pyproject.toml).
