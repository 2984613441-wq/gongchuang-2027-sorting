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
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print("❌ 模型不存在: %s" % args.model)
        return 1

    print("=" * 66)
    print("  MaixCAM v11 → 8765 发送")
    print("=" * 66)
    print("  model  = %s" % args.model)
    print("  target = %s:%d  task_id=%d  conf=%.2f"
          % (args.host, args.port, args.task_id, args.conf))
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

    print("开始（Ctrl-C 停止）")
    try:
        while not app.need_exit():
            if args.seconds > 0 and (time.time() - t_start) >= args.seconds:
                break
            frame = cam.read()
            if frame is None:
                continue
            frames += 1

            t0 = time.time()
            try:
                objs = detector.detect(frame, conf_th=args.conf, iou_th=args.iou)
            except Exception as e:
                print("detect 异常: %s" % e)
                objs = []
            ms = (time.time() - t0) * 1000.0

            dets = []
            for o in objs:
                cls = int(o.class_id)
                if cls not in SHAPE_ID:
                    continue          # 只发 6 类（防越界 id 让整批被拒）
                cx = int(o.x + o.w / 2)
                cy = int(o.y + o.h / 2)
                dets.append((SHAPE_ID[cls], int(round(float(o.score) * 100)), cx, cy))

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
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        sender.close()
        el = max(1e-6, time.time() - t_start)
        print("=" * 66)
        print("结束: %.1fs, 帧=%d (%.1f fps), 发送=%d 成功帧=%d, 失败=%d"
              % (el, frames, frames / el, sender.sent, ok_frames, sender.failed))
        print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
