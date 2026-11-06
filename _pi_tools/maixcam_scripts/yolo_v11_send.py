#!/usr/bin/env python3
"""MaixCAM v11 六类 · 检测 → 8765 发送（最小闭环用）  2026-10-29

## 这是什么

把 **v11 形状模型**接上**树莓派的 8765 线格式**，让"视觉能不能把数据发出去"这件事
可以被实测，而不是靠推断。

    camera.read() → nn.YOLO11(v11) → 过滤 6 类 → 编 BATCH_TARGETS → TCP 8765

## 线格式（与 电控/src/electrical_control/rpi/vision_ingest.py 一致）

    target_count(1) + task_id(2, 大端) + target[N]
    target = class_id(1) + conf(1, 0~100) + X(2,大端) + Y(2,大端) + angle(1, 0xFF)
    X/Y = bbox 中心像素坐标（不标定，只用于去重/排序/复核定位，不直接进运动）

## ⚠️ id 字节语义（重要，别当正式方案用）

树莓派侧现在 `vision_ingest.BATCH_ID_BYTE_IS_BOX_ID = True`
⇒ 它把 **id 字节当 box_id(1..6)** 用（校赛口径：box_id 由颜色唯一决定形状）。

本脚本暂时发 **shape_id = class_id + 1**（cube→1 … tetrahedron→6），目的只有两个：
  1) 验证"设备 → 树莓派 → 8765 解析"这条线真的通
  2) 让 p_go8.sh 的视觉门禁（数 `box_id=` 行）能看到件

🔴 **它不代表正式分拣口径**：省赛是「颜色 × 形状解耦」，正式链路应改成
   `code(1..30) = (shape_id-1)*5 + color_id + 1`，并把树莓派
   `BATCH_ID_BYTE_IS_BOX_ID` 改 False + 补 group_table（L4，需授权）。
   在那之前不要拿本脚本跑 `run_chain.py`，只用于联调/验证。

## 用法（在 MaixCAM 上）

    python3 -u /root/yolo_v11_send.py                       # 连发，Ctrl-C 停
    python3 -u /root/yolo_v11_send.py --seconds 12          # 跑 12 秒自动退（联调用）
    python3 -u /root/yolo_v11_send.py --display 1           # 同时在屏幕画框
    python3 -u /root/yolo_v11_send.py --dry-run             # 只打印不联网

## 已知坑（与观测版同源，别改回去）

    1. dual_buff=True ⇒ SIGSEGV；image2cv(copy=True) 在 128MB 下也会崩
    2. 加载顺序：相机 → 显示 → 模型
    3. detect() 必须传 maix image.Image，不能传 numpy
"""
from __future__ import annotations

import argparse
import os
import socket
import time

from maix import app, camera, display, image, nn

MODEL_DEFAULT = "/root/my_models/yolo11n_6c_v11_448_cv181x.mud"
LABELS = ["cube", "cuboid", "cylinder",
          "pentagonal_prism", "cone", "tetrahedron"]
# shape_id 1..6（与 stage1_color_v6_send.SHAPE_TO_ID 对齐）
SHAPE_ID = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6}

# ── 2026-11-01 新增：颜色判定 + code(1..30) 编码（协议 V1.0 口径）────────────
# code = (shape-1)*5 + color + 1
#   shape 1..6 = cube/cuboid/cylinder/pentagonal_prism/cone/tetrahedron
#   color 1..5 = red / yellow / green / blue / white
# ⚠️ 下面 5 组 HSV 阈值【待实测】：必须在**固定补光灯 + 锁定曝光/AWB**下标定。
#    未标定前建议 --id-mode shape（默认，保持现状）。
COLOR_NAMES = ("red", "yellow", "green", "blue", "white")
CODE_UNKNOWN = 0


def _rgb_to_hsv255(r: int, g: int, b: int):
    """RGB(0..255) → (H 0..255, S 0..255, V 0..255)，不依赖 colorsys。"""
    mx = max(r, g, b)
    mn = min(r, g, b)
    v = mx
    if mx == 0:
        return 0, 0, 0
    s_ = int(round(255.0 * (mx - mn) / mx))
    d = mx - mn
    if d == 0:
        return 0, s_, v
    if mx == r:
        h = (60.0 * ((g - b) / float(d))) % 360.0
    elif mx == g:
        h = 60.0 * ((b - r) / float(d)) + 120.0
    else:
        h = 60.0 * ((r - g) / float(d)) + 240.0
    return int(round(h / 360.0 * 255.0)) % 256, s_, v


def classify_color_hsv(r: int, g: int, b: int) -> int:
    """返回 color 1..5；判不出返回 0。阈值【待实测】。"""
    h, s_, v = _rgb_to_hsv255(r, g, b)
    if s_ < 40 and v >= 150:
        return 5          # white：低饱和 + 高亮
    if v < 40:
        return 0          # 太暗，不猜
    if s_ < 40:
        return 0          # 灰/暗灰，不猜
    if h < 12 or h >= 243:
        return 1          # red（红色跨 0 界）
    if 12 <= h < 38:
        return 2          # yellow
    if 38 <= h < 100:
        return 3          # green
    if 100 <= h < 175:
        return 4          # blue
    return 0              # 其余（紫/橙过渡带）不猜


def _sample_rgb(img, x: int, y: int):
    """取一个像素的 RGB；越界/接口不适用返回 None。"""
    try:
        px = img.get_pixel(int(x), int(y))
    except Exception:
        return None
    if px is None:
        return None
    if isinstance(px, int):                      # 兼容灰度/打包格式
        return (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
    if len(px) >= 3:
        return int(px[0]), int(px[1]), int(px[2])
    return None


def color_of_box(img, x: int, y: int, w: int, h: int) -> int:
    """框内 5 点采样投票 → color 1..5；无有效票返回 0。"""
    pts = [(0.50, 0.50), (0.25, 0.50), (0.75, 0.50), (0.50, 0.25), (0.50, 0.75)]
    votes = {}
    for fx, fy in pts:
        rgb = _sample_rgb(img, x + int(w * fx), y + int(h * fy))
        if rgb is None:
            continue
        c = classify_color_hsv(*rgb)
        if c:
            votes[c] = votes.get(c, 0) + 1
    if not votes:
        return 0
    best = max(votes.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 2 else 0        # 至少 2 票才算数，避免噪声


def code_of(shape_id: int, color_id: int) -> int:
    """(shape 1..6, color 1..5) → code(1..30)；color=0 返回 CODE_UNKNOWN。"""
    if not color_id:
        return CODE_UNKNOWN
    return (int(shape_id) - 1) * 5 + int(color_id)
ANGLE_NONE = 0xFF


def encode_batch_targets(dets, task_id: int) -> bytes:
    """dets: [(shape_id, conf0_100, cx, cy)] → BATCH_TARGETS bytes."""
    body = bytearray([len(dets)])
    body += int(task_id).to_bytes(2, "big")
    for shape_id, conf, cx, cy in dets:
        body += bytes((shape_id & 0xFF, max(0, min(100, int(conf)))))
        body += int(cx).to_bytes(2, "big")
        body += int(cy).to_bytes(2, "big")
        body += bytes((ANGLE_NONE,))
    return bytes(body)


# ---------------------------------------------------------------------------
# 2026-11-05：可选 HTTP 快照服务（GET /snap → 当前帧 JPEG）
# 给 PC 的 _pi_tools/three_way_view.py 当"主相机画面"用；不开也不影响发送。
# ---------------------------------------------------------------------------
_snap_latest = {"jpeg": b""}


def _jpeg_of(frame):
    """把当前帧编码成 JPEG。依次尝试多种 MaixPy API，全失败返回 b""。

    MaixPy 各版本 API 不一致：有的有 to_jpeg()，有的只能 save() 到文件。
    最后一条路是 save() 到 /tmp 再读文件（慢一点，但稳）。
    """
    for name in ("to_jpeg", "to_jpg"):
        fn = getattr(frame, name, None)
        if callable(fn):
            try:
                data = fn()
                if data:
                    return bytes(data)
            except Exception:
                pass
    # 退路：save 到文件再读
    try:
        path = "/tmp/_snap_cur.jpg"
        frame.save(path)
        with open(path, "rb") as f:
            data = f.read()
        if data:
            return data
    except Exception:
        pass
    return b""


def _snap_server(port: int):
    import socket as _socket
    import threading as _threading

    def handle(conn):
        try:
            conn.settimeout(2.0)
            req = b""
            while b"\r\n\r\n" not in req and len(req) < 2048:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                req += chunk
            jpeg = _snap_latest["jpeg"]
            if not jpeg:
                body = b"no frame yet\n"
                conn.sendall(b"HTTP/1.1 503 Service Unavailable\r\n"
                             b"Content-Type: text/plain\r\n"
                             b"Content-Length: " + str(len(body)).encode() +
                             b"\r\nConnection: close\r\n\r\n" + body)
                return
            conn.sendall(b"HTTP/1.1 200 OK\r\n"
                         b"Content-Type: image/jpeg\r\n"
                         b"Content-Length: " + str(len(jpeg)).encode() +
                         b"\r\nConnection: close\r\n"
                         b"Cache-Control: no-store\r\n\r\n" + jpeg)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def loop():
        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", int(port)))
        srv.listen(4)
        print("快照服务：http://0.0.0.0:%d/snap" % int(port))
        while True:
            try:
                conn, _ = srv.accept()
            except Exception:
                continue
            _threading.Thread(target=handle, args=(conn,), daemon=True).start()

    _threading.Thread(target=loop, daemon=True).start()


class Sender:
    def __init__(self, host: str, port: int, dry_run: bool = False):
        self.host = host
        self.port = port
        self.dry_run = dry_run
        self.sock = None
        self.sent = 0
        self.failed = 0

    def _connect(self):
        if self.sock is not None or self.dry_run:
            return self.sock
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((self.host, self.port))
            self.sock = s
        except Exception:
            s.close()
            self.sock = None
        return self.sock

    def send(self, payload: bytes) -> bool:
        if self.dry_run:
            self.sent += 1
            return True
        s = self._connect()
        if s is None:
            self.failed += 1
            return False
        try:
            s.sendall(payload)
            self.sent += 1
            return True
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            self.sock = None
            self.failed += 1
            return False

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--host", default="172.20.10.8")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--task-id", type=int, default=1, help="不能是 0")
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--fps", type=float, default=6.0, help="最大处理节奏")
    ap.add_argument("--seconds", type=float, default=0.0, help=">0 则跑这么久自动退")
    ap.add_argument("--display", type=int, default=0, help="1 = 屏幕同步显示")
    ap.add_argument("--dry-run", action="store_true", help="只打印不联网")
    ap.add_argument("--verbose", type=int, default=1)
    ap.add_argument("--snap-port", type=int, default=0,
                    help=">0 时在本机开 HTTP 快照服务（GET /snap 返回当前帧 JPEG），"
                         "给 PC 三路窗口当主相机画面用；0=不开")
    ap.add_argument("--id-mode", choices=("shape", "code"), default="shape",
                    help="id 字节语义：shape=shape_id(1..6)（默认，现状）；"
                         "code=code(1..30)（协议 V1.0，颜色进链路）")
    # 🆕 2026-11-06：分类别置信度阈值（默认空 = 关闭，保持现状）
    ap.add_argument("--min-conf-by-class", type=str, default="",
                    help='分类别置信度阈值，格式"class_id:threshold,class_id:threshold"'
                         '（class_id 0-based），不写的类用 --conf；'
                         '例："2:0.55,3:0.55" 对 cylinder/penta 用 0.55，其他用 0.40；'
                         '⚠️ 分类别阈值应 ≥ --conf（低于全局阈值时不起作用）')
    ap.add_argument("--unknown-as-code0", action="store_true",
                    help="--id-mode code 时，置信度介于 --conf 与分类阈值之间的件"
                         "发 code=0（判不出）而不是丢掉；默认关闭（保持现状：直接丢掉）")
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print("❌ 模型不存在: %s" % args.model)
        return 1

    # 🆕 2026-11-06：解析分类别置信度阈值
    class_conf_map = {}
    if args.min_conf_by_class:
        try:
            for pair in args.min_conf_by_class.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                cid_str, thresh_str = pair.split(":")
                cid = int(cid_str.strip())
                thresh = float(thresh_str.strip())
                class_conf_map[cid] = thresh
        except Exception as e:
            print("❌ --min-conf-by-class 格式错误: %s" % e)
            print("   正确格式示例: \"2:0.55,3:0.55\"")
            return 1

    print("=" * 66)
    print("  MaixCAM v11 → 8765 发送")
    print("=" * 66)
    print("  model  = %s" % args.model)
    print("  target = %s:%d  task_id=%d  conf=%.2f"
          % (args.host, args.port, args.task_id, args.conf))
    if class_conf_map:
        print("  分类别阈值 = %s" % class_conf_map)
    if args.unknown_as_code0:
        print("  低置信发 code=0 已启用（--unknown-as-code0）")
    print("  note   = id_byte 暂发 shape_id(1..6)，**不是正式 code(1..30)**")

    # ① 相机 → ② 显示 → ③ 模型（顺序不能反）
    try:
        cam = camera.Camera(1280, 720, image.Format.FMT_RGB888)
        print("[1/3] camera OK 1280x720 RGB888")
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   先执行: killall launcher_daemon")
        return 1
    disp = None
    if args.display:
        disp = display.Display()
        print("[2/3] display OK")
    else:
        print("[2/3] display off")
    try:
        detector = nn.YOLO11(model=args.model, dual_buff=False)   # dual_buff=True ⇒ 崩
    except Exception as e:
        print("❌ 模型加载失败: %s" % e)
        return 1
    print("[3/3] YOLO11 OK  input %dx%d"
          % (detector.input_width(), detector.input_height()))

    sender = Sender(args.host, args.port, dry_run=args.dry_run)
    t_start = time.time()
    last_send = 0.0
    last_beat = 0.0
    frames = 0
    last_print = t_start
    ok_frames = 0
    # 🆕 2026-11-06：每帧统计（sent / dropped_low_conf / dropped_class）
    stats_sent = 0
    stats_dropped_low_conf = 0
    stats_dropped_class = 0

    if args.snap_port > 0:
        _snap_server(args.snap_port)

    print("开始（Ctrl-C 停止）")
    try:
        while not app.need_exit():
            if args.seconds > 0 and (time.time() - t_start) >= args.seconds:
                break
            frame = cam.read()
            if frame is None:
                continue
            frames += 1
            if args.snap_port > 0:
                # 约 10 fps 更新快照，避免编码占用检测时间
                if frames % max(1, int(round(30 / max(1.0, args.fps)))) == 0:
                    _snap_latest["jpeg"] = _jpeg_of(frame)

            t0 = time.time()
            try:
                objs = detector.detect(frame, conf_th=args.conf, iou_th=args.iou)
            except Exception as e:
                print("detect 异常: %s" % e)
                objs = []
            ms = (time.time() - t0) * 1000.0

            dets = []
            frame_dropped_low = 0
            frame_dropped_class = 0
            for o in objs:
                cls = int(o.class_id)
                if cls not in SHAPE_ID:
                    continue          # 只发 6 类（防越界 id 让整批被拒）

                # 🆕 2026-11-06：分类别置信度阈值判定
                # 🔴 2026-11-07：effective_thresh 必须 >= args.conf（分类阈值低于全局阈值时不起作用）
                conf_score = float(o.score)
                effective_thresh = max(args.conf, class_conf_map.get(cls, args.conf))

                # 判定：conf < 全局阈值 ⇒ 丢弃（原有逻辑）
                if conf_score < args.conf:
                    frame_dropped_low += 1
                    continue

                # 判定：conf ∈ [全局阈值, 分类阈值) ⇒ 看 --unknown-as-code0
                if conf_score < effective_thresh:
                    if args.unknown_as_code0 and args.id_mode == "code":
                        # 发 code=0（判不出）
                        cx = int(o.x + o.w / 2)
                        cy = int(o.y + o.h / 2)
                        dets.append((CODE_UNKNOWN, int(round(conf_score * 100)), cx, cy))
                        stats_sent += 1
                    else:
                        # 默认：丢弃
                        frame_dropped_class += 1
                    continue

                # 通过阈值：正常编码
                cx = int(o.x + o.w / 2)
                cy = int(o.y + o.h / 2)
                shape_id = SHAPE_ID[cls]
                if args.id_mode == "code":
                    color_id = color_of_box(frame, int(o.x), int(o.y),
                                            int(o.w), int(o.h))
                    id_byte = code_of(shape_id, color_id)
                else:
                    id_byte = shape_id
                dets.append((id_byte, int(round(conf_score * 100)), cx, cy))
                stats_sent += 1

            stats_dropped_low_conf += frame_dropped_low
            stats_dropped_class += frame_dropped_class

            now = time.time()
            # 有件 ⇒ 立刻发；无件 ⇒ 500ms 心跳空帧（让树莓派区分"没货"和"断链"）
            if dets and (now - last_send) >= (1.0 / max(0.1, args.fps)):
                payload = encode_batch_targets(dets, args.task_id)
                ok = sender.send(payload)
                last_send = now
                if ok:
                    ok_frames += 1
                if args.verbose and ok:
                    print("[t=%.1fs] %d 件 → %d B: %s"
                          % (now - t_start, len(dets), len(payload),
                             " ".join("%s(%.2f)@(%d,%d)"
                                      % (LABELS[o.class_id], float(o.score),
                                         int(o.x + o.w / 2), int(o.y + o.h / 2))
                                      for o in objs if int(o.class_id) in SHAPE_ID)))
            elif not dets and (now - last_beat) >= 0.5:
                ok = sender.send(encode_batch_targets([], args.task_id))
                last_beat = now
                if not ok and args.verbose:
                    print("[t=%.1fs] 心跳发送失败（树莓派没在监听 8765？）" % (now - t_start))

            if disp is not None and objs:
                for o in objs:
                    frame.draw_rect(int(o.x), int(o.y), int(o.w), int(o.h),
                                    color=image.COLOR_RED, thickness=3)
                disp.show(frame)

            if args.verbose and (now - last_print) >= 5.0:
                last_print = now
                print("[统计 t=%.0fs] 帧=%d 已发送=%d 失败=%d 检测耗时=%.1fms"
                      % (now - t_start, frames, sender.sent, sender.failed, ms))
                if class_conf_map or args.unknown_as_code0:
                    print("              目标统计：sent=%d dropped_low_conf=%d dropped_class=%d"
                          % (stats_sent, stats_dropped_low_conf, stats_dropped_class))
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        sender.close()
        el = max(1e-6, time.time() - t_start)
        print("=" * 66)
        print("结束: %.1fs, 帧=%d (%.1f fps), 发送=%d 成功帧=%d, 失败=%d"
              % (el, frames, frames / el, sender.sent, ok_frames, sender.failed))
        if class_conf_map or args.unknown_as_code0:
            print("目标统计：sent=%d dropped_low_conf=%d dropped_class=%d"
                  % (stats_sent, stats_dropped_low_conf, stats_dropped_class))
        print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
