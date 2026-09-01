"""MaixCAM deployment entry for the converted YOLO11 detector.

This script is intended to run on the MaixCAM itself. It is derived from the
MaixHub generated ``main.py`` reference but:

- uses ``nn.YOLO11`` (matching task 8629);
- keeps the reference comm payload as an opt-in debug channel, not a frozen
  STM32 wire contract;
- prints a lightweight per-frame diagnostic line for host-side inspection.
"""

from __future__ import annotations

import os
import struct

from maix import app, camera, comm, display, image, nn


MODEL_PATH = os.environ.get("MODEL_PATH", "/root/my_models/model_8629.mud")
CONF_TH = float(os.environ.get("CONF_TH", "0.5"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
REPORT_COMM = os.environ.get("REPORT_COMM", "0") == "1"
APP_CMD_DETECT_RES = 0x02


def encode_objs(objs) -> bytes:
    """Encode MaixPy detections into the reference MaixHub comm body.

    Layout per object: 2B x, 2B y, 2B w, 2B h, 2B class_id, 4B score.
    This is the vendor demo payload and must be re-validated against the
    real STM32 command contract before motion is enabled.
    """

    body = b""
    for obj in objs:
        body += struct.pack(
            "<hhHHHf", obj.x, obj.y, obj.w, obj.h, obj.class_id, obj.score
        )
    return body


def diagnostic_line(obj) -> str:
    return (
        f"{detector.labels[obj.class_id]}:{obj.score:.2f}:"
        f"{(obj.x + obj.w / 2):.1f},{(obj.y + obj.h / 2):.1f}"
    )


detector = nn.YOLO11(model=MODEL_PATH, dual_buff=True)
cam = camera.Camera(
    detector.input_width(), detector.input_height(), detector.input_format()
)
display_obj = display.Display()

if REPORT_COMM:
    protocol = comm.CommProtocol(buff_size=1024)
else:
    protocol = None

while not app.need_exit():
    frame = cam.read()
    objects = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)

    if objects:
        if protocol is not None:
            protocol.report(APP_CMD_DETECT_RES, encode_objs(objects))
        print(" ".join(diagnostic_line(obj) for obj in objects))
    else:
        print("none")

    for obj in objects:
        frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_RED)
        label = f"{detector.labels[obj.class_id]}: {obj.score:.2f}"
        frame.draw_string(obj.x, obj.y, label, color=image.COLOR_RED)

    display_obj.show(frame)
