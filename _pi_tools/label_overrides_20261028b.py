#!/usr/bin/env python3
"""20261028b 批次的人工判形结果（我从 200px 拼图逐格判读，共 260 个裁片）。

## 背景

这批是用户 2026-10-28 晚上专为**补弱项**采集的 100 帧：
  · v9 验证显示 cuboid 召回 0.702、pentagonal_prism 0.727、tetrahedron 仅 22 框
  · 用户据此集中拍长方体、五棱柱、正四面体

## 判读依据

`make_object_montages.py --cell 200 --base _new_capture_20261028b`
生成 6 张拼图（前 5 张各 48 格，第 6 张 20 格），gid 0~259。

字母：
    C  cube / B  cuboid / Y  cylinder / P  pentagonal_prism
    N  cone / T  tetrahedron / X  SKIP

## 关键观察

  · **绿/红"三角形"俯视 = 正四面体**（圆锥俯视是圆，四面体俯视是三角）
  · **绿/红/蓝"多边形"俯视 = 五棱柱**（顶面 5 条直边）
  · 蓝/黄"长方形"俯视 = 长方体
  · 本批长方体占 162/260，五棱柱 76，四面体 19
"""

from __future__ import annotations

# montage -> 行列表（前 5 张 6×8=48，第 6 张 8+8+4=20）
ROWS: dict[int, list[str]] = {
    0: [
        "BBBBBBBB",   # 00-07  全长方体（黄/蓝）
        "BBNBBXBN",   # 08-15  10/15 蓝圆锥，13 手挡住
        "PPBBBBBP",   # 16-23  16/17/23 蓝五棱柱
        "BBBTBBBT",   # 24-31  27/31 绿四面体
        "BBPBBTBB",   # 32-39  34 蓝五棱柱，37 绿四面体
        "PBBBBBBB",   # 40-47  40 蓝五棱柱
    ],
    1: [
        "PBBTBPBB",   # 48-55  48/53 蓝五棱柱，51 绿四面体
        "BBPBBBBB",   # 56-63  58 蓝五棱柱
        "BBBBBBBB",   # 64-71
        "BBBBBBBB",   # 72-79
        "BBBPBPTB",   # 80-87  83/85 蓝五棱柱，86 红四面体
        "BBBBBTBB",   # 88-95  93 红四面体
    ],
    2: [
        "BBBBBBBB",   # 96-103
        "BPBBPBBB",   # 104-111  105/108 红五棱柱
        "BBTPBBBT",   # 112-119  114/119 绿四面体，115 黄五棱柱
        "PBBPPBPB",   # 120-127  120/123/124/126 黄五棱柱
        "BTPBBPPB",   # 128-135  129 绿四面体，130/133/134 黄五棱柱
        "BTBBPBPB",   # 136-143  137 绿四面体，140/142 黄五棱柱
    ],
    3: [
        "BBBTBTBB",   # 144-151  147/149 绿四面体
        "BBBBBBBB",   # 152-159  绿/红长方体
        "BBBBBBPP",   # 160-167  166 黄五棱柱，167 红五棱柱
        "PPPPPPPP",   # 168-175  全五棱柱
        "PPPPPPPP",   # 176-183  全五棱柱
        "PPPPPPPP",   # 184-191  全五棱柱
    ],
    4: [
        "PPPPPPPP",   # 192-199  全五棱柱（黄/红）
        "BBBBBBBB",   # 200-207  全长方体（红/绿）
        "BBBBBBBP",   # 208-215  215 绿五棱柱
        "PTTTPTPP",   # 216-223  217/218/219/221 红四面体
        "PTTTPPPP",   # 224-231  225/226/227 红四面体
        "TBPPPBPB",   # 232-239  232 红四面体；233/237/239 长方；234/235/236/238 五棱柱
    ],
    5: [
        "BPPBBBBB",   # 240-247  241 绿五棱柱，242 黄五棱柱
        "BPPBBPBB",   # 248-255  249/250/253 黄五棱柱
        "BBBB",       # 256-259
    ],
}

SHORT2ID = {"C": 0, "B": 1, "Y": 2, "P": 3, "N": 4, "T": 5}
CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}

TOTAL = 260


def _rows_flat() -> dict[int, str]:
    return {m: "".join(rows) for m, rows in ROWS.items()}


def validate() -> list[str]:
    errs = []
    total = 0
    for mno, rows in ROWS.items():
        s = "".join(rows)
        total += len(s)
        per_row = 8 if mno < 5 else None
        if per_row:
            for ri, r in enumerate(rows):
                if len(r) != per_row:
                    errs.append("m%d 行%d 长度 %d != %d: %r"
                                % (mno, ri, len(r), per_row, r))
        for ch in s:
            if ch not in "CBYPNTX":
                errs.append("m%d 含非法字符 %r" % (mno, ch))
    if total != TOTAL:
        errs.append("总格数 %d != %d" % (total, TOTAL))
    return errs


def build_map() -> dict[int, str]:
    out = {}
    for mno, s in _rows_flat().items():
        for i, ch in enumerate(s):
            out[mno * 48 + i] = ch
    return out


def build_class_map() -> dict[int, int]:
    return {g: SHORT2ID[c] for g, c in build_map().items() if c in SHORT2ID}


if __name__ == "__main__":
    errs = validate()
    if errs:
        print("❌ 校验失败:")
        for e in errs:
            print("   " + e)
        raise SystemExit(1)
    print("✅ 结构校验通过（260 格）")
    m = build_map()
    miss = [g for g in range(TOTAL) if g not in m]
    print("缺失 gid: %s" % (miss if miss else "无 ✅"))
    from collections import Counter
    cnt = Counter(m[g] for g in range(TOTAL))
    print()
    print("%-4s %-18s %5s" % ("字母", "类别", "数量"))
    print("-" * 32)
    for k in "CBYPNTX":
        name = ZH.get(CLASS_NAMES[SHORT2ID[k]]) if k in SHORT2ID else "跳过"
        print("%-4s %-18s %5d" % (k, name, cnt.get(k, 0)))
    print("-" * 32)
    print("%-23s %5d" % ("合计", sum(cnt.values())))
