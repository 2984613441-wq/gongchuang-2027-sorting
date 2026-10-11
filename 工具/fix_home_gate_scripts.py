# -*- coding: utf-8 -*-
"""给 Pi 上的启动脚本补上 HOME 门禁（2026-09-21）。

背景：repo 版 run_chain.py 新增 require_home_confirmation()（:508 定义 / :1041 调用），
真实模式 --start-round 要求 stdin 精确输入 HOME。而 nohup 会把 stdin 变成 /dev/null
（有些脚本还显式写了 `< /dev/null`）⇒ 旧写法的启动脚本全部直接拒启动。

本脚本对每个文件做三件事，**任一断言不满足就整体中止、不写任何文件**：
  1. 在调用行前插入"操作员确认 HOME"的交互门（保留人确认这一步，不削弱安全门）
  2. 调用行前面加 `echo HOME | ` 把确认喂给链
  3. 若 --start-round 那行带 ` < /dev/null`，删掉它 —— **重定向会压过管道**，
     不删的话 `echo HOME |` 完全无效（这是本批最容易漏的一处）

用法：py -3 工具/fix_home_gate_scripts.py <目录>
"""
import os
import sys

GATE = [
    "# ── HOME 门禁（2026-09-21）──────────────────────────────────────────────",
    "# 板子无编码器、不寻零 ⇒ 软件无法判断 XY 是否真的在 HOME；起点错了会让第一段",
    "# 增量运动整体偏移，可能顶死堵转并使开环坐标永久失准。新版 run_chain.py 的",
    "# --start-round 要求 stdin 精确输入 HOME，非交互一律拒绝（nohup 会把 stdin",
    "# 变成 /dev/null）。这里由操作员确认一次再把 HOME 喂给链。",
    "# 见 docs/交付/2026-09-21/交接-2026-09-21-深夜-转盘部署与标定.md §10.5",
    'echo "!!! 期望起点：X=-95.0mm, Y=-97.5mm（X/Y 负方向最里角，均顶住）!!!"',
    "printf '确认滑台已在 HOME 后输入 HOME（其他输入均退出）：'",
    "read -r ANS",
    'if [ "$ANS" != "HOME" ]; then echo ">>> 未确认 HOME，拒绝起链。"; exit 1; fi',
    "",
]

TARGETS = [
    "pi_chain_debug.sh", "pi_repro_and_read.sh", "pi_start_chain.sh",
    "p_start7.sh", "p_start_round.sh", "start2.sh", "start3.sh",
    "start4.sh", "start5.sh", "start_round.sh",
]


def patch(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    lines = text.split("\n")

    # 1) 找准唯一的"调用 run_chain.py"那一行（排除注释、pkill/pgrep 行）
    hits = [i for i, l in enumerate(lines)
            if "deploy/run_chain.py" in l and "python3" in l
            and not l.lstrip().startswith("#")]
    assert len(hits) == 1, "%s: 调用行命中 %d 处（要求恰好 1）" % (
        os.path.basename(path), len(hits))
    idx = hits[0]

    assert "echo HOME |" not in lines[idx], \
        "%s: 调用行已经有 echo HOME | 了，别重复加" % os.path.basename(path)

    # 2) 删掉会压过管道的 < /dev/null（只在 --start-round 那行；**排除注释行**——
    #    pi_start_chain.sh:2 是 "# 重启真实链路（含 --start-round）"，不排会把注释也算一处）
    srows = [i for i, l in enumerate(lines)
             if "--start-round" in l and not l.lstrip().startswith("#")]
    assert len(srows) == 1, "%s: --start-round 命中 %d 处" % (
        os.path.basename(path), len(srows))
    s = srows[0]
    removed = False
    if " < /dev/null" in lines[s]:
        lines[s] = lines[s].replace(" < /dev/null", "")
        removed = True

    # 3) 调用行前加管道
    lead = lines[idx][:len(lines[idx]) - len(lines[idx].lstrip())]
    lines[idx] = lead + "echo HOME | " + lines[idx].lstrip()

    # 4) 在调用行之前插入门禁
    lines[idx:idx] = GATE

    new = "\n".join(lines)
    assert new != text
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    return removed


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else r"工具/pi_side/sh"
    for n in TARGETS:
        p = os.path.join(d, n)
        if not os.path.exists(p):
            print("  跳过（没有这个文件）: %s" % n)
            continue
        if "echo HOME |" in open(p, encoding="utf-8").read():
            print("  跳过（已经是修好的）: %s" % n)
            continue
        removed = patch(p)
        b = open(p, "rb").read()
        print("  OK  %-24s 删掉 < /dev/null = %-5s  CRLF=%d BOM=%s"
              % (n, removed, b.count(b"\r\n"), b[:3] == b"\xef\xbb\xbf"))
    print("全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
