#!/usr/bin/env python3
r"""双目（Y 轴对称）+ 中央 ToF 的几何计算器 —— 用来定托盘尺寸。

## 为什么需要这个

你现在的方案是：
```
   左相机(Pi,辅)              右相机(MaixCAM,主)
        \  θ                      /  θ
         \                        /
          ┌──────────────────────┐
          │      托盘（一个）     │
          │                      │
          │     ToF（中间）       │  8x8 点阵
          └──────────────────────┘
```

要回答的问题：
  1. 这个高度/倾角/间距下，两个相机**各自**能看到多大地面区域？
  2. 两个视角的**并集**能覆盖多大的托盘？
  3. 托盘各处 **mm/px** 是多少（越远越粗）？
  4. 物体高度引起的**视差误差**各处多大？（用 ToF 测高后可补偿）
  5. ToF 8x8 的**点间距**多大？能分辨多大的物体？

## 用法

```bash
# 用默认参数算一遍
python _pi_tools/geometry_calc_2cam.py

# 改参数
python _pi_tools/geometry_calc_2cam.py --height 300 --tilt 15 --sep 400
```

不需要相机、不需要联网，纯数学。
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field


@dataclass
class CameraGeom:
    """一个相机的几何参数（世界坐标：X 向右、Y 向前、Z 向上，原点=托盘中心地面）"""
    name: str
    x: float                  # 相机光心在世界坐标的 x（mm）
    y: float                  # y
    z: float                  # 高度（mm）
    tilt_deg: float           # 相对竖直方向（天底）的倾斜角，度
    yaw_deg: float            # 光学轴在 XY 平面的方位角（度，0=+Y）
    fov_h_deg: float          # 水平 FOV
    fov_v_deg: float          # 垂直 FOV
    res_w: int = 1280
    res_h: int = 720

    def ray_dir(self, u: float, v: float) -> tuple[float, float, float]:
        """像素 (u,v) 归一化到 [0,1] → 世界坐标下的单位方向向量。

        相机朝向：先绕 Z 轴转 yaw，再绕 X 轴倾斜 tilt（天底=0）。
        相机本地坐标：+Z 是光轴方向，+X 右、+Y 下。
        """
        # 像素 → 相机本地归一化坐标（假设无畸变、针孔）
        ndc_x = (u - 0.5) * 2.0 * math.tan(math.radians(self.fov_h_deg / 2.0))
        ndc_y = (v - 0.5) * 2.0 * math.tan(math.radians(self.fov_v_deg / 2.0))
        # 相机本地：光轴 -Z（朝下），所以视线方向 = (ndc_x, ndc_y, -1) 归一化
        d_local = (ndc_x, ndc_y, -1.0)

        # 先倾斜（绕本地 X 轴，让光轴朝 yaw 方向偏 tilt）
        t = math.radians(self.tilt_deg)
        ct, st = math.cos(t), math.sin(t)
        # 绕 X 轴旋转：z 轴（朝下）向 +Y 偏转
        x1 = d_local[0]
        y1 = d_local[1] * ct - d_local[2] * st
        z1 = d_local[1] * st + d_local[2] * ct

        # 再绕 Z 轴旋转 yaw
        a = math.radians(self.yaw_deg)
        ca, sa = math.cos(a), math.sin(a)
        x2 = x1 * ca - y1 * sa
        y2 = x1 * sa + y1 * ca
        z2 = z1

        n = math.sqrt(x2 * x2 + y2 * y2 + z2 * z2)
        if n < 1e-9:
            return (0.0, 0.0, -1.0)
        return (x2 / n, y2 / n, z2 / n)

    def ground_hit(self, u: float, v: float, ground_z: float = 0.0):
        """像素视线与 z=ground_z 平面的交点。返回 (x, y) 或 None（射向天空）。"""
        dx, dy, dz = self.ray_dir(u, v)
        if dz >= -1e-6:
            return None
        t = (ground_z - self.z) / dz
        if t <= 0:
            return None
        return (self.x + dx * t, self.y + dy * t)

    def footprint(self, n: int = 33) -> list[tuple[float, float]]:
        """地面覆盖四边形（边界采样）。"""
        pts = []
        # 遍历四条边
        for i in range(n):
            u = i / (n - 1)
            for v in (0.0, 1.0):
                p = self.ground_hit(u, v)
                if p:
                    pts.append(p)
        for i in range(n):
            v = i / (n - 1)
            for u in (0.0, 1.0):
                p = self.ground_hit(u, v)
                if p:
                    pts.append(p)
        return pts

    def gsd_mm_per_px(self, obj_x: float, obj_y: float, obj_z: float = 0.0):
        """在某个物点处的 mm/px（水平方向近似）。

        做法：取该点在图像中的 (u,v)，向 u+du 方向找 +1px 的地面/平面交点，
        算距离。更严谨的做法是沿地面法向，这里取水平距离即可。
        """
        # 反解 (u,v)：用简单搜索（够快，33x33 够用）
        # 更省事：直接用几何近似
        # 相机到该点的距离（沿光轴分量）
        dx = obj_x - self.x
        dy = obj_y - self.y
        dz = obj_z - self.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist <= 0:
            return float("inf")
        # 水平方向 1px 张角
        px_angle = math.radians(self.fov_h_deg) / self.res_w
        return dist * px_angle


@dataclass
class ToFGeom:
    """中央 ToF（8x8 点阵）"""
    x: float = 0.0
    y: float = 0.0
    z: float = 300.0
    fov_deg: float = 65.0     # 全角
    grid: int = 8

    def point_xy(self, i: int, j: int) -> tuple[float, float] | None:
        """第 (i,j) 个点的地面位置（i,j ∈ 0..grid-1）。"""
        half = math.tan(math.radians(self.fov_deg / 2.0))
        # 网格中心在光轴上
        u = (i + 0.5) / self.grid * 2.0 - 1.0
        v = (j + 0.5) / self.grid * 2.0 - 1.0
        dx = u * half
        dy = v * half
        dz = -1.0
        n = math.sqrt(dx * dx + dy * dy + dz * dz)
        dx, dy, dz = dx / n, dy / n, dz / n
        if dz >= -1e-6:
            return None
        t = (0.0 - self.z) / dz
        return (self.x + dx * t, self.y + dy * t)

    def spacing_mm(self) -> float:
        """相邻点在地面上的间距。"""
        a = self.point_xy(0, 0)
        b = self.point_xy(1, 0)
        if a and b:
            return math.hypot(b[0] - a[0], b[1] - a[1])
        return 0.0

    def coverage_radius(self) -> float:
        """覆盖半径。"""
        return self.z * math.tan(math.radians(self.fov_deg / 2.0))


def bbox_of(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def rect_fits_in(rect_w: float, rect_h: float,
                 region_pts) -> tuple[bool, str]:
    """粗略判断矩形托盘是否能完全落在覆盖区域内。

    做法：检查托盘的 4 个角 + 中心点是否都在凸包内。
    """
    if not region_pts or len(region_pts) < 3:
        return False, "覆盖区域为空"

    # 凸包
    pts = sorted(set((round(p[0], 2), round(p[1], 2)) for p in region_pts))
    if len(pts) < 3:
        return False, "点太少"

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]

    def inside(pt):
        n = len(hull)
        for i in range(n):
            a, b = hull[i], hull[(i + 1) % n]
            if cross(a, b, pt) < 0:
                return False
        return True

    hw, hh = rect_w / 2.0, rect_h / 2.0
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (0, 0)]
    for c in corners:
        if not inside(c):
            return False, "角点 %s 超出覆盖" % (c,)
    return True, "全在覆盖内"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="双目+ToF 几何计算器")
    ap.add_argument("--height", type=float, default=300.0,
                    help="相机高度（mm）")
    ap.add_argument("--tilt", type=float, default=15.0,
                    help="相机倾角（度，相对竖直）")
    ap.add_argument("--sep", type=float, default=400.0,
                    help="两个相机的 x 间距（mm）")
    ap.add_argument("--fov-h", type=float, default=67.0, help="水平 FOV（度）")
    ap.add_argument("--fov-v", type=float, default=40.9, help="垂直 FOV（度）")
    ap.add_argument("--tof-height", type=float, default=300.0,
                    help="ToF 高度（mm）")
    ap.add_argument("--tof-fov", type=float, default=65.0, help="ToF 全角 FOV")
    args = ap.parse_args(argv)

    h = args.height
    tilt = args.tilt
    sep = args.sep

    # 左相机在 -x，朝 +x 方向倾斜；右相机镜像
    # ⚠️ yaw 符号（2026-10-26 修 bug）：
    #   注入 tilt 后光轴在 yaw=0 时指向 +Y。
    #   yaw=-90° ⇒ 光轴朝 +X ⇒ 适合放在 -x 侧（左）的相机看向中心。
    #   yaw=+90° ⇒ 光轴朝 -X ⇒ 适合放在 +x 侧（右）的相机看向中心。
    #   写反了会造成「两相机互相看开、中间成盲区」（实测踩过）。
    cam_l = CameraGeom("左(-x)", x=-sep / 2, y=0, z=h,
                       tilt_deg=tilt, yaw_deg=-90.0,
                       fov_h_deg=args.fov_h, fov_v_deg=args.fov_v)
    cam_r = CameraGeom("右(+x)", x=+sep / 2, y=0, z=h,
                       tilt_deg=tilt, yaw_deg=+90.0,
                       fov_h_deg=args.fov_h, fov_v_deg=args.fov_v)
    tof = ToFGeom(z=args.tof_height, fov_deg=args.tof_fov)

    print("=" * 78)
    print("  双目（Y 轴对称）+ 中央 ToF 几何计算")
    print("=" * 78)
    print("  相机高度   : %.0f mm" % h)
    print("  倾角       : %.1f 度（相对竖直）" % tilt)
    print("  相机间距   : %.0f mm（x 方向）" % sep)
    print("  水平 FOV   : %.1f 度" % args.fov_h)
    print("  垂直 FOV   : %.1f 度" % args.fov_v)
    print()

    for cam in (cam_l, cam_r):
        pts = cam.footprint()
        bb = bbox_of(pts)
        print("  ── %s ──" % cam.name)
        print("    光心位置   : (%.0f, %.0f, %.0f)" % (cam.x, cam.y, cam.z))
        if bb:
            print("    地面覆盖   : x [%.0f, %.0f]  y [%.0f, %.0f]"
                  % (bb[0], bb[2], bb[1], bb[3]))
            print("    覆盖宽度   : x %.0f mm, y %.0f mm"
                  % (bb[2] - bb[0], bb[3] - bb[1]))
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            print("    覆盖中心   : (%.0f, %.0f)" % (cx, cy))
            print("    中心处 mm/px : %.3f" % cam.gsd_mm_per_px(cx, cy, 0))
            print("    最远处 mm/px : %.3f"
                  % max(cam.gsd_mm_per_px(bb[0], bb[1], 0),
                        cam.gsd_mm_per_px(bb[2], bb[3], 0)))
        else:
            print("    ❌ 看不到地面（倾角太小或太高）")
        print()

    # 并集
    all_pts = cam_l.footprint() + cam_r.footprint()
    bb = bbox_of(all_pts)
    print("  ── 两个视角的并集 ──")
    if bb:
        print("    覆盖        : x [%.0f, %.0f]  y [%.0f, %.0f]"
              % (bb[0], bb[2], bb[1], bb[3]))
        print("    总覆盖      : x %.0f mm × y %.0f mm"
              % (bb[2] - bb[0], bb[3] - bb[1]))
    print()

    # 托盘尺寸建议
    print("  ── 托盘尺寸建议 ──")
    for tw in (160, 175, 185, 200, 220, 250):
        fits_union, why_u = rect_fits_in(tw, tw, all_pts)
        fits_l, _ = rect_fits_in(tw, tw, cam_l.footprint())
        fits_r, _ = rect_fits_in(tw, tw, cam_r.footprint())
        mark = "✅" if fits_union else "❌"
        print("    %.0f×%.0f mm : 并集%s(%s)  单左%s  单右%s"
              % (tw, tw, mark, why_u if not fits_union else "OK",
                 "✅" if fits_l else "❌", "✅" if fits_r else "❌"))
    print()

    # ToF
    print("  ── 中央 ToF（8×8）──")
    print("    高度        : %.0f mm" % tof.z)
    print("    FOV         : %.0f 度" % tof.fov_deg)
    print("    覆盖半径    : %.0f mm（直径 %.0f mm）"
          % (tof.coverage_radius(), tof.coverage_radius() * 2))
    sp = tof.spacing_mm()
    print("    点间距      : %.1f mm" % sp)
    print("    ⇒ 一个 %.0f mm 的物件落在 %d~%d 个点上"
          % (50, max(1, int(50 / sp)), max(1, int(50 / sp)) + 1))
    print("    ⚠️ 若点间距 > 40mm，则 40~60mm 的物件只有 1~2 个点 ⇒")
    print("        能测**高度**，但测不出**形状梯度**（圆柱 vs 圆锥分不开）")
    print()

    # 视差误差表
    print("  ── 视差误差（物体顶面相对底面的偏移）──")
    print("    倾角 %.1f°: 偏移 ≈ H × tan(%.1f°) = H × %.3f" %
          (tilt, tilt, math.tan(math.radians(tilt))))
    print("    %-10s %-14s %-14s" % ("物体高度", "视差偏移", "ToF测高后残差"))
    for H in (30, 40, 45, 55, 60):
        off = H * math.tan(math.radians(tilt))
        print("    %-10s %-14s %-14s"
              % ("%d mm" % H, "%.1f mm" % off, "≈0（可精确补偿）"))
    print()
    print("=" * 78)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
