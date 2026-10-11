#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RX-DEAF-FIX 验证：持续灌命令，看 STM32 的 USART2 接收会不会"永久失聪"。

背景（旧固件的死因，见 ec_board_stm32.c 的 RX-DEAF-FIX 注释）：
  接收中断里跑完整条协议链（帧解码 + 状态机 + 阻塞式 HAL_UART_Transmit，
  最长约 20ms），而 HAL_UART_Receive_IT 是链尾才重新武装 RX。那几毫秒里
  RXNE 中断是关的，115200 下 87us 就来一个字节 -> 必然 ORE 溢出 -> HAL 的
  UART_EndRxTransfer() 关掉 RXNE 中断，而本工程没定义 HAL_UART_ErrorCallback
  -> 接收永久死亡，板子从此对一切帧装聋，只能按 RESET 恢复。

新固件：ISR 只做「存字节 + 立刻 re-arm」，处理搬到主循环；
        并且补了 ec_board_uart_error_callback，即使溢出也能自愈。

本脚本不需要任何电机运动，零机械风险。判据：
  · 每个阶段之后，板子都必须还能回应 PING —— 这就是"永久失聪"的判据。
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def drain(ser, seconds):
    """收 seconds 秒，返回收到的全部字节。"""
    end = time.time() + seconds
    buf = bytearray()
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.002)
    return bytes(buf)


def liveness(ser, label):
    """发一条 PING，看有没有应答。返回 True/False。"""
    ser.reset_input_buffer()
    time.sleep(0.1)
    ser.write(b"PING\r\n")
    ser.flush()
    got = drain(ser, 1.5)
    ok = b"OK PONG" in got
    print("    [存活检查 %s] 回 %d 字节, PONG=%s -> %s"
          % (label, len(got), ok, "✅ 活着" if ok else "❌ 失聪了"))
    return ok


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    failures = []
    try:
        ser.reset_input_buffer()

        print("[0] 静默 2s，确认 1Hz 心跳 ...")
        hb = drain(ser, 2.0)
        n_status = hb.count(b"STATUS")
        print("    收到 %d 字节, STATUS 行 %d 条" % (len(hb), n_status))
        if n_status == 0:
            print("    ❌ 没有心跳 —— 板子此刻就是死的，先按板载 RESET")
            return 2

        # ---- 阶段 1：节奏性连续命令（模拟协议重传的稳态流量）----
        print("[1] 连续灌 200 条 PING（间隔 15ms，约 3s 不间断流量）...")
        t0 = time.time()
        for _ in range(200):
            ser.write(b"PING\r\n")
            ser.flush()
            time.sleep(0.015)
        print("    发完，耗时 %.2fs" % (time.time() - t0))
        resp = drain(ser, 2.0)
        pong = resp.count(b"OK PONG")
        print("    OK PONG=%d/200, RX_OVERFLOW=%d, 共 %d 字节"
              % (pong, resp.count(b"RX_OVERFLOW"), len(resp)))
        if not liveness(ser, "阶段1后"):
            failures.append("阶段1（节奏性连续命令）之后失聪")

        # ---- 阶段 2：全速灌（这是旧固件必死的场景）----
        print("[2] 全速灌 400 条 PING（能多快就多快，故意制造溢出）...")
        t0 = time.time()
        for _ in range(400):
            ser.write(b"PING\r\n")
            ser.flush()
        print("    发完，耗时 %.2fs" % (time.time() - t0))
        resp = drain(ser, 2.0)
        print("    OK PONG=%d/400, RX_OVERFLOW=%d, 共 %d 字节"
              % (resp.count(b"OK PONG"), resp.count(b"RX_OVERFLOW"), len(resp)))
        if not liveness(ser, "阶段2后"):
            failures.append("阶段2（全速灌）之后失聪")

        # ---- 阶段 3：再来一轮，确认不是"撑过一次就废"----
        print("[3] 重复阶段 1，确认可重复 ...")
        for _ in range(100):
            ser.write(b"PING\r\n")
            ser.flush()
            time.sleep(0.015)
        resp = drain(ser, 2.0)
        print("    OK PONG=%d/100, 共 %d 字节"
              % (resp.count(b"OK PONG"), len(resp)))
        if not liveness(ser, "阶段3后"):
            failures.append("阶段3（重复）之后失聪")

        print("")
        if failures:
            print("==> ❌ FAIL")
            for f in failures:
                print("    - " + f)
            print("    按板载 RESET 恢复后，把这份完整输出发给我。")
            return 1
        print("==> ✅ PASS：持续流量之后接收依然活着。")
        print("    旧固件在这三个存活检查里必然全部失败（永久失聪）。")
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    sys.exit(main())
