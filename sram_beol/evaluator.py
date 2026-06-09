"""ElmoreLadderEvaluator: distributed RC ladder delay calculator for SRAM WL BEOL.

Implements exact topology and multi-layer equivalent R/C per design Section 6.

Topology (per segment):
    driver_R → (wire_segment_R + via_eq_density) → device_R (series) → (device_C + wire_C_seg) (to gnd)

Key properties:
- segment_um and via_pitch_um are independent.
- Via contribution: via_r_ohm / via_pitch_um added to R_per_um (density model).
- Multi-layer: per-metal query to DB using each color's (w, s, shape_color),
  parallel within metal by conductance sum, then parallel across metals.
- Classic Elmore: tau_to_tap_k = sum( R_upstream_j * C_downstream_from_j ) for j <=k
- Returns near/far/avg for both raw tau and prop_delay (0.69 * tau) in picoseconds.
- Also returns per-device profiles + equiv params + cost proxies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from .exceptions import BEOLConfigError, BEOLPatternError, BEOLComputationError
from .pattern import WirePattern

if TYPE_CHECKING:
    from .config import WireConfig


# ohm * fF  product  -> picoseconds
# (1 ohm * 1 fF = 1e-15 s = 0.001 ps)
RC_PRODUCT_TO_PS: float = 1e-3

# Propagation delay factor (approx 50% delay from Elmore tau for RC step response)
PROP_FACTOR: float = 0.69


class ElmoreLadderEvaluator:
    """Evaluator for Elmore delay on the periodic ladder model of a long WL.

    Supports two construction styles for compatibility:
    1. Production / optimizer path: ElmoreLadderEvaluator(config: WireConfig, db: BEOLModelDB)
    2. Direct / unit-test path: ElmoreLadderEvaluator(driver_r_ohm=..., ..., db=..., corner=...)

    All lengths in um, resistances in ohm, capacitances in fF (from DB Ctotal).
    Delays reported in ps.

    Usage (config style):
        evaluator = ElmoreLadderEvaluator(config, db)
        result = evaluator.evaluate(pattern)

    The class is intentionally not a frozen dataclass (it is a calculator with behavior).
    """

    def __init__(
        self,
        config: "WireConfig | None" = None,
        db: Any = None,
        *,
        driver_r_ohm: float | None = None,
        device_r_ohm: float | None = None,
        device_c_ff: float | None = None,
        via_r_ohm: float | None = None,
        length_um: float | None = None,
        segment_um: float | None = None,
        via_pitch_um: float | None = None,
        corner: str | None = None,
        **ignored: Any,
    ) -> None:
        """Flexible constructor.

        If `config` is provided (and is a WireConfig or duck-type), the electrical
        and geometric params + corner are taken from it. `db` must be supplied.
        Otherwise falls back to explicit kwarg scalars (used by isolated unit tests
        with FakeDB).
        """
        if config is not None and hasattr(config, "driver_r_ohm"):
            # Production path: ElmoreLadderEvaluator(config, db)
            self.config = config
            self.driver_r_ohm = float(config.driver_r_ohm)
            self.device_r_ohm = float(config.device_r_ohm)
            self.device_c_ff = float(config.device_c_ff)
            self.via_r_ohm = float(config.via_r_ohm)
            self.length_um = float(config.length_um)
            self.segment_um = float(config.segment_um)
            self.via_pitch_um = float(config.via_pitch_um)
            self.corner = str(config.corner)
            self.db = db
        else:
            # Direct scalar path (tests, advanced)
            if driver_r_ohm is None:
                raise BEOLConfigError("Must provide either WireConfig or driver_r_ohm (and peers) + corner + db")
            self.config = None
            self.driver_r_ohm = float(driver_r_ohm)
            self.device_r_ohm = float(device_r_ohm) if device_r_ohm is not None else None  # type: ignore
            self.device_c_ff = float(device_c_ff) if device_c_ff is not None else None  # type: ignore
            self.via_r_ohm = float(via_r_ohm) if via_r_ohm is not None else None  # type: ignore
            self.length_um = float(length_um) if length_um is not None else None  # type: ignore
            self.segment_um = float(segment_um) if segment_um is not None else None  # type: ignore
            self.via_pitch_um = float(via_pitch_um) if via_pitch_um is not None else None  # type: ignore
            self.corner = str(corner) if corner is not None else ""
            self.db = db

        # Fill any missing from kwargs if partial (defensive)
        for name in ("driver_r_ohm", "device_r_ohm", "device_c_ff", "via_r_ohm",
                     "length_um", "segment_um", "via_pitch_um"):
            if getattr(self, name, None) is None and name in ignored:
                setattr(self, name, float(ignored[name]))

        self._validate_params()

    def _validate_params(self) -> None:
        """Validate all constructor parameters are physically sensible."""
        params = {
            "driver_r_ohm": self.driver_r_ohm,
            "device_r_ohm": self.device_r_ohm,
            "device_c_ff": self.device_c_ff,
            "via_r_ohm": self.via_r_ohm,
            "length_um": self.length_um,
            "segment_um": self.segment_um,
            "via_pitch_um": self.via_pitch_um,
        }
        for name, val in params.items():
            if val is None:
                raise BEOLConfigError(f"{name} is required")
            if not isinstance(val, (int, float)):
                raise BEOLConfigError(f"{name} must be numeric, got {type(val)}")
            if name in ("driver_r_ohm", "device_r_ohm", "via_r_ohm"):
                if val < 0.0:
                    raise BEOLConfigError(f"{name} must be >= 0, got {val}")
            else:
                if val <= 0.0:
                    raise BEOLConfigError(f"{name} must be > 0, got {val}")
        if not self.corner or not str(self.corner).strip():
            raise BEOLConfigError("corner must be a non-empty string")
        if self.db is None:
            raise BEOLConfigError("db (BEOLModelDB-like) is required for RC queries")

        # also run the named method for full checks (kept for override / subclassing)
        self._validate_params()

    def _validate_params(self) -> None:
        """Validate all constructor parameters are physically sensible.

        Resistances (driver/device/via) may be 0 (degenerate model allowed for tests).
        Lengths, pitches and device C must be > 0.
        """
        params = {
            "driver_r_ohm": self.driver_r_ohm,
            "device_r_ohm": self.device_r_ohm,
            "device_c_ff": self.device_c_ff,
            "via_r_ohm": self.via_r_ohm,
            "length_um": self.length_um,
            "segment_um": self.segment_um,
            "via_pitch_um": self.via_pitch_um,
        }
        for name, val in params.items():
            if val is None:
                raise BEOLConfigError(f"{name} is required")
            if not isinstance(val, (int, float)):
                raise BEOLConfigError(f"{name} must be numeric, got {type(val)}")
            if name in ("driver_r_ohm", "device_r_ohm", "via_r_ohm"):
                if val < 0.0:
                    raise BEOLConfigError(f"{name} must be >= 0, got {val}")
            else:
                if val <= 0.0:
                    raise BEOLConfigError(f"{name} must be > 0, got {val}")
        if not self.corner or not str(self.corner).strip():
            raise BEOLConfigError("corner must be a non-empty string")

    def _compute_num_segments(self) -> int:
        """N ≈ length / segment ; always at least 1 device/segment."""
        n = int(round(self.length_um / self.segment_um))
        return max(1, n)

    def _query_metal_rc(
        self, metal: str, width: float, space: float, colors: Tuple[str, ...]
    ) -> Tuple[float, float]:
        """Query DB for each color variant on this metal and return (r_per_um, c_per_um).

        R_per_um for the metal group = 1 / sum( w / Rsh_color ) over colors (parallel)
        C_per_um for the metal group = sum( Ctotal_color )
        """
        if not colors:
            raise BEOLComputationError(f"No colors specified for metal {metal}")

        g_per_um = 0.0  # total conductance per um for this metal's parallels
        c_per_um = 0.0

        for shape_color in colors:
            try:
                rc = self.db.get_rc_params(
                    structure=metal,
                    corner=self.corner,
                    shape_color=shape_color,
                    width=width,
                    space=space,
                )
            except Exception as exc:  # DB may raise its own; wrap for clarity
                raise BEOLComputationError(
                    f"DB query failed for {metal}/{shape_color} w={width} s={space} "
                    f"corner={self.corner}: {exc}"
                ) from exc

            if not isinstance(rc, dict):
                raise BEOLComputationError(f"DB returned non-dict for {metal}/{shape_color}")

            rsh = float(rc.get("Rsh", 0.0))
            ctotal = float(rc.get("Ctotal", 0.0))

            if rsh <= 0.0:
                raise BEOLComputationError(
                    f"Invalid Rsh={rsh} from DB for {metal}/{shape_color}"
                )

            # conductance of one trace: w / Rsh   (1 / (Rsh/w) )
            g_per_um += width / rsh
            c_per_um += ctotal

        if g_per_um <= 0.0:
            raise BEOLComputationError(f"Zero conductance for metal {metal}")

        r_per_um = 1.0 / g_per_um
        return r_per_um, c_per_um

    def _compute_equiv_rc(self, pattern: WirePattern) -> Tuple[float, float, float, float]:
        """Return (equiv_r_per_um, equiv_c_per_um, via_r_per_um, total_metal_width_sum).

        equiv_r_per_um includes the via density contribution.
        total_metal_width_sum is the Pareto cost proxy (sum w * num_colors over metals).
        """
        if not pattern.layers or not pattern.is_valid():
            raise BEOLPatternError(
                f"Pattern is invalid or empty: {pattern.description}"
            )

        total_g = 0.0  # across all metals
        total_c = 0.0
        total_width_sum = 0.0

        for metal in pattern.layers:
            spec = pattern.specs[metal]
            w = float(spec["width"])
            sp = float(spec["space"])
            colors: Tuple[str, ...] = tuple(spec["colors"])

            r_m, c_m = self._query_metal_rc(metal, w, sp, colors)
            # conductance of this metal group
            total_g += 1.0 / r_m
            total_c += c_m

            # cost proxy contribution (regardless of R/C)
            total_width_sum += w * len(colors)

        if total_g <= 0.0:
            raise BEOLComputationError("Total conductance is zero after parallel metals")

        r_metal_parallel = 1.0 / total_g
        c_parallel = total_c

        # via series density contribution (independent of segment)
        via_r_per_um = self.via_r_ohm / self.via_pitch_um

        equiv_r = r_metal_parallel + via_r_per_um
        equiv_c = c_parallel

        return equiv_r, equiv_c, via_r_per_um, total_width_sum

    def _elmore_taus_raw(
        self, r_driver: float, r_stage: float, c_tap: float, n: int
    ) -> List[float]:
        """Compute list of Elmore tau (in raw ohm*fF units) to each of the n device taps.

        Uses classic prefix-R * suffix-C summation.
        Indexing: taps 0..n-1 (0=near/first device after first segment, n-1=far)
        """
        if n < 1:
            raise BEOLComputationError("n must be >= 1")
        if c_tap <= 0.0:
            raise BEOLComputationError("c_tap must be > 0")

        # suffix_c[k] = sum of C from tap k to end (0-based: suffix_c[0] = n * c_tap)
        suffix_c: List[float] = [0.0] * (n + 1)
        for k in range(n - 1, -1, -1):
            suffix_c[k] = suffix_c[k + 1] + c_tap

        taus: List[float] = []
        for k in range(n):  # for tap k (0-based)
            tau = 0.0
            # driver R always sees all downstream C (suffix from first tap)
            tau += r_driver * suffix_c[0]
            # each stage j=0..k  (stage j is before tap j)
            for j in range(k + 1):
                tau += r_stage * suffix_c[j]
            taus.append(tau)
        return taus

    def evaluate(self, pattern: WirePattern) -> Dict[str, Any]:
        """Evaluate the given pattern and return delay metrics + equiv parameters.

        Returns dict with:
            description, pattern_key, num_segments,
            equiv_r_per_um, equiv_c_per_um, via_r_per_um,
            total_metal_width_sum, metal_count,
            near_tau_ps, far_tau_ps, avg_tau_ps,
            near_prop_ps, far_prop_ps, avg_prop_ps,
            per_device_tau_ps, per_device_prop_ps
        All delays in picoseconds (ps).
        """
        if not isinstance(pattern, WirePattern):
            raise BEOLPatternError("evaluate expects a WirePattern instance")

        n = self._compute_num_segments()

        equiv_r, equiv_c, via_r_dens, total_w_sum = self._compute_equiv_rc(pattern)

        # R and C for one full stage (segment + device)
        r_stage = (equiv_r * self.segment_um) + self.device_r_ohm
        c_wire_seg = equiv_c * self.segment_um
        c_tap = self.device_c_ff + c_wire_seg

        # raw RC units (ohm * fF)
        raw_taus = self._elmore_taus_raw(
            r_driver=self.driver_r_ohm,
            r_stage=r_stage,
            c_tap=c_tap,
            n=n,
        )

        # convert to ps
        taus_ps: List[float] = [t * RC_PRODUCT_TO_PS for t in raw_taus]
        props_ps: List[float] = [t * PROP_FACTOR for t in taus_ps]

        if not taus_ps:
            raise BEOLComputationError("No device taps computed")

        near_tau = taus_ps[0]
        far_tau = taus_ps[-1]
        avg_tau = sum(taus_ps) / len(taus_ps)

        near_prop = props_ps[0]
        far_prop = props_ps[-1]
        avg_prop = sum(props_ps) / len(props_ps)

        result: Dict[str, Any] = {
            "description": pattern.description,
            "pattern_key": pattern.key(),
            "num_segments": n,
            "equiv_r_per_um": equiv_r,
            "equiv_c_per_um": equiv_c,
            "via_r_per_um": via_r_dens,
            "total_metal_width_sum": total_w_sum,
            "metal_count": pattern.metal_count(),
            "near_tau_ps": near_tau,
            "far_tau_ps": far_tau,
            "avg_tau_ps": avg_tau,
            "near_prop_ps": near_prop,
            "far_prop_ps": far_prop,
            "avg_prop_ps": avg_prop,
            "per_device_tau_ps": taus_ps,
            "per_device_prop_ps": props_ps,
        }
        return result

    def __repr__(self) -> str:
        return (
            f"ElmoreLadderEvaluator(length={self.length_um}um, segment={self.segment_um}um, "
            f"via_pitch={self.via_pitch_um}um, corner={self.corner!r})"
        )
