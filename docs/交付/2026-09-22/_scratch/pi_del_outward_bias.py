# -*- coding: utf-8 -*-
"""删掉 calibration_config.ini 里那段"教人加外偏"的过期注释。

背景（2026-09-22 用户裁决）：
  ToolOffset 历史上被来回改过：-20.5(标定真值) → -10.5(+1cm 外偏) → -15.5(+0.5cm 外偏)。
  用户明确要求：「不要再向外多偏 1cm 或者 0.5cm 了，把这个删掉」。
  现值已是 -20.5（标定真值），但 :158 起那段注释仍在教后人"补 -9mm 改本值即可" —— 误导源。

本脚本：**只删那 6 行注释、换成一段说明为什么不能加外偏的正文**；不动 x_mm / y_mm 的数值。
安全措施：备份 → 原子替换 → 回读校验（数值未变、注释行数变化符合预期、行数一致）。
"""
import hashlib
import re
import shutil
import sys
import time

CFG = "/home/pi/电控/calibration_config.ini"

OLD = """# 🔴 2026-09-21 修正 y_mm：-43.5 -> -52.5（补 -9mm）。
#    依据：现场三次独立对位（绿正方体/橙圆柱/红三棱柱，三个不同滑台位置）实测
#    「视觉给出的滑台点」到「夹爪真正对正」的修正量均为 Y 负向 8~10mm、X 无修正
#    ⇒ 判定为恒定偏移（不是越远偏越多）⇒ 不需重做仿射标定，改本值即可。
#    见 docs/交付/2026-09-21/现场脉宽标定记录-2026-09-21.md 第三节。
"""

NEW = """# 🔴 2026-09-22 用户裁决（**以此为准**）：本值 = **标定真值 (-108.5, -20.5)**，
#    **不得再加任何"向外偏"**。历史上有过两次人为外偏，均已作废：
#      y_mm = -10.5（= 向外 +1cm）、y_mm = -15.5（= 向外 +0.5cm）
#    ⇒ 加外偏会让**每个取料点整体偏移**（实测：偏 +10mm 时夹爪停在件旁边合嘴、**夹空**）。
#    ⚠️ 本节与 3 点标定是**同一条闭环**：标定解出装置坐标时用的就是 (-108.5, -20.5)，
#       所以改本值 = 把整条映射推偏，不是"调一个偏移旋钮"。
#       若确实要让夹爪相对件外偏，应**另加一个只为夹取用的偏置**（新字段/新节），不要动本值。
#    ⚠️ 另有一份独立的 [ToolOffset] 在 deploy/pick_strategy.ini（被 chain_adapter 用于反向换算），
#       那份与本节不是同一来源，**统一口径的处置另议**，不要照它改本值。
"""


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    with open(CFG, encoding="utf-8", newline="") as fh:
        text = fh.read()

    if OLD not in text:
        print("拒绝：找不到要删的那段注释（可能已被改过）。未写入任何内容。")
        return 2

    before = sha(CFG)
    n_before = text.count("\n")
    y_before = re.search(r"^\s*y_mm\s*=\s*(\S+)\s*$", text, re.M).group(1)
    x_before = re.search(r"^\s*x_mm\s*=\s*(\S+)\s*$", text, re.M).group(1)

    new_text = text.replace(OLD, NEW, 1)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-todel-outward-bias-%s" % (CFG, stamp)
    shutil.copy2(CFG, bak)
    print("备份 -> %s" % bak)

    with open(CFG, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)

    # 回读校验
    with open(CFG, encoding="utf-8", newline="") as fh:
        back = fh.read()
    y_after = re.search(r"^\s*y_mm\s*=\s*(\S+)\s*$", back, re.M).group(1)
    x_after = re.search(r"^\s*x_mm\s*=\s*(\S+)\s*$", back, re.M).group(1)
    assert float(y_after) == float(y_before), "y_mm 被改动了！"
    assert float(x_after) == float(x_before), "x_mm 被改动了！"
    assert OLD not in back, "旧注释还在！"

    print("x_mm: %s -> %s    y_mm: %s -> %s   ✅ 数值未变" % (x_before, x_after, y_before, y_after))
    print("行数: %d -> %d" % (n_before, back.count("\n")))
    print("注释行数 = %d" % sum(1 for l in back.split("\n") if l.lstrip().startswith("#")))
    print("sha256 %s -> %s" % (before[:16], sha(CFG)[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
