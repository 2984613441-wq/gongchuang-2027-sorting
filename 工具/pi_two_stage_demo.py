#!/usr/bin/env python3
"""屏幕两段显示探针（2026-09-18）：识别到物体 → 分拣成功，各出一张 1024x600 图。

为什么单独一个脚本：run_chain.py 真实模式有多道 fail-closed 门（[DropPoints] 六盒、
--image-dir、--names-file…），过不去就 SystemExit，屏幕根本走不到。本脚本只做
"屏幕两段显示"这一件事：走**真实渲染路径**（display_hdmi.TwoStageDisplay）合成两帧，
存 PNG；要直接上屏就加 --fb0（复用已验证的 FramebufferFrameOutput，按 fb 真实 bpp
打包）。不碰串口、不碰落点表、不改 run_chain、不碰 /dev/fb0 以外的设备。

主机（只出图）：
    py -3 工具/pi_two_stage_demo.py --out 工具/screen_samples
树莓派（出图 + 直接写屏；写屏前先停桌面，fkms 下 X 占着屏 fb0 就不显示）：
    sudo systemctl stop lightdm
    python3 pi_two_stage_demo.py --out /home/pi/frames --fb0 --hold 3
    sudo systemctl start lightdm
或只出图，再用已验证的轮播工具上屏：
    python3 /home/pi/pi_blit_png.py /dev/fb0 '/home/pi/frames/*.png' --auto 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

SCREEN = (1024, 600)


def import_display_stack():
    """导入真实渲染路径；树莓派上由 install.sh 写进 venv 的 .pth，主机上兜底加 path。"""
    here = Path(__file__).resolve().parent
    candidates = [
        os.environ.get("EC_SRC", ""),
        str(here.parent / "电控" / "src"),  # 仓库内：工具/ 的兄弟目录
        "/opt/ec-chain/src",               # 树莓派部署约定
        str(here),                         # 与 run_chain.py 同目录放下时
    ]
    try:
        from electrical_control.rpi.display_hdmi import TwoStageDisplay  # noqa: F401
    except ImportError:
        for cand in candidates:
            if cand and Path(cand).is_dir():
                sys.path.insert(0, cand)
                try:
                    from electrical_control.rpi.display_hdmi import TwoStageDisplay  # noqa: F401
                    break
                except ImportError:
                    sys.path.pop(0)
        else:
            raise
    from electrical_control.rpi.display_hdmi import (
        FramebufferFrameOutput,
        TwoStageDisplay,
        TwoStageInfo,
    )

    return TwoStageDisplay, TwoStageInfo, FramebufferFrameOutput


def main() -> int:
    ap = argparse.ArgumentParser(
        description="屏幕两段显示：合成 识别到物体 / 分拣成功 两张 1024x600 图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out", default=".", help="PNG 保存目录（不存在则创建）")
    ap.add_argument("--fb0", action="store_true",
                    help="同时写 /dev/fb0（树莓派；写屏前先 sudo systemctl stop lightdm）")
    ap.add_argument("--fb", default="/dev/fb0", help="framebuffer 设备（默认 /dev/fb0）")
    ap.add_argument("--hold", type=float, default=3.0, help="--fb0 时每张停留秒数")
    ap.add_argument("--font", default=None, help="中文字体路径（默认自动探测 wqy-zenhei）")
    ap.add_argument("--target-seq", type=int, default=3, help="序号（假数据）")
    ap.add_argument("--box-id", type=int, default=3, help="货格号（假数据）")
    ap.add_argument("--name", default="红色三棱柱", help="货物名称（假数据）")
    ap.add_argument("--color", default="红色", help="颜色（假数据）")
    ap.add_argument("--shape", default="三棱柱", help="形状（假数据）")
    args = ap.parse_args()

    try:
        TwoStageDisplay, TwoStageInfo, FramebufferFrameOutput = import_display_stack()
    except ImportError as exc:
        print(f"导入 electrical_control 失败：{exc!r}")
        print("  树莓派：用链路的解释器跑，或 EC_SRC=/opt/ec-chain/src python3 pi_two_stage_demo.py")
        print("  主机：  PYTHONPATH=电控/src py -3 工具/pi_two_stage_demo.py")
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list = []
    display = TwoStageDisplay(
        width=SCREEN[0], height=SCREEN[1], frame_output=frames.append, font_path=args.font
    )
    print(f"字体: {display.font_path or 'PIL 内置（只支持 latin-1，中文会是方块）'}")
    if display.font_path is None:
        print("  ⚠️ 没探测到中文字体 —— 画面其它部分仍然可验，但中文字形验不了。")
        print("     装法（需你执行）：sudo apt install fonts-wqy-zenhei")

    info = TwoStageInfo(
        target_seq=args.target_seq,
        box_id=args.box_id,
        name=args.name,
        color=args.color,
        shape=args.shape,
    )
    display.show_recognized(info)   # 段1：识别到待分拣物体
    display.show_success(info)      # 段2：已放进转盘 / 落料位

    paths = []
    for name, frame in zip(("two_stage_1_recognized", "two_stage_2_success"), frames):
        path = out_dir / f"{name}.png"
        frame.save(path)
        paths.append(path)
        print(f"已生成 {frame.size[0]}x{frame.size[1]} {frame.mode}: {path}")

    if args.fb0:
        try:
            output = FramebufferFrameOutput(args.fb, size=SCREEN)
        except Exception as exc:  # FramebufferFormatError / OSError：说清楚再退
            print(f"读不到 {args.fb} 的真实格式，拒绝靠猜写屏：{exc}")
            return 2
        print(f"{args.fb}: {output.format}（读自 sysfs，不是猜的）")
        for path, frame in zip(paths, frames):
            output(frame)
            print(f"已上屏 {path.name}，停 {args.hold:g}s")
            time.sleep(args.hold)
    else:
        print("（未加 --fb0：只出了图，没有写屏）")
        print("  上屏：python3 工具/pi_blit_png.py /dev/fb0 '<目录>/*.png' --auto 3")

    print("肉眼判据：屏上应依次出现 ①「识别到待分拣物体」+ 货格号/名称/颜色/形状 "
          "②「分拣成功」大字（绿色）。中文若是方块 = 字体没装，不是屏坏了。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
