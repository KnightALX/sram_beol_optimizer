"""
Plotter: generates all required proof plots per design Section 8.

- pareto_scatter.png (labeled full descriptions)
- sensitivity curves (width impact)
- delay_profile_top.png (along WL for top patterns + device taps)
- top_n_comparison.png (bars)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # headless safe
import matplotlib.pyplot as plt
import numpy as np

from .config import WireConfig
from .optimizer import OptimizationResult

logger = logging.getLogger(__name__)


class Plotter:
    """High-quality matplotlib plots for optimality proof."""

    def __init__(self, output_dir: str | Path, dpi: int = 150):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dpi = dpi
        plt.rcParams.update({
            "figure.dpi": dpi,
            "savefig.dpi": dpi,
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.titlesize": 11,
            "legend.fontsize": 8,
            "figure.figsize": (10, 6),
            "axes.grid": True,
            "grid.alpha": 0.3,
        })

    def _savefig(self, fig: plt.Figure, name: str) -> Path:
        p = self.output_dir / name
        fig.tight_layout()
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved plot %s", p)
        return p

    # ---------- Main required plots ----------

    def plot_pareto_scatter(self, result: OptimizationResult) -> Path:
        """Pareto scatter with EVERY point labeled by full description. Annotate bests."""
        records = result.all_records
        pareto = result.pareto_front
        best_far = result.best_far_end
        best_avg = result.best_avg

        fig, ax = plt.subplots(figsize=(14, 9))

        x_vals = [r["far_prop"] for r in records]
        y_vals = [r["avg_prop"] for r in records]

        # All points (x=far, y=avg)
        ax.scatter(x_vals, y_vals, c="steelblue", s=28, alpha=0.65, zorder=3, label="All patterns")

        # Pareto front line (sorted by far for nice line)
        if pareto:
            p_x = [p["far_prop"] for p in sorted(pareto, key=lambda d: d["far_prop"])]
            p_y = [p["avg_prop"] for p in sorted(pareto, key=lambda d: d["far_prop"])]
            ax.plot(p_x, p_y, "r-o", linewidth=1.8, markersize=5, label="Pareto front", zorder=4)

        # Label EVERY point (full desc)
        for r in records:
            x = r["far_prop"]
            y = r["avg_prop"]
            label = r["description"]
            ax.annotate(
                label,
                (x, y),
                textcoords="offset points",
                xytext=(3, 3),
                fontsize=5.5,
                alpha=0.85,
                rotation=18,
                zorder=2,
            )

        # Highlight & annotate BEST FAR
        ax.scatter([best_far["far_prop"]], [best_far["avg_prop"]], c="lime", s=140, marker="*", zorder=5, edgecolors="black", linewidths=0.8, label="Best far-end")
        ax.annotate(
            "BEST FAR-END\n" + best_far["description"],
            (best_far["far_prop"], best_far["avg_prop"]),
            textcoords="offset points",
            xytext=(12, 18),
            fontsize=8,
            fontweight="bold",
            color="darkgreen",
            arrowprops=dict(arrowstyle="->", color="darkgreen", lw=1.5),
            zorder=6,
        )

        # Highlight BEST AVG
        ax.scatter([best_avg["far_prop"]], [best_avg["avg_prop"]], c="orange", s=110, marker="D", zorder=5, edgecolors="black", linewidths=0.8, label="Best avg")
        ax.annotate(
            "BEST AVG\n" + best_avg["description"],
            (best_avg["far_prop"], best_avg["avg_prop"]),
            textcoords="offset points",
            xytext=(10, -22),
            fontsize=8,
            fontweight="bold",
            color="darkorange",
            arrowprops=dict(arrowstyle="->", color="darkorange", lw=1.5),
            zorder=6,
        )

        ax.set_xlabel("Far-end propagation delay (0.69 * τ) [ps]")
        ax.set_ylabel("Average propagation delay (0.69 * τ) [ps]")
        ax.set_title("Pareto Front: Far-End Delay vs. Average Delay\n(Both objectives minimized. Every evaluated pattern labeled with full layer combo description. Fixed signals shown with their locked W/S/Color.)")
        ax.legend(loc="best", framealpha=0.92)
        ax.grid(True, alpha=0.3)

        # Add text box with counts
        txt = f"N={len(records)}  |  Pareto={len(pareto)}  |  best_far={_short(best_far['description'])}"
        ax.text(0.02, 0.98, txt, transform=ax.transAxes, fontsize=8,
                verticalalignment="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.6))

        return self._savefig(fig, "pareto_scatter.png")

    def plot_sensitivity_width(self, result: OptimizationResult) -> Path:
        """Sensitivity of delay to width choice. Multiple representative curves."""
        records = result.all_records

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

        # Group records by "signature" = layers + colors (ignore exact w/s for grouping)
        groups: Dict[str, List[Dict]] = {}
        for r in records:
            # signature from description rough or layers
            sig = r.get("description", "").split("(")[0] + "|" + str(r.get("pattern_layers"))
            # Better: use the first color choice etc, but simple bucket by metal_count + first layer
            sig = f"L{r['metal_count']}_{r.get('pattern_layers', [''])[0]}"
            groups.setdefault(sig, []).append(r)

        # For each group with >=2 points, sort by inferred width proxy (use total_width_sum / layers rough) or just plot vs total_width as proxy
        # Since we don't store per-layer w easily, use total_width_sum as x (monotonic with w), plot far and avg
        plotted = 0
        for sig, recs in list(groups.items())[:6]:  # limit series
            if len(recs) < 2:
                continue
            # sort by total_width_sum (proxy for increasing width choice)
            srec = sorted(recs, key=lambda x: x["total_width_sum"])
            xs = [rr["total_width_sum"] for rr in srec]
            far_y = [rr["far_prop"] for rr in srec]
            avg_y = [rr["avg_prop"] for rr in srec]
            ax1.plot(xs, far_y, marker="o", linewidth=1.4, markersize=4, label=sig, alpha=0.85)
            ax2.plot(xs, avg_y, marker="s", linewidth=1.4, markersize=4, label=sig, alpha=0.85)
            plotted += 1

        if plotted == 0:
            # Fallback: just scatter all
            xs = [r["total_width_sum"] for r in records]
            ax1.scatter(xs, [r["far_prop"] for r in records], alpha=0.6)
            ax2.scatter(xs, [r["avg_prop"] for r in records], alpha=0.6)

        ax1.set_xlabel("Total width sum (increasing width / parallel tracks)")
        ax1.set_ylabel("far_prop")
        ax1.set_title("Sensitivity: Far-end delay vs Width/Cost (by layer group)")
        ax1.legend(fontsize=7, loc="best")

        ax2.set_xlabel("Total width sum")
        ax2.set_ylabel("avg_prop")
        ax2.set_title("Sensitivity: Avg delay vs Width/Cost (by layer group)")
        ax2.legend(fontsize=7, loc="best")

        fig.suptitle("Delay Sensitivity to Metal Width Choices (representative layer/color families)")
        return self._savefig(fig, "sensitivity_width.png")

    def plot_delay_profiles(self, result: OptimizationResult, top_n: int = 5) -> Path:
        """Delay profile along WL (prop delay vs position) for best + other top patterns. Vertical tap lines."""
        best_far = result.best_far_end
        best_avg = result.best_avg

        # Select interesting patterns: best_far, best_avg, and up to 3 more from front or low far
        candidates = [best_far, best_avg]
        for r in result.pareto_front:
            if r["description"] not in [c["description"] for c in candidates]:
                candidates.append(r)
            if len(candidates) >= top_n:
                break
        # Also add one more if possible: lowest cost overall or highest width
        if len(candidates) < top_n:
            sorted_by_cost = sorted(result.all_records, key=lambda x: x["total_width_sum"])
            for r in sorted_by_cost[:3]:
                if r["description"] not in [c["description"] for c in candidates]:
                    candidates.append(r)
                    if len(candidates) >= top_n:
                        break

        fig, ax = plt.subplots(figsize=(11, 6))

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for idx, rec in enumerate(candidates[:top_n]):
            pos = rec.get("device_positions_um", [])
            prof = rec.get("per_device_prop", [])
            if not pos or not prof:
                continue
            label = rec["description"]
            if rec is best_far or rec["description"] == best_far["description"]:
                label = "★ BEST FAR: " + label
            elif rec is best_avg or rec["description"] == best_avg["description"]:
                label = "◆ BEST AVG: " + label
            ax.plot(pos, prof, marker=".", linewidth=1.6, markersize=3.5, label=label[:70], color=colors[idx % len(colors)], alpha=0.92)

            # Vertical lines at device taps (use the positions)
            for p in pos:
                ax.axvline(p, color=colors[idx % len(colors)], alpha=0.08, linewidth=0.6)

        ax.set_xlabel("Position along WL (um)")
        ax.set_ylabel("Cumulative propagation delay estimate (0.69 * τ) [arb units]")
        ax.set_title("Delay Profiles Along WordLine (device taps shown as vertical lines)\nLower curves = faster at that tap")
        ax.legend(loc="upper left", fontsize=7, framealpha=0.9)
        ax.grid(True, alpha=0.25)

        # Mark far end
        ax.axvline(result.config.length_um, color="red", linestyle="--", alpha=0.5, label="WL end")
        return self._savefig(fig, "delay_profile_top.png")

    def plot_top_n_comparison(self, result: OptimizationResult, n: int = 8) -> Path:
        """Grouped bar chart for top-N patterns on far_prop, avg_prop and cost."""
        # Take top N by far_prop (lowest)
        top = sorted(result.all_records, key=lambda r: r["far_prop"])[:n]

        names = [r["description"][:45] + ("..." if len(r["description"])>45 else "") for r in top]
        far_props = [r["far_prop"] for r in top]
        avg_props = [r["avg_prop"] for r in top]
        costs = [r["total_width_sum"] for r in top]

        x = np.arange(len(names))
        width = 0.28

        fig, ax = plt.subplots(figsize=(12, 6))
        bars1 = ax.bar(x - width, far_props, width, label="far_prop", color="#1f77b4")
        bars2 = ax.bar(x, avg_props, width, label="avg_prop", color="#ff7f0e")
        ax2 = ax.twinx()
        bars3 = ax2.bar(x + width, costs, width, label="total_width_sum (cost)", color="#2ca02c", alpha=0.75)

        ax.set_ylabel("Delay (prop)")
        ax2.set_ylabel("Total width sum (cost)")
        ax.set_title(f"Top-{n} Patterns Comparison (sorted by far_prop)")
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=35, ha="right", fontsize=7)
        ax.legend(loc="upper left")
        ax2.legend(loc="upper right")

        # Annotate best
        for i, r in enumerate(top):
            if r["description"] == result.best_far_end["description"]:
                ax.text(i - width, far_props[i], "★FAR", ha="center", va="bottom", fontsize=8, fontweight="bold", color="darkgreen")
            if r["description"] == result.best_avg["description"]:
                ax.text(i, avg_props[i], "◆AVG", ha="center", va="bottom", fontsize=8, fontweight="bold", color="darkorange")

        fig.tight_layout()
        return self._savefig(fig, "top_n_comparison.png")

    def generate_all(self, result: OptimizationResult, config: Optional[WireConfig] = None) -> List[Path]:
        """Generate all proof plots. Returns list of written PNG paths."""
        paths: List[Path] = []
        paths.append(self.plot_pareto_scatter(result))
        paths.append(self.plot_sensitivity_width(result))
        paths.append(self.plot_delay_profiles(result))
        paths.append(self.plot_top_n_comparison(result))
        logger.info("Generated %d plots into %s", len(paths), self.output_dir)
        return paths


def _short(desc: str, max_len: int = 38) -> str:
    return desc if len(desc) <= max_len else desc[:max_len-3] + "..."
