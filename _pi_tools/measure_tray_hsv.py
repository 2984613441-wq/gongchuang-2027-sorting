# -*- coding: utf-8 -*-
"""从 MaixCAM 实拍的托盘照片里，直接量出每个物块的 HSV 分布。

用途：为「重新标定 HSV 颜色窗口」提供**实测依据**，不靠猜。

用法：
    python _pi_tools/measure_tray_hsv.py [照片路径]

默认读 _snap/snap_tray.jpg。

输出：
    · 每个物块的 HSV 均值/范围
    · 按颜色聚合后的建议窗口（含 3σ 余量）

⚠️ 前提：照片必须是**开灯后**、相机 AE/AWB 已收敛时拍的。
"""
import sys
from pathlib import Path

import cv2
import numpy as np

PHOTO = sys.argv[1] if len(sys.argv) > 1 else str(
    Path(__file__).resolve().parent.parent / "_snap" / "snap_tray.jpg"
)

# 物块中心（按实拍照片目视定位，像素坐标，1280x720）
# 顺序：编号, 颜色, 形状, x, y
OBJECTS = [
    (1, "绿", "正方体 cube",           490, 150),
    (2, "蓝", "长方体 cuboid",          800, 200),
    (3, "蓝", "五棱柱 (侧放)",          730, 320),
    (4, "红", "四棱锥 square_pyramid",  490, 430),
    (5, "黄", "五棱柱 (正放)",          845, 450),
    (6, "黄", "长方体 cuboid",          600, 570),
    (7, "绿", "圆柱 cylinder",          765, 620),
]

# 采样半径（避开边缘/阴影/反光）
R = 18


def sample_hsv(img_hsv, x, y, r=R):
    """在 (x,y) 周围 r 像素的方形区域里取 HSV，返回统计。"""
    h, w = img_hsv.shape[:2]
    x0, x1 = max(0, x - r), min(w, x + r)
    y0, y1 = max(0, y - r), min(h, y + r)
    patch = img_hsv[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if patch.size == 0:
        return None
    Hn, S, V = patch[:, 0], patch[:, 1], patch[:, 2]
    # OpenCV 的 H 是 0..179；红色会跨 0，需要特殊处理
    return {
        "h_mean": float(Hn.mean()), "h_std": float(Hn.std()),
        "h_min": float(Hn.min()), "h_max": float(Hn.max()),
        "h_p5": float(np.percentile(Hn, 5)), "h_p95": float(np.percentile(Hn, 95)),
        "s_mean": float(S.mean()), "s_std": float(S.std()),
        "s_min": float(S.min()), "s_max": float(S.max()),
        "v_mean": float(V.mean()), "v_std": float(V.std()),
        "v_min": float(V.min()), "v_max": float(V.max()),
        "n": len(patch),
    }


def circular_h_range(h_p5, h_p95, h_mean):
    """处理红色跨 0/179 的情况：返回 (lo, hi) 可能跨零。"""
    # 如果 5% 分位比 95% 分位大很多，说明跨越了 0
    if h_p95 - h_p5 > 90:
        # 跨零：以均值为中心展开
        span = (h_p95 - h_p5) / 2.0
        return (h_mean + span) % 180, (h_mean - span) % 180
    return h_p5, h_p95


def main():
    p = Path(PHOTO)
    if not p.exists():
        print("❌ 照片不存在: %s" % p)
        return 1
    img = None
    # ⚠️ Windows 上 cv2.imread 读不了含中文的路径（项目根目录就叫「工创赛」）
    #    ⇒ 必须用 np.fromfile + imdecode 绕过
    try:
        buf = np.fromfile(str(p), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception as e:
        print("❌ 读图片异常: %s" % e)
        return 1
    if img is None:
        print("❌ 读不了图片: %s" % p)
        return 1
    h, w = img.shape[:2]
    print("=" * 88)
    print("照片: %s  (%dx%d)" % (p.name, w, h))
    print("=" * 88)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    print("\n%-3s %-4s %-24s %-14s %-22s %-22s" % (
        "#", "色", "形状", "中心", "H (0-179)", "S / V"))
    print("-" * 88)
    per = []
    for idx, color, shape, x, y in OBJECTS:
        st = sample_hsv(hsv, x, y)
        if st is None:
            print("  %d %s %-24s 采样失败" % (idx, color, shape))
            continue
        per.append((idx, color, shape, x, y, st))
        print("%-3d %-4s %-24s (%4d,%3d)  H %5.1f±%4.1f [%3.0f,%3.0f]  S %5.1f  V %5.1f" % (
            idx, color, shape, x, y,
            st["h_mean"], st["h_std"], st["h_p5"], st["h_p95"],
            st["s_mean"], st["v_mean"]))

    # 按颜色聚合，给建议窗口
    print("\n" + "=" * 88)
    print("按颜色聚合 → 建议 HSV 窗口（3σ + 余量，S/V 取实测外包）")
    print("=" * 88)
    by_color = {}
    for idx, color, shape, x, y, st in per:
        by_color.setdefault(color, []).append(st)

    for color in ("绿", "蓝", "红", "黄"):
        if color not in by_color:
            continue
        sts = by_color[color]
        hs = [s["h_mean"] for s in sts]
        h_lo = min(s["h_min"] for s in sts)
        h_hi = max(s["h_max"] for s in sts)
        s_lo = min(s["s_min"] for s in sts)
        s_hi = max(s["s_max"] for s in sts)
        v_lo = min(s["v_min"] for s in sts)
        v_hi = max(s["v_max"] for s in sts)
        n = len(sts)
        print("\n  【%s】%d 个样本" % (color, n))
        print("    实测 H: [%.0f, %.0f]  各点均值 %s" % (
            h_lo, h_hi, ", ".join("%.0f" % x for x in hs)))
        print("    实测 S: [%.0f, %.0f]" % (s_lo, s_hi))
        print("    实测 V: [%.0f, %.0f]" % (v_lo, v_hi))
        # 建议窗口：H 留 ±4，S/V 留余量
        rec_h_lo = max(0, h_lo - 4)
        rec_h_hi = min(179, h_hi + 4)
        rec_s_lo = max(0, s_lo - 25)
        rec_v_lo = max(0, v_lo - 25)
        print("    → 建议窗口: H [%.0f, %.0f]  S [%.0f, 255]  V [%.0f, 255]" % (
            rec_h_lo, rec_h_hi, rec_s_lo, rec_v_lo))
        print("      OpenCV 写法: ((%.0f, %.0f, %.0f), (%.0f, 255, 255))" % (
            rec_h_lo, rec_s_lo, rec_v_lo, rec_h_hi))

    # 现有窗口（从生产代码抄的），对比看看偏多少
    print("\n" + "=" * 88)
    print("对比：现有生产窗口 vs 实测")
    print("=" * 88)
    CURRENT = {
        "red": ((0, 95, 35), (2, 255, 255)),
        "orange": ((3, 95, 45), (23, 255, 255)),
        "yellow": ((24, 95, 45), (35, 255, 255)),
        "green": ((36, 95, 35), (84, 255, 255)),
        "cyan": ((85, 95, 35), (104, 255, 255)),
        "blue": ((105, 95, 30), (137, 255, 255)),
    }
    print("  现有窗口:")
    for k, (lo, hi) in CURRENT.items():
        print("    %-8s H [%3d, %3d]  S>=%3d  V>=%3d" % (
            k, lo[0], hi[0], lo[1], lo[2]))

    # 检查每个实测色落在哪些现有窗口
    print("\n  实测色 → 现有窗口覆盖情况:")
    cmap = {"绿": ("green",), "蓝": ("blue", "cyan"), "红": ("red", "orange"),
            "黄": ("yellow",)}
    for color in ("绿", "蓝", "红", "黄"):
        if color not in by_color:
            continue
        sts = by_color[color]
        h_lo = min(s["h_min"] for s in sts)
        h_hi = max(s["h_max"] for s in sts)
        s_lo = min(s["s_min"] for s in sts)
        v_lo = min(s["v_min"] for s in sts)
        hits = []
        for k, (lo, hi) in CURRENT.items():
            # H 区间有重叠、且 S/V 满足
            if not (h_hi < lo[0] or h_lo > hi[0]) and s_lo >= lo[1] and v_lo >= lo[2]:
                hits.append(k)
        print("    %s (H %.0f~%.0f, S>=%.0f, V>=%.0f) → %s" % (
            color, h_lo, h_hi, s_lo, v_lo,
            ("命中 " + "/".join(hits)) if hits else "❌ 无窗口命中（会完全漏检）"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
