#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夹取策略离线运行入口。

用途
----
用**离线模拟执行器**把"一件一轮"的完整流程跑一遍，打印：
  ① 参数来源清单（哪些是实测、哪些是演示、哪些还没实测）
  ② 锁定的是哪一件、为什么是它（到无壁边的距离 / 并列时的定序）
  ③ 完整路径（空爪平移 → 夹取 → 垂直退出 → 横搬 → 松爪 → 回位）
  ④ 化成"滑台记账坐标"的指令序列
  ⑤ 逐步事件日志与本件记录（含"夹持未证实"的标注）

它**不会**打开串口、不会连相机、不会驱动任何实物。`--executor item_task`
只把计划映射成现有 ITEM_TASK 的 12 字节载荷并打印十六进制（除非你显式注入
sink），不发送。

用法示例
--------
    # 离线端到端示例（演示配置）
    python3 电控/deploy/run_pick_strategy.py \
        --config 电控/deploy/pick_strategy.demo.ini --scenario normal

    # 现有 ITEM_TASK 能否表达这份计划？
    python3 电控/deploy/run_pick_strategy.py --executor item_task

    # 故障分支演示
    python3 电控/deploy/run_pick_strategy.py --scenario timeout

退出码
------
0 = 场景按预期完成；2 = 配置错误；3 = --strict 下有未实测参数；4 = 现有协议表达不了
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许"直接跑本文件"（不依赖外部 PYTHONPATH）。
# 电控/deploy/run_pick_strategy.py → parent.parent = 电控 → /src
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from electrical_control.pick_strategy import (  # noqa: E402
    ConfigError,
    Detection,
    FaultCode,
    ItemTaskExecutor,
    NotExpressible,
    Point,
    Refusal,
    SimExecutor,
    State,
    VirtualClock,
    VisionFrame,
    build_config,
    describe_selection_limitation,
    drive_until_settled,
    PickStrategyMachine,
    plan,
    select_target,
    to_commands,
)

DEFAULT_CONFIG = Path(__file__).with_name("pick_strategy.demo.ini")

# ---- 演示画面（全部是【演示】数据，不是现场识别结果）----
# 托盘演示域：x∈[-95,90], y∈[-97.5,62.5]；无壁边 = y_max（上边）。
DEMO_FRAME_NORMAL = (
    Detection(1, box_id=3, class_id=3, x_mm=-20.0, y_mm=20.0, confidence=88),
    Detection(2, box_id=6, class_id=6, x_mm=55.0, y_mm=30.0, confidence=91),
    Detection(3, box_id=2, class_id=2, x_mm=40.0, y_mm=-60.0, confidence=80),
)

# 每个场景"本来应该出现什么"——用来把离线示例变成自检示例。
# 形式：场景 -> (结束形态, 附加核对项)。结束形态 ∈ item / no_plan / fault / round_done。
SCENARIO_EXPECT: dict[str, tuple[str, dict]] = {
    # 正常一件：锁定离无壁边最近的那件并按完整流程走完
    "normal": ("item", {"picked_target_seq": 2}),
    # 落点恰好在退出法线上 → 现有 ITEM_TASK 可以表达（退出即投送）
    "onray": ("item", {"picked_target_seq": 2, "expressible": True}),
    # 到无壁边距离并列 → 由（空爪移动距离, target_seq）定序，应选空爪更近的 seq2
    "tie": ("item", {"picked_target_seq": 2}),
    # 最近件在可抓窗口外 → 拒识，且不改抓更远的件
    "unreachable-nearest": ("no_plan", {"refusals": 1}),
    # 垂直退出通道被另一件挡住 → 拒识
    "blocked": ("no_plan", {"refusals": 1}),
    # 带料退出段报故障 → 停机且不松爪
    "path-fault": ("fault", {"fault_code": "MOTION_FAULT"}),
    # 卡住无反馈 → 运动超时
    "timeout": ("fault", {"fault_code": "MOTION_TIMEOUT"}),
    # 相机断连 → 故障（绝不当作托盘清空）
    "camera-lost": ("fault", {"fault_code": "CAMERA_LOST"}),
    # 连续 3 个有效空画面 → 判托盘为空、本轮结束
    "empty": ("round_done", {}),
    # 重复帧号 → 旧画面，丢弃（第 1 帧照常出件）
    "stale-frame": ("item", {"frames_stale": 1}),
}

def _frame(frame_id: int, now_s: float, detections) -> VisionFrame:
    return VisionFrame(frame_id=frame_id, received_at_s=now_s,
                       detections=tuple(detections))


def demo_frames(scenario: str, config) -> list[VisionFrame]:
    """按场景给出演示画面序列。"""
    if scenario == "tie":
        # 两件到无壁边距离相同（都是 32.5mm）→ 由（空爪移动距离, target_seq）定序
        return [_frame(1, 0.0, (
            Detection(1, box_id=3, class_id=3, x_mm=70.0, y_mm=30.0, confidence=90),
            Detection(2, box_id=6, class_id=6, x_mm=30.0, y_mm=30.0, confidence=90),
        ))]
    if scenario == "unreachable-nearest":
        # 最近的一件 X=10 < 25.5（可抓窗口下界）→ 必须拒识本件，
        # 且**不得**改抓更远的那件（需求三.7）
        return [_frame(1, 0.0, (
            Detection(1, box_id=3, class_id=3, x_mm=10.0, y_mm=55.0, confidence=90),
            Detection(2, box_id=6, class_id=6, x_mm=55.0, y_mm=20.0, confidence=90),
        ))]
    if scenario == "blocked":
        # 另一件正好挡在**垂直退出通道**上（它在 X 上让开夹爪外形，却挡在扫掠带里）
        # → 需求一.6「不能越过其他物料」/ 四.6
        return [_frame(1, 0.0, (
            Detection(2, box_id=6, class_id=6, x_mm=55.0, y_mm=30.0, confidence=91),
            Detection(4, box_id=4, class_id=4, x_mm=80.0, y_mm=30.0, confidence=70),
        ))]
    if scenario == "camera-lost":
        return [_frame(1, 0.0, DEMO_FRAME_NORMAL)]
    if scenario == "empty":
        return [
            _frame(i, 0.0, ()) for i in range(1, config.empty_confirmation_frames + 1)
        ]
    if scenario == "stale-frame":
        # 第 2 帧的帧号不大于第 1 帧 → 旧画面，必须丢弃
        return [
            _frame(1, 0.0, DEMO_FRAME_NORMAL),
            _frame(1, 0.0, DEMO_FRAME_NORMAL),
        ]
    return [_frame(1, 0.0, DEMO_FRAME_NORMAL)]


def make_drop_provider(args, config):
    """落点查表（滑台记账坐标）。与现有 drop_strategy 同口径。"""
    if args.drop is not None:
        fixed = Point(*args.drop)
    else:
        from electrical_control.pick_strategy.config import as_float

        fixed = Point(as_float(config.raw, "Drop", "x_mm"),
                      as_float(config.raw, "Drop", "y_mm"))

    def lookup(box_id):
        if args.scenario == "onray":
            return None  # 由调用方按所选抓取点现算（见 run_scenario 的预处理）
        return fixed

    return lookup, fixed


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def print_provenance(config) -> None:
    banner("① 参数来源清单（每个参数都必须有来源标签）")
    for line in config.provenance_lines():
        print(line)
    unverified = config.unverified_params()
    if unverified:
        print("\n🔴 其中**未实测**的参数（不得当成实机参数）：")
        for name in unverified:
            print(f"   · {name}")
    else:
        print("\n（没有【待实测】参数）")


def run_scenario(args) -> int:
    try:
        config = build_config(args.config)
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    print_provenance(config)
    print(f"\n选择模式局限：{describe_selection_limitation(config.selection_mode)}")

    if args.strict and config.unverified_params():
        print("\n[--strict] 存在未实测参数，拒绝出计划（fail-closed）。", file=sys.stderr)
        return 3

    # 落点：滑台记账坐标
    from electrical_control.pick_strategy.config import as_float
    if args.drop is not None:
        drop_command = Point(*args.drop)
    else:
        drop_command = Point(as_float(config.raw, "Drop", "x_mm"),
                             as_float(config.raw, "Drop", "y_mm"))

    frames = demo_frames(args.scenario, config)

    faults, stalled = {}, {}
    if args.scenario == "timeout":
        stalled = {1: "卡住/无反馈（演示注入）"}
    if args.scenario == "path-fault":
        faults = {2: "退出段受阻（演示注入）"}

    executor = SimExecutor(config, faults=faults, stalled_steps=stalled)
    print(f"\n执行器：{executor.describe()}")

    def drop_provider(box_id):
        """onray 场景：把落点放到"抓取点的正上方"法线上，使计划最简。"""
        det = _onray_pick[0]
        if args.scenario == "onray" and det is not None:
            return Point(det.x_mm + config.tool_offset.x_mm,
                         drop_command.y_mm)
        return drop_command

    _onray_pick: list = [None]
    if args.scenario == "onray" and frames and frames[0].detections:
        sel = select_target(frames[0], config)
        if not isinstance(sel, Refusal):
            _onray_pick[0] = sel.detection

    machine = PickStrategyMachine(config, executor,
                                 drop_command_provider=drop_provider)
    clock = VirtualClock()
    machine.start()
    picked: dict = {}

    for frame in frames:
        if machine.is_faulted or machine.state is State.ROUND_DONE:
            break
        banner(f"② 收到新画面 {frame}（frame_id={frame.frame_id}） @ t={clock.now:.1f}s")
        machine.on_frame(frame, clock.now)
        drive_until_settled(machine, clock)

        if machine.current_plan is not None:
            picked["target_seq"] = machine.current_plan.selection.detection.target_seq
            picked["expressible"] = \
                machine.current_plan.check.expressible_with_item_task
            banner("③ 路径计划")
            print(machine.current_plan.describe())
            commands = to_commands(machine.current_plan, config)
            banner("④ 化成滑台记账坐标的指令序列")
            if isinstance(commands, Refusal):
                print(f"   拒识：{commands}")
            else:
                for i, cmd in enumerate(commands):
                    print(f"   {i + 1}. {cmd}"
                          + (f"   # {cmd.note}" if cmd.note else ""))

        if args.scenario == "camera-lost" and not machine.is_faulted:
            machine.on_camera_lost("演示：视觉线程已断（心跳超时）", clock.now)
            drive_until_settled(machine, clock)

        # 现有链路的两个收尾信号（离线用模拟值；实机来自 STM32 的帧）
        if machine.state is State.WAIT_RESULT:
            machine.on_item_result(0, clock.now)
            drive_until_settled(machine, clock)
        if machine.state is State.WAIT_DISPLAY:
            machine.on_display_ack(clock.now)
            drive_until_settled(machine, clock)

    banner("⑤ 事件日志（完整，从启动起）")
    for t, msg in machine.log:
        print(f"  {t:7.2f}s  {msg}")

    banner("⑥ 本件记录 / 结束状态")
    for rec in machine.item_records:
        print(f"   target_seq={rec.target_seq} box_id={rec.box_id} "
              f"步数={rec.steps_done}/{rec.steps_total} "
              f"夹持已证实={rec.grasp_verified} "
              f"反馈粒度={rec.feedback_granularity} "
              f"result_code={rec.result_code} 显示已确认={rec.display_confirmed}")
        for name in rec.unverified_params:
            print(f"      （未实测参数：{name}）")
    print(f"\n   状态={machine.state.value} 连续空画面={machine.empty_streak}"
          f"/{config.empty_confirmation_frames}")
    print(f"   计数={machine.counters}")
    if machine.fault is not None:
        print(f"\n🔴 故障 {machine.fault.code}（发生在 {machine.fault.at_state}）："
              f"{machine.fault.detail}")
        print(f"   是否可能仍夹持物料：{machine.fault.retained_grasp}"
              f"（retained=True 时**不发松爪**，见需求五.7）")
        print(f"   执行器收到 stop_and_hold 次数={executor.stop_count}")

    return _verdict(args, machine, config, picked)


def _verdict(args, machine, config, picked) -> int:
    """把"这个场景本来应该出现什么"与"实际出现了什么"对照，自动判定通过与否。"""
    if machine.fault is not None:
        outcome = "fault"
    elif machine.state is State.ROUND_DONE:
        outcome = "round_done"
    elif machine.item_records:
        outcome = "item"
    else:
        outcome = "no_plan"

    if machine.last_refusal is not None and \
            machine.last_refusal.code == "GAP_GEOMETRY_UNVERIFIED":
        print(f"\n✅ 场景 [{args.scenario}]：本配置按 **fail-closed** 拒识本件"
              "（缝隙几何未实测），这正是需求四.6 要求的行为。")
        print("   （要跑离线演示请用 pick_strategy.demo.ini；实机请先实测缝隙再放行）")
        return 0

    expected = SCENARIO_EXPECT.get(args.scenario, ("item", {}))
    want_outcome, checks = expected
    failures = []
    if outcome != want_outcome:
        failures.append(f"期望结束形态={want_outcome}，实际={outcome}")
    for key, want in checks.items():
        if key == "picked_target_seq":
            actual = picked.get("target_seq")
        elif key == "expressible":
            actual = picked.get("expressible")
        elif key == "fault_code":
            actual = machine.fault.code if machine.fault else None
        else:
            actual = machine.counters.get(key)
        if actual != want:
            failures.append(f"期望 {key}={want}，实际={actual}")

    if failures:
        print("\n🔴 场景结果与预期不符（**这是失败**）：")
        for f in failures:
            print(f"   · {f}")
        return 1
    print(f"\n✅ 场景 [{args.scenario}] 按预期跑完：结束形态={outcome}"
          f"，自动核对项 {sorted(checks) or '无'}"
          "（**离线模拟执行器**，不是实机验证）")
    return 0


def run_item_task_adapter(args) -> int:
    """只做"计划 → 现有 ITEM_TASK 载荷"的可行性判定与组帧，不发送。"""
    try:
        config = build_config(args.config)
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    from electrical_control.pick_strategy.config import as_float
    frame = _frame(1, 0.0, DEMO_FRAME_NORMAL)
    selection = select_target(frame, config)
    if isinstance(selection, Refusal):
        print(f"拒识：{selection}", file=sys.stderr)
        return 1
    drop_command = Point(as_float(config.raw, "Drop", "x_mm"),
                         as_float(config.raw, "Drop", "y_mm"))
    if args.scenario == "onray":
        # 落点放在退出法线上 → 计划只剩"抓取点 + 落点"两个位置，
        # 这正是现有 ITEM_TASK 能表达的最简形状。
        drop_command = Point(selection.detection.x_mm + config.tool_offset.x_mm,
                             drop_command.y_mm)
    planned = plan(selection, frame, config, drop_command)
    if isinstance(planned, Refusal):
        print(f"拒识：{planned}", file=sys.stderr)
        return 1

    banner("现有 ITEM_TASK 适配器：能否表达这份计划？")
    print(planned.describe())

    executor = ItemTaskExecutor(config, sink=None)
    try:
        raw = executor.build_frame(planned)
    except NotExpressible as exc:
        print("\n🔴 结论：**表达不了**，拒绝下发（不降级、不猜）。缺：")
        print(str(exc))
        print("\n（本适配器不实现串口，也不会发送任何字节）")
        return 4
    print(f"\n执行器：{executor.describe()}")
    print(f"\n✅ 可表达 —— 12 字节 ITEM_TASK 载荷 = {raw.hex(' ')}")
    print("   （仅为组帧演示，未发送；固件侧是否接受还需实机联调）")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="夹取策略离线运行入口（模拟执行器 / ITEM_TASK 适配器）")
    p.add_argument("--config", default=str(DEFAULT_CONFIG),
                   help="配置文件（默认演示配置）")
    p.add_argument("--scenario", default="normal",
                   choices=["normal", "onray", "tie", "unreachable-nearest",
                            "blocked", "path-fault", "timeout", "camera-lost",
                            "empty", "stale-frame"],
                   help="演示场景")
    p.add_argument("--executor", default="sim", choices=["sim", "item_task"],
                   help="sim=离线模拟执行器；item_task=只做协议可行性判定与组帧")
    p.add_argument("--drop", default=None,
                   help="覆盖落点，格式 X,Y（**滑台记账坐标**，mm）")
    p.add_argument("--strict", action="store_true",
                   help="存在【待实测】参数时拒绝出计划")
    args = p.parse_args(argv)
    if args.drop is not None:
        try:
            x, y = (float(v) for v in args.drop.replace("，", ",").split(","))
        except ValueError:
            p.error("--drop 需要 X,Y 两个数")
        args.drop = (x, y)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.executor == "item_task":
        return run_item_task_adapter(args)
    return run_scenario(args)


if __name__ == "__main__":
    sys.exit(main())
