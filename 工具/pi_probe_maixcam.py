#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从树莓派反向探测 MaixCAM 的端口，判定其脚本是否在跑。

MaixCAM 侧：
  · 9001 = 监控服务（main.py:62 MONITOR_PORT，默认开）—— 它是【服务端】，能连上就证明脚本在跑
  · 9002 = 树莓派侧的监控端口（run_chain 日志里的 [MONITOR] 0.0.0.0:9002）
  · 8765 = 树莓派侧的视觉监听端口（生产通道）—— MaixCAM 是客户端，不该有人从这个方向连

用法： python3 pi_probe_maixcam.py [MaixCAM的IP]
"""
import socket
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.10.9"
PORTS = (
    (9001, "MaixCAM 监控服务（脚本在跑就能连上）"),
    (9002, "树莓派监控端口"),
    (8765, "树莓派视觉监听（生产通道）"),
)

for port, desc in PORTS:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect((HOST, port))
        print("  %-5d OPEN    %s" % (port, desc))
    except Exception as exc:  # noqa: BLE001
        print("  %-5d CLOSED  %s   (%s)" % (port, desc, exc))
    finally:
        s.close()
