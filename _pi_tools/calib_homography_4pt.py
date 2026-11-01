#!/usr/bin/env python3
"""双相机 4 点单应标定（主相机像素 → 副相机像素），替代现在的 identity 近似映射。

## 为什么需要

2026-10-30 联调结论：主相机与副相机**视角不同且镜像安装**，
直接把主相机坐标当副相机坐标（identity）会让逐件判决**全部误判**
（实测 8 次 CONTRADICTED 里绝大多数是坐标错位造成的）。
集合模式（按类别计数）可以不依赖标定，但要做「逐件三态判决」必须有 H。

## 做法（§13.4：不是双目标定，只要平面单应）

1. 在托盘上摆 4 个**明显标记**（例如四个彩色小方块，或直接用托盘栅格的 4 个角）
2. 主相机拍一张 → 记下 4 个标记的像素坐标 (u, v)
3. 副相机拍一张 → 记下同样 4 个标记的像素坐标 (u', v')
4. 用本脚本求 H（3×3），并给出**重投影误差**（应 < 3 px）

## 用法（PC 上有图形界面，可直接点击）

    # 交互：先点主相机图的 4 点，再点副相机图的 4 点（顺序必须一致），按回车结束
    python calib_homography_4pt.py --main main.jpg --sec sec.jpg --out calib_h_cam2.json

    # 或用已有坐标（不弹窗）
    python calib_homography_4pt.py --main main.jpg --sec sec.jpg --out h.json \
        --main-points "320,180;960,180;960,540;320,540" \
        --sec-points  "1050,150;180,160;170,560;1040,570"

输出 JSON：
    {"H": [[...],[...],[...]], "reproj_err_px": 1.8, "points_main": [...], "points_sec": [...]}

之后在 `two_cam_live_pc.py` / `two_cam_live.py` 里用 `--homography calib_h_cam2.json` 替换近似映射。

## 校验

脚本会打印每点的重投影误差。**> 3 px 说明点选错或四次点击顺序不一致，别用。**
"""

from __future__ import annotations

import argparse
import json

import cv2
import numpy as np


def click_points(img_path: str, n: int = 4, title: str = "click", max_w: int = 1280):
    img = cv2.imread(img_path)
    if img is None:
        raise SystemExit("读不到图: %s" % img_path)
    h, w = img.shape[:2]
    scale = min(1.0, max_w / float(w))
    show = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img.copy()
    pts = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < n:
            pts.append((x / scale, y / scale))
            cv2.circle(show, (x, y), 6, (0, 255, 0), 2)
            cv2.putText(show, str(len(pts)), (x + 8, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow(title, show)

    cv2.imshow(title, show)
    cv2.setMouseCallback(title, on_mouse)
    print("[calib] %s：请依次点 %d 个点（点完按任意键）" % (title, n))
    while len(pts) < n:
        if cv2.waitKey(50) in (13, 27, 32):
            break
    cv2.waitKey(300)
    cv2.destroyWindow(title)
    if len(pts) < n:
        raise SystemExit("点数不足 %d（只点到 %d）" % (n, len(pts)))
    return np.array(pts, dtype=np.float32)


def parse_pts(s: str):
    return np.array([[float(x) for x in p.split(",")] for p in s.split(";") if p.strip()],
                    dtype=np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True, help="主相机标定图")
    ap.add_argument("--sec", required=True, help="副相机标定图")
    ap.add_argument("--out", default="calib_h_cam2.json")
    ap.add_argument("--main-points", default="", help='主相机 4 点 "x1,y1;x2,y2;..."')
    ap.add_argument("--sec-points", default="", help='副相机 4 点 "x1,y1;..."')
    ap.add_argument("--save-vis", default="", help="可选：保存可视化校验图")
    args = ap.parse_args()

    if args.main_points and args.sec_points:
        pm, ps = parse_pts(args.main_points), parse_pts(args.sec_points)
    else:
        pm = click_points(args.main, 4, "MAIN: click 4 points")
        ps = click_points(args.sec, 4, "SEC: click 4 points (same order)")
    if len(pm) < 4 or len(ps) < 4:
        raise SystemExit("至少需要 4 点")

    H, mask = cv2.findHomography(pm, ps, cv2.RANSAC, 5.0)
    if H is None:
        raise SystemExit("❌ findHomography 失败（点可能共线）")

    proj = cv2.perspectiveTransform(pm.reshape(-1, 1, 2), H).reshape(-1, 2)
    err = np.linalg.norm(proj - ps, axis=1)
    print("=" * 60)
    print("H =\n%s" % np.array2string(H, precision=6, suppress_small=True))
    print("每点重投影误差(px): %s" % np.array2string(err, precision=2))
    print("最大 %.2f px ｜ 平均 %.2f px" % (err.max(), err.mean()))
    verdict = "✅ 可用" if err.max() < 3.0 else "❌ 误差过大（>3px），检查点选与顺序"
    print("判定: " + verdict)
    print("=" * 60)

    data = dict(H=H.tolist(), reproj_err_px=[float(v) for v in err], max_err_px=float(err.max()),
                points_main=pm.tolist(), points_sec=ps.tolist(),
                src=dict(main=args.main, sec=args.sec),
                note="H 把主相机像素映射到副相机像素；使用前确认 max_err_px<3")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("已保存: %s" % args.out)

    if args.save_vis:
        img = cv2.imread(args.sec)
        for (u, v), (u2, v2) in zip(pm, proj):
            cv2.circle(img, (int(u2), int(v2)), 8, (0, 255, 0), 2)
        for p in ps:
            cv2.drawMarker(img, (int(p[0]), int(p[1])), (0, 0, 255), cv2.MARKER_CROSS, 16, 2)
        ok, buf = cv2.imencode(".jpg", img)
        if ok:
            buf.tofile(args.save_vis)
            print("校验图: %s（绿圈=主相机映射点，红叉=副相机实测点，应重合）" % args.save_vis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
