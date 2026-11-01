#!/usr/bin/env python3
"""人工判形结果（gid -> 6 类之一，或 SKIP）。

## 判据（2026-10-27 定，用户已确认"按你的来"）

    正方体        cube             顶面正方形、六个面相等
    长方体        cuboid           顶面明显长方形（细长）
    圆柱          cylinder         顶面圆形、平顶
    五棱柱        pentagonal_prism  顶面 5 条直边（"房子"形）
    圆锥          cone             锥形、有尖顶
    正四面体      tetrahedron      三角形（三个面）

## 怎么维护

按 montage 顺序分组填写。每个 gid 一个字母：
    C=cube  B=cuboid  Y=cylinder  P=pentagonal_prism  N=cone  T=tetrahedron
    X=SKIP（手/遮挡/看不清）

## 已完成进度

    gid   0~ 47  (montage 000)  ✅ 已判
    gid  48~ 95  (montage 001)  ✅ 已判
    gid  96~    (montage 002+)  ⏳ 待判
"""

from __future__ import annotations

SHORT2ID = {
    "C": 0,   # cube
    "B": 1,   # cuboid
    "Y": 2,   # cylinder
    "P": 3,   # pentagonal_prism
    "N": 4,   # cone
    "T": 5,   # tetrahedron
}

CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]

# ══════════════════════════════════════════════════════════════════════
# 判形表：每 48 个字母对应一张 montage（8×6 网格，从左到右、从上到下）
# ══════════════════════════════════════════════════════════════════════

# montage_000  gid 0~47
# 绿色/蓝色/黄色方块，顶面均为正方形 ⇒ 全部 cube
# X 位置：24(部分+手) 44(整格是手)
M000 = (
    "CCCCCCCC"   # 00-07
    "CCCCCCCC"   # 08-15
    "CCCCCCCC"   # 16-23
    "XCCCCCCC"   # 24-31  24=X
    "CCCCCCCC"   # 32-39
    "CCCCXCCC"   # 40-47  44=X
)

# montage_001  gid 48~95
# 48-53 黄方块 cube；54-57 红方块 cube；58,59 红圆锥；60-63 红方块
# 64-66 红五棱柱；67-70 红方块；71 手；72-75 绿方块；76 绿三角
# 77 手；78,79 绿方块；80,81 黄五棱柱；82 黄方块；83 手；84-88 黄方块
# 89,90 蓝方块；91 蓝五棱柱；92 部分；93-95 绿三角
M001 = (
    "CCCCCCCC"   # 48-55  (48-53 cube, 54,55 cube)
    "CCNNCCCC"   # 56-63  (56,57 cube, 58,59 cone, 60-63 cube)
    "PPPCCCCX"   # 64-71  (64-66 pentagon, 67-70 cube, 71 X)
    "CCCCCTXC"   # 72-79  (72-75 cube, 76 tetra, 77 X, 78,79 cube)
    "PPCCXCCC"   # 80-87  (80,81 pentagon, 82 cube, 83 X, 84-87 cube)
    "CCPCXTTT"   # 88-95  (88 cube, 89,90 cube, 91 pentagon, 92 X, 93-95 tetra)
)

# montage_002  gid 96~143
# 96-109 三角（绿/橙/红/蓝）；110-117 圆锥（红/绿）；118,119 绿三角
# 120-123 圆锥（绿/蓝）；124-126 蓝圆柱（圆顶）；127-129 蓝三角
# 130 蓝圆柱；131,133-139 红方块；132 木质假框；140 红三角；142 蓝方块
M002 = (
    "TTTTTXTT"   # 96-103  (101 手)
    "TXTTTTNN"   # 104-111 (105 手; 110,111 圆锥)
    "NNXNNNTT"   # 112-119 (114 手; 118,119 三角)
    "NNNNYYYT"   # 120-127 (120-123 圆锥; 124-126 圆柱; 127 三角)
    "TTYCXCCC"   # 128-135 (128,129 三角; 130 圆柱; 131 方块; 132 木; 133-135 方块)
    "CCCCTXCX"   # 136-143 (136-139 方块; 140 三角; 141 手; 142 方块; 143 手)
)
# montage_003  gid 144~191
# 144-158 方块（蓝/黄/绿）；159 起大量圆柱（黄/绿，圆形平顶）
# 圆柱是这批的关键补充 —— 之前 6 类里圆柱样本最少
M003 = (
    "CCCCCCCC"   # 144-151 蓝方块 + 黄方块
    "CCXCCCCY"   # 152-159 (154 手; 159 第一个黄圆柱)
    "YYYYYYYY"   # 160-167 绿/黄圆柱交替
    "YYYYYYYY"   # 168-175 绿/黄圆柱交替
    "YYYXYYYY"   # 176-183 (179 手)
    "YYYYYYYY"   # 184-191 黄圆柱为主
)

# montage_004  gid 192~239
# 混合场景：黄圆柱 + 蓝绿方块 + 红圆锥 + 五棱柱（202,221,222,225,227,230,231）
# 217,226,237,238,239 是纸板+笔 → 假框
M004 = (
    "YNYCNYCC"   # 192-199 (193 圆锥; 196 圆锥)
    "CYPCNYCC"   # 200-207 (202 五棱柱; 204 圆锥)
    "YCYCCYCC"   # 208-215
    "XXCCCPPC"   # 216-223 (216,217 假; 221,222 五棱柱)
    "CPXPCCPP"   # 224-231 (225 五棱柱; 226 假; 227,230,231 五棱柱)
    "CCCCCCXX"   # 232-239 (237,238,239 纸板假框)
)

# montage_005  gid 240~287
# 黄圆柱与蓝方块交替；247 绿五棱柱；278,282,286 红圆锥
# 240,243,245 纸板+笔 → 假框；271 手
M005 = (
    "XCCXCXCP"   # 240-247 (240,243,245 假; 247 五棱柱)
    "YCCYYXYC"   # 248-255 (248,251,252,254 圆柱; 253 遮挡)
    "YCYCYCYC"   # 256-263 黄圆柱/蓝方块交替
    "YYCYCYCX"   # 264-271 (271 手)
    "YCCYCCNY"   # 272-279 (278 圆锥)
    "CCNYCCNY"   # 280-287 (282,286 圆锥)
)

# montage_006  gid 288~326（最后一行只有 39 格）
# 红圆锥 + 绿四面体 + 黄圆柱 + 蓝方块 四种轮转；末尾 323-326 全是绿四面体
M006 = (
    "TCYCNYTC"   # 288-295
    "NYTCNYTC"   # 296-303
    "NYTCNYTC"   # 304-311
    "NYTCYTCY"   # 312-319
    "YTXTTTT"    # 320-326 (321 蓝色四面体; 322 手)
)

MONTAGES = {
    0: M000,
    1: M001,
    2: M002,
    3: M003,
    4: M004,
    5: M005,
    6: M006,
}


def build_map() -> dict[int, str]:
    """展开成 {gid: 短字母}。"""
    out: dict[int, str] = {}
    for mi, s in MONTAGES.items():
        for k, ch in enumerate(s):
            out[mi * 48 + k] = ch
    return out


if __name__ == "__main__":
    m = build_map()
    print("已判 gid 数: %d" % len(m))
    from collections import Counter
    cnt = Counter(v for v in m.values() if v != "X")
    print("分布:")
    for ch, n in sorted(cnt.items()):
        print("  %s %-18s %d" % (ch, CLASS_NAMES[SHORT2ID[ch]], n))
    print("  X SKIP             %d" % sum(1 for v in m.values() if v == "X"))
