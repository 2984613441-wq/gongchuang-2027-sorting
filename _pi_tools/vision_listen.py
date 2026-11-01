#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在树莓派上监听 8765，解码 MaixCAM 发来的 BATCH_TARGETS 并打印。

用途：现场调视觉时，不靠盯着 MaixCAM 小屏幕，直接拿到结构化识别结果。

线上格式（来自 stage1_color_v6_send.py encode_batch_targets）：
    count(1) + task_id(2, BE) + target[count]
    每个 target 7 字节: bin_id(1) + conf(1) + X(2,BE) + Y(2,BE) + angle(1)

用法：
    python3 vision_listen.py [端口] [秒数]
    默认 8765 端口，跑 60 秒

输出：
    [帧 n] task_id=1 count=3
        #0 bin=2 conf=87% X=561 Y=332 angle=255
        ...
    统计：收到帧数 / 总件数 / 各 bin 计数
"""
import socket
import struct
import sys
import time
from collections import Counter

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 60

TARGET = 7


def decode(buf):
    """从缓冲区尝试解出若干完整帧，返回 (frames, consumed_bytes)。"""
    frames = []
    i = 0
    while i + 3 <= len(buf):
        count = buf[i]
        # 基本合理性检查：count 0..255，需要 3 + count*7 字节
        need = 3 + count * TARGET
        if i + need > len(buf):
            break
        task_id = struct.unpack(">H", buf[i + 1:i + 3])[0]
        targets = []
        p = i + 3
        for _ in range(count):
            b, c, x, y, a = struct.unpack(">BBHHB", buf[p:p + TARGET])
            targets.append({"bin": b, "conf": c, "x": x, "y": y, "angle": a})
            p += TARGET
        frames.append({"task_id": task_id, "targets": targets})
        i += need
    return frames, i


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(4)
    srv.settimeout(1.0)
    print("[listener] 监听 0.0.0.0:%d，最长 %d 秒" % (PORT, DURATION), flush=True)

    all_bins = Counter()
    n_frames = 0
    n_items = 0
    deadline = time.time() + DURATION
    conn = None
    buf = b""

    try:
        while time.time() < deadline:
            if conn is None:
                try:
                    conn, addr = srv.accept()
                    print("[listener] MaixCAM 已连接: %s:%d" % addr, flush=True)
                    conn.settimeout(0.5)
                    buf = b""
                except socket.timeout:
                    continue
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    print("[listener] 连接断开", flush=True)
                    conn.close()
                    conn = None
                    continue
                buf += chunk
            except socket.timeout:
                continue
            except OSError as e:
                print("[listener] recv 失败: %s" % e, flush=True)
                conn = None
                continue

            frames, used = decode(buf)
            buf = buf[used:]
            for f in frames:
                n_frames += 1
                n_items += len(f["targets"])
                print("[帧 %d] task_id=%d count=%d" %
                      (n_frames, f["task_id"], len(f["targets"])), flush=True)
                for k, t in enumerate(f["targets"]):
                    all_bins[t["bin"]] += 1
                    print("    #%d bin=%d conf=%3d%% X=%4d Y=%4d angle=%d" %
                          (k, t["bin"], t["conf"], t["x"], t["y"], t["angle"]),
                          flush=True)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        srv.close()

    print("", flush=True)
    print("=" * 60, flush=True)
    print("统计：收到 %d 帧 / %d 件" % (n_frames, n_items), flush=True)
    if all_bins:
        for b in sorted(all_bins):
            print("  bin=%d : %d 次" % (b, all_bins[b]), flush=True)
    else:
        print("  ⚠️ 一件都没收到", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
