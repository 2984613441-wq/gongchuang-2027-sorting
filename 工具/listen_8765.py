# -*- coding: utf-8 -*-
"""监听 8765 的 BATCH_TARGETS 并打印（2026-11-06 现场验证用）。

在树莓派上跑：
    python3 listen_8765.py --seconds 20
配合 MaixCAM 的 yolo_v11_send.py（--host <Pi-IP> --port 8765）使用。
只读：不连串口、不写配置。
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

SHAPES = {1: "cube", 2: "cuboid", 3: "cylinder", 4: "pentagonal_prism",
          5: "cone", 6: "tetrahedron"}
TARGET_BYTES = 7


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--id-mode", choices=("shape", "code"), default="shape")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(4)
    srv.settimeout(1.0)
    print("[listen] 监听 %d，%s 秒（Ctrl-C 退出）" % (args.port, args.seconds))
    t0 = time.time()
    batches = 0
    while time.time() - t0 < args.seconds:
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            break
        conn.settimeout(2.0)
        print("[listen] 连接来自 %s" % (addr,))
        try:
            while True:
                hdr = b""
                while len(hdr) < 3:
                    ch = conn.recv(3 - len(hdr))
                    if not ch:
                        raise ConnectionError("closed")
                    hdr += ch
                count = hdr[0]
                body = b""
                need = count * TARGET_BYTES
                while len(body) < need:
                    ch = conn.recv(need - len(body))
                    if not ch:
                        raise ConnectionError("closed")
                    body += ch
                batches += 1
                items = []
                for i in range(count):
                    off = i * TARGET_BYTES
                    idb = body[off]
                    if args.id_mode == "code":
                        shape = (idb - 1) // 5 + 1 if 1 <= idb <= 30 else 0
                    else:
                        shape = idb if 1 <= idb <= 6 else 0
                    items.append("%s(id=%d,conf=%d,%d,%d)" % (
                        SHAPES.get(shape, "?"), idb, body[off + 1],
                        int.from_bytes(body[off + 2:off + 4], "big"),
                        int.from_bytes(body[off + 4:off + 6], "big")))
                print("[batch %d] task_id=%d n=%d  %s" % (
                    batches, int.from_bytes(hdr[1:3], "big"), count,
                    " | ".join(items) if items else "(空)"))
        except (ConnectionError, socket.timeout):
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    print("[listen] 共收到 %d 批" % batches)
    if batches == 0:
        print("[listen] ⚠️ 一批都没收到：检查 MaixCAM 的 --host 是否指向本机、端口是否 8765")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
