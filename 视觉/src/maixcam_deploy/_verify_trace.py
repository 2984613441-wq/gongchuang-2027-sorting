# -*- coding: utf-8 -*-
"""⑤(2026-09-21) 在设备上验证取证脚本的重打包逻辑 —— 只读，不用相机，不动电机。

为什么要有它：forensic_v6_frame.py 原本抄了一份 analyze()，抄本落后生产 4 次改动，
会产出"描述着不存在的闸"的报告。⑤ 把抄本删了，改由生产 analyze(trace=...) 吐中间量。
但新写的 analyze_via_production() 有 ~100 行，主机上没有 cv2 跑不了 ⇒ 不能只在主机上
"编译通过"就宣布完成（这正是 A' 死代码的教训）。

本脚本用设备上**已有的** PNG 当输入，跑与生产完全同一份代码路径（设备自己的 cv2、
设备自己的生产文件），于是：
  · 不需要相机（不会和生产 V6 抢设备）
  · 不需要上电运动
  · 验的是真环境，不是主机的 OpenCV 5.0

判断标准：_gate_crosscheck 必须 OK —— 即"按色重新打包后的闸计数"逐闸等于
"生产函数自己的 _REJ"。对不上就说明重打包丢了东西。
"""
import glob
import os
import sys

sys.path.insert(0, "/root/forensic")

import cv2                                                   # noqa: E402
import forensic_v6_frame as F                                # noqa: E402

# 优先用真件帧（有彩件才有 PASS 行）；没有就退到任意一张
PREFERRED = ["/root/forensic/prism_tri_normal_01.png",
             "/root/forensic/cube_normal_01.png",
             "/root/forensic/cylinder_normal_01.png"]


def pick_frame():
    for p in PREFERRED:
        if os.path.exists(p):
            return p
    rest = sorted(glob.glob("/root/forensic/*.png"))
    rest = [p for p in rest if "_mask" not in p]
    return rest[0] if rest else None


def main():
    png = sys.argv[1] if len(sys.argv) > 1 else pick_frame()
    if png is None:
        print("FAIL  /root/forensic/ 下没有可用 PNG")
        return 1
    print("input      : %s" % png)
    bgr = cv2.imread(png, cv2.IMREAD_COLOR)
    if bgr is None:
        print("FAIL  读不了这张图")
        return 1
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    print("shape      : %s" % (rgb.shape,))

    M, src = F.load_production()
    print("production : %s" % src)

    results, report, masks, xcheck = F.analyze_via_production(rgb, M, input_rgb=True)
    ok, why = xcheck

    print("-" * 70)
    print("results    : %d 件" % len(results))
    for r in results:
        print("   bin=%d color=%-7s bbox=%s center=%s cfrac=%.4f"
              % (r["bin"], r["color"], r["bbox"], r.get("center"),
                 r["color_fraction"]))
    print("prod _REJ  : %s" % {k: v for k, v in sorted(M._REJ.items()) if v})
    print("-" * 70)
    for color in M.COLOR_TO_MATERIAL:
        rec = report["colors"][color]
        rej = {k: v for k, v in rec["rej"].items() if v}
        if rec["n_contours"] or rej:
            print("   %-7s contours=%d dropped_by_max=%d rej=%s h=%s"
                  % (color, rec["n_contours"], rec["dropped_by_max"], rej,
                     rec["h_stats"]))
    print("-" * 70)
    # 逐行核对 rows 的字段是否齐全（print_report 会直接取这些键）
    missing = []
    for color in M.COLOR_TO_MATERIAL:
        for row in report["colors"][color]["rows"]:
            for k in ("i", "area_det", "area_320", "bbox_320", "clip_roi",
                      "clip_frame", "aspect", "extent", "verdict", "edge"):
                if k not in row:
                    missing.append("%s.%s 缺 %s" % (color, row.get("i"), k))
    if missing:
        print("FAIL  rows 字段缺失：%s" % missing[:10])
        return 1
    print("rows 字段  : 齐全")
    print("XCHECK     : %s" % why)
    if not ok:
        print("FAIL  重打包与生产 _REJ 不一致 —— 取证报告不可信")
        return 1
    # 真正的验收：print_report 必须能在新 report 结构下跑完 —— 它才是现场拿到的东西。
    # 只查"rows 字段齐不齐"是不够的：键都在、print_report 却可能照样崩。
    print("=" * 78)
    print("下面是现场会看到的报告本体（print_report 全量输出）：")
    F.print_report("verify", src, rgb.shape[:2], report, results, M, png, "-",
                   why, 0.0)
    print("PASS  ⑤ 设备端验证通过（%d 件，逐闸一致，print_report 跑通）" % len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
