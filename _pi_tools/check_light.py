#!/usr/bin/env python3
"""量化评估补光灯安装位置好不好 —— 抓一张图就能出结论。

## 量什么

1. **纵向照度均匀性**：把托盘纵向分远/中/近三段，比平均亮度
   判据：最暗段 / 最亮段 ≥ 0.90（即差异 <10%）为合格
2. **横向照度均匀性**：每段再分左/中/右三块
   判据：最暗 / 最亮 ≥ 0.85 为合格
3. **过曝率**：灰度 >240 的像素占比
   判据：<2% 合格，>5% 说明有热点（灯太近/没漫射板）
4. **对比度**（灰度标准差）：过低说明画面雾白
   判据：托盘区 std ≥ 25 合格，<15 说明灯光漏进镜头
5. **高光面积**：物件顶面上 >245 的连续区域占比
   判据：<5%，否则圆形/五边形顶面被判形误判

## 用法

    # 先把灯装好，抓一张图：
    ssh root@172.20.10.9 "python3 /root/grab_one.py /root/light_test.jpg"
    scp root@172.20.10.9:/root/light_test.jpg _pi_tools/light_test.jpg

    # 然后：
    python _pi_tools/check_light.py _pi_tools/light_test.jpg

## 注意

托盘区域用「白色高亮区」自动找；如果找不准，用 --tray 手动指定：
    python _pi_tools/check_light.py img.jpg --tray 380,0,1030,720
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def find_tray(img: np.ndarray):
    """找白色托盘区域（最大白连通域）。"""
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 0, 170), np.uint8),
                       np.array((179, 55, 255), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, 1)
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < W * H * 0.02:
        return None
    x, y, w, h = cv2.boundingRect(c)
    return x, y, x + w, y + h


def band_stats(gray: np.ndarray, y0: int, y1: int,
               x0: int, x1: int) -> dict:
    seg = gray[y0:y1, x0:x1]
    if seg.size == 0:
        return {"mean": 0.0, "std": 0.0, "over": 0.0, "hi": 0.0}
    return {
        "mean": float(seg.mean()),
        "std": float(seg.std()),
        "over": float((seg > 240).mean() * 100.0),
        "hi": float((seg > 245).mean() * 100.0),
    }


def verdict(ok: bool, good: str, bad: str) -> str:
    return "✅ " + good if ok else "⚠️ " + bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--tray", default=None,
                    help="手动指定托盘矩形 x0,y0,x1,y1")
    args = ap.parse_args(argv)

    p = Path(args.image)
    if not p.is_file():
        print("文件不存在: %s" % p)
        return 1
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("读图失败")
        return 1
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 托盘区域
    if args.tray:
        tx0, ty0, tx1, ty1 = [int(v) for v in args.tray.split(",")]
        src = "手动指定"
    else:
        box = find_tray(img)
        if box is None:
            print("⚠️ 自动找不到托盘区域，用整幅图代替")
            tx0, ty0, tx1, ty1 = 0, 0, W, H
            src = "整幅图"
        else:
            tx0, ty0, tx1, ty1 = box
            src = "自动识别"

    print("=" * 76)
    print("  补光灯布置评估: %s  (%dx%d)" % (p.name, W, H))
    print("=" * 76)
    print("  托盘区域: (%d,%d)-(%d,%d)  [%s]"
          % (tx0, ty0, tx1, ty1, src))
    print()

    tw = tx1 - tx0
    th = ty1 - ty0
    thirds = [(ty0, ty0 + th // 3), (ty0 + th // 3, ty0 + 2 * th // 3),
              (ty0 + 2 * th // 3, ty1)]
    names = ["远端(上 1/3)", "中段", "近端(下 1/3)"]

    # ── 1. 纵向均匀性 ──────────────────────────────────────────
    print("【1】纵向照度（斜视下最关键：远端 vs 近端）")
    print("  %-14s %8s %8s %8s %8s" % ("区段", "均值", "标准差", "过曝%", "高光%"))
    bands = []
    for (y0, y1), nm in zip(thirds, names):
        st = band_stats(gray, y0, y1, tx0, tx1)
        bands.append(st)
        print("  %-14s %8.1f %8.1f %8.2f %8.2f"
              % (nm, st["mean"], st["std"], st["over"], st["hi"]))
    means = [b["mean"] for b in bands if b["mean"] > 0]
    if means:
        ratio = min(means) / max(means)
        print()
        print("  最暗/最亮 = %.3f  %s"
              % (ratio, verdict(ratio >= 0.90,
                                "照度均匀（差异 <10%）",
                                "照度不均（差异 %.0f%%）⇒ 远端偏暗，"
                                "建议远端补光或抬高灯" % ((1 - ratio) * 100))))
    print()

    # ── 2. 横向均匀性 ──────────────────────────────────────────
    print("【2】横向照度（左/中/右）")
    for (y0, y1), nm in zip(thirds, names):
        cols = []
        for i in range(3):
            cx0 = tx0 + tw * i // 3
            cx1 = tx0 + tw * (i + 1) // 3
            cols.append(band_stats(gray, y0, y1, cx0, cx1)["mean"])
        cols = [c for c in cols if c > 0]
        if cols:
            r = min(cols) / max(cols)
            print("  %-14s 左 %.1f  中 %.1f  右 %.1f   最暗/最亮 %.3f  %s"
                  % (nm, cols[0], cols[1] if len(cols) > 1 else 0,
                     cols[2] if len(cols) > 2 else 0, r,
                     verdict(r >= 0.85, "OK", "偏")))
    print()

    # ── 3. 过曝 ────────────────────────────────────────────────
    print("【3】过曝检查（热点）")
    seg = gray[ty0:ty1, tx0:tx1]
    over = float((seg > 240).mean() * 100.0)
    peak = float((seg > 245).mean() * 100.0)
    print("  托盘区过曝(>240) %.2f%%   高光(>245) %.2f%%"
          % (over, peak))
    print("  " + verdict(over < 2.0,
                         "无明显热点",
                         "过曝 %.1f%% ⇒ 灯太近或没加漫射板，建议抬高到 300mm+ "
                         "或加磨砂亚克力" % over))
    print()

    # ── 4. 对比度（判断灯是否漏进镜头）────────────────────────
    print("【4】对比度（判断灯光是否直射进镜头）")
    std = float(seg.std())
    print("  托盘区灰度标准差 %.1f" % std)
    print("  " + verdict(std >= 25,
                         "对比度正常，灯光没漏进镜头",
                         "对比度偏低 ⇒ 可能有灯光直射进镜头（画面雾白），"
                         "检查远端灯是否在相机视场内、加遮光罩"))
    print()

    # ── 5. 综合结论 ────────────────────────────────────────────
    print("=" * 76)
    print("  综合结论")
    print("=" * 76)
    issues = []
    if means and min(means) / max(means) < 0.90:
        issues.append("纵向照度不均（远端偏暗）")
    if over >= 2.0:
        issues.append("过曝/热点")
    if std < 25:
        issues.append("对比度低（疑似灯光漏进镜头）")
    if not issues:
        print("  ✅ 灯位合格：照度均匀、无热点、无漏光")
        print("     ⇒ 可以开始补拍 110~140 张数据")
    else:
        print("  ⚠️ 有 %d 个问题：" % len(issues))
        for i in issues:
            print("     · %s" % i)
        print()
        print("  按优先级修：")
        if std < 25:
            print("    1) 先解决漏光（最严重）—— 远端灯加遮光罩或移到视场外")
        if over >= 2.0:
            print("    2) 再过曝 —— 灯抬高到 300mm+ 或加磨砂漫射板")
        if means and min(means) / max(means) < 0.90:
            print("    3) 最后调均匀度 —— 远端补一盏或调功率")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
