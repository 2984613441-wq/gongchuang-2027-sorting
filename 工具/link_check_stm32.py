#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC ↔ STM32（USART2 / 115200 8N1）只读链路探测。

回答三个问题，且**默认一个字节都不发**：
  1. 这个 COM 口能不能打开（谁占着、驱动在不在）；
  2. STM32 会不会主动吐帧（BARRIER_READY / ACK / NACK / MOTION_DONE / ITEM_RESULT）；
  3. 从收到的帧反推它**是否已经走到 WAIT_TASK**。

⚠️ 为什么不能靠"发一帧看回不回"来判断：设备不在 WAIT_TASK 时，ITEM_TASK 被
   静默丢弃（没有错误码、没有回帧）。所以本工具默认纯监听；--send 才会发帧，
   而发一帧 ITEM_TASK 会让固件真的**驱动机构运动**（WAIT_TASK → ACK →
   VALIDATE_TASK → START_MOTION），必须显式确认。

判据（读代码得出，未实机验证）：
  * BARRIER_READY(0x20) 是通往 WAIT_TASK 的**唯一**转换时发出的帧
    （stm32_logic/src/ec_state_machine.c:107-111 → EMIT_BARRIER_READY）。
    它**只在转换那一刻发一次**，错过了就没有了。
  * DEVICE_READY(0x03) 在固件里**没有任何发送路径**（gateway dispatch 里
    只有 ITEM_TASK / DISPLAY_ACK 两个 case），别等它。
  * 上电后状态机停在 FAULT_LOCK，必须先按 START（PA4 拉低 ≥20 ms）才启动
    POST→HOMING→BARRIER→WAIT_TASK。

用法：
    py -3 工具/link_check_stm32.py                       # 只列串口，不打开
    py -3 工具/link_check_stm32.py --port COM17 -t 15    # 只读监听 15 秒
    py -3 工具/link_check_stm32.py --port COM17 -t 20 --pulse-dtr   # 顺带复位再听
    py -3 工具/link_check_stm32.py --port COM17 --send --task-id 7 --x 100 --y 50  # ⚠️ 会动机构
    py -3 工具/link_check_stm32.py --self-test           # 不碰硬件，跑帧解码自检

依赖：pyserial（只有真开串口时才需要）。帧构造/解码复用 工具/pc_item_task.py。
未验证：本文件只在主机侧跑过 --self-test 与 --help，没有连过真实串口或 STM32。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_item_task as pit  # noqa: E402  （复用它的成帧/解码/打印，不重复造）

from electrical_control.protocol import (  # noqa: E402  （pit 已把 电控/src 加进 sys.path）
    Command,
    Device,
    OuterFrame,
    encode_outer_frame,
)

FRAME_LEN_ITEM_TASK = 26          # 12 头 + 12 载荷 + 2 CRC（P3：8→12 载荷）


def _hex(data: bytes) -> str:
    return pit._hex(data)


def _cmd_name(command: int) -> str:
    return pit._command_name(command)


# --------------------------------------------------------------------------- #
# 收到帧之后：把帧翻译成"设备状态推断"
# --------------------------------------------------------------------------- #
def classify(frames) -> dict:
    """把收到的帧汇总成结论。返回 dict，不打印（便于自检断言）。"""
    seen = [int(f.command) for f in frames]
    has = lambda cmd: int(cmd) in seen  # noqa: E731
    return {
        "n_frames": len(frames),
        "barrier_ready": has(Command.BARRIER_READY),
        "ack": has(Command.ACK),
        "nack": has(Command.NACK),
        "motion_done": has(Command.MOTION_DONE),
        "item_result": has(Command.ITEM_RESULT),
        "device_ready": has(Command.DEVICE_READY),   # 固件不会发，收到才有鬼
        "silent": len(frames) == 0,
    }


def report_verdict(result: dict, summary: dict, seconds: float) -> None:
    print("=" * 62)
    print(f"结论（监听 {seconds:g} 秒）")
    bad = summary.get("bad", 0)
    if result["barrier_ready"]:
        print("  [通] 收到 BARRIER_READY(0x20)：设备已进入 WAIT_TASK，可以接 ITEM_TASK。")
    elif result["ack"] or result["motion_done"] or result["item_result"] or result["nack"]:
        print("  [通] 收到 STM32 的协议帧 —— 串口、波特率、接线、共地都对。")
        if result["nack"]:
            print("       但收到 NACK：帧被拒（轮次不对/重复帧/设备不接受新件）。")
        if result["ack"] and not (result["motion_done"] or result["item_result"]):
            print("       只有 ACK：设备已受理，但没走到 MOTION_DONE/ITEM_RESULT（机构卡住或窗口太短）。")
    elif result["silent"] and bad == 0:
        print("  [不通/未知] 一个字节都没收到。")
        print("    ⚠️ 这**不能**断定设备不在 WAIT_TASK：BARRIER_READY 只在转换那一刻发一次，")
        print("       开机早期发的你看不到。正确做法：① 复位（--pulse-dtr 或按复位键）")
        print("       ② 在监听窗口内按 START 键 ③ 看是否出现 BARRIER_READY。")
        print("    其余可能（按概率）：设备停在 FAULT_LOCK（没按 START）> 波特率错 >")
        print("       TX/RX 接反 > 没共地 > 口选错/被占用 > DTR 复位。")
    if bad:
        print(f"  [警告] 另有 {bad} 段非法/半截字节 —— 见上面 [入站] 丢弃 行：")
        print("       一整片乱码=波特率不匹配；偶见 A5 5A 但 CRC 不过=噪声/接触不良。")
    if result["n_frames"]:
        print(f"  共收到 {result['n_frames']} 帧，非法段 {bad} 段。")


# --------------------------------------------------------------------------- #
# 串口
# --------------------------------------------------------------------------- #
def list_ports() -> int:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        print("错误: 未安装 pyserial，无法枚举串口。装：py -3 -m pip install pyserial", file=sys.stderr)
        return 2
    ports = list(lp.comports())
    if not ports:
        print("未发现任何串口：USB-TTL 没插 / 驱动没装（CH340 需装驱动）。")
        return 1
    print("当前可用串口：")
    for p in ports:
        print(f"  {p.device:<8} {p.description}  [{p.hwid}]")
    print("\n选一个用 --port 指定，例如：--port " + ports[0].device)
    return 0


def open_port(port: str, baud: int):
    """打开串口，并把 DTR/RTS 拉低——CH340 的 DTR 常接 NRST，置位会把 STM32 复位。"""
    try:
        import serial
    except ImportError:
        print("错误: 未安装 pyserial。装：py -3 -m pip install pyserial", file=sys.stderr)
        return None
    try:
        ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N",
                            stopbits=1, timeout=0.2)
    except Exception as exc:
        print(f"错误: 打不开 {port} @ {baud} 8N1: {exc!r}", file=sys.stderr)
        print("  常见：口选错 / 被别的程序占着（串口助手、monitor_gui、Arduino IDE）/ 驱动没装。", file=sys.stderr)
        return None
    for name in ("dtr", "rts"):
        try:
            setattr(ser, name, False)
        except Exception:
            pass  # 部分虚拟串口驱动不支持，忽略
    print(f"已打开 {port} @ {baud} 8N1（DTR/RTS 均已拉低，避免误复位 STM32）")
    return ser


MAX_BAD_SHOWN = 5


def listen(ser, seconds: float) -> dict:
    """纯监听：不写任何字节。返回与 pc_item_task.listen 同形的 summary。"""
    summary = {"frames": [], "bad": 0, "bad_shown": 0}
    buf = bytearray()
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        event = pit._take_frame(buf)
        if event is None:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except Exception as exc:
                print(f"[串口] 读取失败: {exc!r}（线被拔了？）")
                break
            if chunk:
                buf += chunk
            continue
        kind, first, second = event
        if kind == "frame":
            summary["frames"].append(first)
            pit._print_frame(first, second)
        else:
            summary["bad"] += 1
            if summary["bad_shown"] < MAX_BAD_SHOWN:
                summary["bad_shown"] += 1
                raw = second if len(second) <= 32 else second[:32]
                print(f"[入站] 丢弃: {first}  raw={_hex(raw)}"
                      + ("…" if len(second) > 32 else ""))
    if buf:
        summary["bad"] += 1
        print(f"[入站] 结束时残留 {len(buf)} 字节未成帧: {_hex(bytes(buf))}")
    return summary


# --------------------------------------------------------------------------- #
# 自检（不碰硬件）
# --------------------------------------------------------------------------- #
def self_test() -> int:
    def mk(command: int, payload: bytes = b"") -> bytes:
        return encode_outer_frame(OuterFrame(version=1, sender=Device.STM32,
                                             receiver=Device.RASPI, task_id=0,
                                             frame_seq=1, command=int(command),
                                             payload=payload))

    ready = mk(Command.BARRIER_READY)
    assert len(ready) == 14, len(ready)
    ev = pit._take_frame(bytearray(b"\x11\x22" + ready))   # 前面塞噪声字节
    assert ev[0] == "bad", ev                    # 先报噪声
    ev = pit._take_frame(bytearray(ready))
    assert ev[0] == "frame" and int(ev[1].command) == int(Command.BARRIER_READY), ev
    assert classify([ev[1]])["barrier_ready"] is True
    assert classify([])["silent"] is True

    broken = bytearray(ready)
    broken[-1] ^= 0xFF
    assert pit._take_frame(broken)[0] == "bad"   # CRC 坏 → 必须报非法

    ack = mk(Command.ACK, bytes((0x01, 0x07)))
    ev = pit._take_frame(bytearray(ack))
    assert ev[0] == "frame" and int(ev[1].command) == int(Command.ACK)
    assert classify([ev[1]])["ack"] is True

    print("自检通过：帧同步/噪声跳过/CRC 校验/结论分类 全部符合预期。")
    return 0


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="PC↔STM32 USART2 只读链路探测（默认不发字节；--send 才会发，且会动机构）",
    )
    p.add_argument("--port", help="串口名（如 COM17、/dev/ttyUSB0）；不给则只列举串口")
    p.add_argument("--baud", type=int, default=115200, help="波特率，默认 115200（固件固定）")
    p.add_argument("-t", "--listen-s", type=float, default=15.0, dest="listen_s",
                   help="监听秒数，默认 15")
    p.add_argument("--pulse-dtr", action="store_true", dest="pulse_dtr",
                   help="打开后拉低再置位 DTR 一次（CH340 接 NRST 时会复位 STM32，用于重看开机帧）")
    p.add_argument("--send", action="store_true",
                   help="⚠️ 发一帧 ITEM_TASK 后监听（会让固件驱动机构运动！）")
    p.add_argument("--task-id", type=int, dest="task_id", help="--send 时必填，unsigned 16")
    p.add_argument("--frame-seq", type=int, default=1, dest="frame_seq")
    p.add_argument("--target-seq", type=int, default=1, dest="target_seq")
    p.add_argument("--class-id", type=int, default=2, dest="class_id")
    p.add_argument("--x", type=int, default=0, help="落料点 X，单位 0.1mm")
    p.add_argument("--y", type=int, default=0, help="落料点 Y，单位 0.1mm")
    p.add_argument("--pick-x", type=int, dest="pick_x", help="抓取点 X，单位 0.1mm（--send 时必填）")
    p.add_argument("--pick-y", type=int, dest="pick_y", help="抓取点 Y，单位 0.1mm（--send 时必填）")
    p.add_argument("--yes", action="store_true", help="--send 时跳过交互确认")
    p.add_argument("--self-test", action="store_true", dest="self_test",
                   help="不碰硬件，跑帧解码/分类自检")
    args = p.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.port:
        return list_ports()

    if args.send and args.task_id is None:
        print("错误: --send 必须同时给 --task-id。", file=sys.stderr)
        return 2
    if args.send and (args.pick_x is None or args.pick_y is None):
        # P3：抓取点没有默认值。默认 0 等于"去装置中心抓"，正是要避免的 E-18 空夹。
        print("错误: --send 必须同时给 --pick-x 与 --pick-y（抓取点无默认值，见 P3）。",
              file=sys.stderr)
        return 2
    if args.send:
        print("!" * 62)
        print("⚠️  警告：即将发送 ITEM_TASK。若设备在 WAIT_TASK，固件会：")
        print("      ACK → 安全校验 → **真的驱动 X/Y 电机运动**（可能撞机构/丢步）。")
        print("      手放在急停上；确认落料点坐标是你要的；不确定就先只监听。")
        print("!" * 62)
        if not args.yes:
            if input("确认请输入 MOVE 后回车（其它任何输入都中止）: ").strip() != "MOVE":
                print("已中止，未发送任何字节。")
                return 0
        time.sleep(3)

    ser = open_port(args.port, args.baud)
    if ser is None:
        return 2

    payload = raw = None
    if args.send:
        import types
        ns = types.SimpleNamespace(task_id=args.task_id, frame_seq=args.frame_seq,
                                   target_seq=args.target_seq, class_id=args.class_id,
                                   x=args.x, y=args.y,
                                   pick_x=args.pick_x, pick_y=args.pick_y)
        payload = pit.build_payload(ns)
        if payload is None:
            ser.close()
            return 2
        raw = pit.build_frame(ns, payload)
        if raw is None:
            ser.close()
            return 2
        pit.warn_if_unreachable("落料点", args.x, args.y)
        pit.warn_if_unreachable("抓取点", args.pick_x, args.pick_y)
        print(f"将发送 {len(raw)} 字节: {_hex(raw)}")

    with ser:
        ser.reset_input_buffer()
        if args.pulse_dtr:
            for value in (False, True, False):
                try:
                    ser.dtr = value
                except Exception:
                    print("提示: 该串口不支持切 DTR，--pulse-dtr 无效。")
                    break
                time.sleep(0.1)
            print("已做过一次 DTR 脉冲；若它接了 NRST，STM32 现在刚重启（停在 FAULT_LOCK，等按 START）。")
        if raw is not None:
            written = ser.write(raw)
            ser.flush()
            print(f"已写入 {written} 字节，随后监听 {args.listen_s:g} 秒…")
        else:
            print(f"只读监听 {args.listen_s:g} 秒（不发送任何字节）…")
        summary = listen(ser, args.listen_s)

    result = classify(summary["frames"])
    report_verdict(result, summary, args.listen_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
