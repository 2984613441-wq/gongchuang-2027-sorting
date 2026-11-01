"""货格动态分配器（2026-11-01 新增）。

用户口径（2026-11-01）：「肯定要动态分配，要不然比赛肯定出问题」。
动机：赛规按「同色同形每件 5 分」计分，落点越集中越好；但托盘上件是随机出现的，
固定 30 项 `[BoxMap]` 在场地临时改摆位/加件时会直接判错，所以运行时分配货格。

边界（先写清楚）
----------------
* 本模块**只决定 code → box_id**（哪个货格），不产生落点/脉宽、不发串口、不改 wire。
  `box_id → 落点/转盘侧/脉宽` 仍由 :mod:`electrical_control.rpi.drop_strategy` 静态表给出
  （方案A `[DropPoints]` / 方案C `[TurntablePositions]+[TurntableSides]`）。
* 不修改 `ITEM_TASK`：落点照旧在 offset 3-6 传，动态分配是 Pi 内部决策。
* 默认 `mode="static"`（走旧 `[BoxMap]`），显式 `dynamic` 才启用分配 ⇒ 一键回退。

分配规则（按优先级）
--------------------
1. **同 code 复用**：该 (shape,color) 已分配到某格 ⇒ 继续用同一格（集中落点、少换格）。
2. **优先「与当前转盘挡位相同」的空格**：减少转盘换挡次数（方案C 下 `side` 只有两个值）。
3. **再按格号升序**（1..6），保证可复现。
4. 全满 ⇒ 返回 ``None``（上层拒识/等待，不猜）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

__all__ = ["SlotAllocator", "AllocatorFull"]


class AllocatorFull(RuntimeError):
    """所有货格都已占用（六格满）时抛出（仅在 strict=True 时）。"""


class SlotAllocator:
    """code(1..30) → box_id(1..6) 的动态分配器（可持久化）。"""

    def __init__(
        self,
        box_ids: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
        *,
        mode: str = "static",
        static_map: dict[int, int] | None = None,
        side_of_box: dict[int, str] | None = None,
        journal_path: str | Path | None = None,
        round_id: str | None = None,
        strict: bool = False,
    ) -> None:
        if mode not in ("static", "dynamic"):
            raise ValueError("mode 必须是 'static' 或 'dynamic'，收到 %r" % (mode,))
        self._mode = mode
        self._boxes = tuple(int(b) for b in box_ids)
        if not self._boxes:
            raise ValueError("box_ids 不能为空")
        self._static = dict(static_map or {})
        self._side_of_box = dict(side_of_box or {})
        self._journal = Path(journal_path) if journal_path else None
        self._round_id = round_id
        self._strict = bool(strict)

        # code -> box_id（持久化内容）+ 反向占用表
        self._code_to_box: dict[int, int] = {}
        self._box_to_code: dict[int, int] = {}
        self._last_box: int | None = None
        self._load()

    # ------------------------------------------------------------------ 查询
    @property
    def mode(self) -> str:
        return self._mode

    def box_for(self, code: int) -> int | None:
        """返回该 code 应落到的货格；无格可用返回 None（不猜）。"""
        code = int(code)
        if self._mode == "static":
            return self._static.get(code)

        # 1) 同 code 复用
        hit = self._code_to_box.get(code)
        if hit is not None:
            return hit

        # 2) 空格里优先「与上次落点同侧」，减少转盘换挡
        free = [b for b in self._boxes if b not in self._box_to_code]
        if not free:
            if self._strict:
                raise AllocatorFull("货格已满：%s" % (sorted(self._box_to_code),))
            _LOGGER.warning("货格已满（%s 已占用），code=%d 无法分配",
                            sorted(self._box_to_code.items()), code)
            return None

        prev_side = self._side_of_box.get(self._last_box) if self._last_box else None
        if prev_side is not None:
            same_side = [b for b in free if self._side_of_box.get(b) == prev_side]
            if same_side:
                free = same_side

        chosen = min(free)
        self._assign(code, chosen)
        return chosen

    def assignment(self) -> dict[int, int]:
        """只读副本：code -> box_id。"""
        return dict(self._code_to_box)

    def occupancy(self) -> dict[int, int]:
        """只读副本：box_id -> code。"""
        return dict(self._box_to_code)

    # ------------------------------------------------------------------ 内部
    def _assign(self, code: int, box: int) -> None:
        self._code_to_box[code] = box
        self._box_to_code[box] = code
        self._last_box = box
        self._save()
        _LOGGER.info("动态分配：code=%d → box_id=%d（已占 %d/%d 格）",
                     code, box, len(self._box_to_code), len(self._boxes))

    def _load(self) -> None:
        if self._journal is None or not self._journal.exists():
            return
        try:
            data = json.loads(self._journal.read_text(encoding="utf-8"))
        except Exception:
            _LOGGER.warning("分配台账读不出（%s）：按空台账开始", self._journal,
                            exc_info=True)
            return
        if self._round_id is not None and data.get("round_id") != self._round_id:
            _LOGGER.info("分配台账属于旧轮次（%s ≠ %s）：忽略",
                         data.get("round_id"), self._round_id)
            return
        for k, v in (data.get("code_to_box") or {}).items():
            code, box = int(k), int(v)
            if box in self._boxes and box not in self._box_to_code:
                self._code_to_box[code] = box
                self._box_to_code[box] = code
        self._last_box = data.get("last_box")

    def _save(self) -> None:
        if self._journal is None:
            return
        payload = {
            "round_id": self._round_id,
            "code_to_box": {str(k): v for k, v in sorted(self._code_to_box.items())},
            "last_box": self._last_box,
        }
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            self._journal.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            _LOGGER.warning("分配台账写不出（%s）：本件照常、下轮可能重复用格",
                            self._journal, exc_info=True)
