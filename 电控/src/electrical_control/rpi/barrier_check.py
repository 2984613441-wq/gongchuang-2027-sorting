"""挡板巡检（S3 骨架，2026-11-07）。

需求来源：用户 2026-11-06 原话「每一次放之前都要看一下我们是否将物料崩飞到了这个挡板上」
（设计文档 L76–L82、决策 D6/D7）。动机：件被撞飞到挡板上或卡在挡板边
⇒ ①可能掉件（本轮结束）②后续再撞会二次事故 ③一直抓不到。

边界（先写清权力）
------------------
本模块**只做"看"**：

* **不**发运动指令、**不**碰串口/协议/固件 —— 发现异常后的动作由 `run_chain` 决定；
* **不**判形状/颜色（那是主相机的活）—— 只判「挡板上有没有东西」（CLEAR/OCCUPIED/UNKNOWN）；
  至于"有件时能不能判出 code ⇒ 当正常件抓 / 判不出 ⇒ 夹爪停住"是 D7 的上层分支；
* **默认关闭**：`--barrier-check off|observe|stop`，off 时本模块一行都不执行。

判定方式（用户 2026-11-06 已定）
--------------------------------
**空挡板基准帧差分**（主）+ **HSV/饱和度兜底**（次）；只判"有/无"，不细分类。

* 差分：`|frame - baseline|` 在 ROI 内超过 `pixel_diff` 的像素**占比** ≥ `diff_threshold` ⇒ OCCUPIED；
* 兜底：基准帧缺失或差分不可信（例如 ROI 尺寸不一致）⇒ 用 ROI 内高饱和像素占比作弱证据；
  仍不可判 ⇒ UNKNOWN（**绝不猜"没有"**）。

现场待测（M3，SOP §3.5）：`camera`（main/cam2）、`roi`、`baseline`、`diff_threshold`、
可见性结论 A/B/C —— 这些填进 `[BarrierCheck]` 后本模块才真正可用；骨架阶段
只保证"逻辑与开关正确"，不代表现场可用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "BarrierConfig",
    "BarrierState",
    "BarrierChecker",
    "BarrierCheckError",
    "judge_frame",
    "load_barrier_config",
    "parse_roi",
    "MODES",
]

MODES = ("off", "observe", "stop")


class BarrierCheckError(RuntimeError):
    """巡检配置/图像不可用（fail-closed 时由调用方决定停链）。"""


class BarrierState(str, Enum):
    """挡板巡检三态。UNKNOWN 不等于"没有"——它是"没看清"。"""

    CLEAR = "CLEAR"
    OCCUPIED = "OCCUPIED"
    UNKNOWN = "UNKNOWN"


class FrameProvider(Protocol):
    def __call__(self) -> np.ndarray | None: ...


# ---------------------------------------------------------------------------
# 配置（[BarrierCheck]）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BarrierConfig:
    """`[BarrierCheck]` 段。

    Args:
        mode: off / observe / stop；off = 完全不巡检（默认）。
        camera: main / cam2 —— 现场（M3）测完再定（D8）。
        roi: (x, y, w, h) 像素；M3 用 `工具/pick_roi.py` 框。
        baseline_path: 空挡板基准帧文件（M3 抓的 barrier_<cam>_empty.jpg）。
        diff_threshold: 变化像素占比阈值（0~1，默认 0.02 = 2%）。
        pixel_diff: 单像素灰度差阈值（0~255，默认 30）。
        saturation_threshold: HSV 兜底用的饱和度下限（0~255，默认 90）。
        on_unknown: 取图失败/判不出时的处置：continue（fail-open，默认）
            / stop（fail-closed，现场要求更严时用）。
        snapshot_url: 取图地址（mode != off 时必填）。
        snapshot_timeout_s: 取图超时。
    """

    mode: str = "off"
    camera: str = "main"
    roi: tuple[int, int, int, int] | None = None
    baseline_path: str | None = None
    diff_threshold: float = 0.02
    pixel_diff: int = 30
    saturation_threshold: int = 90
    on_unknown: str = "continue"
    snapshot_url: str | None = None
    snapshot_timeout_s: float = 1.0

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("barrier mode 必须是 %s，收到 %r" % (MODES, self.mode))
        if self.camera not in ("main", "cam2"):
            raise ValueError("barrier camera 必须是 main/cam2，收到 %r" % (self.camera,))
        if not (0.0 < self.diff_threshold <= 1.0):
            raise ValueError("diff_threshold 必须在 (0,1]，收到 %r" % (self.diff_threshold,))
        if not (0 <= self.pixel_diff <= 255):
            raise ValueError("pixel_diff 必须在 0~255，收到 %r" % (self.pixel_diff,))
        if self.on_unknown not in ("continue", "stop"):
            raise ValueError("on_unknown 必须是 continue/stop，收到 %r" % (self.on_unknown,))
        if self.mode != "off":
            if self.roi is None:
                raise BarrierCheckError(
                    "barrier mode=%s 但没配 roi —— 先按 SOP §3.5 框 ROI" % self.mode)
            if not self.baseline_path:
                raise BarrierCheckError(
                    "barrier mode=%s 但没配 baseline —— 先抓空挡板基准帧" % self.mode)
            if not self.snapshot_url:
                raise BarrierCheckError(
                    "barrier mode=%s 但没配 snapshot_url —— 巡检不知道去哪取图" % self.mode)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


def parse_roi(text: str | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """把 `x,y,w,h` 解析成四元组；非法即 raise（fail-closed）。"""
    if isinstance(text, tuple):
        return text
    parts = [p.strip() for p in str(text).replace("，", ",").split(",")]
    if len(parts) != 4:
        raise BarrierCheckError("roi 需要 4 个数（x,y,w,h），收到 %r" % (text,))
    try:
        x, y, w, h = (int(float(p)) for p in parts)
    except ValueError as exc:
        raise BarrierCheckError("roi 含非数字：%r" % (text,)) from exc
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise BarrierCheckError("roi 非法（要求 x,y≥0 且 w,h>0）：%r" % (text,))
    return x, y, w, h


def load_barrier_config(config_path) -> BarrierConfig:
    """读 `[BarrierCheck]` 段；没有该段 ⇒ mode=off（默认关闭，可一键回退）。

    解析失败/字段非法 ⇒ 抛错（加载期 fail-closed，绝不带着半套配置跑）。
    """
    import configparser

    cp = configparser.ConfigParser(inline_comment_prefixes=("#",))
    # utf-8-sig：容忍 Windows 记事本/PowerShell 写出的 BOM（否则第一行会变成
    # '\ufeff[BarrierCheck]'，configparser 报 MissingSectionHeaderError）。
    cp.read(str(config_path), encoding="utf-8-sig")
    if not cp.has_section("BarrierCheck"):
        return BarrierConfig()
    sec = cp["BarrierCheck"]

    def _get(key: str, default: str) -> str:
        return sec.get(key, default).strip()

    roi = None
    if sec.get("roi"):
        roi = parse_roi(sec.get("roi"))
    return BarrierConfig(
        mode=_get("mode", "off").lower(),
        camera=_get("camera", "main").lower(),
        roi=roi,
        baseline_path=_get("baseline", "") or None,
        diff_threshold=float(_get("diff_threshold", "0.02")),
        pixel_diff=int(float(_get("pixel_diff", "30"))),
        saturation_threshold=int(float(_get("saturation_threshold", "90"))),
        on_unknown=_get("on_unknown", "continue").lower(),
        snapshot_url=_get("snapshot_url", "") or None,
        snapshot_timeout_s=float(_get("snapshot_timeout_s", "1.0")),
    )


# ---------------------------------------------------------------------------
# 判定（纯函数，不碰相机/文件）
# ---------------------------------------------------------------------------

def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame.astype(np.float32)
    if frame.ndim == 3:
        # BGR 近似灰度（像素差判定只关心"变没变"，权重不必精确）
        return (frame[..., 0] * 0.114 + frame[..., 1] * 0.587 +
                frame[..., 2] * 0.299).astype(np.float32)
    raise BarrierCheckError("图像维度非法：%r" % (getattr(frame, "shape", None),))


def _crop(gray: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = roi
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise BarrierCheckError("roi 非法：%r" % (roi,))
    if y + h > gray.shape[0] or x + w > gray.shape[1]:
        raise BarrierCheckError(
            "roi %r 超出图像 %r（先按当前分辨率重新框 ROI）" % (roi, gray.shape[:2]))
    return gray[y:y + h, x:x + w]


def judge_frame(
    frame: np.ndarray,
    baseline: np.ndarray | None,
    roi: tuple[int, int, int, int],
    *,
    diff_threshold: float = 0.02,
    pixel_diff: int = 30,
    saturation_threshold: int = 90,
) -> tuple[BarrierState, dict]:
    """判断挡板 ROI 里"有没有东西"。

    返回 `(state, evidence)`；evidence 只含数值，便于日志/复盘。
    基线不可用 ⇒ 退化到"饱和度兜底"；仍不可判 ⇒ UNKNOWN（不猜"没有"）。
    """
    evidence: dict[str, object] = {"roi": roi}
    gray = _to_gray(np.asarray(frame))
    roi_gray = _crop(gray, roi)

    if baseline is not None:
        base_gray = _to_gray(np.asarray(baseline))
        try:
            base_roi = _crop(base_gray, roi)
        except BarrierCheckError as exc:
            evidence["baseline_error"] = str(exc)
            base_roi = None
        if base_roi is not None:
            diff = np.abs(roi_gray - base_roi)
            changed = int((diff > float(pixel_diff)).sum())
            ratio = changed / float(roi_gray.size)
            evidence.update({"diff_ratio": round(ratio, 5), "changed_px": changed,
                             "threshold": diff_threshold})
            state = BarrierState.OCCUPIED if ratio >= diff_threshold else BarrierState.CLEAR
            return state, evidence

    # ---- HSV/饱和度兜底（没有可靠基准帧时）----
    rgb = np.asarray(frame)
    if rgb.ndim == 3 and rgb.shape[2] >= 3:
        x, y, w, h = roi
        patch = rgb[y:y + h, x:x + w, :3].astype(np.float32)
        mx = patch.max(axis=2)
        mn = patch.min(axis=2)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0) * 255.0, 0.0)
        colorful = int((sat >= float(saturation_threshold)).sum())
        ratio = colorful / float(sat.size)
        evidence.update({"hsv_ratio": round(ratio, 5), "colorful_px": colorful,
                         "hsv_threshold": saturation_threshold,
                         "basis": "hsv_fallback"})
        # 兜底只作弱证据：占比很高才敢说"有"，否则 UNKNOWN（不猜"没有"）
        if ratio >= 0.25:
            return BarrierState.OCCUPIED, evidence
    evidence["basis"] = evidence.get("basis", "insufficient")
    return BarrierState.UNKNOWN, evidence


# ---------------------------------------------------------------------------
# 巡检器（取图 + 判定 + 失败处置）
# ---------------------------------------------------------------------------

class BarrierChecker:
    """一次巡检 = 取一帧 → 裁 ROI → 判 CLEAR/OCCUPIED/UNKNOWN。

    `frame_provider` 返回 BGR/灰度 ndarray 或 None；抛错/None/超时 ⇒ UNKNOWN。
    **本类不决定动作**：动作由 `run_chain` 按 mode 与 on_unknown 决定。
    """

    def __init__(
        self,
        config: BarrierConfig,
        frame_provider: FrameProvider,
        baseline: np.ndarray | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not config.enabled:
            raise BarrierCheckError("BarrierChecker 不接受 mode=off（off 时不要构造）")
        if config.roi is None:
            raise BarrierCheckError("BarrierChecker 需要 roi")
        self.config = config
        self._provider = frame_provider
        self._baseline = baseline
        self._clock = clock
        self.checks = 0
        self.last_state: BarrierState | None = None
        self.last_evidence: dict = {}

    def check(self) -> tuple[BarrierState, dict]:
        self.checks += 1
        try:
            frame = self._provider()
        except Exception as exc:  # noqa: BLE001 - 取图失败一律 UNKNOWN
            logger.warning("挡板巡检取图失败：%s", exc)
            self.last_state = BarrierState.UNKNOWN
            self.last_evidence = {"error": str(exc)}
            return self.last_state, self.last_evidence
        if frame is None:
            logger.warning("挡板巡检取图为空 ⇒ UNKNOWN")
            self.last_state = BarrierState.UNKNOWN
            self.last_evidence = {"error": "provider 返回 None"}
            return self.last_state, self.last_evidence

        try:
            state, evidence = judge_frame(
                frame, self._baseline, self.config.roi,
                diff_threshold=self.config.diff_threshold,
                pixel_diff=self.config.pixel_diff,
                saturation_threshold=self.config.saturation_threshold,
            )
        except BarrierCheckError as exc:
            logger.warning("挡板巡检判定失败：%s ⇒ UNKNOWN", exc)
            state, evidence = BarrierState.UNKNOWN, {"error": str(exc)}

        self.last_state, self.last_evidence = state, evidence
        log = logger.info if state is BarrierState.CLEAR else logger.warning
        log("挡板巡检：%s（%s）", state.value, evidence)
        return state, evidence


# ---------------------------------------------------------------------------
# D7 动作映射（只给"有件/没看清"的情形；"有件且能判 code ⇒ 当正常件抓"由上层做）
# ---------------------------------------------------------------------------

def occupied_action(has_code: bool) -> str:
    """D7：挡板上有件时怎么处置。

    * 能判出 code ⇒ ``"treat_as_item"``（当正常件抓了丢进对应格，优先于托盘件）；
    * 判不出 code ⇒ ``"claw_stop"``（夹爪停住，等人工/配置）。
    """
    return "treat_as_item" if has_code else "claw_stop"


def unknown_action(config: BarrierConfig) -> str:
    """没看清时：按 `[BarrierCheck] on_unknown` 决定 continue / stop（fail-open/fail-closed）。"""
    return "stop" if config.on_unknown == "stop" else "continue"
