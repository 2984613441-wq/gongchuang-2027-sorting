#!/usr/bin/env python3
"""主相机 + 副相机「协作/复核」融合逻辑 + 可复现模拟（生产链口径）。

## 生产链里的角色（已与用户确认）

    主相机（MaixCAM，俯视）  → 形状 v11 + 颜色 → code(1..30)，附 conf 与像素框
    副相机（DF200，左右镜像）→ 对**同一件**做独立确证（不看主相机的结论，只看那块区域）

    结果三态：CONFIRMED / CONTRADICTED / UNPROVEN   （不用阈值，逐件出证据）

## 为什么先做「模拟」

副相机现在**能采集**（Pi 上 720p@30s 实测 30.5 fps），但：
  · 还没装到镜像位、没对焦          → 真实画面无法用于验证
  · 没有 4 点单应（托盘未定稿）      → 真实"像素映射"还不存在
所以先用**已知映射的合成副相机画面**跑通融合逻辑，并注入 2 种故障，
这样"逻辑对不对"可以先证明，等装上以后只需替换成真实 H。

## 映射

主相机像素 (u,v) → 副相机像素 (u',v')，用**单应 H**（3x3，行优先 9 个数）。
左右镜像时 H 的形态与"镜像+缩放+平移"一致；真实 H 由 4 个托盘栅格点标出（§13.4）。

## 用法

    # 1) 模拟（默认 3 个场景：正常 / 一件被挡 / 一件颜色不符）
    python two_cam_fusion.py --simulate --frame _device_check/grab1.jpg

    # 2) 真实两张图 + 手填 H（等标定完成后用这个）
    python two_cam_fusion.py --main a.jpg --secondary b.jpg \
        --homography "-0.5,0,960, 0,0.5,0, 0,0,1"

判据（阶段 1，不依赖副相机模型）：
    · 存在性：映射区域内"非托盘底色"像素占比 ≥ 6%       → 否则 CONTRADICTED
    · 颜色一致：区域内主色类别 == 主相机判的颜色类别      → 否则 CONTRADICTED
    · 映射越界 / 副相机没图                              → UNPROVEN
阶段 2（副相机模型训好后）把"颜色一致"升级为"类别+颜色都一致"。
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

# 与生产链同口径的 5 色窗口（H 0..179）；白色单独处理
COLOR_RANGES = {
    "red": [((0, 95, 35), (2, 255, 255)), ((173, 95, 35), (179, 255, 255))],
    "yellow": [((24, 95, 45), (35, 255, 255))],
    "green": [((36, 95, 35), (84, 255, 255))],
    "blue": [((105, 95, 30), (137, 255, 255))],
    "white": [((0, 0, 175), (179, 55, 255))],
}
CONFIRMED, CONTRADICTED, UNPROVEN = "CONFIRMED", "CONTRADICTED", "UNPROVEN"

PRESENCE_MIN = 0.06      # 区域内"有东西"的最低非底色占比
COLOR_MIN_FRAC = 0.20    # 判某色所需的最低占比


# ────────────────────────── 基础工具 ──────────────────────────
def hsv_of(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2HSV)


def color_class(crop_hsv, area_mask=None, include_white=False):
    """返回 (颜色名, 占比)；判不出返回 (None, 最大占比)。

    area_mask: 只在这些像素上统计（用于排除相邻件的映射区域）。
    ⚠️ 注意别把参数名写成 mask —— 循环里会复用同名变量，实测踩过一次。
    """
    total = (int(cv2.countNonZero(area_mask)) if area_mask is not None
             else crop_hsv.shape[0] * crop_hsv.shape[1])
    if total == 0:
        return None, 0.0
    best, best_frac = None, 0.0
    for name, ranges in COLOR_RANGES.items():
        if name == "white" and not include_white:
            # 托盘本身是白的 ⇒ 副相机看到"整片白"其实等于"没件"。
            # 本阶段不判白件（会与"无件"混淆），白件留到阶段 2 由副相机模型判。
            continue
        m_all = None
        for lo, hi in ranges:
            m = cv2.inRange(crop_hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            m_all = m if m_all is None else cv2.bitwise_or(m_all, m)
        if area_mask is not None:
            m_all = cv2.bitwise_and(m_all, area_mask)
        frac = float(cv2.countNonZero(m_all)) / total
        if frac > best_frac:
            best, best_frac = name, frac
    if best_frac < COLOR_MIN_FRAC:
        return None, best_frac
    return best, best_frac


def object_fraction(crop_hsv, area_mask=None):
    """非托盘底色占比：托盘白（S 低 V 高）与深色背景都不算"件"。"""
    s, v = crop_hsv[:, :, 1], crop_hsv[:, :, 2]
    obj = ((s > 70) | ((v < 70) & (s > 40))).astype(np.uint8)
    if area_mask is not None:
        obj = cv2.bitwise_and(obj, area_mask)
        denom = max(1, int(cv2.countNonZero(area_mask)))
    else:
        denom = max(1, int(obj.size))
    return float(np.count_nonzero(obj)) / denom


def project(H, u, v):
    p = H @ np.array([u, v, 1.0])
    if abs(p[2]) < 1e-9:
        return None
    return p[0] / p[2], p[1] / p[2]


def project_box(H, box, canvas_w, canvas_h, margin=6):
    """把主相机 bbox 投到副相机；越界返回 None。"""
    x1, y1, x2, y2 = box
    pts = [project(H, x, y) for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2))]
    if any(p is None for p in pts):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bx1, bx2 = max(0, int(min(xs)) - margin), min(canvas_w, int(max(xs)) + margin)
    by1, by2 = max(0, int(min(ys)) - margin), min(canvas_h, int(max(ys)) + margin)
    if bx2 <= bx1 or by2 <= by1:
        return None
    return bx1, by1, bx2, by2


# ────────────────────────── 融合核心 ──────────────────────────
def verify_one(det, sec_bgr, H, others=()):
    """对一件做独立确证。det = dict(cls/conf/box/color)。"""
    h, w = sec_bgr.shape[:2]
    region = project_box(H, det["box"], w, h)
    out = {"id": det.get("id", "?"), "cls": det["cls"], "conf": det["conf"],
           "main_color": det.get("color"), "verdict": UNPROVEN,
           "why": "", "region": region, "sec_color": None,
           "sec_color_frac": 0.0, "presence": 0.0}
    if region is None:
        out["why"] = "映射越界（主相机框落到副相机画面外）"
        return out
    x1, y1, x2, y2 = region
    crop = sec_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        out["why"] = "映射区域为空"
        return out
    ch = hsv_of(crop)
    # 相邻件的映射区域要排除：否则一件被挡/被涂色会污染邻居的判定（实测踩到过）
    keep = np.full(crop.shape[:2], 255, np.uint8)
    for o in others:
        if o is det:
            continue
        orr = project_box(H, o["box"], w, h, margin=4)
        if not orr:
            continue
        oa, ob, oc, od = orr
        ix1, iy1 = max(x1, oa), max(y1, ob)
        ix2, iy2 = min(x2, oc), min(y2, od)
        if ix2 > ix1 and iy2 > iy1:
            keep[iy1 - y1:iy2 - y1, ix1 - x1:ix2 - x1] = 0
    mask = keep if int(cv2.countNonZero(keep)) > 0 else None
    presence = object_fraction(ch, mask)
    sec_color, sec_frac = color_class(ch, mask)
    out["presence"] = presence
    out["sec_color"] = sec_color
    out["sec_color_frac"] = sec_frac

    if presence < PRESENCE_MIN:
        out["verdict"] = CONTRADICTED
        out["why"] = "该区域没有件（非底色占比 %.1f%% < %.0f%%）" % (presence * 100, PRESENCE_MIN * 100)
        return out
    if det.get("color") and sec_color and det["color"] != sec_color:
        out["verdict"] = CONTRADICTED
        out["why"] = "颜色不一致：主=%s / 副=%s" % (det["color"], sec_color)
        return out
    out["verdict"] = CONFIRMED
    out["why"] = "存在性 ✅ 颜色 %s ✅（副相机置信 %.1f%%）" % (sec_color or "未分类", sec_frac * 100)
    return out


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1e-9, area_a + area_b - inter)


def dedup_primary(dets, thr=0.6):
    """同一件被两个框同时命中时只留 conf 最高的（其余记为 merged）。

    实测：grab1 里同一块红件同时被 tetrahedron(0.83)/pentagonal_prism(0.71) 命中。
    不去重 ⇒ 副相机"验同一块地方两次"，且彼此遮挡统计（第一轮就踩到 T2 被误判）。
    生产链里同类去重由主链负责；这里保证复核环节不放大重复框的影响。
    """
    order = sorted(range(len(dets)), key=lambda i: -dets[i]["conf"])
    primaries, merged = [], {}
    for i in order:
        hit = None
        for j in primaries:
            if _iou(dets[i]["box"], dets[j]["box"]) >= thr:
                hit = j
                break
        if hit is None:
            primaries.append(i)
        else:
            merged[i] = hit
    return [dets[i] for i in primaries], len(merged)


def fuse(dets, sec_bgr, H):
    prim, n_merged = dedup_primary(dets)
    results = [verify_one(d, sec_bgr, H, others=prim) for d in prim]
    summary = {
        CONFIRMED: sum(1 for r in results if r["verdict"] == CONFIRMED),
        CONTRADICTED: sum(1 for r in results if r["verdict"] == CONTRADICTED),
        UNPROVEN: sum(1 for r in results if r["verdict"] == UNPROVEN),
    }
    summary["merged"] = n_merged
    return results, summary


# ── 三态 → 自动动作（比赛**不允许人工介入**，必须有确定的自动策略）──────────────
MAX_RETRY = 2      # 自动重试上限；用尽后按确定策略处置，**绝不等人**


def decide(verdict, attempts=0):
    """返回 (action, reason)。action ∈ {PICK, RETRY, ISOLATE, PICK_SINGLE}。

    CONFIRMED     → PICK        双证一致，直接派件
    CONTRADICTED  → RETRY       先自动重试（重抓副相机帧 / 等稳定帧 / 移开夹爪让视线干净）
                     ISOLATE    重试用尽仍冲突 ⇒ 自动放进**待定区**，不混入任何已分组
    UNPROVEN      → RETRY       副相机看不到（遮挡/越界）先重试
                     PICK_SINGLE 重试用尽 ⇒ 以**主相机为权威**派件，但记 evidence=1/2

    为什么不用"交人工"：比赛期间不允许人工判断（用户 2026-10-30 明确）。
    """
    if verdict == CONFIRMED:
        return "PICK", "双证一致（存在性+颜色）"
    if attempts < MAX_RETRY:
        return "RETRY", "第 %d/%d 次自动重试（换帧/等稳定/清视线）" % (attempts + 1, MAX_RETRY)
    if verdict == CONTRADICTED:
        return "ISOLATE", ("重试 %d 次仍冲突 ⇒ 自动隔离到待定区"
                           "（不污染任何已分组，继续比其余件）" % MAX_RETRY)
    return "PICK_SINGLE", ("重试 %d 次仍无副证 ⇒ 以主相机为权威派件，"
                           "记 evidence=1/2 供复盘" % MAX_RETRY)


def draw_evidence(main_bgr, sec_bgr, results, tag, out_dir):
    """存一张左右并排证据图：主相机框 + 副相机映射框与判定。"""
    h1, w1 = main_bgr.shape[:2]
    h2, w2 = sec_bgr.shape[:2]
    canvas = np.zeros((max(h1, h2), w1 + w2, 3), np.uint8)
    canvas[:h1, :w1] = main_bgr
    canvas[:h2, w1:w1 + w2] = sec_bgr
    for r in results:
        col = {"CONFIRMED": (60, 200, 60), "CONTRADICTED": (40, 40, 230),
               "UNPROVEN": (0, 180, 230)}[r["verdict"]]
        x1, y1, x2, y2 = [int(round(v)) for v in r["box_main"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), col, 2)
        cv2.putText(canvas, "%s %s" % (r["cls"], r["id"]), (x1 + 3, max(14, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
        if r["region"]:
            a, b, c, d = r["region"]
            cv2.rectangle(canvas, (w1 + a, b), (w1 + c, d), col, 2)
            cv2.putText(canvas, r["verdict"][:4], (w1 + a + 3, max(14, b - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "evidence_%s.jpg" % tag)
    cv2.imwrite(p, canvas)
    return p


# ────────────────────────── 模拟 ──────────────────────────
def make_fake_secondary(main_bgr, scale=0.62, dx=90, dy=-30, blur=3, noise=6):
    """把主相机画面变成"左右镜像的副相机视"：水平翻转→缩放→平移→模糊→噪声。

    返回 (fake_bgr, H)，H 满足 (u,v)_main → 上式复合后的像素。
    """
    h, w = main_bgr.shape[:2]
    flip = cv2.flip(main_bgr, 1)                       # 左右镜像
    nw, nh = int(w * scale), int(h * scale)
    small = cv2.resize(flip, (nw, nh), interpolation=cv2.INTER_AREA)
    Hh, Ww = h, w
    canvas = np.full((Hh, Ww, 3), 235, np.uint8)       # 背景填浅灰，便于看出越界
    x0 = (Ww - nw) // 2 + dx
    y0 = (Hh - nh) // 2 + dy
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(Ww, x0 + nw), min(Hh, y0 + nh)
    canvas[ys:ye, xs:xe] = small[ys - y0:ye - y0, xs - x0:xe - x0]
    if blur:
        canvas = cv2.GaussianBlur(canvas, (blur * 2 + 1, blur * 2 + 1), 0)
    if noise:
        canvas = np.clip(canvas.astype(np.int16) + np.random.randint(-noise, noise + 1, canvas.shape),
                         0, 255).astype(np.uint8)
    # H = [镜像] → [缩放] → [平移]
    # u' = scale*(W-1-u) + x0 ; v' = scale*v + y0
    H = np.array([
        [-scale, 0.0, scale * (w - 1) + x0],
        [0.0, scale, y0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    return canvas, H


def detect_main(frame_bgr, model, conf=0.25):
    r = model.predict(frame_bgr, imgsz=448, conf=conf, verbose=False)[0]
    dets = []
    for i, b in enumerate(r.boxes):
        dets.append({
            "id": "T%d" % (i + 1),
            "cls": model.names[int(b.cls)],
            "conf": float(b.conf),
            "box": [float(v) for v in b.xyxy[0]],
        })
    # 主相机侧颜色（生产链里由 HSV 给出；这里顺手用同一套窗口）
    for d in dets:
        x1, y1, x2, y2 = [int(v) for v in d["box"]]
        crop = hsv_of(frame_bgr[max(0, y1):y2, max(0, x1):x2])
        d["color"], _ = color_class(crop) if crop.size else (None, 0.0)
    return dets


def run_simulation(main_bgr, model, out_dir):
    dets = detect_main(main_bgr, model)
    if not dets:
        print("⚠️ 主相机没检出件，模拟无意义（先确认图里有件）")
        return 0
    sec, H = make_fake_secondary(main_bgr)
    print("— 模拟副相机：镜像 + 缩放到 %.2f + 平移 (%d,%d) + 模糊" % (0.62, 90, -30))
    print("  已知 H = [%s]" % ", ".join("%.2f" % v for v in H.reshape(-1)[:9]))

    scenarios = []
    # ① 正常
    scenarios.append(("normal", sec, {}))
    # ② 把第一件在副相机里"抹掉"（模拟遮挡/漏检）
    sec_occ = sec.copy()
    r0 = project_box(H, dets[0]["box"], sec.shape[1], sec.shape[0])
    if r0:
        a, b, c, d = r0
        sec_occ[b:d, a:c] = 235
    scenarios.append(("occluded_one", sec_occ, {}))
    # ③ 把第一件"改色"（模拟两机看到不同东西/贴纸遮挡）
    sec_col = sec.copy()
    if r0:
        a, b, c, d = r0
        sec_col[b:d, a:c] = (60, 200, 60)   # 涂成绿色（BGR）
    scenarios.append(("wrong_color", sec_col, {}))

    for tag, s, _ in scenarios:
        results, summary = fuse(dets, s, H)
        print()
        print("══ 场景：%s ══" % {"normal": "正常（两机一致）",
                              "occluded_one": "一件在副相机里被挡住",
                              "wrong_color": "一件颜色与主判不符"}[tag])
        print("  %-4s %-18s %-6s %-14s %-8s %-12s %s"
              % ("id", "主判类别", "conf", "副相判定", "存在性", "立即动作", "重试用尽后"))
        for r, d in zip(results, dets):
            r["box_main"] = d["box"]
            first, _why1 = decide(r["verdict"], attempts=0)
            final, why2 = decide(r["verdict"], attempts=MAX_RETRY)
            r["action"] = final
            print("  %-4s %-18s %.2f   %-14s %5.1f%%  %-12s %s"
                  % (r["id"], r["cls"], r["conf"], r["verdict"],
                     r["presence"] * 100, first, final))
            print("       └ %s" % why2)
        print("  汇总：CONFIRMED=%d  CONTRADICTED=%d  UNPROVEN=%d  （合并重复框 %d）"
              % (summary[CONFIRMED], summary[CONTRADICTED], summary[UNPROVEN],
                 summary.get("merged", 0)))
        acts = {}
        for r in results:
            acts[r["action"]] = acts.get(r["action"], 0) + 1
        print("  最终动作：%s   ← 全程无人介入" %
              "  ".join("%s×%d" % (k, v) for k, v in sorted(acts.items())))
        p = draw_evidence(main_bgr, s, results, tag, out_dir)
        print("  证据图：%s" % p)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true", help="用主相机画面合成镜像副相机（推荐先跑这个）")
    ap.add_argument("--frame", default="_device_check/grab1.jpg", help="模拟用主相机帧")
    ap.add_argument("--model", default="_runs/yolo11n_6c_v11/weights/best.pt")
    ap.add_argument("--main", help="真实主相机图")
    ap.add_argument("--secondary", help="真实副相机图")
    ap.add_argument("--homography", help="真实 H，9 个数，行优先")
    ap.add_argument("--out", default="_device_check/two_cam")
    args = ap.parse_args(argv)

    if args.simulate:
        from ultralytics import YOLO
        frame = cv2.imread(args.frame)
        if frame is None:
            print("读不到 %s" % args.frame)
            return 2
        # 中文/emoji 输出在 Windows 控制台可能炸，统一 utf-8
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        return run_simulation(frame, YOLO(args.model), args.out)

    if not (args.main and args.secondary and args.homography):
        ap.print_help()
        return 2
    main_bgr = cv2.imread(args.main)
    sec_bgr = cv2.imread(args.secondary)
    if main_bgr is None or sec_bgr is None:
        print("读不到输入图")
        return 2
    H = np.array([float(v) for v in args.homography.replace("，", ",").split(",")]).reshape(3, 3)
    from ultralytics import YOLO
    dets = detect_main(main_bgr, YOLO(args.model))
    results, summary = fuse(dets, sec_bgr, H)
    for r, d in zip(results, dets):
        r["box_main"] = d["box"]
        print("%-4s %-18s %.2f  %-14s %s" % (r["id"], r["cls"], r["conf"], r["verdict"], r["why"]))
    print("汇总：CONFIRMED=%d CONTRADICTED=%d UNPROVEN=%d"
          % (summary[CONFIRMED], summary[CONTRADICTED], summary[UNPROVEN]))
    print("证据图：%s" % draw_evidence(main_bgr, sec_bgr, results, "real", args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
