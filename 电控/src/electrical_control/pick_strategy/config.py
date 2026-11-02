"""夹取策略配置加载 —— 带"参数来源"强制标注。

设计要点
--------
1. **每个 `key = value` 行必须带来源标签**，标签写在行内注释里，取值只能是
   ``【实测】`` / ``【固件常量】`` / ``【演示】`` / ``【待实测】`` 之一。
   缺标签或标签非法 → ``ConfigError``（fail-closed）。
   依据：任务要求五.4「不得将照片估算值或演示值当成实机参数」。靠人工自觉
   遵守不如靠加载器强制；同时策略产出的计划会把所有用到的【待实测】项列出来。

2. **不用 ``configparser``**：它按行内注释前缀把 ``# 【实测】...`` 整段剥掉，
   而标签**就在注释里**。所以这里做一次极小的逐行解析（只认 ``[节]`` 与
   ``键 = 值 # 【标签】``），比"configparser 读值 + 正则再扫一遍"少一遍 IO。

3. 本模块**不解释**任何数值语义（量纲、范围、几何含义都在调用方）。
   它只做：解析、来源标注、取值类型转换、未知节/未知键告警。

不做什么
--------
* 不读串口、不连相机、不碰任何硬件。
* 不复制固件的舵机脉宽 / 步数比 / HOME 常量（避免出现第二权威）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

# 允许的来源标签（顺序即"可信度"从高到低，仅用于展示）
TAG_MEASURED = "实测"
TAG_FIRMWARE = "固件常量"
TAG_DEMO = "演示"
TAG_UNMEASURED = "待实测"
KNOWN_TAGS = (TAG_MEASURED, TAG_FIRMWARE, TAG_DEMO, TAG_UNMEASURED)

_TAG_PATTERN = re.compile(r"#\s*【([^】]*)】")
_KV_PATTERN = re.compile(r"^([^=]+?)\s*=\s*(.*?)\s*$")
_SECTION_PATTERN = re.compile(r"^\[([^\]]+)\]\s*$")


class ConfigError(Exception):
    """配置不合规（缺标签、标签非法、节/键缺失、值不可解析）。"""


@dataclass(frozen=True)
class RawParam:
    section: str
    key: str
    value: str
    tag: str
    line_no: int

    @property
    def qualified(self) -> str:
        return f"[{self.section}] {self.key}"


class RawConfig:
    """逐行解析结果：``{(节, 键): RawParam}`` + 原始顺序。"""

    def __init__(self, params: Mapping[tuple[str, str], RawParam], path: Path):
        self._params = dict(params)
        self.path = path

    @classmethod
    def load(cls, path: str | Path) -> "RawConfig":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"配置文件不存在：{p}")
        text = p.read_text(encoding="utf-8")
        params: dict[tuple[str, str], RawParam] = {}
        section = ""
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            m_section = _SECTION_PATTERN.match(line)
            if m_section:
                section = m_section.group(1).strip()
                continue
            if not section:
                raise ConfigError(
                    f"{p}:{line_no} 在第一个 [节] 之前出现内容：{line!r}"
                )
            m_kv = _KV_PATTERN.match(line)
            if not m_kv:
                raise ConfigError(f"{p}:{line_no} 不是 `键 = 值` 形式：{line!r}")
            key = m_kv.group(1).strip()
            rest = m_kv.group(2)
            m_tag = _TAG_PATTERN.search(rest)
            if m_tag is None:
                raise ConfigError(
                    f"{p}:{line_no} `{section}.{key}` 缺来源标签。"
                    f"每行必须带 # 【{'/'.join(KNOWN_TAGS)}】 之一。"
                    "来源不明 = 不得用于实机（任务要求五.4）"
                )
            tag = m_tag.group(1).strip()
            if tag not in KNOWN_TAGS:
                raise ConfigError(
                    f"{p}:{line_no} `{section}.{key}` 的来源标签 【{tag}】 非法，"
                    f"只能是 {'/'.join(KNOWN_TAGS)}"
                )
            value = rest[: m_tag.start()].strip()
            if not value:
                raise ConfigError(f"{p}:{line_no} `{section}.{key}` 值为空")
            params[(section, key)] = RawParam(section, key, value, tag, line_no)

        if not params:
            raise ConfigError(f"{p} 里没有任何 `键 = 值` 行")
        return cls(params, p)

    # ---- 读取原语（节/键缺失一律抛，不做默认值兜底）----
    def param(self, section: str, key: str) -> RawParam:
        try:
            return self._params[(section, key)]
        except KeyError:
            known = sorted(k for (s, k) in self._params if s == section)
            raise ConfigError(
                f"缺参数 [{section}] {key}（该节现有键：{known or '节不存在'}）"
            ) from None

    def opt(self, section: str, key: str) -> RawParam | None:
        return self._params.get((section, key))

    def section_items(self, section: str) -> list[RawParam]:
        return [p for p in self._params.values() if p.section == section]

    def has_section(self, section: str) -> bool:
        return any(s == section for (s, _) in self._params)

    def all_params(self) -> list[RawParam]:
        return list(self._params.values())

    def unverified(self) -> list[RawParam]:
        return [p for p in self._params.values() if p.tag == TAG_UNMEASURED]


# ---------------------------------------------------------------------------
# 数值读取助手
# ---------------------------------------------------------------------------
def _as_float(param: RawParam) -> float:
    try:
        return float(param.value)
    except ValueError:
        raise ConfigError(
            f"{param.qualified}={param.value!r} 不是数字（第 {param.line_no} 行）"
        ) from None


def as_float(raw: RawConfig, section: str, key: str) -> float:
    return _as_float(raw.param(section, key))


def as_float_pair(raw: RawConfig, key: str, section: str) -> tuple[float, float]:
    param = raw.param(section, key)
    parts = [p.strip() for p in param.value.replace("，", ",").split(",")]
    if len(parts) != 2:
        raise ConfigError(
            f"{param.qualified}={param.value!r} 不是 `a, b` 两数形式"
        )
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        raise ConfigError(
            f"{param.qualified}={param.value!r} 含非数字项"
        ) from None


def as_bool(raw: RawConfig, section: str, key: str) -> bool:
    param = raw.param(section, key)
    low = param.value.strip().lower()
    if low in ("true", "1", "yes", "on"):
        return True
    if low in ("false", "0", "no", "off"):
        return False
    raise ConfigError(f"{param.qualified}={param.value!r} 不是布尔值")


def as_str(raw: RawConfig, section: str, key: str) -> str:
    return raw.param(section, key).value


def format_provenance(raw: RawConfig) -> list[str]:
    """人类可读的来源清单（每行一条），供入口打印。"""
    out = []
    for p in raw.all_params():
        out.append(f"  [{p.tag}] [{p.section}] {p.key} = {p.value}")
    return out


def unverified_names(raw: RawConfig) -> tuple[str, ...]:
    return tuple(p.qualified for p in raw.unverified())


def split_sections(raw: RawConfig) -> Iterable[str]:
    seen: list[str] = []
    for p in raw.all_params():
        if p.section not in seen:
            seen.append(p.section)
    return tuple(seen)


# ---------------------------------------------------------------------------
# 强类型配置（全部字段来自 ini，绝不内置"魔法默认值"）
# ---------------------------------------------------------------------------
from electrical_control.pick_strategy.geometry import (  # noqa: E402
    OPEN_SIDES,
    Point,
    Rect,
    Tray,
)

SELECTION_CENTER = "center"
SELECTION_CONTOUR = "contour"
KNOWN_SELECTION_MODES = (SELECTION_CENTER, SELECTION_CONTOUR)


@dataclass(frozen=True)
class StrategyConfig:
    """策略运行所需的全部参数（均已标注来源）。"""

    workspace: Rect
    home: Point
    tray: Tray
    tool_offset: Point
    gripper_envelope: Point          # 夹爪完整外形半尺寸（含爪指全张）
    item_max_size: Point             # 物料最大半尺寸（用于他件占位与保守估计）
    exit_clearance_mm: float
    step_timeout_s: float
    step_duration_s: float           # 【演示】模拟执行器每步耗时
    assume_grasp_without_fault: bool
    retain_grasp_on_fault: bool
    selection_mode: str
    stale_frame_timeout_s: float
    empty_confirmation_frames: int
    empty_travel_may_cross_tray: bool
    object_sizes: dict[int, Point]   # box_id -> 半尺寸；contour 模式必需
    obstacles: tuple[Rect, ...]
    raw: RawConfig
    # 2026-11-01 新增（可选 [Strategy] 节）：五键排序参数；缺节时用下列默认值。
    order_mode: str = "legacy"
    settle_frames: int = 3
    settle_shift_mm: float = 4.0
    isolation_band_mm: float | None = None
    # 2026-11-02 新增（可选 [Strategy]）：为得分主动放弃难夹的形状。
    # 例：skip_shapes = 3,5 ⇒ 圆柱(3)/圆锥(5) 不派件（但**仍留在几何里当障碍**，见 planner）。
    # class_id_mode：class_id 的取值口径，决定怎么由 class_id 反推 shape。
    #   box_id（默认，现状）：class_id 1..6 与形状冻结 1:1（历史口径）
    #   code            ：class_id = code(1..30) ⇒ shape = (code-1)//5 + 1
    skip_shapes: tuple[int, ...] = ()
    class_id_mode: str = "box_id"
    # 2026-11-02 新增（可选 [Strategy]）：加权排序权重（前端/夹取/路线/隔离度）。
    # 用户口径：主相机前端最先 → 前端内部置信度高的先 → 同时考虑路线。
    # 全部 >= 0 且总和 > 0；缺省体现「前端 > 好夹 > 路线 > 隔离度」。
    weight_front: float = 0.70
    weight_pick: float = 0.15
    weight_route: float = 0.10
    weight_isolation: float = 0.05
    # 2026-11-02 测评结论：难件（tier>=1）不得排首位（否则与「先易后难」冲突，
    # 仿真实测难件首位率 10.33% → 0%）。默认开，可关。
    weighted_guard_hard_first: bool = True

    # ---- 由其它参数推出的量，不是配置项（避免同一事实有两处来源）----
    @property
    def object_window(self) -> Rect:
        """物料（=抓取点）必须落在这个窗口内，滑台目标才在可达域里。

        推导：下发目标 = 物料坐标 + tool_offset（`pixel_to_device.py:468-470`），
        而固件要求下发目标落在可达域（`ec_motion_plan.h:126-127` 的非对称域）。
        故 物料 ∈ 可达域 − tool_offset。
        ⚠️ 2026-09-22：本量的数值**随 tool_offset 走**，引用它当"实测值"时必须把
        tool_offset 的值一起引。当前实机值 tool_offset=(−108.5,−20.5)、
        可达域 X[−95,+90]/Y[−97.5,+92.5] ⇒ X[13.5,198.5] / Y[−77.0,113.0]。
        （旧记 `docs/交付/2026-09-19/标定与工具偏置-最终状态-2026-09-19.md:73`
        的 X[25.5,210.5] / Y[−54.0,136.0] 是用**已过期**的 (−120.5,−43.5) 推的。）
        ⚠️ 本窗口与 `det.point` 同平移 ⇒ 本包内所有比较（如 `selector.py:187`
        的可达性判定）对 tool_offset 的取值**不变**。"""
        o, w = self.tool_offset, self.workspace
        return Rect(
            x_min=w.x_min - o.x_mm,
            x_max=w.x_max - o.x_mm,
            y_min=w.y_min - o.y_mm,
            y_max=w.y_max - o.y_mm,
        )

    def half_size_of(self, box_id: int | None) -> Point | None:
        if box_id is None:
            return None
        return self.object_sizes.get(box_id)

    def unverified_params(self) -> tuple[str, ...]:
        return unverified_names(self.raw)

    def provenance_lines(self) -> list[str]:
        return format_provenance(self.raw)


def _positive(value: float, name: str) -> float:
    if not (value > 0.0):
        raise ConfigError(f"{name}={value} 必须为正数")
    return value


def build_config(path: str | Path) -> StrategyConfig:
    """从 ini 构建强类型配置。任何缺失/非法一律 ``ConfigError``。"""
    raw = RawConfig.load(path)

    ws = Rect(
        x_min=as_float(raw, "Workspace", "x_min"),
        x_max=as_float(raw, "Workspace", "x_max"),
        y_min=as_float(raw, "Workspace", "y_min"),
        y_max=as_float(raw, "Workspace", "y_max"),
    )
    home = Point(
        as_float(raw, "Home", "x_mm"),
        as_float(raw, "Home", "y_mm"),
    )
    tray = Tray(
        rect=Rect(
            x_min=as_float(raw, "Tray", "x_min"),
            x_max=as_float(raw, "Tray", "x_max"),
            y_min=as_float(raw, "Tray", "y_min"),
            y_max=as_float(raw, "Tray", "y_max"),
        ),
        open_side=as_str(raw, "Tray", "open_side").strip(),
        gap_known=as_bool(raw, "Tray", "gap_known"),
        require_gap_geometry=as_bool(raw, "Tray", "require_gap_geometry"),
        row_tolerance_mm=as_float(raw, "Tray", "row_tolerance_mm"),
    )
    if tray.open_side not in OPEN_SIDES:
        raise ConfigError(
            f"[Tray] open_side={tray.open_side!r} 非法，只能是 {OPEN_SIDES}"
        )
    if tray.row_tolerance_mm < 0.0:
        raise ConfigError(
            f"[Tray] row_tolerance_mm={tray.row_tolerance_mm} 不得为负；"
            "0 = 关闭按行分桶（退回旧行为：'同一排'只认 Y 完全相等）"
        )
    if tray.row_tolerance_mm > 25.0:
        raise ConfigError(
            f"[Tray] row_tolerance_mm={tray.row_tolerance_mm} 超过上限 25.0mm："
            "操作员的排间距实测 ≥50mm（2026-09-22），容差 ≥ 排间距的一半会把"
            "**相邻两排并成一排** ⇒ 排间顺序退化成'这一排从左到右'的乱序"
        )
    if ws.x_min >= ws.x_max or ws.y_min >= ws.y_max:
        raise ConfigError(f"[Workspace] 区间非法：{ws}")
    if not ws.contains_point(home):
        raise ConfigError(
            f"[Home] ({home.x_mm},{home.y_mm}) 不在 [Workspace] {ws} 内 —— "
            "固件会对 HOME 做可达域校验，超界的 HOME 会让整条规划返回 false"
            "（ec_motion_plan.c:166-172）"
        )

    tool_offset = Point(
        as_float(raw, "ToolOffset", "x_mm"),
        as_float(raw, "ToolOffset", "y_mm"),
    )
    gripper = Point(*as_float_pair(raw, "envelope_mm", "Gripper"))
    item_max = Point(*as_float_pair(raw, "max_size_mm", "Motion"))
    exit_clear = _positive(as_float(raw, "Motion", "exit_clearance_mm"),
                           "[Motion] exit_clearance_mm")

    step_timeout = _positive(as_float(raw, "Feedback", "step_timeout_s"),
                             "[Feedback] step_timeout_s")
    step_duration = _positive(as_float(raw, "Feedback", "step_duration_s"),
                              "[Feedback] step_duration_s")
    stale = _positive(as_float(raw, "Vision", "stale_frame_timeout_s"),
                      "[Vision] stale_frame_timeout_s")
    empty_frames = int(as_float(raw, "Vision", "empty_confirmation_frames"))
    if empty_frames < 1:
        raise ConfigError("[Vision] empty_confirmation_frames 必须 ≥ 1")

    mode = as_str(raw, "Vision", "selection_mode").strip()
    if mode not in KNOWN_SELECTION_MODES:
        raise ConfigError(
            f"[Vision] selection_mode={mode!r} 非法，只能是 {KNOWN_SELECTION_MODES}"
        )

    object_sizes: dict[int, Point] = {}
    for param in raw.section_items("ObjectSize"):
        try:
            box_id = int(param.key)
        except ValueError:
            raise ConfigError(f"{param.qualified} 的键必须是 box_id 整数") from None
        object_sizes[box_id] = Point(*as_float_pair(raw, param.key, "ObjectSize"))

    obstacles = tuple(
        as_rect(raw, "Obstacle", p.key) for p in raw.section_items("Obstacle")
    )

    if mode == SELECTION_CONTOUR:
        missing = [b for b in range(1, 7) if b not in object_sizes]
        if missing:
            raise ConfigError(
                "selection_mode=contour 需要 [ObjectSize] 给出每个 box_id 的"
                f"半尺寸（w/2, h/2，mm），缺 {missing}。"
                "现有视觉线格式（BATCH_TARGETS 每目标 7 字节）**不携带宽高或轮廓**"
                "（interface-contract.md:137-143），所以这些值必须由人实测填入，"
                "不得由程序虚构。"
            )

    # ---- 可选 [Strategy] 节（2026-11-01 新增；不写则用默认值，不破坏旧 ini）----
    opt_mode = raw.opt("Strategy", "order_mode")
    order_mode = (opt_mode.value.strip() if opt_mode is not None else "legacy")
    try:
        from electrical_control.pick_strategy.orderer import ORDER_MODES as _OM
        if order_mode not in _OM:
            raise ConfigError(
                f"[Strategy] order_mode={order_mode!r} 非法，只能是 {_OM}")
    except ImportError:      # 极端情况下（部分模块未装）不阻塞加载
        pass
    opt_frames = raw.opt("Strategy", "settle_frames")
    settle_frames = int(opt_frames.value) if opt_frames is not None else 3
    if settle_frames < 1:
        raise ConfigError("[Strategy] settle_frames 必须 ≥ 1")
    opt_shift = raw.opt("Strategy", "settle_shift_mm")
    settle_shift = float(opt_shift.value) if opt_shift is not None else 4.0
    if settle_shift <= 0:
        raise ConfigError("[Strategy] settle_shift_mm 必须 > 0")
    # -- 2026-11-02：[Strategy] skip_shapes / class_id_mode --
    opt_skip = raw.opt("Strategy", "skip_shapes")
    skip_shapes: tuple[int, ...] = ()
    if opt_skip is not None:
        raw_skip = opt_skip.value.replace("，", ",").strip()
        if raw_skip in ("0", "none", "None", "-"):
            raw_skip = ""          # 0/none = 不放弃任何形状（默认口径）
        if raw_skip:
            vals = []
            for part in raw_skip.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    v = int(part)
                except ValueError:
                    raise ConfigError(
                        f"{opt_skip.qualified}={opt_skip.value!r} 含非整数项") from None
                if not (1 <= v <= 6):
                    raise ConfigError(
                        f"{opt_skip.qualified}={opt_skip.value!r} 含越界形状"
                        "（只能是 1..6：1=cube 2=cuboid 3=cylinder "
                        "4=pentagonal_prism 5=cone 6=tetrahedron）")
                vals.append(v)
            skip_shapes = tuple(sorted(set(vals)))

    opt_cid_mode = raw.opt("Strategy", "class_id_mode")
    class_id_mode = (opt_cid_mode.value.strip().lower()
                     if opt_cid_mode is not None else "box_id")
    if class_id_mode not in ("box_id", "code"):
        raise ConfigError(
            f"[Strategy] class_id_mode={class_id_mode!r} 非法，只能是 ('box_id', 'code')")

    opt_band = raw.opt("Strategy", "isolation_band_mm")
    isolation_band = float(opt_band.value) if opt_band is not None else None
    if isolation_band is not None and isolation_band < 0:
        raise ConfigError("[Strategy] isolation_band_mm 不能为负")

    # -- 2026-11-02：[Strategy] 加权排序权重（前端/夹取/路线/隔离度）--
    def _opt_weight(key: str, default: float) -> float:
        param = raw.opt("Strategy", key)
        if param is None:
            return default
        try:
            val = float(param.value)
        except ValueError:
            raise ConfigError(f"{param.qualified}={param.value!r} 不是数字") from None
        if val < 0:
            raise ConfigError(f"{param.qualified} 不能为负")
        return val

    w_front = _opt_weight("weight_front", 0.70)
    w_pick = _opt_weight("weight_pick", 0.15)
    w_route = _opt_weight("weight_route", 0.10)
    w_iso = _opt_weight("weight_isolation", 0.05)
    opt_guard = raw.opt("Strategy", "weighted_guard_hard_first")
    guard_hard_first = True
    if opt_guard is not None:
        low = opt_guard.value.strip().lower()
        if low in ("true", "1", "yes", "on"):
            guard_hard_first = True
        elif low in ("false", "0", "no", "off"):
            guard_hard_first = False
        else:
            raise ConfigError(
                f"{opt_guard.qualified}={opt_guard.value!r} 不是布尔值")
    if (w_front + w_pick + w_route + w_iso) <= 0:
        raise ConfigError("[Strategy] 四个权重之和必须 > 0")

    return StrategyConfig(
        weight_front=w_front,
        weight_pick=w_pick,
        weight_route=w_route,
        weight_isolation=w_iso,
        weighted_guard_hard_first=guard_hard_first,
        skip_shapes=skip_shapes,
        class_id_mode=class_id_mode,
        order_mode=order_mode,
        settle_frames=settle_frames,
        settle_shift_mm=settle_shift,
        isolation_band_mm=isolation_band,
        workspace=ws,
        home=home,
        tray=tray,
        tool_offset=tool_offset,
        gripper_envelope=gripper,
        item_max_size=item_max,
        exit_clearance_mm=exit_clear,
        step_timeout_s=step_timeout,
        step_duration_s=step_duration,
        assume_grasp_without_fault=as_bool(raw, "Feedback", "assume_grasp_without_fault"),
        retain_grasp_on_fault=as_bool(raw, "Feedback", "retain_grasp_on_fault"),
        selection_mode=mode,
        stale_frame_timeout_s=stale,
        empty_confirmation_frames=empty_frames,
        empty_travel_may_cross_tray=as_bool(raw, "Motion", "empty_travel_may_cross_tray"),
        object_sizes=object_sizes,
        obstacles=obstacles,
        raw=raw,
    )


def as_rect(raw: RawConfig, section: str, key: str) -> Rect:
    """读 `x_min, x_max, y_min, y_max` 四数 → Rect。"""
    param = raw.param(section, key)
    parts = [p.strip() for p in param.value.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise ConfigError(
            f"{param.qualified}={param.value!r} 不是 "
            "`x_min, x_max, y_min, y_max` 四数形式"
        )
    try:
        x_min, x_max, y_min, y_max = (float(p) for p in parts)
    except ValueError:
        raise ConfigError(f"{param.qualified}={param.value!r} 含非数字项") from None
    if x_min >= x_max or y_min >= y_max:
        raise ConfigError(f"{param.qualified} 区间非法：{param.value!r}")
    return Rect(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)
