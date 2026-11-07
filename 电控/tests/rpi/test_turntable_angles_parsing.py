"""`[TurntableAngles]` 两种写法的解析（2026-11-07 定稿：推荐 pos:NNNN）。

规则（用户 2026-11-07 定稿）：
* `1 = pos:2048` ⇒ 原始位置值 0~4095（360° 六格的正路）；
* `1 = -112.5`  ⇒ 旧口径：角度（270° 旧模板仍可用）；
* **同一段禁止混用**（混用即 SystemExit，fail-closed）；
* 缺任一格 / pos 越界 / pos 非整数 ⇒ SystemExit。
"""

from __future__ import annotations

import configparser

import pytest

from electrical_control.rpi.drop_strategy import TurntableStrategy, load_strategy_from_cfg

HEAD = """[TurntableAngles]
turntable_drop_point = 88.0, 90.0
"""
POS_SIX = """1 = pos:2048
2 = pos:1365
3 = pos:683
4 = pos:0
5 = pos:3413
6 = pos:2731
"""
ANGLE_SIX = """1 = -112.5
2 = -67.5
3 = -22.5
4 = 22.5
5 = 67.5
6 = 112.5
"""


def _load(body: str) -> TurntableStrategy:
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    cfg.read_string(HEAD + body)
    strat = load_strategy_from_cfg(cfg, "<test>")
    assert isinstance(strat, TurntableStrategy)
    return strat


def test_pos_table_parsed_and_preferred():
    strat = _load(POS_SIX)
    assert strat.uses_position_domain() is True
    assert strat.pos_table == {1: 2048, 2: 1365, 3: 683, 4: 0, 5: 3413, 6: 2731}
    assert strat.angle_table == {}, "pos: 口径不应产出角度表"
    assert strat.get_position(4) == 0
    assert strat.get_drop_point(1) == (880, 900)


def test_pos_prefix_is_case_insensitive_and_allows_space():
    strat = _load(
        "1 = POS: 2048\n2 = pos:1365\n3 = pos:683\n4 = pos:0\n5 = pos:3413\n6 = pos:2731\n"
    )
    assert strat.pos_table[1] == 2048


def test_legacy_angle_table_still_works():
    strat = _load(ANGLE_SIX)
    assert strat.uses_position_domain() is False
    assert strat.pos_table == {}
    assert strat.angle_table[6] == 112.5
    assert strat.get_position(1) is None


def test_mixing_pos_and_angle_is_rejected():
    body = "1 = pos:2048\n" + "\n".join(ANGLE_SIX.splitlines()[1:]) + "\n"
    with pytest.raises(SystemExit) as exc:
        _load(body)
    assert "混用" in str(exc.value)


def test_missing_box_is_rejected():
    body = "\n".join(POS_SIX.splitlines()[:5]) + "\n"   # 缺第 6 格
    with pytest.raises(SystemExit) as exc:
        _load(body)
    assert "缺货格" in str(exc.value)


def test_pos_out_of_range_is_rejected():
    body = POS_SIX.replace("6 = pos:2731", "6 = pos:4096")
    with pytest.raises(SystemExit) as exc:
        _load(body)
    assert "越界" in str(exc.value)


def test_pos_non_integer_is_rejected():
    body = POS_SIX.replace("6 = pos:2731", "6 = pos:两七三一")
    with pytest.raises(SystemExit) as exc:
        _load(body)
    assert "格式错误" in str(exc.value)


def test_angle_out_of_range_without_pos_prefix_is_rejected():
    """复核建议 1：漏写 pos: 的纯数字（|值|>360）必须提前拒，不能当"角度 2048°"。"""
    body = ANGLE_SIX.replace("6 = 112.5", "6 = 2048")
    with pytest.raises(SystemExit) as exc:
        _load(body)
    assert "pos:NNNN" in str(exc.value)


def test_unknown_box_key_ignored():
    """9 = ... 这类表外键仍按既有行为跳过（不参与完整性检查）。"""
    strat = _load(POS_SIX + "9 = pos:100\n")
    assert strat.pos_table.keys() == set(range(1, 7))
