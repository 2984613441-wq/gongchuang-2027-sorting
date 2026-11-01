#!/usr/bin/env python3
"""校验 MaixCAM 脚本的静态一致性（不执行、不依赖 maix 模块）。

检查项：
  · 语法
  · compute_masks_fast 返回 3 值 且 调用处解包 3 个（最易错）
  · 关键默认值
  · detect 传的是 frame 不是 numpy
  · 加载顺序 相机 → 显示 → 模型
  · del rgb 位置正确（在打印块之后）

用法：
  python _pi_tools/check_maix_script.py _pi_tools/maixcam_scripts/yolo_v4_fast.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python check_maix_script.py <script.py>")
        return 2
    p = Path(argv[1])
    if not p.is_file():
        print("❌ 文件不存在: %s" % p)
        return 1
    src = p.read_text(encoding="utf-8")

    ok_all = True

    def chk(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok_all
        ok_all = ok_all and cond
        mark = "✓" if cond else "✗"
        print("  %-34s %s %s" % (name, mark, detail))

    print("=" * 70)
    print("  静态检查: %s" % p.name)
    print("=" * 70)

    # 语法
    try:
        ast.parse(src)
        chk("语法", True)
    except SyntaxError as e:
        chk("语法", False, str(e))
        print("=" * 70)
        return 1

    lines = src.splitlines()

    # compute_masks_fast 返回几个值
    m = re.search(r"def compute_masks_fast.*?\n(.*?)\n\ndef ", src, re.S)
    if m:
        body = m.group(1)
        rets = re.findall(r"return\s+([^\n]+)", body)
        n_ret = len(rets[0].split(",")) if rets else 0
        chk("compute_masks_fast 返回 %d 个值" % n_ret, n_ret == 3)
        call = re.search(
            r"(\w+),\s*(\w+),\s*(\w+)\s*=\s*\n?\s*compute_masks_fast", src)
        chk("调用处解包 3 个", call is not None,
            "" if call else "（解包数量与返回值不一致会 ValueError）")
    else:
        chk("compute_masks_fast 存在", False)

    # 关键默认值
    chk("MASK 默认关闭 (0)",
        re.search(r'SHOW_MASK_STRIP"\s*,\s*"0"', src) is not None)
    chk("MASK_EVERY 默认 15",
        re.search(r'MASK_EVERY"\s*,\s*"15"', src) is not None)
    chk("MASK_SCALE 默认 0.25",
        re.search(r'MASK_SCALE"\s*,\s*"0\.25"', src) is not None)

    # API 用法
    chk("detect 传 frame（非 numpy）",
        "detector.detect(frame," in src)
    order = [src.index('camera.Camera'), src.index('display.Display'),
             src.index('nn.YOLO11')]
    chk("加载顺序 相机→显示→模型", order[0] < order[1] < order[2])
    chk("dual_buff = False", "DUAL_BUFF = False" in src)
    chk("image2cv copy=False", "copy=False" in src)

    # del rgb 位置
    code = [l for l in lines if not l.strip().startswith("#")]
    n_del = sum(1 for l in code if re.search(r"\bdel\s+rgb\b", l))
    chk("代码里 del rgb 只 1 处", n_del == 1, "(实际 %d)" % n_del)
    i_p = next((k for k, l in enumerate(lines) if "PRINT_EVERY == 0" in l), -1)
    i_d = next((k for k, l in enumerate(lines)
                if re.search(r"\bdel\s+rgb\b", l)
                and not l.strip().startswith("#")), -1)
    chk("del rgb 在打印块之后", i_p >= 0 and i_d > i_p,
        "(打印 %d 行, del %d 行)" % (i_p + 1, i_d + 1))

    # UI_SCALE
    chk("UI_SCALE 已定义", "UI_SCALE = float" in src)
    chk("UI_SCALE 被绘制函数使用", src.count("UI_SCALE") >= 6)

    print("=" * 70)
    print("  结果: %s" % ("✅ 全部通过" if ok_all else "❌ 有问题"))
    print("  行数: %d" % len(lines))
    print("=" * 70)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
