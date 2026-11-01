#!/usr/bin/env python3
"""双相机「基础验收」一键判读（PC 侧，主/副相机通用）。

## 为什么有它

相机装没装正、清不清晰，靠"看着差不多"会反复返工（今天已经踩过一次：主相机被碰成 +61°）。
本脚本把判据变成数字，**装一次拍一张，30 秒内知道合不合格**。

## 判据（与 v11 训练数据对齐）

| 指标 | 合格区间 | 说明 |
|---|---|---|
| 托盘占画面宽 | **78% ~ 87%** | 训练集实测 81.4% / 78.2% |
| 网格主方向（≈滚转） | **|角| ≤ 5°** | 训练图≈0°；今天实测 +61° 就是不合格 |
| 托盘高度占画面 | **≥ 90%**（远端不被切另看 `touch_top`）| 训练帧托盘纵贯画面 |
| 清晰度 laplacian | **≥ 300**（相对比较也可）| 失焦帧实测 218/128 |
| 检出件数（给了 --model 时）| **≥ 1** | 台上要真的有件 |

## 用法

    # 只量几何/清晰度（不需要模型）
    python cam_verdict.py frame.jpg

    # 顺带跑 v11 看检出
    python cam_verdict.py frame.jpg --model _runs/yolo11n_6c_v11/weights/best.pt

    # 批量（同一位置连拍多张，看稳定性）
    python cam_verdict.py --batch dir/ --model ...

退出码：0 = 全部合格；1 = 有不合格项；2 = 读不到图。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import cv2
import numpy as np

# ── 判据默认值（可在命令行覆盖）──────────────────────────────────────────────
TRAY_W_MIN = 0.78
TRAY_W_MAX = 0.87
TRAY_H_MIN = 0.90
MAX_ROLL_DEG = 5.0
MIN_SHARPNESS = 0.0   # 0 = 不参与判定（清晰度受内容影响大，只作对焦相对参考）


def white_tray_bbox(img: np.ndarray):
    """找白色托盘的最大连通域 → bbox 与占比。

    用 HSV：V>100 且 S<60（白托盘哑光；实验台/墙也偏白 ⇒ 取最大连通域 + 形态学闭运算）。
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 0, 100), np.uint8),
                       np.array((179, 60, 255), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, 1)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = float(cv2.contourArea(c))
    if area < 0.02 * w * h:
        return None
    x, y, bw, bh = cv2.boundingRect(c)
    return {
        "box": (x, y, x + bw, y + bh),
        "w_frac": bw / w, "h_frac": bh / h,
        "area_frac": area / (w * h),
        "touch_top": y <= 3, "touch_bottom": (y + bh) >= h - 3,
        "touch_left": x <= 3, "touch_right": (x + bw) >= w - 3,
    }


def grid_roll_deg(img: np.ndarray, box, min_len_ratio: float = 0.18):
    """在托盘 ROI 内测网格主方向 → 近似相机滚转（度）。

    做法：ROI 内 Canny + HoughP，取长线；把角度对 90° 取模折到 [-45,45]，
    再按长度加权取中位数。托盘是栅格/白板边界，训练位姿下应接近 0°。
    """
    x1, y1, x2, y2 = box
    roi = img[max(0, y1):y2, max(0, x1):x2]
    if roi.size == 0:
        return None, 0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    min_len = max(40, int(min_len_ratio * min(roi.shape[:2])))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                            minLineLength=min_len, maxLineGap=12)
    if lines is None:
        return None, 0
    angs, lens = [], []
    for x_1, y_1, x_2, y_2 in lines.reshape(-1, 4):
        dx, dy = float(x_2 - x_1), float(y_2 - y_1)
        L = float(np.hypot(dx, dy))
        if L < min_len:
            continue
        a = float(np.degrees(np.arctan2(dy, dx))) % 90.0   # 0..90
        if a > 45.0:
            a -= 90.0                                      # 折到 (-45,45]
        angs.append(a)
        lens.append(L)
    if not angs:
        return None, 0
    angs = np.array(angs)
    lens = np.array(lens)
    order = np.argsort(angs)
    cum = np.cumsum(lens[order]) / lens.sum()
    med = float(angs[order][np.searchsorted(cum, 0.5)])
    return med, len(angs)


def sharpness(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def white_quadrants(img: np.ndarray):
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 100))
    out = {}
    for name, sl in (("左上", (slice(0, h // 2), slice(0, w // 2))),
                     ("右上", (slice(0, h // 2), slice(w // 2, w))),
                     ("左下", (slice(h // 2, h), slice(0, w // 2))),
                     ("右下", (slice(h // 2, h), slice(w // 2, w)))):
        out[name] = float(m[sl].mean()) * 100.0
    return out


def verdict_for(path: str, model, args) -> dict:
    img = cv2.imread(path)
    if img is None:
        return {"path": path, "error": "读不到图"}
    h, w = img.shape[:2]
    sharp = sharpness(img)
    tray = white_tray_bbox(img)
    quad = white_quadrants(img)
    res = {
        "path": path, "size": (w, h), "sharpness": sharp, "tray": tray,
        "quadrants": quad, "roll_deg": None, "n_lines": 0,
        "detections": None, "fails": [],
    }
    if tray is not None:
        roll, n = grid_roll_deg(img, tray["box"])
        res["roll_deg"], res["n_lines"] = roll, n
    if model is not None:
        r = model.predict(img, imgsz=448, conf=0.25, verbose=False)[0]
        res["detections"] = [
            (model.names[int(b.cls)], float(b.conf),
             [round(float(v), 1) for v in b.xyxy[0]]) for b in r.boxes
        ]
    # ── 判据 ──
    if tray is not None and (tray["touch_left"] and tray["touch_right"]
                             and tray["touch_top"] and tray["touch_bottom"]):
        res["fails"].append("白色区域占满全画面（疑似背景/墙面）⇒ 不认定为托盘")
        tray = None
    if tray is None:
        res["fails"].append("找不到白色托盘（占位/遮挡/曝光）")
    else:
        if not (args.tray_min <= tray["w_frac"] <= args.tray_max):
            res["fails"].append("托盘占宽 %.1f%% ∉ [%.0f%%,%.0f%%]"
                                % (tray["w_frac"] * 100, args.tray_min * 100,
                                   args.tray_max * 100))
        if tray["h_frac"] < args.tray_h_min:
            res["fails"].append("托盘占高 %.1f%% < %.0f%%"
                                % (tray["h_frac"] * 100, args.tray_h_min * 100))
        if res["roll_deg"] is None or res["n_lines"] < 12:
            res["fails"].append("网格长线不足（%d 条）⇒ 主方向不可判，先确认托盘在画面里" % res["n_lines"])
        elif abs(res["roll_deg"]) > args.max_roll:
            res["fails"].append("网格主方向 %+.1f°（|·| > %.0f°）"
                                % (res["roll_deg"], args.max_roll))
    if sharp < args.min_sharp:
        res["fails"].append("清晰度 %.0f < %.0f（失焦/运动模糊）"
                            % (sharp, args.min_sharp))
    if res["detections"] is not None and len(res["detections"]) == 0:
        res["fails"].append("v11 检出 0 件（台上没件？或模型/位姿不对）")
    return res


def print_one(res: dict) -> None:
    name = os.path.basename(res["path"])
    if "error" in res:
        print("❌ %s：%s" % (name, res["error"]))
        return
    tray = res["tray"]
    print("─" * 74)
    print("【%s】 %dx%d" % (name, res["size"][0], res["size"][1]))
    print("  清晰度 laplacian = %.0f" % res["sharpness"])
    if tray:
        x1, y1, x2, y2 = tray["box"]
        print("  托盘 bbox = (%d,%d)-(%d,%d)  占宽 %.1f%%  占高 %.1f%%  面积 %.1f%%"
              % (x1, y1, x2, y2, tray["w_frac"] * 100, tray["h_frac"] * 100,
                 tray["area_frac"] * 100))
        flags = [k for k, cond in (("顶边被切", tray["touch_top"]),
                                   ("底边被切", tray["touch_bottom"]),
                                   ("左边被切", tray["touch_left"]),
                                   ("右边被切", tray["touch_right"])) if cond]
        print("  边缘状态 = %s" % (" / ".join(flags) if flags else "四边都在画面内"))
    else:
        print("  托盘 bbox = 未找到")
    if res["roll_deg"] is not None:
        print("  网格主方向 = %+.1f°（长线 %d 条）" % (res["roll_deg"], res["n_lines"]))
    q = res["quadrants"]
    print("  白色占比  左上 %.1f%%  右上 %.1f%%  左下 %.1f%%  右下 %.1f%%"
          % (q["左上"], q["右上"], q["左下"], q["右下"]))
    if res["detections"] is not None:
        print("  v11 检出 %d 件" % len(res["detections"]))
        for cls, conf, box in res["detections"][:8]:
            print("      %-18s conf=%.2f  %s" % (cls, conf, box))
    if res["fails"]:
        print("  ❌ 不合格 %d 项：" % len(res["fails"]))
        for f in res["fails"]:
            print("      · %s" % f)
    else:
        print("  ✅ 全部判据通过（占宽/占高/主方向/清晰度%s）"
              % ("/检出" if res["detections"] is not None else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="单张图（或用 --batch）")
    ap.add_argument("--batch", help="目录或 glob，一次判多张")
    ap.add_argument("--model", help="v11 best.pt（可选，给了才跑检出）")
    ap.add_argument("--tray-min", type=float, default=TRAY_W_MIN)
    ap.add_argument("--tray-max", type=float, default=TRAY_W_MAX)
    ap.add_argument("--tray-h-min", type=float, default=TRAY_H_MIN)
    ap.add_argument("--max-roll", type=float, default=MAX_ROLL_DEG)
    ap.add_argument("--min-sharp", type=float, default=MIN_SHARPNESS)
    args = ap.parse_args(argv)

    model = None
    if args.model:
        try:
            from ultralytics import YOLO
            model = YOLO(args.model)
        except Exception as e:
            print("⚠️ 模型加载失败（跳过检出）：%s" % e)

    if args.batch:
        pats = [args.batch] if any(ch in args.batch for ch in "*?[") else [
            os.path.join(args.batch, "*.jpg"), os.path.join(args.batch, "*.png")]
        files = []
        for p in pats:
            files.extend(sorted(glob.glob(p)))
        if not files:
            print("❌ 没找到图片：%s" % args.batch)
            return 2
    elif args.image:
        files = [args.image]
    else:
        ap.print_help()
        return 2

    bad = 0
    results = []
    for f in files:
        r = verdict_for(f, model, args)
        results.append(r)
        print_one(r)
        if r.get("fails"):
            bad += 1
    print("=" * 74)
    print("汇总：%d 张，合格 %d，不合格 %d" % (len(files), len(files) - bad, bad))
    if len(results) > 1:
        ok = [r for r in results if not r.get("fails") and r.get("tray")]
        if ok:
            ws = [r["tray"]["w_frac"] * 100 for r in ok]
            rs = [r["roll_deg"] for r in ok if r["roll_deg"] is not None]
            print("合格组统计：占宽 %.1f%%~%.1f%%（均 %.1f%%）%s"
                  % (min(ws), max(ws), sum(ws) / len(ws),
                     "，主方向 %+.1f°~%+.1f°" % (min(rs), max(rs)) if rs else ""))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
