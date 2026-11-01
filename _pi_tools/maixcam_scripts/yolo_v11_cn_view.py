"""MaixCAM v11 六类模型 · 中文标签观测版  2026-10-28 深夜

## v11 是什么

    v11 = v9 数据（昨晚 + 今早复核） + 20261028b 批次（用户复核后）
    训练指标: mAP50 0.980 / mAP50-95 0.593（历史最高）/ P 0.958（历史最高）/ R 0.943
    逐类 mAP50: cube 0.991 · cuboid 0.965 · cylinder 0.925
                penta 0.970 · cone 0.986 · tetra 0.995
    独立帧 A/B（139 帧未训练）: conf 0.68/0.74，高置信框 273（v9 是 213）

## 与 v7 版的区别

    只改了两处：MODEL_NAME 默认值、本段说明。
    其余逻辑（中文绘制、颜色兜底、加载顺序）原样保留，因为 v7 版已验证可用。

## v7 版原始说明

## 功能

在 MaixCAM 上跑 **v7 模型**（30° 斜视新视角，mAP50 0.976），
框上显示**中文形状名**（正方体/长方体/圆柱/五棱柱/圆锥/正四面体）+ 置信度。

## 中文显示怎么做的（连踩两坑，记下来）

MaixPy 有两套绘制 API，本脚本混用：

    cv2.rectangle / putText   -> 画框和数字（在 image2cv 的 numpy 视图上）
    frame.draw_string(...)    -> 画中文（必须走这个，cv2 不支持中文）

`draw_string` 的正确用法：

    image.load_font(name: str, path: str, size: int = 16) -> Err
        · 第 1 参是**自己起的名字**，第 2 参才是路径
        · 返回状态码，不是字体对象；作用是把字体注册到 name 下

    frame.draw_string(x, y, text, font=NAME, color=..., scale=1.0)
        · **font 传字符串名字**，不是对象！传对象会报
          "incompatible function arguments"

字体：`/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc`（文泉驿正黑，设备自带）

## 屏幕适配

设备屏 552×368，画布 1280×720 ⇒ 缩小 0.43 倍。
⇒ 中文字号取 34（屏幕上约 15px），框线宽 3，可读。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODEL_NAME` | yolo11n_6c_v7_448_cv181x | 模型名（不带扩展名）|
| `CONF_TH` | 0.40 | 置信度阈值（0.4 能滤掉手握物件的干扰）|
| `SHOW_FPS` | 1 | 顶部状态条 |
| `WARMUP_S` | 2.0 | 预热（等 AE/AWB）|

## 已知坑（别改）

1. `dual_buff=True` 会 SIGSEGV ⇒ 必须 False
2. 加载顺序 相机 → 显示 → 模型
3. `detect()` 传 maix 的 image.Image（frame），不是 numpy
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
MODEL_NAME = os.environ.get("MODEL_NAME", "yolo11n_6c_v11_448_cv181x")
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME + ".mud")

FRAME_W = int(os.environ.get("FRAME_W", "1280"))
FRAME_H = int(os.environ.get("FRAME_H", "720"))
CONF_TH = float(os.environ.get("CONF_TH", "0.40"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
DUAL_BUFF = False                       # 坑 #1
SHOW_FPS = os.environ.get("SHOW_FPS", "1") == "1"
WARMUP_S = float(os.environ.get("WARMUP_S", "2.0"))
PRINT_EVERY = int(os.environ.get("PRINT_EVERY", "30"))

CN_FONT_PATH = os.environ.get(
    "CN_FONT_PATH", "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc")
CN_FONT_NAME = "cn34"
CN_FONT_SIZE = int(os.environ.get("CN_FONT_SIZE", "34"))

# 六类中文名（顺序与 v7 的 data.yaml 一致，不能改）
LABELS = ["cube", "cuboid", "cylinder",
          "pentagonal_prism", "cone", "tetrahedron"]
ZH = {
    "cube": "正方体",
    "cuboid": "长方体",
    "cylinder": "圆柱",
    "pentagonal_prism": "五棱柱",
    "cone": "圆锥",
    "tetrahedron": "正四面体",
}
# 每类画框颜色（RGB，因为 image2cv 用 ensure_bgr=False）
CLS_RGB = {
    0: (60, 235, 60),     # 正方体 绿
    1: (60, 200, 255),    # 长方体 橙
    2: (80, 80, 255),     # 圆柱   红
    3: (235, 80, 235),    # 五棱柱 紫
    4: (255, 210, 40),    # 圆锥   青
    5: (40, 255, 255),    # 正四面体 黄
}
# 对应的 maix Color（给 draw_string 用）
#
# ⚠️ 2026-10-28 实测：这台设备的 MaixPy 只有 10 个颜色常量
#    BLACK BLUE GRAY GREEN INVALID ORANGE PURPLE RED WHITE YELLOW
#    **没有 COLOR_CYAN** —— 直接写 image.COLOR_CYAN 会
#    AttributeError: module 'maix._maix.image' has no attribute 'COLOR_CYAN'
#    ⇒ 全部改用 getattr 兜底，缺了就退回白色，脚本永不因颜色崩。
def _mc(name: str):
    """安全取 maix 颜色常量，缺了退回 COLOR_WHITE。"""
    return getattr(image, name, getattr(image, "COLOR_WHITE"))


CLS_MAIX = {
    0: _mc("COLOR_GREEN"),     # 正方体 绿
    1: _mc("COLOR_ORANGE"),    # 长方体 橙
    2: _mc("COLOR_RED"),       # 圆柱   红
    3: _mc("COLOR_PURPLE"),    # 五棱柱 紫
    4: _mc("COLOR_BLUE"),      # 圆锥   蓝（设备无 CYAN）
    5: _mc("COLOR_YELLOW"),    # 正四面体 黄
}

UI_SCALE = float(os.environ.get("UI_SCALE", "2.3"))   # 画布/屏幕比


def draw_boxes_cv2(rgb: np.ndarray, objs) -> Counter:
    """用 cv2 画框（不用 cv2 画中文，中文交给 draw_string）。"""
    cnt = Counter()
    th = max(2, int(round(2 * UI_SCALE)))
    for o in objs:
        cls = int(o.class_id)
        x, y, w, h = int(o.x), int(o.y), int(o.w), int(o.h)
        col = CLS_RGB.get(cls, (255, 255, 255))
        cv2.rectangle(rgb, (x, y), (x + w, y + h), col, th)
        cnt[cls] += 1
    return cnt


def draw_chinese(frame, objs) -> None:
    """用 maix draw_string 在框上方画中文名 + 置信度。

    ⚠️ 2026-10-28 实测的两个坑：
      ① draw_rect **没有 fill 参数**，真实签名是
         draw_rect(x, y, w, h, color, thickness=1)
         填充要用 thickness=-1
      ② draw_rect 的第 3、4 参是 **宽和高**，不是 x2/y2
         我一开始传了 (x, ty, x2, y2) ⇒ 会画出巨大黑块
    """
    for o in objs:
        cls = int(o.class_id)
        x, y = int(o.x), int(o.y)
        name = LABELS[cls] if 0 <= cls < len(LABELS) else str(cls)
        zh = ZH.get(name, name)
        text = "%s %.2f" % (zh, float(o.score))

        # 文字底衬：中文按 1 字宽、ASCII 按半字宽估
        tw = sum(CN_FONT_SIZE if ord(c) > 127 else CN_FONT_SIZE // 2
                 for c in text)
        th = CN_FONT_SIZE + 6
        ty = max(0, y - th - 4)
        try:
            frame.draw_rect(x, ty, tw + 6, th,
                            color=_mc("COLOR_BLACK"), thickness=-1)
        except Exception as e:
            print("底衬绘制失败: %s" % e)

        try:
            frame.draw_string(x + 3, ty + 2, text,
                              font=CN_FONT_NAME,
                              color=CLS_MAIX.get(cls, _mc("COLOR_WHITE")),
                              scale=1.0)
        except Exception as e:
            print("中文绘制失败: %s" % e)


def draw_topbar_cv2(rgb: np.ndarray, fps: float, ms: float, n: int) -> None:
    W = rgb.shape[1]
    bar_h = int(round(30 * UI_SCALE))
    cv2.rectangle(rgb, (0, 0), (W, bar_h), (0, 0, 0), -1)
    txt = "%d obj | %.1f FPS | %.1f ms" % (n, fps, ms)
    cv2.putText(rgb, txt, (4, bar_h - int(round(8 * UI_SCALE))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45 * UI_SCALE, (80, 255, 80),
                max(1, int(round(UI_SCALE * 0.6))), cv2.LINE_AA)


def main():
    print("=" * 66)
    print("  MaixCAM v11 六类 · 中文标签观测版")
    print("=" * 66)
    print("  MODEL = %s" % MODEL_NAME)
    print("  FRAME = %dx%d   CONF=%.2f" % (FRAME_W, FRAME_H, CONF_TH))
    print("  字体  = %s (%d)" % (CN_FONT_NAME, CN_FONT_SIZE))
    print()

    # ① 注册中文字体
    ok_font = False
    if os.path.exists(CN_FONT_PATH):
        try:
            image.load_font(CN_FONT_NAME, CN_FONT_PATH, CN_FONT_SIZE)
            ok_font = True
            print("[0/3] 中文字体注册 OK: %s" % CN_FONT_PATH)
        except Exception as e:
            print("[0/3] ⚠️ 中文字体注册失败: %s" % e)
    else:
        print("[0/3] ⚠️ 字体不存在: %s（将退回英文）" % CN_FONT_PATH)

    if not os.path.exists(MODEL_PATH):
        print("❌ 模型不存在: %s" % MODEL_PATH)
        print("   把 yolo11n_6c_v11_448_cv181x.cvimodel / .mud 放到 %s" % MODEL_DIR)
        return

    # ② 相机（顺序：相机 → 显示 → 模型，坑 #2）
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
        print("[1/3] camera OK")
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   先执行: killall launcher_daemon")
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
        f = cam.read()
        if f is not None:
            disp.show(f)
    print("开始（Ctrl-C 停止）")
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
            rgb = image.image2cv(frame, ensure_bgr=False, copy=False)

            t1 = time.time()
            try:
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

            if SHOW_FPS:
                draw_topbar_cv2(rgb, fps, ms, len(objs))
            cnt = draw_boxes_cv2(rgb, objs)
            del rgb

            # 中文必须画在 maix frame 上（cv2 不支持中文）
            if ok_font and objs:
                draw_chinese(frame, objs)

            disp.show(frame)

            if n % PRINT_EVERY == 0:
                el = time.time() - t_start
                print("[帧 %d  %.1fs] %.1f FPS  %.1f ms  %d 个"
                      % (n, el, fps, ms, len(objs)))
                if cnt:
                    print("    " + "  ".join(
                        "%s×%d" % (ZH.get(LABELS[c], str(c)),
                                   cnt[c]) for c in sorted(cnt)))
                print("-" * 66)

    except KeyboardInterrupt:
        print("用户中断")
    finally:
        el = time.time() - t_start if 't_start' in locals() else 0.0
        print("=" * 66)
        print("结束: %.1f s, %d 帧, 平均 %.1f FPS"
              % (el, n, n / el if el > 0 else 0.0))
        print("=" * 66)


if __name__ == "__main__":
    main()
