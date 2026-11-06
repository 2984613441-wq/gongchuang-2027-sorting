"""Live vision source bridging MaixCAM BATCH_TARGETS into the Scheduler.

A listener thread (:func:`vision_listener`) receives the frozen BATCH_TARGETS
data region over TCP and calls :meth:`SocketVisionSource.ingest`. The scheduler
then pulls :class:`ItemTaskContext` one item at a time through the same
``set_permitted()/next_if_permitted()`` protocol as ``FakeTaskSource``.

Design points (2026-09-05 bridge review; 2026-09-16 修订):
  * Single-slot "latest batch": BATCH_TARGETS is a full-scene snapshot, so a
    new batch replaces any un-consumed one (no stale FIFO, no cross-batch
    target_seq collision).
  * One item per frame: a batch is consumed whole (``_latest = None``) and yields
    at most one item. 赛规要求「货物随机全部放入托盘」，一帧里常有 N 个目标；
    若把这一帧排成 N 件队列，抓第 2 件时用的还是那一帧的坐标，而工件早已被夹爪
    碰走/移位 → 抓空。协议层的 request_id 握手只保证帧新，保证不了执行那一刻
    工件还在。
  * ``box_id`` 必须是视觉真值：BATCH_TARGETS 每个 target 7 字节里**没有**
    box_id，也没有颜色字段，class_id 只是形状（视觉侧 ``shape_id=class_id``）。
    颜色只能在视觉侧折叠成 box_id 再送上来（2026-08-27 裁决「颜色折叠进
    box_id、协议不单列颜色」）。缺 box_id 时**拒识该件**、记 WARNING、链路继续
    —— 绝不用 class_id 顶替：那等于颜色不进决策，送错盒是判负级错误。
  * batch ``task_id`` is validated against the verified round; a mismatch
    (including the unconfigured 0) is dropped fail-closed so a stale/foreign
    round can never leak items into the active round.
  * **首件稳定门**（2026-09-22 用户裁决，默认由 run_chain 打开）：
    「一帧一件」这条规定有一个副作用 —— 排序器**只能在同一帧内**比较，
    于是"本轮第一件用哪一帧"就决定了夹取顺序。实测链在视觉线程起来后 **167ms**
    就派了第一件（18:55:35,405 → :572），那一帧里件不全 ⇒ "Y 最大那件"被排到第三发。
    **排序键没错，是输入不全。**
    ⇒ 第一件必须等"台面连续 ``first_dispatch_settle_frames`` 帧签名稳定"才放行，
    并有 ``first_dispatch_max_wait_s`` 硬上限（超时按当前帧放行 + WARNING）——
    无上限时"操作员还在摆件"会让链在起轮处无限等，而 15s 红线是从起轮算起的。
    派过一件之后永久放行；**不缓存坐标**（签名只用于比较），故不违反上面那条防陈旧规定。
    ``first_dispatch_settle_frames=0`` = 关闭，行为与本改动前逐字节等价。
"""

from __future__ import annotations

from dataclasses import replace as _replace

import logging
import socket
import threading
import time
from typing import Callable

from electrical_control.protocol import ItemTaskPayload
from electrical_control.rpi import ItemTaskContext
from electrical_control.rpi.vision_ingest import (
    BatchTargets,
    GraspPointForTarget,
    build_item_task_queue,
    parse_batch_targets,
)
# 排序复用 scheduler 的贪心最近邻（纯算法模块，不反向依赖 rpi）。
# rpi -> scheduler 单向，无环；本 import 不改变 BATCH_TARGETS/ITEM_TASK 任何字节。
from electrical_control.scheduler.tsp_solver import greedy_tsp

# BATCH_TARGETS wire layout (interface-contract sec. 5.1):
#   target_count(1) + task_id(2, BE) + target[N]
# where each target is 7 bytes. The header encodes the total length, so the
# receiver self-delimits on the count byte (TCP is a byte stream, not messages).
_BATCH_HEADER_BYTES = 3
_BATCH_TARGET_BYTES = 7

_LOGGER = logging.getLogger(__name__)


def _recv_exact(conn: socket.socket, nbytes: int) -> bytes | None:
    """Receive exactly ``nbytes`` bytes, or None on EOF (peer closed)."""
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = conn.recv(nbytes - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def recv_batch(conn: socket.socket) -> bytes | None:
    """Read one self-delimiting BATCH_TARGETS region from a stream socket.

    Reads 1 count byte, then the ``2 + 7*count`` remaining bytes. Works for
    both the current per-frame short connection and a long-lived connection.
    """
    count_byte = _recv_exact(conn, 1)
    if count_byte is None:
        return None
    count = count_byte[0]
    rest = _recv_exact(conn, (_BATCH_HEADER_BYTES - 1) + count * _BATCH_TARGET_BYTES)
    if rest is None:
        return None
    return count_byte + rest


class SocketVisionSource:
    """Live, thread-safe vision source conforming to the FakeTaskSource seam."""

    def __init__(
        self,
        *,
        round_id: str,
        task_id: int,
        image_id_for_class: Callable[[int], int],
        drop_point_for_box: Callable[[int], tuple[int, int]],
        grasp_point_for_target: GraspPointForTarget | None = None,
        current_position: tuple[int, int] = (0, 0),
        # 可选：由外部注入的「选哪一件」排序器。默认 None ⇒ **逐字节等价接入前**。
        # 由 run_chain 的 --pick-strategy 注入，实现见 pick_strategy/chain_adapter.py。
        payload_orderer: Callable[[tuple[ItemTaskPayload, ...]], tuple[ItemTaskPayload, ...]]
        | None = None,
        # 可选：**首件稳定门**（2026-09-22 用户裁决「为顺序牺牲一点起轮时间」）。
        # >0 时本轮**第一件**必须等"台面被看全且连续稳定 N 帧"才放行；
        # 派过一件之后永久放行。默认 0 = 关闭（与本改动前逐字节等价；run_chain 默认传 3）。
        # 为什么需要：排序器只在**同一帧内**比较，而链在视觉线程起来后 ~167ms 就派了第一件
        # （现场 18:55:35,405 → :572），那一帧件不全 ⇒ "Y 最大那件"被排到第三发。
        # 排序键没错，是**输入不全**。
        # 2026-11-01：排序锚点提供器（返回 0.1mm 记账坐标）。
        # 传它以后，TSP 与策略排序都用『上一次落料点』而不是固定 (0,0)。
        current_position_provider: Callable[[], tuple[int, int] | None] | None = None,
        box_id_resolver: Callable[[int], int | None] | None = None,
        # 2026-11-02：主动放弃某些形状（为得分）。返回 True ⇒ 该 class_id 不派件，
        # 但**仍留在帧里**（上层几何/障碍判断不受影响）。
        class_id_filter: Callable[[int], bool] | None = None,
        first_dispatch_settle_frames: int = 0,
        # 稳定门的**等待上限（秒）**。必须有：无上限时"操作员还在摆件"会让链在起轮处
        # 无限等，而 15s 失活窗/显示红线是从起轮算起的 ⇒ 那比顺序错严重得多。
        first_dispatch_max_wait_s: float = 2.0,
        # 签名的栅格粒度（0.1mm）。150 = 15mm ≈ 件的外接尺寸量级，抖动 ±几 mm 不会翻签名。
        settle_grid_mm10: int = 150,
        # 2026-09-22：「已派发过的位置」的排除半径（0.1mm）。250 = 25mm。
        # 现场实测（round-R8-231121）：同一件被连派三次 ——
        # 抓取点 (-91.0,-56.7) / (-92.6,-60.9) / (-89.6,-58.2)（相邻差 ~4mm），
        # 而 success 已涨到 8 但台上只有 6 件 ⇒ 观感就是"在夹不存在的物体 + 顺序混乱"。
        # 成因：视觉无跨帧去重（每帧都重新报同一件），而链不排除已抓过的位置。
        # 25mm 既能吃掉抓取点抖动，又不会误排除相邻的另一个件（相邻件间距通常 >50mm）。
        # 0 = 关闭本机制（行为与本改动前逐字节等价）。
        served_radius_mm10: int = 250,
        # 🔴 2026-09-22 新增：批次**最大可接受年龄（秒）**。0 = 关闭本护栏。
        #   为什么需要（现场实证，round-R8-074808）：
        #     `set_permitted()` 只在 next_task() 拉取的那一瞬间为 True ——
        #     `electrical_control/rpi/__init__.py:204-206` 拉一次就立刻置回 False。
        #     而 `_latest` 在任何时刻都会被新批次覆盖 ⇒ **"最新收到的" ≠ "最新鲜的"**。
        #     若视觉侧有一段时间**没有再发批次**（例如夹爪离开画面后托盘空了、
        #     或它只在"有件/有变化"时才发），`_latest` 里就会一直躺着
        #     【上一件运动期间、夹爪在托盘上方】那一帧。
        #   现场后果：第 1 件做完、滑台已回 PARK（画面外）、台上已空，
        #     链却派出一件抓取点 (-19.9,-31.3)（在托盘上方）的幻影黑圆柱。
        #   ⇒ 年龄超过本值的批次**丢弃不派**（返回 None，等下一批新鲜帧）。
        #   ⚠️ 丢弃**不会吊死**：链的空闲钟会收场，代价只是本件晚一小会儿。
        #   ⚠️ 阈值不能太小，否则会把"刚在 permit 之前一刻到达"的正常帧也丢光。
        max_batch_age_s: float = 2.5,
        # 🆕 2026-11-06：**多帧类别投票**（默认关闭，保持现状）。
        # 为什么需要：主相机 6 类模型在五棱柱/正方体/长方体三类上互相误判约 5%，
        # 且 25~29% 预测落 background（误检）。根因：俯视投影下三类都是多边形，
        # cube vs cuboid 只差长宽比，penta 第五条边小件/模糊时看不出。
        # ⇒ 对同一目标维护最近 N 帧历史，class_id 至少 quorum 票才采纳。
        class_vote_enabled: bool = False,
        class_vote_frames: int = 3,         # 历史窗口大小（默认 3 帧）
        class_vote_quorum: int = 2,         # 最少票数（默认 2/3）
        class_vote_max_wait_frames: int = 6,  # 超时上限（等不到 quorum 就按不可用处理）
    ) -> None:
        self._round_id = round_id
        self._task_id = task_id
        self._image_id_for_class = image_id_for_class
        self._drop_point_for_box = drop_point_for_box
        # P3 (2026-09-16): VisionTarget -> (grasp_x, grasp_y) in 0.1mm. Unset
        # until the pixel->mm calibration is injected, in which case the payload
        # carries no grasp point and encode_item_task_payload refuses it
        # (fail-closed) - there is deliberately no (0,0) fallback.
        self._grasp_point_for_target = grasp_point_for_target
        # TSP 排序起点：0.1mm，原点 = 装置中心（protocol/item_context.py:27-28）。
        # 默认 (0,0) = 装置中心/回零位 —— 树莓派侧目前**没有**真实位姿来源
        # （STM32 只回 MOTION_DONE/ITEM_RESULT，不回坐标），所以这是唯一的
        # 可辩护锚点；谁拿到实机位姿，谁在这里注入真值（构造参数即可，
        # 不需要动 run_chain 之外的任何协议/固件）。
        # ponytail: 固定锚点；若实机每件后回零，用上一次落点当锚点更准。
        self._current_position = current_position
        self._payload_orderer = payload_orderer
        self._current_position_provider = current_position_provider
        self._box_id_resolver = box_id_resolver
        self._class_id_filter = class_id_filter
        self._permitted = False
        self._lock = threading.Lock()
        self._latest: BatchTargets | None = None
        # 🔴 2026-09-22：批次的**到达时刻**（monotonic）。用来判"陈旧帧"——
        # 见 max_batch_age_s 的说明与 next_if_permitted 的护栏。
        self._latest_at = 0.0
        self._max_batch_age_s = max(0.0, float(max_batch_age_s))
        self._frame_seq = 0
        # 首件稳定门的私有状态（全在 __init__ 里归零 ⇒ 一实例 = 一轮）。
        self._settle_frames = max(0, int(first_dispatch_settle_frames))
        self._settle_max_wait_s = max(0.0, float(first_dispatch_max_wait_s))
        self._settle_grid_mm10 = max(1, int(settle_grid_mm10))
        self._settle_sig: tuple[tuple[int, int, int], ...] | None = None
        self._settle_streak = 0
        self._settle_first_seen_at = 0.0
        self._dispatched_any = False
        # 2026-09-22：本轮【已派发过】的位置（0.1mm 装置坐标）。同一位置不再派。
        self._served_positions: list[tuple[int, int]] = []
        self._served_radius_mm10 = max(0, int(served_radius_mm10))
        self._served_skipped = 0
        # 2026-09-22：陈旧帧护栏丢弃计数（限频日志用）。
        self._stale_dropped = 0
        # 🆕 2026-11-06：多帧类别投票的私有状态。
        self._vote_enabled = bool(class_vote_enabled)
        self._vote_frames = max(1, int(class_vote_frames))
        self._vote_quorum = max(1, int(class_vote_quorum))
        self._vote_max_wait = max(1, int(class_vote_max_wait_frames))
        # 目标历史：{target_key → [(class_id, conf, pixel_coord), ...]}
        # target_key = (target_seq, 像素坐标栅格化) 或纯位置匹配
        self._vote_history: dict[tuple, list[tuple[int, int, tuple[int, int]]]] = {}
        self._vote_stats_accepted = 0
        self._vote_stats_rejected = 0
        self._vote_stats_timeout = 0

    def _is_served(self, payload: ItemTaskPayload) -> bool:
        """这个 payload 的位置是否落在某个【已派发过】的位置附近。"""
        if not self._served_positions or self._served_radius_mm10 <= 0:
            return False
        x, y = payload.pick_x_position, payload.pick_y_position
        if x is None or y is None:
            return False
        for sx, sy in self._served_positions:
            if ((x - sx) ** 2 + (y - sy) ** 2) <= (self._served_radius_mm10 ** 2):
                return True
        return False

    def _drop_served(
        self, payloads: tuple[ItemTaskPayload, ...]
    ) -> tuple[ItemTaskPayload, ...]:
        """排掉【已派发过位置】的件。全部排掉 ⇒ 返回空 ⇒ 本轮无新件（由链的空闲钟收场）。

        ⚠️ 语义与代价：按"派发过"而不是"抓成功过"排除 —— 因为链侧拿不到逐件的成功位点
        回传。代价是**一件失败了本轮不会再补抓**；换来的是"同一件被反复抓"这个更严重的
        现象消失（它会同时污染成功计数与抓取顺序）。这是刻意选择的取舍。
        """
        if not self._served_positions or self._served_radius_mm10 <= 0:
            return payloads
        kept = tuple(p for p in payloads if not self._is_served(p))
        dropped = len(payloads) - len(kept)
        if dropped:
            self._served_skipped += dropped
            # 限频：同一个原因只在第一次 + 每 20 次打一条，别把日志淹掉。
            if self._served_skipped == dropped or self._served_skipped % 20 == 0:
                _LOGGER.info(
                    "已派发位置排除：本帧 %d 件里排掉 %d 件（累计 %d）；剩余可派 %d 件",
                    len(payloads), dropped, self._served_skipped, len(kept),
                )
        return kept

    def note_served(self, x_mm10: int, y_mm10: int) -> None:
        """把刚派出去的位置记账（next_if_permitted 内部自动调用）。"""
        if self._served_radius_mm10 > 0:
            self._served_positions.append((int(x_mm10), int(y_mm10)))

    def vote_stats(self) -> dict[str, int]:
        """返回投票统计（accepted / rejected_no_quorum / timeout）。"""
        return {
            "accepted": self._vote_stats_accepted,
            "rejected_no_quorum": self._vote_stats_rejected,
            "timeout": self._vote_stats_timeout,
        }

    def set_permitted(self, permitted: bool) -> None:
        self._permitted = permitted

    def next_if_permitted(self) -> ItemTaskContext | None:
        if not self._permitted:
            return None
        with self._lock:
            batch = self._latest
            if batch is None:
                return None
            # 一帧只取一件：整帧在这里消费掉，下一件必须等下一帧。
            # 不排队（见模块 docstring "One item per frame"）：排队会让第 2 件带着
            # 第 1 件那一帧的坐标去抓，那时工件早已移位。
            self._latest = None
            # 🔴 2026-09-22：**陈旧帧护栏**（理由见构造参数 max_batch_age_s）。
            #   位置：紧跟"消费掉"之后、稳定门之前 —— 陈旧帧不该占用本件的派发机会。
            age = time.monotonic() - self._latest_at
            if self._max_batch_age_s > 0.0 and age > self._max_batch_age_s:
                self._stale_dropped += 1
                # 限频：第一次 + 每 20 次一条，别把日志淹掉（同 _drop_served 的做法）。
                if self._stale_dropped == 1 or self._stale_dropped % 20 == 0:
                    _LOGGER.warning(
                        "陈旧帧丢弃：本帧已到达 %.2fs（阈值 %.2fs）⇒ 本帧不派件、等下一批"
                        "新鲜帧（累计 %d 次）。⚠️ 若频繁出现，说明视觉侧有一段时间没发新批次",
                        age, self._max_batch_age_s, self._stale_dropped,
                    )
                return None
            # 首件稳定门（默认关闭）：本帧**不放行**时也要把帧消费掉 —— 下一帧会覆盖
            # self._latest，留着它没有意义，而且会掩盖"视觉在不在出帧"。
            if not self._first_dispatch_gate_open(batch):
                return None
            contexts = self._expand(batch)
            if contexts:
                self._dispatched_any = True
                # 2026-09-22：观测点 —— 本次派件用的帧有多新鲜（配合陈旧帧护栏一起看）。
                _LOGGER.info("本帧年龄 %.2fs ⇒ 用于本次派件", age)
                # 2026-09-22：把这一件的位置记账 ⇒ 同一位置本轮不再派（见 _drop_served）。
                _p = contexts[0].payload
                if _p.pick_x_position is not None and _p.pick_y_position is not None:
                    self.note_served(_p.pick_x_position, _p.pick_y_position)
        return contexts[0] if contexts else None

    def _filter_skipped(self, batch: BatchTargets) -> BatchTargets:
        """把「主动放弃的形状」从本帧可派发集合里剔除（2026-11-02）。

        只影响**是否派件**；不修改视觉帧本身，也不改 wire。
        被剔除的件下一帧还会出现，仍被剔除（不会重复派发，也不会报"空台面"）。
        """
        if self._class_id_filter is None:
            return batch
        kept = []
        skipped = []
        for target in batch.targets:
            try:
                drop = bool(self._class_id_filter(int(target.class_id)))
            except Exception:
                _LOGGER.warning("跳过判定抛错（class_id=%s）：按不跳过处理",
                                getattr(target, "class_id", None), exc_info=True)
                drop = False
            (skipped if drop else kept).append(target)
        if skipped:
            _LOGGER.info("主动放弃形状：本帧跳过 %d 件（target_seq=%s）",
                         len(skipped), [t.target_seq for t in skipped])
        return BatchTargets(task_id=batch.task_id, targets=tuple(kept))

    def _apply_class_vote(self, batch: BatchTargets) -> BatchTargets:
        """🆕 2026-11-06：多帧类别投票（默认关闭）。

        对同一目标维护最近 N 帧的 (class_id, conf, 像素坐标) 历史，
        class_id 至少 quorum 票才采纳；未达 quorum 时该件不产出（视为不可用）。

        目标关联：优先用 target_seq；若 target_seq 每帧变化（当前不保证唯一），
        退化为**最近位置匹配**（阈值 40mm 像素，约等于件尺寸）。

        关闭时（class_vote_enabled=False）行为与改动前逐字节等价。
        """
        if not self._vote_enabled:
            return batch

        # 位置匹配阈值（像素）：40 像素约 40mm（粗略，未精确标定）
        POS_MATCH_THRESHOLD_PX = 40

        kept_targets = []

        for target in batch.targets:
            # 1. 构造目标键：优先 target_seq，否则用位置栅格
            px, py = target.pixel_x, target.pixel_y
            grid_key = (int(px) // 50, int(py) // 50)  # 50像素栅格

            # 如果 target_seq 看起来可靠（非0且非None），用它
            if target.target_seq and target.target_seq != 0:
                target_key = ("seq", target.target_seq)
            else:
                # 退化为位置匹配：找最近的已有键
                target_key = ("pos", grid_key)
                matched_key = None
                min_dist = float('inf')
                for hist_key, hist_list in self._vote_history.items():
                    if not hist_list or hist_key[0] != "pos":
                        continue
                    last_pos = hist_list[-1][2]  # (class_id, conf, (px, py))
                    dist = ((px - last_pos[0]) ** 2 + (py - last_pos[1]) ** 2) ** 0.5
                    if dist < POS_MATCH_THRESHOLD_PX and dist < min_dist:
                        matched_key = hist_key
                        min_dist = dist
                if matched_key:
                    target_key = matched_key

            # 2. 更新历史（FIFO窗口）
            if target_key not in self._vote_history:
                self._vote_history[target_key] = []
            hist = self._vote_history[target_key]
            hist.append((int(target.class_id), int(target.confidence), (int(px), int(py))))
            if len(hist) > self._vote_frames:
                hist.pop(0)

            # 3. 投票：统计最近 N 帧内各 class_id 的票数
            votes = {}
            for cid, _, _ in hist:
                votes[cid] = votes.get(cid, 0) + 1

            # 4. 判定：至少 quorum 票才采纳
            if not votes:
                continue
            best_cid, best_count = max(votes.items(), key=lambda x: x[1])

            # 5. 超时检查：等待帧数超过 max_wait 仍未达 quorum
            if best_count >= self._vote_quorum:
                # 采纳：用投票胜出的 class_id
                kept_targets.append(_replace(target, class_id=best_cid))
                self._vote_stats_accepted += 1
            elif len(hist) >= self._vote_max_wait:
                # 超时：等不到 quorum，该件按不可用处理（不产出）
                self._vote_stats_timeout += 1
                _LOGGER.warning(
                    "类别投票超时（target_seq=%d, 位置=(%d,%d)）：等待 %d 帧仍未达 %d 票"
                    "（最高票 %d 票 class_id=%d）⇒ 本件不派",
                    target.target_seq, px, py, len(hist), self._vote_quorum,
                    best_count, best_cid,
                )
            else:
                # 未达 quorum 且未超时：该件暂不产出
                self._vote_stats_rejected += 1

        return BatchTargets(task_id=batch.task_id, targets=tuple(kept_targets))

    def _resolve_box_ids(self, batch: BatchTargets) -> BatchTargets:
        """code 模式下把 `VisionTarget.box_id`（None）补成货格号（2026-11-01 动态分配）。

        只在 box_id 为 None 时补，**绝不覆盖**视觉给出的真值；resolver 抛错 ⇒ 按无格处理
        （该件随后被 `_expand` 拒识，链路继续，不猜盒）。
        """
        if self._box_id_resolver is None:
            return batch
        patched = []
        for target in batch.targets:
            if target.box_id is None:
                try:
                    box = self._box_id_resolver(int(target.class_id))
                except Exception:
                    _LOGGER.warning(
                        "货格分配器抛错（code=%d）：该件按无格处理", target.class_id,
                        exc_info=True)
                    box = None
                if box is not None:
                    target = _replace(target, box_id=int(box))
            patched.append(target)
        return BatchTargets(task_id=batch.task_id, targets=tuple(patched))

    # ---- 首件稳定门（2026-09-22）----

    def _visibility_signature(self, batch: BatchTargets) -> tuple | None:
        """这一帧「真正能被派出去」的件集合的**量化签名**；一件都没有时返回 None。

        与 `_expand` 的口径保持一致：box_id 缺失（没有颜色真值）或抓取点算不出来的件
        **不算数** —— 它们本来就派不出去，算进来会让签名永远"不稳定"。

        用**抓取点**（= 排序器用的同一个量）而不是像素：像素受透视/安装角/高度视差影响。
        按 `settle_grid_mm10` 栅格量化 ⇒ 抖动几 mm 不会翻签名。

        ponytail: 栅格法（不是聚类）。件恰好压在栅格线上时会来回翻、多等几帧，
                  但代价只是几帧；要更稳就换成"与上一帧最近邻匹配后比最大位移"，
                  代价是 O(n²) 且要处理件数变化。
        """
        if self._grasp_point_for_target is None:
            return None
        keys = []
        batch = self._resolve_box_ids(batch)
        batch = self._apply_class_vote(batch)        # 🆕 2026-11-06：多帧类别投票
        batch = self._filter_skipped(batch)           # 2026-11-02：主动放弃形状

        for target in batch.targets:
            if target.box_id is None:
                continue
            point = self._grasp_point_for_target(target)
            if point is None:
                continue
            keys.append((
                int(target.box_id),
                int(point[0]) // self._settle_grid_mm10,
                int(point[1]) // self._settle_grid_mm10,
            ))
        return tuple(sorted(keys)) if keys else None

    def _first_dispatch_gate_open(self, batch: BatchTargets) -> bool:
        """本轮**第一件**现在能不能派。**只对第一件生效**。

        派过一件之后永久放行 —— 后续件的顺序由排序器在帧内决定，与本门无关。
        **不缓存任何坐标**：签名只用来比较，真正派件仍用当下这一帧的坐标 ⇒
        不违反 "One item per frame" 的防陈旧规定。
        """
        if self._settle_frames <= 0 or self._dispatched_any:
            return True

        signature = self._visibility_signature(batch)
        if signature is None:
            # 台面还没看到"能派出去的件" ⇒ 计数与计时都还没开始
            self._settle_sig = None
            self._settle_streak = 0
            self._settle_first_seen_at = 0.0
            return False

        now = time.monotonic()
        if self._settle_first_seen_at <= 0.0:
            self._settle_first_seen_at = now

        if signature == self._settle_sig:
            self._settle_streak += 1
        else:
            self._settle_sig = signature
            self._settle_streak = 1

        if self._settle_streak >= self._settle_frames:
            _LOGGER.info(
                "首件稳定门：台面已连续稳定 %d 帧（可见 %d 件）⇒ 放行第一件",
                self._settle_streak, len(signature),
            )
            return True

        waited = now - self._settle_first_seen_at
        if self._settle_max_wait_s > 0.0 and waited >= self._settle_max_wait_s:
            _LOGGER.warning(
                "首件稳定门**超时**（已等 %.1fs ≥ %.1fs；只稳定 %d/%d 帧，可见 %d 件）"
                "⇒ 按当前这一帧放行。⚠️ 本次夹取顺序可能不是行扫描序（台面还在变）",
                waited, self._settle_max_wait_s, self._settle_streak,
                self._settle_frames, len(signature),
            )
            return True

        _LOGGER.info(
            "首件稳定门：台面尚未稳定（%d/%d 帧，可见 %d 件）⇒ 本帧不派件",
            self._settle_streak, self._settle_frames, len(signature),
        )
        return False

    def _expand(self, batch: BatchTargets) -> list[ItemTaskContext]:
        """把一帧里【离当前位置最近的一件】可用目标映射成一个 ItemTaskContext（0 或 1 件）。

        最近 = greedy_tsp 的第一步（见 :meth:`_order_payloads`）；只有 1 件时
        与接入排序前**完全一致**（同一个 payload、同一个 frame_seq）。

        box_id 用视觉真值 (:attr:`VisionTarget.box_id`)，**不是** class_id：
        class_id 只是形状，颜色不在线上（BATCH_TARGETS 7 字节没有颜色字段），
        拿 class_id 当 box_id 就是「颜色不进决策」。

        box_id 缺失（None）= 该件没有颜色真值 → 拒识该件、记 WARNING、链路继续。
        不抛异常（抛出去会冒到 run() 兜底，把整条链带走），也绝不猜盒。
        """
        batch = self._resolve_box_ids(batch)          # 2026-11-01：code → box_id
        batch = self._apply_class_vote(batch)         # 🆕 2026-11-06：多帧类别投票
        batch = self._filter_skipped(batch)           # 2026-11-02：主动放弃形状
        for target in batch.targets:
            if target.box_id is None:
                _LOGGER.warning(
                    "box_id 缺失（class_id=%d, target_seq=%d）：拒识该件，"
                    "链路继续；不用 class_id 顶替（那是送错盒）",
                    target.class_id,
                    target.target_seq,
                )
        usable = tuple(t for t in batch.targets if t.box_id is not None)
        if not usable:
            return []
        payloads = build_item_task_queue(
            BatchTargets(task_id=batch.task_id, targets=usable),
            image_id_for_class=self._image_id_for_class,
            drop_point_for_box=self._drop_point_for_box,
            grasp_point_for_target=self._grasp_point_for_target,
        )
        if not payloads:
            # 本帧的件在落点表里都查不到（未知 box_id）→ 本帧不产出，链路继续。
            return []
        self._frame_seq += 1
        # 一帧多件时只取**离当前位置最近**的那件（= greedy_tsp 的第一步），
        # 其余顺序丢弃：下一件必须等下一帧的新坐标（W14「一帧只取一件」）。
        ordered = self._order_payloads(payloads)
        if not ordered:
            # 🔴 2026-09-22 现场回归修复（R8-073247 轮：第 2 件之后整条链退出码 1）。
            #   _order_payloads() 的**第一步**就是【已派发位置排除】(_drop_served:377)，
            #   而它**合法地**会在全部排掉时返回空元组（见其 docstring「全部排掉 ⇒ 返回空」）
            #   ⇒ 旧代码直接 [0] 抛 IndexError，冒到 run() 兜底把整条链带走。
            #   日志现场：崩溃前一行正是
            #     「已派发位置排除：本帧 1 件里排掉 1 件（累计 1）；剩余可派 0 件」。
            #   处置与上面「本帧的件在落点表里都查不到」**同款**：本帧不产出、链路继续
            #   （调用方 next_if_permitted 已按 `contexts[0] if contexts else None` 处理空表，
            #    本轮剩余时间由链的空闲钟收场）。既不 return None 也不抛异常。
            #   ⚠️ 排除本身已经把原因打进 INFO 日志了，这里不重复打，免得刷屏。
            #   ✅ 回归护栏：tests/rpi/test_socket_vision_source.py
            #      ::test_all_targets_served_returns_empty_without_raising
            #      （该用例在旧代码上复现出与现场完全相同的 :350 IndexError）
            return []
        payload = ordered[0]
        return [
            ItemTaskContext(
                round_id=self._round_id,
                task_id=self._task_id,
                frame_seq=self._frame_seq,
                payload=payload,
            )
        ]

    def _order_payloads(
        self, payloads: tuple[ItemTaskPayload, ...]
    ) -> tuple[ItemTaskPayload, ...]:
        """按贪心最近邻（TSP）排序，返回从近到远的 payload 元组。

        坐标系：只在 **0.1mm** 装置坐标里排序 —— 用 payload.pick_x/pick_y（W6
        像素→mm 换算的产物），**绝不**用 pixel_x/pixel_y：像素距离受透视、
        安装角、高度视差影响，与真实行程不成比例，按像素排序会挑中"看着近"的件。

        失败一律退回**原顺序**（= 排序接入前的行为），不丢件、不抛异常：
          * 只有 1 件 → 原顺序（**单件行为与接入前逐字节一致**）；
          * 抓取点缺失（W6 换算未注入）→ 原顺序；
          * greedy_tsp 抛错 / 字段类型不对 → 原顺序 + WARNING。
        不猜坐标、不猜顺序：排序失败最多多跑几厘米，猜错盒子才是判负级错误。
        """
        # 2026-09-22：先排掉【已派发过位置】的件（治"同一件被反复抓"）。
        # 必须排在排序【之前】：否则已抓走的那件会一直占着排序第一名。
        payloads = self._drop_served(payloads)
        if not payloads:
            return ()
        if len(payloads) < 2:
            return payloads
        # 注入的「夹取策略」排序器优先（默认 None ⇒ 跳过，行为与接入前一致）。
        # α 语义：只改顺序、不丢件；返回件数不符或抛错都**退回默认排序**。
        if self._payload_orderer is not None:
            try:
                ordered = tuple(self._payload_orderer(payloads))
                if len(ordered) == len(payloads):
                    return ordered
                _LOGGER.warning(
                    "注入的排序器返回 %d 件（输入 %d 件）：拒用，退回默认排序（不丢件）",
                    len(ordered),
                    len(payloads),
                )
            except Exception:
                _LOGGER.warning("注入的排序器抛错：退回默认排序", exc_info=True)
        if any(
            p.pick_x_position is None or p.pick_y_position is None for p in payloads
        ):
            # W6（像素→mm）未落地时每一帧都是这条路径：DEBUG 而不是 WARNING，
            # 否则每帧刷一条告警把真问题淹掉。
            _LOGGER.debug("抓取点缺失（像素→mm 未注入）：跳过 TSP 排序，按原顺序取件")
            return payloads
        # 2026-11-01（审核 D1）：锚点优先取『上一次落料点』，取不到才用构造时固定锚点。
        anchor = self._current_position
        if self._current_position_provider is not None:
            try:
                provided = self._current_position_provider()
                if provided is not None:
                    anchor = provided
            except Exception:
                _LOGGER.warning('取『上一次落料点』作排序锚点失败：沿用固定锚点', exc_info=True)
        try:
            ordered = greedy_tsp(
                list(payloads),
                anchor,
                position=lambda p: (p.pick_x_position, p.pick_y_position),
            )
        except Exception:
            _LOGGER.warning("TSP 排序失败：退回原顺序取件（本帧照发，不丢件）", exc_info=True)
            return payloads
        return tuple(ordered)

    def ingest(self, data: bytes) -> None:
        """Parse and stage one BATCH_TARGETS region (thread-safe, fail-closed).

        Malformed / out-of-contract batches are dropped whole; a batch whose
        ``task_id`` does not match the verified round is dropped as well, so a
        stale round never leaks items into the active one.
        """
        try:
            batch = parse_batch_targets(data)
        except Exception:
            # fail-closed: malformed region is dropped, never half-consumed.
            return
        if batch.task_id != self._task_id:
            # fail-closed: stale/foreign round (including unconfigured task_id 0).
            return
        with self._lock:
            self._latest = batch
            # 🔴 2026-09-22：记**到达时刻**（判陈旧帧用；见 max_batch_age_s）。
            self._latest_at = time.monotonic()


def vision_listener(
    source: SocketVisionSource,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    stop_event: threading.Event | None = None,
) -> None:
    """Blocking TCP listener: accept MaixCAM, stream BATCH_TARGETS into source.

    Run as a daemon thread. Accepts one peer at a time and reads self-delimited
    batches until the peer closes (works for both the current per-frame short
    connection and the long-lived connection).
    """
    stop = stop_event or threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    server.settimeout(1.0)
    try:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                while not stop.is_set():
                    try:
                        data = recv_batch(conn)
                    except socket.timeout:
                        # MaixCAM 推理 >1s 或暂时无数据，继续等待下一批
                        continue
                    if data is None:
                        break
                    source.ingest(data)
    finally:
        server.close()


__all__ = [
    "SocketVisionSource",
    "recv_batch",
    "vision_listener",
]
