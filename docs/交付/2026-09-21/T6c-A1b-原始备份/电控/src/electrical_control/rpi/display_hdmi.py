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

除协议帧之外，本模块还有两条**不参与协议**的画面路径（2026-09-18 用户要求）：
``TwoStageDisplay``（两段：识别到物体 / 分拣成功，为验证屏幕可用）与
``TableDisplay``（累计分拣统计表：序号 | 预置图片 | 分拣个数，次日展示用）。
三条路径的分工写在各自类上方，别混用。

帧到屏幕的最后一段（像素打包写 /dev/fb0）也在这里：framebuffer 的真实 bpp
必须从 sysfs 读，不能假定 32bpp（2026-09-17 实机结论，见下方 framebuffer 段）。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable, Mapping

from electrical_control.protocol import DisplayContent
from electrical_control.rpi import ItemTaskContext, PendingRender
from electrical_control.rpi.display import DisplayViewModel

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# framebuffer（/dev/fb0）真实像素格式与打包
#
# 为什么必须有这一段（2026-09-17 实机结论，别删）：
#   · 树莓派 fkms 下 fb 是 16bpp（RGB565）：1024x600 一帧只有 1,228,800 字节。
#     按 32bpp 的 1,843,200 字节直写 → [Errno 28] No space left on device（已实测）。
#   · 所以写屏前必须读 sysfs 的真实 bpp，按它打包；读不到就报错（fail-closed），
#     绝不猜成 32 —— 猜错的两种后果（花屏 / Errno 28）都已实机踩到。
# 参考实现：工具/pi_blit_png.py（同一打包方式，实机出图验证过 16bpp 路径）。
# ---------------------------------------------------------------------------
_BYTES_PER_PIXEL = {16: 2, 24: 3, 32: 4}


class FramebufferFormatError(ValueError):
    """fb 的真实格式读不到/不支持，或帧写不下：fail-closed，绝不按猜的格式写屏。"""


@dataclass(frozen=True)
class FramebufferFormat:
    """fb 的真实几何（读自 sysfs，不是猜的）。

    line_length 是 fb 一行的字节数，可能大于 frame.width * bytes_per_pixel
    （行填充）。为 None 表示内核没暴露 line_length/stride（本机 fkms 实测如此），
    此时按紧凑行处理。
    """

    bpp: int
    virtual_width: int
    virtual_height: int
    line_length: int | None = None

    @property
    def bytes_per_pixel(self) -> int:
        try:
            return _BYTES_PER_PIXEL[self.bpp]
        except KeyError:
            raise FramebufferFormatError(
                f"bits_per_pixel={self.bpp} 不支持（只支持 16/24/32）"
            ) from None

    def __str__(self) -> str:
        line = self.line_length if self.line_length else "读不到（按紧凑行）"
        return (
            f"{self.virtual_width}x{self.virtual_height} @{self.bpp}bpp"
            f" line_length={line}"
        )


def _read_sysfs(path: str) -> str | None:
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return None


def read_framebuffer_format(device: str = "/dev/fb0") -> FramebufferFormat:
    """读 fb 的真实像素格式：bits_per_pixel / virtual_size / line_length（或 stride）。

    bpp 或 virtual_size 读不到就抛 FramebufferFormatError —— 不猜。sysfs 节点按
    设备名（fb0）挂，与传入的路径无关。
    """

    name = os.path.basename(device.rstrip("/")) or "fb0"
    base = f"/sys/class/graphics/{name}"

    bpp_raw = _read_sysfs(f"{base}/bits_per_pixel")
    if not (bpp_raw or "").isdigit():
        raise FramebufferFormatError(
            f"读不到 {base}/bits_per_pixel：拒绝猜 bpp。\n"
            f"  查：ls /sys/class/graphics/ ; cat {base}/bits_per_pixel\n"
            "  该节点缺失通常是 fbdev 兼容层没起来（vc4-kms-v3d 下 /dev/fb0 是影子节点）"
        )
    bpp = int(bpp_raw)
    if bpp not in _BYTES_PER_PIXEL:
        raise FramebufferFormatError(
            f"bits_per_pixel={bpp} 不支持（只支持 16/24/32）："
            "按错误的格式写屏就是花屏，拒绝写"
        )

    virtual = _read_sysfs(f"{base}/virtual_size")
    parts = (virtual or "").split(",")
    if len(parts) < 2 or not all(part.strip().isdigit() for part in parts[:2]):
        raise FramebufferFormatError(
            f"读不到 {base}/virtual_size（读到 {virtual!r}）："
            "没有它无法确认帧写不写得下，拒绝写"
        )

    line_length = None
    for node in ("line_length", "stride"):
        raw = _read_sysfs(f"{base}/{node}")
        if (raw or "").isdigit():
            line_length = int(raw)
            break

    return FramebufferFormat(
        bpp=bpp,
        virtual_width=int(parts[0]),
        virtual_height=int(parts[1]),
        line_length=line_length,
    )


def validate_frame_size(width: int, height: int, fmt: FramebufferFormat) -> None:
    """帧尺寸 vs fb 可见区：写不下就报错；不完全一致只告警（会只覆盖左上角）。"""

    if width > fmt.virtual_width or height > fmt.virtual_height:
        raise FramebufferFormatError(
            f"帧 {width}x{height} 比 fb 可见区 {fmt.virtual_width}x{fmt.virtual_height} 大："
            "写下去要么错位要么越界，拒绝写。\n"
            "  分辨率由 config.txt 的 hdmi_cvt 与 --width/--height 决定，两边必须一致"
        )
    if (width, height) != (fmt.virtual_width, fmt.virtual_height):
        logger.warning(
            "帧 %dx%d ≠ fb 可见区 %s：只覆盖左上角，其余像素保持原样（不是花屏，是没画满）。"
            "对齐办法：改 config.txt 的 hdmi_cvt，或让 --width/--height 与屏一致",
            width,
            height,
            fmt,
        )


def encode_frame(frame: "PIL.Image.Image", fmt: FramebufferFormat) -> bytes:
    """PIL RGB 帧 -> 可直接写 fb 的字节（按真实 bpp 打包 + 行填充）。

    · 16bpp：RGB565 小端 —— 红 (255,0,0) = 0xF800 = 字节 00 F8。
      fbdev 的 fb 内容是 CPU 字节序的像素值，Pi 是小端；工具/pi_blit_png.py
      用同一打包方式在本机 16bpp 上出图成功。
    · 24/32bpp：fbdev truecolor 的内存序是 B,G,R[,X]
      （red 在 bit16 / green 在 bit8 / blue 在 bit0）；32bpp 第 4 字节留 0。
    · line_length 大于一行宽度（行填充）时，每行末尾补零，否则整幅会斜切。
    """

    px = fmt.bytes_per_pixel
    width, height = frame.size
    validate_frame_size(width, height, fmt)

    row = width * px
    stride = fmt.line_length or row
    if stride < row:
        raise FramebufferFormatError(
            f"line_length/stride={stride} 小于一行应有的 {row} 字节"
            f"（{width}px @{fmt.bpp}bpp）"
        )

    rgb = frame.convert("RGB").tobytes()
    out = bytearray(width * height * px)
    index = 0
    if fmt.bpp == 16:
        for offset in range(0, len(rgb), 3):
            value = (
                ((rgb[offset] & 0xF8) << 8)
                | ((rgb[offset + 1] & 0xFC) << 3)
                | (rgb[offset + 2] >> 3)
            )
            out[index] = value & 0xFF  # 小端：低字节先写
            out[index + 1] = value >> 8
            index += 2
    else:  # 24/32bpp：B,G,R[,X]
        for offset in range(0, len(rgb), 3):
            out[index] = rgb[offset + 2]
            out[index + 1] = rgb[offset + 1]
            out[index + 2] = rgb[offset]
            index += px  # 32bpp 的第 4 字节保持 0（屏不用）

    data = bytes(out)
    if stride == row:
        return data
    pad = b"\x00" * (stride - row)
    return b"".join(
        data[at : at + row] + pad for at in range(0, len(data), row)
    )


class FramebufferFrameOutput:
    """frame_output 回调：按 fb 的真实 bpp 打包并写进 framebuffer。

    构造时就把真实格式读出来并校验帧尺寸：配置错了是**启动期**报错，而不是
    第一件物料渲染时才炸（那时 STM32 已经动过了）。
    """

    def __init__(self, device: str = "/dev/fb0", *, size: tuple[int, int]) -> None:
        self.device = device
        self.format = read_framebuffer_format(device)
        validate_frame_size(size[0], size[1], self.format)

    def __call__(self, frame: "PIL.Image.Image") -> None:
        data = encode_frame(frame, self.format)
        with open(self.device, "wb") as handle:
            handle.write(data)


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
        self._font_path = font_path if font_path is not None else _find_cjk_font()
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
        # 2026-09-18 树莓派实机修复：Image.Resampling 是 Pillow 9.1 才有的，
        # 而树莓派是 Pillow 8.1.2 → AttributeError: module 'PIL.Image' has no
        # attribute 'Resampling'。getattr 兜底让 8.x 与 9.1+ 都能跑。
        _resampling = getattr(Image, "Resampling", Image)
        fitted = img.resize((new_w, new_h), _resampling.LANCZOS)
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
        return load_font(self._font_path, size, ImageFont)


def load_font(
    font_path: "str | None", size: int, ImageFont=None
) -> "PIL.ImageFont.ImageFont":
    """按字号取字体：有 CJK 字体就用它，没有才退回 PIL 内置字体（只支持 latin-1）。

    ``ImageFont`` 可注入（供已 import 过 PIL 的调用方复用）；缺省时懒加载。
    """

    if ImageFont is None:
        from PIL import ImageFont as _ImageFont

        ImageFont = _ImageFont
    if font_path is not None:
        return ImageFont.truetype(font_path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1: load_default() 不支持 size
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 屏幕两段显示（2026-09-18 用户要求，只为验证屏幕本身可用）
#
#   段1「识别到待分拣物体」：货格号 / 名称 / 颜色 / 形状
#   段2「分拣成功」：动作完成（STM32 MOTION_DONE）+ 结果码 SUCCESS 之后
#
# 与 HdmiDisplayRenderer 的分工（别混）：
#   · HdmiDisplayRenderer.present() 出的是**协议帧** —— 它要重建 DisplayContent 并
#     返回 PendingRender，CRC32 进 RenderReceipt，走 DISPLAY_ACK 闭环（R-D04 门禁）。
#   · 本类出的帧**不参与任何协议**：没有 DisplayContent、没有回执、不进 DISPLAY_ACK。
#     纯附加信息，因此绝不能改 present() 的语义去承载它（会牵动冻结的显示闭环）。
# ---------------------------------------------------------------------------
# 两行文字的 x 坐标：左列标签 48，右列数值 260（1024x600 版面，见下方 _compose_*）
_LABEL_X = 48
_VALUE_X = 260
_STAGE1_ROW_Y = 250  # 段1 四行信息的第一行 y，行距 88
_STAGE1_ROW_STEP = 88
_UNKNOWN = "—"  # 本地查不到的字段（如颜色/形状）显示它，绝不编一个值


@dataclass(frozen=True)
class TwoStageInfo:
    """两段显示的载荷（本地解析，不来自也不进入任何 wire 帧）。

    box_id 在**校赛模式**下就是 BATCH_TARGETS 那一个 id 字节（颜色已折叠成货格号），
    也是 ItemTaskPayload.class_id；name/color/shape 来自本地名称表，查不到就给 None
    （屏幕显示 ``—``）。
    """

    target_seq: int
    box_id: int | None = None
    name: str | None = None
    color: str | None = None
    shape: str | None = None


class TwoStageDisplay:
    """合成并上屏两段显示帧；每段一个方法，都返回刚合成的那一帧。

    构造参数与 HdmiDisplayRenderer 同名同义（width/height/frame_output/font_path），
    部署时注入 FramebufferFrameOutput 即可上屏；host 上注入 ``list.append`` 就能拿到帧。
    """

    def __init__(
        self,
        *,
        frame_output: FrameOutput,
        width: int = _DEFAULT_WIDTH,   # 默认仅供 host 测试；部署时由配置提供
        height: int = _DEFAULT_HEIGHT,
        font_path: str | None = None,  # None = 自动探测 CJK 字体（见 _find_cjk_font）
    ) -> None:
        if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
            raise ValueError("width must be a positive int")
        if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
            raise ValueError("height must be a positive int")
        self._width = width
        self._height = height
        self._frame_output = frame_output
        # 公开出来是为了可在日志/交付里核对"到底用了哪个字体"（None = 内置字体，中文会是方块）
        self.font_path = font_path if font_path is not None else _find_cjk_font()

    def show_recognized(self, info: TwoStageInfo) -> "PIL.Image.Image":
        """段1：识别到待分拣物体 → 显示该物体信息。"""
        return self._show(self._compose_recognized(info))

    def show_success(self, info: TwoStageInfo) -> "PIL.Image.Image":
        """段2：已放进转盘/落料位 → 显示「分拣成功」。"""
        return self._show(self._compose_success(info))

    def _show(self, frame: "PIL.Image.Image") -> "PIL.Image.Image":
        self._frame_output(frame)
        return frame

    def _blank(self):
        from PIL import Image

        return Image.new("RGB", (self._width, self._height), _BACKGROUND)

    def _compose_recognized(self, info: TwoStageInfo) -> "PIL.Image.Image":
        from PIL import ImageDraw, ImageFont

        canvas = self._blank()
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (_LABEL_X, 36),
            "识别到待分拣物体",
            font=load_font(self.font_path, 44, ImageFont),
            fill=_ACCENT,
        )
        draw.line((_LABEL_X, 100, self._width - _LABEL_X, 100), fill=_ACCENT, width=2)
        draw.text(
            (_LABEL_X, 120),
            f"第 {info.target_seq} 件",
            font=load_font(self.font_path, 88, ImageFont),
            fill=_TEXT,
        )

        rows = (
            ("货格号", _UNKNOWN if info.box_id is None else str(info.box_id)),
            ("名称", info.name or _UNKNOWN),
            ("颜色", info.color or _UNKNOWN),
            ("形状", info.shape or _UNKNOWN),
        )
        for index, (label, value) in enumerate(rows):
            y = _STAGE1_ROW_Y + index * _STAGE1_ROW_STEP
            draw.text(
                (_LABEL_X, y + 14),
                label,
                font=load_font(self.font_path, 30, ImageFont),
                fill=_MUTED,
            )
            draw.text(
                (_VALUE_X, y),
                value,
                font=load_font(self.font_path, 56, ImageFont),
                fill=_TEXT,
            )
        return canvas

    def _compose_success(self, info: TwoStageInfo) -> "PIL.Image.Image":
        from PIL import ImageDraw, ImageFont

        canvas = self._blank()
        draw = ImageDraw.Draw(canvas)

        title = "分拣成功"
        title_font = load_font(self.font_path, 150, ImageFont)
        draw.text(
            (self._center_x(draw, title, title_font), 110),
            title,
            font=title_font,
            fill=_SUCCESS,
        )
        draw.line(
            (_LABEL_X, 320, self._width - _LABEL_X, 320), fill=_SUCCESS, width=3
        )
        detail = self._success_detail(info)
        detail_font = load_font(self.font_path, 48, ImageFont)
        draw.text(
            (self._center_x(draw, detail, detail_font), 368),
            detail,
            font=detail_font,
            fill=_TEXT,
        )
        return canvas

    def _success_detail(self, info: TwoStageInfo) -> str:
        """副标题：只出现在场字段，缺的整段跳过（不写 ``—``，那看着像坏了）。"""

        parts = [f"第 {info.target_seq} 件"]
        if info.box_id is not None:
            parts.append(f"货格 {info.box_id}")
        for extra in (info.color, info.shape):
            if extra:
                parts.append(extra)
        return " · ".join(parts)

    def _center_x(self, draw, text: str, font) -> float:
        """整屏水平居中（= 在第 0..width 列里居中）。"""

        return self._center_in(draw, text, font, 0, self._width)

    def _center_in(self, draw, text: str, font, x0: int, x1: int) -> float:
        """区域内水平居中：按字宽（em advance）算。

        实测 CJK 字形在 em 框内左右留白不等（「分拣成功」左边 1px、右边 11px），
        所以按字宽居中的**墨迹**中心会比区域中心偏 5px —— 1024px 屏上看不出来，
        不值得为此多渲染一遍去量墨迹（真要精确就得先贴到掩模上量包围盒）。
        """

        return max(0.0, x0 + (x1 - x0 - draw.textlength(text, font=font)) / 2)


# ---------------------------------------------------------------------------
# 累计分拣统计表（2026-09-18 用户要求，次日展示用）
#
#     序号 | 预置图片 | 分拣个数
#
# 六行固定（货格数 = 6），**图片按「行序号」取，不按文件名顺序取** —— 见
# DEFAULT_TABLE_IMAGES 的说明，这是整张表最容易搞错的一处。
# ---------------------------------------------------------------------------

# 行序号 = 货格号，六行固定。
_TABLE_SEQS = (1, 2, 3, 4, 5, 6)

# 序号 -> 预置图片文件名（2026-09-18 用户对照「屏幕照片.docx」逐条确认）。
# 🔴 **文件名顺序 ≠ 行序号**：image1..image6 的排列与表格第 1..6 行并不一致，
#    按 imageN 直接排会把六张图全放错格。改这张表前先重新对照一遍原图。
DEFAULT_TABLE_IMAGES = {
    1: "image1.jpeg",  # 青色正方体
    2: "image6.jpeg",  # 绿色正方体
    3: "image2.jpeg",  # 红色三棱柱
    4: "image3.jpeg",  # 深蓝色三棱柱
    5: "image4.jpeg",  # 黑色圆柱
    6: "image5.jpeg",  # 橙色圆柱
}

# 版面常量（1024x600）：表头 50..80，分隔线 86，六行 92..584，底部余 16。
_TABLE_TITLE_Y = 6
_TABLE_HEAD_Y = 50
_TABLE_HEAD_LINE_Y = 86
_TABLE_TOP = 92
_TABLE_ROW_H = 82
_TABLE_FONT_SIZE = 44
_TABLE_LEFT = 32
_TABLE_RIGHT = 992
_TABLE_COL_SEQ = (32, 180)
_TABLE_COL_IMG = (180, 420)
_TABLE_COL_CNT = (420, 992)
_TABLE_THUMB = 64  # 缩略图边长（正方形，ImageOps.fit 居中裁剪）
_GRID = (52, 66, 92)


def table_image_path(
    directory: str, seq: int, mapping: Mapping[int, str] | None = None
) -> str:
    """行序号 1..6 → 预置图片的完整路径（**纯函数，不碰文件系统**）。

    ⚠️ ``seq`` 是**行序号（货格号）**，不是 wire 上的 image_id；序号到文件名的映射
    由 ``mapping`` 决定（缺省 ``DEFAULT_TABLE_IMAGES``）。单独拆成纯函数是为了能在
    没有文件系统的环境里直接测「序号→文件名」这一跳 —— 那正是整张表最易错的地方
    （文件名顺序 ≠ 行序号）。
    """

    table = mapping if mapping is not None else DEFAULT_TABLE_IMAGES
    try:
        name = table[seq]
    except KeyError:
        raise ImageLoadError(
            f"序号 {seq} 不在预置图片映射（有 {sorted(table)}）"
        ) from None
    return os.path.join(directory, name)


def jpeg_dir_loader(
    directory: str, mapping: Mapping[int, str] | None = None
) -> ImageLoader:
    """部署用 image_loader：``<dir>/<文件名>`` 按 ``mapping`` 取图并解码成 RGB。

    文件名由 ``table_image_path`` 决定（传进来的序号是**行序号**，不是 image_id）。
    文件缺失/打不开就抛 —— 由调用方决定是降级还是 fail-closed，这里不吞异常。
    """

    def load(seq: int) -> "PIL.Image.Image":
        from PIL import Image

        # with + convert：convert 会真正解码，同时保证文件句柄被关掉
        with Image.open(table_image_path(directory, seq, mapping)) as handle:
            return handle.convert("RGB")

    return load


class TableDisplay(TwoStageDisplay):
    """累计分拣统计表：序号 | 预置图片 | 分拣个数（1024x600，六行）。

    继承 ``TwoStageDisplay`` 只为复用版面基建（尺寸校验、底色、``_show``、
    区域内居中、CJK 字体探测）；**不覆盖** ``show_recognized`` /
    ``show_success`` —— 两段显示与统计表是两个独立画面，谁都不改谁的语义。

    与 ``HdmiDisplayRenderer`` 的分工同 ``TwoStageDisplay``：本类出的帧**不参与任何
    协议**（无 ``DisplayContent``、无回执、不进 ``DISPLAY_ACK`` 闭环），所以不要拿它
    去替换 ``present()``。

    图片缺失的处理与 ``HdmiDisplayRenderer`` **故意不同**：后者 fail-closed（协议帧
    宁可不出，也不出错帧）。本表是状态画面，缺一张图就把整屏清掉，会让人以为系统
    死了 —— 所以该格画红框「缺图」并写 warning，其余五格照常显示。
    宁可显示得丑，不可显示得不全。
    """

    def __init__(
        self,
        *,
        frame_output: FrameOutput,
        image_loader: ImageLoader,
        width: int = _DEFAULT_WIDTH,   # 默认仅供 host 测试；部署时由配置提供
        height: int = _DEFAULT_HEIGHT,
        font_path: str | None = None,  # None = 自动探测 CJK 字体（见 _find_cjk_font）
    ) -> None:
        super().__init__(
            frame_output=frame_output,
            width=width,
            height=height,
            font_path=font_path,
        )
        self._image_loader = image_loader

    def show_table(self, counts: Mapping[int, int]) -> "PIL.Image.Image":
        """按 ``{序号: 分拣个数}`` 合成并上屏统计表；表里没有的序号按 0 显示。"""

        return self._show(self._compose_table(counts))

    def _compose_table(self, counts: Mapping[int, int]) -> "PIL.Image.Image":
        from PIL import Image, ImageDraw, ImageFont, ImageOps

        canvas = self._blank()
        draw = ImageDraw.Draw(canvas)

        draw.text(
            (_TABLE_LEFT, _TABLE_TITLE_Y),
            "分拣统计",
            font=load_font(self.font_path, 34, ImageFont),
            fill=_ACCENT,
        )

        head_font = load_font(self.font_path, 26, ImageFont)
        for label, (x0, x1) in (
            ("序号", _TABLE_COL_SEQ),
            ("预置图片", _TABLE_COL_IMG),
            ("分拣个数", _TABLE_COL_CNT),
        ):
            draw.text(
                (self._center_in(draw, label, head_font, x0, x1), _TABLE_HEAD_Y),
                label,
                font=head_font,
                fill=_MUTED,
            )
        draw.line(
            (_TABLE_LEFT, _TABLE_HEAD_LINE_Y, _TABLE_RIGHT, _TABLE_HEAD_LINE_Y),
            fill=_ACCENT,
            width=2,
        )

        cell_font = load_font(self.font_path, _TABLE_FONT_SIZE, ImageFont)
        thumb_x = (_TABLE_COL_IMG[0] + _TABLE_COL_IMG[1] - _TABLE_THUMB) // 2

        for index, seq in enumerate(_TABLE_SEQS):
            y0 = _TABLE_TOP + index * _TABLE_ROW_H
            if index:
                draw.line(
                    (_TABLE_LEFT, y0, _TABLE_RIGHT, y0), fill=_GRID, width=1
                )
            text_y = y0 + (_TABLE_ROW_H - _TABLE_FONT_SIZE) // 2

            for text, (x0, x1) in (
                (str(seq), _TABLE_COL_SEQ),
                (str(int(counts.get(seq, 0))), _TABLE_COL_CNT),
            ):
                draw.text(
                    (self._center_in(draw, text, cell_font, x0, x1), text_y),
                    text,
                    font=cell_font,
                    fill=_TEXT,
                )

            thumb_y = y0 + (_TABLE_ROW_H - _TABLE_THUMB) // 2
            try:
                thumb = self._thumbnail(self._image_loader(seq), Image, ImageOps)
            except Exception as exc:  # 缺图不掀桌：见类文档
                logger.warning(
                    "预置图片加载失败 seq=%d：%r（该格画红框占位，整表继续）", seq, exc
                )
                draw.rectangle(
                    (
                        thumb_x,
                        thumb_y,
                        thumb_x + _TABLE_THUMB - 1,
                        thumb_y + _TABLE_THUMB - 1,
                    ),
                    outline=_FAILURE,
                    width=2,
                )
                draw.text(
                    (thumb_x + 8, thumb_y + 22),
                    "缺图",
                    font=load_font(self.font_path, 22, ImageFont),
                    fill=_FAILURE,
                )
            else:
                canvas.paste(thumb, (thumb_x, thumb_y))

        return canvas

    @staticmethod
    def _thumbnail(raw, Image, ImageOps) -> "PIL.Image.Image":
        """正方形缩略图（居中裁剪）。用 ``ImageOps.fit``，不自己算裁剪框。

        预置图是 3:4 竖构图（960x1280 / 1267x1690），等比塞进 64x64 的格子只有
        48px 宽，隔两米看等于没画；居中裁剪成正方形才有 64px。
        """

        # Pillow 8.1.2（树莓派）没有 Image.Resampling，9.1+ 才有 —— 同 _fit_into
        resampling = getattr(Image, "Resampling", Image)
        if not isinstance(raw, Image.Image):
            raise ImageLoadError(
                f"image_loader 返回 {type(raw).__name__}，需要 PIL.Image.Image"
            )
        return ImageOps.fit(
            raw.convert("RGB"), (_TABLE_THUMB, _TABLE_THUMB), resampling.LANCZOS
        )


# ── CJK 字体自动探测（2026-09-18 树莓派实机修复）──────────────────────
# 问题：font_path=None 时会退回 PIL 内置字体，那只支持 latin-1。
#       实机上画「第 N 件」直接抛
#       UnicodeEncodeError: 'latin-1' codec can't encode character '\u7b2c'
#       —— 屏幕一个字都画不出来，而且崩在渲染路径里。
# 树莓派其实已装 fonts-wqy-*（install.sh 第 1 步会 apt install），
# 只是没人把路径传进来。所以在 font_path 为空时按候选表探测。
# 全部找不到仍退回内置字体（保持旧行为，不改变 host 测试的预期）。
_CJK_FONT_CANDIDATES = (
    # 树莓派 / Debian：fonts-wqy-zenhei、fonts-wqy-microhei
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # 其它 Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    # Windows（仅供主机调试）
    "C:\\Windows\\Fonts\\msyh.ttc",
    "C:\\Windows\\Fonts\\simhei.ttf",
    "C:\\Windows\\Fonts\\simsun.ttc",
)


def _find_cjk_font() -> "str | None":
    """返回系统里第一个存在的 CJK 字体路径；一个都没有则返回 None。"""
    import os

    for candidate in _CJK_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


__all__ = [
    "DEFAULT_TABLE_IMAGES",
    "FramebufferFormat",
    "FramebufferFormatError",
    "FramebufferFrameOutput",
    "FrameOutput",
    "HdmiDisplayRenderer",
    "ImageLoadError",
    "ImageLoader",
    "TableDisplay",
    "TwoStageDisplay",
    "TwoStageInfo",
    "encode_frame",
    "jpeg_dir_loader",
    "load_font",
    "read_framebuffer_format",
    "table_image_path",
    "validate_frame_size",
]


def _write_table(argv: list[str], device: str, fmt: FramebufferFormat) -> int:
    """``--table <图片目录>``：用演示计数把统计表写到 fb（验收「表格能上屏」）。"""

    at = argv.index("--table")
    if at + 1 >= len(argv):
        print("--table 需要一个图片目录参数，例如：--table /home/pi/电控/工具/object_images")
        return 2
    directory = argv[at + 1]

    output = FramebufferFrameOutput(device, size=(fmt.virtual_width, fmt.virtual_height))
    display = TableDisplay(
        frame_output=output,
        image_loader=jpeg_dir_loader(directory),
        width=fmt.virtual_width,
        height=fmt.virtual_height,
    )
    # 演示计数：只为看出「表格真的会随计数变」，不是任何真实统计。
    counts = {1: 2, 2: 0, 3: 1, 4: 0, 5: 3, 6: 0}
    display.show_table(counts)

    print(f"已写统计表到 {device}（{fmt}）：图片目录 {directory}")
    print(f"  演示计数 {counts}")
    print("  屏上六行序号 1..6，图片按 DEFAULT_TABLE_IMAGES 取（**不是**按 imageN 顺序取）")
    return 0


def _main(argv: list[str]) -> int:
    """树莓派侧自检（要看屏，所以只能上机跑）：

        python3 -m electrical_control.rpi.display_hdmi --info
            # 只打印 /sys/class/graphics/fb0 的真实 bpp/尺寸/line_length，不写屏
        python3 -m electrical_control.rpi.display_hdmi --bars
            # 用【真实打包路径】写红|绿|蓝三条竖条到 /dev/fb0
        python3 -m electrical_control.rpi.display_hdmi --table <图片目录>
            # 用演示计数把「序号|预置图片|分拣个数」统计表写屏（验收表格能上屏）

    --bars 是 30 秒验字节序的办法：屏上从左到右必须是 红、绿、蓝。
    16bpp 字节序写反的外在表现（不是全黑，是颜色错）：红→深蓝、绿→洋红、蓝→暗绿。

    ⚠️ 写 /dev/fb0 前必须先停掉图形界面（lightdm 占着 fb 会把画面盖回去）：
       sudo systemctl stop lightdm
    """

    device = "/dev/fb0"
    if "--fb" in argv:
        device = argv[argv.index("--fb") + 1]
    try:
        fmt = read_framebuffer_format(device)
    except FramebufferFormatError as exc:
        print(f"读不到 fb 格式，拒绝写：{exc}")
        return 2

    print(f"{device}: {fmt}  (读自 /sys/class/graphics/，不是猜的)")
    if "--info" in argv:
        return 0

    if "--table" in argv:
        return _write_table(argv, device, fmt)

    if "--bars" not in argv:
        print("用法：--info | --bars | --table <图片目录> [--fb /dev/fb0]")
        return 2

    from PIL import Image

    width, height = fmt.virtual_width, fmt.virtual_height
    frame = Image.new("RGB", (width, height))
    third = width // 3
    for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        frame.paste(color, (index * third, 0, min(width, (index + 1) * third), height))
    output = FramebufferFrameOutput(device, size=(width, height))
    output(frame)
    print("已按真实 bpp 写三色条：屏上从左到右必须是 红 | 绿 | 蓝。")
    print("  若看到 深蓝 | 洋红 | 暗绿 → 16bpp 字节序反了，别上机跑链路，先回来改打包。")
    return 0


if __name__ == "__main__":  # pragma: no cover - 需要真 fb 才跑
    raise SystemExit(_main(sys.argv[1:]))
