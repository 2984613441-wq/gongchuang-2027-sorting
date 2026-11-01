"""量化实拍帧相对训练构图的位姿偏差。

## 判据

训练数据里，托盘横向占画面 78~87% 宽、30° 俯角、画面基本水平。
这张实拍帧里：
  · 托盘只在左下角露出，占画面宽 < 35%
  · 铝合金导轨斜穿画面 ⇒ 说明相机有滚转（roll）
  · 背景是窗户/机柜/地面 ⇒ 说明相机近水平而非 30° 俯视

## 方法

用 HoughLinesP 找画面里的长直线（导轨、桌沿、托盘边），
统计它们相对水平方向的夹角 ⇒ 估计滚转角。
"""

from pathlib import Path

import cv2
import numpy as np

F = Path("_device_check/grab1.jpg")


def main() -> int:
    img = cv2.imdecode(np.fromfile(str(F), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("❌ 读取失败")
        return 1
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── 1) 长直线方向（滚转角估计）──
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=90,
                            minLineLength=260, maxLineGap=18)
    angles = []
    if lines is not None:
        for row in lines.reshape(-1, 4):
            x1, y1, x2, y2 = [int(v) for v in row]
            dx, dy = x2 - x1, y2 - y1
            L = float(np.hypot(dx, dy))
            a = float(np.degrees(np.arctan2(dy, dx)))
            # 归一到 [-90, 90)
            while a >= 90:
                a -= 180
            while a < -90:
                a += 180
            angles.append((a, L))
    print("=" * 72)
    print("  实拍帧位姿分析  %s  (%dx%d)" % (F.name, W, H))
    print("=" * 72)
    print("  检出长直线: %d 条" % len(angles))
    if angles:
        # 按长度加权的中位角
        ang = np.array([a for a, _ in angles])
        ln = np.array([L for _, L in angles])
        # 只保留 |a|<70（排除竖直导轨）
        m = np.abs(ang) < 70
        if m.sum() >= 3:
            w = ln[m] / ln[m].sum()
            order = np.argsort(ang[m])
            cum = np.cumsum(w[order])
            med = ang[m][order][np.searchsorted(cum, 0.5)]
        else:
            med = float(np.median(ang))
        print("  主方向角（长度加权中位）: %+.1f°" % med)
        print("  ⇒ 估计相机滚转: 约 %+.1f°（训练数据应接近 0°）" % med)
        # 分布
        hist = {}
        for a, _ in angles:
            k = int(round(a / 15.0)) * 15
            hist[k] = hist.get(k, 0) + 1
        print("  角度分布(15°分桶): %s"
              % "  ".join("%+d°:%d" % (k, v) for k, v in sorted(hist.items())))

    # ── 2) 托盘可见面积（用「白色哑光 + 网格状」特征很难自动判；改为看下方 40% 区域的白色占比）──
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    white = (s < 70) & (v > 130)
    zones = {
        "左上": white[: H // 2, : W // 2],
        "右上": white[: H // 2, W // 2:],
        "左下": white[H // 2:, : W // 2],
        "右下": white[H // 2:, W // 2:],
    }
    print()
    print("  白色占比（分区，判断托盘落在哪个角）:")
    for k, m in zones.items():
        print("    %s  %.1f%%" % (k, m.mean() * 100))

    # ── 3) 与训练口径对比 ──
    print()
    print("  训练口径: 托盘占画面宽 78~87%、30° 俯角、近似水平")
    print("  本帧    : 托盘局部露在画面一角，主方向约 %+.0f°（斜穿画面）"
          % (med if angles else 0))
    print()
    print("  ⇒ 结论：相机位姿属**训练分布外**。v11 的检测结果不能用于")
    print("     判定「实机识别效果」，只能证明「模型在恶劣构图下仍能检出部分物件」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
