"""Thin argparse CLI for the SRAM BEOL Interconnect Optimizer.

Design requirements (Sections 3, 9):
- argparse is intentionally thin.
- Primary / full configuration always comes from YAML.
- Only a few overrides and control flags on the command line:
    --config (REQUIRED)
    --output-dir (override)
    --csv-override (debug / experimentation)
    --log-level
    --no-plot
    --no-report
- The CLI sets up stdlib logging, loads config (with overrides), instantiates
  WLInterconnectOptimizer, calls run(), then conditionally generate_report / plot.
- Top-level errors are caught, friendly messages printed to stderr, exit code 1.

Console script entry point (from pyproject.toml):
    sram-beol-optimizer = "sram_beol.cli:main"

Users can also do:
    python -m sram_beol.cli --config ...
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from .config import configure_logging, load_wire_config
from .exceptions import BEOLBaseError
from .optimizer import WLInterconnectOptimizer

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct the thin command-line parser exactly as specified in the design.

    This function is public for unit testing of argument parsing (no side effects).
    """
    parser = argparse.ArgumentParser(
        prog="sram-beol-optimizer",
        description=(
            "SRAM BEOL Interconnect Optimizer\n\n"
            "Finds optimal multi-layer wire patterns (width/space/color) for long\n"
            "WordLine interconnects (>20um) in SRAM BEOL to minimize Elmore delay.\n"
            "YAML is the primary configuration source."
        ),
        epilog=(
            "Example: sram-beol-optimizer --config my_config.yaml --log-level DEBUG\n"
            "See the design document and README for full YAML schema and Python API."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        add_help=True,
    )

    parser.add_argument(
        "--config",
        "-c",
        required=True,
        metavar="PATH",
        help="Path to the YAML configuration file (required; source of truth).",
    )

    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Override the output directory (default and full spec come from YAML).",
    )

    parser.add_argument(
        "--csv-override",
        metavar="PATH",
        default=None,
        help=(
            "Debug override for the BEOL model CSV path. "
            "Replaces csv_path from YAML (useful for testing different corners/models)."
        ),
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python stdlib logging level for the sram_beol package.",
    )

    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Disable generation of report.md and accompanying CSV table.",
    )

    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Disable generation of all PNG diagnostic and proof plots.",
    )

    # P1-4: 默认不启动 dashboard，避免批处理被阻塞；显式 --dashboard 才开启。
    # P1-4: dashboard is OFF by default to avoid blocking batch/CI runs; opt-in via --dashboard.
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help=(
            "Launch the interactive Dash dashboard after the run (default: OFF). "
            "The dashboard opens a blocking web server on http://localhost:8050 "
            "and waits for Ctrl+C, so disable it (or pass --no-dashboard) for "
            "batch / CI / pipelines scenarios."
        ),
    )

    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help=(
            "Explicitly disable dashboard launch (this is also the default). "
            "Provided for symmetry / scripting. Use --dashboard to opt in."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Primary CLI entry point.

    Args:
        argv: Optional argument list (for testing / subprocess). If None, uses sys.argv[1:].

    Returns:
        Process exit code (0 success, 1 on any BEOL error or unexpected failure).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging as early as possible (design requirement)
    configure_logging(args.log_level)

    logger.info("sram-beol-optimizer starting")
    logger.debug(f"CLI args: config={args.config}, output_dir={args.output_dir}, "
                 f"csv_override={args.csv_override}, log_level={args.log_level}, "
                 f"no_report={args.no_report}, no_plot={args.no_plot}")

    try:
        # Build overrides dict for thin integration with config loader
        overrides: dict[str, Any] = {}
        if args.output_dir is not None:
            overrides["output_dir"] = args.output_dir
        if args.csv_override is not None:
            overrides["csv_path"] = args.csv_override

        # Load (YAML + overrides) -> validated immutable config
        cfg = load_wire_config(args.config, overrides=overrides or None)

        # Create optimizer (public API path)
        opt = WLInterconnectOptimizer(config=cfg)

        # Execute (skeleton today, full flow later)
        result = opt.run()

        # Reporting / plotting controlled by CLI flags (design: --no-plot / --no-report)
        if not args.no_report:
            opt.generate_report(result)
        else:
            logger.info("Report generation skipped (--no-report)")

        if not args.no_plot:
            opt.plot(result)
        else:
            logger.info("Plot generation skipped (--no-plot)")

        # Dashboard launch (P1-4: 默认关闭；显式 --dashboard 才开启)。
        # Dashboard launch (P1-4: OFF by default; opt-in via --dashboard).
        if args.dashboard and not args.no_dashboard:
            opt.launch_dashboard(result)
        else:
            logger.info("Dashboard skipped (default behavior; pass --dashboard to launch)")

        logger.info("sram-beol-optimizer completed successfully")
        return 0

    except BEOLBaseError as exc:
        # Design requirement: dedicated errors, CLI catches top level,
        # prints friendly message to stderr, and exits 1.
        logger.error(f"BEOL error: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "Hint: Verify your YAML config file (all required fields present, "
            "positive values, corner exactly matches CSV). "
            "See design document Section 3 for the schema.",
            file=sys.stderr,
        )
        return 1

    except FileNotFoundError as exc:
        logger.error(f"File not found: {exc}")
        print(f"ERROR: File not found - {exc}", file=sys.stderr)
        return 1

    except Exception as exc:
        # Unexpected: still exit 1, but show traceback at DEBUG level
        logger.exception("Unexpected internal error in CLI")
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        print("Run with --log-level DEBUG for more details.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
