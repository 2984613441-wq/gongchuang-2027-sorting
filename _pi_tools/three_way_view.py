# -*- coding: utf-8 -*-
r"""三路对比视图：**主相机判断 / 副相机判断 / 两者融合**（2026-11-05）。

用途（实验室现场）：
  * 主相机（MaixCAM）通过 TCP 8765 发 `BATCH_TARGETS`（3B 头 + N×7B）
  * 副相机（DF200，插在树莓派）通过 Pi 的 HTTP 快照接口取帧
  * PC 本地推理副相机模型（可选 ONNX）+ HSV 判色，或只看主相机结果
  * 同时打印/显示三块：①主相机判断 ②副相机判断 ③融合判断（CONFIRMED/CONTRADICTED/UNPROVEN）

边界
----
* 只读：不连 STM32、不写串口、不动固件、不改协议。
* 没有 cv2/onnxruntime 时仍可跑「终端模式」（`--headless --no-image`），用 `--cam2-json` 读离线结果。

用法示例
--------
```powershell
# 1) 现场：主相机 + 副相机实时（有画面）
python _pi_tools/three_way_view.py --maixcam 172.20.10.9 --cam2-url http://172.20.10.8:8080/snap

# 2) 只看终端结论，不开窗口
python _pi_tools/three_way_view.py --headless

# 3) 副相机做 6 类模型推理（PC 上有 onnxruntime）
python _pi_tools/three_way_view.py --model _deploy_maixcam\yolo11n_6c_cam2.onnx

# 4) 保存证据（每轮一张副相机图 + 一份 json）
python _pi_tools/three_way_view.py --evidence _three_way_evidence

# 5) 自检（无设备、无 cv2 也能跑）
python _pi_tools/three_way_view.py --self-test
```
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path

SHAPES = {1: "cube", 2: "cuboid", 3: "cylinder", 4: "pentagonal_prism",
          5: "cone", 6: "tetrahedron"}
COLORS = {1: "red", 2: "yellow", 3: "green", 4: "blue", 5: "white"}
_ANGLE_NONE = 0xFF
_TARGET_BYTES = 7

# HSV 阈值（cv2 口径 H 0..179）—— 与电控/rpi/color_judge.py 保持一致，仍为【待实测】
COLOR_HSV = {
    "red": [((0, 90, 60), (10, 255, 255)), ((170, 90, 60), (179, 255, 255))],
    "yellow": [((11, 80, 80), (28, 255, 255))],
    "green": [((29, 60, 60), (80, 255, 255))],
    "blue": [((81, 80, 50), (130, 255, 255))],
    "white": [((0, 0, 170), (179, 60, 255))],
}


# --------------------------------------------------------------------------- #
# 依赖探测（没有 cv2/numpy 也能跑终端模式）
# --------------------------------------------------------------------------- #
def _try(mod: str):
    try:
        return __import__(mod)
    except Exception:
        return None


cv2 = _try("cv2")
np = _try("numpy")


def have_images() -> bool:
    return cv2 is not None and np is not None


# --------------------------------------------------------------------------- #
# 报文解析（主相机 BATCH_TARGETS）
# --------------------------------------------------------------------------- #
def parse_batch(body: bytes, id_mode: str = "shape") -> tuple[int, list[dict]]:
    """解析 `count(1) + task_id(2 BE) + N×7B`。

    ``id_mode``：``shape`` ⇒ id 字节是 shape_id(1..6)（默认，现状）；
                 ``code``  ⇒ id 字节是 code(1..30)。
    """
    if len(body) < 3:
        return 0, []
    count = body[0]
    task_id = int.from_bytes(body[1:3], "big")
    items: list[dict] = []
    off = 3
    for i in range(count):
        if off + _TARGET_BYTES > len(body):
            break
        id_byte = body[off]
        rec = {
            "seq": i + 1,
            "id": id_byte,
            "conf": body[off + 1],
            "x": int.from_bytes(body[off + 2:off + 4], "big"),
            "y": int.from_bytes(body[off + 4:off + 6], "big"),
        }
        if id_mode == "code":
            if 1 <= id_byte <= 30:
                rec["shape"] = (id_byte - 1) // 5 + 1
                rec["color"] = (id_byte - 1) % 5 + 1
            else:
                rec["shape"] = rec["color"] = 0
        else:
            rec["shape"] = id_byte if 1 <= id_byte <= 6 else 0
            rec["color"] = 0
        items.append(rec)
        off += _TARGET_BYTES
    return task_id, items


def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class MainCamClient:
    """连 MaixCAM 的 TCP 8765，一次收一整批 BATCH_TARGETS。"""

    def __init__(self, host: str, port: int = 8765, id_mode: str = "shape"):
        self.host, self.port, self.id_mode = host, port, id_mode
        self.sock: socket.socket | None = None

    def connect(self, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def recv_one(self) -> tuple[int, list[dict]] | None:
        if self.sock is None:
            return None
        hdr = recv_exact(self.sock, 3)
        if hdr is None:
            return None
        count = hdr[0]
        body = hdr + (recv_exact(self.sock, count * _TARGET_BYTES) or b"")
        return parse_batch(body, self.id_mode)


# --------------------------------------------------------------------------- #
# 副相机：取帧 + 判色 + 可选 ONNX
# --------------------------------------------------------------------------- #
def grab_jpeg(url: str, timeout: float = 6.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
    if cv2 is None or np is None:
        raise RuntimeError("没有 cv2/numpy：无法解码副相机图像（请用 --cam2-json 离线模式）")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("副相机图像解码失败")
    return img


def color_of(bgr) -> tuple[str, float]:
    """整帧 HSV 主色（副相机落料位/托盘局部用；现场按需裁 ROI）。"""
    if cv2 is None or np is None:
        return "unknown", 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    best, best_frac = "unknown", 0.0
    for name, ranges in COLOR_HSV.items():
        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mask = m if mask is None else (mask | m)
        frac = float(mask.mean() / 255.0) if mask is not None else 0.0
        if frac > best_frac:
            best, best_frac = name, frac
    return best, round(best_frac, 3)


class Cam2Model:
    """可选：副相机 6 类 ONNX 推理（没有 onnxruntime/文件时自动降级为只用 HSV）。"""

    def __init__(self, model_path: str | None, conf: float = 0.30, size: int = 448):
        self.ok = False
        self.reason = "未启用"
        self.conf, self.size = conf, size
        if not model_path:
            return
        if not Path(model_path).exists():
            self.reason = "模型不存在：%s" % model_path
            return
        ort = _try("onnxruntime")
        if ort is None or np is None or cv2 is None:
            self.reason = "缺 onnxruntime/numpy/cv2"
            return
        try:
            self.sess = ort.InferenceSession(model_path,
                                             providers=["CPUExecutionProvider"])
            self.input_name = self.sess.get_inputs()[0].name
            self.ok = True
            self.reason = "ok"
        except Exception as exc:                       # pragma: no cover
            self.reason = "加载失败：%s" % exc

    def detect(self, bgr) -> list[dict]:
        if not self.ok or cv2 is None or np is None:
            return []
        h, w = bgr.shape[:2]
        s = self.size
        img = cv2.resize(bgr, (s, s))
        blob = img[:, :, ::-1].astype("float32").transpose(2, 0, 1)[None] / 255.0
        out = self.sess.run(None, {self.input_name: blob})[0]
        # YOLO11 输出：(1, 4+nc, N) 或 (1, N, 4+nc)
        pred = out[0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        boxes, scores, classes = [], [], []
        for row in pred:
            cx, cy, bw, bh = row[:4]
            cls_scores = row[4:]
            cid = int(cls_scores.argmax())
            conf = float(cls_scores[cid])
            if conf < self.conf:
                continue
            boxes.append([cx - bw / 2, cy - bh / 2, bw, bh])
            scores.append(conf)
            classes.append(cid)
        dets = []
        for box, conf, cid in zip(boxes, scores, classes):
            cx, cy, bw, bh = box
            # 输出是中心点+宽高（已按 448 缩放），换算回原图
            x1 = int((cx - bw / 2) * w / s)
            y1 = int((cy - bh / 2) * h / s)
            x2 = int((cx + bw / 2) * w / s)
            y2 = int((cy + bh / 2) * h / s)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = bgr[y1:y2, x1:x2]
            cname, frac = color_of(crop) if crop.size else ("unknown", 0.0)
            dets.append({"shape": cid + 1, "shape_name": SHAPES.get(cid + 1, "?"),
                         "conf": round(conf, 3), "color": cname,
                         "box": (x1, y1, x2, y2)})
        return dets


# --------------------------------------------------------------------------- #
# 融合判决（不改协议，只在 PC 显示）
# --------------------------------------------------------------------------- #
def verdict_set(main_items: list[dict], cam2: dict | None) -> dict:
    """集合模式（无单应标定）：比较**形状计数**与颜色集合。"""
    main_shapes: dict[int, int] = {}
    for it in main_items:
        main_shapes[it["shape"]] = main_shapes.get(it["shape"], 0) + 1
    if cam2 is None:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "副相机无数据",
                "main": main_shapes, "cam2": {}}
    cam2_shapes: dict[int, int] = {}
    for d in cam2.get("detections", []):
        cam2_shapes[d["shape"]] = cam2_shapes.get(d["shape"], 0) + 1

    if not main_shapes:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "主相机本帧无件",
                "main": {}, "cam2": cam2_shapes}
    if not cam2_shapes:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "副相机本帧无件",
                "main": main_shapes, "cam2": {}}
    if main_shapes == cam2_shapes:
        return {"mode": "set", "verdict": "CONFIRMED", "reason": "形状计数一致",
                "main": main_shapes, "cam2": cam2_shapes}
    only_main = {k: v for k, v in main_shapes.items() if cam2_shapes.get(k) != v}
    return {"mode": "set", "verdict": "CONTRADICTED",
            "reason": "形状计数不一致（主相机多/少的形状：%s）" % only_main,
            "main": main_shapes, "cam2": cam2_shapes}


def verdict_point(main_items: list[dict], cam2: dict | None,
                  radius: float = 90.0, scale: float = 1.0,
                  dx: float = 0.0, dy: float = 0.0) -> dict:
    """点模式（粗略线性映射，**不是标定**）：主相机点 → 副相机点最近邻匹配。"""
    if cam2 is None:
        return {"mode": "point", "verdict": "UNPROVEN", "reason": "副相机无数据",
                "pairs": []}
    dets = cam2.get("detections", [])
    pairs, unmatched = [], []
    for it in main_items:
        mx = it["x"] * scale + dx
        my = it["y"] * scale + dy
        best, best_d = None, 1e9
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            dist = ((cx - mx) ** 2 + (cy - my) ** 2) ** 0.5
            if dist < best_d:
                best, best_d = d, dist
        if best is not None and best_d <= radius:
            pairs.append({"seq": it["seq"], "main_shape": it["shape"],
                          "cam2_shape": best["shape"], "cam2_color": best["color"],
                          "dist_px": round(best_d, 1),
                          "same_shape": it["shape"] == best["shape"]})
        else:
            unmatched.append(it["seq"])
    if not main_items:
        verdict = "UNPROVEN"
    elif not pairs:
        verdict = "UNPROVEN"
    elif all(p["same_shape"] for p in pairs) and not unmatched:
        verdict = "CONFIRMED"
    else:
        verdict = "CONTRADICTED"
    return {"mode": "point", "verdict": verdict, "pairs": pairs,
            "unmatched_main": unmatched,
            "reason": "未匹配主相机件：%s" % unmatched if unmatched else ""}


# --------------------------------------------------------------------------- #
# 展示：终端三块 + 可选三栏窗口
# --------------------------------------------------------------------------- #
def _fmt_shape(shape: int) -> str:
    return "%d(%s)" % (shape, SHAPES.get(shape, "?"))


def render_terminal(main_items, cam2, fusion, round_no: int) -> str:
    lines = []
    lines.append("=" * 74)
    lines.append("第 %d 批   主相机 %d 件" % (round_no, len(main_items)))
    lines.append("-" * 74)
    lines.append("[1] 主相机判断（MaixCAM → BATCH_TARGETS）")
    if not main_items:
        lines.append("    （无件）")
    for it in main_items:
        lines.append("    seq=%d 形状=%s conf=%d 像素=(%d,%d)" % (
            it["seq"], _fmt_shape(it["shape"]), it["conf"], it["x"], it["y"]))

    lines.append("[2] 副相机判断（DF200 via Pi 快照）")
    if cam2 is None:
        lines.append("    （无数据）")
    else:
        lines.append("    全帧主色=%s(%.3f)  检测 %d 件  模型=%s" % (
            cam2.get("frame_color", "?"), cam2.get("frame_color_frac", 0.0),
            len(cam2.get("detections", [])), cam2.get("model", "off")))
        for d in cam2.get("detections", []):
            lines.append("    %s  conf=%.2f 颜色=%s 框=%s" % (
                _fmt_shape(d["shape"]), d["conf"], d["color"], d["box"]))

    lines.append("[3] 融合判断")
    lines.append("    模式=%s  结论=%s  %s" % (
        fusion["mode"], fusion["verdict"], fusion.get("reason", "")))
    if fusion["mode"] == "point":
        for p in fusion.get("pairs", []):
            lines.append("    seq=%d 主=%s 副=%s(色=%s) 距=%.1fpx %s" % (
                p["seq"], _fmt_shape(p["main_shape"]),
                _fmt_shape(p["cam2_shape"]), p["cam2_color"], p["dist_px"],
                "✓" if p["same_shape"] else "✗"))
    else:
        lines.append("    主相机形状计数=%s" % fusion.get("main"))
        lines.append("    副相机形状计数=%s" % fusion.get("cam2"))
    return "\n".join(lines)


def render_window(state: dict, size=(1280, 720)) -> None:
    """三栏窗口：主相机结果画布 | 副相机实时帧 | 融合文本。"""
    if cv2 is None or np is None:
        return
    w, h = size
    col_w = w // 3
    canvas = np.zeros((h, w, 3), np.uint8)

    # 左：主相机（无图像，画点阵 + 文本）
    panel = np.zeros((h, col_w, 3), np.uint8)
    cv2.putText(panel, "MAIN (MaixCAM)", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    scale_x = col_w / 1280.0
    scale_y = h / 720.0
    for it in state["main_items"]:
        px = int(it["x"] * scale_x)
        py = int(it["y"] * scale_y)
        cv2.circle(panel, (px, py), 6, (0, 255, 0), -1)
        cv2.putText(panel, "%s %d" % (SHAPES.get(it["shape"], "?"), it["conf"]),
                    (px + 8, py - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (200, 255, 200), 1)
    canvas[:, :col_w] = panel

    # 中：副相机画面
    frame = state.get("cam2_frame")
    if frame is not None:
        fh, fw = frame.shape[:2]
        ratio = min(col_w / fw, h / fh)
        small = cv2.resize(frame, (int(fw * ratio), int(fh * ratio)))
        y0 = (h - small.shape[0]) // 2
        x0 = col_w + (col_w - small.shape[1]) // 2
        canvas[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
        off_x = x0
        off_y = y0
    else:
        off_x = off_y = 0
        cv2.putText(canvas, "CAM2 no frame", (col_w + 10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
    cv2.putText(canvas, "CAM2 (DF200)", (col_w + 8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
    for d in (state.get("cam2") or {}).get("detections", []):
        x1, y1, x2, y2 = d["box"]
        if frame is not None:
            r = min(col_w / frame.shape[1], h / frame.shape[0])
            x1, y1, x2, y2 = (int(x1 * r + off_x), int(y1 * r + off_y),
                              int(x2 * r + off_x), int(y2 * r + off_y))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 255), 1)
        cv2.putText(canvas, "%s/%s" % (SHAPES.get(d["shape"], "?"), d["color"]),
                    (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 255, 255), 1)

    # 右：融合判决
    x_text = 2 * col_w + 8
    fusion = state["fusion"]
    color = {"CONFIRMED": (0, 255, 0), "CONTRADICTED": (0, 0, 255)}.get(
        fusion["verdict"], (0, 200, 255))
    cv2.putText(canvas, "FUSION", (x_text, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(canvas, fusion["verdict"], (x_text, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    y = 90
    for line in str(fusion.get("reason", "")).split("\n")[:3]:
        cv2.putText(canvas, line[:34], (x_text, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
        y += 22
    y += 6
    cv2.putText(canvas, "main=%s" % fusion.get("main", {}), (x_text, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 255, 180), 1)
    y += 20
    cv2.putText(canvas, "cam2=%s" % fusion.get("cam2", {}), (x_text, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 220, 255), 1)

    cv2.imshow("three-way view  (q = quit)", canvas)
    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
        raise KeyboardInterrupt


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _grab_cam2(args) -> dict | None:
    """取副相机数据：优先本地图/离线 json，其次 Pi 快照 URL。"""
    frame = None
    dets: list[dict] = []
    frame_color, frame_frac = "unknown", 0.0

    if args.cam2_json:
        data = json.loads(Path(args.cam2_json).read_text(encoding="utf-8-sig"))
        return {"detections": data.get("detections", []),
                "frame_color": data.get("frame_color", "?"),
                "frame_color_frac": data.get("frame_color_frac", 0.0),
                "model": "json"}
    if args.cam2_image:
        if not have_images():
            raise RuntimeError("缺 cv2/numpy：无法读 --cam2-image")
        frame = cv2.imread(args.cam2_image)
    elif args.cam2_url:
        frame = grab_jpeg(args.cam2_url)

    if frame is not None:
        frame_color, frame_frac = color_of(frame)
        if args.roi:
            x, y, w, h = [int(v) for v in args.roi.split(",")]
            roi = frame[max(0, y):y + h, max(0, x):x + w]
            if roi.size:
                crop_color, crop_frac = color_of(roi)
                frame_color, frame_frac = crop_color, crop_frac
        dets = args.sess.detect(frame) if args.sess is not None else []
    return {"detections": dets, "frame_color": frame_color,
            "frame_color_frac": frame_frac,
            "model": (args.sess.reason if args.sess is not None else "off"),
            "frame": frame}


def _self_test() -> int:
    """无设备、无 cv2 也能验证：报文解析 + 集合判决 + 点判决。"""
    body = bytes([2]) + (7).to_bytes(2, "big")
    body += bytes([1, 90]) + (640).to_bytes(2, "big") + (360).to_bytes(2, "big") + bytes([0xFF])
    body += bytes([3, 80]) + (200).to_bytes(2, "big") + (400).to_bytes(2, "big") + bytes([0xFF])
    task_id, items = parse_batch(body, "shape")
    assert task_id == 7 and len(items) == 2, (task_id, items)
    assert items[0]["shape"] == 1 and items[1]["shape"] == 3
    assert items[0]["x"] == 640

    code_body = bytes([1, 0, 9, 11, 88, 0, 10, 1, 44, 0xFF])
    _, code_items = parse_batch(code_body, "code")
    assert code_items[0]["shape"] == 3 and code_items[0]["color"] == 1

    cam2 = {"detections": [{"shape": 1, "conf": 0.9, "color": "red",
                            "box": (600, 320, 680, 400)},
                           {"shape": 3, "conf": 0.8, "color": "blue",
                            "box": (160, 360, 240, 440)}]}
    f = verdict_set(items, cam2)
    assert f["verdict"] == "CONFIRMED", f
    f_bad = verdict_set(items, {"detections": [cam2["detections"][0]]})
    assert f_bad["verdict"] == "CONTRADICTED", f_bad
    p = verdict_point(items, cam2, radius=90.0)
    assert p["verdict"] == "CONFIRMED", p
    print("self-test OK：报文解析(shape/code) + 集合判决 + 点判决 全部通过")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="主相机/副相机/融合 三路对比视图")
    ap.add_argument("--maixcam", default="172.20.10.9", help="MaixCAM IP")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--id-mode", choices=("shape", "code"), default="shape",
                    help="主相机 id 字节语义（shape=现状）")
    ap.add_argument("--cam2-url", default="http://172.20.10.8:8080/snap",
                    help="副相机快照 URL（Pi 上那个 HTTP 服务）")
    ap.add_argument("--cam2-image", default="", help="离线：本地副相机图")
    ap.add_argument("--cam2-json", default="", help="离线：副相机检测结果 json")
    ap.add_argument("--roi", default="", help="副相机 ROI `x,y,w,h`（判色/落料位）")
    ap.add_argument("--model", default="", help="副相机 6 类 ONNX（可空）")
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--mode", choices=("set", "point"), default="set",
                    help="融合模式：set=只比形状计数（无标定）；point=按像素近邻匹配")
    ap.add_argument("--radius", type=float, default=90.0)
    ap.add_argument("--map-scale", type=float, default=1.0)
    ap.add_argument("--map-dx", type=float, default=0.0)
    ap.add_argument("--map-dy", type=float, default=0.0)
    ap.add_argument("--headless", action="store_true", help="不开窗口，只打印终端")
    ap.add_argument("--no-image", action="store_true", help="不取副相机图像（最快）")
    ap.add_argument("--evidence", default="", help="证据目录：每轮存 json(+jpg)")
    ap.add_argument("--max-batches", type=int, default=0, help="0=一直跑")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    args.sess = Cam2Model(args.model, args.conf) if args.model else None
    if args.sess is not None and not args.sess.ok:
        print("[warn] 副相机模型不可用：%s ⇒ 只用 HSV 判色" % args.sess.reason)

    client = MainCamClient(args.maixcam, args.port, args.id_mode)
    print("连 MaixCAM %s:%d ..." % (args.maixcam, args.port))
    client.connect()
    print("已连接。Ctrl-C 退出。")
    if args.evidence:
        Path(args.evidence).mkdir(parents=True, exist_ok=True)

    round_no = 0
    try:
        while True:
            got = client.recv_one()
            if got is None:
                print("连接断开")
                break
            task_id, main_items = got
            if not main_items and args.max_batches == 0:
                continue
            round_no += 1
            cam2 = None
            if not args.no_image:
                try:
                    cam2 = _grab_cam2(args)
                except Exception as exc:
                    print("[warn] 副相机取数失败：%s" % exc)
            fusion = (verdict_point(main_items, cam2, args.radius,
                                    args.map_scale, args.map_dx, args.map_dy)
                      if args.mode == "point" else verdict_set(main_items, cam2))
            print(render_terminal(main_items, cam2, fusion, round_no))

            if args.evidence:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                rec = {"round": round_no, "task_id": task_id,
                       "main": main_items, "cam2": cam2, "fusion": fusion,
                       "time": stamp}
                (Path(args.evidence) / ("round_%s_%03d.json" % (stamp, round_no))
                 ).write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                              encoding="utf-8")
                if cam2 and cam2.get("frame") is not None and cv2 is not None:
                    cv2.imwrite(str(Path(args.evidence) /
                                    ("round_%s_%03d_cam2.jpg" % (stamp, round_no))),
                                cam2["frame"])

            if not args.headless:
                try:
                    render_window({"main_items": main_items, "cam2": cam2,
                                   "fusion": fusion})
                except KeyboardInterrupt:
                    break
            if args.max_batches and round_no >= args.max_batches:
                break
    except KeyboardInterrupt:
        print("\n手动中断")
    finally:
        client.close()
        if cv2 is not None and not args.headless:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
