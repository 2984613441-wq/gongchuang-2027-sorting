"""五键排序：停稳 → 待定 → 难度 → 隔离度 → 落点距离 → seq（2026-11-01 新增）。

设计依据
--------
审核报告 `docs/reports/审核-夹取策略-20261101.md`（2026-11-01）：
* D1：排序锚点应为「上一次落料点」，不是固定 `(0,0)`
* D3：缺「停稳」判据（同一目标连续帧位移/尺寸抖动）
* 用户口径（2026-11-01）：
  1. 每件之间回位再拍（不在移动中抓）—— 见 `docs/design/抓取时序-2026-09-15.md:64`
  2. **先易后难**（好判好抓的先抓，难的留到托盘稀疏时）
  3. 别把旁边的件碰跑 ⇒ 需要「隔离度」排在前面

五键顺序（键值越小越先抓）
--------------------------
```
key = (
    deferred,        # 0 = 已停稳/未知但没检测到运动；1 = 明确检测到还在动
    pending,         # 0 = 形状/颜色已确定；1 = 待定（置信不足，排最后）
    tier,            # 难度层 0 易 / 1 中 / 2 难（复用 selector.PICK_TIER_BY_CLASS_ID）
    isolation,       # 目标环带内其他件的个数（越少越先抓，防碰倒）
    drop_distance,   # 到「上一次落料点」的距离（未知则 0，不惩罚）
    -y_mm, x_mm,     # 行列扫描稳定性（沿用 row_scan 口径）
    target_seq,      # 兜底稳定排序
)
```

边界声明
--------
* 本模块**只改顺序、不拒识**（与 `order_by_*_scan` 同口径），也不产生任何硬件动作。
* 所有参数可由调用方显式传入；未传时使用保守默认值，并在 :data:`DEFAULTS` 里集中列出。
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point
from .selector import (
    PICK_TIER_BY_CLASS_ID,
    PICK_TIER_DEFAULT,
    Detection,
    VisionFrame,
    difficulty_tier_of,
    is_pending,
    row_scan_key,
    usable_detections,
)

__all__ = [
    "ORDER_MODES",
    "SettleTracker",
    "order_by_five_key",
    "neighbor_count",
]

#: 可选排序模式（灰度开关用）。``legacy`` = 完全不排序（原顺序）。
ORDER_MODES: tuple[str, ...] = (
    "legacy",
    "group",
    "difficulty",
    "open_edge",
    "five_key",
)

#: 保守默认参数（单位 mm / 帧）。
DEFAULTS: dict[str, float] = {
    "isolation_band_mm": 10.0,   # 环带 = 夹爪包络半宽 + 该值
    "settle_frames": 3.0,        # 连续观察帧数
    "settle_shift_mm": 4.0,      # 中心位移阈值
    "settle_max_wait_frames": 10.0,
}


def neighbor_count(
    det: Detection, dets: tuple[Detection, ...], band_mm: float
) -> int:
    """目标周围 ``band_mm`` 环带内**其他件**的个数（不含自己）。

    用途：隔离度。值越小越好抓（周围越空），越大越容易碰倒邻件。
    """
    n = 0
    for other in dets:
        if other is det:
            continue
        dx = other.x_mm - det.x_mm
        dy = other.y_mm - det.y_mm
        if (dx * dx + dy * dy) <= (band_mm * band_mm):
            n += 1
    return n


@dataclass
class SettleTracker:
    """跟踪「同一 target_seq 是否已经停稳」。

    语义（刻意保守）：
    * 历史不足 :data:`settle_frames` 帧 → 返回 ``None``（**未知**，不惩罚也不奖励）；
    * 最近 N 帧中心位移全部 <= :data:`settle_shift_mm` → ``True``（停稳）；
    * 否则 → ``False``（还在动，排到最后）。

    调用方式：每来一帧调用一次 :meth:`observe`，排序时调用 :meth:`is_settled`。
    """

    settle_frames: int = 3
    settle_shift_mm: float = 4.0
    settle_max_wait_frames: int = 10

    def __post_init__(self) -> None:
        self._history: dict[int, list[tuple[float, float]]] = {}

    def observe(self, frame: VisionFrame) -> None:
        """记录本帧各件位置（按 target_seq）。"""
        keep = max(1, int(self.settle_frames))
        maxlen = max(keep, int(self.settle_max_wait_frames))
        for det in frame.detections:
            buf = self._history.setdefault(int(det.target_seq), [])
            buf.append((float(det.x_mm), float(det.y_mm)))
            if len(buf) > maxlen:
                del buf[0: len(buf) - maxlen]

    def is_settled(self, target_seq: int) -> bool | None:
        """返回 True / False / None（未知）。"""
        buf = self._history.get(int(target_seq))
        need = max(1, int(self.settle_frames))
        if not buf or len(buf) < need:
            return None
        recent = buf[-need:]
        for (x0, y0), (x1, y1) in zip(recent, recent[1:]):
            dx = x1 - x0
            dy = y1 - y0
            if (dx * dx + dy * dy) ** 0.5 > self.settle_shift_mm:
                return False
        return True

    def reset(self) -> None:
        self._history.clear()


def order_by_five_key(
    frame: VisionFrame,
    config,
    *,
    settle: SettleTracker | None = None,
    last_drop: Point | None = None,
    isolation_band_mm: float | None = None,
) -> tuple[Detection, ...]:
    """按五键排序返回**可用件**（不拒识、不丢件）。"""
    usable, _ = usable_detections(frame, config)
    if len(usable) < 2:
        return tuple(usable)

    band = DEFAULTS["isolation_band_mm"] if isolation_band_mm is None else float(isolation_band_mm)
    if isolation_band_mm is None and getattr(config, "gripper_envelope", None) is not None:
        env = config.gripper_envelope
        band = max(float(env.x_mm), float(env.y_mm)) + DEFAULTS["isolation_band_mm"]

    def key(det: Detection):
        settled = settle.is_settled(det.target_seq) if settle is not None else None
        deferred = 0 if settled is not False else 1
        pending = 1 if is_pending(det) else 0
        tier = PICK_TIER_BY_CLASS_ID.get(int(det.class_id), PICK_TIER_DEFAULT)
        isolation = neighbor_count(det, usable, band)
        if last_drop is None:
            drop_d = 0.0
        else:
            dx = det.x_mm - last_drop.x_mm
            dy = det.y_mm - last_drop.y_mm
            drop_d = (dx * dx + dy * dy) ** 0.5
        return (deferred, pending, tier, isolation, drop_d) + row_scan_key(det)

    return tuple(sorted(usable, key=key))
