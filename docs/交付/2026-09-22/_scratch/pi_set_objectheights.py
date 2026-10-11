# -*- coding: utf-8 -*-
"""把实测件高写进 Pi 的 [ObjectHeights]（2026-09-22）。

为什么重要：pixel_to_device.py:405 `if h > 0.0:` —— 现行六类全 0 ⇒ 视差补偿【被关掉】。
第三方复算（C1）：只把这一项打开（h=40），画面里"软件系越界"面积就从 28.38% 掉到 17.42%
⇒ 那是可证明的 10.95 个百分点（38.6%）的【假拒识】。

实测值（用户 2026-09-22 现场用尺量）：
  正方体(1,2) = 40mm ；圆柱(5,6) = 30mm
  三棱柱(3,4) = 矩形朝向 35mm / 三角朝向 30mm ⇒ 取中值 32.5（h 误差 ±2.5mm ⇒ 位置误差 ≈0.5mm，可忽略）

安全措施：备份 → 原地替换 [ObjectHeights] 段内的 N = x 行 → 回读校验（键齐全、值正确、其它节未动）。
"""
import hashlib
import re
import shutil
import sys
import time

CFG = "/home/pi/电控/calibration_config.ini"
WANT = {1: 40.0, 2: 40.0, 3: 32.5, 4: 32.5, 5: 30.0, 6: 30.0}


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    with open(CFG, encoding="utf-8", newline="") as fh:
        text = fh.read()

    # 定位 [ObjectHeights] 段（到下一个 [ 或文件尾）
    m = re.search(r"(?ms)^\[ObjectHeights\][^\n]*\n(.*?)(?=^\[|\Z)", text)
    if not m:
        print("拒绝：[ObjectHeights] 段不存在。未写入。")
        return 2
    body = m.group(1)
    print("=== 改前 ===")
    for ln in body.splitlines():
        if ln.strip():
            print("   " + ln.rstrip())

    new_body = body
    changed = 0
    for k, v in WANT.items():
        # 只替换该段内 `k = ...` 的行（保留行尾注释）
        pat = re.compile(r"(?m)^(\s*%d\s*=\s*)([-+0-9.eE]+)(\s*(?:#.*)?)$" % k)
        if not pat.search(new_body):
            print("拒绝：段内找不到键 %d = ...。未写入。" % k)
            return 2
        new_body, n = pat.subn(lambda mm: "%s%.1f%s" % (mm.group(1), v, mm.group(3)), new_body)
        changed += n
    print("=== 改后 ===")
    for ln in new_body.splitlines():
        if ln.strip():
            print("   " + ln.rstrip())

    if changed != len(WANT):
        print("拒绝：替换了 %d 行，期望 %d 行。未写入。" % (changed, len(WANT)))
        return 2

    before = sha(CFG)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-before-objheights-%s" % (CFG, stamp)
    shutil.copy2(CFG, bak)
    print("备份 -> %s" % bak)

    new_text = text[: m.start(1)] + new_body + text[m.end(1):]
    with open(CFG, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)

    # 回读校验
    with open(CFG, encoding="utf-8", newline="") as fh:
        back = fh.read()
    m2 = re.search(r"(?ms)^\[ObjectHeights\][^\n]*\n(.*?)(?=^\[|\Z)", back)
    ok = True
    for k, v in WANT.items():
        mm = re.search(r"(?m)^\s*%d\s*=\s*([-+0-9.eE]+)" % k, m2.group(1))
        got = float(mm.group(1)) if mm else None
        if got != v:
            ok = False
            print("❌ 回读不符：%d = %s（期望 %s）" % (k, got, v))
    # 其它节未动
    if back.count("[") != text.count("["):
        ok = False
        print("❌ 节数变了：%d -> %d" % (text.count("["), back.count("[")))
    print("sha256 %s -> %s" % (before[:16], sha(CFG)[:16]))
    print("✅ 回读校验通过：六类件高已写入" if ok else "❌ 校验失败，请用备份回退")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
