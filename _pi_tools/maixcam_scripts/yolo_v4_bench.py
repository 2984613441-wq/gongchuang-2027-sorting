"""MaixCAM v4 模型实测 + 补光灯下 HSV 调参助手  2026-10-27

## 干什么

在 MaixCAM 上跑 **v4 六类模型**（mAP50 0.9802），把结果画出来，
同时**实时测量每个物件的 HSV 中位数并打印** —— 开了补光灯以后
颜色窗口会整体偏移，你照着打印出来的数改阈值就行，不用猜。

## 界面布局

```
┌──────────────────────────────────────┐
│ 顶栏: 模型名 分辨率 FPS 耗时 物件数   │
│                                      │
│      主画面: YOLO 框 + 类别 + 置信度  │
│      (每类不同颜色, 中文+英文)        │
│                                      │
├──────────────────────────────────────┤
│ 底栏: 5 个颜色掩膜缩略图              │
│  R  Y  G  B  W  ← 白平衡后每个的实际面积 │
└──────────────────────────────────────┘
```

## 用之前必须先传模型（两台机器都在线时）

PC 上（热点开启后）：
```
scp _deploy_maixcam/yolo11n_6c_v4_448_cv181x.cvimodel root@172.20.10.9:/root/my_models/
scp _deploy_maixcam/yolo11n_6c_v4_448_cv181x.mud      root@172.20.10.9:/root/my_models/
```

或者用 MaixVision 的「文件」面板手动拖进去，目标目录 `/root/my_models/`。

⚠️ `.mud` 里的 `model=` 必须和 `.cvimodel` 文件名一致。

## 在 MaixVision 里怎么跑

把本文件内容粘贴到 MaixVision 新建脚本里，直接点运行。
停止后看 MaixVision 的控制台输出（有 HSV 统计）。

## 可调配置

| 配置 | 说明 |
|---|---|
| `MODEL_NAME` | 模型名（不带扩展名）|
| `CONF_TH` | 置信度阈值，默认 0.30；调高看误检，调低看漏检 |
| `IOU_TH` | NMS IoU 阈值 |
| `SHOW_MASK_STRIP` | 是否显示底栏颜色掩膜 |
| `PRINT_EVERY` | 每多少帧打印一次统计 |
| `WARMUP_S` | 预热秒数（等 AE/AWB 收敛，开补光灯后建议加到 3.0）|

## ⚠️ 实测踩过的坑（别改）

1. **`dual_buff=True` 会 SIGSEGV**（No buffer space available）⇒ 必须 False
2. **加载顺序：相机 → 显示 → 模型**，先加载模型会吃光缓冲导致相机打不开
3. **`maix.image.draw_rect` 的 color 必须是 `image.Color` 对象**，
   传 tuple 会 TypeError ⇒ 本脚本改用 cv2 在 numpy 视图上画，绕开这个坑
4. **白色物料在白托盘上 HSV 分不开**（S 都低）—— 这是物理难点，
   底栏的 W 掩膜会连托盘一起点亮，属正常现象，不要据此调阈值
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
DUAL_BUFF = False          # 🔴 必须 False，见文件头坑 #1

SHOW_MASK_STRIP = os.environ.get("SHOW_MASK_STRIP", "1") == "1"
PRINT_EVERY = int(os.environ.get("PRINT_EVERY", "30"))
WARMUP_S = float(os.environ.get("WARMUP_S", "3.0"))   # 开补光灯后建议 3.0

# 六类（与 .mud labels 一致）
LABELS = ["cube", "cuboid", "cylinder",
          "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}

# 每类画框颜色（**RGB**，因为 image2cv 用 ensure_bgr=False）
CLS_RGB = {
    0: (60, 220, 60),     # cube        绿
    1: (60, 200, 255),    # cuboid      橙黄
    2: (80, 80, 255),     # cylinder    红
    3: (230, 80, 230),    # pentagonal  紫
    4: (255, 200, 40),    # cone        青蓝
    5: (40, 255, 255),    # tetrahedron 黄
}

# 五个赛规颜色窗口（HSV：H 0-179, S/V 0-255）—— 补光灯下需要改这里
# 来源：视觉/src/maixcam_deploy/calib_grid.py 的实测值
COLOR_RANGES = {
    "红 red":    [((0, 95, 35), (2, 255, 255)), ((173, 95, 35), (179, 255, 255))],
    "黄 yellow": [((24, 95, 45), (35, 255, 255))],
    "绿 green":  [((36, 95, 35), (84, 255, 255))],
    "蓝 blue":   [((105, 95, 30), (137, 255, 255))],
    "白 white":  [((0, 0, 150), (179, 40, 255))],
}
STRIP_COLORS = [(220, 60, 60), (240, 210, 60), (60, 220, 60),
                (70, 120, 255), (230, 230, 230)]

MIN_AREA_RATIO = 0.0008    # 掩膜最小面积（占全图比例），滤掉噪点

# 🔴 实测：MaixCAM Pro 屏幕只有 552x368，而我们在 1280x720 的画布上绘制。
#    disp.show() 会把 1280x720 缩到 552x368（缩放比 0.43），
#    所以所有字号和线宽都要**先放大 ~2.3 倍**，否则屏幕上小到看不清。
#    UI_SCALE = 1280 / 552 ≈ 2.32，取 2.3。
UI_SCALE = float(os.environ.get("UI_SCALE", "2.3"))


# ══════════════════════ 工具 ══════════════════════
def build_masks(rgb: np.ndarray) -> dict[str, np.ndarray]:
    """返回 5 个颜色掩膜（已做形态学清理）。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    out = {}
    for name, ranges in COLOR_RANGES.items():
        m = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            m = part if m is None else cv2.bitwise_or(m, part)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        out[name] = m
    return out


def hsv_median_of_box(rgb: np.ndarray, x: int, y: int, w: int, h: int,
                      shrink: float = 0.25):
    """取框内缩后的 HSV 中位数（缩边避开边缘混色和阴影）。"""
    H, W = rgb.shape[:2]
    dx = int(w * shrink)
    dy = int(h * shrink)
    x1 = max(0, x + dx); y1 = max(0, y + dy)
    x2 = min(W, x + w - dx); y2 = min(H, y + h - dy)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    roi = rgb[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    hch = hsv[:, :, 0].ravel()
    sch = hsv[:, :, 1].ravel()
    vch = hsv[:, :, 2].ravel()
    # 只统计「有颜色」的像素（S 高于中位），避免把白托盘算进去
    smed = float(np.median(sch))
    if smed > 40:
        keep = sch >= smed
        hch = hch[keep]
    return (float(np.median(hch)), float(np.median(sch)), float(np.median(vch)),
            int(np.mean(sch > 60) * 100))


def draw_boxes(rgb: np.ndarray, objs) -> Counter:
    """画框 + 统计每类数量。（尺寸按 UI_SCALE 放大，适配 552x368 小屏）"""
    cnt = Counter()
    th = max(2, int(round(2 * UI_SCALE)))          # 框线宽
    fs = 0.42 * UI_SCALE                            # 字号
    ft = max(1, int(round(1 * UI_SCALE * 0.6)))     # 文字线宽
    for o in objs:
        cls = int(o.class_id)
        x, y, w, h = int(o.x), int(o.y), int(o.w), int(o.h)
        col = CLS_RGB.get(cls, (255, 255, 255))
        cv2.rectangle(rgb, (x, y), (x + w, y + h), col, th)

        name = LABELS[cls] if 0 <= cls < len(LABELS) else str(cls)
        zh = ZH.get(name, "")
        text = "%d.%s %s %.2f" % (cls, name, zh, float(o.score))
        (tw, txt_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                         fs, ft)
        pad = max(4, int(round(4 * UI_SCALE)))
        ty = max(0, y - txt_h - pad)
        cv2.rectangle(rgb, (x, ty), (x + tw + pad, ty + txt_h + pad),
                      (0, 0, 0), -1)
        cv2.putText(rgb, text, (x + pad // 2, ty + txt_h + pad // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, col, ft, cv2.LINE_AA)
        cnt[cls] += 1
    return cnt


def draw_strip(rgb: np.ndarray, masks: dict[str, np.ndarray]) -> None:
    """底部画 5 个颜色掩膜缩略图。（尺寸按 UI_SCALE 适配小屏）"""
    H, W = rgb.shape[:2]
    n = len(masks)
    tw = W // n
    th = max(60, int(round(H / 7)))          # 底栏高度
    y0 = H - th
    total_area = float(W * H)
    fs = 0.40 * UI_SCALE
    ft = max(1, int(round(UI_SCALE * 0.55)))
    pad = max(2, int(round(3 * UI_SCALE)))
    for i, (name, m) in enumerate(masks.items()):
        x0 = i * tw
        small = cv2.resize(m, (tw - 2, th - 2), interpolation=cv2.INTER_AREA)
        tile = np.zeros((th - 2, tw - 2, 3), np.uint8)
        tile[small > 0] = STRIP_COLORS[i]
        rgb[y0 + 1:y0 + th - 1, x0 + 1:x0 + tw - 1] = tile
        # 面积百分比
        pct = cv2.countNonZero(m) / total_area * 100.0
        label = "%s %.1f%%" % (name.split()[0], pct)
        txt_h = int(round(18 * UI_SCALE))
        cv2.rectangle(rgb, (x0 + 1, y0 + 1), (x0 + tw - 2, y0 + txt_h),
                      (0, 0, 0), -1)
        cv2.putText(rgb, label, (x0 + pad, y0 + txt_h - pad),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), ft,
                    cv2.LINE_AA)
        cv2.rectangle(rgb, (x0, y0), (x0 + tw - 1, H - 1), (60, 60, 60), 1)


def draw_topbar(rgb: np.ndarray, fps: float, ms: float, n: int) -> None:
    """顶部状态条。（尺寸按 UI_SCALE 适配小屏）"""
    H, W = rgb.shape[:2]
    bar_h = int(round(30 * UI_SCALE))
    cv2.rectangle(rgb, (0, 0), (W, bar_h), (0, 0, 0), -1)
    txt = "%s | %dx%d | %d obj | %.1f FPS | %.1f ms" % (
        MODEL_NAME, W, H, n, fps, ms)
    cv2.putText(rgb, txt, (4, bar_h - int(round(8 * UI_SCALE))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42 * UI_SCALE,
                (80, 255, 80), max(1, int(round(UI_SCALE * 0.6))),
                cv2.LINE_AA)


# ══════════════════════ 主流程 ══════════════════════
def main():
    print("=" * 66)
    print("  MaixCAM v4 六类模型 实测 + HSV 调参")
    print("=" * 66)
    print("  MODEL_PATH  = %s" % MODEL_PATH)
    print("  FRAME       = %dx%d" % (FRAME_W, FRAME_H))
    print("  CONF / IOU  = %.2f / %.2f" % (CONF_TH, IOU_TH))
    print("  WARMUP      = %.1f s（开补光灯后建议 3.0）" % WARMUP_S)
    print()

    # ── 模型存在性检查（给出可直接复制的修复命令）──
    if not os.path.exists(MODEL_PATH):
        print("❌ 模型不存在: %s" % MODEL_PATH)
        print()
        print("   把这两个文件放到 %s 里（同名配套）：" % MODEL_DIR)
        print("     %s.cvimodel" % MODEL_NAME)
        print("     %s.mud" % MODEL_NAME)
        print()
        print("   PC 上执行（MaixCAM 与 PC 同一热点时）：")
        print("     scp %s.cvimodel root@172.20.10.9:%s/" % (MODEL_NAME, MODEL_DIR))
        print("     scp %s.mud      root@172.20.10.9:%s/" % (MODEL_NAME, MODEL_DIR))
        print()
        print("   或用 MaixVision 的「文件」面板手动拖进 %s" % MODEL_DIR)
        return
    print("✅ 模型文件存在")

    # ── ① 相机（顺序不能变）──
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
        print("[1/3] camera OK %dx%d" % (FRAME_W, FRAME_H))
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   多半是 launcher_daemon 占着 —— 先执行：killall launcher_daemon")
        return

    # ── ② 显示 ──
    disp = display.Display()
    print("[2/3] display OK")

    # ── ③ 模型（最后加载）──
    try:
        detector = nn.YOLO11(model=MODEL_PATH, dual_buff=DUAL_BUFF)
    except Exception as e:
        print("❌ 模型加载失败: %s" % e)
        return
    print("[3/3] YOLO11 OK  input %dx%d  dual_buff=%s"
          % (detector.input_width(), detector.input_height(), DUAL_BUFF))

    labels = LABELS
    try:
        if getattr(detector, "labels", None):
            labels = list(detector.labels)
            print("      labels from .mud: %s" % ", ".join(labels))
            if labels != LABELS:
                print("      ⚠️ .mud labels 与预期不符，请核对顺序！")
                print("         预期: %s" % ", ".join(LABELS))
    except Exception:
        pass

    # ── 预热（等 AE/AWB 收敛，开补光灯尤其需要）──
    print("预热 %.1f s ..." % WARMUP_S)
    t0 = time.time()
    while time.time() - t0 < WARMUP_S and not app.need_exit():
        cam.read()
    print("预热完成，开始检测")
    print("-" * 66)

    fps = 0.0
    last_t = time.time()
    n = 0
    t_start = time.time()

    try:
        while not app.need_exit():
            frame = cam.read()
            if frame is None:
                continue
            # RGB 共享视图（copy=False ⇒ 绘制直接写进 frame 缓冲）
            rgb = image.image2cv(frame, ensure_bgr=False, copy=False)

            t1 = time.time()
            try:
                # ⚠️ 必须传 maix 的 image.Image（frame），不要传 numpy 视图。
                #    已验证可用的是 frame；numpy 传入在不同 MaixPy 版本上行为不一致。
                #    顺序：先 detect 再绘制，否则画上去的框会被当成图像内容。
                objs = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)
            except Exception as e:
                print("detect 异常: %s" % e)
                objs = []
            ms = (time.time() - t1) * 1000.0

            n += 1
            if n % 10 == 0:
                now = time.time()
                fps = 10.0 / max(1e-6, now - last_t)
                last_t = now

            draw_topbar(rgb, fps, ms, len(objs))
            cnt = draw_boxes(rgb, objs)

            if SHOW_MASK_STRIP:
                try:
                    draw_strip(rgb, build_masks(rgb))
                except Exception as e:
                    if n % 60 == 0:
                        print("掩膜异常: %s" % e)

            disp.show(frame)

            # ── 每 PRINT_EVERY 帧打印一次统计（含 HSV 中位数）──
            # ⚠️ 必须在 del rgb 之前，因为要用同一个 numpy 视图测 HSV
            if n % PRINT_EVERY == 0:
                el = time.time() - t_start
                print("[帧 %d  %.1fs] %.1f FPS  %.1f ms  %d 个物件"
                      % (n, el, fps, ms, len(objs)))
                if cnt:
                    parts = []
                    for cid in sorted(cnt):
                        nm = labels[cid] if cid < len(labels) else str(cid)
                        parts.append("%s×%d" % (nm, cnt[cid]))
                    print("    类别: %s" % "  ".join(parts))
                # 每个物件的 HSV 中位数（开补光灯后调阈值就看这个）
                for o in objs:
                    q = hsv_median_of_box(rgb, int(o.x), int(o.y),
                                          int(o.w), int(o.h))
                    if q is None:
                        continue
                    cls = int(o.class_id)
                    nm = labels[cls] if cls < len(labels) else str(cls)
                    print("      %-18s 框(%3d,%3d,%3d,%3d)  "
                          "H=%5.1f S=%5.1f V=%5.1f  有彩占比 %d%%"
                          % (nm, int(o.x), int(o.y), int(o.w), int(o.h),
                             q[0], q[1], q[2], q[3]))
                print("-" * 66)

            del rgb

    except KeyboardInterrupt:
        print("用户中断")
    finally:
        el = time.time() - t_start if 't_start' in locals() else 0.0
        print("=" * 66)
        print("结束：运行 %.1f s，共 %d 帧，平均 %.1f FPS"
              % (el, n, n / el if el > 0 else 0.0))
        print("=" * 66)


if __name__ == "__main__":
    main()
