"""Tests for LayerConstraint dataclass and WireConfig.layer_constraints integration.

覆盖：
- LayerConstraint 自身行为 (resolve / 默认值 / None 处理)
- LayerConstraint 边界条件 (min > max 校验)
"""

from __future__ import annotations

import math
import pytest

from sram_beol.config import LayerConstraint, WireConfig, load_wire_config
from sram_beol.exceptions import BEOLConfigError


class TestLayerConstraintResolve:
    """LayerConstraint.resolve() 与全局 fallback 的交互。"""

    def test_empty_constraint_uses_global_fallback(self):
        """空 LayerConstraint() -> resolve 到 (0.0, global_max, 0.0, inf)。"""
        lc = LayerConstraint(metal="M5")
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0
        assert max_w == 0.060
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_partial_override_only_max_width(self):
        """只设 max_width_um -> min_w 用 0.0, max_w 用用户值。"""
        lc = LayerConstraint(metal="M5", max_width_um=0.070)
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0
        assert max_w == 0.070
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_partial_override_only_min_width(self):
        """只设 min_width_um -> max_w 仍用全局 fallback。"""
        lc = LayerConstraint(metal="M5", min_width_um=0.040)
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.040
        assert max_w == 0.060
        assert min_s == 0.0
        assert math.isinf(max_s)

    def test_full_override_returns_user_values(self):
        """全部 4 个字段都设 -> resolve 返回用户值不变。"""
        lc = LayerConstraint(
            metal="M5",
            min_width_um=0.040,
            max_width_um=0.070,
            min_space_um=0.060,
            max_space_um=0.100,
        )
        min_w, max_w, min_s, max_s = lc.resolve(fallback_max_width_um=0.060)
        assert (min_w, max_w, min_s, max_s) == (0.040, 0.070, 0.060, 0.100)

    def test_explicit_zero_min_width_preserved(self):
        """显式设 min_width_um=0.0 必须保留, 不可被 falsy 转 fallback。"""
        lc = LayerConstraint(metal="M5", min_width_um=0.0)
        min_w, _, _, _ = lc.resolve(fallback_max_width_um=0.060)
        assert min_w == 0.0

    def test_frozen_dataclass(self):
        """frozen: 字段不可变。"""
        lc = LayerConstraint(metal="M5", max_width_um=0.070)
        with pytest.raises(Exception):
            lc.max_width_um = 0.080


class TestWireConfigLayerConstraints:
    """WireConfig 与 layer_constraints 字段的集成测试。"""

    def _base_kwargs(self, **overrides):
        """Build valid kwargs; layer_constraints overrides via param."""
        base = dict(
            csv_path="dummy.csv",
            corner="typical",
            length_um=20.0,
            metals=["M1", "M2", "M3", "M4", "M5"],
            max_width_um=0.060,
            segment_um=1.0,
            via_pitch_um=0.5,
            driver_r_ohm=80.0,
            device_r_ohm=45.0,
            device_c_ff=0.35,
            via_r_ohm=8.0,
            output_dir="results",
        )
        base.update(overrides)
        return base

    def test_default_layer_constraints_is_empty_dict(self):
        """未传 layer_constraints -> 默认 {}。"""
        cfg = WireConfig(**self._base_kwargs())
        assert cfg.layer_constraints == {}

    def test_layer_constraints_parsed_from_dict(self):
        """从 dict 构造 layer_constraints 字段被正确解析。"""
        cfg = WireConfig(
            **self._base_kwargs(
                layer_constraints={
                    "M5": LayerConstraint(
                        metal="M5", min_width_um=0.040, max_width_um=0.070
                    )
                }
            )
        )
        assert "M5" in cfg.layer_constraints
        assert cfg.layer_constraints["M5"].max_width_um == 0.070

    def test_layer_constraint_metal_not_in_metals_raises(self):
        """layer_constraints 引用 metals 列表外的 metal -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="layer_constraints references metal M9"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M9": LayerConstraint(metal="M9", max_width_um=0.080)
                    }
                )
            )

    def test_min_width_exceeds_max_width_raises(self):
        """min > max -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="min_width_um"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(
                            metal="M5", min_width_um=0.080, max_width_um=0.040
                        )
                    }
                )
            )

    def test_min_space_exceeds_max_space_raises(self):
        """min_space > max_space -> BEOLConfigError。"""
        with pytest.raises(BEOLConfigError, match="min_space_um"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(
                            metal="M5", min_space_um=0.10, max_space_um=0.06
                        )
                    }
                )
            )

    def test_negative_width_raises(self):
        """min_width_um = -0.01 -> BEOLConfigError (>= 0)。"""
        with pytest.raises(BEOLConfigError, match="must be >= 0"):
            WireConfig(
                **self._base_kwargs(
                    layer_constraints={
                        "M5": LayerConstraint(metal="M5", min_width_um=-0.01)
                    }
                )
            )