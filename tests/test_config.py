"""Unit tests for WireConfig dataclass, YAML loading, validation, and overrides.

Covers design requirements from Sections 2 and 3 (Config part):
- Load from YAML into frozen WireConfig
- All required fields
- Validation of types, ranges, non-negative
- Overrides (for thin CLI)
- Clear BEOLConfigError on problems
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from sram_beol.config import WireConfig, load_wire_config, configure_logging
from sram_beol.exceptions import BEOLConfigError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "test_config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


VALID_MINIMAL = {
    "csv_path": "backmodel.csv",
    "corner": "typical",
    "length_um": 20.0,
    "metals": ["M3", "M4"],
    "max_width_um": 0.04,
    "segment_um": 1.0,
    "via_pitch_um": 0.5,
    "driver_r_ohm": 80.0,
    "device_r_ohm": 45.0,
    "device_c_ff": 0.35,
    "via_r_ohm": 8.0,
    "output_dir": "results",
}


# ---------------------------------------------------------------------------
# WireConfig direct construction + validation
# ---------------------------------------------------------------------------

def test_wireconfig_valid_construction():
    cfg = WireConfig(**VALID_MINIMAL)
    assert cfg.corner == "typical"
    assert cfg.length_um == 20.0
    assert cfg.metals == ["M3", "M4"]
    assert cfg.output_dir == "results"
    # repr should be useful and not explode
    r = repr(cfg)
    assert "WireConfig" in r and "typical" in r


def test_wireconfig_is_frozen():
    cfg = WireConfig(**VALID_MINIMAL)
    with pytest.raises(Exception) as exc:  # dataclasses.FrozenInstanceError
        cfg.length_um = 99.0  # type: ignore[misc]
    assert "frozen" in str(exc.value).lower() or "cannot assign" in str(exc.value).lower()


def test_wireconfig_validation_negative_values():
    bad = dict(VALID_MINIMAL)
    bad["length_um"] = -5
    with pytest.raises(BEOLConfigError) as exc:
        WireConfig(**bad)
    assert "length_um" in str(exc.value)
    assert "positive" in str(exc.value).lower()


def test_wireconfig_validation_zero_value():
    bad = dict(VALID_MINIMAL)
    bad["via_pitch_um"] = 0.0
    with pytest.raises(BEOLConfigError) as exc:
        WireConfig(**bad)
    assert "via_pitch_um" in str(exc.value)


def test_wireconfig_validation_empty_metals():
    bad = dict(VALID_MINIMAL)
    bad["metals"] = []
    with pytest.raises(BEOLConfigError) as exc:
        WireConfig(**bad)
    assert "metals" in str(exc.value).lower()


def test_wireconfig_validation_bad_metals_type():
    bad = dict(VALID_MINIMAL)
    bad["metals"] = "M3,M4"  # wrong type
    with pytest.raises(BEOLConfigError) as exc:
        WireConfig(**bad)
    assert "list" in str(exc.value).lower()


def test_wireconfig_validation_missing_csv_path():
    bad = dict(VALID_MINIMAL)
    del bad["csv_path"]
    # When constructing directly the dataclass will raise TypeError, but we test via loader mostly
    with pytest.raises(TypeError):
        WireConfig(**bad)


# ---------------------------------------------------------------------------
# load_wire_config from file + validation + overrides
# ---------------------------------------------------------------------------

def test_load_wire_config_success(tmp_path: Path):
    yml = _write_yaml(tmp_path, VALID_MINIMAL)
    cfg = load_wire_config(yml)
    assert isinstance(cfg, WireConfig)
    assert cfg.csv_path == "backmodel.csv"
    assert cfg.corner == "typical"


def test_load_wire_config_from_str_path(tmp_path: Path):
    yml = _write_yaml(tmp_path, VALID_MINIMAL)
    cfg = load_wire_config(str(yml))
    assert cfg.length_um == 20.0


def test_load_wire_config_file_not_found():
    with pytest.raises(BEOLConfigError) as exc:
        load_wire_config("this_file_does_not_exist_12345.yaml")
    assert "not found" in str(exc.value).lower()


def test_load_wire_config_missing_required_field(tmp_path: Path):
    incomplete = {"csv_path": "x.csv", "corner": "tt", "length_um": 10.0}
    yml = _write_yaml(tmp_path, incomplete)
    with pytest.raises(BEOLConfigError) as exc:
        load_wire_config(yml)
    msg = str(exc.value)
    assert "Missing required field" in msg
    assert "max_width_um" in msg or "metals" in msg


def test_load_wire_config_bad_yaml(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("csv_path: [unbalanced: bracket", encoding="utf-8")
    with pytest.raises(BEOLConfigError) as exc:
        load_wire_config(bad)
    assert "yaml" in str(exc.value).lower() or "parse" in str(exc.value).lower()


def test_load_wire_config_overrides(tmp_path: Path):
    yml = _write_yaml(tmp_path, VALID_MINIMAL)
    cfg = load_wire_config(
        yml,
        overrides={
            "output_dir": "custom_out",
            "csv_path": "overridden.csv",
            "length_um": 42.5,  # also test numeric override
        },
    )
    assert cfg.output_dir == "custom_out"
    assert cfg.csv_path == "overridden.csv"
    assert cfg.length_um == 42.5
    # other fields unchanged
    assert cfg.corner == "typical"


def test_load_wire_config_override_does_not_bypass_validation(tmp_path: Path):
    yml = _write_yaml(tmp_path, VALID_MINIMAL)
    with pytest.raises(BEOLConfigError) as exc:
        load_wire_config(yml, overrides={"segment_um": -1.0})
    assert "segment_um" in str(exc.value)


def test_load_wire_config_non_dict_top_level(tmp_path: Path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(BEOLConfigError) as exc:
        load_wire_config(bad)
    assert "mapping" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

def test_configure_logging_basic():
    # Should not raise and should accept standard levels
    configure_logging("DEBUG")
    configure_logging("INFO")
    # reconfigure is supported
    configure_logging("WARNING")


def test_configure_logging_invalid_level():
    with pytest.raises(BEOLConfigError) as exc:
        configure_logging("NOTALEVEL")
    assert "invalid log level" in str(exc.value).lower()
