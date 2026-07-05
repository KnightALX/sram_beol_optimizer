"""Dash callbacks for SRAM BEOL Interconnect Optimizer Dashboard.
Dash 回调函数 — SRAM BEOL 互连线优化器仪表板。

Handles 5 tabs: Summary, Pareto Analysis, Pattern Explorer,
Delay Profiles, and Export .rpt.
处理 5 个 Tab：摘要、Pareto 分析、模式浏览器、延迟曲线、.rpt 导出。
"""

from __future__ import annotations

import io
import csv
from typing import Any, Dict, List, Optional

import dash
import plotly.graph_objects as go
from dash import dash_table, dcc
from dash.dependencies import Input, Output, State

# ============================================================
# Plotly Theme — matching light EDA palette
# Plotly 主题 — 匹配浅色 EDA 配色
# ============================================================
PLOTLY_TEMPLATE: dict = {
    "layout": {
        "paper_bgcolor": "#f8f9fb",
        "plot_bgcolor": "#f8f9fb",
        "font": {"color": "#1e293b", "family": "IBM Plex Sans, Inter, sans-serif", "size": 11},
        "title": {"font": {"color": "#1e293b", "size": 13}},
        "xaxis": {
            "gridcolor": "#e4e7ec",
            "zerolinecolor": "#d0d5dd",
            "linecolor": "#d0d5dd",
            "tickfont": {"color": "#475569", "size": 10},
        },
        "yaxis": {
            "gridcolor": "#e4e7ec",
            "zerolinecolor": "#d0d5dd",
            "linecolor": "#d0d5dd",
            "tickfont": {"color": "#475569", "size": 10},
        },
        "legend": {"font": {"color": "#475569", "size": 10}},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 50},
    }
}


def _fmt(v: Any, prec: int = 4) -> str:
    if isinstance(v, float):
        if abs(v) > 1e5 or (0 < abs(v) < 1e-3):
            return f"{v:.6g}"
        return f"{v:.{prec}f}"
    return str(v)


def _short(desc: str, max_len: int = 50) -> str:
    return desc if len(desc) <= max_len else desc[:max_len - 3] + "..."


# ============================================================
# Axis key mapping — supported objective pairs in Pareto tab
# 轴键映射 — Pareto Tab 支持的目标对
# ============================================================
AXIS_KEYS: Dict[str, Dict[str, str]] = {
    "far/avg": {"x": "far_prop", "y": "avg_prop"},
    "far/near": {"x": "far_prop", "y": "near_prop"},
    "avg/near": {"x": "avg_prop", "y": "near_prop"},
}

# Top-N patterns default for Delay Profiles Tab
# 默认 Top-N 用于延迟曲线 Tab
DEFAULT_TOP_N: int = 5
MAX_TOP_N: int = 12


# ============================================================
# Callback Registration
# 回调注册入口
# ============================================================
def register_callbacks(app: dash.Dash, result: Any, config: Any) -> None:
    """Register all callbacks for the 5-tab dashboard.
    注册 5-Tab 仪表板全部回调。

    Composed of:
      - register_summary_callbacks (Summary tab)
      - register_pareto_callbacks (Pareto Analysis tab)
      - register_pattern_explorer_callbacks (Pattern Explorer tab)
      - register_delay_profile_callbacks (Delay Profiles tab)
      - register_export_callbacks (Export .rpt tab)
    """
    register_summary_callbacks(app)
    register_pareto_callbacks(app)
    register_pattern_explorer_callbacks(app)
    register_delay_profile_callbacks(app, result, config)
    register_export_callbacks(app, result, config)


# ============================================================
# Summary — Metric Cards + Thumbnail Pareto
# 摘要 — 指标卡片 + 缩略 Pareto
# ============================================================
def register_summary_callbacks(app: dash.Dash) -> None:
    """Wire callbacks for Summary tab metric cards + thumbnail Pareto figure.
    注册摘要 Tab 的指标卡片和缩略图回调。"""

    @app.callback(
        Output("metric-best-far", "children"),
        Output("metric-best-far-sub", "children"),
        Output("metric-best-avg", "children"),
        Output("metric-best-avg-sub", "children"),
        Output("metric-n-patterns", "children"),
        Output("metric-n-pareto", "children"),
        Output("metric-runtime", "children"),
        Output("metric-pareto-size", "children"),
        Output("summary-best-far-desc", "children"),
        Output("summary-best-far-detail", "children"),
        Output("summary-best-avg-desc", "children"),
        Output("summary-best-avg-detail", "children"),
        Input("store-result", "data"),
    )
    def update_summary_metrics(store: dict) -> tuple:
        if not store:
            return ("-",) * 12
        best_far = store.get("best_far_end", {})
        best_avg = store.get("best_avg", {})
        summary = store.get("summary", {})

        far_prop = _fmt(best_far.get("far_prop"), 2) + " ps"
        far_sub = _short(best_far.get("description", "-"))
        avg_prop = _fmt(best_avg.get("avg_prop"), 2) + " ps"
        avg_sub = _short(best_avg.get("description", "-"))
        n_pat = str(summary.get("num_patterns_evaluated", "-"))
        n_par = f"{summary.get('num_pareto_points', '-')} Pareto-optimal"
        runtime = _fmt(summary.get("elapsed_seconds", "-"), 2) + " s"
        pareto_sz = str(summary.get("num_pareto_points", "-"))

        far_desc = best_far.get("description", "-")
        far_detail = (
            f"far_prop = {_fmt(best_far.get('far_prop'), 2)} ps  |  "
            f"far_τ = {_fmt(best_far.get('far_tau'), 2)} ps  |  "
            f"total_width = {_fmt(best_far.get('total_width_sum'), 3)} μm  |  "
            f"Pareto: {'YES' if best_far.get('is_pareto') else 'NO'}"
        )
        avg_desc = best_avg.get("description", "-")
        avg_detail = (
            f"avg_prop = {_fmt(best_avg.get('avg_prop'), 2)} ps  |  "
            f"avg_τ = {_fmt(best_avg.get('avg_tau'), 2)} ps  |  "
            f"total_width = {_fmt(best_avg.get('total_width_sum'), 3)} μm  |  "
            f"Pareto: {'YES' if best_avg.get('is_pareto') else 'NO'}"
        )

        return (far_prop, far_sub, avg_prop, avg_sub, n_pat, n_par,
                runtime, pareto_sz, far_desc, far_detail, avg_desc, avg_detail)

    @app.callback(
        Output("summary-pareto-graph", "figure"),
        Input("store-result", "data"),
    )
    def render_summary_pareto(store: dict) -> dict:
        return _build_pareto_figure(store, annotate_bests=True)


# ============================================================
# Pareto Analysis — axis toggle + highlight + summary markdown
# Pareto 分析 — 轴选择 + 高亮 + 解集 Markdown
# ============================================================
def register_pareto_callbacks(app: dash.Dash) -> None:
    """Wire callbacks for the Pareto Analysis tab.
    注册 Pareto 分析 Tab 的回调。

    Triggers:
      - pareto-axis-dropdown (value): change X/Y objective pair
      - pareto-highlight-radio (value): toggle Pareto front highlight
    """

    @app.callback(
        Output("pareto-graph", "figure"),
        Input("store-result", "data"),
        Input("pareto-axis-dropdown", "value"),
        Input("pareto-highlight-radio", "value"),
    )
    def render_pareto_graph(store: dict, axis_pair: str, highlight: str) -> dict:
        """Re-render Pareto scatter based on axis choice + highlight toggle.
        根据坐标轴选择和高亮开关重新渲染 Pareto 散点图。"""
        return _build_pareto_figure(
            store,
            axis_pair=axis_pair or "far/avg",
            highlight_pareto=(highlight != "off"),
            annotate_bests=True,
        )

    @app.callback(
        Output("pareto-summary-md", "children"),
        Input("store-result", "data"),
        Input("pareto-axis-dropdown", "value"),
    )
    def render_pareto_summary(store: dict, axis_pair: str) -> str:
        """Build markdown block summarising Pareto front statistics.
        构建 Markdown 块，展示 Pareto 解集统计信息。"""
        if not store:
            return "*(No data)*"

        pareto = store.get("pareto_front", [])
        all_recs = store.get("all_records", [])
        best_far = store.get("best_far_end", {})
        best_avg = store.get("best_avg", {})

        n_pareto = len(pareto)
        n_total = len(all_recs)
        best_far_far = best_far.get("far_prop")
        best_avg_avg = best_avg.get("avg_prop")

        # Min/max over Pareto front on X axis
        # Pareto 前沿在 X 轴上的最值
        ax = AXIS_KEYS.get(axis_pair or "far/avg", AXIS_KEYS["far/avg"])
        x_key = ax["x"]
        y_key = ax["y"]

        if pareto:
            px_vals = [float(p.get(x_key, 0.0)) for p in pareto]
            py_vals = [float(p.get(y_key, 0.0)) for p in pareto]
            x_min = min(px_vals) if px_vals else 0.0
            x_max = max(px_vals) if px_vals else 0.0
            y_min = min(py_vals) if py_vals else 0.0
            y_max = max(py_vals) if py_vals else 0.0
        else:
            x_min = x_max = y_min = y_max = 0.0

        md_lines: List[str] = []
        md_lines.append("### Pareto Front Summary")
        md_lines.append("")
        md_lines.append(f"- **Patterns on Pareto front**: `{n_pareto}` / `{n_total}`")
        md_lines.append(f"- **Active axis pair**: `{x_key}` vs `{y_key}`")
        md_lines.append(f"- **Best far_prop (global)**: `{_fmt(best_far_far, 3)}` ps  — `{best_far.get('description', '-')}`")
        md_lines.append(f"- **Best avg_prop (global)**: `{_fmt(best_avg_avg, 3)}` ps  — `{best_avg.get('description', '-')}`")
        md_lines.append("")
        md_lines.append("**Front extents (Pareto only)**")
        md_lines.append("")
        md_lines.append(f"| axis | min | max |")
        md_lines.append(f"| --- | --- | --- |")
        md_lines.append(f"| {x_key} (ps) | {_fmt(x_min, 3)} | {_fmt(x_max, 3)} |")
        md_lines.append(f"| {y_key} (ps) | {_fmt(y_min, 3)} | {_fmt(y_max, 3)} |")
        return "\n".join(md_lines)


# ============================================================
# Pattern Explorer — DataTable + delay profile on row select
# 模式浏览器 — DataTable + 行选择后画延迟曲线
# ============================================================
def register_pattern_explorer_callbacks(app: dash.Dash) -> None:
    """Wire callbacks for the Pattern Explorer tab.
    注册模式浏览器 Tab 的回调。

    Triggers:
      - store-result.data: populate DataTable
      - pattern-table.selected_rows: highlight selected pattern
      - pattern-detail-graph: render the selected pattern's delay profile
    """

    @app.callback(
        Output("pattern-table", "data"),
        Output("pattern-table", "columns"),
        Output("pattern-table", "filter_query"),
        Input("store-result", "data"),
    )
    def populate_pattern_table(store: dict) -> tuple:
        """Build DataTable rows + columns from all_records.
        从 all_records 构建 DataTable 行和列。"""
        if not store:
            return [], [], ""

        records = store.get("all_records", [])
        # Columns specification — 列定义
        columns = [
            {"name": "Description", "id": "description", "type": "text"},
            {"name": "Layers", "id": "pattern_layers_str", "type": "text"},
            {"name": "far_prop (ps)", "id": "far_prop", "type": "numeric",
             "format": {"specifier": ".3f"}},
            {"name": "avg_prop (ps)", "id": "avg_prop", "type": "numeric",
             "format": {"specifier": ".3f"}},
            {"name": "near_prop (ps)", "id": "near_prop", "type": "numeric",
             "format": {"specifier": ".3f"}},
            {"name": "Width Sum (μm)", "id": "total_width_sum", "type": "numeric",
             "format": {"specifier": ".3f"}},
            {"name": "Pareto", "id": "is_pareto_str", "type": "text"},
        ]

        rows: List[Dict[str, Any]] = []
        for r in records:
            layers = r.get("pattern_layers") or []
            rows.append({
                "description": r.get("description", ""),
                "pattern_layers_str": ", ".join(layers) if isinstance(layers, list) else str(layers),
                "far_prop": r.get("far_prop"),
                "avg_prop": r.get("avg_prop"),
                "near_prop": r.get("near_prop"),
                "total_width_sum": r.get("total_width_sum"),
                "is_pareto_str": "YES" if r.get("is_pareto") else "",
            })

        return rows, columns, ""

    @app.callback(
        Output("pattern-detail-graph", "figure"),
        Output("pattern-detail-info", "children"),
        Input("store-result", "data"),
        Input("pattern-table", "selected_rows"),
    )
    def render_selected_pattern_delay(store: dict, selected_rows: Optional[List[int]]) -> tuple:
        """Render delay profile for the selected pattern.
        绘制所选模式的延迟曲线。"""
        empty_fig = go.Figure(layout=PLOTLY_TEMPLATE["layout"])
        empty_fig.update_layout(
            title="Select a pattern row to view its delay profile",
            xaxis_title="Segment position (μm)",
            yaxis_title="Propagation delay 0.69·τ (ps)",
        )
        if not store:
            return empty_fig, "*(No data)*"

        records = store.get("all_records", [])
        if not records:
            return empty_fig, "*(No patterns)*"

        # Default: first row if none selected
        # 默认选中第一行
        idx = 0
        if selected_rows:
            idx = int(selected_rows[0])

        if idx < 0 or idx >= len(records):
            idx = 0

        rec = records[idx]
        fig = _build_single_delay_figure(store, rec)

        info_md = (
            f"### {_short(rec.get('description', '-'), 80)}\n"
            f"\n"
            f"- **far_prop**: `{_fmt(rec.get('far_prop'), 3)}` ps\n"
            f"- **avg_prop**: `{_fmt(rec.get('avg_prop'), 3)}` ps\n"
            f"- **near_prop**: `{_fmt(rec.get('near_prop'), 3)}` ps\n"
            f"- **total_width_sum**: `{_fmt(rec.get('total_width_sum'), 3)}` μm\n"
            f"- **metal_count**: `{rec.get('metal_count', '-')}`\n"
            f"- **Pareto**: `{'YES' if rec.get('is_pareto') else 'NO'}`\n"
        )
        return fig, info_md


# ============================================================
# Delay Profiles — multi-select Top-N + overlay + range slider
# 延迟曲线 — 多选 Top-N + 叠加 + 范围滑块
# ============================================================
def register_delay_profile_callbacks(app: dash.Dash, result: Any, config: Any) -> None:
    """Wire callbacks for the Delay Profiles tab.
    注册延迟曲线 Tab 的回调。

    Triggers:
      - store-result.data: populate multi-select dropdown options
      - delay-multi-dropdown (value): list of descriptions to overlay
      - delay-range-slider (value): segment position window [min, max]
    """

    @app.callback(
        Output("delay-multi-dropdown", "options"),
        Output("delay-multi-dropdown", "value"),
        Output("delay-range-slider", "min"),
        Output("delay-range-slider", "max"),
        Output("delay-range-slider", "value"),
        Output("delay-range-slider", "marks"),
        Input("store-result", "data"),
    )
    def setup_delay_controls(store: dict) -> tuple:
        """Configure the multi-select dropdown and range slider.
        配置多选下拉框和范围滑块。"""
        if not store:
            return [], [], 0, 1, [0, 1], {}

        records = store.get("all_records", [])
        # Sort by far_prop ascending, take top-N as default selection
        # 按 far_prop 升序排序，前 N 个为默认
        sorted_recs = sorted(records, key=lambda r: r.get("far_prop", 0.0))
        top_n = sorted_recs[: min(DEFAULT_TOP_N, len(sorted_recs))]

        options = [
            {"label": _short(r.get("description", "-"), 70),
             "value": r.get("description", "")}
            for r in records
        ]
        default_values = [r.get("description", "") for r in top_n]

        length_um = float(store.get("length_um", 0.0))
        if length_um <= 0:
            length_um = 1.0
        # Compute segment positions from first record (uniform ladder)
        # 使用第一条记录计算器件位置
        first = records[0] if records else {}
        positions = first.get("device_positions_um") or []
        if not positions or not isinstance(positions, list):
            # Fall back to uniform ladder based on segment_um
            seg = float(store.get("segment_um", length_um / 10.0))
            n = max(2, int(round(length_um / max(seg, 1e-6))))
            positions = [round(i * length_um / (n - 1), 4) for i in range(n)]
        pos_min = float(min(positions)) if positions else 0.0
        pos_max = float(max(positions)) if positions else length_um

        # Build marks — at most 6 evenly spaced
        n_marks = min(6, len(positions)) if positions else 0
        if n_marks >= 2 and positions:
            step = max(1, len(positions) // n_marks)
            marks = {
                round(float(positions[i]), 3): f"{float(positions[i]):.2f}"
                for i in range(0, len(positions), step)
            }
            # ensure endpoints present
            marks[round(pos_min, 3)] = f"{pos_min:.2f}"
            marks[round(pos_max, 3)] = f"{pos_max:.2f}"
        else:
            marks = {round(pos_min, 3): f"{pos_min:.2f}", round(pos_max, 3): f"{pos_max:.2f}"}

        return options, default_values, pos_min, pos_max, [pos_min, pos_max], marks

    @app.callback(
        Output("delay-profile-graph", "figure"),
        Input("store-result", "data"),
        Input("delay-multi-dropdown", "value"),
        Input("delay-range-slider", "value"),
    )
    def render_delay_profile_overlay(store: dict, selected: Optional[List[str]],
                                     window: Optional[List[float]]) -> dict:
        """Render overlaid delay curves for selected patterns within window.
        在指定位置窗口内叠加所选模式的延迟曲线。"""
        if not store:
            return go.Figure(layout=PLOTLY_TEMPLATE["layout"])

        records = store.get("all_records", [])
        if not records:
            return go.Figure(layout=PLOTLY_TEMPLATE["layout"])

        # Fall back to top-N if nothing selected
        # 未选择时回退为 Top-N
        if not selected:
            sorted_recs = sorted(records, key=lambda r: r.get("far_prop", 0.0))
            selected = [r.get("description", "") for r in sorted_recs[:DEFAULT_TOP_N]]

        # Map desc -> record
        rec_by_desc: Dict[str, Dict[str, Any]] = {
            r.get("description", ""): r for r in records
        }

        fig = go.Figure(layout=PLOTLY_TEMPLATE["layout"])
        palette = ["#2563eb", "#d97706", "#16a34a", "#dc2626", "#9333ea",
                   "#0891b2", "#db2777", "#65a30d", "#0d9488", "#a16207",
                   "#7c3aed", "#ea580c"]
        plotted = 0

        for idx, desc in enumerate(selected):
            rec = rec_by_desc.get(desc)
            if not rec:
                continue
            positions = rec.get("device_positions_um") or []
            prof = rec.get("per_device_prop") or []
            if not positions or not prof or len(positions) != len(prof):
                continue

            xs: List[float] = []
            ys: List[float] = []
            # Apply window filter — 应用窗口过滤
            w_min, w_max = (window or [min(positions), max(positions)])[:2]
            for p, v in zip(positions, prof):
                if w_min <= p <= w_max:
                    xs.append(float(p))
                    ys.append(float(v))

            color = palette[idx % len(palette)]
            label = _short(desc, 70)
            # Highlight bests — 标记最优
            best_far = store.get("best_far_end", {}).get("description", "")
            best_avg = store.get("best_avg", {}).get("description", "")
            if desc == best_far:
                label = "★ " + label
            elif desc == best_avg:
                label = "◆ " + label

            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines+markers",
                name=label,
                line={"color": color, "width": 2.0},
                marker={"color": color, "size": 5, "symbol": "circle"},
                hovertemplate="pos=%{x:.3f} μm<br>0.69·τ=%{y:.3f} ps<extra></extra>",
            ))

            # Device tap scatter — 器件抽头散点
            if xs:
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="markers",
                    marker={"color": color, "size": 8, "symbol": "diamond",
                            "line": {"color": "#fff", "width": 1}},
                    showlegend=False,
                    hoverinfo="skip",
                ))
            plotted += 1

        title = (f"Delay Profile Overlay (Top patterns, {plotted} plotted) "
                 f"in [{_fmt((window or [0, 0])[0], 3)}, "
                 f"{_fmt((window or [0, 0])[1], 3)}] μm")
        fig.update_layout(
            title=title,
            xaxis_title="Segment position along WL (μm)",
            yaxis_title="Propagation delay 0.69·τ (ps)",
            legend={"orientation": "v", "y": 1.0, "x": 1.02,
                    "xanchor": "left", "yanchor": "top"},
            hovermode="closest",
        )
        return fig


# ============================================================
# Export .rpt — preview + download
# 导出 .rpt — 预览 + 下载
# ============================================================
def register_export_callbacks(app: dash.Dash, result: Any, config: Any) -> None:
    """Wire callbacks for Export .rpt tab.
    注册 .rpt 导出 Tab 的回调。"""

    @app.callback(
        Output("rpt-preview", "children"),
        Input("store-result", "data"),
    )
    def update_rpt_preview(store: dict) -> str:
        from ..rpt_generator import RptGenerator
        return RptGenerator.generate_string(result, config)

    @app.callback(
        Output("download-rpt", "data"),
        Input("btn-download-rpt", "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )
    def download_rpt(n_clicks: Any, store: dict) -> dict:
        from ..rpt_generator import RptGenerator
        content = RptGenerator.generate_string(result, config)
        return dcc.send_string(content, filename="beol_optimization.rpt")

    @app.callback(
        Output("download-csv", "data"),
        Input("btn-download-csv", "n_clicks"),
        State("store-result", "data"),
        prevent_initial_call=True,
    )
    def download_csv(n_clicks: Any, store: dict) -> dict:
        if not store:
            return dcc.send_string("", filename="results.csv")
        records = store.get("all_records", [])
        output = io.StringIO()
        fieldnames = [
            "description", "far_prop", "avg_prop", "near_prop",
            "far_tau", "avg_tau", "near_tau",
            "total_width_sum", "metal_count",
            "is_pareto", "pareto_rank",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = {k: rec.get(k) for k in fieldnames}
            row["is_pareto"] = "TRUE" if rec.get("is_pareto") else ""
            writer.writerow(row)
        return dcc.send_string(output.getvalue(), filename="beol_results.csv")


# ============================================================
# Shared — Pareto Figure Builder
# 共享 — Pareto 图构建器
# ============================================================
def _build_pareto_figure(
    store: dict,
    axis_pair: str = "far/avg",
    highlight_pareto: bool = True,
    annotate_bests: bool = False,
    marker_size: int = 6,
) -> dict:
    """Build a Pareto scatter figure with selectable axes + optional highlight.
    构建可选择坐标轴 + 可选高亮的 Pareto 散点图。

    Args:
        store: dcc.Store payload.
        axis_pair: One of "far/avg", "far/near", "avg/near".
        highlight_pareto: If True, emphasise Pareto-front points.
        annotate_bests: If True, mark ★ best-far and ◆ best-avg.
        marker_size: Base marker size for non-Pareto points.
    """
    if not store:
        return go.Figure(layout=PLOTLY_TEMPLATE["layout"])

    all_recs = store.get("all_records", [])
    pareto = store.get("pareto_front", [])
    best_far_desc = store.get("best_far_end", {}).get("description", "")
    best_avg_desc = store.get("best_avg", {}).get("description", "")

    if not all_recs:
        return go.Figure(layout=PLOTLY_TEMPLATE["layout"])

    ax = AXIS_KEYS.get(axis_pair, AXIS_KEYS["far/avg"])
    x_key, y_key = ax["x"], ax["y"]

    all_x = [float(r.get(x_key, 0.0)) for r in all_recs]
    all_y = [float(r.get(y_key, 0.0)) for r in all_recs]
    all_labels = [_short(r.get("description", "-"), 45) for r in all_recs]
    all_is_pareto = [bool(r.get("is_pareto", False)) for r in all_recs]

    fig = go.Figure(layout=PLOTLY_TEMPLATE["layout"])

    # Non-Pareto points
    np_x = [all_x[i] for i in range(len(all_x)) if not all_is_pareto[i]]
    np_y = [all_y[i] for i in range(len(all_x)) if not all_is_pareto[i]]
    np_labels = [all_labels[i] for i in range(len(all_x)) if not all_is_pareto[i]]
    fig.add_trace(go.Scatter(
        x=np_x, y=np_y, mode="markers",
        name="All Patterns",
        marker={"color": "#94a3b8", "size": marker_size, "opacity": 0.5},
        text=np_labels, hoverinfo="text+x+y",
    ))

    # Pareto points (highlighted if requested)
    pp_x = [all_x[i] for i in range(len(all_x)) if all_is_pareto[i]]
    pp_y = [all_y[i] for i in range(len(all_x)) if all_is_pareto[i]]
    pp_labels = [all_labels[i] for i in range(len(all_x)) if all_is_pareto[i]]

    if highlight_pareto and pp_x:
        fig.add_trace(go.Scatter(
            x=pp_x, y=pp_y, mode="markers",
            name="Pareto Front",
            marker={"color": "#d97706", "size": marker_size + 3, "opacity": 0.95,
                    "line": {"color": "#f59e0b", "width": 0.8},
                    "symbol": "circle"},
            text=pp_labels, hoverinfo="text+x+y",
        ))
        # Connect Pareto points sorted by x
        pareto_sorted = sorted(pareto, key=lambda p: float(p.get(x_key, 0.0)))
        line_x = [float(p.get(x_key, 0.0)) for p in pareto_sorted]
        line_y = [float(p.get(y_key, 0.0)) for p in pareto_sorted]
        if len(line_x) >= 2:
            fig.add_trace(go.Scatter(
                x=line_x, y=line_y, mode="lines",
                name="Pareto Line",
                line={"color": "#dc2626", "width": 2, "dash": "dot"},
                hoverinfo="skip",
            ))
    elif pp_x:
        # Front hidden — fold them into grey cloud but keep marker slightly larger
        fig.add_trace(go.Scatter(
            x=pp_x, y=pp_y, mode="markers",
            name="All Patterns (Pareto hidden)",
            marker={"color": "#cbd5e1", "size": marker_size, "opacity": 0.4},
            text=pp_labels, hoverinfo="text+x+y",
            showlegend=False,
        ))

    # Annotate bests
    if annotate_bests:
        for rec in all_recs:
            desc = rec.get("description", "")
            fx = float(rec.get(x_key, 0.0))
            fy = float(rec.get(y_key, 0.0))
            if desc == best_far_desc:
                fig.add_trace(go.Scatter(
                    x=[fx], y=[fy], mode="markers+text",
                    name="★ Best Far-End",
                    marker={"color": "#16a34a", "size": 16, "symbol": "star",
                            "line": {"color": "#fff", "width": 1.5}},
                    text=["★ FAR"], textposition="top center",
                    textfont={"color": "#16a34a", "size": 11,
                              "family": "IBM Plex Sans, sans-serif"},
                    hoverinfo="skip",
                ))
            elif desc == best_avg_desc:
                fig.add_trace(go.Scatter(
                    x=[fx], y=[fy], mode="markers+text",
                    name="◆ Best Average",
                    marker={"color": "#f97316", "size": 13, "symbol": "diamond",
                            "line": {"color": "#fff", "width": 1.5}},
                    text=["◆ AVG"], textposition="bottom center",
                    textfont={"color": "#f97316", "size": 11,
                              "family": "IBM Plex Sans, sans-serif"},
                    hoverinfo="skip",
                ))

    n_pareto = sum(1 for r in all_recs if r.get("is_pareto"))
    fig.update_layout(
        title=f"Pareto Front: {x_key} vs {y_key}  "
              f"(N={len(all_recs)}, Pareto={n_pareto})",
        xaxis_title=f"{x_key} (ps)",
        yaxis_title=f"{y_key} (ps)",
        legend={"orientation": "h", "y": 1.02, "x": 0.5, "xanchor": "center"},
        hovermode="closest",
    )
    return fig


# ============================================================
# Shared — Single Pattern Delay Profile Builder
# 共享 — 单模式延迟曲线构建器
# ============================================================
def _build_single_delay_figure(store: dict, rec: Dict[str, Any]) -> go.Figure:
    """Build a delay-profile figure for a single evaluation record.
    为单条评估记录构建延迟曲线图。

    Shows per_segment_ps vs segment_positions_um, with device taps
    highlighted as diamond markers.
    """
    fig = go.Figure(layout=PLOTLY_TEMPLATE["layout"])

    positions = rec.get("device_positions_um") or []
    prof = rec.get("per_device_prop") or []

    # If positions absent, synthesise a uniform ladder from length_um/segment_um
    if not positions and prof:
        length_um = float(store.get("length_um", 0.0))
        seg_um = float(store.get("segment_um", length_um / max(len(prof) - 1, 1)))
        n = len(prof)
        positions = [round(i * length_um / max(n - 1, 1), 4) for i in range(n)]

    if not positions or not prof or len(positions) != len(prof):
        fig.update_layout(
            title=f"Delay profile unavailable — {_short(rec.get('description','-'),40)}",
            xaxis_title="Segment position (μm)",
            yaxis_title="Propagation delay 0.69·τ (ps)",
        )
        return fig

    xs = [float(p) for p in positions]
    ys = [float(v) for v in prof]

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        name="per_device_prop",
        line={"color": "#2563eb", "width": 2.0},
        marker={"color": "#2563eb", "size": 5, "symbol": "circle"},
        hovertemplate="pos=%{x:.3f} μm<br>0.69·τ=%{y:.3f} ps<extra></extra>",
    ))

    # Device tap markers
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers",
        name="Device tap",
        marker={"color": "#dc2626", "size": 8, "symbol": "diamond",
                "line": {"color": "#fff", "width": 1}},
        hovertemplate="tap pos=%{x:.3f} μm<extra></extra>",
    ))

    # Far-end vertical reference
    length_um = float(store.get("length_um", xs[-1] if xs else 0.0))
    fig.add_vline(x=length_um, line={"color": "#94a3b8", "width": 1, "dash": "dash"},
                  annotation_text="WL far-end", annotation_position="top right",
                  annotation_font={"size": 9, "color": "#94a3b8"})

    fig.update_layout(
        title=f"Delay Profile — {_short(rec.get('description', '-'), 60)}",
        xaxis_title="Segment position along WL (μm)",
        yaxis_title="Propagation delay 0.69·τ (ps)",
        hovermode="closest",
        showlegend=True,
        legend={"orientation": "h", "y": 1.06, "x": 0.5, "xanchor": "center"},
    )
    return fig