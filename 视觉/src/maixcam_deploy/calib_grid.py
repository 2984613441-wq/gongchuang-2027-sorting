"""
MaixCAM 标定辅助 —— 直接在 MaixVision 里跑。

它做两件事：
  1. 在预览画面上画【带坐标标签的网格】，你可以直接读出任何东西的像素坐标；
  2. 自动找出画面里最大的那个【纯色块】，画十字准星并打印它的中心像素。

━━━ 怎么用它做标定（全程不用拍照、不用鼠标）━━━━━━━━━━━━━━━━━━
  1. 在【夹爪】上贴一小块纯色胶带（颜色挑下面 TARGET_COLOR 里有的，
     比如绿色/红色/蓝色），保证这块颜色在托盘背景上能干净地分离出来。
  2. 跑这个脚本，先确认屏幕上十字准星稳稳跟住了夹爪上那块胶带。
  3. 用 MOVE 命令把夹爪依次停到 3 个位置，每停一次读一次控制台打印的 CALIB 行：
          MOVE X DIR0 STEPS 4800 HZ 1000      # X +60mm（60mm x 80步/mm = 4800）
          MOVE Y ...                          # Y +60mm
     建议三点： (0,0) → (+60,0) → (0,+60)
  4. 把三行抄成  u v x y  的格式，喂给电脑上的 工具/calib_affine.py

  提示：如果夹爪不好贴胶带，也可以放一个纯色小物体在工作台上，
        但那样你只知道它的像素、不知道它的毫米 —— 得靠夹爪去对准它。

━━━ 为什么要有网格 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  自动找色块是为了「准」，网格是为了「能人工核对」。
  两个都看得到，出问题时你一眼就知道是检测飘了还是坐标读错了。
"""

import time

import cv2
import numpy as np
from maix import app, camera, display, image

# ==================== 配置 ====================
FRAME = 320            # MaixCAM 实际输出帧；链路里的 (u,v) 就是这个尺寸下的
GRID_STEP = 32         # 网格间距（像素）
TARGET_COLOR = "green"  # 追踪哪种颜色：red/orange/yellow/green/cyan/blue/black
PRINT_INTERVAL = 0.5   # 秒；控制台打印间隔（别设太小，会刷屏）

# HSV 阈值沿用 V6（H=0..179, S/V=0..255）。现场光线不同可能要微调。
COLOR_RANGES = {
    "red": [((0, 95, 35), (2, 255, 255)), ((173, 95, 35), (179, 255, 255))],
    "orange": [((3, 95, 45), (23, 255, 255))],
    "yellow": [((24, 95, 45), (35, 255, 255))],
    "green": [((36, 95, 35), (84, 255, 255))],
    "cyan": [((85, 95, 35), (104, 255, 255))],
    "blue": [((105, 95, 30), (137, 255, 255))],
    "black": [((0, 0, 0), (179, 150, 50))],
}

MIN_AREA = 40          # 小于这个面积认为是噪声

# 画在 RGB 图上，所以颜色是 (R, G, B)
GRID_COLOR = (60, 70, 90)
GRID_MAJOR = (110, 130, 170)
TEXT_COLOR = (255, 210, 60)
CROSS_COLOR = (255, 40, 80)


def find_marker(rgb):
    """返回最大色块的 (u, v, area)；找不到返回 None。"""

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = None
    for lo, hi in COLOR_RANGES[TARGET_COLOR]:
        part = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        mask = part if mask is None else cv2.bitwise_or(mask, part)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(biggest)
    if area < MIN_AREA:
        return None
    m = cv2.moments(biggest)
    if m["m00"] <= 0:
        return None
    return (m["m10"] / m["m00"], m["m01"] / m["m00"], area)


def draw_grid(rgb):
    h, w = rgb.shape[:2]
    for x in range(0, w, GRID_STEP):
        major = (x % (GRID_STEP * 2) == 0)
        cv2.line(rgb, (x, 0), (x, h), GRID_MAJOR if major else GRID_COLOR, 1)
        if major:
            cv2.putText(rgb, str(x), (x + 2, 12),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, TEXT_COLOR, 1)
    for y in range(0, h, GRID_STEP):
        major = (y % (GRID_STEP * 2) == 0)
        cv2.line(rgb, (0, y), (w, y), GRID_MAJOR if major else GRID_COLOR, 1)
        if major:
            cv2.putText(rgb, str(y), (2, y + 12),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, TEXT_COLOR, 1)
    # 画面正中画个白框，方便和网格对齐
    c = w // 2
    cv2.rectangle(rgb, (c - 2, c - 2), (c + 2, c + 2), (255, 255, 255), 1)


def main():
    print("=" * 60)
    print("标定辅助：网格 + 色块追踪")
    print("  帧尺寸 = %dx%d，追踪颜色 = %s" % (FRAME, FRAME, TARGET_COLOR))
    print("  把夹爪上的纯色块对准屏幕里的十字，用 MOVE 命令停到 3 个已知位置，")
    print("  每次抄下 CALIB 行。")
    print("=" * 60)

    cam = camera.Camera(FRAME, FRAME, image.Format.FMT_RGB888)
    disp = display.Display()
    last_print = 0.0

    while not app.need_exit():
        frame = cam.read()
        if frame is None:
            continue
        # RGB 共享视图：绘制直接写进 frame，随后原样显示（V6 同款做法）
        rgb = image.image2cv(frame, ensure_bgr=False, copy=False)

        marker = find_marker(rgb)
        draw_grid(rgb)
        if marker is not None:
            u, v, area = marker
            ui, vi = int(round(u)), int(round(v))
            cv2.drawMarker(rgb, (ui, vi), CROSS_COLOR, cv2.MARKER_CROSS, 24, 2)
            cv2.putText(rgb, "%d,%d" % (ui, vi), (ui + 14, vi - 10),
                        cv2.FONT_HERSHEY_PLAIN, 1.1, CROSS_COLOR, 1)

        disp.show(frame)

        now = time.monotonic()
        if now - last_print >= PRINT_INTERVAL:
            last_print = now
            if marker is None:
                print("CALIB 没找到 %s 色块（面积下限 %d）—— 靠近点/换颜色/调阈值"
                      % (TARGET_COLOR, MIN_AREA))
            else:
                u, v, area = marker
                print("CALIB u=%d v=%d  (面积 %d)" % (int(round(u)), int(round(v)), int(area)))

        del rgb


if __name__ == "__main__":
    main()
