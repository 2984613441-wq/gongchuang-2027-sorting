# -*- coding: utf-8 -*-
"""精确法 3 点 → 解 [CameraCalibration] 的共形 4 参（并给出真检验残差）。

模型（本项目原有口径，`pixel_to_device.py:79-126` 的 validate_affine 不查共形）：
    device_x = a*u + b*v + tx
    device_y = b*u - a*v + ty
⇒ 4 个未知数 ⇒ **2 点即可解，3 点有余量（6 方程 / 4 未知 ⇒ 2 个自由度的真检验）**

数据口径：现场"倒过来"测的精确点 ——
    夹爪开到一个自选滑台坐标（机器坐标精确）→ 用户把件塞进爪片对正
    → 画圈做记号 → 取出件 → 夹爪退开 → 件放回圈里 → 读像素
    ⇒ 得到 (像素, 精确滑台坐标)，**不含"目视报残差"的 ±5mm 噪声**
⚠️ 必须在夹爪【退开】之后读：件塞在爪片里时会被遮挡，实测同一位置偏差达 (-27,-53) px。

装置真实坐标 = 滑台坐标 − [ToolOffset] = 滑台坐标 + (108.5, 20.5)

用法：python3 工具/fit_affine_conformal.py
"""
import sys

import numpy as np

# 原始（2026-09-19 两锚点）配置，用于对比
ORIG = dict(a11=0.047142, a12=-0.483206, tx=148.453,
            a21=-0.483206, a22=-0.047142, ty=52.105)
TO_FIXED = (-108.5, -20.5)

# (px, py, 滑台x, 滑台y, 标签)
SAMPLES = [
    (226, 255, -88.0, -88.0, "A'"),
    (231,  75, -12.0, -88.0, "B'"),
    ( 61, 162, -38.0,   0.0, "C "),
]


def solve(samples):
    rows, rhs = [], []
    for px, py, sx, sy, _ in samples:
        dx, dy = sx - TO_FIXED[0], sy - TO_FIXED[1]     # 装置真实目标
        rows.append([px, py, 1.0, 0.0])
        rhs.append(dx)
        rows.append([-py, px, 0.0, 1.0])
        rhs.append(dy)
    a, b, tx, ty = np.linalg.lstsq(np.asarray(rows), np.asarray(rhs),
                                   rcond=None)[0]
    return a, b, tx, ty


def predict(a, b, tx, ty, px, py):
    return (a * px + b * py + tx + TO_FIXED[0],
            b * px - a * py + ty + TO_FIXED[1])


def main():
    a, b, tx, ty = solve(SAMPLES)
    s = float(np.hypot(a, b))
    ang = float(np.degrees(np.arctan2(b, a)))
    s0 = float(np.hypot(ORIG["a11"], ORIG["a12"]))
    ang0 = float(np.degrees(np.arctan2(ORIG["a12"], ORIG["a11"])))

    print("=" * 70)
    print("解（共形 4 参，%d 个精确点 / %d 个方程）" % (len(SAMPLES), 2 * len(SAMPLES)))
    print("=" * 70)
    for k, v in (("a11", a), ("a12", b), ("tx", tx),
                 ("a21", b), ("a22", -a), ("ty", ty)):
        print("  %-4s = %+.6f" % (k, v))

    print("\n  比例 = %.4f mm/px  ⇒ 320px 视场 = %.1f mm" % (s, 320 * s))
    print("  角度 = %.2f°" % ang)
    print("\n  与原始配置对比：")
    print("    比例 %.4f → %.4f   （%+.1f%%）" % (s0, s, 100 * (s / s0 - 1)))
    print("    角度 %.2f° → %.2f°   （%+.2f°）" % (ang0, ang, ang - ang0))
    print("    ⇒ 若比例基本不变、角度变了 ⇒ 相机是【在支架上被转过一个角度】而不是变近/变高")

    print("\n" + "=" * 70)
    print("逐点残差（这是真检验：方程 6 个、未知 4 个）")
    print("=" * 70)
    worst = 0.0
    for px, py, sx, sy, tag in SAMPLES:
        ex, ey = predict(a, b, tx, ty, px, py)
        e = float(np.hypot(ex - sx, ey - sy))
        worst = max(worst, e)
        print("  %-3s px=%3d py=%3d  预测滑台=(%+7.1f,%+7.1f) 真值=(%+7.1f,%+7.1f)  误差 %.1fmm"
              % (tag, px, py, ex, ey, sx, sy, e))
    print("  ⇒ 最大残差 %.1f mm   （calib_affine.py 判据：单点 ≤5.0mm）" % worst)

    print("\n" + "=" * 70)
    print("可直接粘进 [CameraCalibration]")
    print("=" * 70)
    print("a11 = %.6f    a12 = %.6f    tx = %.3f" % (a, b, tx))
    print("a21 = %.6f    a22 = %.6f    ty = %.3f" % (b, -a, ty))
    print("# 共形约束：a21 == a12 ✓    a22 == -a11 ✓")

    assert np.isfinite([a, b, tx, ty]).all()
    assert 0.02 <= s <= 20.0, "比例超出 validate_affine 的合理范围"
    det = a * (-a) - b * b
    assert abs(det) >= 1e-9 * s * s, "矩阵接近奇异"
    print("\n[PASS] 自检通过（含 validate_affine 的两条硬判据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
