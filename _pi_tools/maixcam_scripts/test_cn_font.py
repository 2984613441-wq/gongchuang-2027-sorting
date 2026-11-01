#!/usr/bin/env python3
"""测 MaixCAM 上中文能否正常渲染（文泉驿正黑）。

## API 用法（连踩两坑，记下来）

    image.load_font(name: str, path: str, size: int = 16) -> Err
        · 第 1 个参数是**自己起的名字**，第 2 个才是字体路径
        · 返回的是状态码，不是字体对象
        · 作用是把这个字体**注册到 name 下**

    Image.draw_string(x, y, textstring, color=..., scale=1, thickness=-1,
                      wrap=True, wrap_space=4, font: str = '')
        · **font 参数是字符串**（load_font 注册的名字），不是对象！

  ⚠️ 我第一次传 font=<Err 对象> 报 incompatible function arguments。

## 用法

    python3 /root/test_cn_font.py /root/cn_test.jpg
"""

from __future__ import annotations

import glob
import sys

from maix import image

OUT = sys.argv[1] if len(sys.argv) > 1 else "/root/cn_test.jpg"

# 找中文字体
CANDS = glob.glob("/usr/share/fonts/wqy-zenhei/*")
if not CANDS:
    for pat in ("/usr/share/fonts/**/*.ttc", "/usr/share/fonts/**/*.ttf"):
        CANDS += glob.glob(pat, recursive=True)
    CANDS = [c for c in CANDS
             if any(k in c.lower() for k in ("wqy", "zenhei", "noto", "cjk"))]
print("候选中文字体: %s" % (CANDS[:3] if CANDS else "无"))
if not CANDS:
    print("❌ 没找到中文字体")
    sys.exit(1)

font_path = CANDS[0]
print("使用: %s" % font_path)

# 注册三个字号（名字自己定）
registered = {}
for size in (18, 22, 26, 30):
    name = "cn%d" % size
    try:
        image.load_font(name, font_path, size)
        registered[size] = name
        print("  load_font('%s', ..., %d) OK" % (name, size))
    except Exception as e:
        print("  load_font size=%d 失败: %s" % (size, e))

if not registered:
    print("❌ 字体注册全部失败")
    sys.exit(1)

# 画中文（font 传名字字符串）
img = image.Image(360, 260)
lines = [
    ("正方体 长方体", registered.get(22), image.COLOR_WHITE),
    ("圆柱 五棱柱",   registered.get(22), image.COLOR_GREEN),
    ("圆锥 正四面体", registered.get(22), image.COLOR_YELLOW),
    ("conf 0.86",     registered.get(18), image.COLOR_RED),
]
y = 4
ok = 0
for text, fname, col in lines:
    if not fname:
        continue
    try:
        img.draw_string(4, y, text, font=fname, color=col, scale=1.0)
        ok += 1
        print("  ✅ draw_string('%s', font='%s')" % (text, fname))
    except Exception as e:
        print("  ❌ draw_string('%s') 失败: %s" % (text, e))
    y += 48

if ok == 0:
    print("❌ 一句都没画成")
    sys.exit(1)

img.save(OUT)
print("✅ 已保存: %s（%d 行中文）" % (OUT, ok))
