"""数据集采集 + 自动打标签 —— 按 (形状, 颜色) 分目录，自动生成 YOLO bbox。

======================================================================
  为什么这样设计
======================================================================
  之前只有「存图」，标签还得手工标 —— 400 张要几小时。
  本脚本在存图的同时**自动用 HSV 分割求出物料的 bbox，直接写 YOLO 标签**。

  前提：**画面里只有 1 个物料**（单件采集）。
        多于 1 个时会拒绝自动标注（只存图 + 警告），避免标签错乱。

  ⇒ 如果你一次要放多个物料（模拟真实托盘），关掉 AUTO_LABEL，
    只存图，回头用 `_pi_tools/prelabel_with_5c.py` + 人工修。

======================================================================
  用法（MaixVision）
======================================================================
  1. 打开 MaixVision，连 MaixCAM
  2. 新建 `capture_dataset.py`，把本文件全部内容粘进去
  3. **改顶部【配置区】的 SHAPE 和 COLOR**（下面有合法值列表）
  4. 确认补光灯亮着（在树莓派上发 `LIGHT ON`）
  5. 点运行（▶）
  6. 屏幕左上角会显示：
       SHAPE / COLOR / CLASS_ID / 已存张数 / 状态 / 自动标注结果
     · 绿色框   = 自动标注算出的 bbox（**看得见才敢信**）
     · 红字警告 = 检出 0 个或多个物料（此时不自动标）
  7. 放物料 → 画面稳定 → 自动存一张（看到 SAVED 计数 +1）
  8. 采够了 → 停止 → 下载 `/root/dataset/<shape>_<color>/`
  9. 换下一个 (形状, 颜色) → 改配置 → 重跑

======================================================================
  类别顺序（必须与 _dataset_yolo_6c/data.yaml 一致，不能改）
======================================================================
  0 = cube             正方体
  1 = cuboid           长方体
  2 = cylinder         圆柱
  3 = pentagonal_prism 五棱柱
  4 = cone             圆锥        ← 目前零数据，最优先
  5 = tetrahedron      正四面体

======================================================================
  ⚠️ 重要提醒
======================================================================
  · **补光灯必须全程亮着**（STM32 PC0，MaixCAM 管不了，要在树莓派发 LIGHT ON）
  · **采集中途不能动相机/托盘/灯**（会引入域偏移，标签也会错）
  · **画面里不要出现手/工具/胳膊**
  · 单件采集时**尽量把物料放在画面中央**，边缘会被镜头畸变影响
  · 一种 (形状,颜色) 建议采 **20~30 张不同摆放**（位置/角度/远近）
  · **圆锥最优先** —— 现在 0 数据，训练时这一类完全检不出
"""

# ═══════════════════════════════════════════════════════════════════════════
#  【配置区】每次采集改这两行
# ═══════════════════════════════════════════════════════════════════════════

# 当前采集的**形状**。合法值：
#   "cube"  "cuboid"  "cylinder"  "pentagonal_prism"  "cone"  "tetrahedron"
SHAPE = "cone"

# 当前采集的**颜色**。合法值：
#   "red"  "yellow"  "green"  "blue"  "white"
COLOR = "red"

# ── 以下一般不用改 ──────────────────────────────────────────────────────

# 采集分辨率（必须 1280x720，与现有标定一致）
FRAME_W = 1280
FRAME_H = 720

# 输出根目录。每个 (形状,颜色) 一个子目录
OUTPUT_ROOT = "/root/dataset"

# 是否自动生成 YOLO 标签（用 HSV 分割求 bbox）
#   True  = 单件采集，自动标（推荐）
#   False = 多件采集，只存图，回头用 prelabel 工具
AUTO_LABEL = True

# 自动标注时要求检出的物料数量（AUTO_LABEL=True 时生效）
EXPECTED_BLOBS = 1

# 自动标注的最小 bbox 面积（像素），太小说明分割失败
MIN_BBOX_AREA_PX = 1500

# 自动标注的最大 bbox 面积占比（超过说明把托盘/背景当下物料了）
MAX_BBOX_FRAC = 0.60

# ── 变化检测参数（与我验证过的 auto_capture 一致）────────────────────
DIFF_W = 64
DIFF_H = 36
STABLE_TH = 3.0          # 帧间差 < 它 ⇒ 认为静止
STABLE_FRAMES = 10       # 连续多少帧静止才算稳（30fps 下 ≈ 0.33s）
COOLDOWN_S = 1.2         # 存档后冷却，防连拍
SAVE_MIN_DIFF = 5.0      # 与上次存档的内容差 < 它 ⇒ 不值得存

# 预热（等 AE/AWB 收敛）
WARMUP_S = 2.0

# 屏幕预览
SHOW_DISPLAY = True

# JPEG 质量
JPEG_QUALITY = 92

# ═══════════════════════════════════════════════════════════════════════════
#  以下不用改
# ═══════════════════════════════════════════════════════════════════════════

import os
import time

# 类别顺序（与 _dataset_yolo_6c/data.yaml 对齐，不能改）
CLASS_NAMES = (
    "cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron")
CLASS_NAMES_ZH = (
    "正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体")

VALID_COLORS = ("red", "yellow", "green", "blue", "white")

# 各颜色的 HSV 窗口（用于自动标注时先验筛选；格式 (H_lo,S_lo,V_lo),(H_hi,S_hi,V_hi)）
# ⚠️ 红色 H 跨越 0 需要两个区间。当前实测：红 H171~173、黄 H20~22、绿 H69~75、蓝 H107~112
COLOR_HSV = {
    "red":    [((167, 80, 30), (179, 255, 255)), ((0, 80, 30), (8, 255, 255))],
    "yellow": [((15, 70, 40), (28, 255, 255))],
    "green":  [((60, 60, 30), (85, 255, 255))],
    "blue":   [((98, 70, 30), (125, 255, 255))],
    # 白色：低饱和 + 高亮度。⚠️ 白托盘也是白的，可能需要靠轮廓而非颜色
    "white":  [((0, 0, 175), (179, 60, 255))],
}


def _fmt_secs(s):
    m, sec = divmod(int(s), 60)
    return "%d:%02d" % (m, sec) if m else "%ds" % sec


def validate_config():
    """检查配置合法性，返回 (class_id, 错误信息)。"""
    if SHAPE not in CLASS_NAMES:
        return None, ("SHAPE=%r 不合法。合法值：%s" % (SHAPE, CLASS_NAMES))
    if COLOR not in VALID_COLORS:
        return None, ("COLOR=%r 不合法。合法值：%s" % (COLOR, VALID_COLORS))
    return CLASS_NAMES.index(SHAPE), None


def main():
    class_id, err = validate_config()
    if err:
        print("=" * 68)
        print("配置错误：", err)
        print("=" * 68)
        return

    try:
        from maix import app, camera, display, image
    except Exception as exc:
        print("=" * 68)
        print("导入 maix 模块失败：", exc)
        print("请确认你在 MaixCAM 上运行（不是在电脑上运行）")
        print("=" * 68)
        return

    # 尝试导入 cv2（MaixPy 一般自带）
    cv2 = None
    if AUTO_LABEL:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except Exception as exc:
            print("[warn] import cv2 失败，AUTO_LABEL 自动关闭：", exc)
            AUTO_LABEL = False

    shape_zh = CLASS_NAMES_ZH[class_id]

    # ── 建输出目录 ────────────────────────────────────────────────────
    session_tag = "%s_%s" % (SHAPE, COLOR)
    out_dir = os.path.join(OUTPUT_ROOT, session_tag)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as exc:
        print("创建目录失败：", out_dir, exc)
        return

    # 从已有文件数续编（避免覆盖）
    existing = [f for f in os.listdir(out_dir) if f.endswith(".jpg")]
    count = len(existing)

    print("=" * 68)
    print("  数据集采集 + 自动标注")
    print("=" * 68)
    print("  形状      : %s (%s)" % (SHAPE, shape_zh))
    print("  颜色      : %s" % COLOR)
    print("  class_id  : %d  （YOLO 标签第 1 列）" % class_id)
    print("  输出目录  : %s" % out_dir)
    print("  已存在    : %d 张（从 %05d 续编）" % (count, count))
    print("  自动标注  : %s" % ("开（HSV 分割求 bbox）" if AUTO_LABEL else "关（只存图）"))
    print("=" * 68)
    print()

    # ── 开相机（必须先于 display）────────────────────────────────────
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    except Exception as exc:
        print("!" * 68)
        print("打开相机失败：", exc)
        print("常见原因：相机被别的程序占着（stage1 / yolo_view / fov_check）。")
        print("先把那些停掉再跑本脚本。不要反复重试。")
        print("!" * 68)
        return
    print("[1/4] camera OK  %dx%d" % (FRAME_W, FRAME_H))

    # ── 开显示 ────────────────────────────────────────────────────────
    disp = None
    if SHOW_DISPLAY:
        try:
            disp = display.Display()
            print("[2/4] display on")
        except Exception as exc:
            print("[2/4] display 打开失败（不影响采集）：", exc)
            disp = None
    else:
        print("[2/4] display off")

    # ── 预热 ──────────────────────────────────────────────────────────
    if WARMUP_S > 0:
        print("[warmup] 跳过快 %.1f 秒，等 AE/AWB 稳定…" % WARMUP_S)
        t0 = time.time()
        while (time.time() - t0) < WARMUP_S:
            cam.read()

    # ── 工具函数 ──────────────────────────────────────────────────────
    def small_gray(frame):
        return frame.resize(DIFF_W, DIFF_H).to_format(image.Format.FMT_GRAYSCALE)

    def mean_diff(a, b):
        try:
            return float(a.difference(b).mean())
        except Exception:
            n = 0
            tot = 0.0
            for y in range(0, DIFF_H, 2):
                for x in range(0, DIFF_W, 2):
                    pa = a.get_pixel(x, y)
                    pb = b.get_pixel(x, y)
                    va = pa[0] if isinstance(pa, (tuple, list)) else pa
                    vb = pb[0] if isinstance(pb, (tuple, list)) else pb
                    tot += abs(va - vb)
                    n += 1
            return tot / n if n else 0.0

    def find_bbox(frame_rgb888):
        """在整幅图上找目标物料的 bbox。返回 (bbox 或 None, 说明)。

        用 cv2 把 MaixPy 帧转成 numpy，做 HSV 分割 + 形态学 + 取最大轮廓。
        ⚠️ 只在 AUTO_LABEL=True 时调用。
        """
        if cv2 is None:
            return None, "no cv2"
        try:
            import numpy as np
            # MaixPy Image → numpy: 用 to_bytes() 拿 RGB 原始字节
            raw = frame_rgb888.to_bytes()
            arr = np.frombuffer(raw, dtype=np.uint8)
            arr = arr.reshape((FRAME_H, FRAME_W, 3))
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        except Exception as exc:
            return None, "转 numpy 失败: %s" % exc

        ranges = COLOR_HSV.get(COLOR, [])
        if not ranges:
            return None, "该颜色没有 HSV 窗口"

        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = m if mask is None else cv2.bitwise_or(mask, m)

        # 形态学：闭运算补洞 + 开运算去噪
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, "0 个连通域"

        # 取面积最大的
        big = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(big)
        if area < MIN_BBOX_AREA_PX:
            return None, "面积 %.0f < %d" % (area, MIN_BBOX_AREA_PX)
        if area > FRAME_W * FRAME_H * MAX_BBOX_FRAC:
            return None, "面积 %.0f 太大（>%.0f%%）" % (
                area, MAX_BBOX_FRAC * 100)

        # 数量检查：面积 >= 最大者 50% 的连通域有几个
        n_big = sum(1 for c in contours
                    if cv2.contourArea(c) >= area * 0.5)
        if n_big != EXPECTED_BLOBS:
            return None, "检出 %d 个物料（期望 %d）" % (n_big, EXPECTED_BLOBS)

        x, y, w, h = cv2.boundingRect(big)
        return (x, y, w, h), "OK"

    def write_label(img_name, bbox):
        """写 YOLO 标签：class cx cy w h（归一化 0~1）。"""
        x, y, w, h = bbox
        cx = (x + w / 2.0) / FRAME_W
        cy = (y + h / 2.0) / FRAME_H
        nw = w / float(FRAME_W)
        nh = h / float(FRAME_H)
        label_path = os.path.join(out_dir, img_name[:-4] + ".txt")
        with open(label_path, "w", encoding="utf-8") as f:
            f.write("%d %.6f %.6f %.6f %.6f\n"
                    % (class_id, cx, cy, nw, nh))
        return label_path

    # ── 主循环 ────────────────────────────────────────────────────────
    print("[3/4] ready —— 放物料吧")
    print("[4/4] 状态：WAIT / MOVE / STABLE / SAVED / COOL")
    print()

    ref_gray = None      # 上次存档的帧（判内容变化）
    prev_gray = None     # 上一帧（判当前是否在动）
    streak = 0
    last_save_t = 0.0
    last_bbox = None
    last_msg = ""
    state = "WAIT"
    t_start = time.time()
    n_ok = 0             # 本 session 成功存了多少
    n_fail = 0           # 自动标注失败多少次

    try:
        while not app.need_exit():
            frame = cam.read()
            now = time.time()
            gray = small_gray(frame)

            if ref_gray is None:
                ref_gray = prev_gray = gray
                last_save_t = now
                if disp is not None:
                    frame.draw_string(4, 4, "WAIT  base set",
                                      color=image.COLOR_YELLOW, scale=1.3)
                    disp.show(frame)
                continue

            motion = mean_diff(gray, prev_gray)
            content = mean_diff(gray, ref_gray)
            prev_gray = gray

            in_cool = (now - last_save_t) < COOLDOWN_S

            if motion < STABLE_TH:
                streak += 1
                state = "STABLE"
            else:
                streak = 0
                state = "MOVE"

            should_save = (state == "STABLE"
                           and streak >= STABLE_FRAMES
                           and content >= SAVE_MIN_DIFF
                           and not in_cool)

            if should_save:
                img_name = "img_%05d.jpg" % count
                img_path = os.path.join(out_dir, img_name)
                bbox = None
                msg = ""
                if AUTO_LABEL:
                    bbox, msg = find_bbox(frame)
                last_bbox = bbox
                last_msg = msg

                try:
                    frame.save(img_path, quality=JPEG_QUALITY)
                except Exception as exc:
                    print("  存图失败：", img_path, exc)
                    continue

                if AUTO_LABEL and bbox is not None:
                    try:
                        write_label(img_name, bbox)
                        n_ok += 1
                        print("SAVED %s  bbox=(%d,%d,%d,%d)  [%d 张, %s]"
                              % (img_name, bbox[0], bbox[1], bbox[2], bbox[3],
                                 count + 1, _fmt_secs(now - t_start)))
                    except Exception as exc:
                        print("  写标签失败：", exc)
                elif AUTO_LABEL:
                    n_fail += 1
                    print("SAVED %s  ⚠️ 未自动标注：%s  （图已存，需手工补）"
                          % (img_name, msg))
                else:
                    print("SAVED %s  [%d 张, %s]"
                          % (img_name, count + 1, _fmt_secs(now - t_start)))

                count += 1
                ref_gray = gray
                last_save_t = now
                streak = 0
                state = "SAVED"

            # ── 屏幕 ──────────────────────────────────────────────────
            if disp is not None:
                colors = {
                    "WAIT": image.COLOR_YELLOW, "MOVE": image.COLOR_ORANGE,
                    "STABLE": image.COLOR_BLUE, "SAVED": image.COLOR_GREEN,
                    "COOL": image.COLOR_GRAY,
                }
                shown = "COOL" if in_cool and state != "SAVED" else state
                frame.draw_string(
                    4, 4, "%s  %s/%s  cls=%d  n=%d"
                    % (shown, SHAPE, COLOR, class_id, count),
                    color=colors.get(shown, image.COLOR_WHITE), scale=1.3)
                frame.draw_string(
                    4, 34, "mot=%.1f con=%.1f  %s"
                    % (motion, content, last_msg[:28]),
                    color=image.COLOR_WHITE, scale=1.1)

                # 把上次算出来的 bbox 画出来（看得见才敢信自动标注）
                if last_bbox is not None:
                    bx, by, bw, bh = last_bbox
                    frame.draw_rect(bx, by, bw, bh,
                                    color=image.COLOR_GREEN, thickness=3)
                else:
                    frame.draw_string(4, 60, "no bbox (auto-label failed)",
                                      color=image.COLOR_RED, scale=1.1)

                disp.show(frame)

    except KeyboardInterrupt:
        print("\n已手动停止")
    except Exception as exc:
        print("!" * 68)
        print("采集中出错：", exc)
        print("!" * 68)

    # ── 汇总 ──────────────────────────────────────────────────────────
    print()
    print("=" * 68)
    print("  采集结束")
    print("=" * 68)
    print("  形状/颜色 : %s / %s   (class_id=%d)" % (SHAPE, COLOR, class_id))
    print("  目录      : %s" % out_dir)
    print("  总文件    : %d 张 .jpg" % count)
    if AUTO_LABEL:
        print("  自动标注  : 成功 %d，失败 %d" % (n_ok, n_fail))
        if n_fail:
            print("  ⚠️ 有 %d 张没自动标注，需要手工补（或删掉重拍）" % n_fail)
    print()
    print("  下一步：")
    print("    1. 用 MaixVision 文件面板把 %s 整个目录下载到电脑" % session_tag)
    print("    2. 抽查几张：打开图看框是否贴住物料")
    print("    3. 换下一个 (形状,颜色) → 改顶部 SHAPE/COLOR → 重跑")
    print("    4. 全部采完 → 把各目录的图/标放进 _dataset_yolo_6c/")
    print("       images/train + labels/train（或 val）")
    print("=" * 68)


main()
