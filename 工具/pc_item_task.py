#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC 侧 ITEM_TASK 触发工具（STM32 分拣固件，USART2 / 115200 8N1）。

用法示例：
    py -3 工具/pc_item_task.py --port COM17 --task-id 7 --x 100 --y 50 \
        --pick-x -30 --pick-y 20 --class-id 2
    py -3 工具/pc_item_task.py --port COM17 --task-id 7 --dry-run

抓取点（--pick-x/--pick-y）【必填、无默认值】：P3（2026-09-16）把 ITEM_TASK
从 8 字节扩到 12 字节，尾部追加抓取点。默认 0 等于"去装置中心抓"，正是台账
E-18 的空夹症状，所以本工具拒绝替你猜——必须显式给出。

设计约束：
  * 不自己拼字节、不自己算 CRC。全部复用工程内 codec：
    电控/src/electrical_control/protocol（outer_frame / frames / item_context / types）。
  * 依赖只有 pyserial，且只在真实串口路径导入；--dry-run 与自检不依赖它。
  * 只读工具：不发其它命令、不改固件代码、不写文件。
  * P3（2026-09-16）：ITEM_TASK 载荷 8 → 12 字节（尾部追加抓取点），整帧
    22 → 26 字节；新增 --pick-x / --pick-y（必填）。旧固件与新固件互不兼容
    （长度精确匹配），联调前两侧必须同时升级。

发送前校验的冻结约束（违反则拒绝发送，退出码 2）：
  1. image_id == class_id（本工具无 --image-id，恒按 class-id 填）
  2. grip_angle == 0xFF
  3. target_seq ∈ [1, 255]
  4. x / y ∈ [-1450, 1450]（落料点，协议域，单位 0.1 mm）
  5. pick-x / pick-y ∈ [-1450, 1450]（抓取点，同一坐标域；必填）
  6. 协议版本 == 0x01
其中 1/2/6 由工具构造固定，3/4/5 由 codec 的 encode_item_task_payload 校验。

机械可达域 ±825（±82.5 mm）窄于协议域 ±1450：超出只警告，仍然发送，
以便观察固件回的 POSITION_UNREACHABLE。

验证范围：本文件只在主机侧验证了帧构造、--dry-run 自检与非法帧处理路径；
没有连接过真实串口或 STM32，未做真机收发验证。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROTOCOL_SRC = _PROJECT_ROOT / "电控" / "src"
if str(_PROTOCOL_SRC) not in sys.path:
    sys.path.insert(0, str(_PROTOCOL_SRC))

from electrical_control.protocol import (  # noqa: E402  (必须在 sys.path 调整之后)
    ACK_REASONS,
    CRC_LEN,
    FRAME_OVERHEAD,
    HEADER_0,
    HEADER_1,
    NACK_REASONS,
    VERSION,
    Command,
    ItemTaskPayload,
    PayloadError,
    crc16_modbus,
    decode_ack_nack_payload,
    decode_item_result_payload,
    decode_item_task_payload,
    decode_outer_frame,
    encode_item_task_frame,
    encode_item_task_payload,
)

EXPECTED_VERSION = 0x01      # 冻结约束 5：协议版本必须 0x01
GRIP_ANGLE_NONE = 0xFF       # 冻结约束 2：夹爪不旋转
MECH_LIMIT_MM10 = 825        # 机械可达域 ±82.5 mm（协议域是 ±1450）
PAYLOAD_LEN = 12             # P3 起冻结 ITEM_TASK 载荷长度（8 → 12）
FRAME_LEN = FRAME_OVERHEAD + PAYLOAD_LEN  # 12 头 + 12 载荷 + 2 CRC = 26
_HEADER_BYTES = bytes((HEADER_0, HEADER_1))
_MAX_BAD_SHOWN = 10          # 非法帧最多逐条打印几条，其余只计数

# docs/design/interface-contract.md §5.3（结果码 / 依据），仅用于把字节翻译成人话
RESULT_CODES = {
    0x00: "SUCCESS",
    0x01: "DROP_FAILED",
    0x02: "GRIP_FAILED",
    0x03: "POSITION_UNREACHABLE",
    0x04: "SAFETY_INTERRUPT",
    0xFF: "UNKNOWN",
}
RESULT_BASIS = {0x00: "CONTROL_SEQUENCE", 0x01: "CONFIRMED"}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _hex(data: bytes) -> str:
    return data.hex(" ").upper()


def _fail(message: str) -> int:
    print(f"错误: {message}", file=sys.stderr, flush=True)
    return 2


def _command_name(command: int) -> str:
    try:
        return f"{Command(command).name}(0x{command:02X})"
    except ValueError:
        return f"UNKNOWN(0x{command:02X})"


def _device_name(device) -> str:
    try:
        return device.name
    except AttributeError:
        return f"0x{int(device):02X}"


def _import_serial():
    """按需导入 pyserial，让 --dry-run / 自检在没有 pyserial 的机器上也能跑。"""
    try:
        import serial
        from serial.tools import list_ports  # noqa: F401
    except ImportError as exc:
        print(f"错误: 缺少 pyserial（{exc}）。", file=sys.stderr)
        print("  安装: py -3 -m pip install -r 集成/demo_bridge/requirements.txt", file=sys.stderr)
        return None
    return serial


def _list_serial_ports() -> list[str]:
    from serial.tools import list_ports

    return [
        f"  {port.device:<8} {port.description}  [{port.hwid}]"
        for port in list_ports.comports()
    ]


# --------------------------------------------------------------------------- #
# 构造帧（全部走 codec）
# --------------------------------------------------------------------------- #
def build_payload(args) -> bytes | None:
    """校验冻结约束并编码 12 字节载荷；不合法则返回 None（已打印原因）。"""
    try:
        item = ItemTaskPayload(
            target_seq=args.target_seq,
            class_id=args.class_id,
            image_id=args.class_id,      # 冻结约束 1
            x_position=args.x,
            y_position=args.y,
            grip_angle=GRIP_ANGLE_NONE,  # 冻结约束 2
            pick_x_position=args.pick_x,  # 冻结约束 5（P3 抓取点，无默认值）
            pick_y_position=args.pick_y,
        )
        return encode_item_task_payload(item)
    except PayloadError as exc:
        _fail(f"拒绝发送，载荷违反冻结约束: {exc}")
        return None


def build_frame(args, payload: bytes) -> bytes | None:
    try:
        return encode_item_task_frame(
            task_id=args.task_id,
            frame_seq=args.frame_seq,
            payload=payload,
        )
    except PayloadError as exc:
        _fail(f"拒绝发送，外层帧字段非法: {exc}")
        return None


def warn_if_unreachable(label: str, x: int, y: int) -> None:
    """超出机械可达域只警告不拦截——要能观察到固件的 POSITION_UNREACHABLE。"""
    if abs(x) <= MECH_LIMIT_MM10 and abs(y) <= MECH_LIMIT_MM10:
        return
    print(
        f"警告: {label} x={x} y={y}（0.1 mm）超出机械可达域 ±{MECH_LIMIT_MM10}"
        f"（±{MECH_LIMIT_MM10 / 10:g} mm），机构不会动，固件预期回 "
        f"POSITION_UNREACHABLE(result_code=0x03)。仍然发送。",
        flush=True,
    )


# --------------------------------------------------------------------------- #
# 入站帧解析
# --------------------------------------------------------------------------- #
def _take_frame(buf: bytearray):
    """从缓冲区取一个事件，返回 (kind, a, b)；数据不够时返回 None。

    kind == "frame": a=OuterFrame, b=原始字节
    kind == "bad"  : a=原因,       b=原始字节
    """
    start = buf.find(_HEADER_BYTES)
    if start < 0:
        if len(buf) >= 2:
            junk = bytes(buf[:-1])  # 末字节可能是 0xA5，留下等下一字节
            del buf[:-1]
            return ("bad", "未找到 0xA5 5A 帧头（噪声字节）", junk)
        return None
    if start:
        junk = bytes(buf[:start])
        del buf[:start]
        return ("bad", "帧头之前的噪声字节", junk)
    if len(buf) < FRAME_OVERHEAD:
        return None
    total = FRAME_OVERHEAD + int.from_bytes(buf[10:12], "big")
    if len(buf) < total:
        return None
    raw = bytes(buf[:total])
    try:
        frame = decode_outer_frame(raw)
    except PayloadError as exc:
        # 帧头可能是载荷里的伪帧头：只丢弃这两个字节后重新同步
        del buf[:2]
        detail = str(exc)
        if "CRC" in detail:
            expected = crc16_modbus(raw[:total - CRC_LEN]).to_bytes(2, "big")
            detail += f"（收到 {_hex(raw[-CRC_LEN:])} / 期望 {expected.hex(' ').upper()}）"
        return ("bad", detail, raw)
    del buf[:total]
    return ("frame", frame, raw)


def _print_frame(frame, raw: bytes) -> None:
    print(
        f"[入站] {_hex(raw)}\n"
        f"       cmd={_command_name(frame.command)} "
        f"from={_device_name(frame.sender)} to={_device_name(frame.receiver)} "
        f"task_id={frame.task_id} frame_seq={frame.frame_seq} "
        f"len={len(frame.payload)} crc=OK({_hex(raw[-CRC_LEN:])}) "
        f"payload={_hex(frame.payload)}",
        flush=True,
    )
    if frame.command == int(Command.ITEM_RESULT):
        try:
            result = decode_item_result_payload(frame.payload)
        except PayloadError as exc:
            print(f"       -> ITEM_RESULT 载荷解码失败: {exc}", flush=True)
            return
        code = RESULT_CODES.get(result.result_code, "UNKNOWN")
        basis = RESULT_BASIS.get(result.basis, "UNKNOWN")
        print(
            f"       -> ITEM_RESULT target_seq={result.target_seq} "
            f"result_code=0x{result.result_code:02X}({code}) "
            f"basis=0x{result.basis:02X}({basis})",
            flush=True,
        )
    elif frame.command in (int(Command.ACK), int(Command.NACK)):
        is_ack = frame.command == int(Command.ACK)
        try:
            reason, target_seq = decode_ack_nack_payload(frame.payload)
        except PayloadError as exc:
            print(f"       -> ACK/NACK 载荷解码失败: {exc}", flush=True)
            return
        table = ACK_REASONS if is_ack else NACK_REASONS
        label = "ACK" if is_ack else "NACK"
        print(
            f"       -> {label} reason=0x{reason:02X}"
            f"({table.get(reason, 'UNKNOWN')}) target_seq={target_seq}",
            flush=True,
        )


def listen(ser, seconds: float) -> dict:
    """监听 seconds 秒，打印每个入站事件，返回汇总。"""
    summary = {"frames": [], "bad": 0, "bad_shown": 0}
    buf = bytearray()
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        event = _take_frame(buf)
        if event is None:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except Exception as exc:  # 串口掉线/被拔：不崩，给结论
                print(f"[串口] 读取失败，提前结束监听: {exc!r}", flush=True)
                break
            if chunk:
                buf += chunk
            continue
        kind, first, second = event
        if kind == "frame":
            summary["frames"].append(first)
            _print_frame(first, second)
        else:
            summary["bad"] += 1
            if summary["bad_shown"] < _MAX_BAD_SHOWN:
                summary["bad_shown"] += 1
                print(
                    f"[入站] 丢弃: {first}  raw={_hex(second if len(second) <= 32 else second[:32])}"
                    + ("…" if len(second) > 32 else ""),
                    flush=True,
                )
            elif summary["bad_shown"] == _MAX_BAD_SHOWN:
                summary["bad_shown"] += 1
                print("[入站] 非法/半截帧过多，后续只计数不再逐条打印", flush=True)
    if buf:
        summary["bad"] += 1
        print(f"[入站] 监听结束时残留 {len(buf)} 字节未成帧: {_hex(buf)}", flush=True)
    return summary


# --------------------------------------------------------------------------- #
# 结论
# --------------------------------------------------------------------------- #
def _payload_of(frame) -> bytes:
    payload = getattr(frame, "payload", b"")
    return payload if isinstance(payload, bytes) else b""


def print_verdict(summary: dict, args) -> None:
    frames = summary["frames"]
    results = [f_ for f_ in frames if f_.command == int(Command.ITEM_RESULT)]
    nacks = [f_ for f_ in frames if f_.command == int(Command.NACK)]
    acks = [f_ for f_ in frames if f_.command == int(Command.ACK)]
    motions = [f_ for f_ in frames if f_.command == int(Command.MOTION_DONE)]
    bad = summary["bad"]

    print("=" * 62, flush=True)
    print("结论", flush=True)

    if results:
        print(f"  [1/4] 收到 {len(results)} 帧 ITEM_RESULT——7 步取放已走完并给出结果。", flush=True)
        for frame in results:
            try:
                result = decode_item_result_payload(_payload_of(frame))
            except PayloadError as exc:
                print(f"    task_id={frame.task_id} frame_seq={frame.frame_seq} 载荷异常: {exc}", flush=True)
                continue
            code = RESULT_CODES.get(result.result_code, "UNKNOWN")
            print(
                f"    task_id={frame.task_id} frame_seq={frame.frame_seq} "
                f"target_seq={result.target_seq} "
                f"result_code=0x{result.result_code:02X} = {code}",
                flush=True,
            )
            if result.result_code == 0x03:
                hint = ""
                if abs(args.x) > MECH_LIMIT_MM10 or abs(args.y) > MECH_LIMIT_MM10:
                    hint = "（本次 x/y 已超出 ±825 机械可达域，与此一致）"
                print(f"      POSITION_UNREACHABLE：落料点超出机构可达范围，机构没动{hint}", flush=True)
            elif result.result_code == 0x00:
                print("      SUCCESS：本件成功（只有它才允许累加成功计数）", flush=True)
        return

    if nacks or bad:
        print(f"  [4/4] 收到 NACK 或 CRC/成帧错误——帧没能被正常接受。", flush=True)
        if nacks:
            for frame in nacks:
                try:
                    reason, target_seq = decode_ack_nack_payload(_payload_of(frame))
                except PayloadError as exc:
                    print(f"    NACK 载荷异常: {exc}", flush=True)
                    continue
                print(
                    f"    NACK reason=0x{reason:02X}"
                    f"({NACK_REASONS.get(reason, 'UNKNOWN')}) target_seq={target_seq}",
                    flush=True,
                )
            print("    常见原因：目标序号不在期望轮次、重复 ITEM_TASK、设备不接受新件。", flush=True)
        if bad:
            print(f"    另有 {bad} 个非法/半截帧未被接受。分类判断：", flush=True)
            print("      - 一整片乱码字节      -> 波特率不匹配（固件侧固定 115200 8N1）", flush=True)
            print("      - 偶见 A5 5A 但 CRC 不过 -> 串口噪声 / 接线质量，检查 TX-RX 与 GND", flush=True)
            print("      - 监听结束仍有残留字节 -> 帧被截断，波特率或流控不匹配", flush=True)
        return

    if acks or motions:
        print("  [2/4] 只收到 ACK / MOTION_DONE——运动开始了，但没走到 ITEM_RESULT。", flush=True)
        if acks:
            print(f"    ACK x{len(acks)}：STM32 已接受本帧 ITEM_TASK（握手通了）。", flush=True)
        if motions:
            print(f"    MOTION_DONE x{len(motions)}：运动序列已结束，但不代表本件成功。", flush=True)
        print("    没等到 ITEM_RESULT 的可能原因：", flush=True)
        print(f"      - 监听窗口太短（当前 --listen-s {args.listen_s}），加大后重试", flush=True)
        print("      - 机构卡住 / 限位触发 / 急停，结果帧永远不会来", flush=True)
        print("      - ITEM_RESULT 发给了别的接收方或被显示流程阻塞", flush=True)
        return

    print("  [3/4] 什么都没收到。", flush=True)
    print("    >>> 设备可能不在 WAIT_TASK 状态，本帧被直接丢弃。", flush=True)
    print("    请依次检查：", flush=True)
    print("      1. 启动序列是否跑完：STM32 是否已完成自检/回零/发过 DEVICE_READY(0x03)", flush=True)
    print("      2. 串口是否选对：确认设备管理器里的 COM 号，且该口未被其它程序占用", flush=True)
    print("      3. 波特率：固件侧主/备 UART 均固定 115200 8N1，--baud 必须一致", flush=True)
    print("      4. 接线：PC TX -> STM32 RX(USART2)、共地；只接 TX 时也可能收不到回帧", flush=True)
    print("      5. 状态机：设备若在等 DISPLAY_ACK 或已进入故障锁死，会拒绝新任务", flush=True)


# --------------------------------------------------------------------------- #
# 主机侧自检（只在 --dry-run 路径执行，不开串口）
# --------------------------------------------------------------------------- #
def self_check(*, raw: bytes, payload: bytes, task_id: int, frame_seq: int) -> None:
    checks: list[str] = []

    def ok(label: str) -> None:
        checks.append(label)
        print(f"  [自检] OK  {label}", flush=True)

    assert len(raw) == FRAME_LEN == 26, f"帧长应为 26，实际 {len(raw)}"
    assert len(payload) == PAYLOAD_LEN == 12, f"载荷应为 12，实际 {len(payload)}"
    ok(f"帧长 = FRAME_OVERHEAD(14) + 载荷(12) = {len(raw)} 字节")

    assert raw[0] == HEADER_0 and raw[1] == HEADER_1, f"帧头错误: {_hex(raw[:2])}"
    ok(f"帧头 = {_hex(raw[:2])} (0xA5 0x5A)")

    assert raw[2] == VERSION == EXPECTED_VERSION, f"版本字节错误: 0x{raw[2]:02X}"
    ok("版本字节 = 0x01（冻结约束 5）")

    assert crc16_modbus(b"123456789") == 0x4B37, "codec CRC16/MODBUS 金标不匹配"
    ok("codec CRC16/MODBUS 金标 b'123456789' -> 0x4B37")

    decoded = decode_outer_frame(raw)
    assert decoded.payload == payload, "回环解码载荷不一致"
    assert decoded.command == int(Command.ITEM_TASK), "回环解码命令字不是 ITEM_TASK"
    assert decoded.task_id == task_id and decoded.frame_seq == frame_seq, "回环解码 task_id/frame_seq 不一致"
    ok("decode_outer_frame(raw) 回环通过（帧头/版本/CRC/长度/字段全部一致）")

    bad_payloads = {
        "grip_angle != 0xFF": ItemTaskPayload(1, 2, 2, 0, 0, 0x00, 0, 0),
        "image_id != class_id": ItemTaskPayload(1, 2, 3, 0, 0, GRIP_ANGLE_NONE, 0, 0),
        "target_seq = 0": ItemTaskPayload(0, 2, 2, 0, 0, GRIP_ANGLE_NONE, 0, 0),
        "x 超协议域 1450": ItemTaskPayload(1, 2, 2, 1451, 0, GRIP_ANGLE_NONE, 0, 0),
        "y 超协议域 1450": ItemTaskPayload(1, 2, 2, 0, -1451, GRIP_ANGLE_NONE, 0, 0),
        "pick-x 超协议域 1450": ItemTaskPayload(1, 2, 2, 0, 0, GRIP_ANGLE_NONE, 1451, 0),
        "pick-y 超协议域 1450": ItemTaskPayload(1, 2, 2, 0, 0, GRIP_ANGLE_NONE, 0, -1451),
        "抓取点缺失（None）": ItemTaskPayload(1, 2, 2, 0, 0, GRIP_ANGLE_NONE, None, None),
    }
    for label, item in bad_payloads.items():
        try:
            encode_item_task_payload(item)
        except PayloadError:
            ok(f"codec 拒绝非法载荷：{label}")
        else:
            raise AssertionError(f"codec 未拒绝非法载荷：{label}")

    # P3 fail-closed：8 字节旧载荷（P3 之前的线格式）必须被拒。
    old_8_byte_payload = bytes.fromhex("01 02 02 FC 18 03 E8 FF")
    try:
        decode_item_task_payload(old_8_byte_payload)
    except PayloadError as exc:
        ok(f"codec 拒绝 8 字节旧载荷（fail-closed）：{exc}")
    else:
        raise AssertionError("codec 接受了 8 字节旧载荷")

    print(f"  [自检] 全部通过（{len(checks)}/{len(checks)}）", flush=True)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="向 STM32 分拣固件发送一帧 ITEM_TASK 并打印回帧结论（USART2, 115200 8N1）。",
    )
    parser.add_argument("--port", required=True, help="STM32 串口，例如 COM17（必填，不写死）")
    parser.add_argument("--baud", type=int, default=115200, help="波特率，默认 115200")
    parser.add_argument("--task-id", type=int, required=True, dest="task_id", help="任务号，unsigned 16（必填）")
    parser.add_argument("--frame-seq", type=int, default=1, dest="frame_seq", help="帧序号，默认 1")
    parser.add_argument("--x", type=int, default=0, help="落料点 X，单位 0.1 mm，默认 0")
    parser.add_argument("--y", type=int, default=0, help="落料点 Y，单位 0.1 mm，默认 0")
    parser.add_argument(
        "--pick-x", type=int, required=True, dest="pick_x",
        help="抓取点 X，单位 0.1 mm（P3 必填，无默认值：0 会被当成装置中心抓）",
    )
    parser.add_argument(
        "--pick-y", type=int, required=True, dest="pick_y",
        help="抓取点 Y，单位 0.1 mm（P3 必填，无默认值）",
    )
    parser.add_argument("--class-id", type=int, default=2, dest="class_id", help="类别 ID（同时作为 image_id），默认 2")
    parser.add_argument("--target-seq", type=int, default=1, dest="target_seq", help="目标序号，默认 1")
    parser.add_argument("--listen-s", type=float, default=5.0, dest="listen_s", help="发送后监听秒数，默认 5")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="只打印将要发送的字节（hex），不开串口")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if VERSION != EXPECTED_VERSION:
        return _fail(f"codec 协议版本 0x{VERSION:02X} != 冻结的 0x{EXPECTED_VERSION:02X}")

    payload = build_payload(args)
    if payload is None:
        return 2
    raw = build_frame(args, payload)
    if raw is None:
        return 2

    warn_if_unreachable("落料点", args.x, args.y)
    warn_if_unreachable("抓取点", args.pick_x, args.pick_y)

    print(
        f"准备发送 1 帧 ITEM_TASK：task_id={args.task_id} frame_seq={args.frame_seq} "
        f"target_seq={args.target_seq} class_id={args.class_id} image_id={args.class_id} "
        f"x={args.x} y={args.y} pick_x={args.pick_x} pick_y={args.pick_y} "
        f"grip_angle=0x{GRIP_ANGLE_NONE:02X}（单位 0.1 mm）",
        flush=True,
    )
    print(f"  载荷 12 字节: {_hex(payload)}", flush=True)
    print(f"  整帧 {len(raw)} 字节: {_hex(raw)}", flush=True)
    print(f"  末尾 CRC16/MODBUS = {_hex(raw[-CRC_LEN:])}（前 {len(raw) - CRC_LEN} 字节的校验）", flush=True)

    if args.dry_run:
        print("--dry-run: 未打开串口，未发送任何字节。", flush=True)
        print("主机侧自检：", flush=True)
        self_check(raw=raw, payload=payload, task_id=args.task_id, frame_seq=args.frame_seq)
        return 0

    serial = _import_serial()
    if serial is None:
        return 2

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
        )
    except (serial.SerialException, OSError) as exc:
        print(f"错误: 无法打开串口 {args.port} @ {args.baud} 8N1: {exc}", file=sys.stderr, flush=True)
        ports = _list_serial_ports()
        if ports:
            print("当前可用串口：", file=sys.stderr, flush=True)
            print("\n".join(ports), file=sys.stderr, flush=True)
        else:
            print("未发现任何串口（检查 USB 转串口驱动与线缆）。", file=sys.stderr, flush=True)
        return 2

    with ser:
        ser.reset_input_buffer()  # 丢掉发送前的陈旧字节，避免误判为回帧
        written = ser.write(raw)
        ser.flush()
        print(f"已写入 {written} 字节到 {args.port} @ {args.baud} 8N1，监听 {args.listen_s} 秒…", flush=True)
        summary = listen(ser, args.listen_s)

    print_verdict(summary, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
