"""sram_beol - SRAM BEOL Interconnect Optimizer

Clean public API per design document Sections 2, 3, 9 and task requirements.

Primary usage (exactly as specified):
    from sram_beol import WLInterconnectOptimizer
    opt = WLInterconnectOptimizer(config_path="...")
    result = opt.run()
    opt.generate_report(result)
    opt.plot(result)

Also: WireConfig, load helpers, configure_logging, full exception hierarchy.
"""

from __future__ import annotations

from .config import (
    WireConfig,
    configure_logging,
    load_wire_config,
)
from .exceptions import (
    BEOLBaseError,
    BEOLConfigError,
    BEOLDataError,
    BEOLPatternError,
    BEOLComputationError,
    BEOLRuntimeError,
)
from .optimizer import (
    OptimizationResult,
    WLInterconnectOptimizer,
)

# Lower-level building blocks (already implemented) also available for power users
from .evaluator import ElmoreLadderEvaluator
from .pattern import WirePattern

__all__ = [
    # Task/design primary public API
    "WLInterconnectOptimizer",
    "WireConfig",
    "OptimizationResult",
    "load_wire_config",
    "configure_logging",
    # Exceptions (design Sec 9)
    "BEOLBaseError",
    "BEOLConfigError",
    "BEOLDataError",
    "BEOLPatternError",
    "BEOLComputationError",
    "BEOLRuntimeError",
    # Additional implemented pieces
    "ElmoreLadderEvaluator",
    "WirePattern",
]

__version__ = "0.1.0"
