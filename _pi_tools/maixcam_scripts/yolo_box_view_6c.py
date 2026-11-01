"""MaixCAM YOLO 看框（6 类版，纯看图，不连树莓派）2026-10-27

## 这个文件干什么

在 MaixCAM 上跑 YOLO 检测，把框 / 类别 / 置信度画在屏幕上，
同时通过 TCP 把结果按**现有线上格式**发给树莓派。

**只测 YOLO 本身，不管颜色。**（颜色判定走另一条 HSV 路径）

## 三种用法

### 1. 纯看图（不发网络）
```
SEND_TO_PI=0
```
或在 MaixVision 里把 `SEND_TO_PI` 改成 `False`。

### 2. 看 + 发树莓派（默认）
树莓派上先起监听：
```
python3 /tmp/vision_listen.py 8765 60
```
然后这里直接运行。

### 3. 换模型
```
MODEL_NAME=yolo11n_7c_448   # 需要该 .cvimodel 已存在
```

## 线上格式（与 stage1_color_v6_send.py 一致，树莓派无需改）
```
count(1) + task_id(2,BE) + target[count]
每个 target 7 字节: id(1) + conf(1,0-100) + X(2,BE) + Y(2,BE) + angle(1)
```
YOLO 模式下 `id = class_id + 1`（1..N），`angle = 0xFF`（未用）。

## ⚠️ 已知坑（都是实测踩过的）

1. **`dual_buff=True` 会 SIGSEGV**（`No buffer space available`）⇒ 默认 False
2. **加载顺序必须是 相机 → 显示 → 模型**，先加载模型会吃光缓冲导致相机打不开
3. **MaixCAM busybox 没有 `timeout` 命令**
4. 模型目录里 `.mud` 和 `.cvimodel` 必须**同名配套**，`.mud` 里 `model=` 指向 `.cvimodel` 文件名
"""
from __future__ import annotations

import os
import socket
import struct
import time

from maix import app, camera, display, image, nn

# ── 配置 ────────────────────────────────────────────────────────────────────
MODEL_DIR = os.environ.get("MODEL_DIR", "/root/my_models")
MODEL_NAME = os.environ.get("MODEL_NAME", "yolo11n_6c_448_cv181x")   # 换成 7c 需先有 cvimodel
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME + ".mud")

FRAME_W = int(os.environ.get("FRAME_W", "1280"))
FRAME_H = int(os.environ.get("FRAME_H", "720"))

CONF_TH = float(os.environ.get("CONF_TH", "0.30"))
IOU_TH = float(os.environ.get("IOU_TH", "0.45"))
# 🔴 必须 False：True 会多占一份输出缓冲 ⇒ No buffer space available ⇒ SIGSEGV
DUAL_BUFF = False

SEND_TO_PI = os.environ.get("SEND_TO_PI", "0") == "1"
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "172.20.10.8")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8765"))
TASK_ID = int(os.environ.get("TASK_ID", "1"))
MIN_SEND_INTERVAL_S = 0.10

_ANGLE_NONE = 0xFF
_TARGET_BYTES = 7

# 类别名（与 .mud 的 labels 对齐；读不到时用序号兜底）
DEFAULT_LABELS = [
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "triangular_prism", "square_pyramid",
    "regular_tetrahedron",
]

# 中英对照，方便现场看
ZH = {
    "cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
    "hexagonal_prism": "六棱柱", "pentagonal_prism": "五棱柱",
    "triangular_prism": "三棱柱", "square_pyramid": "四棱锥",
    "regular_tetrahedron": "正四面体", "cone": "圆锥",
}

# 每类一个颜色画框
# ⚠️ 2026-10-25 实测：MaixPy 的 draw_rect/draw_string 的 color 参数
#    **必须是 maix.image.Color 对象**（如 image.COLOR_GREEN），
#    传普通 tuple (0,255,0) 会 TypeError: incompatible function arguments。
#    正确写法见 capture.py:165。下面用库里现成的常量兜底，缺哪个就退回白色。
def _mk_colors():
    names = ["COLOR_GREEN", "COLOR_YELLOW", "COLOR_BLUE", "COLOR_PURPLE",
             "COLOR_ORANGE", "COLOR_RED", "COLOR_CYAN", "COLOR_WHITE"]
    out = []
    for n in names:
        c = getattr(image, n, None)
        out.append(c if c is not None else getattr(image, "COLOR_WHITE"))
    return out


BOX_COLORS = _mk_colors()


class Sender:
    """把 YOLO 结果按现有线上格式发给树莓派。断线自动重连。"""

    def __init__(self, host, port, task_id, enable):
        self.host, self.port, self.task_id, self.enable = host, port, task_id, enable
        self.sock = None
        self.last = 0.0
        self.sent_frames = 0
        self.sent_items = 0

    def _ensure(self):
        if self.sock is not None:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self.host, self.port))
            s.settimeout(None)
            self.sock = s
            print("[send] connected %s:%d" % (self.host, self.port))
            return True
        except OSError as e:
            print("[send] connect failed: %s" % e)
            return False

    def send(self, objs, frame_w, frame_h):
        if not self.enable:
            return
        now = time.monotonic()
        if now - self.last < MIN_SEND_INTERVAL_S:
            return
        self.last = now
        payload = bytearray()
        for o in objs:
            cx = int(o.x + o.w / 2.0)
            cy = int(o.y + o.h / 2.0)
            if not (0 <= cx <= 0xFFFF and 0 <= cy <= 0xFFFF):
                continue
            cls = int(o.class_id) & 0xFF
            conf = max(0, min(100, int(round(float(o.score) * 100))))
            payload += struct.pack(">BBHHB", (cls + 1) & 0xFF, conf, cx, cy, _ANGLE_NONE)
        count = len(payload) // _TARGET_BYTES
        if count == 0:
            return
        if not self._ensure():
            return
        try:
            self.sock.sendall(bytes([count]) + struct.pack(">H", self.task_id) + bytes(payload))
            self.sent_frames += 1
            self.sent_items += count
        except OSError as e:
            print("[send] send failed: %s" % e)
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def draw(img, objs, labels, fps, elapsed_ms):
    """在 image 上画框与文字。

    ⚠️ 2026-10-25 实测踩坑（两条，都踩过）：
      1. `color` 必须是 `maix.image.Color` 对象（如 image.COLOR_GREEN），
         **传 tuple (0,255,0) 会 `TypeError: incompatible function arguments`**。
         正确写法见 capture.py:165。
      2. `thickness` 必须 ≥1；`thickness=-1`（填充）不支持。
    """
    for o in objs:
        cls = int(o.class_id)
        name = labels[cls] if 0 <= cls < len(labels) else str(cls)
        zh = ZH.get(name, "")
        color = BOX_COLORS[cls % len(BOX_COLORS)]
        img.draw_rect(int(o.x), int(o.y), int(o.w), int(o.h),
                      color=color, thickness=2)
        text = "%s%s %.2f" % (name, ("/" + zh) if zh else "", float(o.score))
        img.draw_string(int(o.x) + 2, max(0, int(o.y) - 16), text,
                        color=color, scale=1.2)
    # 顶部状态条：描边矩形（不支持填充）
    img.draw_rect(0, 0, img.width(), 22,
                  color=image.COLOR_BLACK, thickness=1)
    img.draw_string(3, 3, "YOLO %s %dx%d %dobj %.1fFPS %.1fms" % (
        MODEL_NAME, img.width(), img.height(), len(objs), fps, elapsed_ms),
        color=image.COLOR_GREEN, scale=1.2)


def main():
    print("=" * 60)
    print("MaixCAM YOLO 效果查看器")
    print("  MODEL_PATH = %s" % MODEL_PATH)
    print("  FRAME      = %dx%d" % (FRAME_W, FRAME_H))
    print("  CONF/IOU   = %.2f / %.2f" % (CONF_TH, IOU_TH))
    print("  SEND_TO_PI = %s -> %s:%d" % (SEND_TO_PI, GATEWAY_HOST, GATEWAY_PORT))
    print("=" * 60)

    if not os.path.exists(MODEL_PATH):
        print("❌ 模型不存在: %s" % MODEL_PATH)
        print("   .mud 和 .cvimodel 必须同名配套放在 %s 里" % MODEL_DIR)
        return

    # ── ① 相机 ──（顺序不能变：相机 → 显示 → 模型）
    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
        print("[1/3] camera OK %dx%d" % (FRAME_W, FRAME_H))
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   多半是 launcher_daemon 占着 —— 先 kill 掉它")
        return

    # ── ② 显示 ──
    disp = display.Display()
    print("[2/3] display OK")

    # ── ③ 模型（最后加载，避免吃光缓冲）──
    try:
        detector = nn.YOLO11(model=MODEL_PATH, dual_buff=DUAL_BUFF)
    except Exception as e:
        print("❌ 模型加载失败: %s" % e)
        return
    mw, mh = detector.input_width(), detector.input_height()
    print("[3/3] YOLO11 OK  input %dx%d  dual_buff=%s" % (mw, mh, DUAL_BUFF))

    # 尝试从 .mud 读 labels（拿不到就用默认）
    labels = DEFAULT_LABELS
    try:
        obj = detector
        if hasattr(obj, "labels") and obj.labels:
            labels = list(obj.labels)
            print("      labels from model: %s" % ", ".join(labels))
    except Exception:
        pass

    sender = Sender(GATEWAY_HOST, GATEWAY_PORT, TASK_ID, SEND_TO_PI)
    print("开始检测（Ctrl-C 或 MaixVision 停止按钮退出）")

    # 预热：等 AE/AWB 收敛（前几帧颜色/亮度会变）
    warmup = float(os.environ.get("WARMUP_S", "1.5"))
    t0 = time.time()
    while time.time() - t0 < warmup and not app.need_exit():
        cam.read()
    print("预热完成")

    fps = 0.0
    last_t = time.time()
    n = 0
    try:
        while not app.need_exit():
            frame = cam.read()
            t1 = time.time()

            try:
                objs = detector.detect(frame, conf_th=CONF_TH, iou_th=IOU_TH)
            except Exception as e:
                print("detect 异常: %s" % e)
                objs = []

            elapsed_ms = (time.time() - t1) * 1000.0
            n += 1
            if n % 10 == 0:
                now = time.time()
                fps = 10.0 / max(1e-6, now - last_t)
                last_t = now

            draw(frame, objs, labels, fps, elapsed_ms)
            disp.show(frame)

            # 打印到 MaixVision 控制台（每类计数）
            if n % 30 == 0 and objs:
                parts = []
                for o in objs:
                    cls = int(o.class_id)
                    nm = labels[cls] if 0 <= cls < len(labels) else str(cls)
                    parts.append("%s(%.2f)" % (nm, float(o.score)))
                print("[%d obj] %s" % (len(objs), "  ".join(parts)))

            sender.send(objs, FRAME_W, FRAME_H)
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        sender.close()
        print("=" * 60)
        print("结束：发出 %d 帧 / %d 件" % (sender.sent_frames, sender.sent_items))
        print("=" * 60)


if __name__ == "__main__":
    main()
