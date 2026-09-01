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


def write_label(path: str, objects, img_w: int, img_h: int) -> None:
    """把 MaixPy 检测结果写成 YOLO 格式（归一化中心坐标）。"""
    lines = []
    for obj in objects:
        cx = (obj.x + obj.w / 2.0) / img_w
        cy = (obj.y + obj.h / 2.0) / img_h
        nw = obj.w / img_w
        nh = obj.h / img_h
        lines.append(f"{int(obj.class_id)} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    with open(path, "w") as f:
        if lines:
            f.write("\n".join(lines) + "\n")


def main() -> None:
    try:
        detector = nn.YOLO11(model=MODEL_PATH, dual_buff=True)
    except Exception as exc:
        print(f"model load failed, check MODEL_PATH={MODEL_PATH}: {exc}")
        return

    img_w = detector.input_width()
    img_h = detector.input_height()

    session_dir = os.path.join(CAPTURE_ROOT, f"session_{int(time.time())}")
    os.makedirs(session_dir, exist_ok=True)
    print(f"capture dir: {session_dir}")
    print(f"input {img_w}x{img_h} conf_th={CONF_TH} iou_th={IOU_TH}")

    cam = camera.Camera(img_w, img_h, detector.input_format())
    disp = display.Display()

    count = 0
    last_save = 0.0

    while not app.need_exit():
        frame = cam.read()
        now = time.time()

        if now - last_save >= INTERVAL_S:
            objects = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)

            # 先存干净原始帧 + draft 标签，再往显示帧上叠框。
            img_path = os.path.join(session_dir, f"img_{count:05d}.jpg")
            frame.save(img_path)
            write_label(
                os.path.join(session_dir, f"img_{count:05d}.txt"),
                objects,
                img_w,
                img_h,
            )
            print(f"saved {os.path.basename(img_path)}  ({len(objects)} obj)")
            count += 1
            last_save = now

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
        disp.show(frame)


if __name__ == "__main__":
    main()
