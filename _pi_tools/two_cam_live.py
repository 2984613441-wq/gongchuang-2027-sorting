#!/usr/bin/env python3
"""双相机协作读取（树莓派侧）：收主相机 BATCH_TARGETS → 抓副相机一帧 → 独立推理 → 三态判定。

## 数据流

    MaixCAM（主相机） --TCP 8765--> 本脚本
        BATCH_TARGETS = count(1) + task_id(2,BE) + N×[cls(1) conf(1) X(2,BE) Y(2,BE) 0xFF]

    本脚本对每一批：
      1) 从 DF200 抓 1 帧（1280×720）
      2) 用副相机自己的 ONNX 模型整帧推理，得到副相机侧的件（类 + 置信 + 像素框）
      3) 把主相机坐标 (X,Y) 映射到副相机坐标（**暂用镜像近似**，真值要等 4 点单应按 §13.4）
      4) 就近匹配 → 判定：
           CONFIRMED    副相机在预测点附近确有件，且**同类**
           CONTRADICTED 附近有件但**不同类**
           UNPROVEN     附近没检出（被挡/越界/太远）
      5) 打印表格 + 存证据图

## 用法（Pi 上）

    python3 -u /home/pi/two_cam_live.py --model /home/pi/yolo11n_6c_cam2.onnx --port 8765

    可选：--map-scale 1.0 --map-dx 0 --map-dy 0   # 粗映射（镜像时通常 scale≈1, dx≈0 或负）
          --radius 90                             # 匹配半径（副相机像素）
          --conf 0.30 --evidence /home/pi/two_cam_evidence

## 注意

* 未做 4 点单应前，坐标映射只是**近似**；判定会带 `map=approx` 标记
* 副相机模型是「6 类形状」，颜色由框内 HSV 判（不参与 CONFIRMED/CONTRADICTED，只作报告）
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import time

import cv2
import numpy as np

CLASSES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
COLOR_HSV = {
    "red": ((0, 90, 60), (10, 255, 255)),
    "yellow": ((20, 90, 80), (35, 255, 255)),
    "green": ((36, 70, 50), (90, 255, 255)),
    "blue": ((95, 70, 50), (135, 255, 255)),
    "white": ((0, 0, 170), (179, 45, 255)),
}


def color_of(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    best, best_frac = "unknown", 0.0
    for name, (lo, hi) in COLOR_HSV.items():
        m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        frac = float(m.mean() / 255.0)
        if frac > best_frac:
            best, best_frac = name, frac
    return best, round(best_frac, 3)


class Yolo11:
    """极简 YOLO11 ONNXRuntime 推理（6 类，输入 448×448 letterbox）。"""

    def __init__(self, path: str, conf: float = 0.30, imgsz: int = 448, nms_iou: float = 0.45):
        import onnxruntime as ort

        self.sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.iname = self.sess.get_inputs()[0].name
        self.conf, self.imgsz, self.iou = conf, imgsz, nms_iou
        self.names = CLASSES

    def _letterbox(self, img):
        h, w = img.shape[:2]
        s = min(self.imgmsz / w, self.imgmsz / h)
        nw, nh = int(round(w * s)), int(round(h * s))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self.imgmsz, self.imgmsz, 3), 114, np.uint8)
        dx, dy = (self.imgmsz - nw) // 2, (self.imgmsz - nh) // 2
        canvas[dy:dy + nh, dx:dx + nw] = resized
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        return blob, s, dx, dy

    def __call__(self, img):
        blob, s, dx, dy = self._letterbox(img)
        out = self.sess.run(None, {self.iname: blob})[0]
        pred = out[0]
        if pred.shape[0] != 4 + len(self.names):
            pred = pred.T
        boxes_xywh = pred[:4].T
        scores = pred[4:].T
        cls = scores.argmax(1)
        conf = scores.max(1)
        keep = conf >= self.conf
        if not keep.any():
            return []
        boxes_xywh, cls, conf = boxes_xywh[keep], cls[keep], conf[keep]
        x1 = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
        y1 = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
        xyxy = np.stack([x1, y1, x1 + boxes_xywh[:, 2], y1 + boxes_xywh[:, 3]], 1)
        idx = cv2.dnn.NMSBoxes(xyxy.tolist(), conf.tolist(), self.conf, self.iou)
        res = []
        if len(idx):
            for i in np.array(idx).reshape(-1):
                bx = (xyxy[i] - np.array([dx, dy, dx, dy])) / s
                res.append(dict(cls=int(cls[i]), name=self.names[int(cls[i])],
                                conf=float(conf[i]),
                                box=[float(v) for v in bx]))
        return res


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def parse_batch(body: bytes):
    if len(body) < 3:
        return None, []
    count = body[0]
    task_id = int.from_bytes(body[1:3], "big")
    items, off = [], 3
    for _ in range(count):
        if off + 7 > len(body):
            break
        cls = body[off]
        conf = body[off + 1]
        x = int.from_bytes(body[off + 2:off + 4], "big")
        y = int.from_bytes(body[off + 4:off + 6], "big")
        items.append(dict(cls=cls, conf=conf, x=x, y=y))
        off += 7
    return task_id, items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/home/pi/yolo11n_6c_cam2.onnx")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--radius", type=float, default=90.0, help="主相机点 → 副相机匹配半径(px)")
    ap.add_argument("--map-scale", type=float, default=1.0)
    ap.add_argument("--map-dx", type=float, default=0.0)
    ap.add_argument("--map-dy", type=float, default=0.0)
    ap.add_argument("--evidence", default="/home/pi/two_cam_evidence")
    args = ap.parse_args()

    os.makedirs(args.evidence, exist_ok=True)
    model = Yolo11(args.model, conf=args.conf)
    print("[two-cam] 模型加载完成: %s" % args.model, flush=True)

    cap = cv2.VideoCapture(args.cam, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.h)
    if not cap.isOpened():
        print("[two-cam] ❌ 打不开副相机", flush=True)
        return 1
    for _ in range(6):
        cap.read()
    print("[two-cam] 副相机就绪 %dx%d；等待主相机 BATCH_TARGETS（:%d）"
          % (args.w, args.h, args.port), flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print("[two-cam] 已监听 :%d，等 MaixCAM 连接…" % args.port, flush=True)

    n_batch = n_conf = n_contra = n_unproven = 0
    try:
        while True:
            conn, addr = srv.accept()
            print("[two-cam] 主相机已连接 %s" % (addr,), flush=True)
            conn.settimeout(10.0)
            try:
                while True:
                    head = conn.recv(1)
                    if not head:
                        break
                    count = head[0]
                    nbytes = 2 + count * 7
                    if count == 0:
                        conn.recv(nbytes) if nbytes else None
                        continue
                    body_tail = recv_exact(conn, nbytes)
                    if body_tail is None:
                        break
                    task_id, items = parse_batch(head + body_tail)
                    if not items:
                        continue
                    n_batch += 1
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        print("[two-cam] ⚠ 抓帧失败，跳过本批", flush=True)
                        continue
                    dets = model(frame)

                    rows, verdicts = [], []
                    for it in items:
                        mx = it["x"] * args.map_scale + args.map_dx
                        my = it["y"] * args.map_scale + args.map_dy
                        near = [d for d in dets
                                if abs((d["box"][0] + d["box"][2]) / 2 - mx) <= args.radius
                                and abs((d["box"][1] + d["box"][3]) / 2 - my) <= args.radius]
                        near.sort(key=lambda d: -d["conf"])
                        if not near:
                            verdict, sec = "UNPROVEN", None
                            n_unproven += 1
                        else:
                            sec = near[0]
                            verdict = "CONFIRMED" if sec["cls"] == it["cls"] else "CONTRADICTED"
                            if verdict == "CONFIRMED":
                                n_conf += 1
                            else:
                                n_contra += 1
                        color = "?"
                        if sec:
                            b = [int(v) for v in sec["box"]]
                            crop = frame[max(0, b[1]):max(0, b[3]), max(0, b[0]):max(0, b[2])]
                            if crop.size:
                                color, _ = color_of(crop)
                        rows.append(dict(task_id=task_id, main_cls=it["cls"], main_conf=it["conf"],
                                         mx=int(mx), my=int(my), verdict=verdict,
                                         sec_cls=(sec["name"] if sec else None),
                                         sec_conf=(round(sec["conf"], 3) if sec else None),
                                         color=color))

                    print("─" * 96, flush=True)
                    print("批次 #%d  task_id=%d  主相机 %d 件 ｜ 副相机检出 %d 件"
                          % (n_batch, task_id, len(items), len(dets)), flush=True)
                    print("%-3s %-16s %5s → %-14s %6s %-8s %-6s %s"
                          % ("#", "主判类别", "conf", "副判类别", "conf", "一致?", "颜色", "判定"),
                          flush=True)
                    for i, r in enumerate(rows, 1):
                        same = ("是" if r["sec_cls"] == CLASSES[r["main_cls"]] else
                                ("—" if r["sec_cls"] is None else "否"))
                        print("%-3d %-16s %5d → %-14s %6s %-8s %-6s %s"
                              % (i, CLASSES[r["main_cls"]], r["main_conf"],
                                 r["sec_cls"] or "(无)", r["sec_conf"] if r["sec_conf"] is not None else "—",
                                 same, r["color"], r["verdict"]), flush=True)

                    # 证据图
                    vis = frame.copy()
                    for r in rows:
                        col = {"CONFIRMED": (60, 200, 60), "CONTRADICTED": (0, 0, 255),
                               "UNPROVEN": (0, 200, 255)}[r["verdict"]]
                        cv2.circle(vis, (r["mx"], r["my"]), int(args.radius), col, 2)
                        cv2.putText(vis, "%s" % r["verdict"], (r["mx"] - 40, r["my"] - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)
                    for d in dets:
                        b = [int(v) for v in d["box"]]
                        cv2.rectangle(vis, (b[0], b[1]), (b[2], b[3]), (80, 200, 255), 1)
                    ev = os.path.join(args.evidence, "ev_%s_%d.jpg"
                                      % (time.strftime("%Y%m%d_%H%M%S"), n_batch))
                    cv2.imwrite(ev, vis)
                    with open(ev.replace(".jpg", ".json"), "w", encoding="utf-8") as f:
                        json.dump(dict(map="approx", scale=args.map_scale, dx=args.map_dx,
                                       dy=args.map_dy, rows=rows), f, ensure_ascii=False, indent=1)
                    print("证据: %s ｜ 累计 CONFIRMED=%d CONTRADICTED=%d UNPROVEN=%d"
                          % (ev, n_conf, n_contra, n_unproven), flush=True)
            except socket.timeout:
                print("[two-cam] 连接超时，等待重连", flush=True)
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("[two-cam] 用户中断", flush=True)
    finally:
        srv.close()
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
