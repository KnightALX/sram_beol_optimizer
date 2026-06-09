"""
Integration tests: full small example end-to-end.

Runs DB -> Enumerator -> Evaluator -> Optimizer -> Pareto -> Report + Plot.
Verifies OptimizationResult structure, special points, and that all artifacts are produced.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sram_beol import WLInterconnectOptimizer, WireConfig
from sram_beol.optimizer import OptimizationResult
from sram_beol.report import ReportGenerator
from sram_beol.plot import Plotter


@pytest.mark.integration
def test_full_small_optimization_and_artifacts(small_config: WireConfig, tmp_path: Path):
    """Run complete flow on tiny config and assert outputs + structure per design."""
    # Ensure output inside tmp for test isolation
    out_dir = tmp_path / "opt_results"
    # Patch config (frozen)
    object.__setattr__(small_config, "output_dir", str(out_dir))

    opt = WLInterconnectOptimizer(config=small_config)
    result: OptimizationResult = opt.run()

    # === Structure verification (OptimizationResult + records) ===
    assert isinstance(result, OptimizationResult)
    assert len(result.all_records) > 0
    assert len(result.pareto_front) > 0
    assert isinstance(result.best_far_end, dict)
    assert isinstance(result.best_avg, dict)
    assert "far_prop" in result.best_far_end
    assert "avg_prop" in result.best_avg
    assert "description" in result.best_far_end
    assert result.summary["num_patterns_evaluated"] == len(result.all_records)

    # bests are among records
    descs = {r["description"] for r in result.all_records}
    assert result.best_far_end["description"] in descs
    assert result.best_avg["description"] in descs

    # Pareto points are subset
    pareto_descs = {p["description"] for p in result.pareto_front}
    for p in result.pareto_front:
        assert p.get("is_pareto") is True

    # All records have required keys from design
    for rec in result.all_records[:3]:
        for k in ["far_prop", "avg_prop", "far_tau", "total_width_sum", "description",
                  "is_pareto", "per_device_prop", "device_positions_um"]:
            assert k in rec

    # === Generate report + plots explicitly ===
    rg = ReportGenerator(out_dir)
    md_path = rg.write(result, config=small_config)
    assert md_path.exists()
    assert md_path.name == "report.md"

    csv_path = out_dir / "results.csv"
    assert csv_path.exists()

    # Verify markdown content has key sections and highlights
    md_text = md_path.read_text(encoding="utf-8")
    assert "Key Conclusions" in md_text
    assert "BEST FAR-END" in md_text or "best far" in md_text.lower()
    assert "BEST AVG" in md_text or "best avg" in md_text.lower()
    assert "Pareto Front" in md_text
    assert small_config.corner in md_text
    assert "Full Configuration Echo" in md_text
    # At least one full pattern description style
    assert "M3(" in md_text or "M4(" in md_text

    # Verify CSV has header + data
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "description,far_prop" in csv_text or "far_prop" in csv_text.splitlines()[0]
    assert len(csv_text.splitlines()) > 3

    # === Plots ===
    pl = Plotter(out_dir)
    plot_paths = pl.generate_all(result, config=small_config)
    assert len(plot_paths) >= 4

    expected_plots = {
        "pareto_scatter.png",
        "sensitivity_width.png",
        "delay_profile_top.png",
        "top_n_comparison.png",
    }
    for p in plot_paths:
        assert p.exists()
        assert p.suffix == ".png"
    present = {p.name for p in plot_paths}
    assert expected_plots.issubset(present)

    # Pareto scatter must be reasonably sized
    pareto_png = out_dir / "pareto_scatter.png"
    assert pareto_png.stat().st_size > 20000  # non-trivial image with labels

    # === Verify special points extraction ===
    # best_far should have smallest far_prop
    min_far = min(r["far_prop"] for r in result.all_records)
    assert abs(result.best_far_end["far_prop"] - min_far) < 1e-9

    min_avg = min(r["avg_prop"] for r in result.all_records)
    assert abs(result.best_avg["avg_prop"] - min_avg) < 1e-9

    print(f"\n[integration] SUCCESS: {len(result.all_records)} patterns, "
          f"{len(result.pareto_front)} pareto, "
          f"best_far={result.best_far_end['description'][:50]}, "
          f"artifacts in {out_dir}")


@pytest.mark.integration
def test_optimizer_public_api_and_report_plot_facades(small_config: WireConfig, tmp_path: Path):
    """Test the documented public usage pattern from design."""
    object.__setattr__(small_config, "output_dir", str(tmp_path / "api_test"))

    from sram_beol import WLInterconnectOptimizer

    opt = WLInterconnectOptimizer(config=small_config)
    result = opt.run()

    # Facade methods should work and produce files
    md = opt.generate_report(result)
    plots = opt.plot(result)

    assert md.exists()
    assert any("pareto_scatter" in str(p) for p in plots)

    # Direct import of result
    assert hasattr(result, "best_far_end")
    assert hasattr(result, "all_records")
