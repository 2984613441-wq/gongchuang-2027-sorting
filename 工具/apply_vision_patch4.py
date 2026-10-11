# -*- coding: utf-8 -*-
"""第四轮视觉补丁：c2 改为「贴 >=2 条 ROI 边才丢」。

依据（2026-09-21 现场）：
  · 杆子/机架的深色带贴 2~3 条 ROI 边（实测 bbox(9,253,61,59) 贴 2 条；
    右侧竖带 (271,9,40,303) 贴 3 条）
  · 真实件只贴 1 条边（用户现场：蓝正方体 4/5 在识别框内，却被整件丢掉）
⇒ 「>=2 条边才丢」同时做到：放真件进来、继续挡固定暗物。
代价：贴 1 条边时中心偏向可见一侧（4/5 可见 ≈ 偏 4mm，在 5mm 预算内）；
      可见比例更低的由 M2 的绝对面积下限兜底。

断言式：不"恰好命中一次"就整体中止、不写任何文件。
用法: py -3 工具/apply_vision_patch4.py [--apply]
"""
import io, os, shutil, sys, time, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V6 = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "stage1_color_v6_send.py")

OLD = (
 '            if x <= 1 or y <= 1 or x+w >= hsv.shape[1]-1 or y+h >= hsv.shape[0]-1:\n'
 '                _REJ["c2_border"] += 1\n'
 '                continue\n'
)
NEW = (
 '            # C2 改判据(2026-09-21)：从「贴任意 1 条 ROI 边就丢」改成「贴 >=2 条才丢」。\n'
 '            # 实测依据：杆子/机架的深色带贴 2~3 条边（(9,253,61,59) 贴 2 条；\n'
 '            # (271,9,40,303) 贴 3 条），而真实件只贴 1 条边 —— 用户现场目击：\n'
 '            # 蓝正方体 4/5 在识别框内，却被现行 c2 整件丢掉。\n'
 '            # 代价：贴 1 条边时只能按可见部分算中心，会偏向可见一侧\n'
 '            # （4/5 可见 ≈ 偏 4mm，仍在 5mm 预算内）；可见更少的由 M2 面积下限兜底。\n'
 '            # ⚠️ 根因未治：ROI 只内缩 3%=4.37mm，比项目自身 5mm 误差预算还小，\n'
 '            #    c2 一直是在替一个"选得太小的 ROI"兜底。正解是重定取景/托盘位置。\n'
 '            _edge = ((x <= 1) + (y <= 1) + (x + w >= hsv.shape[1] - 1)\n'
 '                     + (y + h >= hsv.shape[0] - 1))\n'
 '            if _edge >= 2:\n'
 '                _REJ["c2_border"] += 1\n'
 '                continue\n'
)


def main():
    apply = "--apply" in sys.argv
    s = io.open(V6, encoding="utf-8").read()
    n = s.count(OLD)
    print("c2 anchor hit %d %s" % (n, "" if n == 1 else "  <<< MUST BE 1"))
    if n != 1:
        print("\nFAIL -> ABORT, nothing written.")
        return 1
    if not apply:
        print("\nDRY-RUN OK. add --apply.")
        return 0
    shutil.copy2(V6, V6 + ".bak-visionpatch4-" + time.strftime("%Y%m%d-%H%M%S"))
    io.open(V6, "w", encoding="utf-8", newline="").write(s.replace(OLD, NEW, 1))
    py_compile.compile(V6, doraise=True)
    print("APPLIED + py_compile OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
