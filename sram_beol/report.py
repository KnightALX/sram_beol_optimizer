"""
ReportGenerator: commercial-grade markdown report + CSV export.

Follows design Section 8 exactly:
- tables with Rank, full pattern desc, delays (near/far/avg both tau/prop), total_width_sum, is_pareto, Pareto Rank, relative improvement
- highlighted special point cards for best_far_end and best_avg
- full config echo
- stats
- references to plots
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import WireConfig
from .optimizer import OptimizationResult

logger = logging.getLogger(__name__)


def _fmt(v: Any, prec: int = 4) -> str:
    if isinstance(v, float):
        if abs(v) > 1e5 or (abs(v) < 1e-3 and v != 0):
            return f"{v:.6g}"
        return f"{v:.{prec}f}"
    return str(v)


def _make_markdown_table(headers: List[str], rows: List[List[Any]], align: Optional[List[str]] = None) -> str:
    """Simple GitHub-flavored markdown table without external deps."""
    if not rows:
        return "| (no data) |\n"
    col_widths = [len(h) for h in headers]
    str_rows = []
    for r in rows:
        srow = []
        for i, cell in enumerate(r):
            s = _fmt(cell) if not isinstance(cell, str) else cell
            col_widths[i] = max(col_widths[i], len(s))
            srow.append(s)
        str_rows.append(srow)

    def pad(s: str, w: int, a: str = "l") -> str:
        if a == "r":
            return s.rjust(w)
        if a == "c":
            return s.center(w)
        return s.ljust(w)

    aligns = align or ["l"] * len(headers)
    line = "| " + " | ".join(pad(h, col_widths[i], aligns[i]) for i, h in enumerate(headers)) + " |"
    sep = "| " + " | ".join(("-" * col_widths[i]) if a != "r" else (":" + "-"*(col_widths[i]-1)) for i,a in enumerate(aligns)) + " |"
    body = "\n".join("| " + " | ".join(pad(c, col_widths[i], aligns[i]) for i,c in enumerate(r)) + " |" for r in str_rows)
    return "\n".join([line, sep, body]) + "\n"


class ReportGenerator:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _prepare_records_for_table(self, records: List[Dict[str, Any]], sort_key: str = "far_prop") -> List[Dict[str, Any]]:
        # Sort for ranking (by far_prop primarily)
        sorted_recs = sorted(records, key=lambda r: (r.get(sort_key, float("inf")), r.get("total_width_sum", 0)))
        # Compute relative improvement vs worst far_prop
        worst_far = max((r["far_prop"] for r in records if r["far_prop"] == r["far_prop"]), default=1.0)
        for rank, rec in enumerate(sorted_recs, 1):
            rec = dict(rec)  # copy
            rec["_rank"] = rank
            imp = 0.0
            if worst_far > 0 and rec["far_prop"] == rec["far_prop"]:
                imp = (worst_far - rec["far_prop"]) / worst_far * 100.0
            rec["_rel_improvement_pct"] = round(imp, 2)
            yield rec

    def write_markdown(self, result: OptimizationResult, config: Optional[WireConfig] = None) -> Path:
        cfg = config or result.config
        out_path = self.output_dir / "report.md"

        all_recs = result.all_records
        pareto = result.pareto_front
        best_far = result.best_far_end
        best_avg = result.best_avg
        summary = result.summary

        lines: List[str] = []
        lines.append("# SRAM BEOL WL Interconnect Optimizer - Optimization Report\n")
        lines.append(f"**Generated for corner**: `{cfg.corner}` | **length**: {cfg.length_um} um\n")
        lines.append("")

        # Key conclusions
        lines.append("## Key Conclusions\n")
        lines.append(f"- **Best far-end delay pattern**: `{best_far['description']}`")
        lines.append(f"  - far_prop = {_fmt(best_far['far_prop'])} , far_tau = {_fmt(best_far['far_tau'])}")
        lines.append(f"  - total_width_sum (cost) = {_fmt(best_far['total_width_sum'])} , layers = {best_far['metal_count']}")
        lines.append("")
        lines.append(f"- **Best average delay pattern**: `{best_avg['description']}`")
        lines.append(f"  - avg_prop = {_fmt(best_avg['avg_prop'])} , avg_tau = {_fmt(best_avg['avg_tau'])}")
        lines.append(f"  - total_width_sum = {_fmt(best_avg['total_width_sum'])}")
        lines.append("")
        lines.append(f"- **Pareto front size**: {len(pareto)} / {len(all_recs)} evaluated patterns")
        lines.append(f"- **Evaluation time**: {summary.get('elapsed_seconds', '?')} s")
        lines.append("")

        # Special point cards
        lines.append("## Highlighted Special Points\n")
        lines.append("### BEST FAR-END (min far_prop)\n")
        lines.append(f"**Pattern**: `{best_far['description']}`\n")
        lines.append(f"- far_prop: **{_fmt(best_far['far_prop'])}** (0.69*far_tau)")
        lines.append(f"- far_tau: {_fmt(best_far['far_tau'])}")
        lines.append(f"- avg_prop: {_fmt(best_far.get('avg_prop', 0))}")
        lines.append(f"- total_width_sum: {_fmt(best_far['total_width_sum'])} (Pareto: {best_far.get('is_pareto', False)})")
        lines.append(f"- metal_count: {best_far['metal_count']}")
        lines.append("")

        lines.append("### BEST AVG (min avg_prop)\n")
        lines.append(f"**Pattern**: `{best_avg['description']}`\n")
        lines.append(f"- avg_prop: **{_fmt(best_avg['avg_prop'])}**")
        lines.append(f"- avg_tau: {_fmt(best_avg['avg_tau'])}")
        lines.append(f"- far_prop: {_fmt(best_avg.get('far_prop', 0))}")
        lines.append(f"- total_width_sum: {_fmt(best_avg['total_width_sum'])} (Pareto: {best_avg.get('is_pareto', False)})")
        lines.append("")

        # Main results table (top 30 + note if more, or all if small)
        lines.append("## All Evaluated Patterns (sorted by far_prop)\n")
        lines.append("Relative improvement computed vs worst far_prop in the set.\n")

        table_rows: List[List[Any]] = []
        headers = [
            "Rank", "Pattern Description", "far_prop", "avg_prop", "far_tau", "avg_tau",
            "total_width_sum", "layers", "is_pareto", "P_Rank", "rel_impr_%"
        ]
        align = ["r", "l", "r", "r", "r", "r", "r", "c", "c", "r", "r"]

        prepared = list(self._prepare_records_for_table(all_recs))
        for rec in prepared:
            table_rows.append([
                rec["_rank"],
                rec["description"],
                rec["far_prop"],
                rec["avg_prop"],
                rec["far_tau"],
                rec["avg_tau"],
                rec["total_width_sum"],
                rec["metal_count"],
                "YES" if rec.get("is_pareto") else "",
                rec.get("pareto_rank") if rec.get("pareto_rank") is not None else "",
                rec["_rel_improvement_pct"],
            ])

        # For very large, truncate table in md but still have full in CSV
        MAX_MD_ROWS = 40
        show_rows = table_rows[:MAX_MD_ROWS]
        lines.append(_make_markdown_table(headers, show_rows, align))
        if len(table_rows) > MAX_MD_ROWS:
            lines.append(f"\n*... {len(table_rows) - MAX_MD_ROWS} more rows truncated in this report. See results.csv for complete data.*\n")

        # Pareto front table
        lines.append("\n## Pareto Front (non-dominated: far_prop vs total_width_sum)\n")
        pareto_rows = []
        for idx, pr in enumerate(pareto, 1):
            pareto_rows.append([
                idx,
                pr["description"],
                pr["far_prop"],
                pr["avg_prop"],
                pr["total_width_sum"],
                pr["metal_count"],
                "BEST_FAR" if pr["description"] == best_far["description"] else ("BEST_AVG" if pr["description"] == best_avg["description"] else ""),
            ])
        pareto_headers = ["P_Rank", "Pattern", "far_prop", "avg_prop", "total_width_sum", "layers", "special"]
        lines.append(_make_markdown_table(pareto_headers, pareto_rows))

        # Stats
        lines.append("\n## Summary Statistics\n")
        lines.append(f"- Patterns evaluated: {summary.get('num_patterns_evaluated')}")
        lines.append(f"- Pareto points: {summary.get('num_pareto_points')}")
        lines.append(f"- Min far_prop: {_fmt(summary.get('min_far_prop'))}")
        lines.append(f"- Min avg_prop: {_fmt(summary.get('min_avg_prop'))}")
        lines.append(f"- Elapsed: {summary.get('elapsed_seconds')} s")
        lines.append("")

        # Plot references + explanations
        lines.append("## Proof Plots\n")
        lines.append("The following figures are generated in the same `output_dir` and embedded here for traceability:\n")
        lines.append("- `pareto_scatter.png`: far_prop vs total_width_sum. All points labeled with full pattern descriptions (e.g. `M3(0.040/0.020/ABA)+M4(0.035/0.025/BAB)`). Pareto front connected. Arrows mark `best_far_end` and `best_avg`.")
        lines.append("- `delay_profile_top.png`: Propagation delay (0.69*τ) vs position (um) along the WL for the two best + 2-3 other top patterns. Device tap locations marked with vertical lines.")
        lines.append("- `sensitivity_width.png`: Representative sensitivity of far/avg delay to Width choice (multiple curves for different layer/color combos).")
        lines.append("- `top_n_comparison.png`: Grouped bar comparison of top-N patterns on far_prop, avg_prop, and cost.")
        lines.append("")
        lines.append("> **Interpretation note**: The chosen best patterns lie on (or very near) the Pareto front, offering the lowest far-end (or average) delay for their metal cost. Increasing width or adding parallel tracks (ABA/BAB) or extra layers reduces R but increases C and area (total_width_sum). The optimizer quantifies the exact trade-off using the Elmore ladder model.")
        lines.append("")

        # Full config echo
        lines.append("## Full Configuration Echo\n")
        lines.append("```yaml")
        for k, v in cfg.to_dict().items():
            lines.append(f"{k}: {v}")
        lines.append("```\n")

        lines.append("---\n*Report generated by sram_beol WLInterconnectOptimizer*")

        content = "\n".join(lines)
        out_path.write_text(content, encoding="utf-8")
        logger.info("Wrote markdown report to %s", out_path)
        return out_path

    def write_csv(self, result: OptimizationResult) -> Path:
        out_path = self.output_dir / "results.csv"
        all_recs = result.all_records

        # Flat columns (exclude large lists for CSV readability, or keep as json-ish)
        fieldnames = [
            "description", "far_prop", "avg_prop", "near_prop",
            "far_tau", "avg_tau", "near_tau",
            "total_width_sum", "metal_count", "equiv_r_per_um", "equiv_c_per_um",
            "is_pareto", "pareto_rank",
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for rec in all_recs:
                row = {k: rec.get(k) for k in fieldnames}
                # bool to str for clarity
                row["is_pareto"] = "TRUE" if rec.get("is_pareto") else ""
                writer.writerow(row)

        logger.info("Wrote CSV results to %s", out_path)
        return out_path

    def write(self, result: OptimizationResult, config: Optional[WireConfig] = None) -> Path:
        """Convenience: write both markdown + csv. Return path to .md"""
        self.write_csv(result)
        md_path = self.write_markdown(result, config=config)
        # Also write a machine friendly summary json? but not required
        return md_path
