"""MaixCAM 工作区采集 + 自动预标注工具。

在 MaixCAM 上运行：每 INTERVAL_S 秒把当前原始帧存成 JPEG，同时用当前
YOLO11 模型跑一遍，把检测结果存成 YOLO 格式的 draft 标签（同名 .txt）。
标注时只需改错框/改错类，不用从零画框。

输出（在 session 目录内，同名一一对应）：
  img_00001.jpg   原始帧（干净，不叠任何文字/框）
  img_00001.txt   YOLO 标签：每行 "class_id cx cy w h"（归一化 0~1）

环境变量（可选）：
  CAPTURE_DIR   输出根目录，默认 /root/capture
  INTERVAL_S    采集间隔秒数，默认 1.0
  CONF_TH       预标注置信度阈值，默认 0.30（偏宽松，宁可多框、人工删）
  IOU_TH        NMS 阈值，默认 0.45
  MODEL_PATH    模型 mud 路径，默认 /root/my_models/model_8629.mud
"""

from __future__ import annotations

import os
import time

from maix import app, camera, display, image, nn


CAPTURE_ROOT = os.environ.get("CAPTURE_DIR", "/root/capture")
INTERVAL_S = float(os.environ.get("INTERVAL_S", "1.0"))
CONF_TH = float(os.environ.get("CONF_TH", "0.30"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
MODEL_PATH = os.environ.get("MODEL_PATH", "/root/my_models/model_8629.mud")

# ⚠️ 2026-10-18 改动（第二次）：相机默认改为 **1280×720（16:9）**。
#   · 原因：MaixPy 请求正方形时会从传感器 2560×1440 里**裁剪**中间 1440×1440，
#     横向只用了 56%，托盘外的物料完全看不到（识别区 184.5mm < 抓取区 190×195mm）。
#   · 16:9 用满整个传感器横向视野（184.5 → 328mm），面积 +78%。
#   · 生产链同步改好（stage1_color_v6_send.py 的 FRAME_W/FRAME_H）。
#   · 若需要旧的 320×320 正方形（会裁掉左右 44%），设 CAPTURE_W=320 CAPTURE_H=320。
CAPTURE_W = int(os.environ.get("CAPTURE_W", "1280"))
CAPTURE_H = int(os.environ.get("CAPTURE_H", "720"))

# ⚠️ 2026-10-18 崩溃排查（第二次）：`nn.YOLO11(dual_buff=True)` 会多占**一份输出缓冲**。
#   MaixCAM 每次崩溃后媒体缓冲池会泄漏（日志里 Pool 的 Free < BlkCnt），
#   再叠加 dual_buff 就会 `No buffer space available` → SIGSEGV。
#   默认关掉；确需开启时用环境变量 NO_DUAL_BUFF=0。
DUAL_BUFF = os.environ.get("NO_DUAL_BUFF", "1") != "1"
# 纯采集（无头）时可关显示再省一点内存/CPU：NO_DISPLAY=1
NO_DISPLAY = os.environ.get("NO_DISPLAY", "0") == "1"

# 🔴 2026-10-18 新增：NO_PRELABEL=1 时**完全不做预标注**，只存干净图片 + 空 .txt。
#   为什么需要：旧模型（model_8629）是在**旧的 320×320 正方形 + 旧照明**下训练的，
#   换成 1280×720 全视野 + 补光灯后，实测空托盘每帧都会误检 3~4 个物体。
#   这种情况下 draft 框不但没帮助，反而要人工逐个删。
#   重采数据集建议：先 `NO_PRELABEL=1` 采一批干净图，
#   等新模型训出来之后再开预标注来加速后续标注。
NO_PRELABEL = os.environ.get("NO_PRELABEL", "0") == "1"


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def write_label(path: str, objects, img_w: int, img_h: int) -> None:
    """把 MaixPy 检测结果写成 YOLO 格式（归一化中心坐标）。

    ⚠️ img_w / img_h 必须是**保存下来的图片尺寸**（即相机采集分辨率），
    不能传模型输入尺寸 —— detect() 返回的是原图坐标。
    这里额外做 [0,1] 钳位与合法性丢弃，防止越界框污染训练集。
    """
    lines = []
    for obj in objects:
        cx = (obj.x + obj.w / 2.0) / img_w
        cy = (obj.y + obj.h / 2.0) / img_h
        nw = obj.w / img_w
        nh = obj.h / img_h
        cx, cy, nw, nh = _clamp01(cx), _clamp01(cy), _clamp01(nw), _clamp01(nh)
        if nw <= 0.0 or nh <= 0.0:
            continue
        lines.append(f"{int(obj.class_id)} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    with open(path, "w") as f:
        if lines:
            f.write("\n".join(lines) + "\n")


def main() -> None:
    # ⚠️ 2026-10-18 崩溃排查（第三次）：**先开相机，再加载模型**。
    #   原顺序是「先 nn.YOLO11 吃内存 → 再开相机」，结果 camera.Camera() 在
    #   vi_sdk_enable_chn 时拿不到缓冲 → "No buffer space available" → SIGSEGV。
    #   相机先拿到 VI/VPSS 缓冲，模型后加载，可显著降低失败概率。
    session_dir = os.path.join(CAPTURE_ROOT, f"session_{int(time.time())}")
    os.makedirs(session_dir, exist_ok=True)
    print(f"capture dir: {session_dir}")

    # ① 先开相机（模型输入是 rgb，等价于 FMT_RGB888）
    cam = camera.Camera(CAPTURE_W, CAPTURE_H, image.Format.FMT_RGB888)
    print(f"[1/3] camera OK  {CAPTURE_W}x{CAPTURE_H}")

    # ② 再开显示（可关）
    disp = None if NO_DISPLAY else display.Display()
    print(f"[2/3] display {'off' if NO_DISPLAY else 'on'}")

    # ③ 最后加载模型
    if NO_PRELABEL:
        detector = None
        model_w = model_h = 0
        print("[3/3] 预标注已关闭（NO_PRELABEL=1）—— 只存图片，.txt 留空")
        label_w, label_h = CAPTURE_W, CAPTURE_H
    else:
        try:
            detector = nn.YOLO11(model=MODEL_PATH, dual_buff=DUAL_BUFF)
        except Exception as exc:
            print(f"model load failed, check MODEL_PATH={MODEL_PATH}: {exc}")
            return
        model_w = detector.input_width()
        model_h = detector.input_height()
        print(f"[3/3] model OK  input {model_w}x{model_h}  dual_buff={DUAL_BUFF} "
              f"conf_th={CONF_TH} iou_th={IOU_TH}")

        # 🔴 2026-10-18 修复：YOLO 标签的归一化分母必须是**保存下来的图片尺寸**，
        #   不是模型输入尺寸。detect() 返回的 x/y/w/h 是原图坐标（0..CAPTURE_W / 0..CAPTURE_H），
        #   之前误用 detector.input_width()（=448）作分母 ⇒ 1280 宽的画面算出的归一化值
        #   最大到 1280/448=2.86，远超 [0,1]，draft 标签完全不可用。
        label_w = CAPTURE_W
        label_h = CAPTURE_H
        print(f"[label] 归一化分母 = 采集图 {label_w}x{label_h}（不是模型输入 {model_w}x{model_h}）")

    # 2026-10-18：预热 —— 相机刚启动时 AE/AWB 还在收敛，前几帧颜色会和稳定后不同。
    #   采数据集时必须跳过，否则第一批图白平衡不一致会污染训练集。
    warmup_s = float(os.environ.get("WARMUP_S", "2.0"))
    if warmup_s > 0:
        print(f"[warmup] 跳过前 {warmup_s}s（等 AE/AWB 收敛）")
        t0 = time.time()
        while (time.time() - t0) < warmup_s:
            cam.read()
        print("[warmup] done")

    count = 0
    last_save = 0.0

    while not app.need_exit():
        frame = cam.read()
        now = time.time()

        if now - last_save >= INTERVAL_S:
            if detector is not None:
                objects = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)
            else:
                objects = []

            # 先存干净原始帧 + draft 标签，再往显示帧上叠框。
            img_path = os.path.join(session_dir, f"img_{count:05d}.jpg")
            frame.save(img_path)
            write_label(
                os.path.join(session_dir, f"img_{count:05d}.txt"),
                objects,
                label_w,
                label_h,
            )
            print(f"saved {os.path.basename(img_path)}  ({len(objects)} obj)")
            count += 1
            last_save = now

            if detector is not None:
                for obj in objects:
                    frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_YELLOW)
                    label = f"{detector.labels[obj.class_id]}: {obj.score:.2f}"
                    frame.draw_string(obj.x, obj.y - 16, label, color=image.COLOR_YELLOW)

        frame.draw_string(
            4,
            4,
            f"cap {count}  conf={CONF_TH}",
            color=image.COLOR_GREEN,
            scale=1.5,
        )
        if disp is not None:
            disp.show(frame)


if __name__ == "__main__":
    main()
