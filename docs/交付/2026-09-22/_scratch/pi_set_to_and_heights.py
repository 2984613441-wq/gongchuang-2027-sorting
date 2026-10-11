# -*- coding: utf-8 -*-
"""两件事一起做（2026-09-22）：
  ① [ObjectHeights] 写回实测件高（正方体 40 / 三棱柱 32.5 / 圆柱 30）
  ② [ToolOffset] y_mm 由 -20.5 改成 -30.5
     —— 用户说明：标定当时【人工把 Y 向 +1cm 干涉过】⇒ 算出的坐标整体多偏 +1cm
        ⇒ 修正 = 每个 PICK 整体向 Y 负 10mm。

安全：备份 → 精确替换（只动这两处）→ 回读校验（值正确、其它节与其它键未动）。
"""
import hashlib
import re
import shutil
import sys
import time

CFG = "/home/pi/电控/calibration_config.ini"
HEIGHTS = {1: 40.0, 2: 40.0, 3: 32.5, 4: 32.5, 5: 30.0, 6: 30.0}
NEW_TO_Y = -30.5


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    with open(CFG, encoding="utf-8", newline="") as fh:
        text = fh.read()
    orig = text

    # ① 件高
    m = re.search(r"(?ms)^\[ObjectHeights\][^\n]*\n(.*?)(?=^\[|\Z)", text)
    if not m:
        print("拒绝：无 [ObjectHeights]")
        return 2
    body = m.group(1)
    new_body = body
    for k, v in HEIGHTS.items():
        pat = re.compile(r"(?m)^(\s*%d\s*=\s*)([-+0-9.eE]+)(\s*(?:#.*)?)$" % k)
        if not pat.search(new_body):
            print("拒绝：段内找不到键 %d" % k)
            return 2
        new_body = pat.sub(lambda mm: "%s%.1f%s" % (mm.group(1), v, mm.group(3)), new_body, count=1)
    text = text[: m.start(1)] + new_body + text[m.end(1):]

    # ② ToolOffset y_mm
    before_y = re.search(r"(?m)^\s*y_mm\s*=\s*([-+0-9.eE]+)", text)
    if not before_y:
        print("拒绝：找不到 y_mm")
        return 2
    text = re.sub(r"(?m)^(\s*y_mm\s*=\s*)([-+0-9.eE]+)",
                  lambda mm: "%s%.1f" % (mm.group(1), NEW_TO_Y), text, count=1)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-before-to-30p5-%s" % (CFG, stamp)
    shutil.copy2(CFG, bak)
    print("备份 -> %s" % bak)
    before = sha(CFG)
    with open(CFG, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

    # 回读
    with open(CFG, encoding="utf-8", newline="") as fh:
        back = fh.read()
    ok = True
    m2 = re.search(r"(?ms)^\[ObjectHeights\][^\n]*\n(.*?)(?=^\[|\Z)", back)
    for k, v in HEIGHTS.items():
        mm = re.search(r"(?m)^\s*%d\s*=\s*([-+0-9.eE]+)" % k, m2.group(1))
        got = float(mm.group(1)) if mm else None
        if got != v:
            ok = False
            print("❌ 件高 %d = %s（期望 %s）" % (k, got, v))
    y = re.search(r"(?m)^\s*y_mm\s*=\s*([-+0-9.eE]+)", back)
    if not y or float(y.group(1)) != NEW_TO_Y:
        ok = False
        print("❌ y_mm = %s（期望 %s）" % (y.group(1) if y else None, NEW_TO_Y))
    x = re.search(r"(?m)^\s*x_mm\s*=\s*([-+0-9.eE]+)", back)
    if not x or float(x.group(1)) != -108.5:
        ok = False
        print("❌ x_mm 被动了：%s" % (x.group(1) if x else None))
    if back.count("[") != orig.count("["):
        ok = False
        print("❌ 节数变了")
    print("sha256 %s -> %s" % (before[:16], sha(CFG)[:16]))
    print("✅ 两项都写入并通过回读校验" if ok else "❌ 校验失败，请用备份回退")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
