#!/usr/bin/env python3
"""副相机（DF200 / UVC）数据集采集 + 电脑浏览器实时预览（单进程，带网页按钮）。

## 为什么单进程

`/dev/video0` 只能被一个进程独占。所以"边采边在电脑上看"必须由同一个进程完成：
一个线程持续读帧（最新帧放内存），HTTP 线程把最新帧以 MJPEG 推给浏览器，
采集线程按间隔把最新帧按**全分辨率**存盘。

## 网页上能做什么（不用命令行）

    http://<Pi-IP>:8080/          实时画面 + 【开始采集】【停止采集】【拍一张单帧】
    http://<Pi-IP>:8080/start     开始连续采集（可带参数：/start?interval=1.0&min=110&max=140）
    http://<Pi-IP>:8080/stop      停止采集（预览继续，进程不退出）
    http://<Pi-IP>:8080/snap      拍一张单帧（另存用）
    http://<Pi-IP>:8080/status    进度 JSON（张数/目标/耗时/帧率/是否在采）

## 命令行用法（在 Pi 上）

    # 只预览，不自动采（推荐：先摆位/对焦，再从网页点【开始采集】）
    python3 -u /home/pi/pi_cam2_capture.py --preview-only --port 8080

    # 启动就自动开采
    python3 -u /home/pi/pi_cam2_capture.py --interval 1.0 --target-min 110 --target-max 140

## 输出

    /home/pi/dataset_cam2/cam2_<YYYYmmdd-HHMMSS>/img_00000.jpg …   （全分辨率 1280×720）

## 注意

* DF200 **只有 MJPG**，必须显式 FOURCC=MJPG；
* 预览流默认缩到 640 宽（只影响观看），**存盘始终是全分辨率**；
* 每次点【开始采集】都新建 `cam2_<时间戳>` 会话目录，可多轮采集互不覆盖。
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

STATE = {
    "session": "",
    "out_dir": "",
    "count": 0,
    "target_min": 110,
    "target_max": 140,
    "interval": 1.0,
    "started_at": 0.0,
    "fps": 0.0,
    "running": True,      # 进程存活（预览）
    "capturing": False,   # 是否正在连续采集
    "layout_every": 4,
    "layout_hint": "",
    "last_dir": "",
}
_LATEST = {"frame": None, "t": 0.0}
_FRAME_LOCK = threading.Lock()
_CAP_THREAD = None
_ARGS = None


# ────────────────────────── 读帧线程 ──────────────────────────
def reader_loop(cap):
    n = 0
    t0 = time.time()
    while STATE["running"]:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue
        with _FRAME_LOCK:
            _LATEST["frame"] = frame
            _LATEST["t"] = time.time()
        n += 1
        if n % 30 == 0:
            STATE["fps"] = n / max(1e-6, time.time() - t0)


def get_latest():
    with _FRAME_LOCK:
        f = _LATEST["frame"]
        return None if f is None else f.copy()


# ────────────────────────── 采集 ──────────────────────────
LAYOUTS = [
    "1~6   单件 · 远/中/近各放一次（每形状轮换）",
    "7~12  两件同类 · 一前一后（远端被遮）",
    "13~18 两件不同类 · 一前一后（跨类遮挡）",
    "19~24 五件混放 · 标准阵型",
    "25~27 贴边角 · 远端最远 / 左右边缘",
    "28~30 密集堆叠 3~6 件（最坏情况）",
]


def begin_session(interval=None, target_min=None, target_max=None):
    """新建会话目录并开始采集（网页 /start 也走这里）。"""
    global _CAP_THREAD
    if STATE["capturing"]:
        return False, "已经在采集了"
    if interval is not None:
        STATE["interval"] = float(interval)
    if target_min is not None:
        STATE["target_min"] = int(target_min)
    if target_max is not None:
        STATE["target_max"] = int(target_max)

    session = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(_ARGS.root, "cam2_" + session)
    os.makedirs(out_dir, exist_ok=True)
    STATE.update(session=session, out_dir=out_dir, count=0,
                 started_at=time.time(), capturing=True,
                 layout_hint=LAYOUTS[0], last_dir=out_dir)
    print("▶ 开始采集：%s（%.1f s/张，目标 %d~%d）"
          % (out_dir, STATE["interval"], STATE["target_min"], STATE["target_max"]))
    _CAP_THREAD = threading.Thread(target=capture_loop, daemon=True)
    _CAP_THREAD.start()
    return True, out_dir


def stop_capture():
    if not STATE["capturing"]:
        return False, "当前没有在采集"
    STATE["capturing"] = False
    print("■ 停止采集：本会话共 %d 张（%s）" % (STATE["count"], STATE["out_dir"]))
    return True, STATE["out_dir"]


def capture_loop():
    while get_latest() is None and STATE["running"]:
        time.sleep(0.05)
    t_last = 0.0
    while STATE["running"] and STATE["capturing"]:
        if STATE["count"] >= STATE["target_max"]:
            print("  ✅ 到目标上限 %d 张 —— 自动停止" % STATE["target_max"])
            stop_capture()
            break
        now = time.time()
        if now - t_last < STATE["interval"]:
            time.sleep(0.01)
            continue
        frame = get_latest()
        if frame is None:
            time.sleep(0.02)
            continue
        t_last = now

        idx = STATE["count"]
        path = os.path.join(STATE["out_dir"], "img_%05d.jpg" % idx)
        try:
            cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), _ARGS.quality])
        except Exception as e:
            print("  第 %d 张保存失败：%s" % (idx + 1, e))
            continue
        STATE["count"] = idx + 1
        n = STATE["count"]
        lay = (n - 1) // STATE["layout_every"]
        if lay < len(LAYOUTS):
            STATE["layout_hint"] = LAYOUTS[lay]
        if n % STATE["layout_every"] == 0:
            print("  已拍 %3d 张 ← 换布局：%s" % (n, STATE["layout_hint"]))
        elif n % 10 == 1:
            print("  已拍 %3d 张 （%s）" % (n, STATE["layout_hint"]))
        if n == STATE["target_min"]:
            print()
            print("  ✅ 到目标下限 %d 张 —— 可以停了（确认：远端 90%%、遮挡 ≥30 张）"
                  % STATE["target_min"])
            print()


# ────────────────────────── HTTP ──────────────────────────
def _jpeg_bytes(quality: int, max_w: int):
    frame = get_latest()
    if frame is None:
        return None
    if max_w and frame.shape[1] > max_w:
        scale = max_w / float(frame.shape[1])
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        if path in ("/", "/index.html"):
            self._send(self._html(), "text/html; charset=utf-8")
        elif path == "/stream":
            self._stream()
        elif path == "/snap":
            jpg = _jpeg_bytes(_ARGS.quality, 0)
            if jpg is None:
                self.send_error(503, "no frame")
            else:
                self._send(jpg, "image/jpeg")
        elif path == "/status":
            d = dict(STATE)
            d["elapsed_s"] = round(time.time() - STATE["started_at"], 1) if STATE["started_at"] else 0
            d.pop("running", None)
            self._send(json.dumps(d, ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/start":
            def _f(k, default=None):
                return float(q[k][0]) if k in q else default
            ok, msg = begin_session(interval=_f("interval"), target_min=_f("min"),
                                    target_max=_f("max"))
            self._send((("OK " if ok else "ERR ") + str(msg) + "\n").encode("utf-8"),
                       "text/plain; charset=utf-8")
        elif path == "/stop":
            ok, msg = stop_capture()
            self._send((("OK " if ok else "ERR ") + str(msg) + "\n").encode("utf-8"),
                       "text/plain; charset=utf-8")
        else:
            self.send_error(404)

    def _html(self):
        if STATE["capturing"]:
            cap = ('<span class="bad">&#9679; 采集中</span>　已 <b class="k">%d</b> 张'
                   '　目标 %d~%d　间隔 %.1fs　会话 %s'
                   % (STATE["count"], STATE["target_min"], STATE["target_max"],
                      STATE["interval"], STATE["session"]))
        else:
            cap = ('<span class="w">&#9675; 未采集（仅预览）</span>　'
                   '上限设 %d 张；点【开始采集】才开始存盘'
                   % STATE["target_max"])
        hint = STATE["layout_hint"] or ""
        last = STATE["last_dir"] or "（还没有采集过）"
        html = ("""<!doctype html><html><head><meta charset="utf-8">
<title>副相机采集 · DF200</title>
<style>
body{background:#111;color:#ddd;font-family:sans-serif;margin:0}
.bar{padding:10px 12px;font-size:15px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
form.bar input{width:64px;font-size:15px;padding:5px;background:#1b1b1b;color:#eee;
  border:1px solid #444;border-radius:5px}
button,.btn{font-size:15px;padding:8px 16px;border-radius:6px;border:1px solid #444;
  background:#222;color:#eee;cursor:pointer;text-decoration:none;display:inline-block}
button.go{background:#136b2e;border-color:#2a9d4d}
.btn.stop{background:#7a1f1f;border-color:#a33}
img{display:block;max-width:100%%;height:auto;background:#000}
.k{color:#9f9} .w{color:#fc6} .bad{color:#f88} .dim{color:#888;font-size:13px}
</style></head><body>
<div class="bar"><b>副相机 · DF200</b> <span>%s</span></div>
<form class="bar" action="/start" method="get">
  <label>间隔(秒) <input name="interval" value="%.1f"></label>
  <label>下限(张) <input name="min" value="%d"></label>
  <label>上限(张) <input name="max" value="%d"></label>
  <button type="submit" class="go">开始采集</button>
</form>
<div class="bar">
  <a class="btn stop" href="/stop">停止采集</a>
  <a class="btn" href="/snap">拍一张单帧</a>
  <a class="btn" href="/status">进度(JSON)</a>
  <a class="btn" href="/">刷新本页</a>
</div>
<div class="bar"><span class="w">%s</span></div>
<div class="bar"><span class="dim">上次会话目录：%s</span></div>
<img src="/stream" alt="preview">
<div class="bar"><span class="dim">
不用按钮也行：地址栏直接开
http://&lt;Pi-IP&gt;:%d/start?interval=1.0&amp;min=110&amp;max=140 　/stop 　/snap 　/status
</span></div>
</body></html>""" % (cap, STATE["interval"], STATE["target_min"], STATE["target_max"],
                     hint, last, _ARGS.port))
        return html.encode("utf-8")
    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while STATE["running"]:
                jpg = _jpeg_bytes(_ARGS.stream_quality, _ARGS.stream_w)
                if jpg is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: %d\r\n\r\n" % len(jpg))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                time.sleep(1.0 / max(1.0, _ARGS.stream_fps))
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> int:
    global _ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--target-min", type=int, default=110)
    ap.add_argument("--target-max", type=int, default=140)
    ap.add_argument("--layout-every", type=int, default=4)
    ap.add_argument("--root", default="/home/pi/dataset_cam2")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--quality", type=int, default=95)
    ap.add_argument("--stream-quality", type=int, default=70)
    ap.add_argument("--stream-w", type=int, default=640)
    ap.add_argument("--stream-fps", type=float, default=10.0)
    ap.add_argument("--preview-only", action="store_true",
                    help="启动不自动采（从网页点【开始采集】）")
    _ARGS = ap.parse_args()

    STATE.update(target_min=_ARGS.target_min, target_max=_ARGS.target_max,
                 interval=_ARGS.interval, layout_every=_ARGS.layout_every,
                 layout_hint=LAYOUTS[0])

    cap = cv2.VideoCapture(_ARGS.dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, _ARGS.w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _ARGS.h)
    if not cap.isOpened():
        print("❌ 打不开 /dev/video%d（被占用？先 pkill -f pi_cam2_stream.py）" % _ARGS.dev)
        return 1
    real = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    for _ in range(8):
        cap.read()

    print("=" * 70)
    print("  副相机采集 · DF200（网页可控）")
    print("=" * 70)
    print("  设备     : /dev/video%d  实际 %dx%d" % (_ARGS.dev, real[0], real[1]))
    print("  输出根   : %s" % _ARGS.root)
    print("  网页     : http://<Pi-IP>:%d/   （【开始采集】【停止采集】【拍一张】）"
          % _ARGS.port)
    print("  接口     : /start?interval=1.0&min=110&max=140  /stop  /snap  /status")
    print("  🔴 铁律  : ① 90%% 照片要有远端物件 ② ≥30 张明显遮挡 ③ 补光灯全程开")
    print("=" * 70)

    threading.Thread(target=reader_loop, args=(cap,), daemon=True).start()
    if not _ARGS.preview_only:
        begin_session()

    srv = ThreadingHTTPServer(("0.0.0.0", _ARGS.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        STATE["running"] = False
        STATE["capturing"] = False
        time.sleep(0.2)
        srv.server_close()
        cap.release()
        print("=" * 70)
        print("  退出。最后会话：%s" % (STATE["last_dir"] or "（无）"))
        print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
