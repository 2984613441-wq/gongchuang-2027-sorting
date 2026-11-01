#!/usr/bin/env python3
"""30° 斜视主相机的数据采集脚本（补拍用）

## 为什么要单独写一个

2026-10-27 实测发现：之前那批 161 张是「近正顶视、托盘竖放」
（托盘包围盒 650×720，宽 50.8% / 高 100%），
而现在相机改成 **30° 俯角、托盘横放**（1126×390，宽 88% / 高 54%）。
两者宽差 +37%、高差 −46% ⇒ **模型训练的是另一个世界，必须按新视角补拍**。

本脚本在 `cap_1s.py` 基础上加了：
  · **张数计数 + 布局进度提示**（每 LAYOUT_SHOTS 张提示换布局）
  · **自动分目录**（每次运行一个 session 目录，互不覆盖）
  · **目标张数提醒**（到 110 张后提醒可以停）
  · **保存前打印每张的序号**，方便回溯

## 采集计划（30 个布局 × 3~4 张 ≈ 110 张）

  布局 1~6   : 单个物件，分别放远/中/近（每形状一次）
  布局 7~12  : 两个同类，一前一后（远端被遮）
  布局 13~18 : 两个不同类，一前一后
  布局 19~24 : 5 个混放，标准赛题阵型
  布局 25~27 : 贴边角（远端最远 / 左右边）
  布局 28~30 : 3~6 个密集堆叠（最坏情况）

## 三个铁律

  1. 90% 的照片里必须有「远端物件」—— 不能只拍近端
  2. 至少 30 张要有明显前后遮挡（后面物件上 1/3 被前面挡住）
  3. **补光灯全程开着**，中途别关（光照不一致会废掉前后数据）

## 用法

在 MaixVision 里跑，或 ssh 执行：
    python3 /root/cap_tilt30.py

停止：Ctrl-C 或 MaixVision 停止按钮。

⚠️ 相机需要空闲；正在跑检测脚本时先停掉。
"""
from __future__ import annotations

import os
import time

from maix import app, camera, display, image

# ══════════════ 配置 ══════════════
FRAME_W, FRAME_H = 1280, 720
INTERVAL_S = 1.0                  # 每张间隔（秒）
OUTPUT_ROOT = "/root/dataset_tilt30"
LAYOUT_SHOTS = 4                  # 每多少张提示「该换布局了」
TARGET_MIN, TARGET_MAX = 110, 140  # 目标张数范围
SHOW_PREVIEW = True               # 是否在屏幕显示预览
WARMUP_S = 2.5                    # 预热（等 AE/AWB 收敛）

LAYOUTS = [
    "1~6   单件 · 远/中/近各放一次（每形状轮换）",
    "7~12  两件同类 · 一前一后（远端被遮）",
    "13~18 两件不同类 · 一前一后（跨类遮挡）",
    "19~24 五件混放 · 标准赛题阵型",
    "25~27 贴边角 · 远端最远 / 左右边缘",
    "28~30 密集堆叠 3~6 件（最坏情况）",
]


def main() -> int:
    session = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(OUTPUT_ROOT, "tilt30_" + session)
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 68)
    print("  30° 斜视主相机 · 数据采集")
    print("=" * 68)
    print("  输出目录 : %s" % out_dir)
    print("  间隔     : %.1f s/张" % INTERVAL_S)
    print("  目标     : %d ~ %d 张（每 %d 张提示换布局）"
          % (TARGET_MIN, TARGET_MAX, LAYOUT_SHOTS))
    print()
    print("  布局计划：")
    for l in LAYOUTS:
        print("    %s" % l)
    print()
    print("  🔴 铁律：① 90%% 照片要有远端物件 ② ≥30 张有明显前后遮挡")
    print("          ③ 补光灯全程开着，别中途关")
    print("=" * 68)

    try:
        cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    except Exception as e:
        print("❌ 相机打不开: %s" % e)
        print("   先执行：killall launcher_daemon")
        return 1

    disp = None
    if SHOW_PREVIEW:
        disp = display.Display()

    print("预热 %.1f s ..." % WARMUP_S)
    t0 = time.time()
    while time.time() - t0 < WARMUP_S and not app.need_exit():
        f = cam.read()
        if disp is not None and f is not None:
            disp.show(f)

    print("开始采集（Ctrl-C 停止）")
    print("-" * 68)

    n = 0
    t_last = 0.0
    try:
        while not app.need_exit():
            frame = cam.read()
            if frame is None:
                continue
            if disp is not None:
                disp.show(frame)

            now = time.time()
            if now - t_last < INTERVAL_S:
                continue
            t_last = now

            n += 1
            name = "img_%05d.jpg" % (n - 1)
            path = os.path.join(out_dir, name)
            try:
                frame.save(path)
            except Exception as e:
                print("  第 %d 张保存失败: %s" % (n, e))
                n -= 1
                continue

            # 每张打印，方便盯着看进度
            layout_idx = (n - 1) // LAYOUT_SHOTS
            layout_txt = ""
            if layout_idx < len(LAYOUTS):
                layout_txt = "  [布局 %s]" % LAYOUTS[layout_idx].split()[0]
            if n % LAYOUT_SHOTS == 0:
                print("  已拍 %3d 张%s  ← 换下一个布局" % (n, layout_txt))
            elif n % 10 == 1:
                print("  已拍 %3d 张%s" % (n, layout_txt))

            if n == TARGET_MIN:
                print()
                print("  ✅ 已到 %d 张（目标下限）—— 可以停了" % TARGET_MIN)
                print("     ！但先确认：≥30 张有前后遮挡？90%% 有远端物件？")
                print()
            elif n == TARGET_MAX:
                print()
                print("  ✅ 已到 %d 张（目标上限）—— 建议停止" % TARGET_MAX)
                print()

    except KeyboardInterrupt:
        print("用户中断")
    finally:
        files = [f for f in os.listdir(out_dir) if f.endswith(".jpg")]
        print("=" * 68)
        print("  结束：共 %d 张" % len(files))
        print("  目录: %s" % out_dir)
        if len(files) < TARGET_MIN:
            print("  ⚠️ 少于目标下限 %d 张，建议再补" % TARGET_MIN)
        print("=" * 68)
        print("  PC 上拉回（树莓派/PC 与 MaixCAM 同一热点时）：")
        print("    scp -r root@172.20.10.9:%s ." % out_dir)
        print("=" * 68)
    return 0


if __name__ == "__main__":
    main()
