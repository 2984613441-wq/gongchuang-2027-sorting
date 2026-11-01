"""落料位复看的「眼睛」：副相机抓帧 + ROI 判色（2026-11-01 新增）。

用户口径（2026-11-01）：
* 复看位置 = **落料位**，相机 = **副相机 DF200（USB 接树莓派）**；
* 「副摄像头只是远端有点看不完全，但是落点是看的完的」；
* 判色在 **Pi 本地** 跑（`cv2` 已有，HSV 是纯算法，不需要 YOLO 运行时）。

边界（先写清楚）
----------------
* 本模块**只负责**：读 `[PlaceEye]` 配置、抓一帧、裁 ROI、统计 ROI 内的 HSV 众数颜色。
* **不**做判决、**不**改台账、**不**发串口、**不**碰 wire；判决在
  :mod:`electrical_control.rpi.place_verifier`，台账修正在 `SlotAllocator.correct()`。
* `cv2` **延迟导入**：没有 cv2 的机器（如开发机）只跑配置/统计的纯逻辑测试，
  抓帧函数会抛 :class:`PlaceEyeUnavailable`，不会在 import 期炸掉整条链。

配置（`sorting_config.ini`，缺节 = 禁用）
----------------------------------------
```ini
[PlaceEye]
enabled = true
device = /dev/video2        # 副相机设备节点（Pi 上 v4l2）
width = 1280
height = 720
fps = 30
roi = x, y, w, h            # 落料位在副相机画面里的矩形（像素）
grid = 5                    # ROI 内采样网格 N×N
min_votes = 3               # 至少这么多有效票才认
```
"""

from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "PlaceEyeConfig",
    "PlaceEyeUnavailable",
    "load_place_eye_config",
    "majority_color",
    "sample_hsv_grid",
    "capture_frame",
]


class PlaceEyeUnavailable(RuntimeError):
    """没有 cv2 / 打不开相机时抛出（调用方按「复看不可用」降级，不是致命错误）。"""


@dataclass(frozen=True)
class PlaceEyeConfig:
    """`[PlaceEye]` 的不可变配置。"""

    enabled: bool
    device: str
    width: int
    height: int
    fps: int
    roi: tuple[int, int, int, int] | None
    grid: int = 5
    min_votes: int = 3
    warmup_frames: int = 5

    def is_usable(self) -> bool:
        """启用且 ROI 合法才算真能用。"""
        return bool(self.enabled and self.roi is not None and self.grid >= 1)


_SECTION = "PlaceEye"


def _as_bool(value: str, default: bool = False) -> bool:
    low = str(value).strip().lower()
    if low in ("true", "1", "yes", "on"):
        return True
    if low in ("false", "0", "no", "off"):
        return False
    return default


def load_place_eye_config(path: str | Path) -> PlaceEyeConfig | None:
    """读 `[PlaceEye]`；文件不存在 / 缺节 / enabled=false ⇒ 返回 None（= 禁用）。

    解析失败只记 WARNING 并返回 None —— 复看是**增强功能**，不能因为配置写错
    把整条链拖下来（fail-safe，不是 fail-closed）。
    """
    p = Path(path)
    if not p.exists():
        return None
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    try:
        cfg.read(p, encoding="utf-8")
    except Exception:
        _LOGGER.warning("读不到 %s：落料位复看禁用", p, exc_info=True)
        return None
    if not cfg.has_section(_SECTION):
        return None
    sec = cfg[_SECTION]

    enabled = _as_bool(sec.get("enabled", "false"))
    if not enabled:
        return None

    roi = None
    raw_roi = sec.get("roi", "").strip()
    if not raw_roi:
        _LOGGER.warning("[PlaceEye] enabled=true 但缺 roi：复看禁用"
                        "（ROI 必须标定，连拍全画面没有意义）")
        return None
    if raw_roi:
        parts = [x.strip() for x in raw_roi.replace("，", ",").split(",")]
        if len(parts) == 4:
            try:
                x, y, w, h = (int(float(v)) for v in parts)
                if w > 0 and h > 0:
                    roi = (x, y, w, h)
            except ValueError:
                roi = None
        if roi is None:
            _LOGGER.warning("[PlaceEye] roi=%r 非法（要 `x, y, w, h` 四个正数）："
                            "复看禁用", raw_roi)
            return None

    try:
        width = int(sec.get("width", "1280"))
        height = int(sec.get("height", "720"))
        fps = int(sec.get("fps", "30"))
        grid = int(sec.get("grid", "5"))
        min_votes = int(sec.get("min_votes", "3"))
        warmup = int(sec.get("warmup_frames", "5"))
    except ValueError:
        _LOGGER.warning("[PlaceEye] 数值项解析失败：复看禁用", exc_info=True)
        return None

    if width <= 0 or height <= 0 or grid < 1 or min_votes < 1:
        _LOGGER.warning("[PlaceEye] width/height/grid/min_votes 取值非法：复看禁用")
        return None
    if roi is not None and (roi[0] + roi[2] > width or roi[1] + roi[3] > height):
        _LOGGER.warning("[PlaceEye] roi=%s 超出画面 %dx%d：复看禁用",
                        roi, width, height)
        return None

    return PlaceEyeConfig(
        enabled=True,
        device=str(sec.get("device", "/dev/video2")).strip(),
        width=width,
        height=height,
        fps=fps,
        roi=roi,
        grid=grid,
        min_votes=min_votes,
        warmup_frames=max(0, warmup),
    )


# --------------------------------------------------------------------------- #
# 纯逻辑：HSV 众数（可在无 cv2 的机器上测）
# --------------------------------------------------------------------------- #
def majority_color(
    hsv_pixels, *, min_votes: int = 3
) -> tuple[int, int, int]:
    """统计一批 HSV 像素的颜色众数。

    Args:
        hsv_pixels: 可迭代的 ``(h, s, v)``（**cv2 口径**：H 0..179，S/V 0..255）。
        min_votes: 至少这么多**该颜色**的票才认可。

    Returns:
        ``(color_id, votes, total)``；color_id=0 表示判不出（票不足 / 全无效）。
    """
    from .color_judge import hsv_to_color

    votes: dict[int, int] = {}
    total = 0
    for px in hsv_pixels:
        if px is None or len(px) < 3:
            continue
        total += 1
        color = hsv_to_color(px[0], px[1], px[2])
        if color:
            votes[color] = votes.get(color, 0) + 1
    if not votes:
        return 0, 0, total
    best_color, best_votes = max(votes.items(), key=lambda kv: (kv[1], -kv[0]))
    if best_votes < max(1, int(min_votes)):
        return 0, best_votes, total
    return best_color, best_votes, total


# --------------------------------------------------------------------------- #
# 依赖 cv2 的部分（延迟导入）
# --------------------------------------------------------------------------- #
def _require_cv2():
    try:
        import cv2  # noqa: PLC0415
    except Exception as exc:                       # pragma: no cover - 环境相关
        raise PlaceEyeUnavailable("没有 cv2：落料位复看不可用") from exc
    return cv2


def sample_hsv_grid(frame_bgr, roi, grid: int = 5):
    """在 ROI 内取 ``grid×grid`` 个点的 HSV（cv2 口径）。ROI 越界会被裁到画面内。"""
    cv2 = _require_cv2()
    h, w = frame_bgr.shape[:2]
    x, y, rw, rh = (int(v) for v in roi)
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    rw = max(1, min(rw, w - x))
    rh = max(1, min(rh, h - y))
    crop = frame_bgr[y:y + rh, x:x + rw]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    n = max(1, int(grid))
    out = []
    for i in range(n):
        py = min(rh - 1, int((i + 0.5) * rh / n))
        for j in range(n):
            px = min(rw - 1, int((j + 0.5) * rw / n))
            # cv2.cvtColor(BGR→HSV) 之后通道顺序是 (H, S, V)
            hh, ss, vv = (int(v) for v in hsv[py, px])
            out.append((hh, ss, vv))
    return out


def capture_frame(cfg: PlaceEyeConfig):
    """打开副相机抓一帧（BGR）。失败抛 :class:`PlaceEyeUnavailable`。"""
    if not cfg.is_usable():
        raise PlaceEyeUnavailable("PlaceEye 未启用或 ROI 缺失")
    cv2 = _require_cv2()
    cap = cv2.VideoCapture(cfg.device)
    if not cap.isOpened():
        raise PlaceEyeUnavailable("打不开副相机 %s" % cfg.device)
    try:
        # 副相机只支持 MJPG（DF200 实测），先设格式再设分辨率
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
            cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        except Exception:
            _LOGGER.warning("副相机参数设置失败（继续用默认）", exc_info=True)
        for _ in range(max(0, cfg.warmup_frames)):
            cap.read()                       # 丢掉曝光未稳定的前几帧
        ok, frame = cap.read()
        if not ok or frame is None:
            raise PlaceEyeUnavailable("副相机读帧失败")
        return frame
    finally:
        cap.release()
