"""摄像头视野可视化 —— 量出「画面能覆盖多少 mm」，方便设计托盘。

======================================================================
  用法（在 MaixVision 里跑）
======================================================================
  1. 打开 MaixVision，连 MaixCAM
  2. 新建文件 `fov_check.py`，把本文件**全部内容**粘进去
  3. **改下面【配置区】的 CAMERA_HEIGHT_MM**（当前相机到底多高，用尺子量）
  4. 点运行（▶）
  5. 屏幕上看：
       · 白色细网格 = 每 100 像素
       · 青色粗线   = 每 100 mm（按 MM_PER_PX 换算）
       · 黄色方框   = 190×190 mm（我们托盘的尺寸）
       · 绿色方框   = A4 纸 210×297 mm（用来定标：把 A4 放上去看对不对齐）
       · 红色十字   = 画面中心
       · 左上面板   = 关键数字
  6. 看 console 输出，里面有完整的换算表

======================================================================
  这个脚本要回答的问题
======================================================================
  · 我现在的相机高度，竖直方向能覆盖多少 mm？够不够放下托盘？
  · 190×190mm 的托盘在画面里占多少像素？会不会被裁掉？
  · 托盘最小尺寸 160×160mm（赛规 L44）够不够？
  · 需要把相机升高到多少 mm 才能完整覆盖托盘？

======================================================================
  关于 MM_PER_PX 的三个来源（自检逻辑）
======================================================================
  A. 默认值 0.2715 mm/px
     推算：GC4653 1280x720 模式，水平 FOV ≈ 67°
       水平覆盖 = 2 * h * tan(33.5°) = 2 * 262 * 0.662 = 347 mm
       mm/px    = 347 / 1280 = 0.2711
  B. 你用已知物体实测（推荐：A4 纸 210mm 宽）
     把 A4 纸横放贴着画面左边缘，看右边缘落在哪个像素 x
       mm/px = 210 / (x_right - x_left)
  C. 从标定文件读（如果 [Calibration] 有 scale）
     ⚠️ 当前 calibration_config.ini 的仿射矩阵已过期（相机移动过 4 次），
        不要直接信它，用 A 或 B。

  ⇒ 脚本里 MM_PER_PX 是**可配置**的，你实测后改它，重跑即可。
"""

# ═══════════════════════════════════════════════════════════════════════════
#  【配置区】
# ═══════════════════════════════════════════════════════════════════════════

# 采集分辨率（必须 1280x720，与现有标定一致）
FRAME_W = 1280
FRAME_H = 720

# 🔴 相机镜头到托盘平面的高度（mm）—— 用尺子量，这是最关键的数
CAMERA_HEIGHT_MM = 262.0

# 🔴 每个像素对应多少 mm —— 实测后改这里
#    默认 0.2711 = 按水平 FOV 67° / 高度 262mm 推算
MM_PER_PX = 0.2711

# 我们要的托盘尺寸（mm）—— 画黄色框
TRAY_W_MM = 185.0
TRAY_H_MM = 190.0

# 赛规要求的托盘最小尺寸（mm）
TRAY_MIN_MM = 160.0

# A4 纸尺寸（mm）—— 画绿色框，用来定标
A4_W_MM = 210.0
A4_H_MM = 297.0

# 网格间距
PIXEL_GRID_STEP = 100     # 像素网格（白）
MM_GRID_STEP = 100        # 毫米网格（青）

# 是否在屏幕上显示（False = 只打印到 console）
SHOW_DISPLAY = True

# 是否叠加 A4 参考框（A4 竖放时 297mm 会超出画面，正常）
DRAW_A4 = True

# 是否叠加托盘参考框
DRAW_TRAY = True

# ═══════════════════════════════════════════════════════════════════════════
#  以下不用改
# ═══════════════════════════════════════════════════════════════════════════

import time


def mm_to_px_ratio() -> float:
    return 1.0 / MM_PER_PX if MM_PER_PX > 0 else 0.0


def calibrate_report() -> dict:
    """算出关键数字，打印并返回。"""
    fov_w_mm = FRAME_W * MM_PER_PX
    fov_h_mm = FRAME_H * MM_PER_PX

    # 由 mm/px 反推等效 FOV（假定方形像素、无畸变）
    import math
    half_w = fov_w_mm / 2.0
    half_h = fov_h_mm / 2.0
    fov_h_deg = 2.0 * math.degrees(math.atan(half_w / CAMERA_HEIGHT_MM))
    fov_v_deg = 2.0 * math.degrees(math.atan(half_h / CAMERA_HEIGHT_MM))

    tray_px_w = TRAY_W_MM / MM_PER_PX
    tray_px_h = TRAY_H_MM / MM_PER_PX

    # 要完整覆盖托盘 + 每边留 margin 需要多高
    def height_for(target_mm: float, margin: float = 0.15) -> float:
        need_mm = target_mm * (1.0 + 2 * margin)
        # need_mm = 2 * h * tan(half_fov_v)
        tan_v = (fov_h_mm / 2.0) / CAMERA_HEIGHT_MM * (FRAME_H / FRAME_W)
        # 重新精确算 tan(half vertical)
        tan_v = math.tan(math.radians(fov_v_deg / 2.0))
        return need_mm / (2.0 * tan_v)

    return {
        "fov_w_mm": fov_w_mm,
        "fov_h_mm": fov_h_mm,
        "fov_h_deg": fov_h_deg,
        "fov_v_deg": fov_v_deg,
        "tray_px_w": tray_px_w,
        "tray_px_h": tray_px_h,
        "tray_fits_w": tray_px_w <= FRAME_W,
        "tray_fits_h": tray_px_h <= FRAME_H,
        "tray_cover_w": tray_px_w / FRAME_W,
        "tray_cover_h": tray_px_h / FRAME_H,
        "min_tray_fits_h": TRAY_MIN_MM / MM_PER_PX <= FRAME_H,
        "height_for_tray": height_for(TRAY_H_MM),
        "height_for_min": height_for(TRAY_MIN_MM),
    }


def print_report(r: dict) -> None:
    print("=" * 68)
    print("  摄像头视野报告")
    print("=" * 68)
    print("  分辨率        : %d x %d" % (FRAME_W, FRAME_H))
    print("  相机高度      : %.1f mm" % CAMERA_HEIGHT_MM)
    print("  mm/px         : %.4f" % MM_PER_PX)
    print()
    print("  ── 画面覆盖范围 ──")
    print("  水平           : %.1f mm  (%.1f 度 FOV)" % (r["fov_w_mm"], r["fov_h_deg"]))
    print("  竖直           : %.1f mm  (%.1f 度 FOV)" % (r["fov_h_mm"], r["fov_v_deg"]))
    print()
    print("  ── 托盘 %.0fx%.0f mm ──" % (TRAY_W_MM, TRAY_H_MM))
    print("  需要像素       : %.0f x %.0f" % (r["tray_px_w"], r["tray_px_h"]))
    print("  水平占比       : %.1f%%  %s"
          % (r["tray_cover_w"] * 100,
             "OK 完整入画" if r["tray_fits_w"] else "❌ 超出画面！"))
    print("  竖直占比       : %.1f%%  %s"
          % (r["tray_cover_h"] * 100,
             "OK 完整入画" if r["tray_fits_h"] else "❌ 超出画面！"))
    print()
    print("  ── 赛规最小托盘 %.0fx%.0f mm（L44）──" % (TRAY_MIN_MM, TRAY_MIN_MM))
    print("  竖直是否够     : %s"
          % ("OK 够" if r["min_tray_fits_h"] else "❌ 不够"))
    print()
    print("  ── 要完整覆盖托盘需要多高 ──")
    print("  覆盖 %.0fx%.0f mm（每边留 15%%）: 需要相机高度 ≈ %.0f mm"
          % (TRAY_W_MM, TRAY_H_MM, r["height_for_tray"]))
    print("  覆盖 %.0fx%.0f mm（最小托盘）  : 需要相机高度 ≈ %.0f mm"
          % (TRAY_MIN_MM, TRAY_MIN_MM, r["height_for_min"]))
    print()
    if r["tray_fits_h"] and r["tray_fits_w"]:
        print("  >>> 结论：当前高度够，托盘能完整入画 <<<")
    else:
        print("  >>> 结论：当前高度【不够】，托盘会被裁掉 <<<")
        print("      要么把相机升高到 %.0f mm 以上，要么缩小托盘" % r["height_for_tray"])
    print()
    print("  ── 定标方法（提高 MM_PER_PX 准确度）──")
    print("  1. 把 A4 纸横放（长边 210mm 朝水平方向），贴着画面左边缘")
    print("  2. 看 A4 右边缘落在哪个像素 x（屏幕上青色网格可辅助读数）")
    print("  3. mm/px = 210.0 / (x_right - x_left)")
    print("  4. 把算出来的值填回本文件顶部 MM_PER_PX，重跑")
    print("=" * 68)


def main():
    try:
        from maix import app, camera, display, image
    except Exception as exc:
        print("=" * 60)
        print("导入 maix 模块失败：", exc)
        print("请确认你在 MaixCAM 上运行（不是在电脑上运行）")
        print("=" * 60)
        return

    print()

    # ── 1. 先打印数字（不开相机也能看）────────────────────────────────
    r = calibrate_report()
    print_report(r)
    print()

    # ── 2. 开相机（必须先于 display）──────────────────────────────────
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    except Exception as exc:
        print("!" * 60)
        print("打开相机失败：", exc)
        print("常见原因：相机被别的程序占着（stage1 / yolo_view / auto_capture）。")
        print("先把它停掉再跑本脚本。")
        print("!" * 60)
        return
    print("[1/3] camera OK  %dx%d" % (FRAME_W, FRAME_H))

    # ── 3. 开显示 ────────────────────────────────────────────────────
    disp = None
    if SHOW_DISPLAY:
        try:
            disp = display.Display()
            print("[2/3] display on")
        except Exception as exc:
            print("[2/3] display 打开失败（不影响 console 输出）：", exc)
            disp = None
    else:
        print("[2/3] display off（按配置关闭）")

    # ── 4. 预热 ──────────────────────────────────────────────────────
    print("[warmup] 等自动曝光/白平衡稳定 2 秒…")
    t0 = time.time()
    while (time.time() - t0) < 2.0:
        cam.read()
    print("[3/3] ready —— 看屏幕 / 按停止退出")
    print()
    print("  图例：白细线=100px  青粗线=100mm  黄框=托盘  绿框=A4  红十字=中心")
    print()

    # ── 5. 画图层 ────────────────────────────────────────────────────
    cx0, cy0 = FRAME_W // 2, FRAME_H // 2

    def draw_all(frame):
        # ── 像素网格（白，每 100px）─────────────────────────────────
        x = PIXEL_GRID_STEP
        while x < FRAME_W:
            frame.draw_line(x, 0, x, FRAME_H,
                            color=image.COLOR_WHITE, thickness=1)
            x += PIXEL_GRID_STEP
        y = PIXEL_GRID_STEP
        while y < FRAME_H:
            frame.draw_line(0, y, FRAME_W, y,
                            color=image.COLOR_WHITE, thickness=1)
            y += PIXEL_GRID_STEP

        # ── 毫米网格（青，每 100mm，以画面中心为原点）───────────────
        step_px = MM_GRID_STEP / MM_PER_PX
        k = 1
        while True:
            off = step_px * k
            if off > FRAME_W:
                break
            for xx in (int(cx0 - off), int(cx0 + off)):
                if 0 <= xx < FRAME_W:
                    frame.draw_line(xx, 0, xx, FRAME_H,
                                    color=image.COLOR_BLUE, thickness=2)
            k += 1
        k = 1
        while True:
            off = step_px * k
            if off > FRAME_H:
                break
            for yy in (int(cy0 - off), int(cy0 + off)):
                if 0 <= yy < FRAME_H:
                    frame.draw_line(0, yy, FRAME_W, yy,
                                    color=image.COLOR_BLUE, thickness=2)
            k += 1

        # ── 托盘框（黄）─────────────────────────────────────────────
        if DRAW_TRAY:
            tw = int(TRAY_W_MM / MM_PER_PX)
            th = int(TRAY_H_MM / MM_PER_PX)
            x1 = cx0 - tw // 2
            y1 = cy0 - th // 2
            x2 = cx0 + tw // 2
            y2 = cy0 + th // 2
            # 框可能超出画面 —— 画到边界为止（draw_rect 会自动裁，但要防负数）
            frame.draw_rect(max(0, x1), max(0, y1),
                            min(FRAME_W - 1, x2) - max(0, x1),
                            min(FRAME_H - 1, y2) - max(0, y1),
                            color=image.COLOR_YELLOW, thickness=3)
            frame.draw_string(
                max(2, x1 + 4), max(2, y1 + 4),
                "TRAY %.0fx%.0fmm" % (TRAY_W_MM, TRAY_H_MM),
                color=image.COLOR_YELLOW, scale=1.2)

        # ── A4 参考框（绿）──────────────────────────────────────────
        if DRAW_A4:
            aw = int(A4_W_MM / MM_PER_PX)
            ah = int(A4_H_MM / MM_PER_PX)
            x1 = cx0 - aw // 2
            y1 = cy0 - ah // 2
            x2 = cx0 + aw // 2
            y2 = cy0 + ah // 2
            frame.draw_rect(max(0, x1), max(0, y1),
                            min(FRAME_W - 1, x2) - max(0, x1),
                            min(FRAME_H - 1, y2) - max(0, y1),
                            color=image.COLOR_GREEN, thickness=2)
            frame.draw_string(
                max(2, x1 + 4), max(2, y1 + 20),
                "A4 210x297mm",
                color=image.COLOR_GREEN, scale=1.2)

        # ── 中心十字（红）───────────────────────────────────────────
        frame.draw_line(cx0 - 30, cy0, cx0 + 30, cy0,
                        color=image.COLOR_RED, thickness=2)
        frame.draw_line(cx0, cy0 - 30, cx0, cy0 + 30,
                        color=image.COLOR_RED, thickness=2)

        # ── 左上角信息面板 ──────────────────────────────────────────
        lines = [
            "FOV %.0f x %.0f mm" % (r["fov_w_mm"], r["fov_h_mm"]),
            "h=%.0fmm  mm/px=%.4f" % (CAMERA_HEIGHT_MM, MM_PER_PX),
            "TRAY %.0f%%x%.0f%% %s" % (
                r["tray_cover_w"] * 100, r["tray_cover_h"] * 100,
                "FITS" if (r["tray_fits_w"] and r["tray_fits_h"]) else "CUT!"),
        ]
        yy = 4
        for s in lines:
            frame.draw_string(4, yy, s, color=image.COLOR_WHITE, scale=1.3)
            yy += 26

    # ── 6. 主循环 ────────────────────────────────────────────────────
    try:
        while not app.need_exit():
            frame = cam.read()
            if disp is not None:
                draw_all(frame)
                disp.show(frame)
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("已手动停止")
    except Exception as exc:
        print("!" * 60)
        print("出错：", exc)
        print("!" * 60)

    print()
    print("=" * 68)
    print("  结束。要改参数就改本文件顶部【配置区】，重跑一次。")
    print("=" * 68)


main()
