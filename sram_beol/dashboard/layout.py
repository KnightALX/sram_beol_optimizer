"""5-tab Dash layout for SRAM BEOL Interconnect Optimizer Dashboard.
5-Tab Dash 布局 — SRAM BEOL 互连线优化器仪表板。

Tabs:
  - Summary           — metric cards + best patterns + thumbnail Pareto
  - Pareto Analysis   — interactive scatter + axis toggle + highlight + summary md
  - Pattern Explorer  — sortable / filterable DataTable + per-row delay profile
  - Delay Profiles    — multi-select Top-N + overlay + segment position range slider
  - Export .rpt       — text preview + download .rpt / .csv
"""

from __future__ import annotations

from typing import Any

from dash import dash_table, dcc, html

__all__ = ["create_layout"]


def _fmt(v: Any, prec: int = 4) -> str:
    if isinstance(v, float):
        if abs(v) > 1e5 or (0 < abs(v) < 1e-3):
            return f"{v:.6g}"
        return f"{v:.{prec}f}"
    return str(v)


# ------------------------------------------------------------------
# Header Bar — 顶部状态栏
# ------------------------------------------------------------------
def _create_header(config: Any) -> html.Div:
    metals_str = " ".join(config.metals)
    corner = str(config.corner)
    length = _fmt(config.length_um, 2)

    return html.Div([
        html.Div([
            html.Div("SRAM BEOL OPTIMIZER", className="header-logo"),
            html.Div("WL Interconnect Pareto Analysis", className="header-subtitle"),
        ], style={"display": "flex", "align-items": "center"}),
        html.Div([
            html.Span(f"Corner: {corner}", className="header-badge"),
            html.Span(f"WL Length: {length} μm", className="header-badge"),
            html.Span(f"Metals: {metals_str}", className="header-badge"),
            html.Span(className="header-dot ok"),
            html.Span("Optimization Complete",
                      style={"font-size": "11px", "color": "var(--text-muted)"}),
        ], className="header-right"),
    ], className="header-bar")


# ==================================================================
# TAB 1: SUMMARY
# 摘要 — 指标卡片 + 最佳模式 + 缩略 Pareto
# ==================================================================
def _create_summary_tab() -> html.Div:
    return html.Div([
        # --- Metric cards ---
        html.Div([
            html.Div([
                html.Div("Best Far-End Delay (0.69τ)", className="metric-label"),
                html.Div(id="metric-best-far", className="metric-value",
                         style={"color": "var(--status-pass)"}),
                html.Div(id="metric-best-far-sub", className="metric-sub"),
            ], className="metric-card highlight"),
            html.Div([
                html.Div("Best Avg Delay (0.69τ)", className="metric-label"),
                html.Div(id="metric-best-avg", className="metric-value",
                         style={"color": "var(--status-pass)"}),
                html.Div(id="metric-best-avg-sub", className="metric-sub"),
            ], className="metric-card highlight"),
            html.Div([
                html.Div("Patterns Evaluated", className="metric-label"),
                html.Div(id="metric-n-patterns", className="metric-value",
                         style={"color": "var(--accent-primary)"}),
                html.Div(id="metric-n-pareto", className="metric-sub"),
            ], className="metric-card"),
            html.Div([
                html.Div("Optimization Time", className="metric-label"),
                html.Div(id="metric-runtime", className="metric-value"),
                html.Div("Elmore eval @ configured WL", className="metric-sub"),
            ], className="metric-card"),
            html.Div([
                html.Div("Pareto Front Size", className="metric-label"),
                html.Div(id="metric-pareto-size", className="metric-value",
                         style={"color": "var(--status-warning)"}),
                html.Div("Non-dominated (far_prop vs avg_prop)", className="metric-sub"),
            ], className="metric-card"),
        ], className="metrics-row"),

        # --- Key Conclusions + Thumbnail Pareto ---
        html.Div([
            html.Div([
                html.Div([
                    html.Span("KEY CONCLUSIONS", className="section-title"),
                ], className="section-header", style={"borderRadius": "4px 4px 0 0"}),
                html.Div([
                    html.Div([
                        html.Div("★ Best Far-End Delay Pattern", className="best-title"),
                        html.Div(id="summary-best-far-desc", className="best-desc"),
                        html.Div(id="summary-best-far-detail", style={
                            "color": "var(--text-secondary)", "font-size": "10px",
                            "margin-top": "4px",
                        }),
                    ], className="best-box"),
                    html.Div([
                        html.Div("◆ Best Average Delay Pattern", className="best-title"),
                        html.Div(id="summary-best-avg-desc", className="best-desc"),
                        html.Div(id="summary-best-avg-detail", style={
                            "color": "var(--text-secondary)", "font-size": "10px",
                            "margin-top": "4px",
                        }),
                    ], className="best-box"),
                    html.P(
                        "Direction rules enforce same-group stacking "
                        "(odd: M1/M3/M5, even: M2/M4/M6). "
                        "Wider wires + multi-color parallel (ABA+BAB) reduce R at the "
                        "cost of extra C and area.",
                        style={"color": "var(--text-muted)",
                               "font-size": "10px", "margin-top": "8px"},
                    ),
                ], style={
                    "background": "var(--bg-secondary)",
                    "border": "1px solid var(--border-secondary)",
                    "border-top": "none", "padding": "12px",
                    "border-radius": "0 0 4px 4px",
                }),
            ], style={"flex": "1", "minWidth": "0"}),

            html.Div([
                dcc.Graph(
                    id="summary-pareto-graph",
                    config={"displayModeBar": False},
                    responsive=True,
                    style={"height": "100%"},
                ),
            ], className="chart-box", style={"width": "440px", "flexShrink": "0"}),
        ], style={"display": "flex", "gap": "12px", "flex": "1", "minHeight": "0"}),
    ], style={"display": "flex", "flexDirection": "column", "height": "100%"})


# ==================================================================
# TAB 2: PARETO ANALYSIS
# Pareto 分析 — 坐标轴选择 + 高亮 + 解集 Markdown
# ==================================================================
def _create_pareto_tab() -> html.Div:
    """Interactive Pareto scatter with axis + highlight controls.
    可交互 Pareto 散点图（坐标轴 + 高亮控制）。"""
    return html.Div([
        # --- Controls row ---
        html.Div([
            html.Div([
                html.Div("Axis Pair", style={
                    "fontSize": "10px", "textTransform": "uppercase",
                    "color": "var(--text-secondary)", "letterSpacing": "0.5px",
                    "fontWeight": "600", "marginBottom": "4px",
                }),
                dcc.Dropdown(
                    id="pareto-axis-dropdown",
                    options=[
                        {"label": "far_prop vs avg_prop", "value": "far/avg"},
                        {"label": "far_prop vs near_prop", "value": "far/near"},
                        {"label": "avg_prop vs near_prop", "value": "avg/near"},
                    ],
                    value="far/avg",
                    clearable=False,
                    style={"minWidth": "220px", "fontSize": "12px"},
                ),
            ], style={"display": "flex", "flexDirection": "column", "gap": "2px"}),

            html.Div([
                html.Div("Pareto Front Highlight", style={
                    "fontSize": "10px", "textTransform": "uppercase",
                    "color": "var(--text-secondary)", "letterSpacing": "0.5px",
                    "fontWeight": "600", "marginBottom": "4px",
                }),
                dcc.RadioItems(
                    id="pareto-highlight-radio",
                    options=[
                        {"label": "  On", "value": "on"},
                        {"label": "  Off", "value": "off"},
                    ],
                    value="on",
                    inline=True,
                    inputStyle={"marginRight": "4px"},
                    labelStyle={"fontSize": "12px", "marginRight": "12px"},
                ),
            ], style={"display": "flex", "flexDirection": "column", "gap": "2px"}),
        ], style={
            "display": "flex", "gap": "24px", "alignItems": "flex-end",
            "padding": "10px 14px",
            "background": "var(--bg-secondary)",
            "border": "1px solid var(--border-secondary)",
            "borderRadius": "4px", "marginBottom": "10px",
        }),

        # --- Pareto graph + summary markdown ---
        html.Div([
            html.Div([
                dcc.Graph(
                    id="pareto-graph",
                    config={"displayModeBar": True},
                    responsive=True,
                    style={"height": "100%"},
                ),
            ], className="chart-box", style={"flex": "1", "minWidth": "0"}),

            html.Div([
                html.Div([
                    html.Span("PARETO SUMMARY", className="section-title"),
                ], className="section-header", style={"borderRadius": "4px 4px 0 0"}),
                dcc.Markdown(
                    id="pareto-summary-md",
                    children="*(Loading...)*",
                    style={
                        "background": "var(--bg-secondary)",
                        "border": "1px solid var(--border-secondary)",
                        "border-top": "none",
                        "padding": "12px",
                        "fontSize": "12px",
                        "borderRadius": "0 0 4px 4px",
                        "overflow": "auto",
                    },
                ),
            ], style={"width": "340px", "flexShrink": "0",
                      "display": "flex", "flexDirection": "column"}),
        ], style={
            "display": "flex", "gap": "12px", "flex": "1", "minHeight": "0",
        }),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "100%", "padding": "10px",
    })


# ==================================================================
# TAB 3: PATTERN EXPLORER
# 模式浏览器 — DataTable + 行选择后画延迟曲线
# ==================================================================
def _create_pattern_explorer_tab() -> html.Div:
    """Sortable / filterable DataTable of all evaluation records.
    可排序 / 筛选的全量评估记录表 + 行选择后单条延迟曲线。"""
    return html.Div([
        # --- DataTable ---
        html.Div([
            html.Div([
                html.Span("PATTERN EXPLORER — All Evaluated Patterns",
                          className="section-title"),
            ], className="section-header", style={"borderRadius": "4px 4px 0 0"}),
            dash_table.DataTable(
                id="pattern-table",
                columns=[],
                data=[],
                sort_action="native",
                filter_action="native",
                row_selectable="single",
                selected_rows=[0],
                page_size=15,
                page_action="native",
                style_cell={
                    "fontFamily": "var(--font-mono)",
                    "fontSize": "11px",
                    "textAlign": "left",
                    "padding": "4px 6px",
                    "minWidth": "80px",
                    "maxWidth": "320px",
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                    "whiteSpace": "nowrap",
                },
                style_header={
                    "backgroundColor": "var(--bg-tertiary)",
                    "color": "var(--text-secondary)",
                    "fontWeight": "600",
                    "borderBottom": "2px solid var(--border-primary)",
                    "fontFamily": "var(--font-mono)",
                    "fontSize": "10px",
                    "textTransform": "uppercase",
                },
                style_data={
                    "backgroundColor": "var(--bg-secondary)",
                    "color": "var(--text-primary)",
                },
                style_data_conditional=[
                    {
                        "if": {"filter_query": '{is_pareto_str} = "YES"'},
                        "backgroundColor": "#fef3c7",
                        "fontWeight": "600",
                    },
                    {
                        "if": {"column_id": "description"},
                        "fontFamily": "var(--font-mono)",
                        "minWidth": "260px",
                    },
                ],
                style_table={
                    "overflowX": "auto",
                    "border": "1px solid var(--border-secondary)",
                    "borderRadius": "0 0 4px 4px",
                },
                tooltip_duration=500,
            ),
        ], style={"height": "55%", "display": "flex", "flexDirection": "column"}),

        # --- Per-row delay profile + meta info ---
        html.Div([
            html.Div([
                dcc.Graph(
                    id="pattern-detail-graph",
                    config={"displayModeBar": False},
                    responsive=True,
                    style={"height": "100%"},
                ),
            ], className="chart-box", style={"flex": "1", "minWidth": "0"}),

            html.Div([
                html.Div([
                    html.Span("SELECTED PATTERN", className="section-title"),
                ], className="section-header", style={"borderRadius": "4px 4px 0 0"}),
                dcc.Markdown(
                    id="pattern-detail-info",
                    children="*(Select a row to see its delay profile and metrics)*",
                    style={
                        "background": "var(--bg-secondary)",
                        "border": "1px solid var(--border-secondary)",
                        "border-top": "none",
                        "padding": "12px",
                        "fontSize": "12px",
                        "borderRadius": "0 0 4px 4px",
                        "overflow": "auto",
                    },
                ),
            ], style={"width": "320px", "flexShrink": "0"}),
        ], style={
            "display": "flex", "gap": "12px",
            "height": "45%", "marginTop": "10px", "minHeight": "0",
        }),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "100%", "padding": "10px",
    })


# ==================================================================
# TAB 4: DELAY PROFILES
# 延迟曲线 — 多选 + 叠加 + 范围滑块
# ==================================================================
def _create_delay_profiles_tab() -> html.Div:
    """Top-N delay-curve overlay with multi-select and position-range filter.
    Top-N 延迟曲线叠加图 + 多选 + 位置范围过滤。"""
    return html.Div([
        # --- Controls row ---
        html.Div([
            html.Div([
                html.Div("Top-N Patterns (multi-select)", style={
                    "fontSize": "10px", "textTransform": "uppercase",
                    "color": "var(--text-secondary)", "letterSpacing": "0.5px",
                    "fontWeight": "600", "marginBottom": "4px",
                }),
                dcc.Dropdown(
                    id="delay-multi-dropdown",
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Select patterns to overlay…",
                    style={"minWidth": "320px", "fontSize": "12px"},
                ),
            ], style={"display": "flex", "flexDirection": "column", "gap": "2px",
                      "flex": "1"}),

            html.Div([
                html.Div("Segment Position Range (μm)", style={
                    "fontSize": "10px", "textTransform": "uppercase",
                    "color": "var(--text-secondary)", "letterSpacing": "0.5px",
                    "fontWeight": "600", "marginBottom": "4px",
                }),
                dcc.RangeSlider(
                    id="delay-range-slider",
                    min=0, max=1, value=[0, 1],
                    marks={},
                    step=None,
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
            ], style={"display": "flex", "flexDirection": "column", "gap": "2px",
                      "flex": "1.5"}),
        ], style={
            "display": "flex", "gap": "20px", "alignItems": "flex-end",
            "padding": "10px 14px",
            "background": "var(--bg-secondary)",
            "border": "1px solid var(--border-secondary)",
            "borderRadius": "4px", "marginBottom": "10px",
        }),

        # --- Overlay graph ---
        html.Div([
            dcc.Graph(
                id="delay-profile-graph",
                config={"displayModeBar": True},
                responsive=True,
                style={"height": "100%"},
            ),
        ], className="chart-box", style={"flex": "1", "minHeight": "0"}),
    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "100%", "padding": "10px",
    })


# ==================================================================
# TAB 5: EXPORT .RPT
# 导出 .rpt — 文本预览 + 下载
# ==================================================================
def _create_export_tab() -> html.Div:
    return html.Div([
        html.Div([
            # --- LEFT: .rpt preview ---
            html.Div([
                html.Div([
                    html.Span(".RPT PREVIEW — Synopsys/Cadence Style",
                              className="section-title"),
                ], className="section-header", style={"borderRadius": "4px 4px 0 0"}),
                html.Pre(
                    id="rpt-preview",
                    className="rpt-preview",
                    children="Loading .rpt content...",
                ),
            ], style={"flex": "1", "display": "flex", "flexDirection": "column",
                      "minHeight": "0", "overflow": "auto"}),

            # --- RIGHT: Export actions ---
            html.Div([
                html.Div([
                    html.Div("EXPORT", style={
                        "fontSize": "10px", "textTransform": "uppercase",
                        "color": "var(--text-secondary)", "letterSpacing": "0.5px",
                        "fontWeight": "600", "marginBottom": "8px",
                    }),
                    html.Button("Download .rpt", id="btn-download-rpt",
                                className="btn",
                                style={"width": "100%", "marginBottom": "6px"}),
                    html.Button("Download CSV", id="btn-download-csv",
                                className="btn-ghost",
                                style={"width": "100%"}),
                    html.Div(
                        "Plain-text EDA report, compatible with Synopsys PT / "
                        "Cadence Innovus log viewers.",
                        style={"fontSize": "9px", "color": "var(--text-muted)",
                               "marginTop": "8px"},
                    ),
                ], style={
                    "background": "var(--bg-secondary)",
                    "border": "1px solid var(--border-secondary)",
                    "borderRadius": "4px", "padding": "12px",
                }),
                dcc.Download(id="download-rpt"),
                dcc.Download(id="download-csv"),
            ], style={"width": "190px", "display": "flex",
                      "flexDirection": "column", "gap": "8px"}),
        ], style={"display": "flex", "gap": "14px", "height": "100%"}),
    ], style={"height": "100%"})


# ==================================================================
# MAIN LAYOUT ENTRY
# 主布局入口
# ==================================================================
def create_layout(config: Any, _store_data: dict) -> html.Div:
    """Build the 5-tab dashboard layout.
    构建 5-Tab 仪表板布局。"""
    return html.Div([
        dcc.Store(id="store-result", data=_store_data),
        _create_header(config),

        dcc.Tabs(
            id="tabs",
            value="tab-summary",
            className="tab-bar",
            children=[
                dcc.Tab(label="Summary", value="tab-summary",
                        children=_create_summary_tab()),
                dcc.Tab(label="Pareto Analysis", value="tab-pareto",
                        children=_create_pareto_tab()),
                dcc.Tab(label="Pattern Explorer", value="tab-explorer",
                        children=_create_pattern_explorer_tab()),
                dcc.Tab(label="Delay Profiles", value="tab-delay",
                        children=_create_delay_profiles_tab()),
                dcc.Tab(label="Export .rpt", value="tab-export",
                        children=_create_export_tab()),
            ],
        ),
    ])