#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转盘六格测量工具（ST-3215 + 微雪 Bus Servo Adapter，UART2）。

用途：现场把「6 个货格分别转到落料口正下方」时，读回舵机位置值，
      并直接生成可粘贴进 `sorting_config.ini` 的 `[TurntableAngles]` 片段。

━━━ 硬件前置（2026-10-17 实测）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · /boot/config.txt 有 dtoverlay=uart2 ⇒ /dev/ttyAMA1
  · 树莓派 27/28 脚与转换板【同名直连】（TX→TX、RX→RX，交叉接完全无响应）
  · 舵机 ID=1，波特率 1,000,000；位置 0~4095 ↔ 0~360°
  · 帧：FF FF ID LEN INST PARAM... CS；LEN=参数数+2；CS=~(ID+LEN+INST+PARAM)&0xFF
  · 寄存器：目标位置 0x2A、目标时间 0x2C、当前位置 0x38（2 字节小端）

━━━ 用法 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python3 measure_turntable_slots.py --ping
  python3 measure_turntable_slots.py --read
  python3 measure_turntable_slots.py --goto 2048            # 转到任意位置值
  python3 measure_turntable_slots.py --interactive \
      --drop-x 88.0 --drop-y 90.0 --out /tmp/tt_slots.ini   # 逐格测量并生成配置
  python3 measure_turntable_slots.py --dry-run              # 不连硬件，只看流程

━━━ 安全 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  本工具只发 PING / READ / WRITE(目标时间、目标位置)，不碰任何其它设备；
  位置值强制限制在 0~4095；每次移动限速（默认 1500ms 到位）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ADDR_GOAL_POS = 0x2A
ADDR_GOAL_TIME = 0x2C
ADDR_PRESENT_POS = 0x38

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03

POS_MIN, POS_MAX = 0, 4095
COUNTS_PER_DEG = 4096.0 / 360.0
ARRIVE_TOL = 20          # 约 1.8°


def _checksum(body):
    return (~sum(body)) & 0xFF


def _frame(body):
    return bytes([0xFF, 0xFF] + list(body) + [_checksum(body)])


class Servo:
    """最小 ST-3215 客户端（与 工具/pi_turntable.py 同协议）。"""

    def __init__(self, port: str, baud: int, sid: int, timeout: float = 0.12):
        import serial  # 延迟导入：--dry-run 时不需要 pyserial

        self.sid = int(sid)
        self.ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(0.2)          # 开串口后总线约需 0.2s 稳定
        try:
            self.ser.reset_input_buffer()
        except Exception:        # noqa: BLE001
            pass

    def close(self):
        try:
            self.ser.close()
        except Exception:        # noqa: BLE001
            pass

    def _read_packet(self):
        buf = self.ser.read(32)
        i = buf.find(b"\xff\xff")
        if i < 0 or len(buf) < i + 4:
            return None
        ln = buf[i + 3]
        need = i + 4 + ln
        if len(buf) < need:
            buf += self.ser.read(need - len(buf))
        if len(buf) < need:
            return None
        return {"err": buf[i + 4], "data": buf[i + 5:i + 4 + ln - 1]}

    def _txn(self, body, wait: float = 0.06):
        self.ser.reset_input_buffer()
        self.ser.write(_frame(body))
        self.ser.flush()
        time.sleep(wait)
        return self._read_packet()

    def ping(self) -> bool:
        r = self._txn([self.sid, 2, INST_PING])
        return r is not None and r["err"] == 0

    def read_pos(self) -> int | None:
        r = self._txn([self.sid, 4, INST_READ, ADDR_PRESENT_POS, 2])
        if r is None or len(r["data"]) < 2:
            return None
        return r["data"][0] | (r["data"][1] << 8)

    def _write16(self, addr: int, value: int) -> bool:
        v = int(value) & 0xFFFF
        r = self._txn([self.sid, 5, INST_WRITE, addr, v & 0xFF, v >> 8])
        return r is not None and r["err"] == 0

    def goto(self, pos: int, time_ms: int = 1500) -> bool:
        if not (POS_MIN <= pos <= POS_MAX):
            raise ValueError("位置超范围 0~4095：%d" % pos)
        if not self._write16(ADDR_GOAL_TIME, time_ms):
            return False
        return self._write16(ADDR_GOAL_POS, pos)

    def wait_arrive(self, target: int, timeout_s: float = 8.0) -> tuple[bool, int | None]:
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout_s:
            p = self.read_pos()
            if p is not None:
                last = p
                if abs(p - target) <= ARRIVE_TOL:
                    return True, p
            time.sleep(0.05)
        return False, last


def _emit_config(slots: dict[int, int], drop_x: float | None, drop_y: float | None) -> str:
    """由 6 格位置值生成 [TurntableAngles] 片段（第 1 格 = 0°）。"""
    if 1 not in slots:
        raise SystemExit("缺少第 1 格位置值，无法定义 0°")
    base = slots[1]
    lines = [
        "# ===== 由 工具/measure_turntable_slots.py 生成（%s）=====" %
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "[TurntableAngles]",
        "# 单一固定落料点（滑台记账坐标 mm，不叠加 ToolOffset）",
        "turntable_drop_point = %s, %s" % (
            ("%.1f" % drop_x) if drop_x is not None else "<待测 X>",
            ("%.1f" % drop_y) if drop_y is not None else "<待测 Y>",
        ),
        "# 6 个货格角度（第 1 格 = 0°；顺时针为正，按实测位置值换算）",
    ]
    for b in range(1, 7):
        if b not in slots:
            lines.append("# %d = <缺>" % b)
            continue
        delta = (slots[b] - base) % 4096
        deg = delta / COUNTS_PER_DEG
        lines.append("%d = %.1f   # pos=%d  delta=%d" % (b, deg, slots[b], delta))
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="转盘六格测量（ST-3215/UART2）")
    ap.add_argument("--port", default=os.environ.get("TURNTABLE_PORT", "/dev/ttyAMA1"))
    ap.add_argument("--baud", type=int, default=int(os.environ.get("TURNTABLE_BAUD", "1000000")))
    ap.add_argument("--id", type=int, default=int(os.environ.get("TURNTABLE_ID", "1")))
    ap.add_argument("--time-ms", type=int, default=1500, help="移动到目标位置的耗时（限速）")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--goto", type=int, help="转到指定位置值 0~4095")
    ap.add_argument("--interactive", action="store_true", help="逐格测量（第 1~6 格）")
    ap.add_argument("--drop-x", type=float, help="单一落点滑台坐标 X（mm），生成配置用")
    ap.add_argument("--drop-y", type=float, help="单一落点滑台坐标 Y（mm），生成配置用")
    ap.add_argument("--out", help="把生成的 [TurntableAngles] 片段写到该文件")
    ap.add_argument("--dry-run", action="store_true", help="不连硬件，只打印流程")
    args = ap.parse_args(argv)

    if args.dry_run:
        print("[dry-run] 需要硬件；本模式只演示流程。")
        print("1) --ping 探测舵机")
        print("2) --read 读当前位置")
        print("3) --interactive 逐格：把第 k 格转到落料口正下方后回车，自动记录")
        print("4) 结束后生成 [TurntableAngles]（第 1 格 = 0°）")
        demo = {1: 0, 2: 683, 3: 1365, 4: 2048, 5: 2731, 6: 3413}
        print("\n[dry-run] 用示例位置值演示生成结果：\n")
        print(_emit_config(demo, args.drop_x or 88.0, args.drop_y or 90.0))
        return 0

    try:
        sv = Servo(args.port, args.baud, args.id)
    except Exception as exc:     # noqa: BLE001
        sys.stderr.write("打开串口失败 %s@%d：%s\n" % (args.port, args.baud, exc))
        return 1

    try:
        if args.ping:
            ok = sv.ping()
            print("PING %s (ID=%d @ %s)" % ("OK" if ok else "无响应", args.id, args.port))
            return 0 if ok else 2

        if args.read:
            p = sv.read_pos()
            if p is None:
                print("读取失败：无响应")
                return 2
            print("当前位置 = %d  (%.1f°)" % (p, p / COUNTS_PER_DEG))
            return 0

        if args.goto is not None:
            if not (POS_MIN <= args.goto <= POS_MAX):
                sys.stderr.write("位置超范围 0~4095：%d\n" % args.goto)
                return 4
            before = sv.read_pos()
            ok = sv.goto(args.goto, args.time_ms)
            if not ok:
                print("指令发送失败（舵机无响应）")
                return 2
            arrived, after = sv.wait_arrive(args.goto, timeout_s=max(4.0, args.time_ms / 1000.0 + 4.0))
            print("目标 %d  到位 %s  误差 %s  %s" % (
                args.goto, after if after is not None else "?",
                (after - args.goto) if after is not None else "?",
                "OK" if arrived else "未到位（检查机械/供电/是否卡住）",
            ))
            return 0 if arrived else 3

        if args.interactive:
            print("=" * 66)
            print(" 转盘六格测量：**把第 k 格转到落料口正下方**，然后按回车读取位置值")
            print(" 输入 s 跳过该格 / q 中止。第 1 格将被定义为 0°。")
            print("=" * 66)
            slots: dict[int, int] = {}
            for k in range(1, 7):
                while True:
                    ans = input("把【第 %d 格】转到落料口正下方，回车读取（s=跳过 q=中止）: " % k)
                    if ans.strip().lower() == "q":
                        print("已中止，不生成配置。")
                        return 5
                    if ans.strip().lower() == "s":
                        break
                    p = sv.read_pos()
                    if p is None:
                        print("  读取失败（无响应），请检查接线后重试")
                        continue
                    print("  第 %d 格位置值 = %d  (%.1f°)" % (k, p, p / COUNTS_PER_DEG))
                    slots[k] = p
                    break
            if not slots:
                print("没有记录任何格，退出。")
                return 5
            print("\n记录结果：")
            for k in sorted(slots):
                print("  格%d  pos=%d" % (k, slots[k]))
            snippet = _emit_config(slots, args.drop_x, args.drop_y)
            print("\n" + snippet)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(snippet)
                print("已写入 %s（把它粘进 sorting_config.ini，替换掉方案C 的节）" % args.out)
            return 0

        print(__doc__)
        return 0
    finally:
        sv.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
