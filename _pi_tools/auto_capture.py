"""变化触发的自动采集 —— 你放物料，它自动存一张。2026-10-26

======================================================================
  用法（在 MaixCAM 上）
======================================================================
  1. 打开 MaixVision，连 MaixCAM
  2. 新建文件 `auto_capture.py`，把本文件**全部内容**粘进去
  3. **先确认补光灯亮着**（见下方"补光灯"一节）
  4. 点运行（▶）
  5. 屏幕左上角会显示状态：
       WAIT   等待你放物料
       MOVE   检测到画面在变（你正在放/挪）
       STABLE 已稳定，马上存
       SAVED  已存，计数 +1
       COOL   冷却中（防止连续存重复帧）
  6. 摆够了 → 点停止
  7. 用 MaixVision 文件面板进 `/root/capture/auto_<时间戳>/`，
     把整个目录下载到电脑

======================================================================
  它在干什么（和旧的固定间隔版有什么区别）
======================================================================
  旧版（capture_standalone.py）：每 1.0 秒存一张，
     结果同一摆放会被存几十张重复图 → 标注时白费工。

  本版：**只在"画面变了 + 变完稳定下来"的时候才存一张。**
     判据 = 当前帧与"上次保存的帧"的灰度平均差：
       · 差 > CHANGE_TH  ⇒ 正在变化 ⇒ 什么都不做
       · 差 < STABLE_TH 且 持续 STABLE_FRAMES 帧 ⇒ 稳定了 ⇒ 存
       · 存完把当前帧设为新的"基准帧"，进入 COOLDOWN_S 冷却
     ⇒ 你放一次料 = 存一张；不动 = 不存；挪了位置再放 = 再存一张。

  ⚠️ 保底：即使一直没检测到"变化后稳定"，也每 SAFETY_SAVE_S 秒
     强制存一张，防止某种情况下完全采不到。

======================================================================
  ⚠️ 重要提醒（踩过的坑）
======================================================================
  · **补光灯必须全程亮着**。灯在 STM32 的 PC0（WS2812），
    由树莓派发 `LIGHT ON` 控制，**MaixCAM 管不了**。
    开跑前在树莓派上发一次 `LIGHT ON`（或用你们的现成流程）。
  · **采集中途绝对不能动相机、托盘、灯**（会引入域偏移）
  · **画面里不要出现手、工具、胳膊**
  · 如果报 `No buffer space available` 或 `SIGSEGV`，说明相机被别的程序
    占着 —— **停下来告诉我们，不要自己反复重试**
  · 相机必须先开、显示后开（顺序反了会拿不到 VI/VPSS 缓冲 → SIGSEGV）
  · 分辨率必须 1280x720（和现有标定一致，不要改）
"""

# ═══════════════════════════════════════════════════════════════════════════
#  【配置区】只改这里
# ═══════════════════════════════════════════════════════════════════════════

# 采集分辨率（必须 1280x720，不要改 —— 与现有标定一致）
FRAME_W = 1280
FRAME_H = 720

# 输出根目录（每个 session 会在这里建一个 auto_<时间戳> 子目录）
OUTPUT_ROOT = "/root/capture"

# 变化检测用的缩略图尺寸（越小越快，64x36 已足够判断"变没变"）
DIFF_W = 64
DIFF_H = 36

# 判定"画面在变"的平均灰度差阈值（0~255）。越小越敏感
CHANGE_TH = 8.0

# 判定"稳定"的平均灰度差阈值（必须 < CHANGE_TH）
STABLE_TH = 3.0

# 连续多少帧"稳定"才算真的稳下来（30fps 下 10 帧 ≈ 0.33 秒）
STABLE_FRAMES = 10

# 保存后的冷却时间（秒），防止连拍同一摆放
COOLDOWN_S = 1.5

# 与"上次保存帧"的最小差（小于它就不存 —— 避免"放着不动也反复存"）
SAVE_MIN_DIFF = 5.0

# 保底强制保存间隔（秒）。设 0 = 关闭保底
SAFETY_SAVE_S = 30.0

# 相机启动时 AE/AWB 还在收敛，前几秒的图颜色不准，要跳过
WARMUP_S = 2.0

# 是否在屏幕上显示实时预览（True = 显示，方便你摆物料）
SHOW_DISPLAY = True

# JPEG 质量（85 一般够，数据集不必最高）
JPEG_QUALITY = 90

# ═══════════════════════════════════════════════════════════════════════════
#  以下不用改
# ═══════════════════════════════════════════════════════════════════════════

import os
import time


def _fmt_secs(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return "%d:%02d" % (m, sec) if m else "%ds" % sec


def main():
    # 延迟导入，方便报错时给清楚提示
    try:
        from maix import app, camera, display, image
    except Exception as exc:
        print("=" * 60)
        print("导入 maix 模块失败：", exc)
        print("请确认你在 MaixCAM 上运行（不是在电脑上运行）")
        print("=" * 60)
        return

    # ── 1. 建输出目录 ────────────────────────────────────────────────────
    session_dir = os.path.join(OUTPUT_ROOT, "auto_%d" % int(time.time()))
    try:
        os.makedirs(session_dir, exist_ok=True)
    except Exception as exc:
        print("=" * 60)
        print("创建输出目录失败：", session_dir, exc)
        print("=" * 60)
        return

    print("=" * 60)
    print("变化触发自动采集")
    print("=" * 60)
    print("采集目录  :", session_dir)
    print("分辨率    : %d x %d" % (FRAME_W, FRAME_H))
    print("变化阈值  : %.1f（> 判为在变）" % CHANGE_TH)
    print("稳定阈值  : %.1f（< 判为稳定）" % STABLE_TH)
    print("稳定帧数  : %d" % STABLE_FRAMES)
    print("冷却      : %.1f 秒" % COOLDOWN_S)
    print("保底保存  : %s" % ("每 %.0f 秒" % SAFETY_SAVE_S
                             if SAFETY_SAVE_S > 0 else "关闭"))
    print("=" * 60)
    print()

    # ── 2. 开相机（必须先于 display）─────────────────────────────────────
    try:
        # dual_buff=True 在 1280x720 RGB888 下会 No buffer space available → SIGSEGV
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    except Exception as exc:
        print("!" * 60)
        print("打开相机失败：", exc)
        print("")
        print("常见原因：相机被别的程序占着（比如还在跑 stage1 / yolo_view）。")
        print("请把这段日志截图发给我们，由我们远程处理。")
        print("不要自己反复重试 —— 反复开关会让驱动进入坏状态。")
        print("!" * 60)
        return
    print("[1/4] camera OK  %dx%d" % (FRAME_W, FRAME_H))

    # ── 3. 开显示（可关）────────────────────────────────────────────────
    disp = None
    if SHOW_DISPLAY:
        try:
            disp = display.Display()
            print("[2/4] display on")
        except Exception as exc:
            print("[2/4] display 打开失败（不影响采集）：", exc)
            disp = None
    else:
        print("[2/4] display off（按配置关闭）")

    # ── 4. 预热：丢弃前几帧，等 AE/AWB 收敛 ────────────────────────────
    if WARMUP_S > 0:
        print("[warmup] 跳过快 %.1f 秒，等自动曝光/白平衡稳定…" % WARMUP_S)
        t0 = time.time()
        while (time.time() - t0) < WARMUP_S:
            cam.read()
        print("[warmup] done")

    # ── 5. 内联：算两帧缩略图的平均灰度差 ──────────────────────────────
    def small_gray(frame):
        """把帧缩到 DIFF_W x DIFF_H 并转灰度，返回 Image（用于比较）。"""
        return frame.resize(DIFF_W, DIFF_H).to_format(image.Format.FMT_GRAYSCALE)

    def mean_diff(gray_a, gray_b) -> float:
        """两帧灰度的平均绝对差（0~255）。用 Image.difference + mean。"""
        try:
            diff = gray_a.difference(gray_b)
            return float(diff.mean())
        except Exception:
            # 兜底：逐像素采样（API 差异时用）
            n = 0
            total = 0.0
            for y in range(0, DIFF_H, 2):
                for x in range(0, DIFF_W, 2):
                    a = gray_a.get_pixel(x, y)
                    b = gray_b.get_pixel(x, y)
                    va = a[0] if isinstance(a, (tuple, list)) else a
                    vb = b[0] if isinstance(b, (tuple, list)) else b
                    total += abs(va - vb)
                    n += 1
            return total / n if n else 0.0

    # ── 6. 采集主循环 ────────────────────────────────────────────────────
    #
    # 🔴 关键设计（2026-10-26 修正）：
    #   必须用【两个】参考帧，不能只用一个。
    #
    #   prev_gray = 上一帧  → 判"现在在不在动"（帧间差）
    #   ref_gray  = 上次保存的帧 → 判"内容是否真的变了"（与基准差）
    #
    #   为什么不能只用一个（第一版写错、被自检抓到）：
    #     空托盘放上物件后，物件静止不动
    #     ⇒ 与"空托盘基准"的差一直很大（物件一直在）
    #     ⇒ 若用它判运动，就会一直判成 MOVE，stable_streak 永远归零
    #     ⇒ 【永远不保存】
    #
    #   正确逻辑：
    #     · 帧间差 < STABLE_TH 连续 N 帧  ⇒ 场景静止
    #     · 且 与上次保存帧的差 >= SAVE_MIN_DIFF ⇒ 内容确实不同
    #     · 且 不在冷却期
    #     ⇒ 才保存
    print("[3/4] ready —— 开始摆物料吧")
    print("[4/4] 状态会显示在屏幕上（WAIT/MOVE/STABLE/SAVED/COOL）")
    print()

    count = 0
    ref_gray = None          # "上次保存的帧"（判内容是否变了）
    prev_gray = None         # "上一帧"（判当前是否在动）
    stable_streak = 0        # 连续静止帧数
    last_save_t = 0.0        # 上次保存时刻
    last_safety_t = time.time()
    state = "WAIT"
    last_motion = 0.0        # 帧间差（运动量）
    last_content = 0.0       # 与基准差（内容差）
    t_start = time.time()

    try:
        while not app.need_exit():
            frame = cam.read()
            now = time.time()
            gray = small_gray(frame)

            # 第一帧：建立两个基准，不保存（此时托盘应是空的）
            if ref_gray is None:
                ref_gray = gray
                prev_gray = gray
                last_save_t = now
                last_safety_t = now
                if disp is not None:
                    frame.draw_string(4, 4, "WAIT  base set",
                                      color=image.COLOR_YELLOW, scale=1.5)
                    disp.show(frame)
                continue

            motion = mean_diff(gray, prev_gray)     # 帧间差 = 运动量
            content = mean_diff(gray, ref_gray)     # 与基准差 = 内容差
            prev_gray = gray
            last_motion = motion
            last_content = content

            in_cooldown = (now - last_save_t) < COOLDOWN_S

            # 静止判定：用帧间差（motion），不是内容差
            if motion < STABLE_TH:
                stable_streak += 1
                state = "STABLE"
            else:
                stable_streak = 0
                state = "MOVE"

            should_save = False
            reason = ""

            # 主判据：场景静止够久 + 内容确实与上次保存不同 + 不在冷却
            if (state == "STABLE"
                    and stable_streak >= STABLE_FRAMES
                    and content >= SAVE_MIN_DIFF
                    and not in_cooldown):
                should_save = True
                reason = "stable"

            # 保底：超时强制存（防止某种情况下一直检测不到稳定）
            if (not should_save
                    and SAFETY_SAVE_S > 0
                    and (now - last_safety_t) >= SAFETY_SAVE_S
                    and state == "STABLE"
                    and content >= SAVE_MIN_DIFF
                    and not in_cooldown):
                should_save = True
                reason = "safety"

            if should_save:
                img_path = os.path.join(session_dir, "img_%05d.jpg" % count)
                try:
                    frame.save(img_path, quality=JPEG_QUALITY)
                    print("SAVED %s   (第 %d 张, 内容差=%.1f, 运动=%.1f, %s, 已跑 %s)"
                          % (os.path.basename(img_path), count + 1,
                             content, motion, reason, _fmt_secs(now - t_start)))
                    count += 1
                    ref_gray = gray          # 更新"内容基准"
                    last_save_t = now
                    last_safety_t = now
                    stable_streak = 0
                    state = "SAVED"
                except Exception as exc:
                    print("保存失败:", img_path, exc)

            # ── 屏幕状态 ────────────────────────────────────────────────
            if disp is not None:
                colors = {
                    "WAIT": image.COLOR_YELLOW,
                    "MOVE": image.COLOR_ORANGE,
                    "STABLE": image.COLOR_BLUE,
                    "SAVED": image.COLOR_GREEN,
                    "COOL": image.COLOR_GRAY,
                }
                shown = "COOL" if in_cooldown and state != "SAVED" else state
                frame.draw_string(
                    4, 4, "%s n=%d mot=%.1f con=%.1f"
                    % (shown, count, motion, content),
                    color=colors.get(shown, image.COLOR_WHITE), scale=1.5)
                frame.draw_string(
                    4, 44, "put object -> auto save",
                    color=image.COLOR_WHITE, scale=1.2)
                disp.show(frame)

    except KeyboardInterrupt:
        print("")
        print("已手动停止")
    except Exception as exc:
        print("!" * 60)
        print("采集中出错：", exc)
        print("!" * 60)

    # ── 7. 结束汇总 ─────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("采集结束，共 %d 张" % count)
    print("目录：", session_dir)
    print("耗时：%s" % _fmt_secs(time.time() - t_start))
    print()
    print("下一步：用 MaixVision 的文件面板进入上面这个目录，")
    print("        把整个 session 文件夹下载到电脑。")
    print("=" * 60)


main()
