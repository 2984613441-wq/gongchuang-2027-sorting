#!/usr/bin/env python3
"""校验 /home/pi/images/ 下 1.png~30.png 是否齐全、合法、且与 manifest 对得上。

用法：python3 verify_screen_images.py
"""

import json
import sys
from pathlib import Path

IMG_DIR = Path("/home/pi/images")
MANIFEST = Path("/home/pi/电控/deploy/manifest.json")


def main() -> int:
    try:
        from PIL import Image
    except Exception as e:
        print("  没有 PIL: %s" % e)
        return 1

    print("=" * 60)
    print("  屏幕图片校验")
    print("=" * 60)
    print()

    # 1) 30 个文件齐全
    missing = []
    bad = []
    for i in range(1, 31):
        p = IMG_DIR / ("%d.png" % i)
        if not p.is_file():
            missing.append(i)
            continue
        try:
            im = Image.open(p)
            if im.size != (256, 256):
                bad.append((i, "size=%s" % (im.size,)))
            elif im.mode != "RGBA":
                bad.append((i, "mode=%s" % im.mode))
        except Exception as e:
            bad.append((i, "打不开: %s" % e))

    print("  文件齐全: %s" % ("✅ 30/30" if not missing else "❌ 缺 %s" % missing))
    print("  尺寸/格式: %s" % ("✅ 全部 256x256 RGBA" if not bad else "❌ %s" % bad))
    print()

    # 2) manifest 自洽
    if not MANIFEST.is_file():
        print("  manifest: ❌ 不存在 (%s)" % MANIFEST)
        return 1
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    entries = m.get("entries", [])
    print("  manifest entries: %d 条" % len(entries))

    ok_formula = True
    ids = []
    for e in entries:
        want = (e["shape_id"] - 1) * 5 + e["color_id"] + 1
        if e["image_id"] != want:
            ok_formula = False
            print("    ❌ image_id=%s 公式算应为 %s" % (e["image_id"], want))
        if e["file"] != "%d.png" % e["image_id"]:
            ok_formula = False
            print("    ❌ file=%s 与 image_id=%s 不符" % (e["file"], e["image_id"]))
        ids.append(e["image_id"])
    print("  公式自洽: %s" % ("✅" if ok_formula else "❌"))
    print("  image_id 覆盖 1~30: %s" % ("✅" if sorted(ids) == list(range(1, 31)) else "❌"))
    print()

    # 3) 打印一张对照表
    print("  image_id → 形状 / 颜色")
    print("  " + "-" * 44)
    for e in entries:
        print("    %2d  %-6s %-4s  (%s %s)" % (
            e["image_id"], e["shape_zh"], e["color_zh"],
            e["shape"], e["color"]))
    print()

    ok = (not missing) and (not bad) and ok_formula and sorted(ids) == list(range(1, 31))
    print("  总判定: %s" % ("✅ 全部通过" if ok else "❌ 有问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
