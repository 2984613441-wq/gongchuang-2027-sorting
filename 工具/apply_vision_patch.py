# -*- coding: utf-8 -*-
"""应用视觉补丁 0 + A' + C（断言式，失败即整体中止，绝不半途改坏生产文件）。

用法: py -3 工具/apply_vision_patch.py [--apply]
不加 --apply 只做干跑（检查每处命中次数 + 语法编译），不写任何文件。
"""
import io, os, shutil, sys, time, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V6 = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "stage1_color_v6_send.py")
BR = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "v6_bridge.py")

R = []  # (文件, 旧串, 新串, 说明)

# ---- 0：模块级拒绝计数器 + A' 常量 -------------------------------------
R.append((V6,
 'MIN_COLOR_FRACTION = 0.70\n',
 'MIN_COLOR_FRACTION = 0.70\n'
 'SHAPE_EXTENT_CENTROID = 0.65   # A\'(2026-09-21) ext<此值判为"非中心对称形状"，抓取点改用形心\n'
 '_REJ = {}                      # 方案0(2026-09-21) 每帧五道 continue 的拒绝计数\n',
 'A\'常量 + _REJ'))

# ---- 0：每帧清零 -------------------------------------------------------
R.append((V6,
 '    original_h, original_w = pixels.shape[:2]\n',
 '    _REJ.clear()\n'
 '    _REJ.update(c1_area=0, c2_border=0, c3_aspect_extent=0,\n'
 '                c4_color_frac=0, c5_black_core=0)\n'
 '    original_h, original_w = pixels.shape[:2]\n',
 '方案0 每帧清零'))

# ---- 0：五道 continue 计数 ---------------------------------------------
R.append((V6,
 '            if not min_area <= area <= max_area:\n                continue\n',
 '            if not min_area <= area <= max_area:\n'
 '                _REJ["c1_area"] += 1\n                continue\n', ':235 area'))
R.append((V6,
 '                continue\n            if min(w, h) / max(w, h) < 0.28 or area / (w*h) < 0.35:\n',
 '                _REJ["c2_border"] += 1\n                continue\n'
 '            if min(w, h) / max(w, h) < 0.28 or area / (w*h) < 0.35:\n', ':239 border'))
R.append((V6,
 '                continue  # 排除细长背景条和极稀疏噪声，不据此确定物料形状。\n',
 '                _REJ["c3_aspect_extent"] += 1\n'
 '                continue  # 排除细长背景条和极稀疏噪声，不据此确定物料形状。\n', ':241 geometry'))
R.append((V6,
 '            if fraction < MIN_COLOR_FRACTION:\n                continue\n',
 '            if fraction < MIN_COLOR_FRACTION:\n'
 '                _REJ["c4_color_frac"] += 1\n                continue\n', ':254 fraction'))
R.append((V6,
 '                if not count or cv2.countNonZero(cv2.bitwise_and(core, inside))/count < 0.30:\n'
 '                    continue\n',
 '                if not count or cv2.countNonZero(cv2.bitwise_and(core, inside))/count < 0.30:\n'
 '                    _REJ["c5_black_core"] += 1\n                    continue\n', ':259 black_core'))

# ---- A'：候选加 center --------------------------------------------------
R.append((V6,
 '            candidates.append({"color": color, "shape": shape, "bin": bin_id,\n'
 '                               "classification_source": "color", "reason": "color_mapping",\n',
 '            # A\'(2026-09-21)：只在"测出不是中心对称形状"时才用形心当抓取点。\n'
 '            # 三角形 ext∈[0.464,0.500]、圆盘 0.785、正方形 1.000 ⇒ 条件天然只命中三角形；\n'
 '            # 对称形状走原 bbox 中心路径，取值逐字节不变。\n'
 '            _ext = area / float(w * h) if w and h else 1.0\n'
 '            if _ext < SHAPE_EXTENT_CENTROID:\n'
 '                _m = cv2.moments(contour)\n'
 '                if _m["m00"] > 0:\n'
 '                    cxl, cyl = _m["m10"] / _m["m00"], _m["m01"] / _m["m00"]\n'
 '                else:\n'
 '                    cxl, cyl = x + w / 2.0, y + h / 2.0\n'
 '            else:\n'
 '                cxl, cyl = x + w / 2.0, y + h / 2.0\n'
 '            candidates.append({"color": color, "shape": shape, "bin": bin_id,\n'
 '                               "classification_source": "color", "reason": "color_mapping",\n',
 'A\' 计算形心'))

# ---- C：返回前做 black 互斥 + 打印计数 ----------------------------------
R.append((V6,
 '    return results, (round(x0*sx), round(y0*sy), round(x1*sx), round(y1*sy))\n',
 '    # C(2026-09-21)：black 与彩色候选空间互斥。\n'
 '    # black 窗口 :191 横跨全部色相、与彩色窗在 S∈[95,150] 重叠 ⇒ 同一个物体可能\n'
 '    # 同时产出 bin4(blue) 与 bin5(black)（实测 HSV(120,120,34) 双发）。这里丢掉与\n'
 '    # 彩色候选 bbox 重叠、或中心距 < 0.5*max(w,h) 的 black 候选。\n'
 '    # 系数取 0.5 而非 0.8：幻影双发的两候选中心几乎重合，0.5 一样拦得住，\n'
 '    # 却更不容易误丢"紧挨着彩色件"的真黑圆柱。\n'
 '    # ponytail: 启发式上限，只做空间互斥，不动 :184-192 的色阈值。\n'
 '    _colored = [r for r in results if r["color"] != "black"]\n'
 '    if _colored:\n'
 '        _kept = []\n'
 '        for _row in results:\n'
 '            if _row["color"] != "black":\n'
 '                _kept.append(_row)\n'
 '                continue\n'
 '            _l, _t, _w, _h = _row["bbox"]\n'
 '            _rc = _row.get("center") or (_l + _w // 2, _t + _h // 2)\n'
 '            _drop = False\n'
 '            for _o in _colored:\n'
 '                _ol, _ot, _ow, _oh = _o["bbox"]\n'
 '                _oc = _o.get("center") or (_ol + _ow // 2, _ot + _oh // 2)\n'
 '                _ix = max(0, min(_l + _w, _ol + _ow) - max(_l, _ol))\n'
 '                _iy = max(0, min(_t + _h, _ot + _oh) - max(_t, _ot))\n'
 '                _d = ((_rc[0] - _oc[0]) ** 2 + (_rc[1] - _oc[1]) ** 2) ** 0.5\n'
 '                if (_ix * _iy) > 0 or _d < 0.5 * max(_w, _h):\n'
 '                    _drop = True\n'
 '                    break\n'
 '            if not _drop:\n'
 '                _kept.append(_row)\n'
 '        results = _kept\n'
 '    _n = getattr(analyze, "_frames", 0) + 1\n'
 '    analyze._frames = _n\n'
 '    if _n % 60 == 1:\n'
 '        print("V6 REJECT " + " ".join("%s=%d" % (k, _REJ[k]) for k in sorted(_REJ))\n'
 '              + " kept=%d" % len(results))\n'
 '    return results, (round(x0*sx), round(y0*sy), round(x1*sx), round(y1*sy))\n',
 'C 互斥 + 方案0 打印'))

# ---- A'：StableTargets 的 center 一起做 EMA ------------------------------
R.append((V6,
 '                previous["box"] += alpha*(box-previous["box"])\n',
 '                previous["box"] += alpha*(box-previous["box"])\n'
 '                _c = np.array(row.get("center") or (\n'
 '                    row["bbox"][0] + row["bbox"][2] / 2.0,\n'
 '                    row["bbox"][1] + row["bbox"][3] / 2.0), dtype=float)\n'
 '                if previous.get("center") is None:\n'
 '                    previous["center"] = _c\n'
 '                else:\n'
 '                    previous["center"] += alpha * (_c - previous["center"])\n',
 'A\' center EMA'))
R.append((V6,
 '                previous = {"box": box, "hits": 0, "confirmed": False,\n'
 '                            "last_seen": now, "row": row}\n',
 '                previous = {"box": box, "hits": 0, "confirmed": False,\n'
 '                            "last_seen": now, "row": row, "center": None}\n',
 'A\' center 初始'))
R.append((V6,
 '            row["bbox"] = tuple(int(round(v)) for v in track["box"])\n',
 '            row["bbox"] = tuple(int(round(v)) for v in track["box"])\n'
 '            if track.get("center") is not None:\n'
 '                row["center"] = tuple(int(round(v)) for v in track["center"])\n',
 'A\' center 回写'))

# ---- 桥侧第二份拷贝 -----------------------------------------------------
R.append((BR,
 '    left, top, w, h = row["bbox"]\n    cx = int(left + w / 2)\n    cy = int(top + h / 2)\n',
 '    left, top, w, h = row["bbox"]\n'
 '    cx, cy = row.get("center") or (int(left + w / 2), int(top + h / 2))\n',
 'v6_bridge center 回落'))


def main():
    apply = "--apply" in sys.argv
    plan = {}
    for path, old, new, tag in R:
        plan.setdefault(path, []).append((old, new, tag))

    bad = 0
    for path, items in plan.items():
        s = io.open(path, encoding="utf-8").read()
        print("=== %s (%d 处) ===" % (os.path.basename(path), len(items)))
        for old, new, tag in items:
            n = s.count(old)
            print("   %-24s 命中 %d 次 %s" % (tag, n, "" if n == 1 else "  <<< 必须恰好 1 次"))
            if n != 1:
                bad += 1
    if bad:
        print("\nFAIL: %d spot(s) not exactly-once => ABORT, nothing written." % bad)
        return 1
    if not apply:
        print("\nDRY-RUN OK (%d spots). add --apply to write." % len(R))
        return 0

    ts = time.strftime("%Y%m%d-%H%M%S")
    for path, items in plan.items():
        dst = path + ".bak-visionpatch-" + ts
        shutil.copy2(path, dst)
        s = io.open(path, encoding="utf-8").read()
        for old, new, tag in items:
            s = s.replace(old, new, 1)
        io.open(path, "w", encoding="utf-8", newline="").write(s)
        print("已改 %s   备份=%s" % (os.path.basename(path), os.path.basename(dst)))
    for path in plan:
        py_compile.compile(path, doraise=True)
        print("py_compile OK: %s" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
