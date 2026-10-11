#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物块是否落在标定工作区内的预检：监听 8765，解析真实帧，报像素与换算结果。

用法： python3 pi_check_object.py [秒数]
判据：换算结果不是 None，就说明这件能过 vision_ingest 的抓取点检查。
"""
import socket
import sys
import time

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.vision_ingest import parse_batch_targets      # noqa: E402
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter  # noqa: E402

SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 6

conv = PixelToDeviceConverter("/home/pi/电控/calibration_config.ini")
print("is_calibrated =", conv.is_calibrated)

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8765))
srv.listen(4)
srv.settimeout(1.0)

t0 = time.time()
n = 0
while time.time() - t0 < SECS:
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        continue
    conn.settimeout(2.0)
    try:
        data = b""
        while len(data) < 10:
            chunk = conn.recv(10 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) < 10:
            continue
        n += 1
        b = parse_batch_targets(data)
        for t in b.targets:
            got = conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id)
            flag = "✅ 可用" if got is not None else "❌ 超出工作区（会被静默丢弃）"
            print("帧%-3d box_id=%s pixel=(%3d,%3d) -> %-16r %s"
                  % (n, t.box_id, t.pixel_x, t.pixel_y, got, flag))
    except Exception as exc:  # noqa: BLE001
        print("帧%d 异常: %s" % (n, exc))
    finally:
        conn.close()

srv.close()
print("--- 共 %d 帧 ---" % n)
if n == 0:
    print(">>> 一帧都没收到：MaixCAM 没在发（没检出物体 / 发送被关）")
