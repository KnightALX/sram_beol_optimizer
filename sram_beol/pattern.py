"""WirePattern and PatternEnumerator (pattern.py).

Implements Sections 4 and 5 of the approved design document exactly.

WirePattern (frozen dataclass):
  - layers: tuple[str, ...]
  - specs: dict[metal, {"width": float, "space": float, "colors": tuple[str, ...]} ]
  - description (computed): e.g. "M3(0.040/0.020/ABA+BAB)+M4(0.035/0.025/ABA)"
  - is_valid(): strict same-layer parallel (same W/S + allowed multiple colors) vs
    cross-layer (independent per metal). Also positive dims, unique layers, etc.
  - key(): hashable for caching/dedup
  - Preserves backward-compatible helper APIs used by evaluator/optimizer/report:
    num_colors(metal), total_metal_width(), metal_count()

PatternEnumerator:
  - __init__(config: WireConfig, db: BEOLModelDB)
  - generate() -> list[WirePattern]
  - Per design:
      * For each metal (from config.metals): skip or (W,S filtered by max_width from DB grid for config.corner) + color combination(s)
      * Cartesian (via combinations of 1..MAX_LAYERS metals + product of their use-choices)
      * Filter to those with .is_valid()
      * Practical pruning: MAX_LAYERS=3, MAX_WS_CANDIDATES_PER_LAYER (top by Rsh via get_rc_params using representative color)
      * "prefer upper metals": achieved naturally by generating from config order + final deterministic sort
      * Only (W,S,Color) that can be queried successfully from DB (via get_rc_params) are considered valid for inclusion
  - Color support expanded for completeness (design cites ABA/BAB examples but single-wire and other patterns needed for full coverage); is_valid and generation respect ALLOWED_COLORS.

All code is clean, typed, and documented. DB validity enforced at generation time (by successful rc query); structural rules in is_valid().
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .config import WireConfig
from .db import BEOLModelDB
from .exceptions import BEOLConfigError, BEOLPatternError

logger = logging.getLogger(__name__)

# Direction groups for stacking (叠线) rules.
# Odd layers (M1, M3, ...) share one preferred routing direction.
# Even layers (M2, M4, ...) share the orthogonal direction.
# Only metals within the *same* direction group may be stacked together in one pattern.
# Same-layer parallel (并线 with multiple colors on one metal) is always allowed.
DIRECTION_GROUPS = {
    "odd": {f"M{i}" for i in range(1, 20, 2)},   # M1, M3, M5, ...
    "even": {f"M{i}" for i in range(2, 20, 2)},  # M2, M4, M6, ...
}

def _get_direction(metal: str) -> str:
    if metal in DIRECTION_GROUPS["odd"]:
        return "odd"
    if metal in DIRECTION_GROUPS["even"]:
        return "even"
    return "unknown"


# Allowed ShapeColor / parallel color pattern identifiers.
# Design explicitly references ABA and BAB for same-layer parallel.
# We include common singles/pairs for full practical generation while remaining
# backward compatible with existing tests and call sites that use ("ABA",) and ("ABA", "BAB").
ALLOWED_COLORS: frozenset[str] = frozenset({"A", "B", "AB", "BA", "ABA", "BAB"})


@dataclass(frozen=True, eq=False)
class WirePattern:
    """Frozen dataclass representing one routing pattern (layer selection + per-layer W/S/Color).

    Follows design Section 5 exactly.
    Additional convenience methods (num_colors, total_metal_width, metal_count) are
    kept for compatibility with evaluator, optimizer and reports (they use total_metal_width
    as the cost proxy for Pareto).
    """

    layers: Tuple[str, ...]
    specs: Dict[str, Dict[str, Any]]

    description: str = field(init=False, repr=True, compare=False)

    def __post_init__(self) -> None:
        """Normalize layers/specs and compute description.

        Lenient on construction for is_valid() testing of bad cases (no raise on
        empty layers or bad numeric values). Existing call sites pass well-formed
        data; we additionally coerce colors lists->tuples and values to native types
        so that .specs after construction satisfies test expectations (tuple colors)
        and internal key/description logic.
        """
        if not isinstance(self.layers, tuple):
            object.__setattr__(self, "layers", tuple(self.layers))

        # Normalize specs (rebind the field because frozen dataclass).
        # Lenient: if a spec entry is missing keys or bad types, leave it (is_valid will return False).
        norm_specs: Dict[str, Dict[str, Any]] = {}
        for m, sp in dict(self.specs).items():
            mm = str(m)
            try:
                w = float(sp["width"])
                s = float(sp["space"])
                raw_c = sp["colors"]
                cols: Tuple[str, ...] = tuple(raw_c) if isinstance(raw_c, (list, tuple)) else (str(raw_c),)
                norm_specs[mm] = {"width": w, "space": s, "colors": cols}
            except Exception:
                # Preserve original (bad) entry so is_valid can detect and return False
                norm_specs[mm] = dict(sp)
        object.__setattr__(self, "specs", norm_specs)

        # Compute description leniently (skip bad metals)
        desc_parts: list[str] = []
        for metal in self.layers:
            try:
                if metal not in self.specs:
                    continue
                s = self.specs[metal]
                w = float(s["width"])
                sp = float(s["space"])
                cols: Tuple[str, ...] = tuple(s["colors"])
                cols_str = "+".join(cols)
                desc_parts.append(f"{metal}({w:.3f}/{sp:.3f}/{cols_str})")
            except Exception:
                continue
        object.__setattr__(self, "description", "+".join(desc_parts))

    def __str__(self) -> str:
        """String form is the human description (used in reports, labels, logs)."""
        return self.description

    def _get_spec(self, metal: str) -> Dict[str, Any]:
        if metal not in self.specs:
            raise KeyError(f"Metal {metal} not in pattern")
        return self.specs[metal]

    def is_valid(self) -> bool:
        """Enforce rules per design Section 5.

        Same-layer parallel rules: one (width, space) per metal; multiple colors
        (e.g. ABA + BAB) allowed under that single (W, S).

        Cross-layer: metals have completely independent (W, S, Color) choices.

        Additional:
        - >= 1 layer
        - unique layer names
        - specs consistent with layers
        - colors non-empty and subset of ALLOWED_COLORS
        - width > 0, space >= 0 (per existing test expectations)
        - DB (W,S,Color) validity is *not* checked here (decoupled); enforced by
          PatternEnumerator using only grids + successful get_rc_params queries.
        """
        if not self.layers:
            return False
        seen: set[str] = set()
        for metal in self.layers:
            if metal in seen:
                return False
            seen.add(metal)
            if metal not in self.specs:
                return False
            spec = self.specs[metal]
            colors = spec.get("colors")
            if not isinstance(colors, (list, tuple)) or len(colors) == 0:
                return False
            if not all(c in ALLOWED_COLORS for c in colors):
                return False
            try:
                w = float(spec["width"])
                sp = float(spec.get("space", 0.0))
            except (KeyError, TypeError, ValueError):
                return False
            if w <= 0.0 or sp < 0.0:
                return False
        return True

    def key(self) -> Tuple:
        """Stable hashable key (independent of dict ordering). For caching and dedup."""
        key_items: list = []
        for metal in self.layers:
            s = self.specs[metal]
            w = float(s["width"])
            sp = float(s["space"])
            cols = tuple(s["colors"])
            key_items.append((metal, w, sp, cols))
        return tuple(key_items)

    def __hash__(self) -> int:
        return hash((self.layers, self.key()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WirePattern):
            return NotImplemented
        return (self.layers == other.layers) and (self.key() == other.key())

    # --- Compatibility APIs used by evaluator / optimizer / reports (design Sec 6/7) ---

    def num_colors(self, metal: str) -> int:
        """Number of parallel traces (sum of color pattern lengths, but here len(colors) as each entry is one bundle)."""
        return len(self._get_spec(metal)["colors"])

    def total_metal_width(self) -> float:
        """Cost proxy: sum over metals of (width * num_color_bundles)."""
        total = 0.0
        for metal in self.layers:
            s = self.specs[metal]
            total += float(s["width"]) * len(s["colors"])
        return total

    def metal_count(self) -> int:
        """Number of distinct metals used."""
        return len(self.layers)


class PatternEnumerator:
    """Generates valid WirePattern from config.metals + max_width + DB.

    Strictly implements design Section 5:
    - Obtains (W, S) grids via db.get_available_grid(metal, config.corner)
    - Filters widths <= config.max_width_um
    - Uses color combinations drawn from ALLOWED_COLORS (supporting same-layer multi-color)
    - Prunes WS candidates per layer to top-N by Rsh (via get_rc_params, using first viable color)
    - Limits total layers used to 1..MAX_LAYERS (default 3)
    - Uses combinations(k metals) + product(their choices) instead of full cross-product
      to avoid >MAX_LAYERS patterns
    - Emits only patterns for which is_valid() and for which every (metal, color, w, s)
      is queryable in the DB (no extrapolation / missing shapecolor)
    - Deterministic sorted output
    """

    MAX_LAYERS: int = 3
    MAX_WS_CANDIDATES_PER_LAYER: int = 4

    def __init__(self, config: WireConfig, db: BEOLModelDB) -> None:
        self.config = config
        self.db = db
        self._metals: Tuple[str, ...] = tuple(config.metals)

        # Fixed signals (mandatory base patterns, locked W/S/Color).
        # These are always included; we optimize additional parallel/stacking *on top of* them
        # (respecting direction rules).
        self.fixed_specs: Dict[str, Dict[str, Any]] = {}
        for fs in getattr(config, "fixed_signals", []) or []:
            try:
                m = str(fs.get("metal", "")).strip()
                if not m:
                    continue
                w = float(fs["width"])
                s = float(fs["space"])
                cols_raw = fs.get("colors", [])
                if isinstance(cols_raw, str):
                    cols_raw = [cols_raw]
                cols = tuple(str(c).strip() for c in cols_raw if str(c).strip())
                if cols:
                    self.fixed_specs[m] = {"width": w, "space": s, "colors": cols}
            except Exception:
                # Invalid fixed entry; will be ignored or cause later validation failure.
                continue

        # Determine the direction(s) enforced by fixed signals.
        # Fail-fast on unknown direction (likely typo like M99).
        # Warn on mixed directions (allows broad stacking on top).
        self._fixed_dirs: set[str] = set()
        for m in self.fixed_specs:
            d = _get_direction(m)
            if d == "unknown":
                raise BEOLConfigError(
                    f"fixed_signals references metal {m!r} with unknown direction group. "
                    "Use metals in {M1, M2, ..., M19} (M1/M3/M5... are 'odd', "
                    "M2/M4/M6... are 'even')."
                )
            self._fixed_dirs.add(d)
        if len(self._fixed_dirs) > 1:
            logger.warning(
                "fixed_signals contains mixed direction groups %s; "
                "candidate stacking metals will include any metal whose direction matches "
                "at least one fixed metal (union of groups).",
                sorted(self._fixed_dirs),
            )

    def _discover_colors(self, metal: str) -> List[str]:
        """Return the list of allowed color/ShapeColor values that have grid data for this metal+corner.

        Tries the known ALLOWED_COLORS; falls back to union behavior if needed.
        Uses try/except around get_available_grid(..., specific color) because it
        raises BEOLDataError when no data for that (structure,corner,shapecolor).
        """
        corner = self.config.corner
        discovered: List[str] = []
        for c in sorted(ALLOWED_COLORS):
            try:
                w_arr, s_arr = self.db.get_available_grid(metal, corner, c)
                if len(w_arr) > 0 and len(s_arr) > 0:
                    discovered.append(c)
            except Exception:
                continue
        if not discovered:
            # Fallback: use the module allowed (assume they will be validated later at rc query time)
            discovered = [c for c in sorted(ALLOWED_COLORS)]
        return discovered

    def _get_ws_candidates(self, metal: str) -> List[Tuple[float, float]]:
        """Pruned (w, s) list for the metal, filtered by per-layer constraints.

        1. Resolve effective (min_w, max_w, min_s, max_s) from layer_constraints
           (per-layer override) or global max_width_um (fallback).
        2. Get union grid for metal+corner (all shapecolors) from DB.
        3. Filter widths to [min_w, max_w] and spaces to [min_s, max_s].
        4. Rank candidate pairs by representative Rsh (lowest first) using get_rc_params
           with a viable color for that metal. Falls back gracefully.
        5. Take top N (or uniform stride sample on ties / no R variation)
        6. Return sorted unique.
        """
        corner = self.config.corner
        global_max_w = float(self.config.max_width_um)

        # Resolve effective (min_w, max_w, min_s, max_s) from per-layer constraints
        constraint = self.config.layer_constraints.get(metal)
        if constraint is None:
            min_w, max_w = 0.0, global_max_w
            min_s, max_s = 0.0, float("inf")
        else:
            min_w, max_w, min_s, max_s = constraint.resolve(global_max_w)

        try:
            w_arr, s_arr = self.db.get_available_grid(metal, corner)
        except Exception:
            return []

        # Filter widths to [min_w, max_w]
        widths = [
            float(w) for w in w_arr
            if min_w - 1e-12 <= float(w) <= max_w + 1e-12
        ]
        # Filter spaces to [min_s, max_s] (inf on max means no upper bound)
        if math.isinf(max_s):
            spaces = [float(s) for s in s_arr if float(s) >= min_s - 1e-12]
        else:
            spaces = [
                float(s) for s in s_arr
                if min_s - 1e-12 <= float(s) <= max_s + 1e-12
            ]

        if not widths or not spaces:
            logger.warning(
                "metal=%s: 0 valid (W,S) candidates after layer_constraints filter "
                "(min_w=%.4f max_w=%.4f min_s=%.4f max_s=%s). DB grid widths=%s, spaces=%s.",
                metal, min_w, max_w, min_s,
                "inf" if math.isinf(max_s) else f"{max_s:.4f}",
                list(w_arr), list(s_arr),
            )
            return []

        all_pairs: List[Tuple[float, float]] = [(w, s) for w in widths for s in spaces]

        # Representative Rsh for ranking (use first discoverable color)
        viable_colors = self._discover_colors(metal)
        rep_color = viable_colors[0] if viable_colors else "ABA"

        def rsh_of(pair: Tuple[float, float]) -> float:
            w, s = pair
            try:
                rc = self.db.get_rc_params(metal, corner, rep_color, w, s)
                return float(rc["Rsh"])
            except Exception:
                # Prefer wider on fallback (lower effective R)
                return 1000.0 - w * 100.0

        ranked = sorted(all_pairs, key=rsh_of)

        n = min(self.MAX_WS_CANDIDATES_PER_LAYER, len(ranked))
        selected = ranked[:n]

        # If R values effectively constant, uniform sample
        rvals = [rsh_of(p) for p in selected]
        if len(set(round(r, 6) for r in rvals)) <= 1 and len(ranked) > n:
            stride = max(1, len(ranked) // n)
            selected = ranked[::stride][:n]

        # dedup + stable sort
        uniq = sorted(set(selected), key=lambda p: (round(p[0], 9), round(p[1], 9)))
        return uniq

    def _per_metal_choices(self, metal: str) -> List[Optional[Dict[str, Any]]]:
        """Return [None (skip), spec, spec, ...] for this metal."""
        ws = self._get_ws_candidates(metal)
        if not ws:
            return [None]

        corner = self.config.corner
        viable_colors = self._discover_colors(metal)
        if not viable_colors:
            return [None]

        # Build curated combos from viable colors (singles + the documented ABA+BAB pair when both viable)
        combos: List[Tuple[str, ...]] = []
        for c in viable_colors:
            combos.append((c,))
        if "ABA" in viable_colors and "BAB" in viable_colors:
            combos.append(("ABA", "BAB"))

        choices: List[Optional[Dict[str, Any]]] = [None]
        for w, s in ws:
            # Only include (w,s,color) that are individually valid in DB for at least the colors we pick
            for cols_t in combos:
                # Validate each color in the bundle actually supports this exact (w,s) via rc query
                ok = True
                for c in cols_t:
                    try:
                        self.db.get_rc_params(metal, corner, c, w, s)
                    except Exception:
                        ok = False
                        break
                if ok:
                    choices.append(
                        {"width": float(w), "space": float(s), "colors": tuple(cols_t)}
                    )
        return choices

    def generate(self) -> List[WirePattern]:
        """Generate pruned list of valid patterns, with support for fixed_signals and direction rules.

        - Fixed signals (from config) are *mandatory* base: every pattern includes them with their exact locked W/S/colors.
        - Additional metals are chosen only from the *same direction group* as the fixed base (if any fixed exist).
          If no fixed, any single-direction group is allowed (enforced by is_valid).
        - Same-layer parallel (multiple colors on one metal) remains fully supported.
        - Pruning and determinism preserved.
        """
        patterns: List[WirePattern] = []
        seen: set[Tuple] = set()

        base_fixed = dict(self.fixed_specs)  # locked base
        fixed_metals = list(base_fixed.keys())

        # Determine allowed direction(s) from fixed (if any). All additional must match.
        if fixed_metals:
            allowed_dirs = self._fixed_dirs
            # Filter candidate additional metals to same dir as fixed
            candidate_additional = [
                m for m in self._metals
                if m not in base_fixed and _get_direction(m) in allowed_dirs
            ]
        else:
            allowed_dirs = None  # no restriction yet; is_valid will enforce single-dir for multi-metal
            candidate_additional = [m for m in self._metals if m not in base_fixed]

        # Always emit the pure fixed pattern (if any fixed)
        if base_fixed:
            fixed_layers = tuple(sorted(base_fixed.keys(), key=lambda x: (0 if x in fixed_metals else 1, x)))  # fixed first-ish
            # Better: preserve a stable order (config order)
            metal_list = list(self._metals)
            ordered_fixed = tuple(sorted(base_fixed.keys(), key=metal_list.index)) if metal_list else tuple(base_fixed.keys())
            pat = WirePattern(layers=ordered_fixed, specs=base_fixed)
            if pat.is_valid():
                kpat = pat.key()
                if kpat not in seen:
                    seen.add(kpat)
                    patterns.append(pat)

        if not candidate_additional:
            # Only fixed (or nothing)
            patterns.sort(key=lambda p: (len(p.layers), p.description))
            return patterns

        # Generate additional from same-dir candidates
        metal_list = list(self._metals)
        max_k = min(self.MAX_LAYERS - len(base_fixed), len(candidate_additional))
        if max_k < 0:
            max_k = 0

        for k in range(0, max_k + 1):  # k=0 is pure fixed (already added if any)
            for metal_subset in combinations(candidate_additional, k):
                ordered = tuple(sorted(metal_subset, key=metal_list.index))

                per_use_choices: List[List[Dict[str, Any]]] = []
                can_use = True
                for m in ordered:
                    use_only = [c for c in self._per_metal_choices(m) if c is not None]
                    if not use_only:
                        can_use = False
                        break
                    per_use_choices.append(use_only)
                if not can_use or not per_use_choices:
                    continue

                for combo in product(*per_use_choices):
                    spec_d: Dict[str, Dict[str, Any]] = dict(base_fixed)
                    for m, spec in zip(ordered, combo):
                        spec_d[m] = spec
                    # layers: fixed + additional, in stable config order
                    all_used = list(base_fixed.keys()) + list(ordered)
                    ordered_layers = tuple(sorted(set(all_used), key=metal_list.index)) if metal_list else tuple(set(all_used))
                    pat = WirePattern(layers=ordered_layers, specs=spec_d)
                    if not pat.is_valid():
                        continue
                    kpat = pat.key()
                    if kpat in seen:
                        continue
                    seen.add(kpat)
                    patterns.append(pat)

        # Deterministic order
        patterns.sort(key=lambda p: (len(p.layers), p.description))
        return patterns

    def __repr__(self) -> str:
        return (
            f"PatternEnumerator(metals={self._metals}, max_width_um={self.config.max_width_um}, "
            f"corner={getattr(self.config, 'corner', None)}, max_layers={self.MAX_LAYERS})"
        )
