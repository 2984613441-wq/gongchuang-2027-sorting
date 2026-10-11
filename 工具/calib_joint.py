#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""像素 → 滑台记账 复合映射的联合最小二乘标定（2026-09-22，v2 含视差反解）。

【为什么标"复合映射"而不是"分开解"】——别改回去：
    链只需要 像素 → 滑台记账 PICK。拆成 affine + ToolOffset 时，平移部分**不可辨识**
    （数据只能定出 tx+ox），故 ToolOffset 保持机械真值、只拟合 4 个可辨识量：
        Px = a·u + b·v + cx ,  Py = b·u − a·v + cy      （共形模型）
    写配置时：tx = cx − ox , ty = cy − oy。

【为什么必须带件高（h）】——pixel_to_device.py:404-422 的链路是：
        affine(像素) = G （"顶面"看上去落在地面上的位置）
        B = N + (G − N)/scale ,  scale = H/(H−h) ,  N = 光轴落点 = affine(图像中心)
    而实测真值是 B = P − ToolOffset（P = 把夹爪开到该滑台坐标时、件正落在爪心）。
    ⇒ 拟合时必须先把 B 反推成 G（用该件的 h），否则视差会被"吸收"进参数里，
      残差虚高（可用区内视差量级 3~9mm，正是 RMS 目标的数倍）。
    ⚠️ N 依赖 affine 自身 ⇒ 迭代（本脚本迭代到收敛，通常 3~5 次）。

用法：
    py -3 工具/calib_joint.py points.csv        # 列头: u,v,h_mm,px_mm,py_mm
    py -3 工具/calib_joint.py --selftest
判据：RMS ≤ 2.0mm 且 单点 ≤ 4.0mm（审核v7.md:3078）；任取 4 点 ≤ 3.0mm（01-相机安装方案.md:101）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

# Pi: /home/pi/电控/calibration_config.ini [ToolOffset]（机械真值；**与相机无关**，不参与拟合）
# ⚠️ 2026-09-23 实测更正：原值 (-108.5, -20.5) 是错的 ✗，机械真值为 (-120.5, -43.5)
#    （依据 docs/交付/2026-09-19/标定与工具偏置-最终状态-2026-09-19.md:22-44 的 5 个目视样本均值）
#    旧值会让拟合目标整体偏 (12, 23) mm；Pi 上那份已于 2026-09-23 同步改为此值。
# ⚠️ 另：本文件打印的 "tx = cx − ox" 口径**也是错的** ✗ —— 实测应为 **tx = cx**
#    （见 docs/交付/2026-09-23/实机验证成果与待办-20260923.md:26）
TO = (-120.5, -43.5)
H_CAMERA = 262.0          # [CameraCalibration] camera_height
FRAME = (320.0, 320.0)    # 相机帧；光轴落点取图像中心（pixel_to_device._optical_axis_point）

RMS_LIMIT = 2.0
POINT_LIMIT = 4.0
FOUR_LIMIT = 3.0

# 当前配置值（迭代初值）
A0, B0, TX0, TY0 = -0.027890, -0.477932, 145.697, 39.782


def _nadir(a: float, b: float, tx: float, ty: float) -> tuple[float, float]:
    cx, cy = FRAME[0] / 2.0, FRAME[1] / 2.0
    return (a * cx + b * cy + tx, b * cx - a * cy + ty)


def _fit(points, *, use_parallax: bool, h_camera: float = H_CAMERA, iters: int = 12):
    """points = [(u, v, h_mm, Px_mm, Py_mm)]；返回 (a,b,tx,ty) + 迭代次数"""
    a, b, tx, ty = A0, B0, TX0, TY0
    for k in range(iters):
        nx, ny = _nadir(a, b, tx, ty)
        A, rhs = [], []
        for u, v, h, px, py in points:
            bx, by = px - TO[0], py - TO[1]          # 真值 = 装置坐标 B
            if use_parallax and h > 0.0:
                scale = h_camera / (h_camera - h)
                gx, gy = nx + (bx - nx) * scale, ny + (by - ny) * scale
            else:
                gx, gy = bx, by
            A.append([u, v, 1.0, 0.0]); rhs.append(gx)
            A.append([-v, u, 0.0, 1.0]); rhs.append(gy)
        sol, *_ = np.linalg.lstsq(np.array(A, float), np.array(rhs, float), rcond=None)
        na, nb, ntx, nty = (float(x) for x in sol)
        if max(abs(na - a), abs(nb - b), abs(ntx - tx), abs(nty - ty)) < 1e-9:
            a, b, tx, ty = na, nb, ntx, nty
            break
        a, b, tx, ty = na, nb, ntx, nty
    return a, b, tx, ty, k + 1


def _residuals(points, a, b, tx, ty, *, use_parallax: bool, h_camera: float = H_CAMERA):
    """把参数跑一遍完整链（含视差补偿）→ 预测的滑台坐标，与真值比。单位 mm。"""
    nx, ny = _nadir(a, b, tx, ty)
    out = []
    for u, v, h, px, py in points:
        gx, gy = a * u + b * v + tx, b * u - a * v + ty
        if use_parallax and h > 0.0:
            scale = h_camera / (h_camera - h)
            bx, by = nx + (gx - nx) / scale, ny + (gy - ny) / scale
        else:
            bx, by = gx, gy
        ex, ey = bx + TO[0] - px, by + TO[1] - py
        out.append((ex, ey, float(np.hypot(ex, ey))))
    rms = float(np.sqrt(np.mean([r[2] ** 2 for r in out])))
    return out, rms


def report(points) -> int:
    a, b, tx, ty, it = _fit(points, use_parallax=True)
    resid, rms = _residuals(points, a, b, tx, ty, use_parallax=True)
    _a2, _b2, _tx2, _ty2, _ = _fit(points, use_parallax=False)
    _r2, rms2 = _residuals(points, _a2, _b2, _tx2, _ty2, use_parallax=False)

    nx, ny = _nadir(a, b, tx, ty)
    print("点数 = %d   迭代 = %d 次   光轴落点 N = (%.1f, %.1f)" % (len(points), it, nx, ny))
    print("比例 = %.4f mm/px   角度 = %.2f°"
          % (float(np.hypot(a, b)), float(np.degrees(np.arctan2(-b, a)))))
    print("逐点残差（含视差反解）：")
    for i, (ex, ey, e) in enumerate(resid, 1):
        print("   #%d  Δx=%+6.2f  Δy=%+6.2f  |Δ|=%5.2f mm" % (i, ex, ey, e))
    print("RMS = %.2f mm（≤%.1f）   单点最大 = %.2f mm（≤%.1f）"
          % (rms, RMS_LIMIT, max(r[2] for r in resid), POINT_LIMIT))
    print("对照：不做视差反解时 RMS = %.2f mm  ⇒ 差值 %.2f mm 就是"
          "「链路视差与实测高度是否自洽」的直接证据" % (rms2, rms2 - rms))
    ok = rms <= RMS_LIMIT and max(r[2] for r in resid) <= POINT_LIMIT
    print()
    print("→ 写进 calibration_config.ini（ToolOffset 保持机械真值 %s）：" % (TO,))
    print("   a11 = %.6f" % a)
    print("   a12 = %.6f" % b)
    print("   a21 = %.6f" % b)
    print("   a22 = %.6f" % (-a))
    print("   tx  = %.6f      # = cx − %.1f" % (tx, TO[0]))
    print("   ty  = %.6f      # = cy − %.1f" % (ty, TO[1]))
    print()
    print("验收：%s" % ("✅ 达标（写前仍要备份 + 解析级比对 + 用没参与拟合的点盲测）" if ok
                       else "❌ 不达标 ⇒ 不写盘（先查：对正误差 / 件高是否填对 / 相机是否被碰）"))
    return 0 if ok else 1


def _selftest() -> int:
    """自检：按【真实工作流】造点 → 必须还原参数，并证明"视差反解"是必需的。

    真实工作流：把夹爪开到滑台坐标 P（命令值，精确）⇒ 件落在爪心
                ⇒ 件的装置坐标 B = P − TO   （链的口径：PICK = device + ToolOffset）
                ⇒ 仿射输出 G = N + (B−N)·scale , scale = H/(H−h)
                ⇒ 像素 (u,v) = 共形逆映射(G)
    ⚠️ 符号别写反：是 P = B + TO（TO 为负），不是 P = B − TO。
    """
    a_t, b_t = A0, B0
    nx_t, ny_t = _nadir(a_t, b_t, TX0, TY0)
    det = -(a_t * a_t + b_t * b_t)
    cases = [(-85.0, -85.0, 40.0), (5.0, -85.0, 30.0), (-85.0, -5.0, 32.5),
             (5.0, -5.0, 40.0), (-40.0, -45.0, 30.0)]
    pts, uvs = [], []
    for px, py, h in cases:
        bx, by = px - TO[0], py - TO[1]                      # B = P − TO
        scale = H_CAMERA / (H_CAMERA - h)
        gx, gy = nx_t + (bx - nx_t) * scale, ny_t + (by - ny_t) * scale
        dx, dy = gx - TX0, gy - TY0
        u = (-a_t * dx - b_t * dy) / det                     # 共形逆映射 [[a,b],[b,-a]]
        v = (-b_t * dx + a_t * dy) / det
        pts.append((u, v, h, px, py)); uvs.append((round(u, 1), round(v, 1)))
    a, b, tx, ty, it = _fit(pts, use_parallax=True)
    assert abs(a - a_t) < 1e-6 and abs(b - b_t) < 1e-6, "还原 a/b 失败"
    assert abs(tx - TX0) < 1e-3 and abs(ty - TY0) < 1e-3, \
        "还原 tx/ty 失败：得 %.4f/%.4f，应 %.4f/%.4f" % (tx, ty, TX0, TY0)
    _r, rms = _residuals(pts, a, b, tx, ty, use_parallax=True)
    assert rms < 1e-6, "无噪声残差应为 0，实际 %.2e" % rms
    print("[selftest] 无噪声：还原成功（迭代 %d 次）RMS=%.1e" % (it, rms))
    print("[selftest]   造点像素样例 = %s" % (uvs,))

    _a2, _b2, _tx2, _ty2, _ = _fit(pts, use_parallax=False)
    _r2, rms_np = _residuals(pts, _a2, _b2, _tx2, _ty2, use_parallax=False)
    assert rms_np > 1.0, "不做视差反解本该有明显残差，实际 %.2f（自检失去意义）" % rms_np
    print("[selftest] 对照：不做视差反解 RMS=%.2f mm ⇒ 证明这一步必需" % rms_np)

    rng = np.random.default_rng(0)
    noisy = [(u, v, h, px + rng.normal(0, 1.0), py + rng.normal(0, 1.0))
             for u, v, h, px, py in pts]
    _r3, rms2 = _residuals(noisy, *_fit(noisy, use_parallax=True)[:4], use_parallax=True)
    assert 0.2 < rms2 < 3.0, "1mm 噪声下 RMS 不合理：%.2f" % rms2
    print("[selftest] 1mm 噪声：RMS=%.2f mm（量级合理）" % rms2)
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    if len(argv) < 1:
        print(__doc__)
        return 2
    rows = list(csv.DictReader(Path(argv[0]).open(encoding="utf-8-sig")))
    pts = [(float(r["u"]), float(r["v"]), float(r["h_mm"]),
            float(r["px_mm"]), float(r["py_mm"])) for r in rows]
    return report(pts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
