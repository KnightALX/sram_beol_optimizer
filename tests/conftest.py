"""
Pytest fixtures for sram_beol tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sram_beol.config import WireConfig


@pytest.fixture(scope="session")
def sample_csv_path() -> Path:
    # Use the committed sample
    p = Path(__file__).parent.parent / "samples" / "beol_sample.csv"
    assert p.exists(), f"Sample CSV missing at {p}"
    return p


@pytest.fixture(scope="session")
def sample_config_path() -> Path:
    p = Path(__file__).parent.parent / "samples" / "config_small.yaml"
    assert p.exists()
    return p


@pytest.fixture
def small_config(sample_csv_path: Path, tmp_path: Path) -> WireConfig:
    """Small config suitable for fast integration tests."""
    cfg = WireConfig.from_dict({
        "csv_path": str(sample_csv_path),
        "corner": "typical",
        "length_um": 8.0,   # smaller for speed in tests
        "metals": ["M3", "M4"],
        "max_width_um": 0.040,
        "segment_um": 2.0,
        "via_pitch_um": 1.0,
        "driver_r_ohm": 80.0,
        "device_r_ohm": 45.0,
        "device_c_ff": 0.35,
        "via_r_ohm": 8.0,
        "output_dir": str(tmp_path / "results_test"),
        "max_patterns": 80,
    })
    return cfg
