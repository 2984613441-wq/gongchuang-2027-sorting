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

import json
import os
import socket
import threading
import time

from maix import app, camera, comm, display, image, nn
from maix import time as mtime   # MaixPy 的 ticks_ms()，标准库 time 里没有


# Override at runtime if the on-board model directory differs.
MODEL_PATH = os.environ.get("MODEL_PATH", "/root/my_models/model_8766.mud")
# 2026-09-15 用户裁决：置信度统一为 0.5（与 MaixHub 导出包 conf_th=0.5 及
# commit ade707b4「视觉：对齐置信度阈值0.50」一致）。此前代码默认 0.3 与之冲突。
CONF_TH = float(os.environ.get("CONF_TH", "0.5"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
REPORT_COMM = os.environ.get("REPORT_COMM", "0") == "1"
APP_CMD_DETECT_RES = 0x02
TASK_ID = int(os.environ.get("TASK_ID", "0"))

# Network gateway configuration (树莓派网关)
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "172.20.10.8")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8765"))
# 2026-09-15：改为可关。单独测视觉（树莓派不在线）时设 ENABLE_NETWORK=0，
# 否则每帧都要尝试 connect，会拖慢检测循环。
ENABLE_NETWORK = os.environ.get("ENABLE_NETWORK", "1") == "1"

# 冻结的 active class-id 集（interface-contract §5.2）：1=cuboid 本轮缺失。
# 发送前过滤，避免一个越界 class_id 让整批被树莓派拒收。
ACTIVE_CLASS_IDS = frozenset({0, 2, 3, 4, 5, 6})

# 无物体时的心跳间隔（ms）：周期性发 count=0 空帧，让桥接端区分"无货"与"断连"。
HEARTBEAT_INTERVAL_MS = 500

# ============ 监控服务（独立旁路，默认 9001）============
# 2026-09-15 新增：供电脑端 GUI（工具/monitor_gui.py）实时查看原始检测结果，
# 并支持参数热更新与按需截图。
#
# 设计约束（务必保持）：
#   - 完全独立于生产通道（8765）。监控出任何问题都不影响检测与上报：
#     主循环只调用 monitor.update()，其内部全部 try/except 吞掉；
#     网络收发全在守护线程里，主循环不做任何阻塞 I/O。
#   - 参数更新与主通道共用同一个 `params` 对象，两条路径同源，不会互相覆盖。
#   - 可用 MONITOR_PORT=0 或 ENABLE_MONITOR=0 关掉（比赛时建议关）。
MONITOR_PORT = int(os.environ.get("MONITOR_PORT", "9001"))
ENABLE_MONITOR = os.environ.get("ENABLE_MONITOR", "1") == "1"
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "/root/screenshots")


# 参数热更新管理器
class ParamManager:
    """非阻塞参数热更新管理器

    接收来自树莓派的参数更新命令（JSON格式），动态调整检测阈值。
    不阻塞主循环，使用短超时socket接收。

    协议格式：
        {"type": "UPDATE_PARAMS", "conf_th": 0.5, "iou_th": 0.45}

    响应：
        b'OK' - 参数更新成功
        b'ERROR' - 参数格式错误
    """

    def __init__(self, initial_conf_th: float, initial_iou_th: float):
        self.conf_th = initial_conf_th
        self.iou_th = initial_iou_th
        self.update_count = 0

    def try_update(self, sock) -> None:
        """非阻塞尝试接收参数更新

        Args:
            sock: 已连接的socket对象（长连接）
        """
        if sock is None:
            return

        try:
            # 短超时，避免阻塞检测循环
            sock.settimeout(0.001)
            data = sock.recv(256)

            if not data:
                return

            # 解析JSON命令
            cmd = None
            try:
                import json as _json
                cmd = _json.loads(data.decode('utf-8'))
            except Exception:
                sock.sendall(b'ERROR: invalid JSON')
                return

            # 处理UPDATE_PARAMS命令
            if cmd.get('type') == 'UPDATE_PARAMS':
                new_conf = cmd.get('conf_th')
                new_iou = cmd.get('iou_th')

                # 参数校验
                if new_conf is not None and 0.0 <= new_conf <= 1.0:
                    self.conf_th = float(new_conf)
                if new_iou is not None and 0.0 <= new_iou <= 1.0:
                    self.iou_th = float(new_iou)

                self.update_count += 1
                sock.sendall(b'OK')

                print(f"[PARAM] #{self.update_count}: conf_th={self.conf_th:.2f}, "
                      f"iou_th={self.iou_th:.2f}")
            else:
                sock.sendall(b'ERROR: unknown command')

        except socket.timeout:
            # 正常超时，无数据
            pass
        except Exception as e:
            # 其他错误（连接断开等），静默处理
            pass


params = ParamManager(CONF_TH, IOU_TH)


class MonitorServer:
    """只读旁路监控服务（默认 9001），供电脑端 GUI 查看原始检测结果。

    与生产通道（8765）完全独立：
      - 检测主循环只调用 update()，内部全 try/except，绝不向上抛；
      - accept / recv / sendall 全在守护线程，主循环不做阻塞 I/O；
      - update() 里只做"算 FPS + 组 JSON + 赋值"，发送由 _send_loop 承担；
        因此客户端再慢也不会拖慢检测（旧帧被新帧覆盖，天然丢帧保护）。

    协议（换行分隔 JSON，与 工具/monitor_gui.py 对齐）：
      MaixCAM → GUI:
        {"fps":..., "count":..., "conf_th":..., "iou_th":...,
         "detections":[{"class_id":0,"class_name":"cube",
                        "confidence":0.87,"center":[x,y]}, ...]}\n
      GUI → MaixCAM:
        {"type":"UPDATE_PARAMS","conf_th":0.5,"iou_th":0.45}\n
        {"type":"SAVE_SCREENSHOT"}\n
    """

    def __init__(self, port: int, params_ref) -> None:
        self.port = port
        self.params = params_ref          # 与主通道共用同一对象，两条调参路径同源
        self.fps = 0.0
        self._clients = []
        self._lock = threading.Lock()
        self._payload = b""
        self._seq = 0
        self._sent_seq = 0
        self._frame = None                # 最近一帧（带框），供截图
        self._running = False
        self._listener = None
        self._fps_t0 = None
        self._fps_n = 0

    # ---------- 生命周期 ----------
    def start(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(4)
            srv.settimeout(0.5)           # accept 带超时，便于干净退出
        except Exception as e:
            print(f"[MONITOR] 启动失败（不影响检测）: {e}")
            return
        self._listener = srv
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()
        print(f"[MONITOR] 监听端口 {self.port}")

    # ---------- 后台线程 ----------
    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            conn.settimeout(0.2)
            with self._lock:
                self._clients.append(conn)
            print(f"[MONITOR] 客户端连接: {addr}")
            threading.Thread(target=self._reader_loop, args=(conn,),
                             daemon=True).start()

    def _reader_loop(self, conn) -> None:
        buf = b""
        while self._running:
            try:
                chunk = conn.recv(512)
            except socket.timeout:
                continue
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._handle_command(line)
        self._drop(conn)

    def _send_loop(self) -> None:
        while self._running:
            time.sleep(0.02)
            with self._lock:
                if self._seq == self._sent_seq:
                    continue
                payload = self._payload
                self._sent_seq = self._seq
                clients = list(self._clients)
            for c in clients:
                try:
                    c.sendall(payload)
                except Exception:
                    self._drop(c)

    def _drop(self, conn) -> None:
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
        try:
            conn.close()
        except Exception:
            pass

    # ---------- 主循环接口 ----------
    def update(self, frame, objects) -> None:
        """每帧调用一次。绝不抛异常、绝不阻塞。"""
        try:
            self._frame = frame

            now = mtime.ticks_ms()
            if self._fps_t0 is None:
                self._fps_t0 = now
            self._fps_n += 1
            span = now - self._fps_t0
            if span >= 1000:
                self.fps = self._fps_n * 1000.0 / span
                self._fps_n = 0
                self._fps_t0 = now

            dets = []
            for obj in objects:
                try:
                    name = detector.labels[obj.class_id]
                except Exception:
                    name = str(obj.class_id)
                dets.append({
                    "class_id": int(obj.class_id),
                    "class_name": name,
                    "confidence": round(float(obj.score), 3),
                    "center": [int(obj.x + obj.w / 2), int(obj.y + obj.h / 2)],
                })

            payload = json.dumps({
                "fps": round(self.fps, 1),
                "count": len(dets),
                "conf_th": self.params.conf_th,
                "iou_th": self.params.iou_th,
                "task_id": TASK_ID,
                "detections": dets,
            }, ensure_ascii=False).encode("utf-8") + b"\n"

            with self._lock:
                self._payload = payload
                self._seq += 1
        except Exception:
            pass

    # ---------- 命令处理 ----------
    def _handle_command(self, line: bytes) -> None:
        try:
            cmd = json.loads(line.decode("utf-8"))
        except Exception:
            return
        kind = cmd.get("type")

        if kind == "UPDATE_PARAMS":
            try:
                new_conf = cmd.get("conf_th")
                new_iou = cmd.get("iou_th")
                if new_conf is not None and 0.0 <= float(new_conf) <= 1.0:
                    self.params.conf_th = float(new_conf)
                if new_iou is not None and 0.0 <= float(new_iou) <= 1.0:
                    self.params.iou_th = float(new_iou)
                self.params.update_count += 1
                print(f"[MONITOR] 参数已更新: conf={self.params.conf_th:.2f}, "
                      f"iou={self.params.iou_th:.2f}")
            except Exception:
                pass
        elif kind == "SAVE_SCREENSHOT":
            self._save_screenshot()
        else:
            print(f"[MONITOR] 未知命令: {kind}")

    def _save_screenshot(self) -> None:
        try:
            frame = self._frame
            if frame is None:
                print("[MONITOR] 截图失败：尚无帧")
                return
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            path = os.path.join(SCREENSHOT_DIR,
                                f"screenshot_{int(mtime.ticks_ms())}.jpg")
            frame.save(path)
            print(f"[MONITOR] 截图已保存: {path}")
        except Exception as e:
            print(f"[MONITOR] 截图失败: {e}")


monitor = MonitorServer(MONITOR_PORT, params)
if ENABLE_MONITOR:
    monitor.start()


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

    # 尝试接收参数更新（非阻塞）
    params.try_update(_sock)

    # 使用动态参数进行检测
    objects = detector.detect(frame, conf_th=params.conf_th, iou_th=params.iou_th)

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
        now = mtime.ticks_ms()
        if ENABLE_NETWORK and (now - _last_heartbeat_ms) >= HEARTBEAT_INTERVAL_MS:
            if _send(encode_batch_targets([], task_id=TASK_ID)):
                _last_heartbeat_ms = now
        print("none")

    for obj in objects:
        frame.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_RED)
        label = f"{detector.labels[obj.class_id]}: {obj.score:.2f}"
        frame.draw_string(obj.x, obj.y, label, color=image.COLOR_RED)

    # 旁路监控广播（画框之后，截图才带框）。内部全 try/except，绝不影响检测。
    if ENABLE_MONITOR:
        monitor.update(frame, objects)

    display_obj.show(frame)
