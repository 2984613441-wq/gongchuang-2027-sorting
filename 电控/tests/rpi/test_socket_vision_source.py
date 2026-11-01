"""Host-side tests for the SocketVisionSource bridge.

Verifies the MaixCAM -> Pi bridge logic without any hardware: parse the frozen
BATCH_TARGETS region, stage it fail-closed against the verified round task_id,
and pull one ItemTaskContext at a time through the Scheduler's seam.
"""

from __future__ import annotations

import pytest

from electrical_control.protocol import encode_item_task_payload
from electrical_control.rpi.socket_vision_source import SocketVisionSource


# 真实现场样本（2026-09-03 调试总结）：count=1, task_id=0, class_id=4,
# conf=90, x=94, y=284, angle=0xFF。
_SAMPLE_TASK0 = bytes.fromhex("010000045a005e011cff")
# 同一样本但 task_id=1（已验证轮次）。
_SAMPLE_TASK1 = bytes.fromhex("010001045a005e011cff")


def _make_source(task_id: int = 1) -> SocketVisionSource:
    return SocketVisionSource(
        round_id="round-1",
        task_id=task_id,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda target: (-30, 40),
    )


def test_task_id_zero_is_rejected_fail_closed():
    """Unconfigured task_id 0 (MaixCAM default) must not leak into the round."""
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK0)
    source.set_permitted(True)
    assert source.next_if_permitted() is None


def test_matching_task_id_yields_serializable_context():
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    source.set_permitted(True)
    ctx = source.next_if_permitted()
    assert ctx is not None
    assert ctx.round_id == "round-1"
    assert ctx.task_id == 1
    assert ctx.frame_seq == 1
    payload = ctx.payload
    assert payload.class_id == 4
    assert payload.image_id == 4  # image_id == class_id frozen 1:1
    assert payload.grip_angle == 0xFF
    assert payload.x_position == 100  # 占位落点
    assert payload.y_position == 200
    assert payload.pick_x_position == -30  # P3 抓取点（像素→mm 换算注入值）
    assert payload.pick_y_position == 40
    # 可序列化（grip_angle=0xFF + image_id==class_id + 抓取点非 None）
    assert len(encode_item_task_payload(payload)) == 12


def test_single_slot_latest_batch_overwrites_stale():
    """新批次覆盖未消费的旧批次；且【一帧最多只出一件】。

    2026-09-17 更新：socket_vision_source 已改为「一帧只取一件、不排队」
    （排队会让第 2 件带着第 1 件那一帧的坐标去抓，那时工件早已移位）。
    旧断言「一帧两目标 → 两次 next_if_permitted 都出货」是在排队语义下写的，已作废。
    """
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    # 两目标 batch 覆盖前一个单目标 batch（仍用 task_id=1）
    two = bytes.fromhex("020001045a005e011cff025a005f011dff")
    source.ingest(two)
    source.set_permitted(True)
    first = source.next_if_permitted()
    second = source.next_if_permitted()
    assert first is not None and first.payload.target_seq in (1, 2)
    # 一帧只取一件：整帧已在本帧消费掉，第二件必须等下一帧
    assert second is None


def test_malformed_batch_is_dropped_fail_closed():
    source = _make_source(task_id=1)
    source.ingest(b"\x02\x00\x01")  # 声明 2 目标但缺字节
    source.set_permitted(True)
    assert source.next_if_permitted() is None


def test_without_permit_returns_none():
    source = _make_source(task_id=1)
    source.ingest(_SAMPLE_TASK1)
    # 未 set_permitted(True) 前，next_if_permitted 不产出
    assert source.next_if_permitted() is None


# ---------------------------------------------------------------------------
# W15：TSP 排序（一帧多件时取"离当前位置最近"的一件）
#
# 这些用例直接构造 BatchTargets / 调用 _expand()，**绕过 wire**：BATCH_TARGETS
# 每个 target 7 字节里没有颜色字段，parse_batch_targets 造不出 box_id，
# 所以 wire 这条路径今天一件也产不出来（见文件末尾"已知红灯"）。
# ---------------------------------------------------------------------------

from electrical_control.rpi import BatchTargets, VisionTarget
from electrical_control.rpi import socket_vision_source as svs_module


def _make_source_with_anchor(
    grasp_by_seq: dict[int, tuple[int, int]],
    *,
    current_position: tuple[int, int] = (0, 0),
    task_id: int = 1,
    drop_point_for_box=lambda box_id: (100, 200),
) -> SocketVisionSource:
    return SocketVisionSource(
        round_id="round-1",
        task_id=task_id,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=drop_point_for_box,
        grasp_point_for_target=lambda target: grasp_by_seq[target.target_seq],
        current_position=current_position,
    )


def _two_target_frame() -> BatchTargets:
    """t1 = 远件（但像素上"看着最近"），t2 = 近件（像素上很远）。

    像素故意反向标注：排序若误用 pixel_x/pixel_y 就会挑错件。
    """
    return BatchTargets(
        task_id=1,
        targets=(
            VisionTarget(1, 2, pixel_x=0, pixel_y=0, box_id=1),
            VisionTarget(2, 2, pixel_x=5000, pixel_y=5000, box_id=2),
        ),
    )


def test_multi_target_picks_nearest_in_mm_not_pixel_order():
    """多件时取最近的一件：锚点在原点 → 选 t2（100 * 0.1mm）。"""
    src = _make_source_with_anchor({1: (-900, 0), 2: (100, 0)})
    ctx = src._expand(_two_target_frame())
    assert len(ctx) == 1, "一帧仍然只产出 1 件（W14 语义不动）"
    assert ctx[0].payload.target_seq == 2


def test_multi_target_order_follows_current_position_anchor():
    """换锚点 → 换选择：锚点在 (-800,0) 时 t1 更近。"""
    src = _make_source_with_anchor({1: (-900, 0), 2: (100, 0)}, current_position=(-800, 0))
    ctx = src._expand(_two_target_frame())
    assert ctx[0].payload.target_seq == 1


def test_single_target_behaviour_unchanged():
    """单件：payload、frame_seq、可序列化性必须与接入排序前逐字段一致。"""
    src = _make_source_with_anchor({1: (-30, 40)})
    frame = BatchTargets(task_id=1, targets=(VisionTarget(1, 2, box_id=1),))
    ctx = src._expand(frame)
    assert len(ctx) == 1
    assert ctx[0].frame_seq == 1
    payload = ctx[0].payload
    assert (payload.target_seq, payload.x_position, payload.y_position) == (1, 100, 200)
    assert (payload.pick_x_position, payload.pick_y_position) == (-30, 40)
    assert len(encode_item_task_payload(payload)) == 12


def test_missing_grasp_point_keeps_source_order():
    """抓取点整体未注入（W6 未落地）→ 退回原顺序，不丢件、不抛。

    注意区分两种"缺"：grasp_point_for_target 未注入 = 本用例（payload 保留但
    pick 为 None）；注入了但某件返回 None = 拒识该件（build_item_task_queue 丢弃）。
    """
    src = SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=None,
    )
    ctx = src._expand(_two_target_frame())
    assert len(ctx) == 1
    assert ctx[0].payload.target_seq == 1, "无 mm 抓取点时不猜顺序，按视觉原顺序"
    assert ctx[0].payload.pick_x_position is None


def test_sorting_failure_degrades_to_source_order(monkeypatch):
    """greedy_tsp 抛错 → 原顺序照发，链路不崩（fail-closed 退化）。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated solver failure")

    monkeypatch.setattr(svs_module, "greedy_tsp", _boom)
    src = _make_source_with_anchor({1: (-900, 0), 2: (100, 0)})
    ctx = src._expand(_two_target_frame())
    assert len(ctx) == 1
    assert ctx[0].payload.target_seq == 1


def test_all_targets_served_returns_empty_without_raising():
    """🔴 2026-09-22 现场回归：R8-073247 轮，链在第 2 件之后整体崩掉。

    现象（实测栈）::

        IndexError: tuple index out of range
          run_chain.py:1373 scheduler.next_task()
          socket_vision_source.py:223 contexts = self._expand(batch)
          socket_vision_source.py:350 payload = self._order_payloads(payloads)[0]

    真因：`_order_payloads()` 的**第一步**就是【已派发位置排除】`_drop_served()`，
    而它**合法地**会在全部排掉时返回空元组（其 docstring 原话：「全部排掉 ⇒ 返回空
    ⇒ 本轮无新件」）⇒ 旧代码无条件 `[0]` 抛 IndexError ⇒ 冒到 `run()` 兜底把整条链
    带走（退出码 1）。现场日志崩溃前一行正是
    「已派发位置排除：本帧 1 件里排掉 1 件（累计 1）；剩余可派 0 件」。

    本条钉住：本帧的件**全被排掉**时 `_expand` 返回**空列表**（不抛）。
    调用方 `next_if_permitted` 对空表已有处置 → 本帧不派件，链路继续。
    """

    src = _make_source_with_anchor({1: (-30, 40)})
    frame = BatchTargets(task_id=1, targets=(VisionTarget(1, 2, box_id=1),))

    assert len(src._expand(frame)) == 1, "第一帧正常派一件"
    # 平时这一步由 next_if_permitted 自动做（见 socket_vision_source.py:226-229）
    src.note_served(-30, 40)

    assert src._expand(frame) == [], (
        "同一位置再来 ⇒ 被【已派发位置排除】排光 ⇒ 必须返回空列表，"
        "绝不能抛 IndexError（那会把整条链带走）"
    )


def test_recv_batch_delimits_stream():
    """长连接下 recv_batch 必须按 count 首字节正确切分字节流。"""
    import socket

    from electrical_control.rpi.socket_vision_source import recv_batch

    client, server = socket.socketpair()
    try:
        # 连续两个 batch（模拟长连接连续 sendall，无消息边界）
        client.sendall(_SAMPLE_TASK1 + _SAMPLE_TASK1)
        assert recv_batch(server) == _SAMPLE_TASK1
        assert recv_batch(server) == _SAMPLE_TASK1
    finally:
        client.close()
        server.close()


# ---------------------------------------------------------------------------
# 首件稳定门（2026-09-22）：本轮第一件必须等台面看全再派
# ---------------------------------------------------------------------------

# 每个货格一个**固定**抓取点（0.1mm，滑台系）。y 越大 = 越靠 +Y 敞开侧 =
# 行扫描规则下**应当最先被夹**的那一件。box_id=4 是"晚出现的那一件"。
_GRASP_Y = {1: -500, 2: -600, 3: -700, 4: 900}


def _gate_source(*, settle: int, max_wait: float = 5.0) -> SocketVisionSource:
    """带**行扫描排序器**的源（production 的 order_by_row_scan 就是这个键）。

    必须注入排序器：默认路径是"从当前位置的贪心最近邻"（`greedy_tsp`），
    它对 (0,-500)/(0,900) 会先挑更近的 -500，那样就测不出行扫描了。
    """

    def row_scan(payloads):
        return tuple(sorted(payloads, key=lambda p: (-p.pick_y_position, p.pick_x_position)))

    return SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda t: (0, _GRASP_Y[t.box_id]),
        payload_orderer=row_scan,
        first_dispatch_settle_frames=settle,
        first_dispatch_max_wait_s=max_wait,
    )


def _batch(pieces: list[int]) -> bytes:
    """pieces=[box_id,...] → BATCH_TARGETS（每个 target 7 字节，像素值随便给）。"""
    out = bytearray([len(pieces)])
    out += (1).to_bytes(2, "big")
    for box_id in pieces:
        out += bytes([box_id, 90])
        out += (100 + box_id).to_bytes(2, "big")
        out += (100 + box_id).to_bytes(2, "big")
        out += b"\xff"
    return bytes(out)


def _pull(source: SocketVisionSource, pieces: list[int]):
    source.ingest(_batch(pieces))
    return source.next_if_permitted()


def test_first_dispatch_gate_waits_until_the_tray_is_fully_seen():
    """🔴 现场回归（2026-09-21 18:55 那轮）。

    现象：链在视觉线程起来后 **167ms** 就派了第一件，那一帧里只有部分件
    ⇒ 排序器只能在"这一帧"内比较 ⇒ **Y 最大那件被排到第三发**（现场实测
    (-28.5,-22.4) → (2.7,-70.3) → (-83.3,-15.4) → (-68.8,-87.2)）。
    排序键没错，是输入不全。

    本条同时证明**门真的有用**：同一串帧，
      · settle=0 ⇒ 第一发是 box 1（帧内 y 最大 = -500）
      · settle=3 ⇒ 前两帧不派件；等第 4 件出现并稳定后才派，且第一发是 box 4（y=+900）
    """

    # ---- 关闭门 = 旧行为：第一帧就派，派到的是"帧内 y 最大"的 box 1 ----
    off = _gate_source(settle=0)
    off.set_permitted(True)
    first_off = _pull(off, [1, 2, 3])
    assert first_off is not None
    assert first_off.payload.class_id == 1, "关掉门时应复现现场症状：先夹的不是 Y 最大那件"

    # ---- 打开门：帧不全时不派 ----
    on = _gate_source(settle=3)
    on.set_permitted(True)
    assert _pull(on, [1, 2, 3]) is None, "第 1 帧：台面未稳定，不许派"
    assert _pull(on, [1, 2, 3]) is None, "第 2 帧：仍不够"

    # 第 4 件出现 ⇒ 签名变了 ⇒ 稳定计数从头开始（这正是"等看全"的关键）
    assert _pull(on, [1, 2, 3, 4]) is None, "件集合变了 ⇒ 计数必须重来"
    assert _pull(on, [1, 2, 3, 4]) is None, "第 2 帧（4 件）"
    first_on = _pull(on, [1, 2, 3, 4])
    assert first_on is not None, "连续 3 帧稳定 ⇒ 放行"
    assert first_on.payload.class_id == 4, "看全之后，第一发必须是 Y 最大那件（box 4）"

    # ---- 派过一件之后永久放行（门只对第一件生效）----
    assert _pull(on, [2, 3]) is not None


def test_first_dispatch_gate_resets_when_positions_drift():
    """件数相同但位置漂移（> 栅格）也要重新计数 —— 否则"看起来稳定"就放行了。"""

    source = SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        # 每次调用都把 y 挪 100mm ⇒ 远超 15mm 栅格 ⇒ 签名必然翻
        grasp_point_for_target=lambda t: (0, 0),
        first_dispatch_settle_frames=2,
        first_dispatch_max_wait_s=5.0,
    )
    source.set_permitted(True)
    moves = iter([(0, 0), (0, 1000), (0, 2000)])
    source._grasp_point_for_target = lambda t: next(moves)

    assert _pull(source, [1]) is None      # streak=1
    assert _pull(source, [1]) is None      # 位置变了 ⇒ streak 回 1
    assert _pull(source, [1]) is None      # 又变 ⇒ 回 1（永不达标）


def test_first_dispatch_gate_has_a_hard_wait_cap():
    """等待上限**必须存在**：操作员还在摆件时不能让链在起轮处无限等 ——
    15s 红线是从起轮算起的，无限等比顺序错严重得多。超时应放行 + WARNING。"""
    import time as _time

    # 2026-11-01：原 0.05/0.06 只留 10ms 余量，慢机器上首次 _pull 就可能已超时
    #   ⇒ 偶发失败（并非逻辑问题）。放宽到 0.20/0.25，保留同一语义。
    source = _gate_source(settle=999, max_wait=0.20)
    source.set_permitted(True)
    assert _pull(source, [1, 2]) is None, "未超时：不派"
    _time.sleep(0.25)
    late = _pull(source, [1, 2])
    assert late is not None, "超过等待上限必须放行（否则链死在起轮处）"


def test_first_dispatch_gate_ignores_unreachable_targets():
    """没有 box_id（颜色真值缺失）或抓取点算不出来的件**不算进签名** ——
    它们本来就派不出去，算进来会让签名永远"不稳定"。"""
    source = SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda t: None,   # 未标定：一件都算不出来
        first_dispatch_settle_frames=2,
        first_dispatch_max_wait_s=5.0,
    )
    source.set_permitted(True)
    from electrical_control.rpi.vision_ingest import parse_batch_targets

    sig = source._visibility_signature(parse_batch_targets(_batch([1, 2])))
    assert sig is None, "算不出抓取点的件不算数"


# ---------------------------------------------------------------------------
# 陈旧帧护栏（2026-09-22）
#
# 机制：`set_permitted()` 只在 next_task() 拉取的那一瞬间为 True
# （electrical_control/rpi/__init__.py:204-206 拉一次就立刻置回 False），
# 而 `_latest` 在任何时刻都会被新批次覆盖 ⇒ **"最新收到的" ≠ "最新鲜的"**。
# 现场实证（round-R8-074808）：第 1 件做完、滑台已回 PARK（画面外）、台上已空，
# 链却派出一件抓取点 (-19.9,-31.3)（在托盘上方）的幻影黑圆柱 ——
# 那一帧描述的只能是【上一件运动期间、夹爪在托盘上方】的场景。
# ---------------------------------------------------------------------------


def _age_source(max_age: float) -> SocketVisionSource:
    return SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda t: (0, _GRASP_Y[t.box_id]),
        max_batch_age_s=max_age,
    )


def test_stale_batch_is_dropped_instead_of_dispatched():
    """陈旧批次必须丢弃（而不是拿去派件）—— 这是那件幻影的直接成因。"""
    src = _age_source(max_age=2.5)
    src.set_permitted(True)
    src.ingest(_batch([1]))
    src._latest_at -= 5.0  # 模拟"这一帧是 5 秒前到达的"
    assert src.next_if_permitted() is None, "陈旧帧不得派件"


def test_fresh_batch_is_dispatched_normally():
    """护栏不能误杀新鲜帧 —— 否则会把正常派件全堵死。"""
    src = _age_source(max_age=2.5)
    src.set_permitted(True)
    src.ingest(_batch([1]))
    assert src.next_if_permitted() is not None, "刚到达的帧照常派件"


def test_age_guard_can_be_disabled():
    """0 = 关闭护栏（行为与本改动前逐字节等价，便于回退对照）。"""
    src = _age_source(max_age=0.0)
    src.set_permitted(True)
    src.ingest(_batch([1]))
    src._latest_at -= 999.0
    assert src.next_if_permitted() is not None, "关闭后不判年龄"

# ---------------------------------------------------------------------------
# 2026-11-01 新增（审核报告 D1）：排序锚点改为「上一次落料点」提供器
# ---------------------------------------------------------------------------
def _source_with_provider(provider, *, grasp_by_seq, current_position=(0, 0)):
    return SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=lambda target: grasp_by_seq[target.target_seq],
        current_position=current_position,
        current_position_provider=provider,
    )


def test_anchor_provider_overrides_fixed_anchor():
    """provider 返回『上一次落料点』时，排序锚点以它为准（不是固定的 (0,0)）。"""
    src = _source_with_provider(
        lambda: (-800, 0), grasp_by_seq={1: (-900, 0), 2: (100, 0)}
    )
    ctx = src._expand(_two_target_frame())
    assert ctx[0].payload.target_seq == 1, "锚点在 (-800,0) ⇒ t1 更近"


def test_anchor_provider_none_keeps_fixed_anchor():
    """provider 返回 None（还没有落料点）⇒ 沿用构造时的固定锚点。"""
    src = _source_with_provider(
        lambda: None, grasp_by_seq={1: (-900, 0), 2: (100, 0)}
    )
    ctx = src._expand(_two_target_frame())
    assert ctx[0].payload.target_seq == 2


def test_anchor_provider_exception_degrades_to_fixed_anchor():
    """provider 抛错不能崩：退回固定锚点（本帧照发，不丢件）。"""
    def boom():
        raise RuntimeError("boom")

    src = _source_with_provider(boom, grasp_by_seq={1: (-900, 0), 2: (100, 0)})
    ctx = src._expand(_two_target_frame())
    assert ctx[0].payload.target_seq == 2

# ---------------------------------------------------------------------------
# 2026-11-01 新增（动态分配）：code 模式下由 resolver 把 code → box_id
# ---------------------------------------------------------------------------
def _source_with_resolver(resolver, *, grasp_by_seq=None, drop=None):
    if grasp_by_seq is None:
        grasp_by_seq = {1: (-30, 40), 2: (-30, 40)}
    if drop is None:
        drop = lambda box_id: (100, 200)
    return SocketVisionSource(
        round_id="round-1",
        task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=drop,
        grasp_point_for_target=lambda target: grasp_by_seq[target.target_seq],
        box_id_resolver=resolver,
    )


def _code_frame(codes):
    """code 模式帧：VisionTarget 直接带 class_id=code、box_id=None。"""
    targets = tuple(
        VisionTarget(i + 1, code, pixel_x=0, pixel_y=0, box_id=None)
        for i, code in enumerate(codes)
    )
    return BatchTargets(task_id=1, targets=targets)


def test_resolver_supplies_box_id_for_code_mode():
    """code 无 box_id 时，resolver 补上 ⇒ 该件能派发（不再被拒识）。"""
    src = _source_with_resolver(lambda code: {11: 3}.get(code))
    ctx = src._expand(_code_frame([11]))
    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 11     # class_id 仍是 code
    assert ctx[0].payload.x_position == 100  # 落点来自 box_id=3 的查表结果


def test_resolver_none_still_rejects_the_item():
    src = _source_with_resolver(lambda code: None)
    assert src._expand(_code_frame([11])) == []


def test_resolver_exception_does_not_crash():
    def boom(code):
        raise RuntimeError("boom")

    src = _source_with_resolver(boom)
    assert src._expand(_code_frame([11])) == []


def test_resolver_does_not_override_visual_box_id():
    """box_id 已有真值（box_id 模式）时，resolver 不得改写它。"""
    src = _source_with_resolver(lambda code: 6)
    frame = BatchTargets(task_id=1, targets=(
        VisionTarget(1, 3, pixel_x=0, pixel_y=0, box_id=2),
    ))
    ctx = src._expand(frame)
    assert len(ctx) == 1
    assert ctx[0].payload.class_id == 3      # class_id 不受影响
