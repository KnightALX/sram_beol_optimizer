"""Dash application entry point for SRAM BEOL Interconnect Optimizer Dashboard.
Dash 应用程序入口 — SRAM BEOL 互连线优化器交互式仪表板。

Provides EDA-industrial themed 5-tab interactive dashboard displaying
optimization results: Summary, Pareto Analysis, Pattern Explorer, Delay Profiles,
and .rpt Export.
提供 EDA 工业风格的 5 个 Tab 交互式仪表板，展示优化结果：
摘要、Pareto 分析、模式浏览器、延迟曲线、.rpt 导出。

Architecture follows sram_layout_review patterns:
- Inline EDA dark CSS theme (Cadence Virtuoso / Synopsys DC color palette)
- Dash app with custom index_string embedding full CSS
- Lazy result injection via launch() method
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from dash import Dash

logger = logging.getLogger(__name__)

# ============================================================
# EDA Industrial Light Theme — CSS Variables
# Clean white-background professional EDA tool aesthetic.
# Inspired by Cadence Virtuoso / Synopsys PrimeTime light panels.
# EDA 工业亮色主题 — CSS 变量
# 干净的白底专业 EDA 工具美学
# ============================================================
EDA_LIGHT_CSS: str = """
/* EDA Light Theme — SRAM BEOL Optimizer Dashboard */
:root {
    --bg-primary: #f8f9fb;
    --bg-secondary: #ffffff;
    --bg-tertiary: #f1f4f8;
    --bg-hover: #e8ecf2;
    --bg-input: #ffffff;

    --border-primary: #d0d5dd;
    --border-secondary: #e4e7ec;
    --border-active: #2563eb;

    --text-primary: #1e293b;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --text-accent: #2563eb;

    --status-pass: #16a34a;
    --status-fail: #dc2626;
    --status-warning: #d97706;
    --status-info: #2563eb;

    --accent-primary: #2563eb;
    --accent-secondary: #0891b2;

    --button-primary: #2563eb;
    --button-hover: #1d4ed8;
    --button-active: #1e40af;

    --graph-bg: #f8f9fb;

    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
    --shadow-md: 0 2px 4px rgba(0, 0, 0, 0.06);
    --shadow-lg: 0 4px 12px rgba(0, 0, 0, 0.08);

    --font-mono: "JetBrains Mono", "Fira Code", "SF Mono", "Consolas", monospace;
    --font-body: "IBM Plex Sans", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: var(--font-body);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 13px;
    overflow: hidden;
    height: 100vh;
}

/* Header Bar — 顶部状态栏 */
.header-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 20px; height: 40px; background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-primary); flex-shrink: 0;
    box-shadow: var(--shadow-sm);
}
.header-logo {
    font-family: var(--font-mono); font-size: 13px; font-weight: 700;
    color: var(--text-accent); letter-spacing: 1.5px;
}
.header-subtitle { font-size: 10px; color: var(--text-muted); margin-left: 12px; }
.header-right { display: flex; align-items: center; gap: 16px; }
.header-badge {
    font-size: 10px; color: var(--text-secondary);
    padding: 2px 8px; background: var(--bg-tertiary);
    border: 1px solid var(--border-secondary); border-radius: 3px;
}
.header-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.header-dot.ok { background: var(--status-pass); }

/* Tab Bar — Tab 导航栏 */
.tab-bar {
    display: flex; gap: 0; background: var(--bg-secondary);
    padding: 0 20px; border-bottom: 1px solid var(--border-secondary);
}
.dash-tab {
    padding: 7px 18px !important; font-size: 12px !important;
    font-family: var(--font-body) !important;
}

/* Metric Cards — 指标卡片 */
.metrics-row {
    display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;
}
.metric-card {
    flex: 1; min-width: 150px; background: var(--bg-secondary);
    border: 1px solid var(--border-secondary); border-radius: 6px;
    padding: 10px 14px; box-shadow: var(--shadow-sm);
}
.metric-card.highlight {
    border-color: var(--accent-primary);
    box-shadow: 0 0 0 1px var(--accent-primary);
}
.metric-label {
    font-size: 9px; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.8px;
    font-weight: 600;
}
.metric-value {
    font-size: 20px; font-weight: 700;
    font-family: var(--font-mono); margin: 3px 0; line-height: 1.2;
}
.metric-sub { font-size: 10px; color: var(--text-secondary); }

/* Best Pattern Box — 最佳模式高亮框 */
.best-box {
    background: #f0fdf4; border: 1px solid #bbf7d0;
    border-left: 3px solid var(--status-pass);
    border-radius: 4px; padding: 10px 14px; margin-bottom: 8px;
}
.best-box .best-title {
    font-size: 10px; text-transform: uppercase; color: var(--status-pass);
    letter-spacing: 0.5px; margin-bottom: 3px; font-weight: 600;
}
.best-box .best-desc {
    font-family: var(--font-mono); font-size: 12px; color: var(--text-primary);
}

/* Section Headers — 区块标题 */
.section-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 14px; background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border-secondary);
}
.section-title {
    font-size: 11px; font-weight: 600; color: var(--text-secondary);
    font-family: var(--font-mono); letter-spacing: 0.5px;
}

/* DataTable Overrides — 数据表格样式 */
.dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner table {
    font-family: var(--font-mono) !important; font-size: 10px !important;
}
.dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
    background: var(--bg-tertiary) !important; color: var(--text-secondary) !important;
    font-weight: 600 !important; border-bottom: 2px solid var(--border-primary) !important;
}

/* .rpt Preview — 报告预览 */
.rpt-preview {
    background: #1e293b; color: #e2e8f0;
    padding: 14px; border: 1px solid var(--border-primary);
    font-family: var(--font-mono); font-size: 10px; line-height: 1.6;
    white-space: pre-wrap; overflow: auto;
    border-radius: 4px;
}

/* Buttons — 按钮 */
.btn {
    background: var(--button-primary); color: #fff; border: none;
    padding: 6px 14px; border-radius: 4px; font-size: 11px;
    cursor: pointer; font-family: var(--font-body); font-weight: 500;
    transition: background 0.15s;
}
.btn:hover { background: var(--button-hover); }
.btn-ghost {
    background: transparent; color: var(--text-secondary);
    border: 1px solid var(--border-primary); padding: 5px 12px;
    border-radius: 4px; font-size: 11px; cursor: pointer;
    transition: all 0.15s;
}
.btn-ghost:hover { border-color: var(--text-accent); color: var(--text-accent); }

/* Chart container — 图表容器 */
.chart-box {
    background: var(--graph-bg); border: 1px solid var(--border-secondary);
    border-radius: 6px;
}

/* Scrollbar — 滚动条 */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border-primary); border-radius: 3px; }

/* Tab content area — fill remaining height */
.dash-tab-content {
    flex: 1; overflow: auto; min-height: 0; background: var(--bg-primary);
}

/* Fixed full-height layout — ensure the entire DOM chain propagates height */
#_dash-app-content {
    height: 100vh; display: flex; flex-direction: column;
}
#_dash-app-content > div {
    flex: 1; display: flex; flex-direction: column; min-height: 0;
}

/* Dash dcc.Tabs internal containers — must all be flex for height propagation */
.dash-tabs,
.tab-container,
.tab-content {
    flex: 1; display: flex; flex-direction: column; min-height: 0;
}

.app-container > .js-plotly-plot { width: 100% !important; }

/* DataTable row hover */
.dash-spreadsheet tr:hover td { background: var(--bg-hover) !important; }
"""


class DashboardApp:
    """SRAM BEOL Interconnect Optimizer interactive dashboard.

    SRAM BEOL 互连线优化器交互式仪表板。

    Usage:
        dashboard = DashboardApp()
        dashboard.launch(result, config)
    """

    def __init__(self, port: int = 8050) -> None:
        """Initialize Dash application with EDA industrial theme.

        Args:
            port: HTTP port for the dashboard server. Default 8050.
        """
        self.port = port
        self._result: Optional[Any] = None   # OptimizationResult (stored after launch)
        self._config: Optional[Any] = None   # WireConfig (stored after launch)

        # Create Dash app — 创建 Dash 应用
        self.app = Dash(
            __name__,
            suppress_callback_exceptions=True,
        )
        self.app.title = "SRAM BEOL Optimizer"

        # Inject EDA theme into index HTML — 将 EDA 主题注入 index HTML
        self.app.index_string = self._build_index_string()

    def _build_index_string(self) -> str:
        """Build custom HTML index string with embedded EDA dark theme CSS.

        构建包含 EDA 暗色主题 CSS 的自定义 HTML 索引字符串。
        """
        template = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
""" + EDA_LIGHT_CSS + """
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""
        return template

    def launch(self, result: Any, config: Any) -> None:
        """Store result data, build layout, register callbacks, and start server.

        存储优化结果数据，构建布局，注册回调，启动 Web 服务。

        Args:
            result: OptimizationResult from WLInterconnectOptimizer.run()
            config: WireConfig used for this optimization run
        """
        # Lazy imports to avoid circular dependencies
        # 延迟导入，避免循环依赖
        from ..config import WireConfig
        from ..optimizer import OptimizationResult

        self._result = result
        self._config = config

        # Serialize result data into dcc.Store payload
        # 将优化结果序列化到 dcc.Store 数据载荷
        store_data = self._serialize_result(result, config)

        # Build layout — 构建布局
        from .layout import create_layout
        self.app.layout = create_layout(config, store_data)

        # Register callbacks — 注册回调
        from .callbacks import register_callbacks
        register_callbacks(self.app, result, config)

        logger.info(
            "Dashboard ready: %d patterns, %d Pareto-optimal. "
            "Open http://localhost:%d in your browser.",
            len(result.all_records), len(result.pareto_front), self.port,
        )

        # Start Dash server (blocking — runs until Ctrl+C)
        # 启动 Dash 服务（阻塞 — 直到 Ctrl+C 终止）
        self.app.run(debug=False, port=self.port, host="0.0.0.0")

    @staticmethod
    def _serialize_result(result: Any, config: Any) -> dict:
        """Serialize OptimizationResult and WireConfig into JSON-serializable dict
        for dcc.Store storage.

        将 OptimizationResult 和 WireConfig 序列化为 JSON 可存储 dict。

        Returns dict with keys:
            all_records, pareto_front, best_far_end, best_avg, summary,
            length_um, segment_um, via_pitch_um, corner, metals, max_width_um,
            output_dir
        """
        # Ensure per-device lists are JSON-serializable (convert numpy to list if needed)
        # 确保逐器件列表可 JSON 序列化
        import numpy as np

        def _make_serializable(obj: Any) -> Any:
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, dict):
                return {k: _make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_make_serializable(v) for v in obj]
            return obj

        all_recs = []
        for rec in result.all_records:
            r = dict(rec)
            # Keep per_device arrays compact (convert to list)
            # 保留逐器件数组（转为 list）
            for k in ("per_device_tau", "per_device_prop", "device_positions_um"):
                if k in r and hasattr(r[k], "tolist"):
                    r[k] = r[k].tolist() if hasattr(r[k], "tolist") else list(r[k])
            all_recs.append(_make_serializable(r))

        pareto = [_make_serializable(dict(p)) for p in result.pareto_front]
        best_far = _make_serializable(dict(result.best_far_end))
        best_avg = _make_serializable(dict(result.best_avg))
        summary = _make_serializable(dict(result.summary))

        return {
            "all_records": all_recs,
            "pareto_front": pareto,
            "best_far_end": best_far,
            "best_avg": best_avg,
            "summary": summary,
            "length_um": float(config.length_um),
            "segment_um": float(config.segment_um),
            "via_pitch_um": float(config.via_pitch_um),
            "corner": str(config.corner),
            "metals": list(config.metals),
            "max_width_um": float(config.max_width_um),
            "output_dir": str(config.output_dir),
            "fixed_signals": list(getattr(config, "fixed_signals", [])),
        }


# ============================================================
# Backward-compatible public aliases
# 向后兼容的公开别名
# ============================================================
# SRAMDashboardApp is the canonical name referenced by the app docstring and
# smoke-test entry; DashboardApp is kept for existing imports.
# SRAMDashboardApp 为 docstring 与冒烟测试约定的规范名；
# DashboardApp 保留以兼容现有导入。
SRAMDashboardApp = DashboardApp

__all__ = ["DashboardApp", "SRAMDashboardApp", "EDA_LIGHT_CSS"]
