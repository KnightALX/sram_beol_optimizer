"""
WLInterconnectOptimizer and OptimizationResult.

Full orchestration per design Section 7:
DB → Enumerator → Evaluator loop → Pareto (far delay vs total_width_sum) → best_far_end + best_avg extraction.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import WireConfig
from .db import BEOLModelDB
from .evaluator import ElmoreLadderEvaluator
# EvaluationResult alias for type hints / older references (evaluate actually returns dict[str,Any] today)
from typing import Any as _Any, Dict as _Dict
EvaluationResult = _Dict[str, _Any]
from .exceptions import BEOLConfigError, BEOLRuntimeError
from .pattern import PatternEnumerator, WirePattern

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """
    Commercial-grade result container.

    - all_records: list of dicts (one per evaluated pattern) with keys:
        description, far_prop, avg_prop, far_tau, avg_tau, near_*, total_width_sum,
        metal_count, equiv_r_per_um, equiv_c_per_um, is_pareto, pareto_rank (or None),
        per_device_*, device_positions_um, etc.
    - pareto_front: sorted subset of records on the Pareto (by increasing total_width_sum)
    - best_far_end: the record achieving minimal far_prop (highlighted)
    - best_avg: record achieving minimal avg_prop (highlighted)
    - summary: num_patterns, elapsed_s, best values, config snapshot, etc.
    """
    config: WireConfig
    all_records: List[Dict[str, Any]]
    pareto_front: List[Dict[str, Any]]
    best_far_end: Dict[str, Any]
    best_avg: Dict[str, Any]
    summary: Dict[str, Any] = field(default_factory=dict)

    def get_record_by_description(self, desc: str) -> Optional[Dict[str, Any]]:
        for r in self.all_records:
            if r.get("description") == desc:
                return r
        return None


class WLInterconnectOptimizer:
    """
    Main orchestrator class.

    Usage:
        opt = WLInterconnectOptimizer(config_path="samples/config_small.yaml")
        result = opt.run()
        opt.generate_report(result)  # if report wired
        opt.plot(result)
    """

    def __init__(
        self,
        config_path: Optional[str | Path] = None,
        config: Optional[WireConfig] = None,
        db: Optional[BEOLModelDB] = None,
        evaluator: Optional[ElmoreLadderEvaluator] = None,
    ):
        if config is not None:
            self.config = config
        elif config_path is not None:
            self.config = WireConfig.from_yaml(config_path)
        else:
            raise BEOLConfigError("Must provide either config_path or config object")

        self._db = db
        self._evaluator = evaluator
        self._output_dir: Optional[Path] = None

        # Lazily created on run()
        self._logger = logging.getLogger("sram_beol.optimizer")

    @property
    def db(self) -> BEOLModelDB:
        if self._db is None:
            csv_path = self.config.resolve_csv_path()
            self._db = BEOLModelDB(csv_path, config=self.config)
        return self._db

    @property
    def evaluator(self) -> ElmoreLadderEvaluator:
        if self._evaluator is None:
            self._evaluator = ElmoreLadderEvaluator(self.config, self.db)
        return self._evaluator

    def _ensure_output(self) -> Path:
        if self._output_dir is None:
            self._output_dir = self.config.ensure_output_dir()
        return self._output_dir

    def run(self) -> OptimizationResult:
        """Execute full optimization flow. Returns OptimizationResult."""
        t0 = time.perf_counter()
        logger.info("Starting WLInterconnectOptimizer run")
        logger.info("Config: %s", self.config)

        # 1. DB + corner validation (uses metals from config)
        db = self.db
        db.validate_corner(self.config.corner, structures=self.config.metals)

        # 2. Enumerator
        enumerator = PatternEnumerator(self.config, db)
        patterns: List[WirePattern] = enumerator.generate()
        if not patterns:
            raise BEOLRuntimeError("No valid patterns generated. Check metals, max_width, CSV data.")

        logger.info("Evaluating %d patterns...", len(patterns))

        # 3. Evaluate all
        evaluator = self.evaluator
        records: List[Dict[str, Any]] = []
        for i, pat in enumerate(patterns):
            ev = evaluator.evaluate(pat)  # returns dict (see ElmoreLadderEvaluator.evaluate)
            rec = {
                "description": ev["description"],
                "far_tau": ev["far_tau_ps"],  # note: keys in current evaluator are *_ps
                "near_tau": ev["near_tau_ps"],
                "avg_tau": ev["avg_tau_ps"],
                "far_prop": ev["far_prop_ps"],
                "near_prop": ev["near_prop_ps"],
                "avg_prop": ev["avg_prop_ps"],
                "equiv_r_per_um": ev["equiv_r_per_um"],
                "equiv_c_per_um": ev["equiv_c_per_um"],
                "total_width_sum": ev["total_metal_width_sum"],
                "metal_count": ev["metal_count"],
                "per_device_tau": ev["per_device_tau_ps"],
                "per_device_prop": ev["per_device_prop_ps"],
                "device_positions_um": None,  # not provided by current evaluator; report/plot can compute
                "pattern_layers": pat.layers,
                # placeholders for pareto info
                "is_pareto": False,
                "pareto_rank": None,
            }
            records.append(rec)
            if (i + 1) % 50 == 0 or i == len(patterns) - 1:
                logger.debug("Evaluated %d/%d", i + 1, len(patterns))

        # 4. Pareto on the two user objectives: far_end_delay and avg_end_delay (both to minimize).
        # total_width_sum kept only as informational (area/power proxy).
        pareto_records = self._compute_pareto_front(records, delay_key="far_prop", cost_key="avg_prop")

        # Mark in all_records
        pareto_descs = {r["description"] for r in pareto_records}
        for rec in records:
            rec["is_pareto"] = rec["description"] in pareto_descs

        # Assign simple pareto rank (0 = on front, higher = dominated layers) - for report we just use is_pareto + sort
        # For now, set rank=None or front order index for those on front
        for idx, pr in enumerate(pareto_records):
            for rec in records:
                if rec["description"] == pr["description"]:
                    rec["pareto_rank"] = idx

        # 5. Identify the two special points (even if not on Pareto)
        if not records:
            raise BEOLRuntimeError("No records after evaluation")

        best_far = min(records, key=lambda r: r["far_prop"])
        best_avg = min(records, key=lambda r: r["avg_prop"])

        # 6. Summary
        elapsed = time.perf_counter() - t0
        summary = {
            "num_patterns_evaluated": len(records),
            "num_pareto_points": len(pareto_records),
            "elapsed_seconds": round(elapsed, 3),
            "min_far_prop": best_far["far_prop"],
            "min_avg_prop": best_avg["avg_prop"],
            "best_far_description": best_far["description"],
            "best_avg_description": best_avg["description"],
            "config_snapshot": self.config.to_dict(),
        }

        result = OptimizationResult(
            config=self.config,
            all_records=records,
            pareto_front=pareto_records,
            best_far_end=best_far,
            best_avg=best_avg,
            summary=summary,
        )

        logger.info(
            "Optimization complete: %d patterns, %d on Pareto, best_far=%s (far_prop=%.4f), "
            "best_avg=%s (avg_prop=%.4f), time=%.3fs",
            len(records), len(pareto_records),
            best_far["description"], best_far["far_prop"],
            best_avg["description"], best_avg["avg_prop"],
            elapsed,
        )
        return result

    @staticmethod
    def _compute_pareto_front(
        records: List[Dict[str, Any]],
        delay_key: str = "far_prop",
        cost_key: str = "avg_prop",
    ) -> List[Dict[str, Any]]:
        """
        Simple non-dominated sort for the two user objectives (far_end_delay and avg_end_delay, both minimized).
        "cost_key" here is the second delay objective (avg_prop by default).
        total_width_sum is kept in records for informational purposes only.
        Returns the front sorted by increasing cost_key (i.e., avg delay).
        """
        front: List[Dict[str, Any]] = []
        for p in records:
            dominated = False
            for q in records:
                if q is p:
                    continue
                p_del = p[delay_key]
                p_c = p[cost_key]
                q_del = q[delay_key]
                q_c = q[cost_key]
                if (q_del <= p_del and q_c <= p_c) and (q_del < p_del or q_c < p_c):
                    dominated = True
                    break
            if not dominated:
                front.append(p)

        # Sort front by cost asc, then delay asc for determinism
        front.sort(key=lambda r: (r[cost_key], r[delay_key]))
        return front

    # The following two are thin facades; real impl in report/plot modules (injected or imported)
    def generate_report(self, result: OptimizationResult, output_dir: Optional[str | Path] = None) -> Path:
        """Delegate to ReportGenerator. Lazy import to avoid circulars."""
        from .report import ReportGenerator

        out = Path(output_dir) if output_dir else self._ensure_output()
        rg = ReportGenerator(out)
        return rg.write(result, config=self.config)

    def plot(self, result: OptimizationResult, output_dir: Optional[str | Path] = None) -> List[Path]:
        """Delegate to Plotter."""
        from .plot import Plotter

        out = Path(output_dir) if output_dir else self._ensure_output()
        pl = Plotter(out)
        return pl.generate_all(result, config=self.config)
