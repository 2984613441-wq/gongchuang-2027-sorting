#!/usr/bin/env python3
"""副相机（DF200 / UVC）→ 电脑浏览器实时预览 + 一键存图（跑在树莓派上）。

## 为什么用它（而不是装厂商软件）

- 相机现在插在**树莓派**上；厂商工具（SEye2 / VideoCap）只能识别**插在 Windows 本机**的相机，
  想用就得拔线换机器 —— 采数据集时来回插拔很折腾。
- 本脚本在 Pi 上把画面以 **MJPEG over HTTP** 推出去，**电脑浏览器直接看**，零安装、可同时录。

## 用法

    # 树莓派上（后台跑）
    python3 -u /home/pi/pi_cam2_stream.py --port 8080 --w 1280 --h 720

    # 电脑浏览器打开
    http://172.20.10.8:8080/            # 实时画面（浏览器直接显示）
    http://172.20.10.8:8080/snap        # 拍一张（返回单张 JPEG，可直接另存）
    http://172.20.10.8:8080/save        # 让 Pi 存一张全分辨率到 /home/pi/cam2_shots/

## 注意

* DF200 **只有 MJPG**，必须显式 FOURCC=MJPG；
* 720p 实测 30.5 fps / 1080p 16.5 fps（Pi 软解上限）；
* **单进程独占相机** —— 跑本脚本时不要同时跑 `pi_cam2_grab.py`（会抢 /dev/video0）。
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

_LOCK = threading.Lock()
_CAP = None
_ARGS = None
_SHOT_DIR = "/home/pi/cam2_shots"


def _open_camera(width: int, height: int, index: int = 0):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        raise RuntimeError("打不开 /dev/video%d" % index)
    # 丢掉开头几帧（AE/AWB 未稳）
    for _ in range(6):
        cap.read()
    real = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    return cap, real


def _grab_jpeg(quality: int = 80):
    """取一帧并编码为 JPEG 字节；失败返回 None。"""
    with _LOCK:
        ok, frame = _CAP.read()
        if not ok or frame is None:
            return None
        scale = _ARGS.downscale
        if scale and scale != 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        return buf.tobytes()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):  # 静音：别刷屏
        pass

    def _index(self):
        html = """<html><head><meta charset="utf-8"><title>副相机预览</title>
<style>body{background:#111;color:#ddd;font-family:sans-serif;margin:0}
img{display:block;max-width:100%;height:auto} .bar{padding:8px 12px;font-size:14px}
a{color:#6cf}</style></head><body>
<div class="bar">副相机（DF200）实时预览 ·
<a href="/snap">拍一张(单帧)</a> ·
<a href="/save">让 Pi 存全分辨率</a> ·
<a href="/">刷新</a></div>
<img src="/stream"></body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                jpg = _grab_jpeg(quality=_ARGS.quality)
                if jpg is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: %d\r\n\r\n" % len(jpg))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return

    def _snap(self):
        jpg = _grab_jpeg(quality=_ARGS.quality)
        if jpg is None:
            self.send_error(503, "camera read failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpg)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(jpg)

    def _save(self):
        with _LOCK:
            ok, frame = _CAP.read()
        if not ok or frame is None:
            self.send_error(503, "camera read failed")
            return
        os.makedirs(_SHOT_DIR, exist_ok=True)
        path = os.path.join(_SHOT_DIR, "cam2_%s.jpg" % time.strftime("%Y%m%d_%H%M%S"))
        cv2.imwrite(path, frame)
        body = ("OK %s\n" % path).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._index()
        elif path == "/stream":
            self._stream()
        elif path == "/snap":
            self._snap()
        elif path == "/save":
            self._save()
        else:
            self.send_error(404)


def main() -> int:
    global _CAP, _ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--downscale", type=float, default=1.0,
                    help="<1.0 时缩小推流尺寸（省带宽；/save 仍是全分辨率）")
    _ARGS = ap.parse_args()

    _CAP, real = _open_camera(_ARGS.w, _ARGS.h, _ARGS.dev)
    print("[cam2-stream] /dev/video%d 实际 %dx%d  推流 quality=%d downscale=%.2f"
          % (_ARGS.dev, real[0], real[1], _ARGS.quality, _ARGS.downscale))
    print("[cam2-stream] 浏览器打开： http://<Pi-IP>:%d/" % _ARGS.port)
    print("[cam2-stream] 单帧： /snap    存全分辨率： /save")
    srv = ThreadingHTTPServer(("0.0.0.0", _ARGS.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        srv.server_close()
        _CAP.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
