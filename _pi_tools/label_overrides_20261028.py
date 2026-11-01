#!/usr/bin/env python3
"""20261028 批次的人工判形结果（我从 200px 拼图逐格判读）。

## 判读依据

2026-10-28 用 `make_object_montages.py --cell 200` 生成 9 张拼图
（8×6 = 48 格/张，共 430 个裁片，gid 0~429）。

⚠️ 与 2026-10-27 那批的差异：
  · 那批用 130px 格子，方块类判得不准（用户复核改了 97 个框）
  · 这批放大到 200px，能看清顶面边数，**五边形/长方形可分辨**

## 字母含义

    C  cube             正方体
    B  cuboid           长方体
    Y  cylinder         圆柱
    P  pentagonal_prism 五棱柱
    N  cone             圆锥
    T  tetrahedron      正四面体
    X  SKIP             跳过（手指/电线/废裁片/黑块）

## 关键确认

  · **五棱柱**：顶面清楚是 5 条边（267/270/276/282 黄，240/272/280/287 绿，
    411/416/419/422/425/426 红）⇒ 类别定义没问题，不存在六棱柱问题
  · **长方体**：顶面是长方形（406/408 红，401-404/407/409-415/417-421/427/429 绿，
    196/199/204/205 蓝）
  · **圆柱**：蓝、黄两色，表面光滑无棱
  · **圆锥**：红、蓝、绿、黄四色都有
  · **正四面体**：黄(145)、绿(148)、红(152)、蓝(159)
  · **手指误检**：304/305/310/316/320/327/333/335/337/371/375/382 ⇒ 全标 X

## 用法

    from label_overrides_20261028 import build_map, build_class_map
    m = build_map()          # {gid: letter}
"""

from __future__ import annotations

# 每个 montage 6 行 × 8 列 = 48 格
ROWS: dict[int, list[str]] = {
    0: [
        "CCCCCCCC",   # 00-07
        "CCCCCCCC",   # 08-15
        "CCXXXPYC",   # 16-23  18/19/20 电线挡住；21 红五棱柱；22 蓝圆柱
        "CCCYCCPC",   # 24-31
        "CCCYCBYC",   # 32-39  36 顶面偏长方
        "CCYCBCXY",   # 40-47  46 手
    ],
    1: [
        "PYP CYC PY".replace(" ", ""),   # 48-55  红五棱柱×3，蓝圆柱×2
        "PCYCCCCY",   # 56-63
        "CCCYCCPP",   # 64-71
        "PCCCCCCB",   # 72-79
        "CCBCCCCB",   # 80-87
        "BYBBYYPB",   # 88-95  93 黄圆柱；94 蓝五棱柱
    ],
    2: [
        "YYPPBPPY",   # 96-103  96 黄圆柱
        "PYBYP C YB".replace(" ", ""),   # 104-111  109 绿方块；110 蓝圆柱
        "YPYPCCBP",   # 112-119
        "YPP C YYB Y".replace(" ", ""),  # 120-127  124/125 黄圆柱躺倒
        "PBYYC YCP".replace(" ", ""),    # 128-135  129 红长方体
        "YBPYBYBP",   # 136-143
    ],
    3: [
        "CTCNTN YN".replace(" ", ""),   # 144-151  145 黄四面体，147 蓝圆锥，148 绿四面体，151 绿圆锥
        "TNYYNNNT",   # 152-159  152 红四面体，156 红圆锥，159 蓝四面体
        "NNNYNNYX",   # 160-167  167 模糊
        "NNNNXNNN",   # 168-175  172 黑
        "YXYXCYBC",   # 176-183  177 黑，179 绿边缘废
        "BBYBB" + "CYN",   # 184-191  184/188 蓝长方体，185/187 绿长方体，190 黄圆柱，191 蓝圆锥
    ],
    4: [
        "CCYB B C YB".replace(" ", ""),   # 192-199
        "CYCB B BYB".replace(" ", ""),    # 200-207
        "CBBYCCBC",   # 208-215  209 绿长方体，212 绿方块
        "CYCB C YCC".replace(" ", ""),    # 216-223
        "BCBYBCBY",   # 224-231
        "CBCXCYCB",   # 232-239  235 黑
    ],
    5: [
        "PYBPBYBB",   # 240-247  240/243 绿五棱柱
        "PYBBBYBY",   # 248-255
        "BBYB BYPB".replace(" ", ""),     # 256-263  262 绿五棱柱
        "YBBPNBPY",   # 264-271  267/270 黄五棱柱，268 蓝圆锥
        "PBBNP BYY".replace(" ", ""),     # 272-279  272 绿五棱柱，275 蓝圆锥，276 黄五棱柱
        "PNPNBBYP",   # 280-287  280 绿五棱柱，281 蓝圆锥，282 黄五棱柱，287 绿五棱柱
    ],
    6: [
        "PNBBPNYB",   # 288-295  288/292 黄五棱柱，293 蓝圆锥
        "PNYBPPNY",   # 296-303  296 绿五棱柱，300/301 黄五棱柱，302 黄圆锥
        "XXYC BPXP".replace(" ", ""),     # 304-311  304/305/310 手指，309/311 绿五棱柱
        "BNPP X PPB".replace(" ", ""),    # 312-319  313 蓝圆锥，316 手指，314/315/318 黄五棱柱，317 绿五棱柱
        "XPPPPNYX",   # 320-327  320 手指，321 绿五棱柱，322/323 黄五棱柱，324 绿五棱柱，325 蓝圆锥，327 手指
        "BP C NYXYX".replace(" ", ""),    # 328-335  329 绿五棱柱，331 蓝圆锥，333/335 手指
    ],
    7: [
        "YXYYYYYY",   # 336-343  337 手指
        "CYPPY NCP".replace(" ", ""),     # 344-351  346/347/351 黄五棱柱，349 蓝圆锥
        "PYCCNPCY",   # 352-359  352/357 黄五棱柱，356 蓝圆锥
        "PCNNYCCC",   # 360-367  360 黄五棱柱，362/363 蓝圆锥
        "XCCXNCCX",   # 368-375  368 黑，371/375 手指，372 蓝圆锥
        "NCCCCCXN",   # 376-383  376/383 蓝圆锥，382 手指
    ],
    8: [
        "YCCYCNYC",   # 384-391  389 蓝圆锥
        "CNCNCCNC",   # 392-399  393/395/398 蓝圆锥
        "CBBBBBBB",   # 400-407  401-405/407 长方体（绿/红）
        "BBB PBBBB".replace(" ", ""),     # 408-415  408 红长方体，411 红五棱柱
        "PBBPBBPX",   # 416-423  416/419/422 红五棱柱
        "XPPBYB" + "XX",   # 424-429（后两格无物件，补 X）
    ],
}

SHORT2ID = {"C": 0, "B": 1, "Y": 2, "P": 3, "N": 4, "T": 5}
CLASS_NAMES = ["cube", "cuboid", "cylinder",
               "pentagonal_prism", "cone", "tetrahedron"]
ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}


def _rows_flat() -> dict[int, str]:
    """montage -> 48 字符串（6 行拼接）。"""
    out = {}
    for mno, rows in ROWS.items():
        s = "".join(rows)
        out[mno] = s
    return out


def validate() -> list[str]:
    """返回问题列表（空 = 全部合法）。"""
    errs = []
    for mno, rows in ROWS.items():
        if len(rows) != 6:
            errs.append("montage %d 行数 %d != 6" % (mno, len(rows)))
        for ri, r in enumerate(rows):
            if len(r) != 8:
                errs.append("montage %d 行%d 长度 %d != 8: %r"
                            % (mno, ri, len(r), r))
            for ch in r:
                if ch not in "CBYPNTX":
                    errs.append("montage %d 行%d 含非法字符 %r" % (mno, ri, ch))
    return errs


def build_map() -> dict[int, str]:
    """gid -> 字母（C/B/Y/P/N/T/X）。"""
    out: dict[int, str] = {}
    for mno, s in _rows_flat().items():
        for i, ch in enumerate(s):
            out[mno * 48 + i] = ch
    return out


def build_class_map() -> dict[int, int]:
    """gid -> class id（跳过 X）。"""
    return {g: SHORT2ID[c] for g, c in build_map().items() if c in SHORT2ID}


if __name__ == "__main__":
    errs = validate()
    if errs:
        print("❌ 校验失败:")
        for e in errs:
            print("   " + e)
        raise SystemExit(1)
    print("✅ 结构校验通过（9 张 × 6 行 × 8 列 = 432 格）")

    m = build_map()
    print("gid 覆盖: %d 个 (0~%d)" % (len(m), max(m)))
    miss = [g for g in range(430) if g not in m]
    print("缺失 gid(0~429): %s" % (miss if miss else "无 ✅"))

    from collections import Counter
    cnt = Counter(m[g] for g in range(430))
    print()
    print("%-4s %-18s %5s" % ("字母", "类别", "数量"))
    print("-" * 32)
    for k in "CBYPNTX":
        name = ZH.get(CLASS_NAMES[SHORT2ID[k]]) if k in SHORT2ID else "跳过"
        print("%-4s %-18s %5d" % (k, name, cnt.get(k, 0)))
    print("-" * 32)
    print("%-23s %5d" % ("合计", sum(cnt.values())))
    print("可用（不含跳过）: %d" % sum(v for k, v in cnt.items() if k in SHORT2ID))
