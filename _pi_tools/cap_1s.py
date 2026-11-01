"""定时拍照采集 —— 每 1 秒存一张，就这么简单。2026-10-26

======================================================================
  设计原则：只存图，不做任何识别/标注
======================================================================
  因为托盘上会放**很多**物料（真实场景），自动标注必然失败。
  标注由后续环节处理（预标注工具 + 人工修）。

======================================================================
  用法（MaixVision）
======================================================================
  1. 打开 MaixVision，连 MaixCAM
  2. 新建 `cap_1s.py`，把本文件全部内容粘进去
  3. 改顶部 **SESSION_NAME**（比如 "whitetray_cone"）
  4. 确认补光灯亮着（树莓派发 `LIGHT ON`）
  5. 点运行（▶）
  6. 屏幕左上角显示：已存张数 / 运行时长 / 下一次存的时间
  7. 采够了 → 点停止
  8. 下载 `/root/dataset_raw/<SESSION_NAME>_<时间戳>/` 整个目录

======================================================================
  和之前脚本的区别
======================================================================
  本脚本 = **固定 1 秒间隔**，不判断画面变化，不识别物料。
  ⇒ 你放一堆物料上去，它就每秒存一张，简单可控。
  ⇒ 缺点：同一摆放会存很多重复图 —— 但**你可以自己控制时长**
     （摆好等 2~3 秒就够，别一直放着让它拍）。

======================================================================
  ⚠️ 注意
======================================================================
  · **补光灯必须全程亮着**（STM32 PC0，MaixCAM 管不了）
  · **别动相机/托盘/灯**（会引入域偏移）
  · **画面里不要出现手/工具**
  · 想换摆放 → 挪好了等 1~2 秒（会自动存 1~2 张）再挪下一个
"""

# ═══════════════════════════════════════════════════════════════════════════
#  【配置区】
# ═══════════════════════════════════════════════════════════════════════════

# 本次采集的名字（会作为子目录前缀）。改成一个能说明内容的词
#   例如："whitetray_all6"  "cone_only"  "mixed_13items"
SESSION_NAME = "whitetray"

# 拍照间隔（秒）。1.0 = 每秒一张
INTERVAL_S = 1.0

# 采集分辨率（必须 1280x720，与现有标定一致）
FRAME_W = 1280
FRAME_H = 720

# 输出根目录
OUTPUT_ROOT = "/root/dataset_raw"

# 相机刚启动时 AE/AWB 还在收敛，前几秒的图颜色不准，跳过
WARMUP_S = 3.0

# 屏幕预览
SHOW_DISPLAY = True

# JPEG 质量
JPEG_QUALITY = 92

# ═══════════════════════════════════════════════════════════════════════════
#  以下不用改
# ═══════════════════════════════════════════════════════════════════════════

import os
import time


def _fmt_time(sec):
    m, s = divmod(int(sec), 60)
    return "%d:%02d" % (m, s)


def main():
    try:
        from maix import app, camera, display, image
    except Exception as exc:
        print("=" * 60)
        print("导入 maix 模块失败：", exc)
        print("请确认你在 MaixCAM 上运行（不是在电脑上运行）")
        print("=" * 60)
        return

    session_dir = os.path.join(
        OUTPUT_ROOT, "%s_%d" % (SESSION_NAME, int(time.time())))
    try:
        os.makedirs(session_dir, exist_ok=True)
    except Exception as exc:
        print("创建目录失败：", session_dir, exc)
        return

    print("=" * 60)
    print("  定时拍照采集")
    print("=" * 60)
    print("  名称      : %s" % SESSION_NAME)
    print("  间隔      : %.2f 秒/张" % INTERVAL_S)
    print("  分辨率    : %d x %d" % (FRAME_W, FRAME_H))
    print("  输出目录  : %s" % session_dir)
    print("  预热      : %.1f 秒" % WARMUP_S)
    print("=" * 60)
    print()

    # 先开相机，再开显示（顺序反了会 SIGSEGV）
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    except Exception as exc:
        print("!" * 60)
        print("打开相机失败：", exc)
        print("常见原因：相机被别的程序占着（stage1 / yolo_view / fov_check / capture_dataset）。")
        print("先把那些停掉再跑本脚本。不要反复重试。")
        print("!" * 60)
        return
    print("[1/3] camera OK  %dx%d" % (FRAME_W, FRAME_H))

    disp = None
    if SHOW_DISPLAY:
        try:
            disp = display.Display()
            print("[2/3] display on")
        except Exception as exc:
            print("[2/3] display 打开失败（不影响采集）：", exc)
            disp = None
    else:
        print("[2/3] display off")

    if WARMUP_S > 0:
        print("[warmup] 跳过快 %.1f 秒，等 AE/AWB 稳定…" % WARMUP_S)
        t0 = time.time()
        while (time.time() - t0) < WARMUP_S:
            cam.read()
        print("[warmup] done")

    print("[3/3] ready —— 开始采")
    print()

    count = 0
    next_at = time.time() + INTERVAL_S
    t_start = time.time()

    try:
        while not app.need_exit():
            frame = cam.read()
            now = time.time()

            if now >= next_at:
                name = "img_%05d.jpg" % count
                path = os.path.join(session_dir, name)
                try:
                    frame.save(path, quality=JPEG_QUALITY)
                    count += 1
                    print("saved %s   (累计 %d 张, 已跑 %s)"
                          % (name, count, _fmt_time(now - t_start)))
                except Exception as exc:
                    print("保存失败:", path, exc)
                # 按固定间隔推进（不累积漂移；追不上就跳到下一个整点）
                next_at += INTERVAL_S
                if next_at < now:
                    next_at = now + INTERVAL_S

            if disp is not None:
                frame.draw_string(
                    4, 4, "REC  %s  n=%d  %s"
                    % (SESSION_NAME, count, _fmt_time(now - t_start)),
                    color=image.COLOR_GREEN, scale=1.5)
                frame.draw_string(
                    4, 40, "1 frame per %.1fs" % INTERVAL_S,
                    color=image.COLOR_WHITE, scale=1.2)
                # 距下一张还剩多久（做个进度符号，知道它在动）
                remain = max(0.0, next_at - now)
                frame.draw_string(
                    4, 70, "next in %.1fs" % remain,
                    color=image.COLOR_YELLOW, scale=1.1)
                disp.show(frame)
            else:
                time.sleep(0.02)

    except KeyboardInterrupt:
        print("\n已手动停止")
    except Exception as exc:
        print("!" * 60)
        print("采集中出错：", exc)
        print("!" * 60)

    print()
    print("=" * 60)
    print("  采集结束")
    print("=" * 60)
    print("  共 %d 张" % count)
    print("  目录：%s" % session_dir)
    print("  耗时：%s" % _fmt_time(time.time() - t_start))
    print()
    print("  下一步：用 MaixVision 的文件面板进入上面这个目录，")
    print("         把整个文件夹下载到电脑，然后告我。")
    print("=" * 60)


main()
