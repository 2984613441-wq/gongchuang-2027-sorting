#!/usr/bin/env python3
"""由标定点解「像素 → 装置 mm」仿射矩阵，并给出残差与是否可用。

模型（6 参数，就是 calibration_config.ini 的 [CameraCalibration]）：
    x_mm = a11*u + a12*v + tx
    y_mm = a21*u + a22*v + ty
相机的安装偏置全部体现在 tx/ty 里 —— **不需要知道相机装在哪**，只需要这 6 个数。

用法：
    py -3 工具/calib_affine.py 标定点.txt
    标定点.txt 每行一个点（# 开头与空行忽略）：
        u v x y
    其中 (u,v) 是 MaixCAM 报的 bbox 中心像素（**320 系**），
    (x,y) 是量出来的装置坐标 mm（原点 = 装置中心）。

最少 3 点且不共线；**强烈建议 9 点（四角 + 四边中点 + 中心）**。
四角必须覆盖到，否则外推会崩。

纯 Python（不依赖 numpy）——树莓派上未必有 numpy。
"""

from __future__ import annotations

import sys

# 判据：九宫格反向验证要求 RMS ≤ 2mm、单点最大 ≤ 5mm（落料点余量只有 5mm）
RMS_LIMIT_MM = 2.0
MAX_LIMIT_MM = 5.0


def solve3(a: list[list[float]], b: list[float]) -> list[float]:
    """3x3 线性方程组高斯消元（带部分主元）。"""

    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("法方程奇异：标定点共线或重复，请换几个分散的点")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(3):
            if r == col:
                continue
            f = m[r][col] / m[col][col]
            for c in range(col, 4):
                m[r][c] -= f * m[col][c]
    return [m[i][3] / m[i][i] for i in range(3)]


def fit(points: list[tuple[float, float, float, float]], target: str):
    """最小二乘拟合 target 分量（'x' 或 'y'）。返回 (系数3个, 逐点残差)。"""

    index = 2 if target == "x" else 3
    # 法方程 A^T A c = A^T b，A 的每行是 [u, v, 1]
    ata = [[0.0] * 3 for _ in range(3)]
    atb = [0.0] * 3
    for p in points:
        row = [p[0], p[1], 1.0]
        for i in range(3):
            for j in range(3):
                ata[i][j] += row[i] * row[j]
            atb[i] += row[i] * p[index]
    coef = solve3(ata, atb)
    residuals = [
        (coef[0] * p[0] + coef[1] * p[1] + coef[2]) - p[index] for p in points
    ]
    return coef, residuals


def main(path: str) -> int:
    points: list[tuple[float, float, float, float]] = []
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) != 4:
                print(f"跳过第 {lineno} 行（不是 4 个数）：{line!r}")
                continue
            try:
                points.append(tuple(float(x) for x in parts))  # type: ignore[arg-type]
            except ValueError:
                print(f"跳过第 {lineno} 行（表头/说明，不是数字）：{line!r}")
                continue

    if len(points) < 3:
        print(f"只有 {len(points)} 个点，至少需要 3 个（不共线）")
        return 2

    (a11, a12, tx), rx = fit(points, "x")
    (a21, a22, ty), ry = fit(points, "y")

    print(f"标定点数：{len(points)}")
    print()
    print("# ---- 粘进 电控/calibration_config.ini 的 [CameraCalibration] ----")
    for key, value in (("a11", a11), ("a12", a12), ("tx", tx),
                       ("a21", a21), ("a22", a22), ("ty", ty)):
        print(f"{key} = {value:.6f}")
    print()
    print("# ---- 逐点残差（mm）----")
    worst = 0.0
    total = 0.0
    for point, dx, dy in zip(points, rx, ry):
        error = (dx * dx + dy * dy) ** 0.5
        worst = max(worst, error)
        total += error * error
        print(f"  u={point[0]:7.1f} v={point[1]:7.1f} -> "
              f"x={point[2]:7.1f} y={point[3]:7.1f}   误差 {error:6.2f} mm")
    rms = (total / len(points)) ** 0.5

    print()
    print(f"RMS  = {rms:.2f} mm   （判据 ≤ {RMS_LIMIT_MM}）")
    print(f"最大 = {worst:.2f} mm   （判据 ≤ {MAX_LIMIT_MM}）")
    print()
    if rms <= RMS_LIMIT_MM and worst <= MAX_LIMIT_MM:
        print("✅ 可用。但**仍须上机做九宫格反向验证**（预测位置 → 走位 → 量偏差）。")
        return 0
    print("❌ 不可用。常见原因：")
    print("   · 标定点没铺开到工作台四角（最常见，外推会崩）")
    print("   · (u,v) 记错：MaixCAM 是 320x320，别按 448 换算")
    print("   · 机器坐标 x/y 不是同一个原点（确认原点=行程中心，且是正方向）")
    print("   · 物体高度不同却没做视差补偿")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
