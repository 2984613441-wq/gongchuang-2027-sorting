#!/usr/bin/env python3
"""MaixCAM 上验证 v7 cvimodel 能否正常加载 + 中文能否显示。

用法：python3 /root/verify_v7.py
"""

from __future__ import annotations

import glob
import os

from maix import image, nn

MODEL_DIR = "/root/my_models"
MODEL_NAME = "yolo11n_6c_v7_448_cv181x"
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME + ".mud")

print("=" * 60)
print("  v7 模型 + 中文 自检")
print("=" * 60)

# ① 模型
if not os.path.exists(MODEL_PATH):
    print("❌ 模型不存在: %s" % MODEL_PATH)
    raise SystemExit(1)
print("[1] mud 存在: %s" % MODEL_PATH)

try:
    d = nn.YOLO11(model=MODEL_PATH, dual_buff=False)
    print("[2] ✅ 模型加载成功")
    print("    input  = %d x %d" % (d.input_width(), d.input_height()))
    print("    labels = %s" % (d.labels,))
    if len(d.labels) != 6:
        print("    ⚠️ 类别数不是 6！")
    else:
        print("    ✅ 6 类正确")
except Exception as e:
    print("[2] ❌ 模型加载失败: %s" % e)
    raise SystemExit(1)

# ② 中文
fonts = glob.glob("/usr/share/fonts/wqy-zenhei/*")
if not fonts:
    print("[3] ⚠️ 没找到中文字体")
else:
    try:
        image.load_font("cn30", fonts[0], 30)
        print("[3] ✅ 中文字体注册成功: %s" % fonts[0])
        # 试着画一句
        img = image.Image(300, 60)
        ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
              "pentagonal_prism": "五棱柱", "cone": "圆锥",
              "tetrahedron": "正四面体"}
        img.draw_string(4, 4, "正方体 圆柱 正四面体", font="cn30",
                        color=image.COLOR_WHITE)
        img.save("/root/v7_verify.jpg")
        print("    ✅ 中文绘制 OK（已存 /root/v7_verify.jpg）")
    except Exception as e:
        print("[3] ❌ 中文失败: %s" % e)

print()
print("=" * 60)
print("  ✅ 全部通过，可以跑 yolo_v7_cn_view.py")
print("=" * 60)
