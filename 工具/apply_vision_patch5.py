# -*- coding: utf-8 -*-
"""④-②(2026-09-21) 视觉侧接入「机构扫掠遮罩」（c9 门）。

锚点全部断言"恰好命中一次"，任一处不满足就整体中止、**不写任何文件**。
改完必须 `py_compile`（本轮已经因为字面量 \\n 把生产文件写坏过一次）。

设计要点：
  · c9 只对 black 生效；只看黑候选 bbox 内落在遮罩里的比例。
  · 生产侧遮罩文件**不存在时整道门不生效** ⇒ 零行为变化（可安全先推上去）。
  · 取证脚本用**同一份遮罩**（否则又变成"取证与生产输入不同"）。
"""
import hashlib
import os
import sys

ROOT = r"C:\Users\29845\Desktop\工创赛"
DEPLOY = os.path.join(ROOT, "视觉", "src", "maixcam_deploy")
PROD = os.path.join(DEPLOY, "stage1_color_v6_send.py")
FORE = os.path.join(DEPLOY, "forensic_v6_frame.py")

CONST_BLOCK = '''KERNEL = np.ones((3, 3), np.uint8)
# ④-②(2026-09-21) 机构扫掠遮罩：夹爪与 X/Y 轴黑方框**本身就是黑的**，与黑圆柱同色。
# 实测三张不同件的实拍互比：件 bbox 内帧间变化 36.9~67.3%，那两块固定黑物内 0.00~0.06%
# ⇒ 颜色/亮度/形状/面积全都分不开，唯一与光照无关的判据是"动过没有"。
# 为什么非做不可：现在挡住幻影的余量只有 3px / 4.6%（短边 59 vs M2 下限 62、
# 面积 2470 vs 2600），而幻影自身帧间抖动 ±10% ⇒ 换个光照它就会通过 M2 变成"像件"的目标。
# 由 make_gripper_mask.py 一次性标定产出（那一步由人手动移动机构，本文件绝不自主动）。
# ⚠️ 文件不存在 ⇒ 这道门**完全不生效**，行为与今天逐字节相同。
GRIPPER_MASK_PATH = "/root/forensic/gripper_mask.png"
GRIPPER_MASK_OVERLAP_MAX = 0.0   # 黑候选 bbox 内允许落在遮罩里的比例；0 = 必须完全在遮罩外
'''

GM_PREP = '''                     sat=_sat, rows=[])
    # ④-② 遮罩与 hsv 同口径：先按同一个 scale 缩到 det 尺寸，再裁到同一个 ROI，
    # 于是黑候选的 (x,y,w,h) 可以直接索引它，不需要第二套坐标换算。
    _gm = None
    if gripper_mask is not None:
        _gm = gripper_mask
        if scale < 1.0:
            _gm = cv2.resize(_gm, (width, height), interpolation=cv2.INTER_NEAREST)
        _gm = _gm[y0:y1, x0:x1] > 0
'''

C9_GATE = '''            if min(w, h) < MIN_BBOX_SIDE_DET or area < MIN_AREA_DET_PX:
                _bump("c7_min_size", color)
                _mark(_tr, "c7_min_size")
                continue
            # ④-②(2026-09-21) c9 机构扫掠遮罩：**只对 black 生效**。
            # 夹爪与 X/Y 轴黑方框会动，件放好后不动 —— 差分信号差 3 个数量级。
            # 遮罩为 None（没标定过）时整段跳过 ⇒ 零行为变化。
            if _gm is not None and color == "black":
                _ov = float(_gm[y:y + h, x:x + w].mean()) if (w and h) else 0.0
                _mark(_tr, gripper_overlap=_ov)
                if _ov > GRIPPER_MASK_OVERLAP_MAX:
                    _bump("c9_gripper_mask", color)
                    _mark(_tr, "c9_gripper_mask")
                    continue
'''

GM_LOAD = '''        print("V6 AE/AWB lock unavailable: %s（继续用自动曝光）" % _exc)
    # ④-② 机构扫掠遮罩：只在文件存在时启用。**绝不在生产循环里自动标定/动机构。**
    gripper_mask = None
    try:
        if os.path.exists(GRIPPER_MASK_PATH):
            gripper_mask = cv2.imread(GRIPPER_MASK_PATH, cv2.IMREAD_GRAYSCALE)
            if gripper_mask is None:
                print("V6 GRIPPER MASK 读不了：%s ⇒ c9 门不生效" % GRIPPER_MASK_PATH)
            else:
                _n = int(cv2.countNonZero(gripper_mask))
                print("V6 GRIPPER MASK 已载入 %s  白像素 %d (%.2f%%)"
                      % (GRIPPER_MASK_PATH, _n, 100.0 * _n / gripper_mask.size))
        else:
            print("V6 GRIPPER MASK 不存在（%s）⇒ c9 门不生效；"
                  "标定见 make_gripper_mask.py" % GRIPPER_MASK_PATH)
    except Exception as _exc:
        print("V6 GRIPPER MASK 载入失败：%s ⇒ c9 门不生效" % _exc)
'''

FORE_GM = '''    tr = {}
    # ④-② 取证必须用**和生产线同一份遮罩**，否则又变成"取证与生产输入不同"（⑤ 的病）。
    _gm = None
    _gmp = getattr(M, "GRIPPER_MASK_PATH", None)
    if _gmp and os.path.exists(_gmp):
        _gm = cv2.imread(_gmp, cv2.IMREAD_GRAYSCALE)
        if _gm is None:
            print("[forensic] 遮罩读不了：%s" % _gmp)
    results, roi_320 = M.analyze(pixels, input_rgb=input_rgb,
                                  detect_size=detect_size, trace=tr,
                                  gripper_mask=_gm)
'''


def patch(path, pairs):
    with open(path, "rb") as fh:
        raw = fh.read()
    old = raw.decode("utf-8")
    print("=== %s\n    before sha256 = %s" % (os.path.basename(path),
                                              hashlib.sha256(raw).hexdigest()))
    new = old
    for i, (a, b) in enumerate(pairs, 1):
        n = new.count(a)
        assert n == 1, "%s 第 %d 处锚点命中 %d 次（要求恰好 1 次）：\n%r" % (
            os.path.basename(path), i, n, a[:120])
        new = new.replace(a, b)
        print("    [%d] OK" % i)
    assert new != old
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    with open(path, "rb") as fh:
        raw2 = fh.read()
    print("    after  sha256 = %s\n    bytes %d -> %d"
          % (hashlib.sha256(raw2).hexdigest(), len(raw), len(raw2)))


PROD_PAIRS = [
    ("import time\n\nimport cv2", "import os\nimport time\n\nimport cv2"),
    ("KERNEL = np.ones((3, 3), np.uint8)\n", CONST_BLOCK),
    ("def analyze(pixels, input_rgb=False, detect_size=None, trace=None):",
     "def analyze(pixels, input_rgb=False, detect_size=None, trace=None,\n"
     "            gripper_mask=None):"),
    ("                c7_min_size=0, c8_saturated=0)",
     "                c7_min_size=0, c8_saturated=0, c9_gripper_mask=0)"),
    ("                     sat=_sat, rows=[])\n", GM_PREP),
    ('            if min(w, h) < MIN_BBOX_SIDE_DET or area < MIN_AREA_DET_PX:\n'
     '                _bump("c7_min_size", color)\n'
     '                _mark(_tr, "c7_min_size")\n'
     '                continue\n', C9_GATE),
    ('        print("V6 AE/AWB lock unavailable: %s（继续用自动曝光）" % _exc)\n',
     GM_LOAD),
    ("            detections, roi = analyze(rgb, input_rgb=True)",
     "            detections, roi = analyze(rgb, input_rgb=True,\n"
     "                                      gripper_mask=gripper_mask)"),
]

FORE_PAIRS = [
    ('    "c7_min_size": "c7 M2 min_size",\n}',
     '    "c7_min_size": "c7 M2 min_size",\n'
     '    "c9_gripper_mask": "c9 gripper_mask",\n}'),
    ('        print("   reject  c1_area=%d  c2_border=%d  c3_aspect_extent=%d  "\n'
     '              "c4_color_frac=%d  c5_black_core=%d  c7_min_size=%d"\n'
     '              % (rec["rej"]["c1_area"], rec["rej"]["c2_border"],\n'
     '                 rec["rej"]["c3_aspect_extent"], rec["rej"]["c4_color_frac"],\n'
     '                 rec["rej"]["c5_black_core"], rec["rej"]["c7_min_size"]))',
     '        print("   reject  c1_area=%d  c2_border=%d  c3_aspect_extent=%d  "\n'
     '              "c4_color_frac=%d  c5_black_core=%d  c7_min_size=%d  "\n'
     '              "c9_gripper_mask=%d"\n'
     '              % (rec["rej"]["c1_area"], rec["rej"]["c2_border"],\n'
     '                 rec["rej"]["c3_aspect_extent"], rec["rej"]["c4_color_frac"],\n'
     '                 rec["rej"]["c5_black_core"], rec["rej"]["c7_min_size"],\n'
     '                 rec["rej"]["c9_gripper_mask"]))'),
    ('    tr = {}\n'
     '    results, roi_320 = M.analyze(pixels, input_rgb=input_rgb,\n'
     '                                  detect_size=detect_size, trace=tr)\n', FORE_GM),
    ('        "max_area_320": tr["max_area_320"], "sat": tr["sat"], "colors": {},',
     '        "max_area_320": tr["max_area_320"], "sat": tr["sat"], "colors": {},\n'
     '        "gripper_mask": ("%s 白像素 %d" % (_gmp, int(cv2.countNonZero(_gm)))\n'
     '                         if _gm is not None else "无（c9 门不生效）"),'),
    ('    print("XCHECK     : %s  （按色重新打包后的闸计数 vs 生产函数自己的 _REJ）" % xcheck)',
     '    print("XCHECK     : %s  （按色重新打包后的闸计数 vs 生产函数自己的 _REJ）" % xcheck)\n'
     '    print("gripperMSK : %s" % report.get("gripper_mask", "-"))'),
]


def main():
    patch(PROD, PROD_PAIRS)
    patch(FORE, FORE_PAIRS)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
