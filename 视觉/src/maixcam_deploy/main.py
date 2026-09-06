"""MaixCAM deployment entry for the converted YOLOv8 detector.

This script is intended to run on the MaixCAM itself. It is derived from the
MaixHub generated ``main.py`` reference but:

- uses ``nn.YOLOv8`` (matching the model_8766 conversion package);
- keeps the reference comm payload as an opt-in debug channel, not a frozen
  STM32 wire contract;
- prints a lightweight per-frame diagnostic line for host-side inspection.

NOTE: after conversion, cross-check the exact constructor args (``dual_buff``,
input size) against the ``main.py`` that MaixHub ships inside the model zip —
that reference is authoritative for the converted artifact.
"""

from __future__ import annotations

import os
import socket
import time

from maix import app, camera, comm, display, image, nn


# Override at runtime if the on-board model directory differs.
MODEL_PATH = os.environ.get("MODEL_PATH", "/root/my_models/model_8766.mud")
# 现场实测置信度 0.4-0.7，弱类可能更低；0.3 避免漏检（漏检比误检更致命）
CONF_TH = float(os.environ.get("CONF_TH", "0.3"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
REPORT_COMM = os.environ.get("REPORT_COMM", "0") == "1"
APP_CMD_DETECT_RES = 0x02
TASK_ID = int(os.environ.get("TASK_ID", "0"))

# Network gateway configuration (树莓派网关)
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "172.20.10.8")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8765"))
ENABLE_NETWORK = True

# 冻结的 active class-id 集（interface-contract §5.2）：1=cuboid 本轮缺失。
# 发送前过滤，避免一个越界 class_id 让整批被树莓派拒收。
ACTIVE_CLASS_IDS = frozenset({0, 2, 3, 4, 5, 6})

# 无物体时的心跳间隔（ms）：周期性发 count=0 空帧，让桥接端区分"无货"与"断连"。
HEARTBEAT_INTERVAL_MS = 500


def encode_batch_targets(objs, task_id: int = TASK_ID) -> bytes:
    """Encode MaixPy detections into the frozen BATCH_TARGETS data region.

    Layout (interface-contract §5.1, big-endian 7 bytes/target)::

        target_count(1) + task_id(2, BE) + target[N]

    Each target::

        class_id(1) + confidence(1, 0-100) + X(2, BE) + Y(2, BE) + angle(1, 0xFF)

    X/Y are the bbox center pixel coordinates (rounded) — not calibrated,
    used only for dedup/sort/reacquire localization, never for motion. The
    angle byte is always 0xFF (claw does not rotate).
    """

    body = bytearray([len(objs)])
    body += int(task_id).to_bytes(2, "big")
    for obj in objs:
        center_x = int(obj.x + obj.w / 2)
        center_y = int(obj.y + obj.h / 2)
        confidence = max(0, min(100, int(round(obj.score * 100))))
        body += bytes((obj.class_id, confidence))
        body += center_x.to_bytes(2, "big")
        body += center_y.to_bytes(2, "big")
        body += bytes((0xFF,))
    return bytes(body)


def diagnostic_line(obj) -> str:
    return (
        f"{detector.labels[obj.class_id]}:{obj.score:.2f}:"
        f"{(obj.x + obj.w / 2):.1f},{(obj.y + obj.h / 2):.1f}"
    )


detector = nn.YOLOv8(model=MODEL_PATH, dual_buff=True)
cam = camera.Camera(
    detector.input_width(), detector.input_height(), detector.input_format()
)
display_obj = display.Display()

if REPORT_COMM:
    protocol = comm.CommProtocol(buff_size=1024)
else:
    protocol = None

# 长连接 socket（循环外，断线重连）。每帧新建连接会累积 TIME_WAIT 且失败尾延迟
# 可达 1s；长连接把握手降为一次性成本，稳态每帧只付一次 sendall。
_sock = None
_last_heartbeat_ms = 0


def _ensure_sock():
    global _sock
    if _sock is not None:
        return _sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)  # 短超时：connect 失败不阻塞检测循环
    try:
        s.connect((GATEWAY_HOST, GATEWAY_PORT))
        _sock = s
    except Exception:
        s.close()
        _sock = None
    return _sock


def _send(payload: bytes) -> bool:
    global _sock
    s = _ensure_sock()
    if s is None:
        return False
    try:
        s.sendall(payload)
        return True
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        _sock = None
        return False


while not app.need_exit():
    frame = cam.read()
    objects = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)

    # fail-closed: 丢弃越界/非法检测框（防御性；detector 正常不应产生越界框）
    frame_w, frame_h = detector.input_width(), detector.input_height()
    objects = [
        obj for obj in objects
        if obj.x >= 0 and obj.y >= 0 and obj.w > 0 and obj.h > 0
        and obj.x + obj.w <= frame_w and obj.y + obj.h <= frame_h
    ]
    # 过滤非 active class-id（cuboid=1 本轮缺失），避免整批被树莓派拒收
    objects = [obj for obj in objects if obj.class_id in ACTIVE_CLASS_IDS]

    if objects:
        # 串口通信（调试用）
        if protocol is not None:
            protocol.report(APP_CMD_DETECT_RES, encode_batch_targets(objects))

        # 网络通信（长连接发送到树莓派网关）
        if ENABLE_NETWORK:
            payload = encode_batch_targets(objects)
            ok = _send(payload)
            if ok:
                print(f"[NET] sent {len(payload)}B to {GATEWAY_HOST}:{GATEWAY_PORT}")
            else:
                print("[NET] send failed (reconnect next frame)")

        # 控制台输出
        print(" ".join(diagnostic_line(obj) for obj in objects))
    else:
        # 心跳：无物体时周期性发 count=0 空帧（冻结向量 B，task_id 与真实 batch 一致）
        now = time.ticks_ms()
        if ENABLE_NETWORK and (now - _last_heartbeat_ms) >= HEARTBEAT_INTERVAL_MS:
            if _send(encode_batch_targets([], task_id=TASK_ID)):
                _last_heartbeat_ms = now
        print("none")

    for obj in objects:
        frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_RED)
        label = f"{detector.labels[obj.class_id]}: {obj.score:.2f}"
        frame.draw_string(obj.x, obj.y, label, color=image.COLOR_RED)

    display_obj.show(frame)
