"""路径规划：空爪平移 → 原地夹取 → **沿无壁边法线退出** → 横向搬运 → 松爪 → 空爪回位。

本模块只产生**点位与顺序**（装置坐标 mm / 滑台记账坐标），不产生任何
舵机脉宽、步数、GPIO 或串口字节。也不引入 Z 轴动作：所谓"升降"是那一个
单自由度舵机的联动效果（`ec_axis_driver.h:170-174`），由固件按固定程序驱动。

⚠️ 两个坐标系必须分清（这是本项目的一个真实坑，见交付报告矛盾清单）
------------------------------------------------------------------------
* **抓取点 / 托盘 / 退出口** 在"物料坐标"里 —— 即夹爪中心所在的物理位置。
* **滑台记账坐标** = 物料坐标 + ``tool_offset``，只有 PICK 会被整链叠加偏移：
  `pixel_to_device.py:461-470` 在 ``pixel_to_device`` 结果之后叠加 ToolOffset；
  而**落料点不叠加** —— `vision_ingest.py:226-236` 把 ``drop_point_for_box``
  的返回值直接写进 wire offset 3-6，`run_chain.py:1150-1156` 的日志也把两者
  并列打印（落点=(20.0,20.0) / 抓取点=(-24.9,-60.0)）。
  故本模块的入参 ``drop_command`` 是**滑台记账坐标**（与线上一致），
  内部先换算成物理位置再做几何判断：
      ``drop_physical = drop_command - tool_offset``
  （要让夹爪落在物理点 P，滑台目标必须是 P + tool_offset。）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from electrical_control.pick_strategy.config import StrategyConfig
from electrical_control.pick_strategy.geometry import (
    Point,
    Rect,
    Segment,
    Tray,
    segment_crosses_side,
    segment_intersects_rect,
)
from electrical_control.pick_strategy.selector import (
    Detection,
    Refusal,
    RefusalCode,
    Selection,
    VisionFrame,
)

# 步骤种类
STEP_MOVE = "move"
STEP_GRASP = "grasp"
STEP_RELEASE = "release"

# 移动段的名称
MOVE_EMPTY_TRAVEL = "empty_travel"
MOVE_EXIT = "exit"
MOVE_TRAVERSE = "traverse"
MOVE_RETURN = "return"


@dataclass(frozen=True)
class PlanStep:
    kind: str
    name: str
    start: Point          # 物料坐标（抓取点口径）
    end: Point            # 物料坐标
    carrying: bool        # True = 夹着物料（此时禁止跨越围壁/其他物料）
    note: str = ""

    def __str__(self) -> str:
        if self.kind == STEP_MOVE:
            return (f"[{self.name}] {'带料' if self.carrying else '空爪'} "
                    f"{self.start} → {self.end} ({self.length_mm:.1f}mm)")
        return f"[{self.name}] {self.kind} @ {self.end}"

    @property
    def length_mm(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def is_move(self) -> bool:
        return self.kind == STEP_MOVE


@dataclass(frozen=True)
class Command:
    """一条要下发的**滑台记账坐标**指令（不含任何硬件细节）。"""

    kind: str            # move / grasp / release
    target: Point        # 滑台记账坐标
    note: str = ""

    def __str__(self) -> str:
        return f"{self.kind} @ {self.target}"


@dataclass(frozen=True)
class PlanCheck:
    expressible_with_item_task: bool
    missing_capabilities: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PickPlan:
    selection: Selection
    steps: tuple[PlanStep, ...]
    pick: Point
    exit_point: Point
    drop_physical: Point
    home: Point                  # 初始位置，**物料坐标**（= 记账坐标 − ToolOffset）
    home_command: Point          # 初始位置，**滑台记账坐标**（配置里那个值）
    tool_offset: Point           # 本计划的坐标系换算基准（物料 → 记账）
    exit_distance_mm: float
    check: PlanCheck
    unverified_params: tuple[str, ...] = field(default=())

    @property
    def drop_command(self) -> Point:
        """落点的**滑台记账坐标**（= 线上 offset 3-6 的口径）。"""
        return self.drop_physical + self.tool_offset

    @property
    def total_travel_mm(self) -> float:
        return sum(s.length_mm for s in self.steps if s.is_move)

    def carrying_steps(self) -> tuple[PlanStep, ...]:
        return tuple(s for s in self.steps if s.is_move and s.carrying)

    def empty_steps(self) -> tuple[PlanStep, ...]:
        return tuple(s for s in self.steps if s.is_move and not s.carrying)

    def describe(self) -> str:
        lines = [f"计划：{self.selection}", f"  夹取点(物料系) {self.pick}"]
        for step in self.steps:
            lines.append(f"  {step}")
        lines.append(f"  退出口(物料系) {self.exit_point}"
                     f"  退出距离={self.exit_distance_mm:.1f}mm")
        lines.append(f"  落点：物理 {self.drop_physical} / 记账 {self.drop_command}")
        lines.append(f"  初始位置：物理 {self.home} / 记账 {self.home_command}")
        lines.append(f"  总行程={self.total_travel_mm:.1f}mm")
        lines.append("  可用现有 ITEM_TASK 表达："
                     f"{'是' if self.check.expressible_with_item_task else '否'}")
        for cap in self.check.missing_capabilities:
            lines.append(f"    · 缺：{cap}")
        for warn in self.check.warnings:
            lines.append(f"    ⚠ {warn}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
def _rect_of(det: Detection, config: StrategyConfig) -> Rect:
    """一件物料的占位矩形；缺实测尺寸时用 [Motion] max_size_mm 保守替代。"""
    half = config.half_size_of(det.box_id) or config.item_max_size
    return Rect(
        det.x_mm - half.x_mm, det.x_mm + half.x_mm,
        det.y_mm - half.y_mm, det.y_mm + half.y_mm,
    )


def _gripper_rect(at: Point, config: StrategyConfig) -> Rect:
    g = config.gripper_envelope
    return Rect(at.x_mm - g.x_mm, at.x_mm + g.x_mm,
                at.y_mm - g.y_mm, at.y_mm + g.y_mm)


def check_grasp_space(
    pick: Point,
    others: tuple[Detection, ...],
    config: StrategyConfig,
) -> Refusal | None:
    """任务要求四.5：检查夹取动作的**展开空间**。

    判据：抓取点上「夹爪完整外形」的展开矩形
      ① 不得与其它物料占位矩形相交；
      ② 不得越过托盘围壁（即必须完全落在托盘内域里）；
      ③ 不得压在已配置的障碍/缝隙矩形上。
    """
    gripper = _gripper_rect(pick, config)
    for det in others:
        if gripper.intersects_rect(_rect_of(det, config)):
            return Refusal(
                RefusalCode.GRASP_SPACE_BLOCKED,
                f"抓取点 {pick} 处夹爪展开矩形 {gripper} 与 target_seq="
                f"{det.target_seq} 的占位 {_rect_of(det, config)} 相交 —— "
                "夹取时张开空间不足。按需求三.7 不做本件",
            )
    for obs in config.obstacles:
        if gripper.intersects_rect(obs):
            return Refusal(
                RefusalCode.GRASP_SPACE_BLOCKED,
                f"夹爪展开矩形 {gripper} 压在已配置的障碍/缝隙区 {obs} 上",
            )
    violations = config.tray.wall_violations(gripper)
    if violations:
        return Refusal(
            RefusalCode.GRASP_SPACE_BLOCKED,
            f"夹爪展开矩形 {gripper} 越过托盘围壁（边 {violations}）—— "
            "无壁边不参与此项判定（伸出开口是允许的）。"
            "若围壁高度未实测，此项按 fail-closed 处理",
        )
    return None


def check_exit(
    pick: Point, tray: Tray, config: StrategyConfig
) -> tuple[Point, float] | Refusal:
    """算退出口，并确认退出方向**穿过无壁边**（而不是围壁）。

    退出距离（任务要求四.4）不能只看"夹爪中心越过托盘边缘"，必须包含：
      中心到无壁边的距离 + 夹爪/物料沿法线方向的外沿 + 定位余量。
    外沿取 ``max(夹爪外形半尺寸, 物料半尺寸)``：物料被夹在两爪之间，
    其外沿与爪片外沿取较大者即可，**相加会重复计入**。
    """
    normal = tray.outward_normal()
    axis = tray.normal_axis()
    outside_extent = max(
        config.gripper_envelope.x_mm if axis == "x" else config.gripper_envelope.y_mm,
        config.item_max_size.x_mm if axis == "x" else config.item_max_size.y_mm,
    )
    distance = tray.to_open_edge_mm(pick) + outside_extent + config.exit_clearance_mm
    exit_point = Point(
        pick.x_mm + normal.x_mm * distance,
        pick.y_mm + normal.y_mm * distance,
    )
    side = segment_crosses_side(Segment(pick, exit_point), tray)
    if side != tray.open_side:
        return Refusal(
            RefusalCode.EXIT_BLOCKED,
            f"从 {pick} 沿无壁边法线退到 {exit_point}，穿出的边是 {side!r}，"
            f"而配置的无壁边是 {tray.open_side!r} —— 退出路径会越过围壁。"
            "需求一.6/四.2 禁止越围壁",
        )
    return exit_point, distance


def _carrying_path_blocked(
    seg: Segment,
    others: tuple[Detection, ...],
    config: StrategyConfig,
    label: str,
) -> Refusal | None:
    """带料搬运段的通道检查：围壁 / 其他物料 / 障碍。"""
    axis = config.tray.normal_axis()
    perp_half = max(
        config.gripper_envelope.y_mm if axis == "x" else config.gripper_envelope.x_mm,
        config.item_max_size.y_mm if axis == "x" else config.item_max_size.x_mm,
    )
    band = seg.swept_rect(perp_half)

    if label == MOVE_TRAVERSE and segment_intersects_rect(seg, config.tray.rect):
        return Refusal(
            RefusalCode.EXIT_BLOCKED,
            f"{label} 段 {seg} 仍与托盘内域 {config.tray.rect} 相交 —— "
            "未完全退出托盘就做横向搬运，违反需求四.3",
        )
    for det in others:
        rect = _rect_of(det, config)
        if band.intersects_rect(rect):
            return Refusal(
                RefusalCode.EXIT_BLOCKED,
                f"{label} 段 {seg}（扫掠带宽 {band}）会越过 target_seq="
                f"{det.target_seq} 的占位 {rect}，违反需求一.6",
            )
    for obs in config.obstacles:
        if band.intersects_rect(obs):
            return Refusal(
                RefusalCode.EXIT_BLOCKED,
                f"{label} 段 {seg} 的扫掠带 {band} 与已配置的障碍/缝隙区 "
                f"{obs} 相交 —— 不能默认缝隙可通行（需求四.6）",
            )
    return None


def plan(
    selection: Selection,
    frame: VisionFrame,
    config: StrategyConfig,
    drop_command: Point,
) -> PickPlan | Refusal:
    """为本件生成完整计划。``drop_command`` 是**滑台记账坐标**（见模块 docstring）。"""
    if config.tray.require_gap_geometry and not config.tray.gap_known:
        return Refusal(
            RefusalCode.GAP_GEOMETRY_UNVERIFIED,
            "[Tray] gap_known=false 且 require_gap_geometry=true：托盘中间缝隙的"
            "实测几何尚未配置。需求四.6 明确不得默认缝隙可通行，故本件不做。"
            "要跑离线演示请显式把 require_gap_geometry 设为 false（演示值）",
        )

    pick = selection.detection.point
    # 初始位置在**配置里是滑台记账坐标**（固件 HOME 常量），本模块统一用物料坐标
    # 做几何，故先换算一次：物理 = 记账 − tool_offset。
    home_command = config.home
    home = home_command - config.tool_offset
    # 落点：线上给的是滑台记账坐标，化成物理位置再做几何判断。
    drop_physical = drop_command - config.tool_offset

    # ⚠️ 通道检查必须包含**所有**检测到的物体，包括没有 box_id 的那些：
    #    box_id 只是"颜色真值"，物理上挡不挡得住与颜色无关。
    #    只有"能不能被选为抓取目标"才需要 box_id（见 selector.usable_detections）。
    others = tuple(
        d for d in frame.detections if d.target_seq != selection.detection.target_seq
    )

    blocked = check_grasp_space(pick, others, config)
    if blocked is not None:
        return blocked

    exit_result = check_exit(pick, config.tray, config)
    if isinstance(exit_result, Refusal):
        return exit_result
    exit_point, exit_distance = exit_result

    normal = config.tray.outward_normal()
    axis = config.tray.normal_axis()

    # 落点是否恰好在退出法线上且比退出口更远？若是，退出即投送，不必横向搬运。
    if axis == "y":
        on_ray = abs(drop_physical.x_mm - pick.x_mm) < 1e-6
        beyond = ((drop_physical.y_mm - exit_point.y_mm) * normal.y_mm) >= -1e-6
    else:
        on_ray = abs(drop_physical.y_mm - pick.y_mm) < 1e-6
        beyond = ((drop_physical.x_mm - exit_point.x_mm) * normal.x_mm) >= -1e-6

    steps: list[PlanStep] = []
    warnings: list[str] = []

    # 1) 空爪平移（需求二：直接平移至目标上方，不先退出托盘）
    steps.append(PlanStep(
        kind=STEP_MOVE, name=MOVE_EMPTY_TRAVEL, start=home, end=pick,
        carrying=False,
        note="空爪直接定位；夹爪的开合/升降由固件程序控制，本策略不产生舵机指令",
    ))
    if config.empty_travel_may_cross_tray:
        warnings.append(
            "空爪平移假定『收缩态移动不碰托盘内物料』（需求一.4）。"
            "⚠️ 该假定与固件现状不一致：固件每件程序第 0 步先发 850us"
            "（张开=抬起，ec_axis_driver.h:67/101、ec_motion_plan.c:193），"
            "即空爪平移时夹爪是**张开抬起**态，而不是收缩态；"
            "且上一轮实测到『张开时爪片正好在物块高度、横向移动把物块推走』。"
            "见交付报告矛盾清单 C-1"
        )

    # 2) 原地夹取
    steps.append(PlanStep(
        kind=STEP_GRASP, name="grasp", start=pick, end=pick, carrying=True,
        note="闭爪(=下压)夹取；固件无夹持传感器，此项没有硬件确认信号",
    ))

    # 3) 带料沿无壁边法线退出
    exit_target = drop_physical if (on_ray and beyond) else exit_point
    steps.append(PlanStep(
        kind=STEP_MOVE, name=MOVE_EXIT, start=pick, end=exit_target,
        carrying=True,
        note="沿无壁边法线退出；退出距离已含夹爪/物料外沿与定位余量",
    ))
    blocked = _carrying_path_blocked(
        Segment(pick, exit_target), others, config, MOVE_EXIT)
    if blocked is not None:
        return blocked

    # 4) 完全出托盘后的横向搬运
    if exit_target != drop_physical:
        steps.append(PlanStep(
            kind=STEP_MOVE, name=MOVE_TRAVERSE, start=exit_target,
            end=drop_physical, carrying=True,
            note="已完全退出托盘后才横向搬运",
        ))
        blocked = _carrying_path_blocked(
            Segment(exit_target, drop_physical), others, config, MOVE_TRAVERSE)
        if blocked is not None:
            return blocked

    # 5) 松爪
    steps.append(PlanStep(
        kind=STEP_RELEASE, name="release", start=drop_physical,
        end=drop_physical, carrying=False,
        note="张开(=抬起)松爪",
    ))

    # 6) 空爪回初始位置（需求二：每件后必须回初始位置，不许停在托盘外等）
    steps.append(PlanStep(
        kind=STEP_MOVE, name=MOVE_RETURN, start=drop_physical, end=home,
        carrying=False, note="每件投放后必须回初始位置，再重新识别",
    ))

    check = _check_expressibility(
        steps=steps, drop_command=drop_command, config=config,
        on_ray=on_ray, beyond=beyond,
    )
    return PickPlan(
        selection=selection,
        steps=tuple(steps),
        pick=pick,
        exit_point=exit_target,
        drop_physical=drop_physical,
        home=home,
        home_command=home_command,
        tool_offset=config.tool_offset,
        exit_distance_mm=exit_distance,
        check=check,
        unverified_params=config.unverified_params(),
    )


def _check_expressibility(
    *,
    steps: list[PlanStep],
    drop_command: Point,
    config: StrategyConfig,
    on_ray: bool,
    beyond: bool,
) -> PlanCheck:
    """判"这份计划能否用现有 ITEM_TASK 表达"，并逐条列出缺什么。

    证据：ITEM_TASK 只有两组坐标 —— 抓取点（offset 8-11，`ec_protocol.h:156-157`）
    与落料点（offset 3-6，`:153-154`）；固件把它们编译成**固定 10 步程序**
    （`ec_motion_plan.c:193-225`），HOME 是编译期常量（`ec_motion_plan.h:193-194`），
    每个路径点的 X/Y 腿序也是编译期常量（`:201-203`）。
    """
    traversed = any(s.name == MOVE_TRAVERSE for s in steps)
    missing: list[str] = []
    warnings: list[str] = []

    single_carry_move = (not traversed) and on_ray and beyond
    if not single_carry_move:
        if traversed:
            missing.append(
                "『退出中间路径点』：现有线格式只有抓取点与落料点两个位置，"
                "没有第二段携带搬运的表达（interface-contract.md:161）"
            )
        else:
            missing.append(
                "『沿无壁边法线退出的落点』：落点不在退出法线上（或比退出口更近），"
                "现有程序会把 PICK→落点 变成一次 X 先、Y 后的折线搬运，"
                "途中可能跨越其他物料"
            )
    # 固件 HOME 的推导依据：方案乙把"上电原点"取在负方向最里角，且该角正压在
    # 可达域负端上（ec_motion_plan.h:171 "HOME = (-95.0mm, -97.5mm)"、
    # :193-194 HOME_X=-950 / HOME_Y=-975）。故在**滑台记账坐标**里
    # 固件 HOME == (workspace.x_min, workspace.y_min)。
    # 若配置里的 [Home] 被改成别的点（例如把"右上方"直接填成 (+90,+92.5)），
    # 这里就会把计划标成"表达不了" —— 这正是要拦住的情形。
    firmware_home = Point(config.workspace.x_min, config.workspace.y_min)
    if config.home != firmware_home:
        missing.append(
            f"『指定初始位置』：[Home]={config.home} 与固件编译期常量 HOME="
            f"{firmware_home}（ec_motion_plan.h:193-194）不一致；"
            "线的载荷里没有任何字段能改 HOME"
        )
    if config.tray.normal_axis() == "x":
        missing.append(
            "『按无壁边方向选择先动哪个轴』：EC_MOTION_XY_ORDER_X_FIRST 是"
            "编译期常量（ec_motion_plan.h:201-203）；无壁边为 X 侧时，"
            "策略无法要求先走 Y"
        )
    missing.append(
        "『带料/空爪状态』：线的载荷没有该位，固件按固定程序推进"
        "（ec_motion_plan.c:193-225）"
    )
    missing.append(
        "『逐步完成反馈』：STM32 只在整段 10 步程序跑完后发一次 MOTION_DONE"
        "（ec_protocol_gateway.c:71-90；ec_app.c:518-525），"
        "策略拿不到『已到取料点/已退出托盘/已松爪』的分步确认"
    )
    missing.append(
        "『总时长校验』：固件 15s 失活窗口只在 DISPLAY_ACK 时关闭"
        "（ec_app.c:218-220、:553），且进度源编译期关闭"
        "（EC_APP_PROGRESS_SOURCE_ENABLED=0，ec_app.h:16-17）→ "
        "策略侧无法校验本件程序是否会在窗口内跑完"
    )

    expressible = single_carry_move and config.home == firmware_home
    if config.tray.gap_known:
        warnings.append("已配置缝隙几何（[Obstacle]）；本计划已按不可通行区校验")
    warnings.append(
        f"落点按线上口径解释为滑台记账坐标 {_fmt(drop_command)}，"
        f"对应夹爪物理位置 {_fmt(drop_command - config.tool_offset)}"
        "（两者差一个 ToolOffset；落点不叠加偏移是现有整链的行为）"
    )
    return PlanCheck(
        expressible_with_item_task=expressible,
        missing_capabilities=tuple(missing),
        warnings=tuple(warnings),
    )


def _fmt(p: Point) -> str:
    return f"({p.x_mm:.1f},{p.y_mm:.1f})"


def to_commands(plan: PickPlan, config: StrategyConfig) -> tuple[Command, ...] | Refusal:
    """把计划化成"滑台记账坐标"指令序列，并逐点校验可达域。

    * 物料坐标点 → 记账坐标：``+ tool_offset``（与整链对 PICK 的叠加一致）。
    * 落点已经是记账坐标，**不再叠加**（否则会多补一个 ToolOffset）。
    """
    commands: list[Command] = []
    for step in plan.steps:
        if step.kind == STEP_MOVE:
            target = step.end + config.tool_offset
            if not config.workspace.contains_point(target):
                return Refusal(
                    RefusalCode.OUT_OF_REACH_WINDOW,
                    f"{step.name} 段终点换算成滑台目标 {target} 后超出可达域 "
                    f"{config.workspace}；X/Y 无限位开关，越界无硬件能发现"
                    "（ec_motion_plan.h:76-80）",
                )
            commands.append(Command("move", target, step.name))
        elif step.kind == STEP_GRASP:
            commands.append(Command("grasp", Point(0.0, 0.0),
                                    "原地闭爪(=下压)，不带坐标"))
        else:
            commands.append(Command("release", Point(0.0, 0.0),
                                    "原地松爪，不带坐标"))
    return tuple(commands)


__all__ = [
    "Command",
    "MOVE_EMPTY_TRAVEL",
    "MOVE_EXIT",
    "MOVE_RETURN",
    "MOVE_TRAVERSE",
    "PickPlan",
    "PlanCheck",
    "PlanStep",
    "STEP_GRASP",
    "STEP_MOVE",
    "STEP_RELEASE",
    "check_exit",
    "check_grasp_space",
    "plan",
    "to_commands",
]
