"""SRAM BEOL Interconnect Optimizer — Interactive Dashboard.
SRAM BEOL 互连线优化器 — 交互式仪表板。

Public API:
    from sram_beol.dashboard import DashboardApp, SRAMDashboardApp
    DashboardApp(port=8050).launch(result, config)
"""

from __future__ import annotations

from .app import DashboardApp, SRAMDashboardApp

__all__ = ["DashboardApp", "SRAMDashboardApp"]
