# -*- coding: utf-8 -*-
"""MaixCAM 相机最小自检 —— 不加载模型、不开显示，只验证"相机能不能开"。

用途：当 capture.py / main.py 崩在
    VI_SDK_IOC_S_CTRL - vi_sdk_enable_chn NG, No buffer space available
    Trigger signal, code:SIGSEGV(11)!
时，先用这个脚本把问题**二分成「相机/媒体系统」还是「模型」**。

⚠️ 跑之前必须**拔电源彻底断电**再上电。MaixCAM 的 mmf 媒体服务是常驻进程，
   程序崩溃后它持有的缓冲不会释放；只重开程序没用，只有断电/重启才清得掉。

判读：
  打印 "OK 320x320"        → 相机和媒体系统正常，问题在模型/内存
  打印 "请求 320 失败"     → 媒体系统仍是脏的（继续断电重启）
  打印 SIGSEGV            → 相机硬件或固件问题
"""

from maix import camera, image


def try_size(w: int, h: int) -> bool:
    cam = None
    try:
        print(f"--- 请求 {w}x{h} ---")
        cam = camera.Camera(w, h, image.Format.FMT_RGB888)
        img = cam.read()
        if img is None:
            print(f"    {w}x{h}: read() 返回 None（失败）")
            return False
        print(f"    OK {img.width()}x{img.height()}")
        # 再读两帧，确认不是"第一帧能出、后面崩"
        for i in range(2):
            img2 = cam.read()
            if img2 is None:
                print(f"    第 {i + 2} 帧 None（不稳定）")
                return False
        print(f"    连续 3 帧正常")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    {w}x{h}: 异常 {type(exc).__name__}: {exc}")
        return False
    finally:
        if cam is not None:
            try:
                del cam
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    print("=== MaixCAM 相机最小自检（无模型、无显示）===")
    ok320 = try_size(320, 320)
    print()
    if ok320:
        print(">>> 结论：相机正常。问题在模型加载（内存不足）或显示。")
        print(">>> 下一步：跑 capture.py（已改为 先开相机→再开显示→最后加载模型）")
    else:
        print(">>> 结论：相机 320x320 都开不出来。")
        print(">>> 1) 请再彻底断电一次（拔电源等 10 秒）")
        print(">>> 2) 仍失败 ⇒ 相机硬件/固件问题，需刷 MaixCAM 系统")
