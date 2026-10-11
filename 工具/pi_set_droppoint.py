#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性写入 [DropPoints] 六格落点，并备份 + 用生产加载器回读自检。

为什么整节原子替换（而不是 sed 逐格改 / 跑 6 次）：
  与 `工具/pi_set_affine.py` 同样的理由 —— 中途失败会留下"半新半旧"的落点表
  （1..3 是新的、4..6 还是旧的），那比不改更危险，因为链会照着它把件投到错地方。

用法:
  python3 pi_set_droppoint.py <x_mm> <y_mm>

例（2026-09-20 用户定的转盘格中心 ⇒ 落点配置）:
  python3 pi_set_droppoint.py 14.5 19.0

⚠️ 这里填的是**滑台坐标**（= 链直接下发的 PLACE），不是物理位置。
   夹爪实际释放点 = 本值 + ToolOffset(120.5, 43.5)。
   ⇒ 格中心物理位置必须落在 x∈[25.5,210.5]、y∈[-54,136]（滑台可达域 + ToolOffset 平移），
     否则会超程（X/Y 无限位开关，超程会顶死）。
"""
import re
import shutil
import sys
import time

CONFIG = "/home/pi/sorting_config.ini"

# 滑台可达域（mm）。用于写入前的越界拦截。
REACH_X = (-95.0, 90.0)    # 固件 EC_MOTION_REACH_FAR_X_MM10 = 900 更严，取固件口径
REACH_Y = (-97.5, 92.5)
# N6 时间约束：落点 x+y 超过此值，单件会 >> 15s 失活窗
PLACE_SUM_MAX_MM = 127.3


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    try:
        x_mm, y_mm = float(sys.argv[1]), float(sys.argv[2])
    except ValueError:
        print("x/y 必须是数字（单位 mm）")
        return 1

    if not (REACH_X[0] <= x_mm <= REACH_X[1]):
        print("拒绝写入：x=%.1f 不在滑台可达域 [%.1f, %.1f]" % (x_mm, *REACH_X))
        return 1
    if not (REACH_Y[0] <= y_mm <= REACH_Y[1]):
        print("拒绝写入：y=%.1f 不在滑台可达域 [%.1f, %.1f]" % (y_mm, *REACH_Y))
        return 1
    if x_mm + y_mm > PLACE_SUM_MAX_MM:
        print("拒绝写入：x+y=%.1f 超过 %.1f（单件会超出 15 秒失活窗）"
              % (x_mm + y_mm, PLACE_SUM_MAX_MM))
        return 1

    bak = CONFIG + time.strftime(".bak-droppoint-%Y%m%d-%H%M%S")
    shutil.copy2(CONFIG, bak)

    with open(CONFIG, encoding="utf-8") as fh:
        lines = fh.readlines()

    in_section = False
    hit = 0
    out = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("["):
            in_section = stripped.startswith("[DropPoints]")
        if in_section and re.match(r"^[1-6]\s*=", stripped):
            out.append("%s= %s,%s\n" % (stripped[0], x_mm, y_mm))
            hit += 1
            continue
        out.append(ln)

    if hit != 6:
        print("只找到 %d 个货格条目（应为 6），未做任何写入" % hit)
        return 1

    with open(CONFIG, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(out)

    sys.path.insert(0, "/home/pi/电控/src")
    sys.path.insert(0, "/home/pi/电控/deploy")
    from run_chain import load_drop_points  # noqa: E402

    d = load_drop_points(CONFIG)
    want = (round(x_mm * 10), round(y_mm * 10))
    print("写入完成，备份:", bak)
    print("生产加载器回读:", d)
    print("校验 六格全为 %s 且恰好 6 格 ->" % (want,),
          all(v == want for v in d.values()) and len(d) == 6)
    print("夹爪实际释放点(mm): (%.1f, %.1f)" % (want[0] / 10 + 120.5, want[1] / 10 + 43.5))
    return 0


if __name__ == "__main__":
    sys.exit(main())
