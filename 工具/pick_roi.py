#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在截图上框一个 ROI（矩形），输出 `roi = x,y,w,h`（像素）。

用途：标定 `[BarrierCheck] roi`（挡板区域）、`[PlaceEye] roi`（落料位）等。
在 **PC 上**跑（需要 OpenCV 的 GUI 窗口），图片可以是从设备抓回来的快照。

━━━ 用法 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # 交互框选：鼠标左键按下→拖→松开，按 c 确认、r 重画、q 退出
  python 工具/pick_roi.py 抓图.jpg

  # 只检查一个已有 ROI 是否合理（会画出框，按 c 关闭）
  python 工具/pick_roi.py 抓图.jpg --roi 820,120,300,180
  python 工具/pick_roi.py 抓图.jpg --roi 820,120,300,180 --out /tmp/roi_check.png

注意：坐标是【图像像素】，与设备端 1280x720 的原始分辨率一致。
     若图片是缩放后的，请用原图，或用 --scale 说明缩放比。
"""

from __future__ import annotations

import argparse
import sys

import cv2


class Picker:
    def __init__(self, img, win: str, preset=None):
        self.img = img
        self.win = win
        self.start = None
        self.cur = None
        self.done = False
        self.roi = preset
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(win, self._on_mouse)

    def _on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start = (x, y)
            self.cur = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.start is not None:
            self.cur = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.start is not None:
            x0, y0 = self.start
            x1, y1 = x, y
            x, y = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0), abs(y1 - y0)
            self.roi = (x, y, w, h)
            self.done = True
            self.start = None

    def run(self):
        while True:
            vis = self.img.copy()
            if self.roi:
                x, y, w, h = self.roi
                cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(vis, "roi = %d,%d,%d,%d" % (x, y, w, h),
                            (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 255), 2)
            if self.start and self.cur:
                cv2.rectangle(vis, self.start, self.cur, (0, 255, 0), 1)
            cv2.imshow(self.win, vis)
            k = cv2.waitKey(20) & 0xFF
            if k in (ord("q"), 27):
                return None
            if k == ord("r"):
                self.roi = None
                self.start = self.cur = None
            if k in (ord("c"), 13) and self.roi:
                return self.roi
            if self.done:
                self.done = False
                # 拖完立即显示结果，等 c 确认


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="在截图上框 ROI，输出 roi = x,y,w,h")
    ap.add_argument("image", help="图片路径（建议用设备原始分辨率快照）")
    ap.add_argument("--roi", help="已有 ROI：x,y,w,h（只检查/画出来）")
    ap.add_argument("--out", help="把带框的图另存到该路径")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="若图片被缩放过，给缩放比（输出会换算回原图坐标）")
    ap.add_argument("--dry-run", action="store_true", help="不弹窗，只校验参数与图片")
    args = ap.parse_args(argv)

    img = cv2.imread(args.image)
    if img is None:
        sys.stderr.write("读不到图片：%s\n" % args.image)
        return 1
    h, w = img.shape[:2]
    print("图片 %dx%d" % (w, h))

    preset = None
    if args.roi:
        parts = [int(round(float(v.strip()))) for v in args.roi.split(",")]
        if len(parts) != 4:
            sys.stderr.write("--roi 格式应为 x,y,w,h\n")
            return 4
        preset = tuple(parts)

    if args.dry_run:
        print("dry-run：图片可读；窗口未打开。给 --roi 时不弹窗也能看坐标。")
        if preset:
            print("roi = %d,%d,%d,%d" % preset)
        return 0

    picker = Picker(img, "pick_roi", preset)
    roi = picker.run()
    cv2.destroyAllWindows()
    if roi is None:
        print("已取消")
        return 5

    x, y, w_, h_ = [int(round(v / args.scale)) for v in roi]
    print("roi = %d,%d,%d,%d" % (x, y, w_, h_))

    vis = img.copy()
    cv2.rectangle(vis, (x, y), (x + w_, y + h_), (0, 0, 255), 2)
    if args.out:
        cv2.imwrite(args.out, vis)
        print("已保存带框图：%s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
