"""落料位复看的运行时封装（2026-11-01 新增）。

把「抓帧 → ROI 判色 → 三态判决 → 台账纠正 → 统计」串起来，供 `run_chain` 在
`ITEM_RESULT` 到达后调用。

边界
----
* 不改 wire、不发串口、不动运动；只做**观测**与**台账纠正**（后者仅 `correct` 模式）。
* 抓帧函数可注入（`frame_provider`），便于无相机环境下单测。
* 任何异常都**不得**拖垮主链：一律计数为 UNKNOWN 并记 WARNING。

三档开关
--------
============  ====================================================
off           完全不看（默认）
observe       只看、只计数、只记日志，**不改台账**
correct       看 + 不符时调 `SlotAllocator.correct()` 纠正台账
============  ====================================================
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

__all__ = ["PlaceVerifyRuntime", "MODES"]

MODES = ("off", "observe", "correct")


class PlaceVerifyRuntime:
    """落料位复看运行时：一次判决 + 累计统计。"""

    def __init__(
        self,
        mode: str = "off",
        *,
        cfg=None,
        allocator=None,
        frame_provider=None,
    ) -> None:
        if mode not in MODES:
            raise ValueError("verify mode 必须是 %s，收到 %r" % (MODES, mode))
        self._mode = mode
        self._cfg = cfg
        self._allocator = allocator
        self._frame_provider = frame_provider
        self._stats = {
            "checked": 0, "match": 0, "mismatch": 0, "unknown": 0,
            "skipped": 0, "corrected": 0,
        }

    # ------------------------------------------------------------------ 查询
    @property
    def mode(self) -> str:
        return self._mode

    def enabled(self) -> bool:
        return self._mode != "off"

    def stats(self) -> dict:
        return dict(self._stats)

    def summary(self) -> str:
        s = self._stats
        return ("复看统计：检查 %d（MATCH %d / MISMATCH %d / UNKNOWN %d），"
                "跳过 %d，纠正台账 %d" % (
                    s["checked"], s["match"], s["mismatch"], s["unknown"],
                    s["skipped"], s["corrected"]))

    # ------------------------------------------------------------------ 主入口
    def on_item_result(
        self,
        *,
        target_seq: int,
        class_id: int,
        box_id: int | None = None,
        result_code: int = 0,
    ) -> dict | None:
        """ITEM_RESULT 到达后调用。返回判决字典（供日志/监控），off 或跳过时返回 None。"""
        if self._mode == "off":
            return None
        if int(result_code) != 0:
            self._stats["skipped"] += 1        # 未成功：本件没放到格子里，不看
            return None
        if self._cfg is None or not getattr(self._cfg, "is_usable", lambda: False)():
            self._stats["unknown"] += 1
            _LOGGER.debug("复看跳过：PlaceEye 未配置/未启用")
            return None

        color = self._read_color()
        if color is None:
            self._stats["checked"] += 1
            self._stats["unknown"] += 1
            return {"verdict": "UNKNOWN", "target_seq": target_seq,
                    "code": int(class_id), "reason": "取帧/判色失败"}

        from .place_verifier import Verdict, verify_place_color

        check = verify_place_color(int(class_id), color)
        self._stats["checked"] += 1
        if check.verdict is Verdict.MATCH:
            self._stats["match"] += 1
        elif check.verdict is Verdict.MISMATCH:
            self._stats["mismatch"] += 1
            self._maybe_correct(check, box_id)
        else:
            self._stats["unknown"] += 1

        return {
            "verdict": check.verdict.value,
            "target_seq": target_seq,
            "code": check.expected_code,
            "observed_color": color,
            "observed_code": check.observed_code,
            "detail": check.detail,
        }

    # ------------------------------------------------------------------ 内部
    def _read_color(self) -> int | None:
        """抓一帧 → ROI 采样 → 判色；任何失败返回 None（→ UNKNOWN）。"""
        from .place_eye import PlaceEyeUnavailable, majority_color, sample_hsv_grid

        try:
            if self._frame_provider is not None:
                frame = self._frame_provider(self._cfg)
            else:
                from .place_eye import capture_frame
                frame = capture_frame(self._cfg)
            pixels = sample_hsv_grid(frame, self._cfg.roi, self._cfg.grid)
            color, _votes, _total = majority_color(
                pixels, min_votes=self._cfg.min_votes)
            return int(color)                 # 0 = 判不出，交给 verify 处理成 UNKNOWN
        except PlaceEyeUnavailable:
            _LOGGER.debug("复看取帧不可用（无 cv2 / 相机忙）", exc_info=True)
            return None
        except Exception:
            _LOGGER.warning("复看取帧/判色异常：按 UNKNOWN 处理", exc_info=True)
            return None

    def _maybe_correct(self, check, box_id: int | None) -> None:
        if self._mode != "correct":
            return
        if self._allocator is None or box_id is None:
            _LOGGER.warning("复看不符但无法纠正台账（allocator=%s, box_id=%s）",
                            self._allocator is not None, box_id)
            return
        if not check.needs_ledger_fix:
            return
        try:
            if self._allocator.correct(check.expected_code, check.observed_code, box_id):
                self._stats["corrected"] += 1
        except Exception:
            _LOGGER.warning("复看纠正台账异常", exc_info=True)
