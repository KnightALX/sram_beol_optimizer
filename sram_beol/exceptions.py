"""Custom exceptions for SRAM BEOL Interconnect Optimizer.

Follows design: clear hierarchy for config, data, and runtime issues.
"""

from __future__ import annotations


class BEOLBaseError(Exception):
    """Base class for all sram_beol package errors."""
    pass


class BEOLConfigError(BEOLBaseError):
    """Raised for invalid configuration (YAML, params, ranges)."""
    pass


class BEOLDataError(BEOLBaseError):
    """
    Raised for data issues (CSV load/columns, missing exact corner for structures,
    interpolation / hull errors, etc.).

    Per design: when raising for corner problems, pass available_corners=...
    The exception stores .available_corners and includes it in str() for diagnostics.
    """
    def __init__(self, message: str, *, available_corners: list[str] | None = None) -> None:
        super().__init__(message)
        self.available_corners: list[str] = list(available_corners) if available_corners else []

    def __str__(self) -> str:
        base = super().__str__()
        if self.available_corners:
            return f"{base} (available corners: {self.available_corners})"
        return base


class BEOLPatternError(BEOLBaseError):
    """Raised for invalid WirePattern (rule violations)."""
    pass


class BEOLComputationError(BEOLBaseError):
    """Raised for numerical or evaluation errors inside models (e.g. evaluator)."""
    pass


# Provide BEOLRuntimeError for compatibility with __init__.py , optimizer and legacy.
class BEOLRuntimeError(BEOLBaseError):
    """Raised for high-level runtime / orchestration errors (e.g. no patterns generated)."""
    pass
