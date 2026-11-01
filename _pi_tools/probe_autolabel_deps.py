#!/usr/bin/env python3
"""检查 MaixCAM 上的 cv2 / numpy 可用性，以及 Image.to_bytes() 的行为。

`capture_dataset.py` 的自动标注依赖 cv2 + numpy + Image.to_bytes()，
如果任一不可用，必须提前知道（否则跑到一半才失败）。
"""

import sys


def main() -> int:
    print("=" * 60)
    print("  MaixCAM 自动标注依赖检查")
    print("=" * 60)
    print("  Python:", sys.version.split()[0])
    print()

    # ── numpy ──────────────────────────────────────────────────────
    try:
        import numpy
        print("  OK   numpy  %s" % numpy.__version__)
        has_np = True
    except Exception as exc:
        print("  FAIL numpy  %s" % exc)
        has_np = False

    # ── cv2 ────────────────────────────────────────────────────────
    try:
        import cv2
        print("  OK   cv2    %s" % cv2.__version__)
        # 检查关键函数
        need = ["inRange", "findContours", "contourArea", "boundingRect",
                "cvtColor", "morphologyEx", "getStructuringElement",
                "bitwise_or"]
        miss = [n for n in need if not hasattr(cv2, n)]
        print("       关键函数缺失: %s" % (miss if miss else "无"))
        has_cv2 = True
    except Exception as exc:
        print("  FAIL cv2    %s" % exc)
        has_cv2 = False

    # ── maix image ─────────────────────────────────────────────────
    print()
    try:
        from maix import camera, image
        print("  OK   maix.image")
        methods = [m for m in dir(image.Image) if not m.startswith("_")]
        for name in ("to_bytes", "to_format", "resize", "save", "get_pixel"):
            print("       %-20s %s" % (name, "有" if name in methods else "❌ 没有"))

        # 试试 to_bytes()
        cam = camera.Camera(1280, 720, image.Format.FMT_RGB888)
        f = cam.read()
        try:
            raw = f.to_bytes()
            print("       to_bytes() 返回 %d 字节 (期望 %d = %d*%d*3)"
                  % (len(raw), 1280 * 720 * 3, 1280, 720))
            if len(raw) == 1280 * 720 * 3:
                print("  OK   to_bytes() 长度对得上")
            else:
                print("  WARN to_bytes() 长度不对 —— numpy reshape 会失败，"
                      "需要改用其他方式取原始像素")
        except Exception as exc:
            print("  FAIL to_bytes()  %s" % exc)
            print("       ⇒ 自动标注需要改方案（可能要用 to_format + get_pixel 采样）")

        # 试试 cv2 转换链（模拟 capture_dataset 里的做法）
        if has_np and has_cv2:
            try:
                import numpy as np
                arr = np.frombuffer(f.to_bytes(), dtype=np.uint8)
                arr = arr.reshape((720, 1280, 3))
                hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
                print("  OK   完整链：to_bytes → numpy → cvtColor(HSV)  形状=%s"
                      % (hsv.shape,))
            except Exception as exc:
                print("  FAIL 转换链失败  %s" % exc)

        del cam
    except Exception as exc:
        print("  FAIL maix.image / camera  %s" % exc)

    print()
    print("=" * 60)
    if has_cv2 and has_np:
        print("  结论：自动标注【可用】")
    else:
        print("  结论：自动标注【不可用】—— 请在 capture_dataset.py 里")
        print("        把 AUTO_LABEL 改成 False（只存图，回头手工标）")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
