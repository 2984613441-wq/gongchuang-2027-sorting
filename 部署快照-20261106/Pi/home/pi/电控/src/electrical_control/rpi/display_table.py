#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R-D03「逐件累加表格」渲染（2026-09-22 DSH 新增）。

为什么单独一个模块：
  · 现有 `TableDisplay`（display_hdmi.py:730 起）是**按货格号固定 6 行**的统计表、
    列里没有"具体货物名称"、图片走另一套文件名映射（imageN.jpeg）⇒ 与赛规 R-D03
    「每件货物存入储物盒后显示 序号/具体货物名称/图片/分拣成功总数量」不符，不能直接用。
  · 现有 `HdmiDisplayRenderer` 是**单件一屏**的四栏面板（合规，但不是用户要的表格形式）。
  ⇒ 这里新写一个"逐件追加"的表格帧：每完成一件追加一行，最多显示最近 max_rows 行，最新一行高亮。

设计约束（与项目其它显示一致）：
  · **fail-closed**：任何一张货物图片加载失败 ⇒ 抛 ValueError，**不返回半张表**
    （调用方应当保留屏幕上一帧，而不是显示残缺内容）。
  · 不碰 wire / 协议 / 固件：本模块只画像素。
"""
from __future__ import annotations

from typing import Callable, Sequence

# 与 display_hdmi.py 保持同一套配色口径
_BG = (16, 20, 28)
_TEXT = (238, 242, 248)
_MUTED = (150, 162, 178)
_ACCENT = (0, 170, 255)
_ROW_HL = (28, 46, 66)      # 最新一行高亮底色
_ROW_ALT = (24, 30, 40)     # 隔行底色
_LINE = (60, 72, 88)

# 列的位置（针对 1024x600）
_COL_SEQ = 40
_COL_NAME = 150
_COL_IMG = 470
_COL_TOTAL = 830
_IMG_W, _IMG_H = 150, 68

ImageLoader = Callable[[int], "object"]


def _font(font_path: str | None, size: int):
    from PIL import ImageFont
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default()
    except Exception:  # pragma: no cover
        return None


def compose_table_frame(
    rows: Sequence[tuple[int, str, int, int]],
    *,
    image_loader: ImageLoader,
    font_path: str | None = None,
    width: int = 1024,
    height: int = 600,
    max_rows: int = 6,
    highlight_last: bool = True,
    title: str = "分拣信息",
):
    """把逐件记录渲染成一帧表格；返回 PIL.Image。

    rows: 按完成顺序的 (序号, 具体货物名称, image_id, 分拣成功总数量)
          —— 末列的"总数量"是**该件完成时的累计值**（与用户给的示例一致）
    """
    from PIL import Image, ImageDraw

    if not isinstance(width, int) or width <= 0 or not isinstance(height, int) or height <= 0:
        raise ValueError("width/height must be positive ints")
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")

    shown = list(rows)[-max_rows:]          # 只留最近 max_rows 行
    canvas = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(canvas)

    # 表头
    draw.rectangle((0, 0, width, 64), fill=(24, 30, 40))
    draw.text((_COL_SEQ, 16), title, font=_font(font_path, 30), fill=_TEXT)
    hy = 78
    draw.text((_COL_SEQ, hy), "序号", font=_font(font_path, 24), fill=_MUTED)
    draw.text((_COL_NAME, hy), "货物名称", font=_font(font_path, 24), fill=_MUTED)
    draw.text((_COL_IMG, hy), "图片", font=_font(font_path, 24), fill=_MUTED)
    draw.text((_COL_TOTAL, hy), "分拣成功总数量", font=_font(font_path, 24), fill=_MUTED)
    draw.line((24, 112, width - 24, 112), fill=_LINE, width=2)

    y0 = 122
    row_h = (height - y0 - 16) // max(max_rows, 1)
    row_h = min(row_h, 78)

    for i, (seq, name, image_id, total) in enumerate(shown):
        y = y0 + i * row_h
        is_last = highlight_last and (i == len(shown) - 1)
        if is_last:
            draw.rectangle((16, y - 4, width - 16, y + row_h - 8), fill=_ROW_HL)
        elif i % 2 == 1:
            draw.rectangle((16, y - 4, width - 16, y + row_h - 8), fill=_ROW_ALT)

        # 序号 / 名称 / 总数量
        draw.text((_COL_SEQ + 8, y + 8), str(seq), font=_font(font_path, 38),
                  fill=_ACCENT if is_last else _TEXT)
        draw.text((_COL_NAME, y + 14), str(name), font=_font(font_path, 32), fill=_TEXT)
        draw.text((_COL_TOTAL + 60, y + 10), str(total), font=_font(font_path, 40),
                  fill=_ACCENT if is_last else _TEXT)

        # 图片缩略图（fail-closed：取不到就抛，绝不留半张表）
        try:
            img = image_loader(int(image_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"货物图片加载失败 image_id={image_id}: {exc!r}") from exc
        if img is None or not hasattr(img, "resize"):
            raise ValueError(f"货物图片无效 image_id={image_id}: {img!r}")
        thumb = img.convert("RGB").copy()
        thumb.thumbnail((_IMG_W, _IMG_H))
        px = _COL_IMG + (_IMG_W - thumb.width) // 2
        py = y + (row_h - 8 - thumb.height) // 2
        draw.rectangle((_COL_IMG, y, _COL_IMG + _IMG_W, y + row_h - 8), outline=_LINE, width=1)
        canvas.paste(thumb, (px, py))

        draw.line((24, y + row_h - 8, width - 24, y + row_h - 8), fill=_LINE, width=1)

    return canvas


if __name__ == "__main__":  # pragma: no cover - 极简自检
    from PIL import Image as _I

    def _fake(image_id: int):
        return _I.new("RGB", (300, 200), (200, 60 + 20 * image_id, 60))

    frame = compose_table_frame(
        [(1, "五棱柱", 1, 1), (2, "正四面体", 2, 2), (3, "橙色圆柱", 6, 3)],
        image_loader=_fake,
    )
    assert frame.size == (1024, 600), frame.size
    try:
        compose_table_frame([(1, "x", 9, 1)], image_loader=lambda i: (_ for _ in ()).throw(ValueError("boom")))
        raise AssertionError("图片缺失时必须抛异常（fail-closed）")
    except ValueError:
        pass
    print("SELF_CHECK_OK", frame.size)
