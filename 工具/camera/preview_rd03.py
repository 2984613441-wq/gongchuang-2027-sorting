#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立预览：把【R-D03 合规四栏帧】直接打到 /dev/fb0（不跑链、不动机构）。

用途：区分两件事——
  ① 渲染/图片/字体/上屏这条路本身是否正常（本脚本能出图 ⇒ 正常 ✓）
  ② 还是"被后续帧覆盖"（那就改链的显示时序）

用法（在树莓派上）：
    PYTHONPATH=/home/pi/电控/src python3 /home/pi/preview_rd03.py <image_id> <序号> <总数量>
例：
    PYTHONPATH=/home/pi/电控/src python3 /home/pi/preview_rd03.py 5 3 3
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/pi/电控/src")

from PIL import Image  # noqa: E402

from electrical_control.rpi.display_hdmi import (  # noqa: E402
    FramebufferFrameOutput,
    HdmiDisplayRenderer,
)
from electrical_control.rpi.display import DisplayViewModel  # noqa: E402

# ItemTaskContext / ItemTaskPayload 的导入路径在不同版本里略有差异 ⇒ 逐个试
ItemTaskContext = ItemTaskPayload = None
for mod, names in (
    ("electrical_control.rpi", ("ItemTaskContext", "ItemTaskPayload")),
    ("electrical_control.protocol.item_context", ("ItemTaskContext", "ItemTaskPayload")),
):
    try:
        m = __import__(mod, fromlist=list(names))
        ItemTaskContext = ItemTaskContext or getattr(m, "ItemTaskContext", None)
        ItemTaskPayload = ItemTaskPayload or getattr(m, "ItemTaskPayload", None)
    except Exception:
        pass
if ItemTaskContext is None or ItemTaskPayload is None:
    m = __import__("electrical_control.rpi.display", fromlist=["*"])
    ItemTaskContext = ItemTaskContext or getattr(m, "ItemTaskContext", None)
    ItemTaskPayload = ItemTaskPayload or getattr(m, "ItemTaskPayload", None)
assert ItemTaskContext and ItemTaskPayload, "找不到 ItemTaskContext/ItemTaskPayload"

IMG_DIR = "/home/pi/images"
FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
NAMES = {
    "1": "青色正方体", "2": "绿色正方体", "3": "红色三棱柱",
    "4": "蓝色三棱柱", "5": "黑色圆柱", "6": "橙色圆柱",
}


def loader(image_id: int) -> Image.Image:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        try:
            return Image.open(f"{IMG_DIR}/{image_id}{ext}")
        except Exception:
            continue
    raise ValueError(f"图片未找到：{IMG_DIR}/{image_id}.[jpg|png|...]")


def main() -> int:
    image_id = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    seq = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    total = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    task = ItemTaskContext(
        round_id="preview",
        task_id=7,
        frame_seq=seq,
        payload=ItemTaskPayload(seq, image_id, image_id, 0, 0, 0, None, None),
    )
    out = FramebufferFrameOutput("/dev/fb0", size=(1024, 600))
    renderer = HdmiDisplayRenderer(
        width=1024, height=600,
        image_loader=loader,
        frame_output=out,
        font_path=FONT,
        task=task,
        seq_no=seq,          # 方案 C：序号用"本件序号"，不再用 success_count+1
    )
    view = DisplayViewModel(seq, NAMES.get(str(image_id), "未知名"), image_id, total, 0)
    renderer.present(view)   # 合成 + 写 /dev/fb0（失败会 fail-closed，不写半屏）
    print(f"RENDERED image_id={image_id} 序号={seq} 总数量={total} 名称={NAMES.get(str(image_id))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
