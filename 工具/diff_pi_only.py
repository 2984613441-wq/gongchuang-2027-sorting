# -*- coding: utf-8 -*-
"""打印两个文件 diff 中**含删除行**的 hunk（带少量上下文）。

用途：合并 run_chain.py 前，先把「Pi 独有、repo 没有」的那些行列清楚。
方向：git diff A B ⇒ '-' 行 = 只在 A 里（Pi 独有）；'+' 行 = 只在 B 里（repo 独有）。
"""
import subprocess
import sys

A, B = sys.argv[1], sys.argv[2]
CTX = int(sys.argv[3]) if len(sys.argv) > 3 else 3

out = subprocess.run(["git", "diff", "--no-index", "-U%d" % CTX, "--", A, B],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace").stdout

# ⚠️ 直接 print 中文会在 Windows GBK 控制台上乱码/崩溃（U+21D2 之类直接 UnicodeEncodeError）。
#    所以一律写 UTF-8 文件，再由 read 工具看。
OUTP = sys.argv[4] if len(sys.argv) > 4 else "工具/pi_only_diff.txt"
buf = []


def emit(s=""):
    buf.append(s)


hunks, cur = [], None
for ln in out.split("\n"):
    if ln.startswith("@@"):
        if cur:
            hunks.append(cur)
        cur = [ln, [], []]
    elif cur is not None:
        cur[1].append(ln)

if cur:
    hunks.append(cur)

n_del = sum(1 for h in hunks for l in h[1] if l.startswith("-") and not l.startswith("---"))
emit("含删除的 hunk 数 = %d ；删除行总数 = %d"
     % (sum(1 for h in hunks if any(l.startswith("-") and not l.startswith("---")
                                   for l in h[1])), n_del))
emit("=" * 78)
for h in hunks:
    body = h[1]
    if not any(l.startswith("-") and not l.startswith("---") for l in body):
        continue
    emit(h[0])
    for l in body:
        if l.startswith("-") and not l.startswith("---"):
            emit("  <<< PI-ONLY   " + l[1:])
        elif l.startswith("+"):
            emit("  >>> REPO-ONLY " + l[1:])
        else:
            emit("      " + (l[1:] if l else ""))
    emit("-" * 78)

with open(OUTP, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(buf) + "\n")
print("written: %s  (%d lines, %d deletions)" % (OUTP, len(buf), n_del))
