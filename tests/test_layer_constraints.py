"""Tests for LayerConstraint dataclass and WireConfig.layer_constraints integration.

覆盖：
- LayerConstraint 自身行为 (resolve / 默认值 / None 处理)
- LayerConstraint 边界条件 (min > max 校验)
"""

from __future__ import annotations

import math
import pytest

from sram_beol.config import LayerConstraint
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