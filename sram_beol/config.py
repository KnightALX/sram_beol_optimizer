"""Configuration model for SRAM BEOL Interconnect Optimizer.

Primary mechanism: YAML file (source of truth) loaded into immutable WireConfig dataclass.

Per design:
- Section 3: exact required fields, argparse thin (overrides handled here).
- Validation for types, ranges, non-negative values.
- Immutable-ish via frozen dataclass.
- Also provides logging setup (stdlib, configurable).

Public functions:
- load_wire_config(config_path, overrides=None)
- configure_logging(level="INFO")

WireConfig fields exactly match the documented YAML keys (with units in names).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import BEOLConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayerConstraint:
    """Per-layer W/S range constraint for geometry.layer_constraints.

    All fields optional; None = unbounded on that side.
    Resolution semantics: per-layer overrides global geometry.max_width_um.

    Attributes:
        metal: Metal layer name (e.g. "M5"). Must exist in WireConfig.metals.
        min_width_um: Lower bound on wire width (inclusive, um). None = 0.0.
        max_width_um: Upper bound on wire width (inclusive, um). None = global fallback.
        min_space_um: Lower bound on wire space (inclusive, um). None = 0.0.
        max_space_um: Upper bound on wire space (inclusive, um). None = +infinity.
    """

    metal: str
    min_width_um: Optional[float] = None
    max_width_um: Optional[float] = None
    min_space_um: Optional[float] = None
    max_space_um: Optional[float] = None

    def resolve(
        self, fallback_max_width_um: float
    ) -> tuple[float, float, float, float]:
        """Resolve to effective (min_w, max_w, min_s, max_s) for DB grid filtering."""
        min_w = 0.0 if self.min_width_um is None else float(self.min_width_um)
        max_w = (
            float(fallback_max_width_um)
            if self.max_width_um is None
            else float(self.max_width_um)
        )
        min_s = 0.0 if self.min_space_um is None else float(self.min_space_um)
        max_s = float("inf") if self.max_space_um is None else float(self.max_space_um)
        return min_w, max_w, min_s, max_s


@dataclass(frozen=True)
class WireConfig:
    """Frozen dataclass holding all optimization parameters.

    Loaded from YAML (primary) or constructed directly (advanced use / tests).
    YAML supports logical grouping for readability:
      geometry:
        length_um: ...
      electrical:
        driver_r_ohm: ...
      fixed_signals:
        - metal: "M1"
          width: 0.06
          space: 0.54
          colors: ["ABA"]

    All geometric units are micrometers (um).
    Resistances in ohms (Ω).
    Capacitance in femtofarads (fF).

    Attributes:
        csv_path: Path to BEOL RC model CSV (exact columns required by DB loader).
        corner: Process corner string; MUST match exactly a corner in the CSV.
        length_um: Total WL length in um (>20 typical for long lines).
        metals: List of candidate metal layers (e.g. ["M1", "M2", "M3", "M4"]).
        max_width_um: Upper bound on allowed wire width in each layer.
        segment_um: Device tap spacing (ladder rung spacing). Independent of via_pitch.
        via_pitch_um: Via strapping pitch (density) along the wire. Independent of segment.
        driver_r_ohm: Driver resistance.
        device_r_ohm: Per-tap poly/device resistance.
        device_c_ff: Per-tap device capacitance to ground.
        via_r_ohm: Single via resistance (scaled by 1/via_pitch in model).
        output_dir: Directory for all reports and plots (created if needed).
        fixed_signals: List of mandatory fixed wires. Each item is a dict with
            metal, width, space, colors. These are always included in every pattern
            (locked W/S/Color). Optimizer searches for best additional parallel/stacking
            (respecting direction rules) on top of the fixed base.

    The dataclass is frozen (immutable after creation). Use overrides at load time
    for CLI variations.
    """

    csv_path: str
    corner: str
    length_um: float
    metals: list[str]
    max_width_um: float
    segment_um: float
    via_pitch_um: float
    driver_r_ohm: float
    device_r_ohm: float
    device_c_ff: float
    via_r_ohm: float
    output_dir: str
    fixed_signals: list[dict] = field(default_factory=list)

    # Extensibility / sample configs may include these (ignored or used by enumerator in full impl)
    max_patterns: int | None = None
    max_layers: int | None = None

    # Per-layer geometry constraints (opt-in YAML section).
    # When a metal is absent from this dict, the global max_width_um applies with no other bound.
    layer_constraints: dict[str, "LayerConstraint"] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Run validation immediately. Raises BEOLConfigError on any failure."""
        self._validate()

    def _validate(self) -> None:
        """Strict validation per design (types + ranges + non-negative)."""
        # Required non-empty strings
        if not isinstance(self.csv_path, str) or not self.csv_path.strip():
            raise BEOLConfigError(
                "csv_path must be a non-empty string. "
                "Example: csv_path: \"backmodel.csv\""
            )
        if not isinstance(self.corner, str) or not self.corner.strip():
            raise BEOLConfigError(
                "corner must be a non-empty string matching a corner exactly present in the CSV. "
                "Example: corner: \"typical\""
            )
        if not isinstance(self.output_dir, str) or not self.output_dir.strip():
            raise BEOLConfigError("output_dir must be a non-empty string.")

        # Positive numeric scalars (allow int or float from YAML)
        numeric_positives = {
            "length_um": self.length_um,
            "max_width_um": self.max_width_um,
            "segment_um": self.segment_um,
            "via_pitch_um": self.via_pitch_um,
            "driver_r_ohm": self.driver_r_ohm,
            "device_r_ohm": self.device_r_ohm,
            "device_c_ff": self.device_c_ff,
            "via_r_ohm": self.via_r_ohm,
        }
        for name, value in numeric_positives.items():
            if not isinstance(value, (int, float)):
                raise BEOLConfigError(
                    f"{name} must be numeric (int or float), got {type(value).__name__}."
                )
            if value <= 0:
                raise BEOLConfigError(
                    f"{name} must be strictly positive (>0), got {value}. "
                    "Check your YAML configuration."
                )

        # metals list
        if not isinstance(self.metals, (list, tuple)):
            raise BEOLConfigError(
                f"metals must be a list of strings, got {type(self.metals).__name__}. "
                'Example: metals: ["M1", "M2", "M3", "M4"]'
            )
        if len(self.metals) == 0:
            raise BEOLConfigError("metals list must contain at least one layer name.")
        if not all(isinstance(m, str) and m.strip() for m in self.metals):
            raise BEOLConfigError(
                "All entries in metals must be non-empty strings. "
                f"Got: {self.metals}"
            )

        # fixed_signals validation (optional)
        if not isinstance(self.fixed_signals, (list, tuple)):
            raise BEOLConfigError("fixed_signals must be a list of dicts if provided.")
        for i, fs in enumerate(self.fixed_signals):
            if not isinstance(fs, dict):
                raise BEOLConfigError(f"fixed_signals[{i}] must be a dict with metal, width, space, colors.")
            for k in ("metal", "width", "space", "colors"):
                if k not in fs:
                    raise BEOLConfigError(f"fixed_signals[{i}] missing required key '{k}'.")
            try:
                float(fs["width"])
                float(fs["space"])
            except Exception:
                raise BEOLConfigError(f"fixed_signals[{i}] width/space must be numeric.")
            cols = fs["colors"]
            if isinstance(cols, str):
                cols = [cols]
            if not isinstance(cols, (list, tuple)) or len(cols) == 0:
                raise BEOLConfigError(f"fixed_signals[{i}] colors must be non-empty list or string.")

        # Per-layer constraints (optional)
        if not isinstance(self.layer_constraints, dict):
            raise BEOLConfigError(
                f"layer_constraints must be a dict (metal -> LayerConstraint), "
                f"got {type(self.layer_constraints).__name__}."
            )
        metals_set = set(self.metals)
        for metal, lc in self.layer_constraints.items():
            if metal not in metals_set:
                raise BEOLConfigError(
                    f"layer_constraints references metal {metal} not in "
                    f"geometry.metals={self.metals}. "
                    "Either add it to metals or remove the constraint."
                )
            for fname in ("min_width_um", "max_width_um", "min_space_um", "max_space_um"):
                v = getattr(lc, fname, None)
                if v is not None:
                    if not isinstance(v, (int, float)):
                        raise BEOLConfigError(
                            f"layer_constraints[{metal!r}].{fname} must be numeric, "
                            f"got {type(v).__name__}."
                        )
                    if v < 0:
                        raise BEOLConfigError(
                            f"layer_constraints[{metal!r}].{fname} must be >= 0, got {v}."
                        )
            if (
                lc.min_width_um is not None
                and lc.max_width_um is not None
                and lc.min_width_um > lc.max_width_um
            ):
                raise BEOLConfigError(
                    f"layer_constraints[{metal!r}]: min_width_um={lc.min_width_um} "
                    f"> max_width_um={lc.max_width_um}."
                )
            if (
                lc.min_space_um is not None
                and lc.max_space_um is not None
                and lc.min_space_um > lc.max_space_um
            ):
                raise BEOLConfigError(
                    f"layer_constraints[{metal!r}]: min_space_um={lc.min_space_um} "
                    f"> max_space_um={lc.max_space_um}."
                )

        # Reasonable sanity (not hard limits but helpful)
        if self.length_um < 1.0:
            logger.warning("length_um < 1um is unusual for long-wire optimization target.")
        if self.max_width_um > 10.0:
            logger.warning("max_width_um is very large; typical BEOL wires are << 1um.")

        logger.debug(f"WireConfig validated successfully for corner={self.corner}")

    def __repr__(self) -> str:
        return (
            f"WireConfig(corner={self.corner!r}, length_um={self.length_um}, "
            f"metals={self.metals}, output_dir={self.output_dir!r}, ...)"
        )

    # ------------------------------------------------------------------
    # Compatibility / convenience methods used by the rest of the package
    # (optimizer, db wrappers, report, etc.). Keep non-mutating since frozen.
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "WireConfig":
        """Classmethod expected by some internal code paths.

        Delegates to the primary load_wire_config (YAML + validation).
        """
        return load_wire_config(config_path)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict of the config (useful for summaries, serialization)."""
        d = {
            "csv_path": self.csv_path,
            "corner": self.corner,
            "length_um": self.length_um,
            "metals": list(self.metals),
            "max_width_um": self.max_width_um,
            "segment_um": self.segment_um,
            "via_pitch_um": self.via_pitch_um,
            "driver_r_ohm": self.driver_r_ohm,
            "device_r_ohm": self.device_r_ohm,
            "device_c_ff": self.device_c_ff,
            "via_r_ohm": self.via_r_ohm,
            "output_dir": self.output_dir,
        }
        if self.max_patterns is not None:
            d["max_patterns"] = self.max_patterns
        if self.max_layers is not None:
            d["max_layers"] = self.max_layers
        d["fixed_signals"] = list(self.fixed_signals) if self.fixed_signals else []
        return d

    def resolve_csv_path(self) -> Path:
        """Return absolute Path to the CSV (used by optimizer/db lazy init)."""
        return Path(self.csv_path).resolve()

    def ensure_output_dir(self) -> Path:
        """Create (if needed) and return the output_dir as Path.

        Many parts of the pipeline write artifacts here.
        """
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WireConfig":
        """Construct WireConfig directly from a dict (for tests, overrides, internal use).
        Fills defaults for missing optionals and validates.
        """
        # Provide minimal defaults matching REQUIRED
        base = {
            "csv_path": data.get("csv_path", ""),
            "corner": data.get("corner", "typical"),
            "length_um": float(data.get("length_um", 1.0)),
            "metals": data.get("metals", ["M3"]),
            "max_width_um": float(data.get("max_width_um", 0.04)),
            "segment_um": float(data.get("segment_um", 1.0)),
            "via_pitch_um": float(data.get("via_pitch_um", 0.5)),
            "driver_r_ohm": float(data.get("driver_r_ohm", 80.0)),
            "device_r_ohm": float(data.get("device_r_ohm", 45.0)),
            "device_c_ff": float(data.get("device_c_ff", 0.35)),
            "via_r_ohm": float(data.get("via_r_ohm", 8.0)),
            "output_dir": data.get("output_dir", "results"),
            "fixed_signals": data.get("fixed_signals", []),
        }
        # merge provided
        for k, v in data.items():
            if k in base or k == "max_patterns":
                base[k] = v
        if "max_patterns" in data:
            base["max_patterns"] = data["max_patterns"]
        # Delegate to constructor (it will validate)
        # We use the dataclass fields directly by constructing via known loader if present, else direct
        try:
            return cls(**{k: base[k] for k in [
                "csv_path","corner","length_um","metals","max_width_um","segment_um",
                "via_pitch_um","driver_r_ohm","device_r_ohm","device_c_ff","via_r_ohm","output_dir"
            ]})
        except TypeError:
            # If dataclass signature differs, fall back
            return load_wire_config.__globals__.get('WireConfig', cls)(**base)  # best effort


def load_wire_config(
    config_path: str | Path,
    overrides: dict[str, Any] | None = None,
) -> WireConfig:
    """Load WireConfig from YAML file (primary mechanism per design).

    YAML is the source of truth. All electrical + geometric params live here.

    Args:
        config_path: Path to .yaml or .yml file.
        overrides: Optional dict of top-level keys to override after YAML load
                   (used by thin CLI for --output-dir, --csv-override etc.).
                   Overrides are applied BEFORE validation.

    Returns:
        Frozen, validated WireConfig instance.

    Raises:
        BEOLConfigError: on file errors, YAML errors, missing fields,
                         validation failures, or bad override results.
    """
    path = Path(config_path)
    if not path.exists():
        raise BEOLConfigError(
            f"Config file not found: {path}. "
            "Provide a valid --config path to the YAML file."
        )
    if not path.is_file():
        raise BEOLConfigError(f"Config path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise BEOLConfigError(f"YAML parse error in {path}: {exc}") from exc
    except Exception as exc:
        raise BEOLConfigError(f"Failed to read config file {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise BEOLConfigError(
            f"Top level of YAML config must be a mapping (dict), got {type(raw).__name__}."
        )

    # Start from YAML content
    # Support grouped YAML for readability (e.g. geometry:, electrical:, fixed_signals:)
    data: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                data[kk] = vv
        else:
            data[k] = v

    # Apply CLI / caller overrides (thin argparse integration)
    if overrides:
        for key, value in overrides.items():
            if value is not None:  # allow falsy? but for paths/strings usually truthy
                data[key] = value
        logger.debug(f"Applied {len(overrides)} config override(s): {list(overrides.keys())}")

    # Ensure all documented required fields are present (fail fast with good msg)
    required_fields = [
        "csv_path",
        "corner",
        "length_um",
        "metals",
        "max_width_um",
        "segment_um",
        "via_pitch_um",
        "driver_r_ohm",
        "device_r_ohm",
        "device_c_ff",
        "via_r_ohm",
        "output_dir",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise BEOLConfigError(
            f"Missing required field(s) in config: {missing}. "
            "YAML must contain all of: " + ", ".join(required_fields) + ". "
            "See design document Section 3 for the full example."
        )

    # Construct (validation happens in __post_init__)
    try:
        cfg = WireConfig(**data)
    except TypeError as exc:
        # e.g. unexpected extra keys or wrong constructor call
        raise BEOLConfigError(
            f"Error constructing WireConfig from YAML data: {exc}. "
            "Ensure only known fields are present and types are correct."
        ) from exc

    logger.info(f"Loaded WireConfig from {path} (corner={cfg.corner}, metals={cfg.metals})")
    return cfg


def configure_logging(level: str = "INFO", *, log_file: str | Path | None = None) -> None:
    """Configure stdlib logging for the sram_beol package.

    Per design: "Use stdlib logging, configurable. key milestones logged."

    This is called automatically by the CLI. Users of the public Python API
    may call it explicitly before constructing WLInterconnectOptimizer if they
    want custom log control.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL (case-insensitive).
        log_file: Optional path; if given, also logs to this file (append mode).

    Notes:
        - Configures the "sram_beol" logger (child loggers propagate).
        - Safe to call multiple times (replaces handlers).
        - Uses a simple timestamped format suitable for EDA tools.
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise BEOLConfigError(
            f"Invalid log level: {level}. Choose from DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )

    pkg_logger = logging.getLogger("sram_beol")
    pkg_logger.setLevel(numeric_level)

    # Remove any pre-existing handlers to support reconfiguration (important for tests + CLI)
    for handler in pkg_logger.handlers[:]:
        pkg_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console (stderr is conventional for logs mixed with CLI output)
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    pkg_logger.addHandler(console)

    if log_file is not None:
        file_handler = logging.FileHandler(Path(log_file), mode="a", encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        pkg_logger.addHandler(file_handler)

    pkg_logger.propagate = False  # package manages its own output when configured

    pkg_logger.debug(f"Logging configured at level {level} (file={log_file})")
