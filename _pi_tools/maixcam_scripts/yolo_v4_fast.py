"""MaixCAM v4 模型**快速观测版**（不卡）  2026-10-27

## 跟 yolo_v4_bench.py 的区别

bench 版每帧都在 1280×720 上算 5 个 HSV 掩膜 + 形态学 + 缩略图，
实测吃掉 65~95 ms/帧，把 15 fps 拖到 6~8 fps。

本版做了三件事把它拉回来：
  1. **掩膜降到 1/4 尺寸算**（230×180 而不是 1280×720）→ 快 16 倍
  2. **掩膜每 MASK_EVERY 帧才重算一次**（默认 15），中间的帧直接用缓存
  3. **默认不画底栏**，要调 HSV 时把 SHOW_MASK_STRIP 改成 1

另外每 PRINT_EVERY 帧打印**耗时分解**（detect / draw / mask / show），
哪一段慢一眼就看出来。

## 用法

默认（最快，只看 YOLO 效果）：
```
直接运行
```

要调 HSV 时（带底栏掩膜）：
```
把 SHOW_MASK_STRIP 改成 1
```

只要最纯粹的速度（连顶栏都省）：
```
把 SHOW_TOPBAR 改成 0
```

## 配置速查

| 配置 | 默认 | 说明 |
|---|---|---|
| `CONF_TH` | 0.30 | 置信度阈值 |
| `SHOW_MASK_STRIP` | **0** | 底栏颜色掩膜（调 HSV 时开）|
| `MASK_EVERY` | 15 | 每多少帧重算掩膜 |
| `MASK_SCALE` | 0.25 | 掩膜计算用的缩放 |
| `SHOW_TOPBAR` | 1 | 顶部状态条 |
| `PRINT_EVERY` | 30 | 统计打印间隔 |
| `WARMUP_S` | 2.0 | 预热（AE/AWB 收敛）|

## ⚠️ 已知坑（别改）

1. `dual_buff=True` 会 SIGSEGV ⇒ 必须 False
2. 加载顺序 相机 → 显示 → 模型
3. `detect()` 传 maix 的 image.Image（frame），不是 numpy
4. 屏幕 552×368，画布 1280×720 ⇒ 字号要 ×2.3
"""
from __future__ import annotations

import os
import time
from collections import Counter

import cv2
import numpy as np

from maix import app, camera, display, image, nn

# ══════════════════════ 配置 ══════════════════════
MODEL_DIR = os.environ.get("MODEL_DIR", "/root/my_models")
MODEL_NAME = os.environ.get("MODEL_NAME", "yolo11n_6c_v4_448_cv181x")
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME + ".mud")

FRAME_W = int(os.environ.get("FRAME_W", "1280"))
FRAME_H = int(os.environ.get("FRAME_H", "720"))

CONF_TH = float(os.environ.get("CONF_TH", "0.30"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
DUAL_BUFF = False                     # 坑 #1

SHOW_TOPBAR = os.environ.get("SHOW_TOPBAR", "1") == "1"
SHOW_MASK_STRIP = os.environ.get("SHOW_MASK_STRIP", "0") == "1"   # 默认关
MASK_EVERY = int(os.environ.get("MASK_EVERY", "15"))
MASK_SCALE = float(os.environ.get("MASK_SCALE", "0.25"))
PRINT_EVERY = int(os.environ.get("PRINT_EVERY", "30"))
WARMUP_S = float(os.environ.get("WARMUP_S", "2.0"))

UI_SCALE = float(os.environ.get("UI_SCALE", "2.3"))   # 坑 #4

LABELS = ["cube", "cuboid", "cylinder",
          "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}
CLS_RGB = {
    0: (60, 220, 60), 1: (60, 200, 255), 2: (80, 80, 255),
    3: (230, 80, 230), 4: (255, 200, 40), 5: (40, 255, 255),
}
COLOR_RANGES = {
    "红": [((0, 95, 35), (2, 255, 255)), ((173, 95, 35), (179, 255, 255))],
    "黄": [((24, 95, 45), (35, 255, 255))],
    "绿": [((36, 95, 35), (84, 255, 255))],
    "蓝": [((105, 95, 30), (137, 255, 255))],
    "白": [((0, 0, 150), (179, 40, 255))],
}
STRIP_COLORS = [(220, 60, 60), (240, 210, 60), (60, 220, 60),
                (70, 120, 255), (230, 230, 230)]


# ══════════════════════ 掩膜（慢，所以降采样 + 降频）══════════════════════
def compute_masks_fast(rgb: np.ndarray):
    """在 1/MASK_SCALE 尺寸上算 5 个掩膜。

    返回三元组 (masks, pcts, ms)：
      masks : 缩略尺寸的掩膜字典（只用于画底栏）
      pcts  : 各色占全图的真实百分比
      ms    : 本函数耗时（毫秒）
    """
    t0 = time.time()
    small = cv2.resize(rgb, None, fx=MASK_SCALE, fy=MASK_SCALE,
                       interpolation=cv2.INTER_NEAREST)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    masks = {}
    pcts = {}
    n_small = float(small.shape[0] * small.shape[1])
    for name, ranges in COLOR_RANGES.items():
        m = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            m = part if m is None else cv2.bitwise_or(m, part)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        masks[name] = m
        pcts[name] = cv2.countNonZero(m) / n_small * 100.0
    return masks, pcts, (time.time() - t0) * 1000.0


def draw_strip_cached(rgb: np.ndarray, masks: dict[str, np.ndarray],
                      pcts: dict[str, float]) -> None:
    """把缓存的缩略掩膜贴到底栏（每帧都要贴，但贴很便宜）。"""
    H, W = rgb.shape[:2]
    n = len(masks)
    tw = W // n
    th = max(60, int(round(H / 7)))
    y0 = H - th
    fs = 0.40 * UI_SCALE
    ft = max(1, int(round(UI_SCALE * 0.55)))
    pad = max(2, int(round(3 * UI_SCALE)))
    txt_h = int(round(18 * UI_SCALE))
    names = list(masks.keys())
    for i, name in enumerate(names):
        x0 = i * tw
        small = cv2.resize(masks[name], (tw - 2, th - 2),
                           interpolation=cv2.INTER_NEAREST)
        tile = np.zeros((th - 2, tw - 2, 3), np.uint8)
        tile[small > 0] = STRIP_COLORS[i]
        rgb[y0 + 1:y0 + th - 1, x0 + 1:x0 + tw - 1] = tile
        cv2.rectangle(rgb, (x0 + 1, y0 + 1), (x0 + tw - 2, y0 + txt_h),
                      (0, 0, 0), -1)
        cv2.putText(rgb, "%s %.1f%%" % (name, pcts.get(name, 0.0)),
                    (x0 + pad, y0 + txt_h - pad),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), ft,
                    cv2.LINE_AA)
        cv2.rectangle(rgb, (x0, y0), (x0 + tw - 1, H - 1), (60, 60, 60), 1)


# ══════════════════════ 绘制 ══════════════════════
def draw_boxes(rgb: np.ndarray, objs) -> Counter:
    cnt = Counter()
    th = max(2, int(round(2 * UI_SCALE)))
    fs = 0.42 * UI_SCALE
    ft = max(1, int(round(UI_SCALE * 0.6)))
    pad = max(4, int(round(4 * UI_SCALE)))
    for o in objs:
        cls = int(o.class_id)
        x, y, w, h = int(o.x), int(o.y), int(o.w), int(o.h)
        col = CLS_RGB.get(cls, (255, 255, 255))
        cv2.rectangle(rgb, (x, y), (x + w, y + h), col, th)
        nm = LABELS[cls] if 0 <= cls < len(LABELS) else str(cls)
        text = "%s %.2f" % (ZH.get(nm, nm), float(o.score))
        (tw, txt_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                         fs, ft)
        ty = max(0, y - txt_h - pad)
        cv2.rectangle(rgb, (x, ty), (x + tw + pad, ty + txt_h + pad),
                      (0, 0, 0), -1)
        cv2.putText(rgb, text, (x + pad // 2, ty + txt_h + pad // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, col, ft, cv2.LINE_AA)
        cnt[cls] += 1
    return cnt


def draw_topbar(rgb: np.ndarray, fps: float, ms: float, n: int) -> None:
    W = rgb.shape[1]
    bar_h = int(round(30 * UI_SCALE))
    cv2.rectangle(rgb, (0, 0), (W, bar_h), (0, 0, 0), -1)
    txt = "%d obj | %.1f FPS | yolo %.1f ms" % (n, fps, ms)
    cv2.putText(rgb, txt, (4, bar_h - int(round(8 * UI_SCALE))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45 * UI_SCALE, (80, 255, 80),
                max(1, int(round(UI_SCALE * 0.6))), cv2.LINE_AA)


# ══════════════════════ 主流程 ══════════════════════
def main():
    print("=" * 66)
    print("  MaixCAM v4 六类 · 快速观测版")
    print("=" * 66)
    print("  MODEL      = %s" % MODEL_NAME)
    print("  FRAME      = %dx%d  CONF=%.2f" % (FRAME_W, FRAME_H, CONF_TH))
    print("  顶栏       = %s   底栏掩膜 = %s (每 %d 帧 @ %.2f 尺寸)"
          % (SHOW_TOPBAR, SHOW_MASK_STRIP, MASK_EVERY, MASK_SCALE))
    print()

    if not os.path.exists(MODEL_PATH):
        print("❌ 模型不存在: %s" % MODEL_PATH)
        return

    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
        print("[1/3] camera OK")
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   先执行：killall launcher_daemon")
        return

    disp = display.Display()
    print("[2/3] display OK")

    try:
        detector = nn.YOLO11(model=MODEL_PATH, dual_buff=DUAL_BUFF)
    except Exception as e:
        print("❌ 模型加载失败: %s" % e)
        return
    print("[3/3] YOLO11 OK  input %dx%d"
          % (detector.input_width(), detector.input_height()))

    print("预热 %.1f s ..." % WARMUP_S)
    t0 = time.time()
    while time.time() - t0 < WARMUP_S and not app.need_exit():
        cam.read()
    print("开始（Ctrl-C / MaixVision 停止）")
    print("-" * 66)

    # 掩膜缓存
    cached_masks = None
    cached_pcts = {}

    fps = 0.0
    last_t = time.time()
    n = 0
    t_start = time.time()
    # 耗时累计
    acc = {"detect": 0.0, "draw": 0.0, "mask": 0.0, "show": 0.0}
    acc_n = 0

    try:
        while not app.need_exit():
            frame = cam.read()
            if frame is None:
                continue
            rgb = image.image2cv(frame, ensure_bgr=False, copy=False)

            # ── YOLO（必须先于绘制）──
            t1 = time.time()
            try:
                objs = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)
            except Exception as e:
                print("detect 异常: %s" % e)
                objs = []
            ms_detect = (time.time() - t1) * 1000.0

            n += 1
            if n % 10 == 0:
                now = time.time()
                fps = 10.0 / max(1e-6, now - last_t)
                last_t = now

            # ── 掩膜（降频 + 降采样）──
            ms_mask = 0.0
            if SHOW_MASK_STRIP and (cached_masks is None or
                                    n % MASK_EVERY == 0):
                try:
                    cached_masks, cached_pcts, ms_mask = compute_masks_fast(rgb)
                except Exception as e:
                    if n % 60 == 0:
                        print("掩膜异常: %s" % e)

            # ── 绘制 ──
            t2 = time.time()
            if SHOW_TOPBAR:
                draw_topbar(rgb, fps, ms_detect, len(objs))
            cnt = draw_boxes(rgb, objs)
            if SHOW_MASK_STRIP and cached_masks is not None:
                draw_strip_cached(rgb, cached_masks, cached_pcts)
            ms_draw = (time.time() - t2) * 1000.0

            # ── 显示 ──
            t3 = time.time()
            disp.show(frame)
            ms_show = (time.time() - t3) * 1000.0

            acc["detect"] += ms_detect
            acc["draw"] += ms_draw
            acc["mask"] += ms_mask
            acc["show"] += ms_show
            acc_n += 1

            # ── 统计 ──
            if n % PRINT_EVERY == 0:
                el = time.time() - t_start
                print("[帧 %d  %.1fs] %.1f FPS   %d 个物件"
                      % (n, el, fps, len(objs)))
                if cnt:
                    print("    类别: %s" % "  ".join(
                        "%s×%d" % (LABELS[c] if c < len(LABELS) else str(c),
                                   cnt[c]) for c in sorted(cnt)))
                if acc_n:
                    print("    耗时分解（平均）: yolo %.1f | 绘制 %.1f | "
                          "掩膜 %.1f | show %.1f  合计 %.1f ms"
                          % (acc["detect"] / acc_n, acc["draw"] / acc_n,
                             acc["mask"] / acc_n, acc["show"] / acc_n,
                             (acc["detect"] + acc["draw"] + acc["mask"]
                              + acc["show"]) / acc_n))
                    acc = {k: 0.0 for k in acc}
                    acc_n = 0
                print("-" * 66)

            del rgb

    except KeyboardInterrupt:
        print("用户中断")
    finally:
        el = time.time() - t_start if 't_start' in locals() else 0.0
        print("=" * 66)
        print("结束：%.1f s，%d 帧，平均 %.2f FPS"
              % (el, n, n / el if el > 0 else 0.0))
        print("=" * 66)


if __name__ == "__main__":
    main()
