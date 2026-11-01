#!/usr/bin/env python3
"""探测树莓派的视觉相关能力（给斜置相机方案用）。

用法：python3 probe_pi_vision.py
"""

import sys
import subprocess


def probe_import(name, human):
    try:
        mod = __import__(name)
        ver = getattr(mod, "__version__", "?")
        print("  OK    %-12s %s" % (human, ver))
        return True
    except Exception as e:
        print("  MISS  %-12s (%s)" % (human, type(e).__name__))
        return False


def main():
    print("=" * 60)
    print("  树莓派视觉能力探测")
    print("=" * 60)
    print()
    print("Python: %s" % sys.version.split()[0])
    print()
    print("--- 关键库 ---")
    has_cv2 = probe_import("cv2", "OpenCV")
    probe_import("numpy", "numpy")
    probe_import("PIL", "Pillow")
    print()

    print("--- CPU 信息 ---")
    try:
        with open("/proc/cpuinfo") as f:
            txt = f.read()
        for line in txt.splitlines():
            if line.startswith("model name") or line.startswith("Hardware"):
                print("  " + line.strip())
    except Exception as e:
        print("  (读不到: %s)" % e)
    try:
        n = subprocess.check_output(["nproc"], text=True).strip()
        print("  核心数: %s" % n)
    except Exception:
        pass
    print()

    print("--- V4L2 真实摄像头（会跳过 ISP/codec 节点）---")
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"], text=True, shell=False)
        print(out)
    except FileNotFoundError:
        print("  (没装 v4l2-utils，用 /sys 判断)")
        import glob
        import os
        for dev in sorted(glob.glob("/dev/video*")):
            name_path = "/sys/class/video4linux/%s/name" % os.path.basename(dev)
            try:
                with open(name_path) as f:
                    nm = f.read().strip()
            except Exception:
                nm = "?"
            print("  %-16s %s" % (dev, nm))
    except Exception as e:
        print("  v4l2-ctl 失败: %s" % e)
    print()

    print("--- OpenCV 能否打开摄像头（附真实耗时）---")
    if not has_cv2:
        print("  SKIP（没有 cv2）")
        return 0
    import cv2
    import time
    for idx in range(0, 4):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            continue
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        t0 = time.time()
        ok, frame = cap.read()
        dt = (time.time() - t0) * 1000.0
        cap.release()
        if ok and frame is not None:
            print("  /dev/video%d  %dx%d  首帧 %.0f ms" % (idx, w, h, dt))
            print("    frame shape = %s" % (frame.shape,))
        else:
            print("  /dev/video%d  打开了但读不到帧" % idx)
    print()
    print("（若上面没有任何 /dev/videoN 成功，说明相机还没插好）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
