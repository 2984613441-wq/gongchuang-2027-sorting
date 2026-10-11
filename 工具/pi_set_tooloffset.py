# -*- coding: utf-8 -*-
"""把 [ToolOffset] y_mm 改成指定值 —— 断言式，**只动那一行**，其余逐字节保留。

为什么不用 configparser 回写：configparser **读不出注释**，write() 会把整份配置的
注释全部抹掉。这份配置有 100+ 行注释承载着标定依据，抹掉就等于毁掉证据链。
（同一个坑项目里踩过：`pi_set_droppoint3.py` 原实现会抹注释，已修。）

用法：python3 pi_set_tooloffset.py <新的 y_mm>
      改前自动备份，改后打印 diff 摘要 + sha256 + 回读验证。
"""
import hashlib
import os
import re
import shutil
import sys
import time

CFG = "/home/pi/电控/calibration_config.ini"
SECTION = "ToolOffset"
KEY = "y_mm"


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main(argv):
    global KEY
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    if len(argv) == 3:
        # 2026-09-21 扩展：可选第二参数指定要改哪个键（x_mm / y_mm）。
        # 不传 ⇒ 仍是 y_mm，与旧调用完全等价（向后兼容）。
        KEY = argv[2]
        if KEY not in ("x_mm", "y_mm"):
            print("拒绝：只接受 x_mm / y_mm，收到 %r" % KEY)
            return 2
    new_val = argv[1]
    try:
        float(new_val)
    except ValueError:
        print("拒绝：%r 不是数字" % new_val)
        return 2

    # newline="" 必须加：默认的换行转换会把文件里的 CRLF 读成 LF、再写回 LF，
    # 于是"只改一行"变成"整个文件的行尾全变了" —— 与"逐字节保留"的承诺不符。
    with open(CFG, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")

    # 定位 [ToolOffset] 节范围
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\[%s\]\s*$" % re.escape(SECTION), ln):
            start = i
            break
    if start is None:
        print("拒绝：找不到 [%s] 节" % SECTION)
        return 2
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*\[.+\]\s*$", lines[j]):
            end = j
            break

    # 在该节内找 KEY=...，必须恰好一行
    hits = [k for k in range(start + 1, end)
            if re.match(r"^\s*%s\s*=" % re.escape(KEY), lines[k])]
    if len(hits) != 1:
        print("拒绝：[%s] 节内 %s= 命中 %d 行（要求恰好 1 行）"
              % (SECTION, KEY, len(hits)))
        return 2
    idx = hits[0]
    old_line = lines[idx]
    m = re.match(r"^(\s*%s\s*=\s*)(\S+)(\s*)$" % re.escape(KEY), old_line)
    if not m:
        print("拒绝：这行格式不认识：%r" % old_line)
        return 2
    old_val = m.group(2)
    if float(old_val) == float(new_val):
        print("无需改动：已经是 %s" % old_val)
        return 0

    lines[idx] = "%s%s%s" % (m.group(1), new_val, m.group(3))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-to-%s-%s" % (CFG, new_val.replace("-", "m").replace(".", "p"), stamp)
    shutil.copy2(CFG, bak)
    print("备份 -> %s" % bak)

    before = sha(CFG)
    with open(CFG, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines))
    after = sha(CFG)

    # 回读验证：只有那一行变了，且值就是新值
    with open(CFG, encoding="utf-8", newline="") as fh:
        back = fh.read().split("\n")
    assert len(back) == len(lines), "行数变了！"
    diff = [k for k in range(len(lines)) if back[k] != lines[k]]
    print("改动了 %d 行（应为 0 —— 我们是先改内存再整体写，这里只做个一致性检查）"
          % len(diff))
    with open(CFG, encoding="utf-8") as fh:
        txt = fh.read()
    got = re.search(r"^\s*%s\s*=\s*(\S+)\s*$" % re.escape(KEY), txt, re.M).group(1)
    assert float(got) == float(new_val), "回读值不对：%s" % got
    print("[%s] %s : %s -> %s   ✅ 回读一致" % (SECTION, KEY, old_val, got))
    print("sha256 %s -> %s" % (before[:16], after[:16]))
    print("注释行数 = %d（应与改前相同）" % sum(1 for l in lines if l.lstrip().startswith("#")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
