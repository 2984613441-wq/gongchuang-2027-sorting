# -*- coding: utf-8 -*-
"""第二轮视觉补丁：F1(A' 真生效) + F3(0号累计/事件触发) + F4(C 收紧到 IoU>=0.6 + 计数)。

断言式：任一处不命中"恰好一次"⇒ 整体中止，不写任何文件。
用法: py -3 工具/apply_vision_patch2.py [--apply]
"""
import io, os, shutil, sys, time, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V6 = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "stage1_color_v6_send.py")

R = []

# ── F1-a：候选 dict 里真的把 center 存进去（A' 这才生效）──────────────
R.append((
 '                               "bbox": (left, top, right-left, bottom-top), "clipped": False})\n',
 '                               "bbox": (left, top, right-left, bottom-top),\n'
 '                               # F1(2026-09-21)：中心必须**存进候选**，否则上面算的形心当场被丢掉。\n'
 '                               # 口径与 bbox 一致：都乘回 320 系并加上 ROI 偏移 (x0,y0)。\n'
 '                               "center": (round((cxl + x0) * sx), round((cyl + y0) * sy)),\n'
 '                               "clipped": False})\n',
 'F1a 候选存 center'))

# ── F1-b：上线编码优先用 center（带回落，旧 row 行为不变）──────────────
R.append((
 '    cx = int(left + w / 2)\n    cy = int(top + h / 2)\n',
 '    # F1(2026-09-21)：A\' 的形心只有在这里被读到才算生效。\n'
 '    # 没有 "center" 键（旧 row / 对称形状回落的旧路径）⇒ 逐字节等同原实现。\n'
 '    cx, cy = row.get("center") or (int(left + w / 2), int(top + h / 2))\n',
 'F1b encode_target 读 center'))

# ── F3-a：模块级累计计数器 ──────────────────────────────────────────────
R.append((
 '_REJ = {}                      # 方案0(2026-09-21) 每帧五道 continue 的拒绝计数\n',
 '_REJ = {}                      # 方案0(2026-09-21) 每帧五道 continue 的拒绝计数\n'
 '_REJ_TOT = {}                  # F3(2026-09-21) 进程内累计，用于事件触发打印\n',
 'F3a 累计计数器'))

# ── F3-b：打 c6 计数键 ─────────────────────────────────────────────────
R.append((
 '    _REJ.update(c1_area=0, c2_border=0, c3_aspect_extent=0,\n'
 '                c4_color_frac=0, c5_black_core=0)\n',
 '    _REJ.update(c1_area=0, c2_border=0, c3_aspect_extent=0,\n'
 '                c4_color_frac=0, c5_black_core=0, c6_black_mutex=0)\n',
 'F3b c6 键'))

# ── F4：C 判据从"1 像素相交"收紧成 IoU>=0.6（并计数）──────────────────
R.append((
 '                _d = ((_rc[0] - _oc[0]) ** 2 + (_rc[1] - _oc[1]) ** 2) ** 0.5\n'
 '                if (_ix * _iy) > 0 or _d < 0.5 * max(_w, _h):\n',
 '                # F4(2026-09-21)：判据从"1 像素相交 or 中心近"收紧为 **IoU>=0.6**。\n'
 '                # 实测依据：幻影是"同一批像素同时进两个窗"，IoU≈1，稳过；\n'
 '                # 而画面右缘那堵墙(blue#0 × black#5)的 IoU 只有 0.19 ⇒ 不再误杀；\n'
 '                # 真黑圆柱与彩色件相邻时 IoU≈0 ⇒ 保住。旧写法每边有 2~4mm 的误伤带。\n'
 '                _inter = _ix * _iy\n'
 '                _union = _w * _h + _ow * _oh - _inter\n'
 '                _iou = (_inter / _union) if _union > 0 else 0.0\n'
 '                if _iou >= 0.6:\n',
 'F4 C 收紧 IoU>=0.6'))

# ── F3-c：改成累计 + 事件触发（kept==0 或任一计数>0 才打印）────────────
R.append((
 '    _n = getattr(analyze, "_frames", 0) + 1\n'
 '    analyze._frames = _n\n'
 '    if _n % 60 == 1:\n'
 '        print("V6 REJECT " + " ".join("%s=%d" % (k, _REJ[k]) for k in sorted(_REJ))\n'
 '              + " kept=%d" % len(results))\n',
 '    # F3(2026-09-21)：原来"每 60 帧挑第 1 帧打印"，导致 59/60 帧的读数全丢。\n'
 '    # 改为**累计 + 事件触发**：只有"本帧一个候选都没留下"或"本帧有任何一闸拒绝"时\n'
 '    # 才打印，既不再丢信息，正常帧也不刷屏。\n'
 '    for _k in _REJ:\n'
 '        _REJ_TOT[_k] = _REJ_TOT.get(_k, 0) + _REJ[_k]\n'
 '    analyze._frames = getattr(analyze, "_frames", 0) + 1\n'
 '    if (not results) or any(_REJ.values()):\n'
 '        print("V6 REJECT frame=%d kept=%d | frame[%s] | total[%s]"\n'
 '              % (analyze._frames, len(results),\n'
 '                 " ".join("%s=%d" % (k, _REJ[k]) for k in sorted(_REJ)),\n'
 '                 " ".join("%s=%d" % (k, _REJ_TOT[k]) for k in sorted(_REJ_TOT))))\n',
 'F3c 累计+事件触发'))


def main():
    apply = "--apply" in sys.argv
    s = io.open(V6, encoding="utf-8").read()
    bad = 0
    for old, new, tag in R:
        n = s.count(old)
        print("%-26s hit %d %s" % (tag, n, "" if n == 1 else "  <<< MUST BE 1"))
        if n != 1:
            bad += 1
    if bad:
        print("\nFAIL: %d spot(s) -> ABORT, nothing written." % bad)
        return 1
    if not apply:
        print("\nDRY-RUN OK (%d spots). add --apply." % len(R))
        return 0
    shutil.copy2(V6, V6 + ".bak-visionpatch2-" + time.strftime("%Y%m%d-%H%M%S"))
    for old, new, tag in R:
        s = s.replace(old, new, 1)
    io.open(V6, "w", encoding="utf-8", newline="").write(s)
    py_compile.compile(V6, doraise=True)
    print("APPLIED %d spots + py_compile OK" % len(R))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
