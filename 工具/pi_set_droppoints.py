#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改写 sorting_config.ini 的 [DropPoints] 六个落点为统一坐标（纯配置，无需重烧）。

用法： python3 pi_set_droppoints.py <x_mm> <y_mm> [ini路径]
例：   python3 pi_set_droppoints.py 20.0 20.0

实现说明（为什么不用正则）：
  上一版用 re.search(r"(^\\[DropPoints\\][^\\[]*?)(?=^\\[|\\Z)", DOTALL|MULTILINE)
  在这份文件上**匹配失败**（段确实存在，第 127 行）。为避免继续跟正则斗，
  改成逐行状态机：找到段头行，之后到下一个以 '[' 开头的行之前，
  把所有 `N = ...` 行改写成 `N = x, y`。更直白也更难错。

为什么要它：
  · 六个盒子现在全是同一个占位值 —— 不是"六盒布局"，而是"全投一个点"。
    用户已确认单一落点即可。
  · 落点往外挪会拉长路径，可能击穿 ec_app.c:553 的 15000ms 失活窗口
    （该窗口不被运动进展重置，超时即 DEADLINE_EXPIRED → FAULT_LOCK）。
    参考：HOME=最里角、80 步/mm 时，方形落点每往外 1mm，六条腿合计约 +320 步。
  · 每改一次都要实跑看总时长。
"""

import shutil
import sys
from pathlib import Path

DEFAULT_INI = "/home/pi/sorting_config.ini"


def rewrite_linear(lines, x, y):
    out = []
    in_section = False
    changed = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped.startswith("[DropPoints]")
            out.append(line)
            continue
        if in_section and "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key.isdigit():
                out.append("%s = %.1f, %.1f\n" % (key, x, y))
                changed += 1
                continue
        out.append(line)
    return out, changed


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    x = float(sys.argv[1])
    y = float(sys.argv[2])
    ini = Path(sys.argv[3] if len(sys.argv) > 3 else DEFAULT_INI)

    if not ini.exists():
        print("找不到 %s" % ini)
        return 3

    lines = ini.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines, n = rewrite_linear(lines, x, y)
    if n == 0:
        print("在 [DropPoints] 段内没找到 `N = ...` 形式的行")
        return 5

    backup = ini.with_suffix(ini.suffix + ".bak-droppoints")
    shutil.copy2(ini, backup)
    ini.write_text("".join(new_lines), encoding="utf-8")

    print("✅ 已改写 %d 个落点为 (%.1f, %.1f)" % (n, x, y))
    print("备份: %s" % backup)
    print("--- 改写后的 [DropPoints] ---")
    show = False
    for line in ini.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("["):
            show = s.startswith("[DropPoints]")
            if show:
                print(s)
            continue
        if show and s:
            print("  " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
