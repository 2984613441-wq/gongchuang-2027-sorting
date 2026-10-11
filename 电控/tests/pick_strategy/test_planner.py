"""路径规划：不越围栏、带料退出、通道受阻、坐标换算、协议可表达性（需求四）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from conftest import det, frame

from electrical_control.pick_strategy import (
    MOVE_EXIT,
    Point,
    Refusal,
    RefusalCode,
    plan,
    select_target,
    to_commands,
)
from electrical_control.pick_strategy.config import build_config
from electrical_control.pick_strategy.geometry import (
    OPEN_SIDE_X_MAX,
    OPEN_SIDE_X_MIN,
    OPEN_SIDE_Y_MAX,
    OPEN_SIDE_Y_MIN,
    Point as GPoint,
    Rect,
    Segment,
    Tray,
    segment_crosses_side,
)

DEMO_TRAY = Rect(-95.0, 90.0, -97.5, 62.5)


def _variant_ini(config, **replaced_lines) -> Path:
    """把 demo ini 里指定的行整行换掉，写一份临时 ini（供反例/严格配置用）。

    临时文件写在**工作区内**（`tests/pick_strategy/_tmp/`）：本次会话的文件沙箱
    允许写工作区，但拒绝写系统临时目录。
    """
    keys = tuple(replaced_lines)
    out = []
    for line in Path(str(config.raw.path)).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        hit = next((k for k in keys
                    if stripped.startswith(k + " ") or stripped.startswith(k + "=")), None)
        out.append(replaced_lines[hit] if hit else line)
    tmp_dir = Path(__file__).resolve().parent / "_tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / f"variant_{abs(hash(keys)) % 100000}.ini"
    tmp.write_text("\n".join(out), encoding="utf-8")
    return tmp


def _plan_for(demo_config, detections, drop_command):
    fr = frame(1, detections)
    picked = select_target(fr, demo_config)
    assert not isinstance(picked, Refusal), picked
    return plan(picked, fr, demo_config, drop_command)


# ---------------------------------------------------------------- 退出路径
def test_exit_distance_covers_extent_and_margin(demo_config):
    """需求四.4：退出距离必须含"外沿 + 定位余量"，不能只判中心越过边缘。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    center_to_edge = demo_config.tray.to_open_edge_mm(Point(55.0, 30.0))
    extent = max(demo_config.gripper_envelope.y_mm, demo_config.item_max_size.y_mm)
    assert center_to_edge == 32.5
    assert planned.exit_distance_mm == center_to_edge + extent \
        + demo_config.exit_clearance_mm == 62.5
    assert planned.exit_distance_mm > center_to_edge + extent


def test_exit_crosses_the_open_side_only(demo_config):
    """需求四.2：带料退出必须穿过**无壁边**，不能穿围壁。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert planned.exit_point.y_mm > demo_config.tray.rect.y_max
    crossed = segment_crosses_side(
        Segment(planned.pick, planned.exit_point), demo_config.tray)
    assert crossed == demo_config.tray.open_side == OPEN_SIDE_Y_MAX


def test_segment_crosses_side_identifies_all_four_edges():
    """四条边的穿出判定（退出方向合法性的底层依赖）。"""
    tray = Tray(rect=DEMO_TRAY, open_side=OPEN_SIDE_Y_MAX,
                gap_known=True, require_gap_geometry=False)
    cases = [
        (GPoint(0.0, 0.0), GPoint(-200.0, 0.0), OPEN_SIDE_X_MIN),
        (GPoint(0.0, 0.0), GPoint(200.0, 0.0), OPEN_SIDE_X_MAX),
        (GPoint(0.0, 0.0), GPoint(0.0, -200.0), OPEN_SIDE_Y_MIN),
        (GPoint(0.0, 0.0), GPoint(0.0, 200.0), OPEN_SIDE_Y_MAX),
    ]
    for start, end, side in cases:
        assert segment_crosses_side(Segment(start, end), tray) == side


def test_open_side_may_be_overhung_but_walls_may_not():
    """无壁边不参与"越墙"判定（伸出开口是允许的）；三条有壁边必须拦住。"""
    tray = Tray(rect=DEMO_TRAY, open_side=OPEN_SIDE_Y_MAX,
                gap_known=True, require_gap_geometry=False)
    assert tray.wall_violations(Rect(30.0, 80.0, 20.0, 90.0)) == ()
    assert tray.wall_violations(Rect(30.0, 95.0, 20.0, 40.0)) == (OPEN_SIDE_X_MAX,)
    assert tray.wall_violations(Rect(-100.0, 0.0, 20.0, 40.0)) == (OPEN_SIDE_X_MIN,)
    assert tray.wall_violations(Rect(30.0, 80.0, -120.0, 40.0)) == (OPEN_SIDE_Y_MIN,)


# ---------------------------------------------------------------- 受阻
def test_traverse_stays_outside_the_tray(demo_config):
    """需求四.3：横向搬运只能在完全退出托盘之后发生。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    traverse = [s for s in planned.steps if s.name == "traverse"]
    assert traverse, "落点不在退出法线上时必须有一段横向搬运"
    seg = Segment(traverse[0].start, traverse[0].end)
    assert not seg.swept_rect(20.0).intersects_rect(demo_config.tray.rect)


def test_corridor_blocked_by_another_item_is_refused(demo_config):
    """需求一.6/四.6：带料通道上有别的物料 → 拒识本件。"""
    res = _plan_for(demo_config, [det(2, 6, 55.0, 30.0), det(4, 4, 80.0, 30.0)],
                    Point(20.0, 74.0))
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.EXIT_BLOCKED
    assert "target_seq=4" in res.detail


def test_corridor_blocked_by_object_without_box_id_is_refused(demo_config):
    """box_id 只是颜色真值；物理上挡不挡得住与颜色无关，故无 box_id 的件也拦。"""
    res = _plan_for(demo_config, [det(2, 6, 55.0, 30.0), det(4, None, 80.0, 30.0)],
                    Point(20.0, 74.0))
    assert isinstance(res, Refusal)
    assert res.code in (RefusalCode.EXIT_BLOCKED, RefusalCode.GRASP_SPACE_BLOCKED)
    assert "target_seq=4" in res.detail


def test_grasp_space_blocked_is_refused(demo_config):
    """需求四.5：夹取动作的展开空间不足 → 拒识。"""
    res = _plan_for(demo_config, [det(2, 6, 55.0, 30.0), det(4, 4, 48.0, 34.0)],
                    Point(20.0, 74.0))
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.GRASP_SPACE_BLOCKED


def test_gap_geometry_unverified_blocks_when_required(demo_config):
    """需求四.6：缝隙几何未实测时不得默认可通行（严格配置下一律拒识）。"""
    strict = build_config(_variant_ini(demo_config, require_gap_geometry=
                                       "require_gap_geometry = true   # 【演示】本用例反例"))
    assert strict.tray.require_gap_geometry is True
    res = _plan_for(strict, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.GAP_GEOMETRY_UNVERIFIED


def test_configured_obstacle_blocks_the_corridor(demo_config):
    """配置了障碍/缝隙区时，通道扫掠带压上去即拒识。"""
    assert demo_config.obstacles == ()   # demo ini 的 [Obstacle] 是注释掉的
    text = Path(str(demo_config.raw.path)).read_text(encoding="utf-8")
    text += "\n[Obstacle]\ngap = 30.0, 80.0, 50.0, 60.0   # 【演示】\n"
    tmp_dir = Path(__file__).resolve().parent / "_tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / "with_obstacle.ini"
    tmp.write_text(text, encoding="utf-8")
    cfg = build_config(tmp)
    assert len(cfg.obstacles) == 1
    res = _plan_for(cfg, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert isinstance(res, Refusal)
    assert res.code == RefusalCode.EXIT_BLOCKED
    assert "障碍" in res.detail or "缝隙" in res.detail


# ---------------------------------------------------------------- 坐标与指令
def test_plan_keeps_physical_and_carriage_frames_apart(demo_config):
    """坐标系：落点入参是**滑台记账坐标**；初始位置配置也是记账坐标。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert planned.drop_physical == Point(140.5, 117.5)     # 20−(−120.5), 74−(−43.5)
    assert planned.drop_command == Point(20.0, 74.0)
    assert planned.home_command == demo_config.home == Point(-95.0, -97.5)
    assert planned.home == Point(25.5, -54.0)


def test_commands_stay_inside_the_reachable_domain(demo_config):
    """每条下发坐标都必须在固件可达域内（X/Y 无限位开关，越界无硬件能发现）。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    commands = to_commands(planned, demo_config)
    assert not isinstance(commands, Refusal), commands
    assert [c.kind for c in commands] == \
        ["move", "grasp", "move", "move", "release", "move"]
    for cmd in commands:
        if cmd.kind == "move":
            assert demo_config.workspace.contains_point(cmd.target), cmd
    # 计划的起点是初始位置，最后一段的终点必须回到固件 HOME
    assert planned.steps[0].start == planned.home
    assert commands[-1].target == demo_config.home


# ---------------------------------------------------------------- 协议能力
def test_expressibility_verdict_lists_missing_capabilities(demo_config):
    """协议能力判定：落点不在退出法线上时现有 ITEM_TASK 表达不了，且要列出缺什么。"""
    off_ray = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert off_ray.check.expressible_with_item_task is False
    joined = " ".join(off_ray.check.missing_capabilities)
    assert "退出中间路径点" in joined
    assert "逐步完成反馈" in joined
    assert "带料/空爪状态" in joined
    assert "总时长校验" in joined

    on_ray = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(-65.5, 74.0))
    assert on_ray.check.expressible_with_item_task is True
    assert all(s.name != "traverse" for s in on_ray.steps)


def test_plan_never_produces_a_z_axis_action(demo_config):
    """需求四.7：本策略不引入 Z 轴动作（只有 move / grasp / release 三类步）。"""
    planned = _plan_for(demo_config, [det(2, 6, 55.0, 30.0)], Point(20.0, 74.0))
    assert {s.kind for s in planned.steps} <= {"move", "grasp", "release"}
    assert MOVE_EXIT in {s.name for s in planned.steps}
    for step in planned.steps:
        assert not hasattr(step, "pulse_us"), "策略层不得携带舵机脉宽"
