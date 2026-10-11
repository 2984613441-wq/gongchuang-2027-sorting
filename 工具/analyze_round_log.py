#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轮次日志分析器 —— 把一轮 run_chain 日志压成"能不能过、15s 吃在哪"的结论。

为什么要有这个脚本：现场日志动辄 900KB（越界拒识每帧一条），人工 grep 会漏。
本脚本把四件事一次算清，判据全部来自项目自己的实测基线。

用法：
    python3 analyze_round_log.py <日志路径> [更多日志...]

输出四节：
  ① 派件表 + 行扫描顺序校验（键 = (-Y, X)，Y 最大那件应最先）
  ② 耗时表（发令→MOTION_DONE、上屏→下一次发令、上屏→上屏）+ **>15s 标红**
  ③ 屏幕/两段显示检查（序号序列、有无 AttributeError 之类合成失败）
  ④ 首件稳定门 + 越界拒识计数 + 结尾状态

只读，不改任何文件。
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
ITEM = re.compile(
    r"ITEM_TASK sent: target_seq=(\d+) class_id=(\d+) image_id=(\d+) "
    r"落点=\(([-\d.]+),([-\d.]+)\)mm 抓取点=\(([-\d.]+),([-\d.]+)\)mm"
)
DISPLAY = re.compile(r"显示完成并确认: target_seq=(\d+) name=(\S+) success=(\d+)")
TWO = re.compile(r"两段显示已上屏: \d+x\d+ 序号=(\S+) target_seq=(\d+) box_id=(\S+)")
GATE = re.compile(r"首件稳定门(.*)")
OVER = re.compile(r"越界：pixel_to_device=\(([-\d]+), ([-\d]+)\)")
IDLE = re.compile(r"空闲: state=(\S+) success=(\d+)")
LIMIT_S = 15.0


def _t(line: str):
    m = TS.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")


def analyse(path: str) -> None:
    print("=" * 78)
    print(f"日志: {path}")
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")

    dispatches, displays, two_stage, gates, overruns, idles = [], [], [], [], [], []
    failures, turntable, motions = [], [], []
    t0 = None
    for line in lines:
        t = _t(line)
        if t is not None and t0 is None:
            t0 = t
        if (m := ITEM.search(line)) and t:
            dispatches.append((t, int(m.group(1)), int(m.group(2)),
                               float(m.group(6)), float(m.group(7))))
        if "MOTION_DONE accepted" in line and t:
            motions.append(t)
        if (m := DISPLAY.search(line)) and t:
            displays.append((t, int(m.group(1)), m.group(2), int(m.group(3))))
        if m := TWO.search(line):
            two_stage.append((m.group(1), m.group(2), m.group(3)))
        if m := GATE.search(line):
            gates.append(m.group(1).strip())
        if OVER.search(line):
            overruns.append(line)
        if (m := IDLE.search(line)) and t:
            idles.append((t, m.group(1), int(m.group(2))))
        if "两段显示帧合成/上屏失败" in line or "  ERROR " in line:
            failures.append(line)
        if "转盘翻转" in line or "转盘开工自检" in line:
            turntable.append(line)

    if t0:
        print(f"轮次起始: {t0}    总行数: {len(lines)}")

    # ---- ① 派件 + 顺序 ----
    print("\n【① 派件表 / 行扫描顺序】")
    if not dispatches:
        print("  ❌ 一次 ITEM_TASK 都没发出去 —— 机器一步没动")
    order_ok = True
    for i, (t, seq, cls, px, py) in enumerate(dispatches, 1):
        print(f"  {i}. {t.strftime('%H:%M:%S.%f')[:-3]}  target_seq={seq} "
              f"货格={cls}  抓取点=({px:6.1f},{py:6.1f})")
    if len(dispatches) >= 2:
        # 行扫描键 = (-Y, X)：Y 最大那件必须最先。⚠️ 别写成 -y——那会挑到 Y 最小的。
        if dispatches[0][4] != max(d[4] for d in dispatches):
            worst = max(range(len(dispatches)), key=lambda i: dispatches[i][4])
            print(f"  ❌ **顺序不符行扫描**：Y 最大那件（y={dispatches[worst][4]:.1f}）"
                  f"是第 {worst + 1} 发，应最先")
            order_ok = False
        if order_ok:
            print(f"  ✅ {len(dispatches)} 发全部满足行扫描（首发的 Y 最大）")

    # ---- ② 耗时 ----
    print("\n【② 耗时（15s 红线怎么吃掉的）】")
    print("     #   发令→MOTION_DONE   上屏→下次发令   发令→下次发令")
    for i, (t, seq, cls, px, py) in enumerate(dispatches):
        nxt = dispatches[i + 1][0] if i + 1 < len(dispatches) else None
        md = motions[i] if i < len(motions) else None
        disp = next((x for x in displays if x[1] == seq and x[0] >= t), None)
        seg1 = (md - t).total_seconds() if md else float("nan")
        seg2 = (nxt - disp[0]).total_seconds() if (nxt and disp) else float("nan")
        seg3 = (nxt - dispatches[i][0]).total_seconds() if nxt else float("nan")
        flag = lambda v: "❌" if (v == v and v > LIMIT_S) else "  "
        print(f"  {flag(seg1)}{i+1:>3}  {seg1:>14.3f}s {flag(seg2)} {seg2:>12.3f}s "
              f"{flag(seg3)} {seg3:>10.3f}s")
    if len(motions) != len(dispatches):
        print(f"  ⚠️ MOTION_DONE {len(motions)} 条 vs 派件 {len(dispatches)} 发"
              f" ⇒ 有 {(len(dispatches) - len(motions))} 发**永远没动**（板子静默）")
    for i in range(1, len(displays)):
        gap = (displays[i][0] - displays[i - 1][0]).total_seconds()
        print(f"    上屏 {i} → 上屏 {i+1}: {gap:6.3f}s  "
              + ("❌ >15s" if gap > LIMIT_S else "ok"))

    # ---- ③ 屏幕 ----
    print("\n【③ 屏幕 / 两段显示】")
    print(f"  规则帧（赛规要求的那一帧）: {len(displays)} 次")
    for t, seq, name, sc in displays:
        print(f"     {t.strftime('%H:%M:%S')}  success={sc} 名称={name}")
    print(f"  两段显示: {len(two_stage)} 次")
    if two_stage:
        seqs = [s for s, _, _ in two_stage]
        print(f"     屏上序号序列 = {seqs}")
        exp = [str(i // 2 + 1) for i in range(len(seqs))]
        print("     " + ("✅ 序号单调不重复、同一件两段同号"
                         if seqs == exp else f"❌ 期望 {exp}"))
    if failures:
        print(f"  ❌ 合成/ERROR {len(failures)} 条（前 3 条）:")
        for ln in failures[:3]:
            print("     " + ln.strip()[:150])
    else:
        print("  ✅ 无「两段显示帧合成/上屏失败」、无 ERROR")

    # ---- ④ 稳定门 / 拒识 / 结尾 ----
    print("\n【④ 首件稳定门 / 越界拒识 / 结尾】")
    if not gates:
        print("  稳定门: 未出现 —— 可能本轮跑的是旧 run_chain（无此功能）")
    for g in gates[:3]:
        print(f"  稳定门: {g[:110]}")
    if any("超时" in g for g in gates):
        print("     ⚠️ 超时 = 帧率太低、该门本轮未生效（行为等同关闭，不是故障）")
    print(f"  越界拒识: {len(overruns)} 条"
          + ("  ⚠️ 刷屏（真问题会被淹）" if len(overruns) > 20 else ""))
    if overruns:
        print("     首条: " + overruns[0].strip()[-110:])
    print(f"  转盘动作: {len(turntable)} 条")
    if idles:
        t, st, sc = idles[-1]
        print(f"  最后状态: {t.strftime('%H:%M:%S')} state={st} success={sc}")
        if idles[-1][1] != "READY":
            print("     ⚠️ 结束时不在 READY —— 轮次被中断在中间")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for p in sys.argv[1:]:
        try:
            analyse(p)
        except FileNotFoundError:
            print(f"❌ 找不到 {p}")
