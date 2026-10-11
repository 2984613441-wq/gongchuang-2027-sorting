#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时监听 8765，看 MaixCAM 到底连不连、连上后发的头 16 字节是什么。

用途：链路停着的时候单独诊断视觉通道，不碰 STM32、不碰串口。
判读：
  · 完全没有 "CONNECT" 行  → MaixCAM 根本没来连（它那边的 enable/GATEWAY_HOST 有问题，
    或者压根没检出物体——发送端在 n==0 时直接 return，连 connect 都不试）
  · 有 CONNECT 但没数据     → 连上了不发
  · 有数据                  → 打印十六进制；BATCH_TARGETS 格式为
                              target_count(1) + task_id(2,BE) + target[N]，每 target 7 字节
                              树莓派期望的 task_id 见链路日志里的 "task_id=?"

用法： python3 pi_watch_8765.py [秒数]
"""
import socket
import sys
import time

SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
PORT = 8765

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(4)
srv.settimeout(1.0)
print("监听 0.0.0.0:%d，共 %d 秒……" % (PORT, SECS))

t0 = time.time()
conns = 0
bytes_total = 0
while time.time() - t0 < SECS:
    try:
        conn, addr = srv.accept()
    except socket.timeout:
        continue
    conns += 1
    print("[%.1fs] CONNECT from %s:%d" % (time.time() - t0, addr[0], addr[1]))
    conn.settimeout(3.0)
    try:
        data = conn.recv(4096)
        if not data:
            print("           连上了但立刻关闭，无数据")
        else:
            bytes_total += len(data)
            print("           收到 %d 字节" % len(data))
            print("           头 16 字节 hex: %s" % data[:16].hex(" "))
            if len(data) >= 3:
                count = data[0]
                task_id = int.from_bytes(data[1:3], "big")
                print("           count=%d  task_id=%d   (树莓派期望 task_id 必须与轮次一致，0 会被丢)"
                      % (count, task_id))
    except Exception as exc:  # noqa: BLE001
        print("           读取异常: %s" % exc)
    finally:
        conn.close()

srv.close()
print("--- 汇总 ---")
print("连接次数 = %d   收到字节 = %d" % (conns, bytes_total))
if conns == 0:
    print(">>> MaixCAM 整个窗口内一次都没来连。")
    print(">>> 原因只可能是：①它的 GATEWAY_HOST/端口不是本机 ②ENABLE_NETWORK=False")
    print(">>> ③它那一帧没检出物体（n==0 时发送端直接 return，不建连接）")
