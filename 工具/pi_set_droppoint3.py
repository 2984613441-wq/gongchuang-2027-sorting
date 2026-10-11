#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「3 个固定落点」写进 /home/pi/sorting_config.ini 的 [DropPoints]（6 格）。

背景（2026-09-21 用户裁决）
--------------------------
转盘方案改为：**固定 3 个落点，转盘转 180° 到另一侧的另外 3 个落点**。
⇒ 6 个货格分两组、每组 3 个；**两组共用同样的 3 个滑台坐标**，
   由转盘停在 A 侧还是 B 侧决定实际落在哪个物理格。

⇒ 本工具把 [DropPoints] 写成：
       1 = A1x, A1y   4 = A1x, A1y
       2 = A2x, A2y   5 = A2x, A2y
       3 = A3x, A3y   6 = A3x, A3y
   并在节内注明「4/5/6 与 1/2/3 同坐标，靠转盘翻 180° 区分」。

⚠️ 坐标口径（别搞错）
--------------------
[DropPoints] 用的是 **滑台记账坐标**（mm），链**原样下发**、**不叠加 ToolOffset**
（`电控/src/electrical_control/rpi/vision_ingest.py:231-236`）。
* 夹爪**物理位置** = 滑台坐标 + (120.5, 43.5)   （`calibration_config.ini:134-135`）
* HOME（最里角）滑台坐标 = (−95.0, −97.5)
⇒ 用户说「距最里角 X a cm / Y b cm」要换成滑台坐标：
     滑台 x = a*10 − 120.5 ；  滑台 y = b*10 − 43.5

用法（在树莓派上跑，**主机上没有 configparser 场景就别用**）
-----------------------------------------------------------
    python3 pi_set_droppoint3.py A1x A1y A2x A2y A3x A3y
例（把 3 个点设成滑台坐标 (14.5,19.0) / (54.5,19.0) / (14.5,59.0)）：
    python3 pi_set_droppoint3.py 14.5 19.0 54.5 19.0 14.5 59.0

行为
----
1. 先备份成 sorting_config.ini.bak-3pt-<时间戳>
2. **整节原子替换**（避免"半新半旧"的落点表）
3. 写入前**拦截越界**：滑台可达域 x ∈ [−95, +90]、y ∈ [−97.5, +92.5]，
   且**单件耗时约束** x + y ≤ 127.3 mm（超过会撞 15 秒失活窗）
4. 写完后**用生产加载器回读自检**（load_drop_points），不通过就自动回滚
"""

from __future__ import annotations

import configparser
import shutil
import sys
import time
from pathlib import Path

CONFIG = Path("/home/pi/sorting_config.ini")

# 滑台可达域（ec_motion_plan.h:94/106/126/127）
X_MIN, X_MAX = -95.0, 90.0
Y_MIN, Y_MAX = -97.5, 92.5
# N6 时间模型：x + y 超过这个值，单件就会超 15 秒失活窗
XY_SUM_MAX = 127.3


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"❌ {msg}")
    sys.exit(1)


def guard(x: float, y: float, idx: int) -> None:
    if not (X_MIN <= x <= X_MAX):
        fail(f"第 {idx} 个点 x={x} 越界（滑台可达 x ∈ [{X_MIN}, {X_MAX}]）")
    if not (Y_MIN <= y <= Y_MAX):
        fail(f"第 {idx} 个点 y={y} 越界（滑台可达 y ∈ [{Y_MIN}, {Y_MAX}]）")
    if x + y > XY_SUM_MAX:
        fail(
            f"第 {idx} 个点 x+y={x + y:.1f} 超过 {XY_SUM_MAX}"
            f"（会撞 15 秒失活窗，单件必超时）"
        )


def replace_section(text: str, name: str, new_body: str) -> str:
    """把 [name] 这一节的正文换成 new_body，其余部分（含注释）逐字节保留。

    为什么不用 configparser：它读不出注释，write() 是整文件重写 ⇒ 注释全丢。
    **找不到该节就原样返回**，调用方据此中止（绝不静默写坏文件）。
    """
    header = "[" + name + "]"
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    found = False
    i = 0
    while i < len(lines):
        if lines[i].strip() == header:
            found = True
            out.append(lines[i])
            i += 1
            while i < len(lines) and not (
                lines[i].lstrip().startswith("[") and lines[i].rstrip().endswith("]")
            ):
                i += 1
            out.append(new_body)
            continue
        out.append(lines[i])
        i += 1
    return "".join(out) if found else text


def main(argv: list[str]) -> int:
    if len(argv) != 7:
        print(__doc__)
        return 2

    try:
        vals = [float(a) for a in argv[1:]]
    except ValueError:
        return fail("参数必须是 6 个数字：A1x A1y A2x A2y A3x A3y")

    pts = [(vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])]
    for i, (x, y) in enumerate(pts, 1):
        guard(x, y, i)

    if not CONFIG.exists():
        return fail(f"配置不存在：{CONFIG}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = CONFIG.with_name(CONFIG.name + f".bak-3pt-{ts}")
    shutil.copy(CONFIG, bak)
    print(f"✅ 已备份 → {bak.name}")

    # ⚠️ 2026-09-21 修：**不能**用 configparser.write() 整文件重写 —— configparser
    #    读不出注释，那样会把本文件**所有注释**抹掉（8.4KB 里注释占大半，含落点口径说明）。
    #    改成"只替换 [DropPoints] 一节、其余逐字节保留"，这才对得起 docstring 里
    #    "整节原子替换" 的说法。
    body = [
        "# 3 个固定落点 × 转盘 2 个方向（A/B 两组共用同样 3 个滑台坐标）",
        "# 坐标 = 滑台记账坐标 mm；物理位置 = 本值 + (120.5, 43.5)",
        "# 4/5/6 与 1/2/3 同坐标：靠转盘翻 180° 落到另一侧的物理格",
        "# 🔴 2026-09-21 现场实测（板子复位后全程只向正方向走，每段 STEP_RESULT=1）：",
        "#    ① 距 HOME (+7.0, +18.5) cm   ② (0.0, +14.5) cm   ③ (+14.0, +14.5) cm",
    ]
    for i in range(3):
        x, y = pts[i]
        body.append(f"{i + 1} = {x:g}, {y:g}")
    for i in range(3):
        x, y = pts[i]
        body.append(f"{i + 4} = {x:g}, {y:g}")
    new_section = "\n".join(body) + "\n"

    original = CONFIG.read_text(encoding="utf-8")
    replaced = replace_section(original, "DropPoints", new_section)
    if replaced == original:
        return fail("没能定位并替换 [DropPoints] —— 未写入任何内容（文件原样）")

    tmp = CONFIG.with_suffix(".ini.tmp")
    tmp.write_text(replaced, encoding="utf-8")
    tmp.replace(CONFIG)
    print("✅ 已写入（只替换 [DropPoints] 一节，其余含注释逐字节保留）")

    # 回读自检：用生产加载器，不用自己再解析一遍
    sys.path.insert(0, "/home/pi/电控/deploy")
    try:
        from run_chain import load_drop_points  # type: ignore

        got = load_drop_points(CONFIG)
        want = {
            **{i + 1: (int(round(pts[i][0] * 10)), int(round(pts[i][1] * 10))) for i in range(3)},
            **{i + 4: (int(round(pts[i][0] * 10)), int(round(pts[i][1] * 10))) for i in range(3)},
        }
        ok = got == want
        print(f"   回读（0.1mm）: {got}")
        print(f"   期望（0.1mm）: {want}")
        if not ok:
            shutil.copy(bak, CONFIG)
            return fail("回读与期望不符 —— 已自动回滚到备份")
        print("✅ 回读校验通过")
        print("\n   实际释放点（物理 mm）= 滑台 + ToolOffset(120.5, 43.5)：")
        for b in (1, 4):
            x, y = got[b]
            print(f"     货格 {b}: ({x / 10 + 120.5:.1f}, {y / 10 + 43.5:.1f}) mm")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 回读自检没做成（{exc}）—— 文件已写入，请手动核对")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
