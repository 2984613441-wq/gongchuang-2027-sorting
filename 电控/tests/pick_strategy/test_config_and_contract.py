"""配置来源标注、现有协议能力判定、端到端离线示例。"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import DEMO_INI, REAL_INI, det, frame, make_machine, run_item

from electrical_control.pick_strategy import (
    ConfigError,
    ItemTaskExecutor,
    NotExpressible,
    Point,
    State,
    build_config,
    plan,
    select_target,
)
from electrical_control.protocol import decode_item_task_payload

RUNNER = Path(__file__).resolve().parents[2] / "deploy" / "run_pick_strategy.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_pick_strategy", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_ini(tmp_path: Path, text: str) -> Path:
    """写一份临时 ini（放在工作区内，脚本沙箱不允许写系统临时目录）。"""
    target = Path(__file__).resolve().parent / "_tmp"
    target.mkdir(exist_ok=True)
    path = target / tmp_path.name
    path.write_text(text, encoding="utf-8")
    return path


BASE_TEXT = None


def _base() -> str:
    return DEMO_INI.read_text(encoding="utf-8")


# ------------------------------------------------------------------ 配置纪律
def test_missing_source_tag_is_rejected():
    text = _base().replace(
        "x_min = -95.0      # 【固件常量】ec_motion_plan.h:94",
        "x_min = -95.0")
    with pytest.raises(ConfigError) as excinfo:
        build_config(_write_ini(Path("no_tag.ini"), text))
    assert "缺来源标签" in str(excinfo.value)


def test_unknown_source_tag_is_rejected():
    text = _base().replace(
        "x_min = -95.0      # 【固件常量】ec_motion_plan.h:94",
        "x_min = -95.0      # 【听说】")
    with pytest.raises(ConfigError) as excinfo:
        build_config(_write_ini(Path("bad_tag.ini"), text))
    assert "非法" in str(excinfo.value)


def test_contour_mode_requires_measured_object_sizes():
    """规则三.3/三.4：要按轮廓排序就必须有实测宽高；没有就 fail-closed。"""
    text = _base().replace("selection_mode = center", "selection_mode = contour")
    # demo ini 只给 box_id=4 填了尺寸 → 缺 1/2/3/5/6
    with pytest.raises(ConfigError) as excinfo:
        build_config(_write_ini(Path("contour.ini"), text))
    message = str(excinfo.value)
    assert "contour" in message and "不携带宽高或轮廓" in message


def test_home_outside_workspace_is_rejected():
    text = _base().replace("x_mm = -95.0       # 【固件常量】ec_motion_plan.h:193",
                          "x_mm = -999.0      # 【演示】越界反例")
    with pytest.raises(ConfigError) as excinfo:
        build_config(_write_ini(Path("bad_home.ini"), text))
    assert "不在 [Workspace]" in str(excinfo.value)


def test_demo_config_declares_its_unverified_params():
    config = build_config(DEMO_INI)
    # 2026-11-01：新增 [Strategy] 四项（五键排序参数），同样标【待实测】
    assert config.unverified_params() == (
        "[Tray] open_side", "[Tray] gap_known",
        "[Strategy] order_mode", "[Strategy] settle_frames",
        "[Strategy] settle_shift_mm", "[Strategy] isolation_band_mm",
    )


def test_real_config_is_fail_closed_on_gap_geometry():
    config = build_config(REAL_INI)
    assert config.tray.gap_known is False
    assert config.tray.require_gap_geometry is True
    names = config.unverified_params()
    # 🔴 2026-09-22 修正（本条自 2026-09-21 起一直红着）：原先还断言
    #   `"[Tray] open_side" in names`，但 `pick_strategy.ini:38` 早已把它改成
    #   `open_side = y_max  # 【实测】2026-09-21 用户现场确认：X 轴全部被挡住、只有 Y 正方向敞开`
    #   ⇒ 该键**已实测**，本就不该出现在"未核实清单"里 ⇒ 是**测试的期望过期**，不是配置错。
    #   本用例真正要守的是上面两条（gap_known=false + require_gap_geometry=true
    #   = 缝隙几何未实测即 fail-closed），那两条原样保留；另保留 gap_known / envelope_mm
    #   仍在清单内（它们确实是待实测项）。
    #   ⚠️ 注意 demo ini 里 open_side 仍标【待实测】（离线演示夹具的口径），
    #      故 test_demo_config_declares_its_unverified_params 的精确元组断言不动。
    assert "[Tray] gap_known" in names
    assert "[Gripper] envelope_mm" in names


# ------------------------------------------------------------------ 协议能力
def test_item_task_adapter_refuses_a_plan_it_cannot_express(demo_config):
    """协议能力判定：需要"退出中间路径点"时，现有 ITEM_TASK 表达不了 → 拒发。"""
    fr = frame(1, [det(2, 6, 55.0, 30.0)])
    picked = select_target(fr, demo_config)
    planned = plan(picked, fr, demo_config, Point(20.0, 74.0))
    executor = ItemTaskExecutor(demo_config, sink=None)
    with pytest.raises(NotExpressible) as excinfo:
        executor.build_frame(planned)
    assert "退出中间路径点" in str(excinfo.value)
    assert executor.frames == (), "拒发时不得留下任何帧"


def test_item_task_adapter_encodes_a_single_leg_plan_by_reusing_project_codec(
        demo_config):
    """可在现有协议上表达的方案：12 字节载荷，且用项目既有解码器回读一致。"""
    fr = frame(1, [det(2, 6, 55.0, 30.0)])
    picked = select_target(fr, demo_config)
    # 落点放在退出法线上 → 只剩"抓取点 + 落点"两个位置
    planned = plan(picked, fr, demo_config, Point(-65.5, 74.0))
    assert planned.check.expressible_with_item_task is True

    sent: list[bytes] = []
    executor = ItemTaskExecutor(demo_config, sink=sent.append)
    executor.execute(planned, 0)
    assert len(sent) == 1
    raw = sent[0]
    assert len(raw) == 12

    decoded = decode_item_task_payload(raw)
    assert decoded.target_seq == 2
    assert decoded.class_id == decoded.image_id == 6
    assert (decoded.x_position, decoded.y_position) == (-655, 740)      # 落点记账
    assert (decoded.pick_x_position, decoded.pick_y_position) == (-655, -135)
    assert decoded.grip_angle == 0xFF


def test_item_task_executor_only_reports_whole_program_feedback(demo_config):
    """现有协议没有逐步反馈：适配器必须如实声明粒度。"""
    executor = ItemTaskExecutor(demo_config)
    assert executor.feedback_granularity() == "whole_program"
    assert executor.poll(0.0) == [], "适配器不得自证完成（完成来自真实 MOTION_DONE）"


# ------------------------------------------------------------------ 端到端
def test_end_to_end_offline_demo_matches_the_shipped_scenario(demo_config):
    """与运行入口共用同一份演示画面，避免"文档/示例/测试三份数据"。"""
    runner = _load_runner()
    frames = runner.demo_frames("normal", demo_config)
    assert frames, "演示场景必须有画面"

    machine, executor, clock = make_machine(demo_config)
    for fr in frames:
        run_item(machine, clock, fr)

    assert machine.state is State.WAIT_FRAME
    assert machine.fault is None
    assert len(machine.item_records) == 1
    record = machine.item_records[0]
    assert record.target_seq == 2
    assert (record.steps_done, record.steps_total) == (6, 6)
    assert record.result_code == 0
    assert record.display_confirmed is True
    assert record.grasp_verified is False
    assert record.exit_distance_mm == 62.5
    assert executor.feedback_granularity() == "per_step"


def test_end_to_end_round_ends_only_after_consecutive_empty_frames(demo_config):
    runner = _load_runner()
    machine, _exec, clock = make_machine(demo_config)
    run_item(machine, clock, runner.demo_frames("normal", demo_config)[0])
    assert len(machine.item_records) == 1

    for index, fr in enumerate(runner.demo_frames("empty", demo_config)):
        # 演示数据的时间戳是 0.0、帧号从 1 开始；这里按"本件之后的新画面"重新盖戳，
        # 否则会被旧画面判据（帧号单调 + 本机接收时刻）整批丢弃。
        machine.on_frame(replace(fr, frame_id=100 + index,
                                 received_at_s=clock.now), clock.now)
    assert machine.state is State.ROUND_DONE
    assert machine.empty_streak == demo_config.empty_confirmation_frames


def test_every_step_needs_a_completion_feedback_event(demo_config):
    """需求五.5：不喂完成反馈时，状态机一步都不许自己往前走。"""
    machine, _exec, clock = make_machine(demo_config)
    machine.on_frame(frame(1, [det(2, 6, 55.0, 30.0)]), clock.now)
    assert machine.state is State.MOVING_EMPTY
    for _ in range(50):
        clock.advance(0.01)
        machine.tick(clock.now)
    assert machine.state is State.MOVING_EMPTY, "没有完成反馈就不得进入下一步"
