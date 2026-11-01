"""落料位复看判决（2026-11-01 新增）。

用户口径（2026-11-01）：
* 复看位置选 **落料位 + 副相机（DF200）**：「副摄像头只是远端有点看不完全，
  但是落点是看的完的」。
* 目的：确认**实际被抓到并放下的**是不是派发时认定的那件（code）。

边界（先写清楚）
----------------
* 本模块**纯逻辑**：只把「期望 code」与「落料位观测到的 code 列表」比对成三态，
  不抓帧、不判色、不发串口、不改 wire。
* 取帧与判色在视觉侧（`_pi_tools` 里的双相机脚本 / MaixCAM 侧）完成，本模块只吃结果。
* 判决只影响 **台账（SlotAllocator）** 与日志；是否「二次搬运纠正」由上层开关决定。

三态语义
--------
================  ====================================================
MATCH             观测里出现期望 code ⇒ 记账确认
MISMATCH          观测非空且不含期望 code ⇒ 台账需要纠正（同 code 复用会把错判放大）
UNKNOWN           观测为空 / 置信度不足 / 件被遮挡 ⇒ 不动作，只计数
================  ====================================================

⚠️ 复看**不一定**每件都做：落料位常被夹爪/机身短暂遮挡，漏验比错判安全。
"""

from __future__ import annotations

import logging
from enum import Enum

_LOGGER = logging.getLogger(__name__)

__all__ = ["Verdict", "PlaceCheck", "verify_place"]


class Verdict(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class PlaceCheck:
    """一次复看的判决结果（不可变）。"""

    __slots__ = ("verdict", "expected_code", "observed_code", "detail")

    def __init__(
        self,
        verdict: Verdict,
        expected_code: int,
        observed_code: int | None,
        detail: str = "",
    ) -> None:
        self.verdict = verdict
        self.expected_code = int(expected_code)
        self.observed_code = None if observed_code is None else int(observed_code)
        self.detail = detail

    def __repr__(self) -> str:                       # pragma: no cover - 仅日志
        return "PlaceCheck(%s, expected=%d, observed=%s%s)" % (
            self.verdict.value, self.expected_code, self.observed_code,
            (", " + self.detail) if self.detail else "",
        )

    @property
    def needs_ledger_fix(self) -> bool:
        """MISMATCH 且能确定实际 code ⇒ 需要纠正台账。"""
        return self.verdict is Verdict.MISMATCH and self.observed_code is not None


def verify_place(
    expected_code: int,
    observed_codes,
    *,
    min_conf: int = 0,
    confidences=None,
) -> PlaceCheck:
    """把「期望 code」与「落料位观测」比对成三态。

    Args:
        expected_code: 派发时认定的 code(1..30)。
        observed_codes: 落料位一帧里检出的 code 序列（>=1 件时通常只有 1 件）。
        min_conf: 观测置信度阈值（0..100）；低于它的观测视为不可用。
        confidences: 与 ``observed_codes`` 等长的置信度序列；None 视为全部合格。

    Returns:
        :class:`PlaceCheck`。多个候选中若能唯一匹配期望 ⇒ MATCH；都不匹配 ⇒
        取置信度最高的候选作为 ``observed_code``（供台账纠正）。
    """
    expected = int(expected_code)
    codes = [int(c) for c in (observed_codes or ()) if c is not None]
    confs = list(confidences) if confidences is not None else [100] * len(codes)
    if len(confs) < len(codes):
        confs += [100] * (len(codes) - len(confs))

    usable = [(c, int(k)) for c, k in zip(codes, confs) if int(k) >= int(min_conf)]
    if not usable:
        return PlaceCheck(Verdict.UNKNOWN, expected, None, "落料位无可用观测")

    if any(c == expected for c, _ in usable):
        return PlaceCheck(Verdict.MATCH, expected, expected)

    best = max(usable, key=lambda ck: ck[1])
    _LOGGER.warning(
        "落料位复看不符：期望 code=%d，实际看到 code=%s ⇒ 台账需纠正",
        expected, [c for c, _ in usable],
    )
    return PlaceCheck(
        Verdict.MISMATCH, expected, best[0],
        "观测=%s" % ([c for c, _ in usable],),
    )
