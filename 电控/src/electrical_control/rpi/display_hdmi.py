"""Real HDMI display renderer: Pillow-composed full-screen frames (Pi -> HDMI).

Implements the ``DisplayRenderer`` protocol from ``rpi/display.py`` for the
competition display requirements (seq number / cargo name / cargo image /
total success count, shown before the next item may proceed). Each
``DisplayViewModel`` is composed into a 1024x600 RGB frame with Pillow and
handed to an injected output callback.

Nothing hardware-specific is hardcoded here. The screen size, the image
loader, the frame output and the font path are all constructor-injected.
The 1024x600 default exists only so host tests run without deployment
configuration; on the Raspberry Pi the resolution comes from the deployment
config (see docs/design/2026-08-29-hdmi-screen-arrival-verification.md).

Deployment notes (Raspberry Pi, all provided by configuration at deploy time):
- ``image_loader``: image_id -> PIL.Image, read from the local TF card;
- ``frame_output``: pushes the composed frame to the HDMI framebuffer
  (host tests save a file instead);
- ``font_path``: a CJK TTF (e.g. the wqy-zenhei fonts from
  ``fonts-wqy-zenhei``). With font_path=None PIL's built-in font is used and
  CJK glyphs render as boxes -- acceptable for host tests only.

Pillow is imported lazily so this module imports cleanly (and the rest of
the host-side chain can be tested) without Pillow installed.
"""

from __future__ import annotations

from typing import Callable

from electrical_control.protocol import DisplayContent
from electrical_control.rpi import ItemTaskContext, PendingRender
from electrical_control.rpi.display import DisplayViewModel

# image_id -> 货物图片（部署时由配置提供；host 测试用假图）
ImageLoader = Callable[[int], "PIL.Image.Image"]
# 合成帧输出（host: 存文件；树莓派: 屏显示；部署时由配置提供）
FrameOutput = Callable[["PIL.Image.Image"], None]


class ImageLoadError(ValueError):
    """The injected image_loader failed; fail-closed, no partial frame reaches the screen."""


# 默认分辨率仅用于 host 测试；部署时由配置提供（本屏规格 1024x600）。
_DEFAULT_WIDTH = 1024
_DEFAULT_HEIGHT = 600

_BACKGROUND = (14, 22, 40)
_TEXT = (240, 244, 250)
_ACCENT = (88, 166, 255)
_MUTED = (150, 165, 190)
_SUCCESS = (96, 220, 120)
_FAILURE = (240, 90, 90)

# 左栏货物图片区域 (x0, y0, x1, y1)，针对默认 1024x600 布局。
_IMAGE_BOX = (48, 150, 548, 560)


class HdmiDisplayRenderer:
    """Pillow-composes DisplayViewModel frames; implements the DisplayRenderer protocol.

    Constructed per item with the active ``ItemTaskContext`` so that
    ``PendingRender.complete()`` rebuilds the exact ``DisplayContent``
    (class_id recovered from ``task.payload.class_id``, as
    ``FakeDisplayRenderer`` does) whose crc32 lands in the ``RenderReceipt``
    the DISPLAY_ACK loop needs.
    """

    def __init__(
        self,
        *,
        width: int = _DEFAULT_WIDTH,   # 默认仅供 host 测试；部署时由配置提供
        height: int = _DEFAULT_HEIGHT,  # 默认仅供 host 测试；部署时由配置提供
        image_loader: ImageLoader,
        frame_output: FrameOutput,
        font_path: str | None = None,  # 部署时由配置提供（如 wqy-zenhei）；None = PIL 默认字体
        task: ItemTaskContext,
    ) -> None:
        if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
            raise ValueError("width must be a positive int")
        if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
            raise ValueError("height must be a positive int")
        self._width = width
        self._height = height
        self._image_loader = image_loader
        self._frame_output = frame_output
        self._font_path = font_path
        self._task = task

    def present(self, view: DisplayViewModel) -> PendingRender:
        """Compose one frame from the view, output it, and open the render.

        Fail-closed: if the cargo image cannot be loaded (image_loader
        raises) or returns a non-image, ``ImageLoadError`` (a ValueError)
        is raised and ``frame_output`` is never called, so the screen keeps
        its previous frame and no PendingRender is produced.
        """
        frame = self._compose_frame(view)
        self._frame_output(frame)
        content = DisplayContent(
            target_seq=view.target_seq,
            class_id=self._task.payload.class_id,  # 名称已在本地解析，class_id 从任务载荷恢复
            image_id=view.image_id,
            success_count=view.success_count,
            result_code=view.result_code,
        )
        return PendingRender(content, self._task)

    def _compose_frame(self, view: DisplayViewModel) -> "PIL.Image.Image":
        # 懒加载：无 Pillow 环境也能 import 本模块
        from PIL import Image, ImageDraw, ImageFont

        canvas = Image.new("RGB", (self._width, self._height), _BACKGROUND)
        draw = ImageDraw.Draw(canvas)

        # 序号（最大字号）
        draw.text(
            (48, 24),
            f"第 {view.target_seq} 件",
            font=self._font(ImageFont, 88),
            fill=_TEXT,
        )

        # 货物图片：等比缩放居中嵌入左栏
        img = self._load_cargo_image(view, Image)
        fitted, px, py = self._fit_into(img, Image, _IMAGE_BOX)
        draw.rectangle(_IMAGE_BOX, outline=_ACCENT, width=2)
        self._paste_clipped(canvas, fitted, px, py)

        # 右栏：货物名称 / 结果码 / 分拣成功总数量
        draw.text((600, 148), "货物名称", font=self._font(ImageFont, 26), fill=_MUTED)
        draw.text((600, 186), view.name, font=self._font(ImageFont, 44), fill=_TEXT)
        draw.text((600, 280), "分拣结果", font=self._font(ImageFont, 26), fill=_MUTED)
        is_success = view.result_code == 0  # 协议 RoundSuccessCounter.SUCCESS = 0x00
        draw.text(
            (600, 316),
            "SUCCESS" if is_success else "FAILURE",
            font=self._font(ImageFont, 48),
            fill=_SUCCESS if is_success else _FAILURE,
        )
        draw.text((600, 408), "分拣成功总数量", font=self._font(ImageFont, 26), fill=_MUTED)
        draw.text(
            (600, 444),
            str(view.success_count),
            font=self._font(ImageFont, 44),
            fill=_TEXT,
        )

        return canvas

    def _load_cargo_image(self, view: DisplayViewModel, Image) -> "PIL.Image.Image":
        try:
            raw = self._image_loader(view.image_id)
        except Exception as exc:
            raise ImageLoadError(
                f"货物图片加载失败 image_id={view.image_id}: {exc!r}"
            ) from exc
        if not isinstance(raw, Image.Image):
            raise ImageLoadError(
                f"image_loader(image_id={view.image_id}) 返回 {type(raw).__name__}，"
                "需要 PIL.Image.Image"
            )
        if raw.mode == "RGBA":
            base = Image.new("RGB", raw.size, (255, 255, 255))
            base.paste(raw, mask=raw.getchannel("A"))
            return base
        return raw.convert("RGB")

    @staticmethod
    def _fit_into(
        img: "PIL.Image.Image", Image, box: tuple[int, int, int, int]
    ) -> tuple["PIL.Image.Image", int, int]:
        """Aspect-fit ``img`` into ``box``; return (fitted, paste_x, paste_y)."""
        x0, y0, x1, y1 = box
        box_w, box_h = x1 - x0, y1 - y0
        scale = min(box_w / img.width, box_h / img.height)
        new_w = max(1, round(img.width * scale))
        new_h = max(1, round(img.height * scale))
        fitted = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        px = x0 + (box_w - new_w) // 2
        py = y0 + (box_h - new_h) // 2
        return fitted, px, py

    @staticmethod
    def _paste_clipped(
        canvas: "PIL.Image.Image", fitted: "PIL.Image.Image", px: int, py: int
    ) -> None:
        """Paste ``fitted`` at (px, py), clipping to the canvas (custom sizes)."""
        left = max(0, px)
        top = max(0, py)
        right = min(canvas.width, px + fitted.width)
        bottom = min(canvas.height, py + fitted.height)
        if left >= right or top >= bottom:
            return
        region = fitted.crop((left - px, top - py, right - px, bottom - py))
        canvas.paste(region, (left, top))

    def _font(self, ImageFont, size: int) -> "PIL.ImageFont.ImageFont":
        if self._font_path is not None:
            return ImageFont.truetype(self._font_path, size)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1: load_default() 不支持 size
            return ImageFont.load_default()


__all__ = [
    "FrameOutput",
    "HdmiDisplayRenderer",
    "ImageLoadError",
    "ImageLoader",
]
