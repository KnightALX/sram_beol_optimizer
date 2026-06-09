"""Unit tests for the thin argparse CLI (argument parsing + high-level flow).

Per design (Sections 3 and 9):
- --config is required
- --output-dir, --csv-override, --log-level, --no-plot, --no-report supported
- main() returns exit codes
- CLI catches BEOL errors and exits 1 with friendly messages
- build_parser() is testable independently of full execution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sram_beol.cli import build_parser, main
from sram_beol.exceptions import BEOLConfigError


# ---------------------------------------------------------------------------
# Parser tests (pure argument parsing, no side effects)
# ---------------------------------------------------------------------------

def test_build_parser_required_config():
    parser = build_parser()
    # Missing --config must fail at parse time
    with pytest.raises(SystemExit):
        parser.parse_args([])

    args = parser.parse_args(["--config", "my.yaml"])
    assert args.config == "my.yaml"
    assert args.output_dir is None
    assert args.csv_override is None
    assert args.log_level == "INFO"
    assert args.no_report is False
    assert args.no_plot is False


def test_build_parser_all_overrides_and_flags():
    parser = build_parser()
    argv = [
        "--config", "cfg.yaml",
        "--output-dir", "my_out",
        "--csv-override", "other.csv",
        "--log-level", "DEBUG",
        "--no-report",
        "--no-plot",
    ]
    args = parser.parse_args(argv)

    assert args.config == "cfg.yaml"
    assert args.output_dir == "my_out"
    assert args.csv_override == "other.csv"
    assert args.log_level == "DEBUG"
    assert args.no_report is True
    assert args.no_plot is True


def test_build_parser_short_option_for_config():
    parser = build_parser()
    args = parser.parse_args(["-c", "short.yaml"])
    assert args.config == "short.yaml"


def test_build_parser_log_level_choices():
    parser = build_parser()
    for lvl in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        args = parser.parse_args(["--config", "x.yaml", "--log-level", lvl])
        assert args.log_level == lvl

    with pytest.raises(SystemExit):
        parser.parse_args(["--config", "x.yaml", "--log-level", "TRACE"])


# ---------------------------------------------------------------------------
# main() integration-style tests via heavy patching of the layers below CLI
# ---------------------------------------------------------------------------

@patch("sram_beol.cli.load_wire_config")
@patch("sram_beol.cli.WLInterconnectOptimizer")
def test_main_happy_path_full_flow(mock_opt_class, mock_load, capsys):
    """Happy path: config loads, optimizer created, run + report + plot called, exit 0."""
    fake_cfg = MagicMock()
    mock_load.return_value = fake_cfg

    fake_opt = MagicMock()
    fake_result = MagicMock()
    fake_opt.run.return_value = fake_result
    mock_opt_class.return_value = fake_opt

    exit_code = main(["--config", "good.yaml"])

    assert exit_code == 0
    mock_load.assert_called_once_with("good.yaml", overrides=None)
    mock_opt_class.assert_called_once_with(config=fake_cfg)
    fake_opt.run.assert_called_once()
    fake_opt.generate_report.assert_called_once_with(fake_result)
    fake_opt.plot.assert_called_once_with(fake_result)

    # No error output on success
    captured = capsys.readouterr()
    assert "ERROR" not in captured.err


@patch("sram_beol.cli.load_wire_config")
@patch("sram_beol.cli.WLInterconnectOptimizer")
def test_main_with_overrides_passes_them_to_load(mock_opt_class, mock_load):
    fake_cfg = MagicMock()
    mock_load.return_value = fake_cfg
    fake_opt = MagicMock()
    fake_opt.run.return_value = MagicMock()
    mock_opt_class.return_value = fake_opt

    exit_code = main([
        "--config", "c.yaml",
        "--output-dir", "outdir",
        "--csv-override", "data.csv",
    ])

    assert exit_code == 0
    expected_overrides = {"output_dir": "outdir", "csv_path": "data.csv"}
    mock_load.assert_called_once_with("c.yaml", overrides=expected_overrides)


@patch("sram_beol.cli.load_wire_config")
@patch("sram_beol.cli.WLInterconnectOptimizer")
def test_main_no_report_no_plot_skips_calls(mock_opt_class, mock_load):
    fake_cfg = MagicMock()
    mock_load.return_value = fake_cfg
    fake_opt = MagicMock()
    fake_opt.run.return_value = MagicMock()
    mock_opt_class.return_value = fake_opt

    exit_code = main(["--config", "c.yaml", "--no-report", "--no-plot"])

    assert exit_code == 0
    fake_opt.generate_report.assert_not_called()
    fake_opt.plot.assert_not_called()


@patch("sram_beol.cli.load_wire_config")
def test_main_config_error_exits_1_and_prints_friendly(mock_load, capsys):
    mock_load.side_effect = BEOLConfigError("Missing required field 'corner'")

    exit_code = main(["--config", "bad.yaml"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR: Missing required field 'corner'" in captured.err
    assert "Hint:" in captured.err
    assert "YAML config file" in captured.err


@patch("sram_beol.cli.load_wire_config")
@patch("sram_beol.cli.WLInterconnectOptimizer")
def test_main_unexpected_exception_exits_1(mock_opt_class, mock_load, capsys):
    mock_load.return_value = MagicMock()
    mock_opt_class.side_effect = RuntimeError("something internal blew up")

    exit_code = main(["--config", "c.yaml"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Unexpected failure" in captured.err or "ERROR" in captured.err


def test_main_missing_required_config_arg_exits_nonzero():
    """Argparse itself enforces --config; main should propagate non-zero exit."""
    with pytest.raises(SystemExit) as excinfo:
        main([])  # no --config
    # argparse uses 2 for usage errors
    assert excinfo.value.code != 0


@patch("sram_beol.cli.configure_logging")
@patch("sram_beol.cli.load_wire_config")
@patch("sram_beol.cli.WLInterconnectOptimizer")
def test_main_calls_configure_logging_early(mock_opt, mock_load, mock_configure):
    """Logging setup must happen before any other work (design requirement)."""
    mock_load.return_value = MagicMock()
    mock_opt.return_value.run.return_value = MagicMock()

    main(["--config", "c.yaml", "--log-level", "DEBUG"])

    mock_configure.assert_called_once_with("DEBUG")
