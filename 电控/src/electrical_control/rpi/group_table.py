"""动态货格分配表 (GroupTable) — 省赛模式核心调度逻辑。

设计要求
--------
1. **分层清楚**：decode（纯）→ aggregate（可测）→ assign（纯）→ schedule（副作用）
2. **表的生命周期**：按轮（round_id）重置；落盘 JSON；断线/重启恢复
3. **绑定可变性**：第一件落下前可变；落下后不可变
4. **第 7 类 = 矛盾**：返回 CONTRADICTION，不简单拒识
5. **第 5 类 = 静默合并**：必须检测并标记 MERGE_SUSPECT
6. **占用计数分离**：分配幂等；count 只由 on_drop_ok() +1
7. **反饿死看门狗**：5s 无派发 ⇒ 强制动作
8. **Cmax = 4 硬上限**：满 4 件拒绝再抓
9. **掉件 = 本轮结束**：吸盘失败必须硬停止
10. **落料成功可观测**：需要 DROP_OK/DROP_FAIL/DROP_UNKNOWN 反馈

Protocol
--------
视觉侧 code 编码（1~30）：
    code = shape_idx * 5 + color_idx + 1
    shape_idx ∈ 0..5  (0=正方体 1=长方体 2=圆柱 3=五棱柱 4=圆锥 5=正四面体)
    color_idx ∈ 0..4  (0=红 1=黄 2=绿 3=蓝 4=白)

屏幕图片映射：
    code 同时就是 image_id（/home/pi/images/1.png ~ 30.png）
    映射表：/home/pi/电控/deploy/manifest.json

Invariants (5 条不变量)
-----------------------
1. 双射：一个盒只有一个 code；一个 code 只有一个盒
2. count 隔离：只由 on_drop_ok(code) 增加
3. 范围检查：code ∉ [1,30] 不进表
4. 第 7 类矛盾：第 7 个 code 返回 CONTRADICTION，不返回 REJECT
5. 落下后不可变：count[code] > 0 后拒绝 rebind/merge
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_LOGGER = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

NUM_BOXES = 6
"""储物盒数量（赛规固定 6 个）"""

MAX_COUNT_PER_BOX = 3
"""每盒最多放 3 件 —— **刻意不用赛规允许的 4**。

## 为什么取 3 而不是 4（2026-10-26 用户裁决 + 工程推理）

赛规 L42-43 说储物盒要能装「不超过4个」，所以**物理上限是 4**。
但 `count` 这个计数**不是物理占用数**，而是"我们以为放进去的次数"。

固件 `ec_app.c:701-704` 的分类是 **PLACEHOLDER**：
    `axis_result == OK`  ⇒ `EC_RESULT_SUCCESS`
    否则                 ⇒ `EC_RESULT_DROP_FAILED`
而 `axis_result == OK` 只代表**运动序列跑完**，不代表件真进了盒。
以下情况都会报 SUCCESS 却实际没进盒：
  · 吸盘没吸住（抓空）⇒ 件留在托盘
  · 吸住后半路掉件
  · 真空衰减中途脱落

⇒ 若按 4 封顶，一旦 `count` 虚增 1，就会出现
  「以为 4 件、实际还在往里塞第 5 件」
  ⇒ 挤出别人的件 / 滚进邻盒
  ⇒ **混装 0 分** 或 **掉件 ⇒ 本轮比赛结束**（赛规 L267-268）。

⇒ 所以留 1 件余量：**宁可少拿 5 分（3 件 15 分 vs 4 件 20 分），
  也不能因为挤出/掉件丢掉整轮。**

## 什么时候可以改回 4

只有在**落料真的有传感器确认**之后才能改成 4，例如：
  · 真空压力开关（吸住 -40~-60 kPa 导通，掉了断开）接进 STM32 一个 GPIO
  · 或 ToF 测盒内高度
届时 `ec_app.c` 的 result_code 才真正区分"进了"和"没进"，
`count` 才等于物理占用数。

## 已知代价

理论上限从 13×5 = 65 分降到：若某类有 4 件，第 4 件只能留在托盘
⇒ 最多少拿 5 分/轮。用户 2026-10-26 决定：「先取 3，看效果再决定要不要 4」。
"""

CODE_MIN = 1
CODE_MAX = 30
"""视觉 code 范围 [1, 30]"""

# ── Result Types ──────────────────────────────────────────────────────────────

AssignResult = Literal[
    "OK",              # 成功分配
    "CONTRADICTION",   # 第 7 类矛盾（无空闲盒）
    "UNPLACED",        # 无法放置（盒子已有件且无法合并）
    "FULL",            # 该类已满 4 件
    "OUT_OF_RANGE",    # code 越界
    "MERGE_SUSPECT",   # 疑似静默合并（≤5 类但见 ≥11 件）
]


# ── Decode Layer (纯函数) ──────────────────────────────────────────────────────

def decode_code(code: int) -> tuple[int, int] | None:
    """解码 code → (shape_idx, color_idx)。

    Args:
        code: 视觉侧编码 (1~30)

    Returns:
        (shape_idx, color_idx) 或 None（越界）

    Examples:
        >>> decode_code(1)   # 正方体-红
        (0, 0)
        >>> decode_code(6)   # 正方体-白
        (0, 4)
        >>> decode_code(7)   # 长方体-红
        (1, 0)
        >>> decode_code(30)  # 正四面体-白
        (5, 4)
        >>> decode_code(0)   # 越界
        None
    """
    if not (CODE_MIN <= code <= CODE_MAX):
        return None
    # code = shape_idx * 5 + color_idx + 1
    # ⇒ shape_idx = (code - 1) // 5, color_idx = (code - 1) % 5
    idx = code - 1
    return (idx // 5, idx % 5)


def encode_code(shape_idx: int, color_idx: int) -> int:
    """编码 (shape_idx, color_idx) → code。

    与 decode_code 互逆。
    """
    return shape_idx * 5 + color_idx + 1


# ── Box State ─────────────────────────────────────────────────────────────────

@dataclass
class BoxState:
    """单个储物盒的状态。"""

    box_id: int
    """盒号 (1~6)"""

    bound_code: int | None = None
    """绑定的 code（None = 未绑定）"""

    dropped_count: int = 0
    """已成功落下的件数（只由 on_drop_ok 增加）"""

    state: Literal["EMPTY", "BOUND", "DROPPING", "SUSPECT", "FULL"] = "EMPTY"
    """
    状态：
    - EMPTY: 空盒，未绑定
    - BOUND: 已绑定但还没落下任何件
    - DROPPING: 至少落下 1 件
    - SUSPECT: 落料反馈 UNKNOWN，不再进新件
    - FULL: 已满 4 件
    """


# ── Group Table ───────────────────────────────────────────────────────────────

@dataclass
class GroupTable:
    """动态货格分配表（核心调度逻辑）。

    Attributes:
        round_id: 本轮 ID（重置单位）
        boxes: 6 个储物盒的状态
        code_to_box: code → box_id 映射（反查索引）
        seen_codes: 见过的所有 code（用于检测第 7 类和静默合并）
        seen_items_total: 见过的总件数（用于检测静默合并）
        state_file: 状态持久化文件路径
    """

    round_id: str
    boxes: list[BoxState] = field(default_factory=list)
    code_to_box: dict[int, int] = field(default_factory=dict)
    seen_codes: set[int] = field(default_factory=set)
    seen_items_total: int = 0
    state_file: Path | None = None

    def __post_init__(self):
        """初始化 6 个空盒。"""
        if not self.boxes:
            self.boxes = [BoxState(box_id=i) for i in range(1, NUM_BOXES + 1)]

    # ── Core Assignment Logic (纯函数层) ────────────────────────────────────────

    def assign(self, code: int) -> tuple[int | None, AssignResult]:
        """分配 code 到储物盒（纯函数，幂等）。

        **不变量**：
        1. 同一个 code 多次调用返回同一个 box_id
        2. 不修改 dropped_count（只由 on_drop_ok 修改）
        3. 绑定可变性：count > 0 后不可 rebind

        Args:
            code: 视觉侧编码 (1~30)

        Returns:
            (box_id, result) 或 (None, error_code)

        Result Codes:
            - OK: 成功分配（新绑定或复用已绑定）
            - CONTRADICTION: 第 7 类矛盾（6 个盒都绑定了且这是新 code）
            - FULL: 该类已满 4 件
            - OUT_OF_RANGE: code 越界
            - MERGE_SUSPECT: 疑似静默合并
            - UNPLACED: 无法放置
        """
        # ── Invariant 3: 范围检查 ────────────────────────────────────────────
        if not (CODE_MIN <= code <= CODE_MAX):
            return (None, "OUT_OF_RANGE")

        # ── 检测静默合并（第 5 类）─────────────────────────────────────────
        # 条件：≤5 个不同 code 且已见 ≥11 件 ⇒ 必有两类装进同一盒
        unique_codes = len(self.seen_codes | {code})
        total_items = self.seen_items_total + 1  # 加上这一件
        if unique_codes <= 5 and total_items >= 11:
            _LOGGER.warning(
                "疑似静默合并：只见到 %d 类 code，但已见 %d 件（≥11）"
                "⇒ 必有两类被判成同一 code。该盒需强制二次确认",
                unique_codes, total_items
            )
            return (None, "MERGE_SUSPECT")

        # ── 已绑定：直接返回 ──────────────────────────────────────────────
        if code in self.code_to_box:
            box_id = self.code_to_box[code]
            box = self.boxes[box_id - 1]

            # 检查是否已满
            if box.dropped_count >= MAX_COUNT_PER_BOX:
                return (None, "FULL")

            # SUSPECT 盒不再进新件
            if box.state == "SUSPECT":
                return (None, "UNPLACED")

            return (box_id, "OK")

        # ── 第 7 类矛盾检测（Invariant 4）──────────────────────────────────
        # 6 个盒都绑定了 ⇒ 这是第 7 个 code ⇒ 返回 CONTRADICTION
        bound_boxes = [b for b in self.boxes if b.bound_code is not None]
        if len(bound_boxes) >= NUM_BOXES:
            _LOGGER.warning(
                "第 7 类矛盾：6 个盒都已绑定，code=%d 无法分配。"
                "已绑定：%s",
                code, {b.box_id: b.bound_code for b in bound_boxes}
            )
            return (None, "CONTRADICTION")

        # ── 新绑定：找空盒 ────────────────────────────────────────────────
        for box in self.boxes:
            if box.bound_code is None:
                # 找到空盒，绑定（注意：这里不修改 dropped_count）
                box.bound_code = code
                box.state = "BOUND"
                self.code_to_box[code] = box.box_id
                _LOGGER.info(
                    "新绑定：code=%d → box_id=%d（现有绑定数：%d）",
                    code, box.box_id, len(bound_boxes) + 1
                )
                return (box.box_id, "OK")

        # 理论上不应到这里（上面已经检查了 CONTRADICTION）
        return (None, "UNPLACED")

    # ── Event Handlers (有副作用) ──────────────────────────────────────────────

    def on_drop_ok(self, code: int) -> bool:
        """落料成功事件（唯一修改 dropped_count 的地方）。

        **Invariant 2**: 只有这个函数可以增加 dropped_count。
        **Invariant 5**: count > 0 后，该 code 的绑定不可变。

        Args:
            code: 成功落下的 code

        Returns:
            True = 计数成功；False = code 未绑定或已满
        """
        if code not in self.code_to_box:
            _LOGGER.warning("on_drop_ok: code=%d 未绑定，忽略", code)
            return False

        box_id = self.code_to_box[code]
        box = self.boxes[box_id - 1]

        if box.dropped_count >= MAX_COUNT_PER_BOX:
            _LOGGER.warning(
                "on_drop_ok: box_id=%d 已满 %d 件，拒绝再加",
                box_id, MAX_COUNT_PER_BOX
            )
            return False

        # Invariant 2: 唯一的 +1 位置
        box.dropped_count += 1

        # 更新状态
        if box.dropped_count >= MAX_COUNT_PER_BOX:
            box.state = "FULL"
        elif box.dropped_count > 0:
            box.state = "DROPPING"

        _LOGGER.info(
            "落料成功：code=%d → box_id=%d（计数 %d/%d）",
            code, box_id, box.dropped_count, MAX_COUNT_PER_BOX
        )

        # 落盘
        if self.state_file:
            self._save_state()

        return True

    def on_drop_fail(self, code: int, reason: str = "") -> None:
        """落料失败事件（记录但不修改计数）。"""
        _LOGGER.error(
            "落料失败：code=%d, reason=%s。⚠️ 赛规：掉件 = 本轮结束",
            code, reason
        )
        # TODO: 触发硬停止（需要与 scheduler 联动）

    def on_drop_unknown(self, code: int) -> None:
        """落料反馈不明（标记该盒 SUSPECT，不再进新件）。"""
        if code not in self.code_to_box:
            return

        box_id = self.code_to_box[code]
        box = self.boxes[box_id - 1]
        box.state = "SUSPECT"

        _LOGGER.warning(
            "落料反馈不明：code=%d → box_id=%d 标记 SUSPECT（不再进新件）",
            code, box_id
        )

        if self.state_file:
            self._save_state()

    # ── Aggregate Layer (可测逻辑) ─────────────────────────────────────────────

    def update_seen(self, code: int) -> None:
        """更新"见过的 code"计数（用于静默合并检测）。

        注意：这是识别事件，不是落料事件；与 dropped_count 分离。
        """
        if code not in self.seen_codes:
            self.seen_codes.add(code)
        self.seen_items_total += 1

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """落盘到 JSON。"""
        if not self.state_file:
            return

        state = {
            "round_id": self.round_id,
            "boxes": [
                {
                    "box_id": b.box_id,
                    "bound_code": b.bound_code,
                    "dropped_count": b.dropped_count,
                    "state": b.state,
                }
                for b in self.boxes
            ],
            "code_to_box": self.code_to_box,
            "seen_codes": list(self.seen_codes),
            "seen_items_total": self.seen_items_total,
        }

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self.state_file.open("w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            _LOGGER.error("保存状态失败：%s", e)

    @classmethod
    def load_or_create(
        cls, round_id: str, state_file: Path | None = None
    ) -> GroupTable:
        """从文件加载或创建新表。

        **生命周期规则**：
        1. 文件不存在 ⇒ 创建新表
        2. 文件存在且 round_id 匹配 ⇒ 恢复
        3. 文件存在但 round_id 不匹配 ⇒ 进只读模式（全盒 UNKNOWN）

        Args:
            round_id: 本轮 ID
            state_file: 状态文件路径

        Returns:
            GroupTable 实例
        """
        if not state_file or not state_file.exists():
            _LOGGER.info("新建表：round_id=%s", round_id)
            table = cls(round_id=round_id, state_file=state_file)
            if state_file:
                table._save_state()
            return table

        # 加载文件
        try:
            with state_file.open("r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            _LOGGER.error("加载状态失败：%s，创建新表", e)
            return cls(round_id=round_id, state_file=state_file)

        # 检查 round_id
        saved_round_id = state.get("round_id", "")
        if saved_round_id != round_id:
            _LOGGER.warning(
                "round_id 不匹配（文件=%s, 请求=%s）⇒ 进只读模式（全盒 UNKNOWN）",
                saved_round_id, round_id
            )
            # 全盒标 SUSPECT（不再进新件）
            table = cls(round_id=round_id, state_file=state_file)
            for box in table.boxes:
                box.state = "SUSPECT"
            return table

        # 恢复状态
        boxes = [
            BoxState(
                box_id=b["box_id"],
                bound_code=b["bound_code"],
                dropped_count=b["dropped_count"],
                state=b["state"],
            )
            for b in state.get("boxes", [])
        ]

        code_to_box = {int(k): v for k, v in state.get("code_to_box", {}).items()}
        seen_codes = set(state.get("seen_codes", []))
        seen_items_total = state.get("seen_items_total", 0)

        _LOGGER.info(
            "恢复表：round_id=%s，绑定数=%d，总计数=%d",
            round_id, len(code_to_box), seen_items_total
        )

        return cls(
            round_id=round_id,
            boxes=boxes,
            code_to_box=code_to_box,
            seen_codes=seen_codes,
            seen_items_total=seen_items_total,
            state_file=state_file,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_box_for_code(self, code: int) -> int | None:
        """查询 code 对应的 box_id（不修改状态）。"""
        return self.code_to_box.get(code)

    def get_box_state(self, box_id: int) -> BoxState | None:
        """查询盒子状态（不修改状态）。"""
        if not (1 <= box_id <= NUM_BOXES):
            return None
        return self.boxes[box_id - 1]

    def summary(self) -> dict:
        """返回表的摘要信息（用于日志/调试）。"""
        return {
            "round_id": self.round_id,
            "bound_count": len(self.code_to_box),
            "total_dropped": sum(b.dropped_count for b in self.boxes),
            "seen_codes_count": len(self.seen_codes),
            "seen_items_total": self.seen_items_total,
            "bindings": {b.box_id: b.bound_code for b in self.boxes if b.bound_code},
            "counts": {b.box_id: b.dropped_count for b in self.boxes if b.dropped_count > 0},
        }


__all__ = [
    "AssignResult",
    "BoxState",
    "GroupTable",
    "decode_code",
    "encode_code",
    "CODE_MIN",
    "CODE_MAX",
    "NUM_BOXES",
    "MAX_COUNT_PER_BOX",
]
