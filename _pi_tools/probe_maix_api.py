#!/usr/bin/env python3
"""探测 MaixCAM 的 MaixPy 版本与 image API 可用性（给自动采集脚本用）。

用法（在 MaixCAM 上）：python3 probe_maix_api.py
"""

import sys


def main() -> int:
    print("=" * 60)
    print("  MaixCAM MaixPy API 探测")
    print("=" * 60)
    print()
    print("Python:", sys.version.split()[0])
    print()

    try:
        import maix
    except Exception as exc:
        print("  ❌ import maix 失败:", exc)
        return 1

    print("  maix 版本:", getattr(maix, "__version__", "?"))
    print()

    try:
        from maix import app, camera, display, image
    except Exception as exc:
        print("  ❌ import 子模块失败:", exc)
        return 1

    print("── image.Format 的可枚举值 ──")
    fmts = [m for m in dir(image.Format) if m.startswith("FMT_")]
    print("  " + ", ".join(fmts))
    print()

    print("── image 模块的 COLOR_* 常量 ──")
    colors = [m for m in dir(image) if m.startswith("COLOR_")]
    print("  " + ", ".join(colors))
    print()

    print("── image.Image 的公开方法 ──")
    methods = sorted(m for m in dir(image.Image) if not m.startswith("_"))
    # 分组打印，方便看
    for i in range(0, len(methods), 6):
        print("  " + ", ".join(methods[i:i + 6]))
    print()

    # 关键方法是否存在（自动采集脚本要用）
    print("── 自动采集脚本需要的方法 ──")
    need = ["save", "resize", "draw_string", "draw_rect", "to_format",
            "mean", "width", "height", "get_pixel", "set_pixel", "crop"]
    for name in need:
        ok = name in methods
        print("  %s  %s" % ("OK  " if ok else "MISS", name))
    print()

    # 能不能真正开相机（这一步会占相机，跑之前确保没有别的程序在跑）
    print("── 试开相机 1280x720 RGB888 ──")
    cam = None
    try:
        cam = camera.Camera(1280, 720, image.Format.FMT_RGB888)
        frame = cam.read()
        print("  OK  拿到一帧: %dx%d, mode=%s"
              % (frame.width(), frame.height(), frame.format()))
        # 试 resize
        try:
            small = frame.resize(64, 36)
            print("  OK  resize 到 64x36 成功: %dx%d"
                  % (small.width(), small.height()))
        except Exception as exc:
            print("  ❌ resize 失败:", exc)
    except Exception as exc:
        print("  ❌ 开相机失败:", exc)
        print("     （如果相机被别的程序占着，这里会失败，属正常）")
    finally:
        if cam is not None:
            try:
                del cam
            except Exception:
                pass
    print()
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
