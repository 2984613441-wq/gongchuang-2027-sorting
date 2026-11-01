"""检查 _device_check/ 里的实拍帧，并量化相机位姿偏差。"""

from pathlib import Path
import cv2
import numpy as np

D = Path("_device_check")

print("=" * 70)
print("  实拍帧检查")
print("=" * 70)
for f in sorted(D.glob("*.jpg")):
    img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("  %-24s 读取失败" % f.name)
        continue
    h, w = img.shape[:2]
    mean = [int(v) for v in img.reshape(-1, 3).mean(axis=0)]
    print("  %-24s %dx%d  BGR均值=%s" % (f.name, w, h, mean))

print()
print("=" * 70)
print("  量化：原始帧里「白色托盘」占比 vs 训练口径（78~87% 宽）")
print("=" * 70)

for name in ("grab1.jpg", "grab1_rot90ccw.jpg", "grab1_rot90cw.jpg"):
    f = D / name
    if not f.exists():
        continue
    img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        continue
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    # 近白（托盘是白色哑光塑料）
    white = ((s < 60) & (v > 150)).astype(np.uint8) * 255
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ratio = white.mean() / 255.0
    print("  %-24s 白色像素占比 %.1f%%" % (name, ratio * 100))
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        x, y, w2, h2 = cv2.boundingRect(c)
        print("        最大白色连通块 bbox=(%d,%d)-(%d,%d)  占画面 %.1f%% × %.1f%%"
              % (x, y, x + w2, y + h2, w2 * 100.0 / img.shape[1],
                 h2 * 100.0 / img.shape[0]))
