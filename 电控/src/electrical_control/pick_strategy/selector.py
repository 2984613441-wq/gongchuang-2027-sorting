"""目标选择：每轮锁定**离托盘无壁边最近**的一件物料。

规则来源（任务要求三）
----------------------
1. 优先级 = 物料到**无壁边**的距离，**不是**到夹爪当前位置的距离。
   ⚠️ 这与现有整链的排序**相反**：`socket_vision_source.py:180-213` 用
   `greedy_tsp(payloads, self._current_position, ...)` 按"离当前位置最近"排序，
   而 `_current_position` 是构造参数，`run_chain.py:1070-1076` 没有传 →
   恒为默认锚点 `(0,0)`（`socket_vision_source.py:94,105-111`，且 :110 有
   `ponytail:` 注明是固定锚点）。本模块**不修改**那条路径（改它会动到
   已实测跑通的整链）；它只提供符合新规则的选择器，由调用方决定是否接入。
2. 用**标定后的装置坐标**（mm）比较，不用像素。
3. 优先用"靠近无壁边的**轮廓**到该边的垂直距离"；现有视觉只给中心 ⇒ 见
   :func:`select_target` 的 ``mode`` 说明与 :mod:`.geometry` 的
   :func:`contour_distance_to_open_edge` 局限。
4. 距离相同时按（空爪移动距离, target_seq）定序。
5. 每轮只锁定一件。返回初始位置后重新识别（由状态机保证，见
   :mod:`.state_machine` 的 ``WAIT_FRAME``）。
6. **最近目标不可行时不得改抓更远的件**（任务要求三.7）：本模块先按距离选出
   最近的一件，再判可行；不可行就整体拒识本件并给出原因。

排序 vs 锁定（两件事，别混）
----------------------------
* :func:`select_target` / :func:`ordering_key` = **锁定**规则：离托盘无壁边最近
  （需求三原文）。主键是 ``tray.rect.y_max − y`` 这类量，**依赖 ``[Tray] open_side``**。
* :func:`order_by_row_scan` / :func:`row_scan_key` = **抓取顺序**规则
  （2026-09-21 用户口径）：第一键 Y 从大到小、第二键同行 X 从小到大。
  2026-09-22 升级：**"同一排"由 ``[Tray] row_tolerance_mm``（【实测】17.0mm）
  按容差聚类判定**，不再是"Y 完全相等"（见 :func:`order_by_row_scan`）；
  除此之外它仍不读 ``[Tray]`` 几何/``[Home]``/``selection_mode``。
  实链（:func:`~electrical_control.pick_strategy.chain_adapter.make_payload_orderer`）
  用的是这一条。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from electrical_control.pick_strategy.config import (
    SELECTION_CENTER,
    SELECTION_CONTOUR,
    StrategyConfig,
)
from electrical_control.pick_strategy.geometry import (
    Point,
    contour_distance_to_open_edge,
)


class RefusalCode:
    """拒识原因码（字符串常量，便于日志与测试断言）。"""

    NO_USABLE_TARGET = "NO_USABLE_TARGET"
    OUT_OF_REACH_WINDOW = "OUT_OF_REACH_WINDOW"
    GRASP_SPACE_BLOCKED = "GRASP_SPACE_BLOCKED"
    EXIT_BLOCKED = "EXIT_BLOCKED"
    STALE_FRAME = "STALE_FRAME"
    CAMERA_LOST = "CAMERA_LOST"
    TIME_SYNC_UNKNOWN = "TIME_SYNC_UNKNOWN"
    GAP_GEOMETRY_UNVERIFIED = "GAP_GEOMETRY_UNVERIFIED"


@dataclass(frozen=True)
class Refusal:
    """本件**不做**的结构化原因。"""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class Detection:
    """一帧里的一件物料（装置坐标 mm，抓取点 = 夹爪中心，见 :mod:`.geometry`）。"""

    target_seq: int
    box_id: int | None
    class_id: int
    x_mm: float
    y_mm: float
    confidence: int = 0

    @property
    def point(self) -> Point:
        return Point(self.x_mm, self.y_mm)


@dataclass(frozen=True)
class VisionFrame:
    """一整帧识别结果。

    ``frame_id`` 必须单调递增（由帧来源负责）。线格式
    （``interface-contract.md:129-143``）**没有时间戳**，所以"旧画面"只能靠
    帧号单调性 + 本机接收时刻判定，无法判定相机端的拍摄时刻 —— 见
    :mod:`.state_machine` 的 ``age_s`` 语义说明。
    """

    frame_id: int
    received_at_s: float
    detections: tuple[Detection, ...]

    def __str__(self) -> str:
        return f"frame#{self.frame_id}({len(self.detections)}件)"


@dataclass(frozen=True)
class Selection:
    """被锁定的一件，以及它是怎么被选出来的（可复核）。"""

    detection: Detection
    distance_to_open_edge_mm: float
    empty_travel_mm: float
    candidate_count: int
    mode: str
    unverified_params: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        return (f"target_seq={self.detection.target_seq} "
                f"box_id={self.detection.box_id} {self.detection.point} "
                f"到无壁边={self.distance_to_open_edge_mm:.1f}mm")


def shape_of_class_id(class_id: int, class_id_mode: str = "box_id") -> int | None:
    """由 class_id 反推形状(1..6)；判不出返回 None。

    * ``box_id``（默认，历史口径）：class_id 1..6 与形状冻结 1:1；
    * ``code``（协议 V1.0）：class_id = code(1..30) ⇒ shape = (code-1)//5 + 1。
    """
    try:
        cid = int(class_id)
    except (TypeError, ValueError):
        return None
    if class_id_mode == "code":
        if 1 <= cid <= 30:
            return (cid - 1) // 5 + 1
        return None
    if 1 <= cid <= 6:
        return cid
    return None


def shape_of_detection(det: Detection, config: StrategyConfig) -> int | None:
    """由 Detection.class_id 反推形状；口径取自 ``config.class_id_mode``。"""
    try:
        cid = int(det.class_id)
    except (TypeError, ValueError):
        return None
    return shape_of_class_id(cid, getattr(config, "class_id_mode", "box_id"))


def usable_detections(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[tuple[Detection, ...], list[str]]:
    """过滤出可用于决策的件，并返回被丢弃件的原因说明。"""
    usable: list[Detection] = []
    notes: list[str] = []
    for det in frame.detections:
        if det.box_id is None:
            notes.append(
                f"target_seq={det.target_seq} 无 box_id（颜色真值缺失）→ 拒识该件"
            )
            continue
        usable.append(det)
    # 2026-11-02：主动放弃难夹形状（[Strategy] skip_shapes）。
    # ⚠️ 只从"可决策集合"里剔除；frame.detections 保持不变 ⇒ planner 仍把它们当障碍物，
    #    路径/退出检查不会因"看不见"而放行（这是刻意设计，见方案备选文档 §三.1）。
    skip = tuple(getattr(config, "skip_shapes", ()) or ())
    if skip:
        kept = []
        skipped = []
        for det in usable:
            shp = shape_of_detection(det, config)
            if shp is not None and shp in skip:
                skipped.append(det)
            else:
                kept.append(det)
        if skipped:
            notes.append(
                "主动放弃形状 %s：本帧跳过 %d 件（target_seq=%s），"
                "它们仍作为障碍物参与路径检查" % (
                    skip, len(skipped), [d.target_seq for d in skipped]))
        usable = kept
    if config.selection_mode == SELECTION_CONTOUR:
        without_size = [d for d in usable if config.half_size_of(d.box_id) is None]
        if without_size:
            seqs = [d.target_seq for d in without_size]
            notes.append(
                f"contour 模式下这些件缺 [ObjectSize] 半尺寸：{seqs} → 拒识"
            )
            usable = [d for d in usable if config.half_size_of(d.box_id) is not None]
    return tuple(usable), notes


def _distance_to_open_edge(det: Detection, config: StrategyConfig) -> float:
    """沿无壁边法线、从物料（抓取点）到该边的距离。

    ``center`` 模式 = 中心到边的距离（**近似**：真实"轮廓到边"会更近，
    差额 = 沿法线方向的一半尺寸，最坏为物料半尺寸）。
    ``contour`` 模式 = 中心距离 − 该件的包围盒半尺寸（矩形近似真轮廓）。
    """
    if config.selection_mode == SELECTION_CONTOUR:
        half = config.half_size_of(det.box_id)
        assert half is not None  # usable_detections 已保证
        return contour_distance_to_open_edge(config.tray, det.point, half)
    return config.tray.to_open_edge_mm(det.point)


def select_target(
    frame: VisionFrame, config: StrategyConfig
) -> Selection | Refusal:
    """选出本件要抓的目标，或给出拒识原因。"""
    usable, notes = usable_detections(frame, config)
    if not usable:
        detail = "本帧没有可用件（无 box_id 或缺少实测尺寸）"
        if notes:
            detail += "；" + "；".join(notes)
        return Refusal(RefusalCode.NO_USABLE_TARGET, detail)

    # 规则三.4：距离为主键；并列时用（空爪移动距离, target_seq）。
    def sort_key(det: Detection) -> tuple[float, float, int]:
        return (
            _distance_to_open_edge(det, config),
            config.home.distance_to(det.point),
            det.target_seq,
        )

    nearest = min(usable, key=sort_key)
    distance = _distance_to_open_edge(nearest, config)

    # 规则三.7（前半）：最近件本身不可达 → 拒识本件，**不改抓更远的件**。
    if not config.object_window.contains_point(nearest.point):
        commanded = nearest.point + config.tool_offset
        return Refusal(
            RefusalCode.OUT_OF_REACH_WINDOW,
            f"最近件 target_seq={nearest.target_seq} 在 {nearest.point}，"
            f"叠加 ToolOffset={config.tool_offset} 后滑台目标 {commanded} 不在"
            f"可达域 {config.workspace} 内；物料可抓窗口 "
            f"{config.object_window}。按需求三.7 **不**改为抓更远的件",
        )

    return Selection(
        detection=nearest,
        distance_to_open_edge_mm=distance,
        empty_travel_mm=config.home.distance_to(nearest.point),
        candidate_count=len(usable),
        mode=config.selection_mode,
        unverified_params=config.unverified_params(),
    )


def ordering_key(config: StrategyConfig, det: Detection) -> tuple[float, float, int]:
    """排序键的公开形式（测试用，保证与 :func:`select_target` 同源）。"""
    return (
        _distance_to_open_edge(det, config),
        config.home.distance_to(det.point),
        det.target_seq,
    )


def order_by_open_edge(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[Detection, ...]:
    """把一帧里的可用件按规则三的优先级排序（供复核/日志，不改变锁定规则）。"""
    usable, _ = usable_detections(frame, config)
    return tuple(sorted(usable, key=lambda d: ordering_key(config, d)))


def row_scan_key(det: Detection) -> tuple[float, float, int]:
    """**行扫描排内**键：Y 从大到小 → 同行 X 从小到大 → target_seq。

    用户口径（2026-09-21 确认）：从靠 Y 正方向那一排开始逐排往里；每排内从
    最靠 HOME 那件（X 最小）沿 +X 依次抓。⇒ 效果 = "从上到下、每排从左到右"。

    **"同一排"不归它管**：本键只负责**排内**次序；一件属哪一排由
    :func:`order_by_row_scan` 按 ``[Tray] row_tolerance_mm`` 分桶决定。

    **它不吃 config**：不读 ``[Tray]``、不读 ``[Home]``，也不读 ``selection_mode``。
    这正是它比 :func:`ordering_key` 稳的地方 —— 现役键的主键是
    ``tray.rect.y_max − y``，**只有** ``[Tray] open_side = y_max`` 时它才等价于
    "Y 降序"。该值已于 2026-09-21 现场【实测】确认
    （``电控/deploy/pick_strategy.ini:38``：X 轴全部被挡住、只有 Y 正方向敞开），
    所以**此刻**两者主键同序（`tests/pick_strategy/test_row_scan_order.py` 的
    ``test_row_scan_agrees_with_open_edge_when_open_side_is_y_max`` 锁死了这一点）；
    但它终归是**配置里的一行** —— 换托盘、改边界，或现场照抄仍是【待实测】的
    ``pick_strategy.demo.ini:45``，顺序都会悄悄变。行扫描把这个前提从
    "配置对不对"搬进了代码。

    ponytail（**已实施，2026-09-22**）：原先"同一行"只认 Y **完全相等**，同排各件
    Y 因识别抖动差几毫米时顺序会退化成"Y 大者先"。实机复现：肉眼同一排的两件
    （青 x=+43 / 黑 x=+95）在链自己那一帧里 y = +3.0 / −2.6（差 5.6mm）⇒ 黑先，
    而用户要青先。升级路径已落地 = **按行容差聚类分桶**（容差来自
    ``[Tray] row_tolerance_mm``，【实测】**17.0mm**：同排散布 4.3/3.8/3.4/3.4/2.9mm、
    链帧 5.6mm、帧间抖动 ≤1.4mm、排间距 ≥50mm；判别轮实测"操作员自摆同排"两件
    差 **14.7mm** ⇒ 由 15.0 上调至 **17.0**（> 14.7 盖住实测摆放；< 20 不碰"两排"最小间距），实现见
    :func:`order_by_row_scan`；``0`` = 一键退回旧口径。本键**未改**，其它调用方与
    测试仍按"排内键"用它。

    🔴 2026-09-22 更正：本键**实机值已按用户现场裁决改为 20.0**（理由：要让"正方体-圆柱-正方体
    挤在一起"的三件算同一排）⇒ 上面那句"< 20 不碰'两排'最小间距"**只对历史 17.0 成立**。
    ⚠️ 20.0 的已知代价：现场实测过相邻排只差 **17.3mm** 的一帧（round-R8-093310）⇒ 可能把真两排并排；
    且它**治不了**"同排件 y 差达 2.5cm"的摆放（≥25 更糟）。离线夹具 `pick_strategy.demo.ini`
    仍保持 17.0 ⇒ **与实机的差异是有意的**（避免夹具语料里 |30−10|=20mm 的两排被并）。
    """
    return (-det.y_mm, det.x_mm, det.target_seq)


# ─────────────────────────────────────────────────────────────────────────────
# 抓取难度分层（2026-10-26 用户裁决）
# ─────────────────────────────────────────────────────────────────────────────
#
# 用户口径（2026-10-26 现场）：
#   「我们的这个圆锥和圆柱就最后来分拣，因为俯视图这个不好拍全」
#   「圆锥和正四面体不好吸」
#
# 具体含义：
#   · **圆柱 / 圆锥**：俯视投影都是「圆」，**光靠俯视相机拍不全、判不准**
#     （真歧义，需斜置相机或 ToF 二次确认）⇒ 放到最后抓，
#     这样即使后半场时间不够，损失的是「难判的件」而不是「好判的件」。
#   · **圆锥 / 正四面体**：尖顶/斜面，**吸盘吸不住**（机械问题，软件解决不了）。
#     圆锥同时受两条影响 ⇒ 排最后。
#
# 分层表（值越小越先抓）：
#   0 = 容易：正方体 / 长方体 / 五棱柱 / 正四面体（吸盘或夹爪都能稳定抓）
#   1 = 中等：圆柱（俯视判形有歧义，但吸盘能吸）
#   2 = 最难：圆锥（判形有歧义 + 尖顶难吸）
#
# ⚠️ 前提：`class_id` 必须是**形状编号**（1=正方体 … 6=正四面体），
#    与 names.json / image_id 的编号一致。
#    🔴 若将来 wire 上仍是「颜色→货格」的旧 bin_id，本表会错位 ——
#    届时必须先把视觉输出改成形状编号（见协议 1 字节打包方案）。
PICK_TIER_BY_CLASS_ID: Mapping[int, int] = {
    1: 0,   # 正方体 cube
    2: 0,   # 长方体 cuboid
    3: 1,   # 圆柱 cylinder      ← 俯视判形有歧义
    4: 0,   # 五棱柱 pentagonal_prism
    5: 2,   # 圆锥 cone          ← 判形有歧义 + 尖顶难吸
    6: 0,   # 正四面体 tetrahedron
}

#: 未登记的 class_id 当作最容易（保守：先抓，避免被永远跳过）
PICK_TIER_DEFAULT: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# 「待定」机制（2026-10-26 用户裁决）
# ─────────────────────────────────────────────────────────────────────────────
#
# 用户原话：「难的件是指判别不清的，越到后面越好判别」「建议加，那就加待定」
#
# 为什么"越到后面越好判别"：托盘上件多时互相遮挡、边缘贴在一起，
# 视觉判形容易错；抓走一些后托盘变稀疏，同样的件就判得准了。
#
# 🔴 关键设计选择：**低置信度件不丢弃，只排到最后**。
#   如果直接丢弃，会出现两种坏情况：
#     ① 全部件都低置信度 ⇒ 一件都发不出去 ⇒ 链路空转（死锁）
#     ② 某件一直判不准 ⇒ 永远不抓 ⇒ 留在托盘上丢分
#   排到最后则：前面好判的先抓，托盘稀疏后该件的置信度自然上升，
#   到那时再抓就准了；即使一直不上升，最后也会被抓走（不是永远不抓）。
#
# 实现方式：在排序键最前面加一位 `pending`（0 = 已确定，1 = 待定），
# 这样**所有待定件都排在所有已确定件之后**，而待定件内部仍按原规则排。

#: 置信度（0~100）低于此值 ⇒ 判为「待定」。
#: 取 50 的理由：MaixCAM 侧 HSV 命中率/ YOLO 置信度都归一化到 0~100，
#: 50 大致对应"一半证据"，低于它时形状判定的错误率明显升高。
#: ⚠️ 这是初始值，需要现场用真实托盘标定：若发现"待定"太多导致
#:    最后扎堆抓不完 ⇒ 调低；若误判太多 ⇒ 调高。
DEFER_CONFIDENCE_BELOW: int = 50


def is_pending(det: Detection) -> bool:
    """这件是否「待定」（置信度不足以确定形状/颜色）。

    Returns:
        True = 待定（应排到后面，等托盘稀疏了再判/再抓）
        False = 已确定
    """
    return det.confidence < DEFER_CONFIDENCE_BELOW


def difficulty_tier_of(det: Detection) -> int:
    """这件物料的抓取难度层（0 最容易 / 1 中等 / 2 最难）。

    未登记的 class_id 返回 :data:`PICK_TIER_DEFAULT`（= 0，按容易处理）。
    理由：宁可先抓一件"难度未知"的，也不要让它因为排不上而永远被留在托盘上。

    ⚠️ 本函数**不含**「待定」判定 —— 待定是排序时的独立一位，
    见 :func:`difficulty_scan_key` / :func:`group_then_scan_key`。
    """
    return PICK_TIER_BY_CLASS_ID.get(det.class_id, PICK_TIER_DEFAULT)


def difficulty_scan_key(det: Detection) -> tuple[int, int, float, float, int]:
    """**待定 → 难度分层 → 行扫描**键。

    与 :func:`row_scan_key` 的差别在最前面多了两级：
      · ``pending``（0 = 已确定，1 = 待定）—— **待定件整体排到最后**
      · ``tier``（难度层）
    当全部件都已确定且同属一层时，它的后半段与 ``row_scan_key`` 完全一致。
    """
    return (
        1 if is_pending(det) else 0,
        difficulty_tier_of(det),
        -det.y_mm,
        det.x_mm,
        det.target_seq,
    )


def order_by_difficulty_scan(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[Detection, ...]:
    """把一帧里的**可用件**按「难度分层 → 行扫描」排序（实链接入用）。

    与 :func:`order_by_row_scan` 唯一的区别：**先按难度层分组**，
    每层内部再走原来的行扫描（含 ``[Tray] row_tolerance_mm`` 分桶）。

    效果：好抓的先抓（正方体/长方体/五棱柱/正四面体）
          → 再抓圆柱 → 最后抓圆锥。
    这样即使后半场超时，留在托盘上的是**难判/难吸的件**，不是好抓的件。

    **一键回退开关**：把 :data:`PICK_TIER_BY_CLASS_ID` 清空（或全部置 0）
    ⇒ 退化成与 :func:`order_by_row_scan` 完全相同的顺序。
    本函数**只改顺序、不拒识**（与 :func:`order_by_row_scan` 同）。
    """
    usable, _ = usable_detections(frame, config)
    tol = config.tray.row_tolerance_mm

    # 先按 (pending, tier) 两级分组：
    #   pending=1（待定）整体排在 pending=0（已确定）之后
    by_tier: dict[tuple[int, int], list[Detection]] = {}
    for det in usable:
        key = (1 if is_pending(det) else 0, difficulty_tier_of(det))
        by_tier.setdefault(key, []).append(det)

    out: list[Detection] = []
    for _pending, _tier in sorted(by_tier):
        group = by_tier[(_pending, _tier)]
        if tol <= 0.0:
            # 行容差关闭 ⇒ 退化成逐件行扫描键
            out.extend(sorted(group, key=row_scan_key))
        else:
            # 与 order_by_row_scan 同一套分桶逻辑，只是喂进去的是"同层子集"
            out.extend(
                det
                for _anchor_y, row in _rows_by_y_tolerance(group, tol)
                for det in sorted(row, key=lambda d: (d.x_mm, d.target_seq))
            )
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────────────
# 「先一类再一类」+ 难度分层（2026-10-26 用户裁决，第二版）
# ─────────────────────────────────────────────────────────────────────────────
#
# 用户口径（2026-10-26 追加）：
#   「我们的夹取策略改成哪个简单哪个来，然后的话在合适的时机 yolo 判别
#     再找简单的，最后判别最难的，在其他的弄完了之后和我们的先一类再一类结合」
#
# 解读成三级优先：
#   ① **难度层**（tier）：容易的先抓 —— 保证后半场超时损失的是难件
#   ② **类别**（class_id）：同一层内**做完一类再做下一类** —— 减少来回换箱
#   ③ **行扫描**：同一类内仍按"从上到下、每排从左到右"
#
# 为什么要"先一类再一类"：
#   每个 (颜色,形状) 组只进一个货格。若在组之间来回跳，机械臂每次都要
#   走一趟不同落点、且组表状态频繁切换；做完一类再换下一类，落点更集中。
#
# ⚠️ 已知代价（用户需知）：同一类的件若散布在托盘两侧，会来回横穿，
#   总行程可能比纯行扫描更长。若实测发现"总时间变长"，把本函数换回
#   :func:`order_by_difficulty_scan`（只分层、不分类）即可。


def group_then_scan_key(det: Detection) -> tuple[int, int, int, float, float, int]:
    """「待定 → 难度 → 类别 → 行扫描」四级排序键。

    返回 ``(pending, tier, class_id, -y_mm, x_mm, target_seq)``：
      · pending 升序（0 = 已确定先，1 = 待定排最后）
      · tier 升序（容易的先）
      · class_id 升序（做完一类再下一类）
      · -y 降序（靠 +Y 那排先）
      · x 升序（同排从左到右）
      · target_seq 升序（兜底稳定）
    """
    return (
        1 if is_pending(det) else 0,
        difficulty_tier_of(det),
        det.class_id,
        -det.y_mm,
        det.x_mm,
        det.target_seq,
    )


def order_by_group_scan(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[Detection, ...]:
    """把一帧里的**可用件**按「难度 → 类别 → 行扫描」排序（实链接入用）。

    这是 :func:`order_by_difficulty_scan` 的加强版：多了一级 ``class_id``，
    实现用户要求的「先一类再一类」。

    行为：
      1. 先按难度层分组（tier 0 → 1 → 2）
      2. 每层内按 ``class_id`` 升序分组（== 一类做完再做下一类）
      3. 每个类内按行扫描（含 ``[Tray] row_tolerance_mm`` 分桶）

    **本函数只改顺序、不拒识**（与另外两个排序器一致）。

    **一键回退**：
      · 想只分层不分类 ⇒ 换回 :func:`order_by_difficulty_scan`
      · 想完全回旧行为 ⇒ 换回 :func:`order_by_row_scan`
    """
    usable, _ = usable_detections(frame, config)
    tol = config.tray.row_tolerance_mm

    # 先按 (pending, tier, class_id) 三级分组
    #   pending=1（待定）整体排在 pending=0（已确定）之后
    by_group: dict[tuple[int, int, int], list[Detection]] = {}
    for det in usable:
        key = (1 if is_pending(det) else 0, difficulty_tier_of(det), det.class_id)
        by_group.setdefault(key, []).append(det)

    out: list[Detection] = []
    for _pending, _tier, _class_id in sorted(by_group):
        group = by_group[(_pending, _tier, _class_id)]
        if tol <= 0.0:
            out.extend(sorted(group, key=row_scan_key))
        else:
            out.extend(
                det
                for _anchor_y, row in _rows_by_y_tolerance(group, tol)
                for det in sorted(row, key=lambda d: (d.x_mm, d.target_seq))
            )
    return tuple(out)


def _rows_by_y_tolerance(
    dets: Sequence[Detection], tol_mm: float
) -> list[tuple[float, list[Detection]]]:
    """按 y 容差把件聚成"排"：返回 ``[(锚点y, [件...]), ...]``（锚点 y 降序）。

    **聚类，不是量化**：y 从大到小遍历，与"当前排的锚点 y"（= 该排第一件、也是
    该排最高那件）相差 ≤ ``tol_mm`` 的并入该排，否则新起一排。
    不用 ``floor(y / tol)`` —— 量化会在桶边界上把相差 1mm 的两件拆成两排。
    每件都与**锚点**比（不是与上一件比）⇒ 排内散布不会沿链累积（"排"不会越滚越大）。
    """
    rows: list[tuple[float, list[Detection]]] = []
    for det in sorted(dets, key=lambda d: -d.y_mm):
        if rows and rows[-1][0] - det.y_mm <= tol_mm:
            rows[-1][1].append(det)
        else:
            rows.append((det.y_mm, [det]))
    return rows


def order_by_row_scan(
    frame: VisionFrame, config: StrategyConfig
) -> tuple[Detection, ...]:
    """把一帧里的**可用件**按行扫描排序（实链接入用）。

    签名与 :func:`order_by_open_edge` 相同，便于在 ``chain_adapter.py`` 里原地替换；
    ``config`` 用于 :func:`usable_detections` 的可用性过滤（无 box_id、contour 模式
    缺半尺寸的件不参与排序）与 ``[Tray] row_tolerance_mm`` 分桶，**不参与排内键**。
    与 :func:`order_by_open_edge` 一样，它**只改顺序、不拒识**。

    规则：排间按**锚点 y 降序**（最靠 +Y 那排先）→ 排内按 ``(x_mm, target_seq)``
    升序（同排先抓最靠 −X 那件）。
    **一键回退开关**：``[Tray] row_tolerance_mm = 0``（或负值，但配置会拦负值）⇒
    完全退回旧行为 = 逐件 ``sorted(usable, key=row_scan_key)``，即"同一排"只认
    Y 完全相等。
    """
    usable, _ = usable_detections(frame, config)
    tol = config.tray.row_tolerance_mm
    if tol <= 0.0:
        return tuple(sorted(usable, key=row_scan_key))
    return tuple(
        det
        for _anchor_y, row in _rows_by_y_tolerance(usable, tol)
        for det in sorted(row, key=lambda d: (d.x_mm, d.target_seq))
    )


def describe_selection_limitation(mode: str) -> str:
    """把当前选择模式的局限写清楚（写进日志，避免"看起来精确"的假象）。"""
    if mode == SELECTION_CONTOUR:
        return (
            "selection_mode=contour：用[ObjectSize]的轴对齐包围盒近似轮廓距离。"
            "现有视觉线格式只给中心像素、不给宽高或轮廓点，故半尺寸必须是"
            "实测值；对圆柱/三棱柱/四棱锥，矩形近似会低估或高估真实轮廓距离"
            "（误差 = 外形与轴对齐矩形之差，需按实测外形评估）"
        )
    return (
        "selection_mode=center：只有中心坐标可用 ⇒ 用的是**中心**到无壁边的"
        "距离，不是轮廓距离。它与真实轮廓距离相差'沿法线方向的一半尺寸'"
        "（对 ≤40mm 的件最坏约 20mm）。要改成真正的轮廓距离，需要视觉侧"
        "补发 bbox 宽高（或轮廓点），见交付报告§视觉接口局限"
    )


__all__ = [
    "DEFER_CONFIDENCE_BELOW",
    "Detection",
    "PICK_TIER_BY_CLASS_ID",
    "PICK_TIER_DEFAULT",
    "Refusal",
    "RefusalCode",
    "Selection",
    "VisionFrame",
    "describe_selection_limitation",
    "difficulty_scan_key",
    "difficulty_tier_of",
    "group_then_scan_key",
    "is_pending",
    "order_by_difficulty_scan",
    "order_by_group_scan",
    "order_by_open_edge",
    "order_by_row_scan",
    "ordering_key",
    "row_scan_key",
    "select_target",
    "usable_detections",
]
