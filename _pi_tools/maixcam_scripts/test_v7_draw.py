#!/usr/bin/env python3
"""离线验证 v7 + 中文绘制：读一张已存图，跑检测，画中文框，存结果。

不需要相机，不会和 MaixVision 抢资源。
用来在真正跑 yolo_v7_cn_view.py 之前确认「检测 + 中文 + 框」都对。

用法：
    python3 /root/test_v7_draw.py /root/dataset_tilt30/tilt30_20261027-155244/img_00010.jpg
"""

from __future__ import annotations

import glob
import os
import sys

import cv2
import numpy as np

from maix import image, nn

MODEL_PATH = "/root/my_models/yolo11n_6c_v7_448_cv181x.mud"
CN_FONT_NAME = "cn34"
CN_FONT_SIZE = 34

LABELS = ["cube", "cuboid", "cylinder",
          "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}
CLS_RGB = {
    0: (60, 235, 60), 1: (60, 200, 255), 2: (80, 80, 255),
    3: (235, 80, 235), 4: (255, 210, 40), 5: (40, 255, 255),
}


def _mc(name: str):
    return getattr(image, name, getattr(image, "COLOR_WHITE"))


CLS_MAIX = {
    0: _mc("COLOR_GREEN"), 1: _mc("COLOR_ORANGE"), 2: _mc("COLOR_RED"),
    3: _mc("COLOR_PURPLE"), 4: _mc("COLOR_BLUE"), 5: _mc("COLOR_YELLOW"),
}

CONF_TH = float(os.environ.get("CONF_TH", "0.25"))


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src or not os.path.exists(src):
        # 自动找一张
        cands = sorted(glob.glob(
            "/root/dataset_tilt30/*/img_*.jpg"))[:1]
        if not cands:
            print("❌ 没给图片且找不到默认图")
            return 1
        src = cands[0]
    print("输入图: %s" % src)

    # 字体
    fonts = glob.glob("/usr/share/fonts/wqy-zenhei/*")
    if fonts:
        image.load_font(CN_FONT_NAME, fonts[0], CN_FONT_SIZE)
        print("字体: %s" % fonts[0])
    else:
        print("⚠️ 无中文字体")

    # 模型
    d = nn.YOLO11(model=MODEL_PATH, dual_buff=False)
    print("模型: input %dx%d, labels %s"
          % (d.input_width(), d.input_height(), d.labels))

    # 读图
    img = image.load(src)
    print("图: %dx%d" % (img.width(), img.height()))

    # 检测
    objs = d.detect(img, conf_th=CONF_TH, iou_th=0.45)
    print("检出: %d 个" % len(objs))
    for o in objs:
        c = int(o.class_id)
        print("  %s %.2f  (%d,%d,%d,%d)"
              % (LABELS[c], float(o.score), int(o.x), int(o.y),
                 int(o.w), int(o.h)))

    # 画框（cv2，走 numpy 视图）
    rgb = image.image2cv(img, ensure_bgr=False, copy=False)
    th = max(2, 4)
    for o in objs:
        c = int(o.class_id)
        x, y, w, h = int(o.x), int(o.y), int(o.w), int(o.h)
        cv2.rectangle(rgb, (x, y), (x + w, y + h),
                      CLS_RGB.get(c, (255, 255, 255)), th)
    del rgb

    # 画中文（maix draw_string）
    for o in objs:
        c = int(o.class_id)
        x, y = int(o.x), int(o.y)
        zh = ZH.get(LABELS[c], LABELS[c])
        text = "%s %.2f" % (zh, float(o.score))
        tw = sum(CN_FONT_SIZE if ord(ch) > 127 else CN_FONT_SIZE // 2
                 for ch in text)
        thh = CN_FONT_SIZE + 6
        ty = max(0, y - thh - 4)
        try:
            img.draw_rect(x, ty, tw + 6, thh,
                          color=_mc("COLOR_BLACK"), thickness=-1)
        except Exception as e:
            print("  底衬失败: %s" % e)
        try:
            img.draw_string(x + 3, ty + 2, text, font=CN_FONT_NAME,
                            color=CLS_MAIX.get(c, _mc("COLOR_WHITE")),
                            scale=1.0)
        except Exception as e:
            print("  中文失败: %s" % e)

    out = "/root/v7_draw_test.jpg"
    img.save(out)
    print("✅ 已存: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
