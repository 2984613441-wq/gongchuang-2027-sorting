# -*- coding: utf-8 -*-
"""无显示器环境下验证三路窗口与副相机模型（2026-11-05）。

用途：在没有实验室设备、也不方便弹窗时，确认：
  1. `three_way_view.render()` 能正常出图（三栏布局不错位）；
  2. 副相机 ONNX 能加载并在合成图上出框（`Cam2Model.detect` 路径通）；
  3. 把渲染结果写成 PNG，便于人眼检查。

用法（用**带 cv2 的环境**跑，例如 D:\\Anaconda\\envs\\yolo\\python.exe）：
    python 工具/smoke_three_way.py --out _three_way_evidence
    python 工具/smoke_three_way.py --model _deploy_maixcam\\yolo11n_6c_cam2.onnx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_pi_tools"))

import three_way_view as tw  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_three_way_evidence")
    ap.add_argument("--model", default="")
    ap.add_argument("--frames", type=int, default=3)
    args = ap.parse_args()

    if not tw.have_images():
        print("当前 Python 没有 cv2/numpy：换 D:\\Anaconda\\envs\\yolo\\python.exe 再跑")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 1) 合成三栏渲染
    for i in range(args.frames):
        st = tw.synthetic_state(i * 0.5)
        canvas = tw.render(st)
        path = out / ("smoke_three_way_%d.png" % i)
        tw.cv2.imwrite(str(path), canvas)
        print("渲染 OK →", path, canvas.shape)

    # 2) 副相机模型冒烟（可选）
    if args.model:
        sess = tw.Cam2Model(args.model, 0.30)
        print("模型状态：", sess.reason)
        if sess.ok:
            st = tw.synthetic_state(0.0)
            frame = st["cam2"]["frame"]
            dets = sess.detect(frame)
            print("合成图上检出 %d 件：%s" % (
                len(dets), [(d["shape"], d["color"], d["conf"]) for d in dets][:6]))
            vis = frame.copy()
            for d in dets:
                x1, y1, x2, y2 = d["box"]
                tw.cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 2)
                tw.cv2.putText(vis, "%d %s %.2f" % (d["shape"], d["color"], d["conf"]),
                               (x1, max(14, y1 - 6)),
                               tw.cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            p = out / "smoke_cam2_model.png"
            tw.cv2.imwrite(str(p), vis)
            print("模型渲染 →", p)

    print("smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
