# -*- coding: utf-8 -*-
"""分辨率探针 —— 在 MaixVision 里直接打开运行即可。

作用：不看任何代码常量，直接问摄像头"实际返回的一帧有多大"。
     如果把 FMT_RGB888 的帧交给 analyze()，帧尺寸就是像素坐标所在的坐标系。

对照结论：
  · 打印「实得 320x320」→ 现在整条链路跑在 320 系
  · 打印「实得 448x448」→ 跑在 448 系
  · 某个尺寸「失败」→ 该硬件模式不可用

注意：camera.Camera(w, h) 是"请求"尺寸，摄像头有可能就近取整返回别的值，
      所以必须以 img.width()/height() 的实测值为准，不能只看请求值。
"""

from maix import camera, image

# 只测这两个：320 是当前代码写死的值，448 是你说的值
CANDIDATES = (320, 448)


def probe(size):
    cam = None
    try:
        cam = camera.Camera(size, size, image.Format.FMT_RGB888)
        img = cam.read()
        if img is None:
            print("[PROBE] 请求 %4dx%-4d -> 读帧返回 None（失败）" % (size, size))
            return None
        w, h = img.width(), img.height()
        flag = "一致" if (w == size and h == size) else "!!! 与请求不符 !!!"
        print("[PROBE] 请求 %4dx%-4d -> 实得 %4dx%-4d   %s" % (size, size, w, h, flag))
        return (w, h)
    except Exception as exc:
        print("[PROBE] 请求 %4dx%-4d -> 异常: %s" % (size, size, exc))
        return None
    finally:
        if cam is not None:
            try:
                cam.close()
            except Exception:
                pass


def main():
    print("=" * 58)
    print("MaixCAM 分辨率探针")
    print("=" * 58)
    got = {}
    for size in CANDIDATES:
        got[size] = probe(size)

    print("-" * 58)
    if got.get(320) == (320, 320):
        print(">>> 320x320 可用。当前 stage1_color_v6_send.py 用的就是它。")
    if got.get(448) == (448, 448):
        print(">>> 448x448 也可用。若要用它，把 FRAME_SIZE 改成 448 即可。")
    elif got.get(448) is None:
        print(">>> 448x448 在本硬件上不可用，只能维持 320x320。")

    print("-" * 58)
    print("另外请把下面这句的结果一并记下（判断色彩正确性用）：")
    cam = camera.Camera(320, 320, image.Format.FMT_RGB888)
    img = cam.read()
    print("    320x320 帧尺寸 = %dx%d" % (img.width(), img.height()))
    cam.close()


if __name__ == "__main__":
    main()
