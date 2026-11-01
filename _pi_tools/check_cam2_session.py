#!/usr/bin/env python3
"""副相机（DF200）采集会话质检（PC 侧）。

与 `check_capture_session.py`（主相机 30° 俯视用）不同：副相机是**斜侧视**，
"托盘占画面 78~87%" 那套判据不适用。这里只查与视角无关的质量项：

| 指标 | 判据 | 说明 |
|---|---|---|
| 张数 | 记录 vs 目标 110~140 | 少了要补 |
| 清晰度 laplacian | **记录 + 同会话内比较** | 主相机训练帧 115、副相机实测 55 ⇒ 跨设备不可比，只看同批是否明显更低 |
| 亮度均值 | 60 ~ 200 | <60 太暗 / >200 过曝 |
| 过曝(≥250)占比 | ≤ 5% | 灯 255 太亮时容易炸 |
| 与上一帧差异 | > 0.3% | 太小 ⇒ 没换布局（重复样本） |
| 分辨率 | 全部一致 | 混分辨率会毁训练 |
| JPEG 体积 | 记录 | 突变说明曝光/对焦变了 |

用法：
    python check_cam2_session.py <session_dir> [--limit N] [--quiet]
退出码：0 = 无异常；1 = 有异常项。
"""

from __future__ import annotations

import argparse
import glob
import os

import cv2
import numpy as np

SHARP_WARN_RATIO = 0.6     # 低于本会话中位数的 60% ⇒ 警告
BRIGHT_MIN, BRIGHT_MAX = 60.0, 200.0
OVER_MAX = 5.0
DIFF_MIN = 0.003


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.session, "*.jpg")))
    if not files:
        print("❌ 目录里没有 jpg：%s" % args.session)
        return 1
    if args.limit:
        files = files[:args.limit]

    rows = []
    prev = None
    print("=" * 92)
    print("副相机会话质检：%s  共 %d 张" % (os.path.basename(args.session), len(files)))
    print("=" * 92)
    if not args.quiet:
        print("%-6s %-11s %7s %7s %7s %8s  %s"
              % ("帧", "分辨率", "清晰度", "亮度", "过曝%", "与上帧%", "提示"))
    for i, p in enumerate(files):
        img = cv2.imread(p)
        if img is None:
            rows.append(dict(name=os.path.basename(p), bad=["读不出"]))
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
        mean = float(g.mean())
        over = float((g >= 250).mean() * 100)
        diff = 1.0 if prev is None else float((cv2.absdiff(g, prev) > 8).mean())
        size = os.path.getsize(p)
        tips = []
        if not (BRIGHT_MIN <= mean <= BRIGHT_MAX):
            tips.append("亮度%.0f" % mean)
        if over > OVER_MAX:
            tips.append("过曝")
        if prev is not None and diff < DIFF_MIN:
            tips.append("与上帧几乎相同")
        rows.append(dict(name=os.path.basename(p), h=img.shape[0], w=img.shape[1],
                         sharp=sharp, mean=mean, over=over, diff=diff, size=size, tips=tips))
        if not args.quiet:
            print("%-6d %-11s %7.0f %7.1f %7.2f %8.2f  %s"
                  % (i, "%dx%d" % (img.shape[1], img.shape[0]), sharp, mean, over,
                     diff * 100, " / ".join(tips)))
        prev = g

    sharp_med = float(np.median([r["sharp"] for r in rows if "sharp" in r])) if rows else 0.0
    sizes = {(r["w"], r["h"]) for r in rows if "w" in r}
    print("-" * 92)
    print("张数 %d｜分辨率种类 %d｜清晰度中位 %.0f｜亮度均 %.1f"
          % (len(rows), len(sizes), sharp_med,
             sum(r["mean"] for r in rows if "mean" in r) / max(1, len(rows))))
    if len(sizes) > 1:
        print("⚠️ 分辨率不一致：%s" % sorted(sizes))
    weak = [r for r in rows if "sharp" in r and r["sharp"] < sharp_med * SHARP_WARN_RATIO]
    if weak:
        print("⚠️ 明显偏糊的 %d 张：%s" % (len(weak),
                                       ", ".join(r["name"] for r in weak[:10])))
    flagged = [r for r in rows if r.get("tips")]
    if flagged:
        print("⚠️ 需注意 %d 张：" % len(flagged))
        for r in flagged[:20]:
            print("   %s  ←  %s" % (r["name"], " / ".join(r["tips"])))
    print("=" * 92)
    return 0 if not flagged and len(sizes) <= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
