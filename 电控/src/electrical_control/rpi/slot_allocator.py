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

分配规则（按优先级，2026-11-07 S2 定稿）
----------------------------------------
1. **同 code 复用**：该 (shape,color) 已分配到某格 ⇒ 继续用同一格（集中落点、少换格）。
2. **空格选择 = 编号最小（1→6）**：保证转盘角度单调 +60°、不回摆，且完全可复现。
3. 全满 ⇒ 返回 ``None``（上层拒识/等待，不猜）。

~~2. 优先「与当前转盘挡位相同」的空格~~ —— **已删除**（2026-11-07，S2）：
360° 转盘每格差 60°、位置域是绝对坐标，"同侧"没有意义；保留 `side_of_box`
构造参数只为兼容旧调用，**传了也会被忽略**并打一条 WARNING。
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
        # ⚠️ 2026-11-07（S2）：side_of_box 已废弃 —— 选格固定 1→6，不再按"侧"挑格。
        #    参数保留只为旧调用方不炸；传了就忽略并提示。
        if side_of_box:
            _LOGGER.warning(
                "slot_allocator：side_of_box 已废弃（2026-11-07 S2：选格固定 1→6），"
                "本次忽略 %s", side_of_box,
            )
        self._side_of_box: dict[int, str] = {}
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

        # 2026-11-07（S2）：两侧逻辑已删除 —— 空格里直接取编号最小的（1→6 单调）
        chosen = min(free)
        self._assign(code, chosen)
        return chosen

    def correct(self, expected_code: int, actual_code: int, box_id: int) -> bool:
        """落料位复看发现不一致时**纠正台账**（2026-11-01）。

        场景：派发时以为 code=A 放到 box=B，复看发现该格里实际是 code=C。
        处置：
          * 解除 A→B（若 A 确实指向 B）；
          * 记 C→B（同格复用规则从此按实际走）；
          * 若 C 已指向别的格（另一处不一致）⇒ 只记日志、不改 C 的旧映射，返回 False，
            让上层人工/后续复看去收敛，避免静默覆盖。
        """
        expected_code = int(expected_code)
        actual_code = int(actual_code)
        box_id = int(box_id)
        if box_id not in self._boxes:
            _LOGGER.warning("复看纠正：box_id=%d 不在可用货格 %s，忽略",
                            box_id, self._boxes)
            return False
        if self._code_to_box.get(actual_code, box_id) != box_id:
            _LOGGER.warning(
                "复看纠正冲突：实际 code=%d 已映射到 box=%d，但复看在 box=%d 看到它；"
                "保留旧映射，不改",
                actual_code, self._code_to_box[actual_code], box_id)
            return False
        if self._code_to_box.get(expected_code) == box_id:
            del self._code_to_box[expected_code]
        self._box_to_code[box_id] = actual_code
        self._code_to_box[actual_code] = box_id
        self._last_box = box_id
        self._save()
        _LOGGER.info("复看纠正：box=%d 实际为 code=%d（原以为 code=%d）",
                     box_id, actual_code, expected_code)
        return True

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
