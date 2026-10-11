# -*- coding: utf-8 -*-
"""⑤(2026-09-21) 取证脚本改走生产函数 —— 任何锚点不"恰好出现一次"就中止，不落盘。

背景：forensic_v6_frame.py 里抄了一份 analyze()（analyze_instrumented）。抄本已落后
生产 4 次改动（c2 改判据 / c7 M2 / c8 M3 / A' 形心 / C 互斥 / center 字段），
于是它会产出一份"看起来很像、其实描述的是不存在的闸"的现场报告 —— 比没有更坏。

根因不是"忘了同步"，而是"存在第二份真相"。本补丁把它删掉：生产 analyze() 新增
trace 参数自己吐中间量，取证脚本只负责呈现。
"""
import hashlib
import os
import sys

ROOT = r"C:\Users\29845\Desktop\工创赛"
TARGET = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "forensic_v6_frame.py")

NEW_ANALYZE = '''def analyze_via_production(pixels, M, input_rgb=False, detect_size=None):
    """⑤(2026-09-21) 不再抄一份 analyze()：直接调生产函数，让它把中间量吐进 trace。

    旧版本是本文件的 hand-copy，落后生产 4 次改动，产出的报告描述的闸根本不存在。
    现在每一行 rows 都由生产函数自己填 —— 结构上不可能与生产不一致。
    本文件只负责"呈现"（掩膜拼图 / H 直方图 / 表格），不负责判据。
    """
    tr = {}
    results, roi_320 = M.analyze(pixels, input_rgb=input_rgb,
                                  detect_size=detect_size, trace=tr)
    det = tr["det"]
    sx, sy = tr["sx"], tr["sy"]
    x0, y0 = tr["roi_det"][0], tr["roi_det"][1]
    original_h, original_w = pixels.shape[:2]
    report = {
        "det": det, "sx": sx, "sy": sy, "roi_det": tr["roi_det"],
        "roi_320": tr["roi_320"], "min_area_det": tr["min_area_det"],
        "max_area_det": tr["max_area_det"], "min_area_320": tr["min_area_320"],
        "max_area_320": tr["max_area_320"], "sat": tr["sat"], "colors": {},
        "h_hist": None, "h_hist_sel": 0, "bright_px": 0, "roi_px": 0,
    }
    # 下面这段是纯呈现：掩膜、H 直方图、过曝量化。它退化了也不会让"哪道闸丢了件"的
    # 结论变错，所以允许留在这里自己算（生产函数里不该塞这些东西）。
    det_px = cv2.resize(pixels, det, interpolation=cv2.INTER_NEAREST)
    hsv = cv2.cvtColor(det_px[y0:tr["roi_det"][3], x0:tr["roi_det"][2]],
                       cv2.COLOR_RGB2HSV if input_rgb else cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    sel = (S >= 95) & (V >= 35)
    hist180 = np.bincount(H[sel].ravel(), minlength=180)[:180]
    report["h_hist"] = np.add.reduceat(hist180, np.arange(0, 180, 5))
    report["h_hist_sel"] = int(sel.sum())
    report["roi_px"] = int(hsv.shape[0] * hsv.shape[1])
    report["bright_px"] = int(np.count_nonzero(V >= 150))

    rows_by = {}
    for r in tr["rows"]:
        rows_by.setdefault(r["color"], []).append(r)
    masks = {}
    for color in M.COLOR_TO_MATERIAL:
        ranges = M.COLOR_RANGES[color]
        mask = cv2.inRange(hsv, ranges[0][0], ranges[0][1])
        for low, high in ranges[1:]:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))
        raw_px = int(cv2.countNonZero(mask))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, M.KERNEL)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, M.KERNEL)
        masks[color] = mask
        rows = rows_by.get(color, [])
        rec = {"n_contours": len(rows), "raw_px": raw_px,
               "morphed_px": int(cv2.countNonZero(mask)),
               "rej": {k: 0 for k in GATE_SRC}, "dropped_by_max": 0, "rows": [],
               "h_stats": None}
        m_ys, m_xs = np.nonzero(mask)
        if len(m_ys):
            hv = hsv[m_ys, m_xs, 0]
            rec["h_stats"] = (int(hv.min()), int(np.median(hv)), int(hv.max()))
        n_pass = 0
        for i, r in enumerate(rows):
            x, y, w, h = r["bbox_det"]
            gate = r["gate"]
            if gate:
                rec["rej"][gate] = rec["rej"].get(gate, 0) + 1
            else:
                n_pass += 1
            row = {
                "i": i, "area_det": r["area_det"], "area_320": r["area_det"] * sx * sy,
                "bbox_det": r["bbox_det"],
                "bbox_320": (round((x + x0) * sx), round((y + y0) * sy),
                             round(w * sx), round(h * sy)),
                "clamped": (round((x + x0 + w) * sx) > original_w or
                            round((y + y0 + h) * sy) > original_h),
                # edge 直接取生产函数算好的值（贴几条 ROI 边是 c2 的判据本身）
                "clip_roi": bool(r.get("edge", 0)),
                "edge": r.get("edge", 0),
                "clip_frame": bool(x <= -x0 or y <= -y0 or
                                   x + w >= det[0] - x0 or y + h >= det[1] - y0),
                "aspect": (min(w, h) / max(w, h)) if w and h else 0.0,
                "extent": (r["area_det"] / (w * h)) if w and h else 0.0,
                "verdict": ("REJECT " + GATE_SRC.get(gate, gate)) if gate else "PASS",
            }
            if "color_fraction" in r:
                row["color_fraction"] = r["color_fraction"]
            if "black_core" in r:
                row["black_core"] = r["black_core"]
            rec["rows"].append(row)
        rec["dropped_by_max"] = max(
            0, n_pass - (1 if any(x["color"] == color for x in results) else 0))
        report["colors"][color] = rec
    # 独立复算：把按色汇总的闸计数加回去，必须等于生产函数自己的 _REJ。
    # 这是本文件唯一真正的交叉验证 —— 它检查"重新打包"有没有丢东西。
    xcheck = _gate_crosscheck(M, report, tr)
    return results, report, masks, xcheck


def _gate_crosscheck(M, report, tr):
    """返回 (是否一致, 说明)。逐闸比对"按色汇总" vs 生产函数的全局 _REJ。"""
    bad = []
    for gate in sorted(GATE_SRC):
        summed = sum(report["colors"][c]["rej"].get(gate, 0)
                     for c in M.COLOR_TO_MATERIAL)
        actual = M._REJ.get(gate, 0)
        if summed != actual:
            bad.append("%s sum=%d prod=%d" % (gate, summed, actual))
    if len(tr["rows"]) != sum(report["colors"][c]["n_contours"]
                              for c in M.COLOR_TO_MATERIAL):
        bad.append("rows 总数对不上")
    return (not bad), ("OK 逐闸一致（rows=%d，sat=%s）" % (len(tr["rows"]), tr["sat"])
                       if not bad else "MISMATCH " + "; ".join(bad))


'''

NEW_GATESRC = '''# 闸的出处与真名。打印时直接引用，防对错行。
# ⑤(2026-09-21)：序号已按生产文件重核；c7 是 M2 绝对尺寸下限，c8 是 M3 饱和门
# （c8 在颜色循环之外，按色表里不会出现）。
GATE_SRC = {
    "c1_area": "c1 area",
    "c2_border": "c2 roi_border>=2",
    "c3_aspect_extent": "c3 aspect_extent",
    "c4_color_frac": "c4 color_fraction",
    "c5_black_core": "c5 black_core",
    "c7_min_size": "c7 M2 min_size",
}
'''


def main():
    with open(TARGET, "rb") as fh:
        raw = fh.read()
    old = raw.decode("utf-8")
    print("before sha256 = %s" % hashlib.sha256(raw).hexdigest())

    # 1) 整段替换手抄的 analyze_instrumented
    start = old.find("def analyze_instrumented(")
    end = old.find("def _q(")
    assert start != -1, "找不到 analyze_instrumented 起点"
    assert end != -1, "找不到 _q( 终点"
    assert start < end, "顺序不对"
    assert old.count("def analyze_instrumented(") == 1, "analyze_instrumented 不止一处"
    new = old[:start] + NEW_ANALYZE + old[end:]

    # 2) 换掉 GATE_SRC（旧的只有 5 闸、且行号已过期）
    g_start = new.find("# 五道 continue 的出处")
    g_end = new.find("TARGET_NAME = ")
    assert g_start != -1, "找不到 GATE_SRC 注释锚点"
    assert g_end != -1, "找不到 TARGET_NAME 锚点"
    assert g_start < g_end, "顺序不对"
    new = new[:g_start] + NEW_GATESRC + "\n\n" + new[g_end:]

    # 3) main()：改调新函数，XCHECK 换成"重新打包有没有丢东西"的独立复算
    old_call = (
        '        results, report, masks = analyze_instrumented(rgb, M, input_rgb=True)\n'
        '        ref, ref_roi = M.analyze(rgb, input_rgb=True)\n'
        '        xcheck = ("identical" if (ref == results and\n'
        '                                  tuple(ref_roi) == tuple(report["roi_320"]))\n'
        '                  else "MISMATCH ref=%r mine=%r" % (ref, results))\n')
    assert new.count(old_call) == 1, "main() 里的 analyze_instrumented 调用点不是恰好一处"
    new_call = (
        '        # ⑤ 只有一个 analyze()：这里不再有"副本 vs 生产"的比对，改成\n'
        '        #    "按色重新打包后的闸计数 vs 生产函数自己的 _REJ" 的独立复算。\n'
        '        results, report, masks, xcheck = analyze_via_production(\n'
        '            rgb, M, input_rgb=True)\n')
    new = new.replace(old_call, new_call)

    assert new != old, "没有任何改动"
    assert new.count("def analyze_via_production(") == 1, "新函数注入次数不对"
    assert "def analyze_instrumented(" not in new, "旧抄本没删干净"

    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    with open(TARGET, "rb") as fh:
        raw2 = fh.read()
    print("after  sha256 = %s" % hashlib.sha256(raw2).hexdigest())
    print("bytes %d -> %d" % (len(raw), len(raw2)))
    print("OK")


if __name__ == "__main__":
    sys.exit(main())
