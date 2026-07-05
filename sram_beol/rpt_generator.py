""".rpt report generator — Synopsys PT / Cadence Innovus style plain-text reports.
.rpt 报告生成器 — Synopsys PT / Cadence Innovus 风格的纯文本报告。

Generates structured, sectioned text reports with:
- Header banner with metadata
- Executive summary with highlighted best patterns
- Pareto front table
- Full pattern ranking table
- Equivalent RC parameter breakdown
- Configuration echo
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Separator line width — 分隔线宽度
SEP_WIDTH: int = 77


def _sep(char: str = "=") -> str:
    """Build a full-width separator line."""
    return char * SEP_WIDTH


def _subsep() -> str:
    """Build a subsection separator."""
    return "-" * SEP_WIDTH


def _fmt(v: Any, prec: int = 4, width: int = 0) -> str:
    """Format numeric with precision and optional width.

    Args:
        v: Value to format.
        prec: Decimal precision for floats.
        width: Minimum field width (padded with spaces on left).
    """
    if isinstance(v, float):
        if abs(v) > 1e5 or (0 < abs(v) < 1e-3):
            s = f"{v:.6g}"
        else:
            s = f"{v:.{prec}f}"
    else:
        s = str(v)
    if width > 0:
        s = s.rjust(width)
    return s


def _pad_col(s: str, width: int) -> str:
    """Pad a string to exact column width (truncate or extend with spaces).

    Args:
        s: String to pad.
        width: Target width in characters.
    """
    if len(s) > width:
        return s[:width]
    return s.ljust(width)


class RptGenerator:
    """Generate Synopsys/Cadence style .rpt plain-text optimization reports.

    生成 Synopsys/Cadence 风格的 .rpt 纯文本优化报告。

    Usage:
        content = RptGenerator.generate_string(result, config)
        path = RptGenerator.write(output_dir, result, config)
    """

    @staticmethod
    def generate_string(result: Any, config: Any) -> str:
        """Build complete .rpt report string from optimization result and config.

        从优化结果和配置构建完整 .rpt 报告字符串。

        Args:
            result: OptimizationResult from WLInterconnectOptimizer.run()
            config: WireConfig used for this run

        Returns:
            str — the full report text.
        """
        lines: List[str] = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")

        # ============================================================
        # Report Header — 报告头
        # ============================================================
        lines.append(_sep("="))
        lines.append("  SRAM BEOL WL INTERCONNECT OPTIMIZER")
        lines.append(f"  Report: sram_beol_wl_optimization")
        lines.append(f"  Generated: {now}")
        lines.append(f"  Corner: {config.corner}    WL Length: {config.length_um:.3f} um"
                     f"    Segments: {int(round(config.length_um / config.segment_um))}")
        lines.append(f"  Candidate Metals: {' '.join(config.metals)}")
        if getattr(config, "fixed_signals", None):
            lines.append(f"  Fixed Signals: {config.fixed_signals} [LOCKED]")
        lines.append(f"  BEOL Model DB: {config.csv_path}")
        lines.append(_sep("="))
        lines.append("")

        # ============================================================
        # 1.0 Executive Summary — 执行摘要
        # ============================================================
        summary = result.summary
        best_far = result.best_far_end
        best_avg = result.best_avg

        lines.append("1.0  EXECUTIVE SUMMARY")
        lines.append(_subsep())
        lines.append(f"  Total Patterns Evaluated           : {len(result.all_records)}")
        lines.append(f"  Pareto-Optimal (Non-dominated)     : {len(result.pareto_front)}")
        # P0-3 fix: 防御性格式化 elapsed_seconds，避免缺失时 TypeError
        # Defensive format for elapsed_seconds to avoid TypeError when missing.
        _elapsed = summary.get("elapsed_seconds")
        if isinstance(_elapsed, (int, float)):
            _elapsed_str = f"{_elapsed:.2f}"
        else:
            _elapsed_str = "N/A"
        lines.append(f"  Optimization Runtime               : {_elapsed_str} s")
        lines.append("")

        # Best Far-End block — 最佳远端延迟
        lines.append("  " + "*" * 69)
        lines.append(f"  *  BEST FAR-END DELAY{' ' * 48}*")
        lines.append(f"  *    Pattern : {_pad_col(best_far['description'], 56)}*")
        lines.append(f"  *    far_prop = {_fmt(best_far['far_prop'], 2)} ps"
                     f"    far_tau = {_fmt(best_far['far_tau'], 2)} ps{' ' * 20}*")
        lines.append(f"  *    avg_prop = {_fmt(best_far.get('avg_prop', 0), 2)} ps"
                     f"    avg_tau = {_fmt(best_far.get('avg_tau', 0), 2)} ps{' ' * 20}*")
        lines.append(f"  *    Total Width = {_fmt(best_far['total_width_sum'], 3)} um"
                     f"    Layers = {best_far['metal_count']}"
                     f"    Pareto = {'YES' if best_far.get('is_pareto') else 'NO'}{' ' * 15}*")
        lines.append("  " + "*" * 69)
        lines.append("")

        # Best Average block — 最佳平均延迟
        lines.append("  " + "*" * 69)
        lines.append(f"  *  BEST AVERAGE DELAY{' ' * 49}*")
        lines.append(f"  *    Pattern : {_pad_col(best_avg['description'], 56)}*")
        lines.append(f"  *    avg_prop = {_fmt(best_avg['avg_prop'], 2)} ps"
                     f"    avg_tau = {_fmt(best_avg['avg_tau'], 2)} ps{' ' * 20}*")
        lines.append(f"  *    far_prop = {_fmt(best_avg.get('far_prop', 0), 2)} ps"
                     f"    far_tau = {_fmt(best_avg.get('far_tau', 0), 2)} ps{' ' * 20}*")
        lines.append(f"  *    Total Width = {_fmt(best_avg['total_width_sum'], 3)} um"
                     f"    Layers = {best_avg['metal_count']}"
                     f"    Pareto = {'YES' if best_avg.get('is_pareto') else 'NO'}{' ' * 15}*")
        lines.append("  " + "*" * 69)
        lines.append("")

        # ============================================================
        # 2.0 Pareto Front — Pareto 前沿
        # ============================================================
        pareto = result.pareto_front
        top_n_pareto = min(10, len(pareto))
        lines.append(f"2.0  PARETO FRONT (far_prop vs avg_prop) — Top {top_n_pareto} Non-dominated")
        lines.append(_subsep())
        lines.append(f"  {'Rank':<6} {'Pattern':<45} {'far_prop':>10} {'avg_prop':>10} {'Width':>8} {'L':>3}")
        lines.append(f"  {'-'*6} {'-'*45} {'-'*10} {'-'*10} {'-'*8} {'-'*3}")
        for idx, p in enumerate(pareto[:top_n_pareto], 1):
            desc = _pad_col(p['description'], 45)
            far = _fmt(p['far_prop'], 2)
            avg = _fmt(p['avg_prop'], 2)
            width = _fmt(p['total_width_sum'], 3)
            layers = str(p['metal_count'])
            tag = ""
            if p['description'] == best_far['description']:
                tag = "  ★FAR"
            elif p['description'] == best_avg['description']:
                tag = "  ◆AVG"
            lines.append(f"  {idx:<6} {desc:<45} {far:>10} ps {avg:>10} ps {width:>8} {layers:>3}{tag}")
        if len(pareto) > top_n_pareto:
            lines.append(f"  ... {len(pareto) - top_n_pareto} more Pareto points omitted")
        lines.append("")

        # ============================================================
        # 3.0 Full Pattern Ranking — 全量模式排序
        # ============================================================
        all_recs = result.all_records
        top_n = min(20, len(all_recs))
        lines.append(f"3.0  FULL PATTERN RANKING (sorted by far_prop, top {top_n}/{len(all_recs)})")
        lines.append(_subsep())
        lines.append(
            f"  {'Rank':<6} {'Pattern':<42} {'far_prop':>10} {'avg_prop':>10}"
            f"  {'far_tau':>10} {'avg_tau':>10} {'Width':>8} {'L':>3} {'Pareto':>7}"
        )
        lines.append(f"  {'-'*6} {'-'*42} {'-'*10} {'-'*10}  {'-'*10} {'-'*10} {'-'*8} {'-'*3} {'-'*7}")
        for idx, rec in enumerate(all_recs[:top_n], 1):
            desc = _pad_col(rec['description'], 42)
            far_p = _fmt(rec['far_prop'], 2)
            avg_p = _fmt(rec['avg_prop'], 2)
            far_t = _fmt(rec['far_tau'], 2)
            avg_t = _fmt(rec['avg_tau'], 2)
            width = _fmt(rec['total_width_sum'], 3)
            layers = str(rec['metal_count'])
            pareto_flag = "YES" if rec.get('is_pareto') else ""
            tag = ""
            if rec['description'] == best_far['description']:
                tag = " ★FAR"
            elif rec['description'] == best_avg['description']:
                tag = " ◆AVG"
            lines.append(
                f"  {idx:<6} {desc:<42} {far_p:>10} {avg_p:>10}  "
                f"{far_t:>10} {avg_t:>10} {width:>8} {layers:>3} {pareto_flag:>7}{tag}"
            )
        if len(all_recs) > top_n:
            lines.append(f"  ... {len(all_recs) - top_n} more patterns truncated")
        lines.append("")

        # ============================================================
        # 4.0 Equivalent RC Parameters — 等效 RC 参数
        # ============================================================
        lines.append("4.0  EQUIVALENT RC PARAMETERS (Best Patterns)")
        lines.append(_subsep())

        # Show RC breakdown for best_far
        lines.append(f"  Pattern: {best_far['description']}  ★FAR")
        equiv_r = best_far.get("equiv_r_per_um", 0)
        equiv_c = best_far.get("equiv_c_per_um", 0)
        lines.append(f"    Equiv R_per_um = {equiv_r:.4f} ohm/um"
                     f"    C_per_um = {equiv_c:.4f} fF/um")
        via_r_per_um = best_far.get("via_r_per_um", config.via_r_ohm / config.via_pitch_um)
        lines.append(f"    Via (density) R_per_um = {via_r_per_um:.4f} ohm/um"
                     f"  (via_R={config.via_r_ohm}, pitch={config.via_pitch_um})")
        lines.append("")

        # Show RC breakdown for best_avg
        lines.append(f"  Pattern: {best_avg['description']}  ◆AVG")
        equiv_r2 = best_avg.get("equiv_r_per_um", 0)
        equiv_c2 = best_avg.get("equiv_c_per_um", 0)
        lines.append(f"    Equiv R_per_um = {equiv_r2:.4f} ohm/um"
                     f"    C_per_um = {equiv_c2:.4f} fF/um")
        lines.append(f"    Via (density) R_per_um = {via_r_per_um:.4f} ohm/um")
        lines.append("")

        # ============================================================
        # 5.0 Configuration Echo — 配置回显
        # ============================================================
        lines.append("5.0  CONFIGURATION ECHO")
        lines.append(_subsep())
        config_items = [
            ("csv_path", config.csv_path),
            ("corner", config.corner),
            ("length_um", config.length_um),
            ("metals", config.metals),
            ("max_width_um", config.max_width_um),
            ("segment_um", config.segment_um),
            ("via_pitch_um", config.via_pitch_um),
            ("driver_r_ohm", config.driver_r_ohm),
            ("device_r_ohm", config.device_r_ohm),
            ("device_c_ff", config.device_c_ff),
            ("via_r_ohm", config.via_r_ohm),
            ("output_dir", config.output_dir),
        ]
        for name, val in config_items:
            lines.append(f"  {name:<16} : {val}")

        if getattr(config, "fixed_signals", None):
            lines.append(f"  {'fixed_signals':<16} : {config.fixed_signals}")
        lines.append("")

        # Footer — 报告尾部
        lines.append(_sep("="))
        lines.append("  END OF REPORT — sram_beol_wl_optimization")
        lines.append(_sep("="))
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def write(output_dir: str | Path, result: Any, config: Any,
              filename: str = "beol_optimization.rpt") -> Path:
        """Generate .rpt text and write to file.

        生成 .rpt 文本并写入文件。

        Args:
            output_dir: Directory to write the .rpt file.
            result: OptimizationResult.
            config: WireConfig.
            filename: Output filename (default: beol_optimization.rpt).

        Returns:
            Path to the written .rpt file.
        """
        content = RptGenerator.generate_string(result, config)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        rpt_path = out / filename
        rpt_path.write_text(content, encoding="utf-8")
        logger.info("Wrote .rpt report to %s (%d bytes)", rpt_path, len(content))
        return rpt_path
