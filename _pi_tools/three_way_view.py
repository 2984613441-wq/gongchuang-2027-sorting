# -*- coding: utf-8 -*-
r"""三路实时观测窗口：主相机 / 副相机 / 融合判决（2026-11-05 v2）。

**默认就是窗口模式**（`--headless` 才是纯终端）。
左栏：主相机画面 + 检测框（主相机若没开快照服务，则退化为检测点阵）
中栏：副相机画面 + 检测框/颜色
右栏：融合判决（CONFIRMED / CONTRADICTED / UNPROVEN）、计数、FPS、数据新鲜度

快捷键
------
q / ESC  退出        s  存一张证据（json+jpg）      1  集合模式
2        点匹配模式     m 切换主相机 id 语义(shape/code)

用法
----
```powershell
# 最小：连主相机 TCP 8765 + 副相机 Pi 快照（会自动尝试主相机 :8766 快照）
python _pi_tools/three_way_view.py

# 指定地址
python _pi_tools/three_way_view.py --maixcam 172.20.10.9 --cam2-url http://172.20.10.8:8080/snap

# 副相机跑 6 类 ONNX
python _pi_tools/three_way_view.py --model _deploy_maixcam\yolo11n_6c_cam2.onnx

# 没有设备时，先验证窗口本身是否正常（合成动画）
python _pi_tools/three_way_view.py --synthetic

# 纯终端
python _pi_tools/three_way_view.py --headless
```

边界：只读。不连 STM32、不写串口、不改协议、不影响场上运行。
"""

from __future__ import annotations

import argparse
import json
import socket
import time
import urllib.request
from pathlib import Path

SHAPES = {1: "cube", 2: "cuboid", 3: "cylinder", 4: "pentagonal_prism",
          5: "cone", 6: "tetrahedron"}
COLORS = {1: "red", 2: "yellow", 3: "green", 4: "blue", 5: "white"}
_TARGET_BYTES = 7

COLOR_HSV = {
    "red": [((0, 90, 60), (10, 255, 255)), ((170, 90, 60), (179, 255, 255))],
    "yellow": [((11, 80, 80), (28, 255, 255))],
    "green": [((29, 60, 60), (80, 255, 255))],
    "blue": [((81, 80, 50), (130, 255, 255))],
    "white": [((0, 0, 170), (179, 60, 255))],
}


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
# 主相机报文
# --------------------------------------------------------------------------- #
def parse_batch(body: bytes, id_mode: str = "shape") -> tuple[int, list[dict]]:
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
        rec = {"seq": i + 1, "id": id_byte, "conf": body[off + 1],
               "x": int.from_bytes(body[off + 2:off + 4], "big"),
               "y": int.from_bytes(body[off + 4:off + 6], "big")}
        if id_mode == "code":
            rec["shape"] = (id_byte - 1) // 5 + 1 if 1 <= id_byte <= 30 else 0
            rec["color"] = (id_byte - 1) % 5 + 1 if 1 <= id_byte <= 30 else 0
        else:
            rec["shape"] = id_byte if 1 <= id_byte <= 6 else 0
            rec["color"] = 0
        items.append(rec)
        off += _TARGET_BYTES
    return task_id, items


class MainCamClient:
    """TCP 8765 收 BATCH_TARGETS（非阻塞：超时返回 None，界面继续刷）。"""

    def __init__(self, host: str, port: int = 8765, id_mode: str = "shape"):
        self.host, self.port, self.id_mode = host, port, id_mode
        self.sock: socket.socket | None = None
        self.last_error = ""

    def connect(self, timeout: float = 4.0) -> bool:
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
            self.sock.settimeout(0.05)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.sock = None
            return False

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def poll(self) -> tuple[int, list[dict]] | None:
        if self.sock is None:
            return None
        try:
            hdr = self.sock.recv(3)
        except socket.timeout:
            return None
        except Exception as exc:
            self.last_error = str(exc)
            self.sock = None
            return None
        if not hdr:
            self.sock = None
            return None
        while len(hdr) < 3:
            try:
                more = self.sock.recv(3 - len(hdr))
            except socket.timeout:
                continue
            if not more:
                self.sock = None
                return None
            hdr += more
        need = hdr[0] * _TARGET_BYTES
        body = b""
        while len(body) < need:
            try:
                chunk = self.sock.recv(need - len(body))
            except socket.timeout:
                continue
            if not chunk:
                self.sock = None
                return None
            body += chunk
        return parse_batch(hdr + body, self.id_mode)


# --------------------------------------------------------------------------- #
# 取图 / 判色 / 可选 ONNX
# --------------------------------------------------------------------------- #
def grab_jpeg(url: str, timeout: float = 1.5):
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
    except Exception:
        return None
    if cv2 is None or np is None or not raw:
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def color_of(bgr) -> tuple[str, float]:
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
    def __init__(self, model_path: str | None, conf: float = 0.30, size: int = 448):
        self.ok = False
        self.reason = "未启用（只用 HSV）"
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
        except Exception as exc:
            self.reason = "加载失败：%s" % exc

    def detect(self, bgr) -> list[dict]:
        if not self.ok or cv2 is None:
            return []
        h, w = bgr.shape[:2]
        s = self.size
        blob = cv2.resize(bgr, (s, s))[:, :, ::-1].astype("float32")
        blob = blob.transpose(2, 0, 1)[None] / 255.0
        out = self.sess.run(None, {self.input_name: blob})[0]
        pred = out[0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        dets = []
        for row in pred:
            cx, cy, bw, bh = row[:4]
            cls_scores = row[4:]
            cid = int(cls_scores.argmax())
            conf = float(cls_scores[cid])
            if conf < self.conf:
                continue
            x1 = max(0, int((cx - bw / 2) * w / s))
            y1 = max(0, int((cy - bh / 2) * h / s))
            x2 = min(w - 1, int((cx + bw / 2) * w / s))
            y2 = min(h - 1, int((cy + bh / 2) * h / s))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = bgr[y1:y2, x1:x2]
            cname, _ = color_of(crop) if crop.size else ("unknown", 0.0)
            dets.append({"shape": cid + 1, "conf": round(conf, 3), "color": cname,
                         "box": (x1, y1, x2, y2)})
        # NMS（同一目标会被多类/多锚点重复检出；不加会把 1 件画成几十个框）
        if not dets:
            return []
        boxes = [[b["box"][0], b["box"][1],
                  b["box"][2] - b["box"][0], b["box"][3] - b["box"][1]] for b in dets]
        scores = [b["conf"] for b in dets]
        try:
            keep = cv2.dnn.NMSBoxes(boxes, scores, self.conf, 0.45)
            keep = list(keep) if len(keep) else []
            if keep and isinstance(keep[0], (list, tuple)):
                keep = [int(k[0]) for k in keep]
            else:
                keep = [int(k) for k in keep]
            if keep:
                dets = [dets[i] for i in keep]
        except Exception:
            pass
        return dets


# --------------------------------------------------------------------------- #
# 融合判决
# --------------------------------------------------------------------------- #
def _shape_counts(items) -> dict:
    out: dict[int, int] = {}
    for it in items:
        out[int(it["shape"])] = out.get(int(it["shape"]), 0) + 1
    return out


def verdict_set(main_items, cam2) -> dict:
    main_shapes = _shape_counts(main_items)
    cam2_shapes = _shape_counts((cam2 or {}).get("detections", []))
    if cam2 is None:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "副相机无数据",
                "main": main_shapes, "cam2": {}}
    if not main_shapes:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "主相机本帧无件",
                "main": {}, "cam2": cam2_shapes}
    if not cam2_shapes:
        return {"mode": "set", "verdict": "UNPROVEN", "reason": "副相机本帧无件",
                "main": main_shapes, "cam2": {}}
    if main_shapes == cam2_shapes:
        return {"mode": "set", "verdict": "CONFIRMED", "reason": "形状计数一致",
                "main": main_shapes, "cam2": cam2_shapes}
    diff = {k: (main_shapes.get(k, 0), cam2_shapes.get(k, 0))
            for k in set(main_shapes) | set(cam2_shapes)
            if main_shapes.get(k, 0) != cam2_shapes.get(k, 0)}
    return {"mode": "set", "verdict": "CONTRADICTED",
            "reason": "计数不一致 形状:(主,副)=%s" % diff,
            "main": main_shapes, "cam2": cam2_shapes}


def verdict_point(main_items, cam2, radius=90.0, scale=1.0, dx=0.0, dy=0.0) -> dict:
    if cam2 is None:
        return {"mode": "point", "verdict": "UNPROVEN", "reason": "副相机无数据",
                "pairs": [], "main": _shape_counts(main_items), "cam2": {}}
    dets = cam2.get("detections", [])
    pairs, unmatched = [], []
    for it in main_items:
        mx, my = it["x"] * scale + dx, it["y"] * scale + dy
        best, best_d = None, 1e9
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            dist = (((x1 + x2) / 2.0 - mx) ** 2 + ((y1 + y2) / 2.0 - my) ** 2) ** 0.5
            if dist < best_d:
                best, best_d = d, dist
        if best is not None and best_d <= radius:
            pairs.append({"seq": it["seq"], "main_shape": it["shape"],
                          "cam2_shape": best["shape"], "cam2_color": best["color"],
                          "dist_px": round(best_d, 1),
                          "same_shape": it["shape"] == best["shape"]})
        else:
            unmatched.append(it["seq"])
    if not main_items or not pairs:
        verdict = "UNPROVEN"
    elif all(p["same_shape"] for p in pairs) and not unmatched:
        verdict = "CONFIRMED"
    else:
        verdict = "CONTRADICTED"
    return {"mode": "point", "verdict": verdict, "pairs": pairs,
            "unmatched_main": unmatched,
            "reason": "未匹配：%s" % unmatched if unmatched else "",
            "main": _shape_counts(main_items),
            "cam2": _shape_counts(dets)}


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
W, H = 1500, 620
COL = W // 3


def _fit(img, cw, ch):
    canvas = np.zeros((ch, cw, 3), np.uint8)
    if img is None:
        return canvas, 0, 0, 1.0
    ih, iw = img.shape[:2]
    r = min(cw / iw, ch / ih)
    nw, nh = max(1, int(iw * r)), max(1, int(ih * r))
    small = cv2.resize(img, (nw, nh))
    x0, y0 = (cw - nw) // 2, (ch - nh) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = small
    return canvas, x0, y0, r


def render(state: dict):
    canvas = np.zeros((H, W, 3), np.uint8)

    # 左：主相机
    has_main = state.get("main_frame") is not None
    left, ox, oy, lr = _fit(state.get("main_frame"), COL, H)
    for it in state["main_items"]:
        if has_main:
            px, py = int(it["x"] * lr + ox), int(it["y"] * lr + oy)
        else:
            px, py = int(it["x"] * COL / 1280.0), int(it["y"] * H / 720.0)
        cv2.circle(left, (px, py), 7, (0, 255, 0), 2)
        cv2.putText(left, "%s %d" % (SHAPES.get(it["shape"], "?"), it["conf"]),
                    (px + 9, py - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    cv2.putText(left, "MAIN (MaixCAM) %d pcs  %.1fs" % (
        len(state["main_items"]), state["main_age"]), (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    canvas[:, 0:COL] = left

    # 中：副相机
    mid, mx0, my0, mr = _fit((state.get("cam2") or {}).get("frame"), COL, H)
    for d in (state.get("cam2") or {}).get("detections", []):
        x1, y1, x2, y2 = d["box"]
        x1, y1 = int(x1 * mr + mx0), int(y1 * mr + my0)
        x2, y2 = int(x2 * mr + mx0), int(y2 * mr + my0)
        cv2.rectangle(mid, (x1, y1), (x2, y2), (0, 255, 255), 1)
        cv2.putText(mid, "%s/%s %.2f" % (SHAPES.get(d["shape"], "?"), d["color"],
                                         d["conf"]),
                    (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (0, 255, 255), 1)
    cam2 = state.get("cam2")
    cv2.putText(mid, "CAM2 (DF200) %d pcs  %s" % (
        len((cam2 or {}).get("detections", [])),
        (cam2 or {}).get("model", "-")), (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    if cam2 and cam2.get("frame_color"):
        cv2.putText(mid, "frame color: %s %.3f" % (
            cam2["frame_color"], cam2.get("frame_color_frac", 0.0)), (8, 46),
            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 200, 255), 1)
    canvas[:, COL:2 * COL] = mid

    # 右：融合
    right = np.zeros((H, COL, 3), np.uint8)
    fusion = state["fusion"]
    v = fusion["verdict"]
    vcolor = {"CONFIRMED": (0, 255, 0), "CONTRADICTED": (0, 0, 255)}.get(
        v, (0, 200, 255))
    cv2.putText(right, "FUSION  (%s)" % fusion["mode"], (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(right, v, (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 1.0, vcolor, 2)
    y = 100
    reason = str(fusion.get("reason", ""))
    for i in range(0, min(len(reason), 90), 30):
        cv2.putText(right, reason[i:i + 30], (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
        y += 20
    y += 8
    for title, key, color in (("main shapes:", "main", (180, 255, 180)),
                              ("cam2 shapes:", "cam2", (180, 220, 255))):
        cv2.putText(right, title, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        y += 18
        for k, cnt in sorted(fusion.get(key, {}).items()):
            cv2.putText(right, "  %s x%d" % (SHAPES.get(k, "?"), cnt), (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            y += 17
        y += 6
    stat = "conn=%s main=%s cam2=%s fps=%.1f" % (
        state.get("conn", "?"), "OK" if state.get("main_ok") else "DOWN",
        "OK" if state.get("cam2_ok") else "NO", state.get("fps", 0.0))
    cv2.putText(right, stat[:60], (10, H - 34), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (200, 200, 200), 1)
    cv2.putText(right, "q=quit s=save 1=set 2=point m=idmode", (10, H - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)
    canvas[:, 2 * COL:] = right
    return canvas


def render_terminal(state: dict) -> str:
    fusion = state["fusion"]
    return "\n".join([
        "=" * 70,
        "主相机 %d 件 | 副相机 %d 件 | fps %.1f | conn=%s" % (
            len(state["main_items"]),
            len((state.get("cam2") or {}).get("detections", [])),
            state.get("fps", 0.0), state.get("conn", "?")),
        "[1] 主相机: " + ("; ".join(
            "seq%d=%s(%d)" % (it["seq"], SHAPES.get(it["shape"], "?"), it["conf"])
            for it in state["main_items"]) or "（无件）"),
        "[2] 副相机: " + ("; ".join(
            "%s/%s(%.2f)" % (SHAPES.get(d["shape"], "?"), d["color"], d["conf"])
            for d in (state.get("cam2") or {}).get("detections", []))
            or "（无数据）"),
        "[3] 融合[%s] %s：%s" % (fusion["mode"], fusion["verdict"],
                                fusion.get("reason", "")),
        "    主=%s 副=%s" % (fusion.get("main"), fusion.get("cam2")),
    ])


# --------------------------------------------------------------------------- #
# 合成模式（无设备验证窗口）
# --------------------------------------------------------------------------- #
def synthetic_state(t: float) -> dict:
    import math
    items = []
    for i in range(4):
        ang = t + i * math.pi / 2
        items.append({"seq": i + 1, "id": 1 + i, "conf": 70 + i * 5,
                      "shape": 1 + (i % 6),
                      "x": int(640 + 300 * math.cos(ang)),
                      "y": int(360 + 200 * math.sin(ang))})
    main_frame = cam2_frame = None
    dets = []
    if cv2 is not None and np is not None:
        main_frame = np.full((720, 1280, 3), 30, np.uint8)
        cv2.putText(main_frame, "SYNTHETIC MAIN", (420, 360),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 180, 0), 2)
        cam2_frame = np.full((720, 1280, 3), 45, np.uint8)
        for it in items:
            x, y = it["x"] // 2 + 320, it["y"] // 2 + 120
            cv2.circle(cam2_frame, (x, y), 30, (60, 60, 200), -1)
            dets.append({"shape": it["shape"], "conf": 0.9, "color": "red",
                         "box": (x - 30, y - 30, x + 30, y + 30)})
    return {"main_items": items, "main_age": 0.0, "main_ok": True,
            "main_frame": main_frame, "cam2_ok": True,
            "cam2": {"detections": dets, "frame": cam2_frame,
                     "frame_color": "red", "frame_color_frac": 0.2,
                     "model": "synthetic"},
            "fusion": verdict_set(items, {"detections": dets}),
            "fps": 0.0, "conn": "synthetic"}


def _self_test() -> int:
    body = bytes([2]) + (7).to_bytes(2, "big")
    body += bytes([1, 90]) + (640).to_bytes(2, "big") + (360).to_bytes(2, "big") + bytes([255])
    body += bytes([3, 80]) + (200).to_bytes(2, "big") + (400).to_bytes(2, "big") + bytes([255])
    _, items = parse_batch(body, "shape")
    assert len(items) == 2 and items[0]["shape"] == 1 and items[1]["shape"] == 3
    _, code_items = parse_batch(bytes([1, 0, 9, 11, 88, 0, 10, 1, 44, 255]), "code")
    assert code_items[0]["shape"] == 3 and code_items[0]["color"] == 1
    cam2 = {"detections": [{"shape": 1, "conf": 0.9, "color": "red",
                            "box": (600, 320, 680, 400)},
                           {"shape": 3, "conf": 0.8, "color": "blue",
                            "box": (160, 360, 240, 440)}]}
    assert verdict_set(items, cam2)["verdict"] == "CONFIRMED"
    assert verdict_set(items, {"detections": cam2["detections"][:1]})["verdict"] == "CONTRADICTED"
    assert verdict_point(items, cam2, 90.0)["verdict"] == "CONFIRMED"
    assert verdict_set(items, None)["verdict"] == "UNPROVEN"
    st = synthetic_state(0.0)
    assert len(st["main_items"]) == 4
    if have_images():
        assert render(st).shape == (H, W, 3)
    print("self-test OK：解析(shape/code) + 集合/点判决 + 合成渲染 全部通过")
    return 0


# --------------------------------------------------------------------------- #
# 主循环
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="三路实时观测窗口（主/副/融合）")
    ap.add_argument("--maixcam", default="172.20.10.9")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--id-mode", choices=("shape", "code"), default="shape")
    ap.add_argument("--main-url", default="",
                    help="主相机快照 URL（默认自动试 http://<maixcam>:8766/snap）")
    ap.add_argument("--cam2-url", default="http://172.20.10.8:8080/snap")
    ap.add_argument("--roi", default="", help="副相机 ROI x,y,w,h")
    ap.add_argument("--model", default="", help="副相机 6 类 ONNX（可空）")
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--mode", choices=("set", "point"), default="set")
    ap.add_argument("--radius", type=float, default=90.0)
    ap.add_argument("--map-scale", type=float, default=1.0)
    ap.add_argument("--map-dx", type=float, default=0.0)
    ap.add_argument("--map-dy", type=float, default=0.0)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--synthetic", action="store_true", help="合成动画（无设备验窗口）")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--target-fps", type=float, default=20.0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    if not args.headless and not have_images():
        print("[warn] 当前 Python 没有 cv2/numpy ⇒ 无法开窗口，自动切 --headless")
        print("       请用装了 opencv 的环境运行（例如 Anaconda 训练环境）")
        args.headless = True

    sess = Cam2Model(args.model, args.conf) if args.model else None
    if sess is not None and not sess.ok:
        print("[warn] 副相机模型不可用：%s ⇒ 只用 HSV 判色" % sess.reason)

    client = None
    if not args.synthetic:
        client = MainCamClient(args.maixcam, args.port, args.id_mode)
        print("连 MaixCAM %s:%d ..." % (args.maixcam, args.port))
        ok = client.connect()
        print("已连接" if ok else "连接失败：%s（继续看副相机）" % client.last_error)
        if not args.main_url:
            args.main_url = "http://%s:8766/snap" % args.maixcam

    if args.evidence:
        Path(args.evidence).mkdir(parents=True, exist_ok=True)

    state = {"main_items": [], "main_age": 9.9, "main_ok": False,
             "main_frame": None, "cam2": None, "cam2_ok": False,
             "fusion": {"mode": args.mode, "verdict": "UNPROVEN",
                        "reason": "等待数据", "main": {}, "cam2": {}},
             "fps": 0.0, "conn": "synthetic" if args.synthetic else "connecting"}
    last_main_ts = 0.0
    fps_t, fps_n, fps = time.time(), 0, 0.0
    last_term = 0.0
    t0 = time.time()
    mode, id_mode = args.mode, args.id_mode
    running = True

    try:
        while running:
            loop_start = time.time()
            if args.synthetic:
                state.update(synthetic_state(time.time() - t0))
                state["fps"] = fps
            else:
                got = client.poll() if client is not None else None
                if got is not None:
                    _, items = got
                    state["main_items"] = items
                    last_main_ts = time.time()
                    state["conn"] = "ok"
                state["main_ok"] = client is not None and client.sock is not None
                state["main_age"] = (time.time() - last_main_ts) if last_main_ts else 9.9
                state["main_frame"] = grab_jpeg(args.main_url) if args.main_url else None

                cam2 = None
                frame = grab_jpeg(args.cam2_url)
                if frame is not None:
                    fc, ff = color_of(frame)
                    if args.roi:
                        try:
                            x, y, w, h = [int(v) for v in args.roi.split(",")]
                            roi = frame[max(0, y):y + h, max(0, x):x + w]
                            if roi.size:
                                fc, ff = color_of(roi)
                        except Exception:
                            pass
                    cam2 = {"detections": sess.detect(frame) if (sess and sess.ok) else [],
                            "frame": frame, "frame_color": fc,
                            "frame_color_frac": ff,
                            "model": sess.reason if sess is not None else "HSV only"}
                    state["cam2"] = cam2
                state["cam2_ok"] = state.get("cam2") is not None
                if mode == "point":
                    state["fusion"] = verdict_point(state["main_items"], state["cam2"],
                                                    args.radius, args.map_scale,
                                                    args.map_dx, args.map_dy)
                else:
                    state["fusion"] = verdict_set(state["main_items"], state["cam2"])

            fps_n += 1
            if time.time() - fps_t >= 0.5:
                fps = fps_n / (time.time() - fps_t)
                fps_t, fps_n = time.time(), 0
                state["fps"] = fps

            if args.headless:
                now = time.time()
                if now - last_term >= 1.0:
                    print(render_terminal(state))
                    last_term = now
            else:
                cv2.imshow("three-way view  (q quit / s save / 1 set / 2 point / m id-mode)",
                           render(state))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    running = False
                elif key == ord("s") and args.evidence:
                    stamp = time.strftime("%Y%m%d-%H%M%S")
                    rec = {"main": state["main_items"],
                           "cam2": {k: v for k, v in (state["cam2"] or {}).items()
                                    if k != "frame"},
                           "fusion": state["fusion"], "time": stamp}
                    (Path(args.evidence) / ("snap_%s.json" % stamp)).write_text(
                        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
                    if state["cam2"] and state["cam2"].get("frame") is not None:
                        cv2.imwrite(str(Path(args.evidence) /
                                        ("snap_%s_cam2.jpg" % stamp)),
                                    state["cam2"]["frame"])
                    if state["main_frame"] is not None:
                        cv2.imwrite(str(Path(args.evidence) /
                                        ("snap_%s_main.jpg" % stamp)),
                                    state["main_frame"])
                    print("已保存证据到 %s" % args.evidence)
                elif key == ord("1"):
                    mode = "set"
                elif key == ord("2"):
                    mode = "point"
                elif key == ord("m"):
                    id_mode = "code" if id_mode == "shape" else "shape"
                    if client is not None:
                        client.id_mode = id_mode
                    print("主相机 id 语义切换为 %s（需发送端同步）" % id_mode)

            dt = time.time() - loop_start
            if dt < 1.0 / max(1.0, args.target_fps):
                time.sleep(1.0 / max(1.0, args.target_fps) - dt)
    except KeyboardInterrupt:
        print("\n手动中断")
    finally:
        if client is not None:
            client.close()
        if cv2 is not None and not args.headless:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
