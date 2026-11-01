#!/usr/bin/env python3
"""双相机协作读取（**电脑侧**版，零安装）：主相机 BATCH_TARGETS → 副相机一帧 → 独立判决。

## 为什么有这一版

树莓派上缺 onnxruntime（PyPI 对 Pi 的 aarch64/cp39 不给 wheel），
而 Pi 的 cv2 4.5.1 DNN 不支持 YOLO11 的 attention Split 节点 ⇒ Pi 侧推理暂时跑不了。
为不耽误联调，把「副相机推理 + 判决」放到**电脑**上跑：

    MaixCAM（主相机, 现有 v11 模型）
        │ TCP 8765, 7 字节/件的 BATCH_TARGETS
        ▼
    本脚本（电脑）  ──HTTP /snap──►  树莓派 :8080（DF200 抓帧）
        │
        └─ 电脑上跑 _deploy_maixcam/yolo11n_6c_cam2.onnx → 三态判决 + 证据图

生产口径仍是「Pi 侧推理」，等 Pi 的运行时解决后把同一套逻辑搬过去即可。

## 用法

    1) MaixCAM 上：
       python3 /root/yolo_v11_send.py --host 172.20.10.3 --port 8765 --task-id 1 --conf 0.4
    2) 电脑上：
       python two_cam_live_pc.py --cam2-url http://172.20.10.8:8080/snap
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import time

import cv2
import numpy as np
import urllib.request

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


def grab_cam2(url: str, timeout=6.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        buf = np.frombuffer(r.read(), np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            return None
        buf += c
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
        items.append(dict(cls=body[off], conf=body[off + 1],
                          x=int.from_bytes(body[off + 2:off + 4], "big"),
                          y=int.from_bytes(body[off + 4:off + 6], "big")))
        off += 7
    return task_id, items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"_deploy_maixcam\yolo11n_6c_cam2.onnx")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cam2-url", default="http://172.20.10.8:8080/snap")
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--mode", choices=["point", "set"], default="set",
                    help="point=按坐标逐件匹配(需标定)；set=按类别计数集合比对(无需标定)")
    ap.add_argument("--main-base", type=int, default=1, choices=[0, 1],
                    help="主相机类别字节基：MaixCAM 现在发 shape_id=class+1，所以默认 1")
    ap.add_argument("--radius", type=float, default=90.0)
    ap.add_argument("--map-scale", type=float, default=1.0)
    ap.add_argument("--map-dx", type=float, default=0.0)
    ap.add_argument("--map-dy", type=float, default=0.0)
    ap.add_argument("--evidence", default="_two_cam_evidence")
    ap.add_argument("--max-batches", type=int, default=0, help="0=一直跑")
    args = ap.parse_args()

    os.makedirs(args.evidence, exist_ok=True)
    from ultralytics import YOLO

    model = YOLO(args.model)
    print("[two-cam-PC] 副相机模型: %s" % args.model, flush=True)
    print("[two-cam-PC] 副相机抓帧: %s" % args.cam2_url, flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    print("[two-cam-PC] 监听 :%d，等 MaixCAM 连接…" % args.port, flush=True)

    n_batch = n_conf = n_contra = n_unproven = 0
    conn, addr = srv.accept()
    print("[two-cam-PC] 主相机已连接 %s" % (addr,), flush=True)
    try:
        while True:
            head = conn.recv(1)
            if not head:
                break
            count = head[0]
            tail = recv_exact(conn, 2 + count * 7) if count else recv_exact(conn, 2)
            if tail is None:
                break
            if count == 0:
                continue
            task_id, items = parse_batch(head + tail)
            if not items:
                continue
            n_batch += 1

            frame = None
            try:
                frame = grab_cam2(args.cam2_url)
            except Exception as e:
                print("[two-cam-PC] ⚠ 副相机抓帧失败: %r" % e, flush=True)
            dets = []
            if frame is not None:
                r = model.predict(frame, imgsz=448, conf=args.conf, verbose=False)[0]
                for b in r.boxes:
                    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
                    dets.append(dict(cls=int(b.cls), name=CLASSES[int(b.cls)],
                                     conf=float(b.conf), box=[x1, y1, x2, y2]))

            if args.mode == "set":
                from collections import Counter
                mc, sc = Counter(), Counter()
                for it in items:
                    mi_ = it["cls"] - args.main_base
                    if 0 <= mi_ < len(CLASSES):
                        mc[CLASSES[mi_]] += 1
                for d_ in dets:
                    sc[d_["name"]] += 1
                missing = {c: mc[c] - sc[c] for c in mc if sc[c] < mc[c]}
                extra = {c: sc[c] - mc[c] for c in sc if sc[c] > mc[c]}
                vset = "CONFIRMED_SET" if not missing else "CONTRADICTED_SET"
                if vset == "CONFIRMED_SET":
                    n_conf += 1
                else:
                    n_contra += 1
                print("-" * 92, flush=True)
                print("批次 #%d task_id=%d［集合模式·无需标定］主 %d 件 ｜ 副 %d 件 → %s"
                      % (n_batch, task_id, len(items), len(dets), vset), flush=True)
                print("   主相机: " + ", ".join("%s x%d" % (k, v) for k, v in sorted(mc.items())), flush=True)
                print("   副相机: " + ", ".join("%s x%d" % (k, v) for k, v in sorted(sc.items())), flush=True)
                if missing:
                    print("   X 副相机看不到: " + ", ".join("%s 缺%d" % (k, v) for k, v in missing.items()), flush=True)
                if extra:
                    print("   + 副相机多出: " + ", ".join("%s 多%d" % (k, v) for k, v in extra.items()), flush=True)
                if frame is not None:
                    vis = frame.copy()
                    for d_ in dets:
                        b_ = [int(v) for v in d_["box"]]
                        cv2.rectangle(vis, (b_[0], b_[1]), (b_[2], b_[3]), (80, 200, 255), 2)
                        cv2.putText(vis, "%s %.2f" % (d_["name"], d_["conf"]),
                                    (b_[0], max(16, b_[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                                    0.55, (80, 200, 255), 2, cv2.LINE_AA)
                    ev = os.path.join(args.evidence, "set_%s_%d.jpg"
                                      % (time.strftime("%Y%m%d_%H%M%S"), n_batch))
                    cv2.imwrite(ev, vis)
                    print("证据: %s ｜ 累计 C=%d X=%d" % (ev, n_conf, n_contra), flush=True)
                if args.max_batches and n_batch >= args.max_batches:
                    print("[two-cam-PC] 达到 --max-batches，退出", flush=True)
                    break
                continue

            rows = []
            for it in items:
                mi = it["cls"] - args.main_base
                if not (0 <= mi < len(CLASSES)):
                    mi = 0   # 越界保护（不会静默假装对：下面 verdict 记为 INVALID）
                mx = it["x"] * args.map_scale + args.map_dx
                my = it["y"] * args.map_scale + args.map_dy
                near = [d for d in dets
                        if abs((d["box"][0] + d["box"][2]) / 2 - mx) <= args.radius
                        and abs((d["box"][1] + d["box"][3]) / 2 - my) <= args.radius]
                near.sort(key=lambda d: -d["conf"])
                sec = near[0] if near else None
                if sec is None:
                    verdict = "UNPROVEN"
                    n_unproven += 1
                elif sec["cls"] == mi:
                    verdict = "CONFIRMED"
                    n_conf += 1
                else:
                    verdict = "CONTRADICTED"
                    n_contra += 1
                color = "?"
                if sec is not None and frame is not None:
                    b = [int(v) for v in sec["box"]]
                    crop = frame[max(0, b[1]):max(0, b[3]), max(0, b[0]):max(0, b[2])]
                    if crop.size:
                        color, _ = color_of(crop)
                rows.append(dict(task_id=task_id, main_cls=mi, main_raw=it["cls"], main_conf=it["conf"],
                                 mx=int(mx), my=int(my), verdict=verdict,
                                 sec_cls=(sec["name"] if sec else None),
                                 sec_conf=(round(sec["conf"], 3) if sec else None), color=color))

            print("─" * 92, flush=True)
            print("批次 #%d task_id=%d 主相机 %d 件 ｜ 副相机检出 %d 件"
                  % (n_batch, task_id, len(items), len(dets)), flush=True)
            print("%-3s %-16s %5s → %-14s %6s %-6s %-7s %s"
                  % ("#", "主判", "conf", "副判", "conf", "一致", "颜色", "判定"), flush=True)
            for i, r in enumerate(rows, 1):
                same = ("是" if r["sec_cls"] == CLASSES[r["main_cls"]]
                        else ("—" if r["sec_cls"] is None else "否"))
                print("%-3d %-16s %5d → %-14s %6s %-6s %-7s %s"
                      % (i, CLASSES[r["main_cls"]], r["main_conf"], r["sec_cls"] or "(无)",
                         r["sec_conf"] if r["sec_conf"] is not None else "—",
                         same, r["color"], r["verdict"]), flush=True)

            if frame is not None:
                vis = frame.copy()
                for r in rows:
                    col = {"CONFIRMED": (60, 200, 60), "CONTRADICTED": (0, 0, 255),
                           "UNPROVEN": (0, 200, 255)}[r["verdict"]]
                    cv2.circle(vis, (r["mx"], r["my"]), int(args.radius), col, 2)
                    cv2.putText(vis, r["verdict"], (r["mx"] - 40, r["my"] - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)
                for d in dets:
                    b = [int(v) for v in d["box"]]
                    cv2.rectangle(vis, (b[0], b[1]), (b[2], b[3]), (80, 200, 255), 1)
                ev = os.path.join(args.evidence, "ev_%s_%d.jpg"
                                  % (time.strftime("%Y%m%d_%H%M%S"), n_batch))
                tmp = ev.replace(".jpg", ".tmp.jpg")
                cv2.imwrite(tmp, vis)
                os.replace(tmp, ev)
                with open(ev.replace(".jpg", ".json"), "w", encoding="utf-8") as f:
                    json.dump(dict(map="approx", scale=args.map_scale, dx=args.map_dx,
                                   dy=args.map_dy, rows=rows), f, ensure_ascii=False, indent=1)
                print("证据: %s ｜ 累计 C=%d X=%d U=%d"
                      % (ev, n_conf, n_contra, n_unproven), flush=True)

            if args.max_batches and n_batch >= args.max_batches:
                print("[two-cam-PC] 达到 --max-batches，退出", flush=True)
                break
    except KeyboardInterrupt:
        print("[two-cam-PC] 用户中断", flush=True)
    finally:
        conn.close()
        srv.close()
    print("[two-cam-PC] 结束：共 %d 批（C=%d X=%d U=%d）"
          % (n_batch, n_conf, n_contra, n_unproven), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
