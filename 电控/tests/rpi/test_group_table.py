"""单测：GroupTable（货格分配表）。

覆盖 5 条不变量 + 4 种故障注入。
"""

import tempfile
from pathlib import Path

import pytest

from electrical_control.rpi.group_table import (
    CODE_MAX,
    CODE_MIN,
    MAX_COUNT_PER_BOX,
    NUM_BOXES,
    GroupTable,
    decode_code,
    encode_code,
)


# ── Decode/Encode Tests ───────────────────────────────────────────────────────

def test_decode_encode_roundtrip():
    """编解码互逆。"""
    for shape_idx in range(6):
        for color_idx in range(5):
            code = encode_code(shape_idx, color_idx)
            assert CODE_MIN <= code <= CODE_MAX
            decoded = decode_code(code)
            assert decoded == (shape_idx, color_idx)


def test_decode_out_of_range():
    """越界 code 返回 None。"""
    assert decode_code(0) is None
    assert decode_code(31) is None
    assert decode_code(-1) is None


def test_encode_boundaries():
    """边界编码正确。"""
    # 正方体-红 = 1
    assert encode_code(0, 0) == 1
    # 正四面体-白 = 30
    assert encode_code(5, 4) == 30


# ── Invariant 1: 双射（一个盒只有一个 code；一个 code 只有一个盒）──────────

def test_invariant_1_one_code_one_box():
    """不变量 1：同一个 code 多次分配返回同一个 box_id。"""
    table = GroupTable(round_id="test-round")

    # 第一次分配
    box1, res1 = table.assign(1)
    assert res1 == "OK"
    assert box1 is not None

    # 重复分配 10 次
    for _ in range(10):
        box2, res2 = table.assign(1)
        assert res2 == "OK"
        assert box2 == box1  # 必须返回同一个盒


def test_invariant_1_different_codes_different_boxes():
    """不变量 1：不同 code 分配到不同盒。"""
    table = GroupTable(round_id="test-round")

    boxes = set()
    for code in [1, 2, 3, 4, 5, 6]:
        box_id, res = table.assign(code)
        assert res == "OK"
        assert box_id not in boxes  # 每个 code 独占一个盒
        boxes.add(box_id)

    assert len(boxes) == 6  # 6 个不同的盒


# ── Invariant 2: count 只由 on_drop_ok() 增加 ────────────────────────────────

def test_invariant_2_assign_is_idempotent():
    """不变量 2：同一帧重复喂 10 次，dropped_count 不变。"""
    table = GroupTable(round_id="test-round")

    # 第一次分配
    box_id, res = table.assign(1)
    assert res == "OK"
    assert box_id is not None

    # 检查初始计数
    box = table.get_box_state(box_id)
    assert box.dropped_count == 0

    # 重复喂 10 次（模拟同一件在多帧中被识别）
    for _ in range(10):
        box_id2, res2 = table.assign(1)
        assert res2 == "OK"
        assert box_id2 == box_id

    # dropped_count 仍为 0
    box = table.get_box_state(box_id)
    assert box.dropped_count == 0


def test_invariant_2_count_only_by_on_drop_ok():
    """不变量 2：只有 on_drop_ok() 可以增加 dropped_count。"""
    table = GroupTable(round_id="test-round")

    box_id, res = table.assign(1)
    assert res == "OK"

    # 初始为 0
    box = table.get_box_state(box_id)
    assert box.dropped_count == 0

    # 调用 on_drop_ok，计数 +1
    ok = table.on_drop_ok(1)
    assert ok is True

    box = table.get_box_state(box_id)
    assert box.dropped_count == 1

    # 再调用一次
    ok = table.on_drop_ok(1)
    assert ok is True

    box = table.get_box_state(box_id)
    assert box.dropped_count == 2


# ── Invariant 3: code ∉ [1,30] 不进表 ─────────────────────────────────────────

def test_invariant_3_out_of_range_rejected():
    """不变量 3：越界 code 不进表。"""
    table = GroupTable(round_id="test-round")

    box_id, res = table.assign(0)
    assert res == "OUT_OF_RANGE"
    assert box_id is None

    box_id, res = table.assign(31)
    assert res == "OUT_OF_RANGE"
    assert box_id is None

    box_id, res = table.assign(-5)
    assert res == "OUT_OF_RANGE"
    assert box_id is None

    # 表仍为空
    assert len(table.code_to_box) == 0


# ── Invariant 4: 第 7 个 code 返回 CONTRADICTION ──────────────────────────────

def test_invariant_4_seventh_code_returns_contradiction():
    """不变量 4：第 7 个 code 返回 CONTRADICTION，不返回 REJECT。"""
    table = GroupTable(round_id="test-round")

    # 分配 6 个 code（填满所有盒）
    for i in range(1, 7):
        box_id, res = table.assign(i)
        assert res == "OK"
        assert box_id is not None

    # 第 7 个 code
    box_id, res = table.assign(7)
    assert res == "CONTRADICTION"  # 不是 REJECT
    assert box_id is None


# ── Invariant 5: count[code] > 0 后拒绝 rebind/merge ──────────────────────────

def test_invariant_5_no_rebind_after_drop():
    """不变量 5：落下后不可变。"""
    table = GroupTable(round_id="test-round")

    # 分配并落下 code=1
    box_id, res = table.assign(1)
    assert res == "OK"
    table.on_drop_ok(1)

    box = table.get_box_state(box_id)
    assert box.dropped_count == 1

    # 尝试重新分配（应该返回同一个盒，不改变绑定）
    box_id2, res2 = table.assign(1)
    assert res2 == "OK"
    assert box_id2 == box_id  # 同一个盒

    # 检查绑定未变
    assert table.code_to_box[1] == box_id


# ── 故障注入 1: code 翻转（第 7 类矛盾）──────────────────────────────────────

def test_fault_injection_code_flip():
    """故障注入 1：1 个 code 翻转 ⇒ 出现 CONTRADICTION，无混装。"""
    table = GroupTable(round_id="test-round")

    # 正常分配 6 类（1~6）
    codes = [1, 2, 3, 4, 5, 6]
    for code in codes:
        box_id, res = table.assign(code)
        assert res == "OK"
        table.on_drop_ok(code)

    # 故障：code=1 被错判成 7（翻转）
    box_id, res = table.assign(7)
    assert res == "CONTRADICTION"
    assert box_id is None

    # 检查：任何盒都没有混装
    for box in table.boxes:
        if box.bound_code is not None:
            assert box.bound_code in codes  # 只有原来的 6 个


def test_fault_injection_code_flip_allows_missing_one():
    """故障注入 1：允许少收一件（矛盾件不进表）。"""
    table = GroupTable(round_id="test-round")

    # 正常分配 6 类（填满所有盒）
    for code in [1, 2, 3, 4, 5, 6]:
        box_id, res = table.assign(code)
        assert res == "OK"
        table.on_drop_ok(code)

    # 第 7 类出现（应该是第 6 类的重复，但被错判成新类）
    box_id, res = table.assign(7)
    assert res == "CONTRADICTION"

    # 总计只收了 6 件（第 7 件因矛盾被拒，实际是少收了"真正的第 6 类重复件"）
    total = sum(b.dropped_count for b in table.boxes)
    assert total == 6


# ── 故障注入 2: 1 类消失 ────────────────────────────────────────────────────

def test_fault_injection_class_missing():
    """故障注入 2：1 类消失 ⇒ 只绑定 5 个盒。"""
    table = GroupTable(round_id="test-round")

    # 只出现 5 类（code=1 消失）
    for code in [2, 3, 4, 5, 6]:
        box_id, res = table.assign(code)
        assert res == "OK"
        table.on_drop_ok(code)

    # 检查：只绑定了 5 个盒
    bound_count = len([b for b in table.boxes if b.bound_code is not None])
    assert bound_count == 5

    # 还有 1 个空盒
    empty_count = len([b for b in table.boxes if b.bound_code is None])
    assert empty_count == 1


# ── 故障注入 3: 1 类复制（静默合并）─────────────────────────────────────────

def test_fault_injection_class_duplicate_merge_suspect():
    """故障注入 3：1 类复制 ⇒ ≤5 类但 ≥11 件 ⇒ MERGE_SUSPECT。"""
    table = GroupTable(round_id="test-round")

    # 只出现 5 个 code（code=1 和 code=2 被判成同一个 code）
    codes = [1, 2, 3, 4, 5]

    # 喂 10 件
    for i in range(10):
        code = codes[i % 5]
        table.update_seen(code)  # 更新识别计数
        box_id, res = table.assign(code)
        if res == "OK":
            table.on_drop_ok(code)

    # 第 11 件触发 MERGE_SUSPECT
    table.update_seen(1)
    box_id, res = table.assign(1)
    assert res == "MERGE_SUSPECT"
    assert box_id is None


def test_fault_injection_silent_merge_no_visible_error():
    """故障注入 3：静默合并在日志里一切正常，必须靠计数检测。"""
    table = GroupTable(round_id="test-round")

    # 6 类实际只映射到 5 个 code（code=1 被两类共享）
    # 模拟：类 A 和类 B 都被判成 code=1
    codes = [1, 1, 2, 3, 4, 5]  # 第 1、2 类都是 code=1

    # 喂前 5 件（每类 1 件）
    for i in range(5):
        code = codes[i]
        table.update_seen(code)
        box_id, res = table.assign(code)
        assert res == "OK"  # 日志正常
        table.on_drop_ok(code)

    # 喂 6 件（类 B 的第二件，code=1）
    table.update_seen(codes[1])
    box_id, res = table.assign(codes[1])
    assert res == "OK"  # 日志仍正常！

    # 继续喂到第 11 件
    for i in range(6, 11):
        code = codes[i % 6]
        table.update_seen(code)

    # 第 11 件触发检测
    table.update_seen(1)
    box_id, res = table.assign(1)
    assert res == "MERGE_SUSPECT"


# ── 故障注入 4: 1 件超容 ────────────────────────────────────────────────────

def test_fault_injection_overflow():
    """故障注入 4：1 类超过 MAX_COUNT_PER_BOX 件 ⇒ 返回 FULL。

    注：2026-10-26 用户裁决把 MAX_COUNT_PER_BOX 从 4 改成 3
        （留落料不可观测的余量）。
        本测试改用常量而不是硬编码 4，这样以后改 Cmax 不用再改测试。
    """
    table = GroupTable(round_id="test-round")
    cmax = MAX_COUNT_PER_BOX

    box_id, res = table.assign(1)
    assert res == "OK"

    # 落下 cmax 件
    for _ in range(cmax):
        ok = table.on_drop_ok(1)
        assert ok is True

    # 检查已满
    box = table.get_box_state(box_id)
    assert box.dropped_count == cmax
    assert box.state == "FULL"

    # 尝试再分配下一件 ⇒ 必须 FULL
    box_id2, res2 = table.assign(1)
    assert res2 == "FULL"
    assert box_id2 is None


def test_save_and_load():
    """保存并加载状态。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "group_table.json"

        # 创建表并分配
        table1 = GroupTable(round_id="round-001", state_file=state_file)
        box_id, res = table1.assign(1)
        assert res == "OK"
        table1.on_drop_ok(1)

        # 保存（on_drop_ok 自动触发）
        assert state_file.exists()

        # 加载
        table2 = GroupTable.load_or_create("round-001", state_file)
        assert table2.round_id == "round-001"
        assert table2.code_to_box[1] == box_id
        assert table2.get_box_state(box_id).dropped_count == 1


def test_load_or_create_round_id_mismatch():
    """round_id 不匹配 ⇒ 进只读模式（全盒 SUSPECT）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "group_table.json"

        # 创建表（round-001）
        table1 = GroupTable(round_id="round-001", state_file=state_file)
        table1.assign(1)
        table1.on_drop_ok(1)

        # 用不同 round_id 加载
        table2 = GroupTable.load_or_create("round-002", state_file)

        # 检查：所有盒都标记为 SUSPECT
        for box in table2.boxes:
            assert box.state == "SUSPECT"


def test_load_or_create_file_not_exists():
    """文件不存在 ⇒ 创建新表。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "nonexistent.json"

        table = GroupTable.load_or_create("round-001", state_file)
        assert table.round_id == "round-001"
        assert len(table.code_to_box) == 0


# ── Drop Event Tests ──────────────────────────────────────────────────────────

def test_on_drop_fail_logs_error():
    """落料失败 ⇒ 记录错误日志（不修改计数）。"""
    table = GroupTable(round_id="test-round")

    box_id, res = table.assign(1)
    assert res == "OK"

    # 落料失败
    table.on_drop_fail(1, reason="吸盘失败")

    # 检查计数未变
    box = table.get_box_state(box_id)
    assert box.dropped_count == 0


def test_on_drop_unknown_marks_suspect():
    """落料反馈不明 ⇒ 标记 SUSPECT。"""
    table = GroupTable(round_id="test-round")

    box_id, res = table.assign(1)
    assert res == "OK"

    # 落料反馈不明
    table.on_drop_unknown(1)

    # 检查盒子被标记为 SUSPECT
    box = table.get_box_state(box_id)
    assert box.state == "SUSPECT"

    # 不再进新件
    box_id2, res2 = table.assign(1)
    assert res2 == "UNPLACED"


# ── Query Tests ───────────────────────────────────────────────────────────────

def test_get_box_for_code():
    """查询 code 对应的 box_id。"""
    table = GroupTable(round_id="test-round")

    # 未绑定
    assert table.get_box_for_code(1) is None

    # 绑定后
    box_id, res = table.assign(1)
    assert res == "OK"
    assert table.get_box_for_code(1) == box_id


def test_get_box_state():
    """查询盒子状态。"""
    table = GroupTable(round_id="test-round")

    box = table.get_box_state(1)
    assert box is not None
    assert box.box_id == 1
    assert box.state == "EMPTY"

    # 越界
    assert table.get_box_state(0) is None
    assert table.get_box_state(7) is None


def test_summary():
    """表摘要。"""
    table = GroupTable(round_id="test-round")

    # 空表
    summary = table.summary()
    assert summary["bound_count"] == 0
    assert summary["total_dropped"] == 0

    # 分配并落下
    table.assign(1)
    table.on_drop_ok(1)

    summary = table.summary()
    assert summary["bound_count"] == 1
    assert summary["total_dropped"] == 1
    assert 1 in summary["bindings"].values()
