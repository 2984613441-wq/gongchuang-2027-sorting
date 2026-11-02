"""三套策略预设的自检（2026-11-02）。

用户口径：三套方案（原来的 / 权重的 / 放弃的）都要测试、参数都要填好。
本文件保证三份预设 ini **能解析、语义正确**（防止现场改坏 ini 导致链退回默认口径）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from electrical_control.pick_strategy.config import build_config

_PRESET_DIR = Path(__file__).resolve().parents[2] / "deploy" / "presets"

PRESETS = {
    "planA_legacy": dict(order_mode="group", skip=(), guard=True),
    "planB_weighted": dict(order_mode="weighted", skip=(), guard=True),
    "planC_skip": dict(order_mode="weighted", skip=(3, 5), guard=True),
}


@pytest.mark.parametrize("name,expect", sorted(PRESETS.items()))
def test_preset_parses_and_matches_intent(name, expect):
    path = _PRESET_DIR / ("pick_strategy.%s.ini" % name)
    assert path.exists(), "预设缺失：%s" % path
    cfg = build_config(path)
    assert cfg.order_mode == expect["order_mode"]
    assert cfg.skip_shapes == expect["skip"]
    assert cfg.weighted_guard_hard_first == expect["guard"]


def test_all_presets_exist():
    missing = [n for n in PRESETS
               if not (_PRESET_DIR / ("pick_strategy.%s.ini" % n)).exists()]
    assert not missing, "缺预设：%s" % missing


def test_presets_share_geometry_sections():
    """三套只应在 [Strategy] 上有差异（几何/托盘/工具偏移必须一致）。"""
    cfgs = {}
    for name in PRESETS:
        cfgs[name] = build_config(_PRESET_DIR / ("pick_strategy.%s.ini" % name))
    ref = cfgs["planA_legacy"]
    for name, cfg in cfgs.items():
        assert cfg.home == ref.home, name
        assert cfg.tool_offset == ref.tool_offset, name
        assert cfg.workspace.x_min == ref.workspace.x_min, name
        assert cfg.tray.open_side == ref.tray.open_side, name
