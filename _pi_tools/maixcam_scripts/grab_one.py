#!/usr/bin/env python3
"""在 MaixCAM 上抓一帧存成 jpg（内存安全版）。

## 为什么有 v2

v1 在 1280x720 上做了 `image2cv(..., copy=True)` + 灰度 + 拉普拉斯，
一次性多要 2.7MB 连续内存，直接把 MaixCAM 打到 SIGSEGV：

    [W] we do not recommend using large resolution RGB888 images
    Trigger signal, code:SIGSEGV(11)!

v2 的原则：**设备只负责存图，所有分析挪到 PC 上做**。
  · 不在设备上做任何 cv2 cvtColor / Laplacian
  · 不用 copy=True
  · 存完立刻退出，尽快释放相机

## 用法

    python3 /root/grab_one.py            # -> /root/grab1.jpg
    python3 /root/grab_one.py /root/a.jpg

PC 端：
    ssh root@172.20.10.9 "python3 /root/grab_one.py /root/grab1.jpg"
    scp root@172.20.10.9:/root/grab1.jpg .

⚠️ 需要相机空闲。正在跑 MaixVision 检测脚本时先停掉。
"""
from __future__ import annotations

import sys
import time

from maix import camera, image

OUT = sys.argv[1] if len(sys.argv) > 1 else "/root/grab1.jpg"
W, H = 1280, 720
WARMUP_S = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5


def main() -> int:
    print("打开相机 %dx%d ..." % (W, H))
    try:
        cam = camera.Camera(W, H, image.Format.FMT_RGB888)
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   先执行：killall launcher_daemon")
        return 1

    print("预热 %.1f s ..." % WARMUP_S)
    t0 = time.time()
    frame = None
    n = 0
    while time.time() - t0 < WARMUP_S:
        f = cam.read()
        if f is not None:
            frame = f
            n += 1
    if frame is None:
        print("❌ 读不到帧")
        return 1
    print("预热期间读到 %d 帧" % n)

    # 再连读 3 帧取最新，避免半帧
    for _ in range(3):
        f = cam.read()
        if f is not None:
            frame = f

    # ── 直接存，不做任何 cv2 分析（v1 就是死在这里）──
    try:
        frame.save(OUT)
    except Exception as e:
        print("❌ 保存失败: %s" % e)
        return 1

    print("✅ 已保存: %s  (%dx%d)" % (OUT, frame.width(), frame.height()))
    print("   分析请在 PC 上做（cv2 会很吃内存）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
