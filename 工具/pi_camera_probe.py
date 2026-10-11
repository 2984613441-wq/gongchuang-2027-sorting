#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相机视野实测：只听 MaixCAM 发来的 BATCH_TARGETS，**完全不碰 STM32**。

用途：判断「物块放在哪、相机看不看得见、看见的是哪个像素」。
    · 把物块放在工作台正中 / 四角 / 边缘，看这里有没有输出、输出的像素是多少。
    · 检不出 → 那一处不在相机有效视野内（或检测判据把它筛掉了）。

BATCH_TARGETS 线格式（interface-contract §5.1，冻结）：
    target_count(1) + task_id(2, BE) + target[N]
    每个 target 7 字节： id(1) + confidence(1) + X(2,BE) + Y(2,BE) + angle(1)
    校赛模式下 id 字节 = box_id(1..6)（颜色已折叠进货格号）。

用法：python3 pi_camera_probe.py            # 持续监听并打印
      python3 pi_camera_probe.py 30         # 只跑 30 秒
"""

import socket
import sys
import time
from typing import Optional

PORT = 8765
HEADER = 3
PER_TARGET = 7
IDLE_PRINT_S = 3.0   # 连续这么久没检出就打印一次「本帧没检出」


def parse(data: bytes):
    if len(data) < 3:
        return None
    count = data[0]
    task_id = int.from_bytes(data[1:3], "big")
    if len(data) != HEADER + count * PER_TARGET:
        return None
    out = []
    for i in range(count):
        o = HEADER + i * PER_TARGET
        out.append((data[o], data[o + 1],
                    int.from_bytes(data[o + 2:o + 4], "big"),
                    int.from_bytes(data[o + 4:o + 6], "big"),
                    data[o + 6]))
    return task_id, out


def main(seconds: Optional[float]) -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(1)
    srv.settimeout(1.0)
    print("=" * 64)
    print("相机视野实测：监听 0.0.0.0:%d（只收不发，不碰 STM32）" % PORT)
    print("把物块放到不同位置，看下面输出的像素坐标。")
    print("  X 范围 0~319（左→右），Y 范围 0~319（上→下）")
    print("=" * 64)

    deadline = time.monotonic() + seconds if seconds else None
    conn = None
    frames = 0
    detected = 0
    started = time.monotonic()
    last_seen = 0.0

    try:
        while True:
            if deadline and time.monotonic() > deadline:
                break
            if conn is None:
                try:
                    conn, addr = srv.accept()
                    print("\n[连接] %s:%d" % addr)
                    conn.settimeout(1.0)
                except socket.timeout:
                    print("  ...等 MaixCAM 连进来（在 MaixVision 里跑 stage1_color_v6_send.py）")
                    continue
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                conn = None
                continue
            if not chunk:
                print("[断开] 等待重连...")
                conn = None
                continue

            frames += 1
            got = parse(chunk)
            if got is None:
                continue
            task_id, targets = got
            now = time.monotonic()
            if targets:
                detected += 1
                for (box_id, conf, px, py, angle) in targets:
                    print("  检出  box_id=%d conf=%d  像素(%3d, %3d)  angle=%d"
                          % (box_id, conf, px, py, angle))
                last_seen = now
            elif now - last_seen > IDLE_PRINT_S:
                print("  本帧没检出任何目标（物块不在视野内 / 被筛掉 / 摆放不完整）")
                last_seen = now
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()

    dt = time.monotonic() - started
    print("\n" + "=" * 64)
    print("统计：%d 秒内收到 %d 帧，其中 %d 帧有检出" % (dt, frames, detected))
    print("=" * 64)
    return 0


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else None
    sys.exit(main(secs))
