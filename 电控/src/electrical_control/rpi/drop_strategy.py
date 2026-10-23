"""落料策略抽象：方案A（六固定盒）vs 方案B（转盘选格）的统一接口。

设计原则（P11-A §1.2）：
- 配置驱动：切换方案 A/B 只改 sorting_config.ini，不改代码分支
- fail-closed：未知 box_id 返回 None → 拒识该件、记日志、链路继续
- 零预留代码：不写无人调用的桩；FixedBoxStrategy 就是当前 run_chain.py 的行为

方案判定（2026-09-21 起三种）：
- 存在 [TurntableAngles]    → 方案B（TurntableStrategy，1 个落点 × 6 个角度）
- 存在 [TurntablePositions] → 方案C（TwoPositionTurntableStrategy，**3 个落点 × 2 个位置**）
- 否则                      → 方案A（FixedBoxStrategy，读 [DropPoints]）
"""

from __future__ import annotations

import configparser
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from electrical_control.rpi.turntable import TurntableConfig, TurntableError

logger = logging.getLogger(__name__)

# 方案C：转盘的 2 个位置标识。**不是货格号**，不进 wire（ITEM_TASK 一个字节都不加）。
SIDE_A = "a"
SIDE_B = "b"
_SIDES = (SIDE_A, SIDE_B)


class DropStrategy(ABC):
    """落料策略抽象：根据 box_id 确定落料位置（方案A）或转盘角度（方案B）。"""

    @abstractmethod
    def get_drop_point(self, box_id: int) -> tuple[int, int] | None:
        """查落料点（0.1mm），未知 box_id 返回 None。"""
        pass

    @abstractmethod
    def requires_turntable_control(self) -> bool:
        """是否需要转盘控制（方案B=True，方案A=False）。"""
        pass

    def uses_drop_points(self) -> bool:
        """落点表是否来自 [DropPoints]（方案A/C=True，方案B=False）。

        只用于启动期一致性校验，**不参与任何坐标计算**；给默认实现 ⇒
        已有子类（FixedBoxStrategy / TurntableStrategy）行为不变。
        """
        return True


class FixedBoxStrategy(DropStrategy):
    """方案A：六固定盒，box_id → 固定坐标（从 [DropPoints] 读）。"""

    def __init__(self, drop_points: dict[int, tuple[int, int]]):
        """
        Args:
            drop_points: {box_id: (x_0.1mm, y_0.1mm)}，已换算为 0.1mm
        """
        self._drop_points = drop_points
        logger.info(
            "[FixedBox] 六盒落点表: %s", dict(sorted(self._drop_points.items()))
        )

    def get_drop_point(self, box_id: int) -> tuple[int, int] | None:
        """查落料点（0.1mm），未知 box_id 返回 None。"""
        point = self._drop_points.get(box_id)
        if point is None:
            logger.warning(
                "[FixedBox] 未知 box_id=%d（表中只有 %s），拒识该件",
                box_id, sorted(self._drop_points.keys())
            )
        return point

    def requires_turntable_control(self) -> bool:
        return False


class TurntableStrategy(DropStrategy):
    """方案B：转盘选格，box_id → 转盘角度（落料点固定，转盘对准货格）。

    落料点：固定在装置角落或机械臂可达的某位置（由 turntable_drop_point 指定）。
    转盘角度：从 [TurntableAngles] 读，格式 box_id = angle_degrees。
    """

    def __init__(
        self,
        turntable_drop_point: tuple[int, int],
        angle_table: dict[int, float],
    ):
        """
        Args:
            turntable_drop_point: 固定落料点 (x_0.1mm, y_0.1mm)
            angle_table: {box_id: angle_degrees}（0° = 货格1零位，顺时针）
        """
        self._drop_point = turntable_drop_point
        self._angles = angle_table
        logger.info(
            "[Turntable] 固定落料点=%s，角度表=%s",
            self._drop_point, sorted(self._angles.keys())
        )

    def get_drop_point(self, box_id: int) -> tuple[int, int] | None:
        """方案B：所有货格用同一落料点，box_id 只决定转盘角度。"""
        angle = self._angles.get(box_id)
        if angle is None:
            logger.warning(
                "[Turntable] 未知 box_id=%d（表中只有 %s），拒识该件",
                box_id, sorted(self._angles.keys())
            )
            return None
        # 方案B：落料点固定，所有货格用同一坐标
        return self._drop_point

    def get_angle(self, box_id: int) -> float | None:
        """查转盘角度（度），未知 box_id 返回 None。"""
        return self._angles.get(box_id)

    def requires_turntable_control(self) -> bool:
        return True

    def uses_drop_points(self) -> bool:
        return False  # 方案B：落点固定，不读 [DropPoints]


class TwoPositionTurntableStrategy(FixedBoxStrategy):
    """方案C（2026-09-21 用户裁决）：**3 个固定落点 × 转盘 2 个位置**。

    与 A / B 的关系
    ---------------
    * 落料点（滑台记账坐标）**完全沿用方案A 的 [DropPoints]**：6 行，其中 4/5/6 是
      1/2/3 的"孪生格"（转盘翻 180° 后落到同一坐标）⇒ **查点逻辑直接继承，一个字不改**。
    * 与方案B 的区别：B = 1 个落点 + 6 个角度；C = **3 个落点 + 2 个角度**。

    为什么新建类而不扩展方案B
    -------------------------
    B 的不变式是"所有 box_id 用同一个落点"，C 的是"3 个落点 × 2 侧"。
    硬塞进一个类会让下面"落点表是否完整"那条 fail-closed 校验失去意义。
    所以新建子类，共用 A 的查点与报错路径。

    ⚠️ 本类**不自带 GPIO/文件写入** —— 只管"查表 + 算脉宽"。
       真正的下发与到位校验在 `rpi/turntable.Turntable` 与
       `rpi/turntable_guard.TurntableGuard`。
    """

    def __init__(
        self,
        drop_points: dict[int, tuple[int, int]],
        *,
        side_of_box: dict[int, str],
        config: TurntableConfig,
        index_side: str | None = None,
        index_pin: int = 17,
    ) -> None:
        super().__init__(drop_points)
        self._side_of_box = dict(side_of_box)
        self.turntable_config = config      # 脉宽换算 + 越界 fail-closed 都在这里面
        self.index_side = index_side        # 'a' / 'b' / None(=没有可用索引)
        self.index_pin = index_pin          # 索引开关引脚（默认 GPIO17）
        lo, hi = config.coverage()
        logger.info(
            "[TwoPos] 3 落点 × 2 位置：A 侧=%s  B 侧=%s  脉宽范围=[%d,%d]µs  "
            "整定=%.2fs  索引=%s",
            sorted(b for b, s in self._side_of_box.items() if s == SIDE_A),
            sorted(b for b, s in self._side_of_box.items() if s == SIDE_B),
            lo, hi, config.settle_s,
            index_side if index_side else "无（只按时间判到位）",
        )

    # ---- 落点：继承 FixedBoxStrategy，不动 ----

    def requires_turntable_control(self) -> bool:
        return True

    def uses_drop_points(self) -> bool:
        return True                          # 落点仍来自 [DropPoints]

    # ---- 转盘侧 ----

    def side_for_box(self, box_id: int) -> str | None:
        """货格 → 转盘侧（'a'/'b'）。查不到返回 None ⇒ 调用方拒识该件。"""
        return self._side_of_box.get(box_id)

    def side_of_box(self) -> dict[int, str]:
        return dict(self._side_of_box)       # 只读副本，防调用方就地改

    def pulse_for_box(self, box_id: int) -> int:
        """货格 → 脉宽（µs）。越界 / 缺格 **必然 raise**（见 TurntableConfig）。"""
        return self.turntable_config.pulse_for_box(box_id)


def _read_drop_points(
    cfg: configparser.ConfigParser, config_path: str | Path, label: str
) -> dict[int, tuple[int, int]]:
    """读 [DropPoints] 六行（mm → 0.1mm）。方案A 与方案C 共用同一条校验路径。

    `label` 只出现在报错文案里；方案A 传 "方案A" ⇒ 与接线前的报错**逐字相同**。
    """
    if not cfg.has_section("DropPoints"):
        raise SystemExit(
            f"{label} 缺 [DropPoints]：{config_path} 必须配置六盒落点"
        )
    drop_points: dict[int, tuple[int, int]] = {}
    for key, value in cfg.items("DropPoints"):
        try:
            box_id = int(key)
            x_mm, y_mm = (float(part) for part in value.split(","))
        except ValueError:
            continue
        if 1 <= box_id <= 6:
            drop_points[box_id] = (int(round(x_mm * 10)), int(round(y_mm * 10)))

    missing = [b for b in range(1, 7) if b not in drop_points]
    if missing:
        raise SystemExit(
            f"{label} 六盒落点表不完整：{config_path} [DropPoints] 缺货格 {missing}"
        )
    return drop_points


# ============================================================================
# 可达域校验（2026-10-22 T3 新增）
# ============================================================================
# 数值来源：电控/firmware/stm32f407_m144z/App/Inc/ec_motion_plan.h
#   EC_MOTION_HOME_X_MM10       = -950   原点 X（最负角，上电手工推到这里）
#   EC_MOTION_HOME_Y_MM10       = -975   原点 Y
#   EC_MOTION_REACH_FAR_X_MM10  = +900   正端（相对 ±950 极限留 5mm 余量）
#   EC_MOTION_REACH_FAR_Y_MM10  = +925   正端（相对 ±975 极限留 5mm 余量）
#
# 🔴 为什么必须校验：
#    X/Y **没有限位开关**，超出可达域会持续堵转 → 电流拉满、发热
#    → 把主控带挂（历史实测已发生 3 次，见 sorting_config.ini [DropPoints] 注释）。
#    固件侧自己没法发现越界（它只会闷头走完），所以必须在**启动期**拦住。
#
# ⚠️ 坐标系：滑台记账坐标（与固件同口径），单位 0.1mm。
#    原点 = 装置最负角 = HOME，所以范围是 [-950, +900] 而不是 [0, +1850]。
REACH_X_MIN_MM10 = -950
REACH_X_MAX_MM10 = 900
REACH_Y_MIN_MM10 = -975
REACH_Y_MAX_MM10 = 925


def _check_within_reach(strategy: DropStrategy, config_path: str | Path) -> None:
    """启动期校验：所有落料点必须落在可达域内。

    fail-closed：任一货格越界 → SystemExit（**拒绝启动**，绝不带着越界配置跑）。

    只由 `load_strategy_from_config`（读真实文件）调用；
    `load_strategy_from_cfg`（自检/单测用）**不受影响** —— 那些自检用的是
    任意构造的坐标，不代表物理可达域。
    """
    violations: list[str] = []
    for box_id in range(1, 7):
        point = strategy.get_drop_point(box_id)
        if point is None:
            continue  # 未知货格（fail-closed 由各 strategy 自行处理）
        x_mm10, y_mm10 = point
        if not (REACH_X_MIN_MM10 <= x_mm10 <= REACH_X_MAX_MM10) or not (
            REACH_Y_MIN_MM10 <= y_mm10 <= REACH_Y_MAX_MM10
        ):
            violations.append(
                "货格 %d 落点 (%.1f, %.1f)mm 超可达域 "
                "X[%.1f, %.1f] Y[%.1f, %.1f]"
                % (
                    box_id, x_mm10 / 10.0, y_mm10 / 10.0,
                    REACH_X_MIN_MM10 / 10.0, REACH_X_MAX_MM10 / 10.0,
                    REACH_Y_MIN_MM10 / 10.0, REACH_Y_MAX_MM10 / 10.0,
                )
            )
    if violations:
        raise SystemExit(
            "落料点越界（X/Y 无限位开关，超程会堵转并把主控带挂，实测已发生 3 次）：\n"
            "  配置：%s\n  %s" % (config_path, "\n  ".join(violations))
        )


def load_strategy_from_config(config_path: str | Path) -> DropStrategy:
    """从 sorting_config.ini **文件**加载落料策略（A/B/C 自动识别）。

    与 `load_strategy_from_cfg` 的唯一区别：
    **本函数额外做可达域校验**（`_check_within_reach`），因为只有它代表"要真跑"。
    """
    # 🔴 2026-10-23：必须剥行内注释。configparser 默认**不**剥，于是
    #      `1 = -112.5   # 脉宽 681µs`
    #    解出来的 value 是 `-112.5   # 脉宽 681µs`，float() 抛 ValueError 后被
    #    load_strategy_from_cfg 里的 `except ValueError: continue` **静默跳过**，
    #    最后报 "方案B 转盘角度表不完整：缺货格 [1,2,3,4,5,6]"
    #    —— 真正原因（行内注释）在错误信息里完全看不出来。2026-10-23 实际踩过。
    # ⚠️ 与 pixel_to_device.py:210 保持同一行为（那里早就加了，本处遗漏）。
    # ⚠️ 已核对：现行 sorting_config.ini 的所有值里都没有 `#`，加此参数安全。
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    cfg.read(config_path, encoding="utf-8")
    strategy = load_strategy_from_cfg(cfg, config_path)
    _check_within_reach(strategy, config_path)
    return strategy


def load_strategy_from_cfg(
    cfg: configparser.ConfigParser, config_path: str | Path = "<memory>"
) -> DropStrategy:
    """从**已解析的** ConfigParser 加载落料策略（A/B/C 自动识别）。

    加载器主体在这里；`load_strategy_from_config` 只是"读文件 + 委托"。
    拆出来是为了让**自检完全不碰文件系统**：不需要临时目录，也不会往 CWD 落
    `_test_*.ini`（历史自检的旧习惯，已一并改掉）。

    fail-closed：
    - 方案A：[DropPoints] 缺货格 1-6 任一项 → raise SystemExit
    - 方案B：[TurntableAngles] 缺货格或 turntable_drop_point 无效 → raise SystemExit
    - 方案C：见 `_load_two_position_strategy` 的说明
    """
    # 方案判定
    if cfg.has_section("TurntableAngles"):
        # 方案B：转盘
        if not cfg.has_option("TurntableAngles", "turntable_drop_point"):
            raise SystemExit(
                f"方案B 缺 turntable_drop_point：{config_path} [TurntableAngles] "
                "需配置 turntable_drop_point = x_mm, y_mm"
            )
        raw = cfg.get("TurntableAngles", "turntable_drop_point")
        try:
            x_mm, y_mm = (float(part.strip()) for part in raw.split(","))
        except ValueError as exc:
            raise SystemExit(
                f"turntable_drop_point 格式错误（需 x_mm, y_mm）：{raw}"
            ) from exc
        drop_point = (int(round(x_mm * 10)), int(round(y_mm * 10)))

        # 读角度表（box_id = angle_degrees）
        angle_table: dict[int, float] = {}
        for key, value in cfg.items("TurntableAngles"):
            if key == "turntable_drop_point":
                continue  # 跳过非角度配置项
            try:
                box_id = int(key)
                angle = float(value)
            except ValueError:
                continue  # 跳过格式错误项
            if 1 <= box_id <= 6:
                angle_table[box_id] = angle

        missing = [b for b in range(1, 7) if b not in angle_table]
        if missing:
            raise SystemExit(
                f"方案B 转盘角度表不完整：{config_path} [TurntableAngles] "
                f"缺货格 {missing}"
            )
        return TurntableStrategy(drop_point, angle_table)
    elif cfg.has_section("TurntablePositions"):
        # 方案C：3 个固定落点 × 转盘 2 个位置（2026-09-21 用户裁决）
        return _load_two_position_strategy(cfg, config_path)
    else:
        # 方案A：六固定盒（行为与接线前逐字节一致，只是解析搬进了 _read_drop_points）
        return FixedBoxStrategy(_read_drop_points(cfg, config_path, "方案A"))


def _load_two_position_strategy(
    cfg: configparser.ConfigParser, config_path: str | Path
) -> TwoPositionTurntableStrategy:
    """方案C：3 个固定落点（[DropPoints]）+ 转盘 2 个位置（[TurntablePositions]）。

    fail-closed（缺任一项都拒绝启动，**绝不猜**）：
    * 缺 [TurntableSides]，或 6 格任缺一行 / 侧名非法 / 某一侧一个货格都没有；
    * 缺 [TurntablePositions] 的必需键 / 数值非法；
    * 由角度算出的脉宽越出 pigpio 的 [500, 2500] µs —— 这正是"向一侧直接要 180°"
      会踩的坑（1500±1310 → 190/2810）。`coverage()` 在**启动时**就把它拦下来，
      而不是等第一件物料走到落料才炸。
    * 3 个落点必须"每点恰好一格 a、一格 b"（孪生一致性）：两侧共用同一批滑台坐标，
      配错侧 = 投错格。
    """
    # 配置自相矛盾：配了 [TurntableSides] 却没有 [TurntablePositions]
    if not cfg.has_section("TurntableSides"):
        raise SystemExit(
            f"方案C 缺 [TurntableSides]：{config_path} 必须显式写出「哪个货格在哪一侧」。"
            "货格→侧的分配规则**未经用户裁决**，程序绝不猜（缺一行就拒绝启动）。"
        )

    # ---- 1) 货格 → 侧（6 格必须齐全）----
    side_of_box: dict[int, str] = {}
    for box_id in range(1, 7):
        raw = cfg.get("TurntableSides", str(box_id), fallback="").strip().lower()
        if raw not in _SIDES:
            raise SystemExit(
                f"方案C [TurntableSides] {box_id} = {raw!r} 非法：只能是 "
                f"{' 或 '.join(_SIDES)}（缺行 / 写错都拒绝启动，不猜）"
            )
        side_of_box[box_id] = raw
    for side in _SIDES:
        if not any(s == side for s in side_of_box.values()):
            raise SystemExit(
                f"方案C [TurntableSides] 里 {side!r} 侧一个货格都没有 —— "
                "2 位置转盘要求两侧都有货格；只有一侧请改用方案A（删掉 [TurntablePositions]）"
            )

    # ---- 2) 两个位置的角度（基准 = 舵机中心；实测数据见 ini 注释）----
    def _num(key: str, *, cast, default=None):
        if not cfg.has_option("TurntablePositions", key):
            if default is not None:
                return default
            raise SystemExit(
                f"方案C 缺 [TurntablePositions] {key}：{config_path}（拒绝启动，不猜标定值）"
            )
        try:
            return cast(cfg.get("TurntablePositions", key))
        except ValueError as exc:
            raise SystemExit(f"[TurntablePositions] {key} 不是合法数字：{exc}") from exc

    center_us = _num("center_us", cast=int)
    us_per_90deg = _num("us_per_90deg", cast=float)
    angle_a = _num("angle_a", cast=float)      # 两个角度**互相独立**，装夹偏心就分别改
    angle_b = _num("angle_b", cast=float)
    settle_s = _num("settle_s", cast=float, default=1.0)
    index_pin = _num("index_pin", cast=int, default=17)
    raw_index = cfg.get("TurntablePositions", "index_side", fallback="none").strip().lower()
    if raw_index not in (SIDE_A, SIDE_B, "none"):
        raise SystemExit(f"[TurntablePositions] index_side = {raw_index!r} 非法：a / b / none")
    index_side = None if raw_index == "none" else raw_index

    angle_of_side = {SIDE_A: angle_a, SIDE_B: angle_b}
    try:
        config = TurntableConfig(
            zero_pulse_us=center_us,
            us_per_degree=us_per_90deg / 90.0,
            angle_sign=-1,       # 已实测：脉宽减小 = 顺时针（turntable.py 头注释）
            angle_table={b: angle_of_side[s] for b, s in side_of_box.items()},
            settle_s=settle_s,
        )
        lo, hi = config.coverage()   # ← 越界在这里就 raise，不等到第一件物料
    except TurntableError as exc:
        # 统一成 SystemExit：启动期失败应该是一句清楚的话，不是一条 traceback
        raise SystemExit(f"方案C 转盘标定非法（拒绝启动）：{exc}") from exc

    # ---- 3) 落点表 + 孪生一致性 ----
    drop_points = _read_drop_points(cfg, config_path, "方案C")
    groups: dict[tuple[int, int], dict[str, list[int]]] = {}
    for box_id, point in drop_points.items():
        groups.setdefault(point, {}).setdefault(side_of_box[box_id], []).append(box_id)
    bad = {
        point: {side: sorted(boxes) for side, boxes in sides.items()}
        for point, sides in groups.items()
        if sorted(sides) != list(_SIDES) or any(len(v) != 1 for v in sides.values())
    }
    if bad:
        raise SystemExit(
            "方案C 孪生一致性校验失败：每个落点必须**恰好**一格在 a、一格在 b"
            f"（转盘翻 180° 后两侧共用同一批滑台坐标）。违规落点={bad}"
        )

    logger.info("[方案C] 落点查表共用方案A；转盘脉宽范围=[%d,%d]µs", lo, hi)
    return TwoPositionTurntableStrategy(
        drop_points,
        side_of_box=side_of_box,
        config=config,
        index_side=index_side,
        index_pin=index_pin,
    )


# ========== 自检（可直接 python drop_strategy.py 运行）==========
if __name__ == "__main__":
    # ⚠️ 自检**完全不碰文件系统**（configparser.read_string 走内存）：
    #    不需要临时目录，也不会往 CWD 落 _test_*.ini（旧写法会留下 4 个临时文件）。
    from io import StringIO

    def _selftest_load(text: str) -> DropStrategy:
        # 2026-10-23：自检必须用与 load_strategy_from_config 同一种解析器，
        # 否则测的行为和真实路径不一致（行内注释在那边会被剥、在这边不会）。
        _cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
        _cfg.read_string(text)
        return load_strategy_from_cfg(_cfg, "<selftest>")

    # 自检 1：方案A（FixedBoxStrategy）
    cfg_a = StringIO("""[DropPoints]
1 = 10.5, 20.3
2 = 30.0, 40.0
3 = 50.0, 60.0
4 = 70.0, 80.0
5 = 90.0, 100.0
6 = 110.0, 120.0
""")
    strategy_a = _selftest_load(cfg_a.getvalue())
    assert isinstance(strategy_a, FixedBoxStrategy)
    assert not isinstance(strategy_a, TwoPositionTurntableStrategy)
    assert strategy_a.get_drop_point(1) == (105, 203)  # mm → 0.1mm
    assert strategy_a.get_drop_point(99) is None
    assert not strategy_a.requires_turntable_control()
    assert strategy_a.uses_drop_points()
    print("✅ FixedBoxStrategy 自检通过")

    # 自检 2：方案B（TurntableStrategy）
    cfg_b = StringIO("""[TurntableAngles]
turntable_drop_point = 0, 0
1 = 0
2 = 60
3 = 120
4 = 180
5 = 240
6 = 300
""")
    strategy_b = _selftest_load(cfg_b.getvalue())
    assert isinstance(strategy_b, TurntableStrategy)
    assert strategy_b.get_drop_point(2) == (0, 0)  # 所有货格同一落料点
    assert strategy_b.get_angle(2) == 60.0
    assert strategy_b.get_angle(99) is None
    assert strategy_b.requires_turntable_control()
    assert not strategy_b.uses_drop_points()
    print("✅ TurntableStrategy 自检通过")

    # 自检 2b（2026-10-23）：**行内注释必须被正确剥掉**。
    #
    # 历史：configparser 默认不剥行内注释，于是
    #     1 = -112.5   # 脉宽 681µs
    # 解出来的 value 是 "-112.5   # 脉宽 681µs"，float() 抛 ValueError，
    # 被 load_strategy_from_cfg 的 `except ValueError: continue` **静默跳过**，
    # 最终报 "方案B 转盘角度表不完整：缺货格 [1,2,3,4,5,6]"
    # —— 真因（行内注释）在错误信息里完全看不出来。2026-10-23 实际踩过。
    #
    # 修法：所有 ConfigParser 统一加 inline_comment_prefixes=("#",)
    #       （与 pixel_to_device.py:210 早就在用的行为对齐）。
    #
    # 本断言固定修好后的行为：**带行内注释的角度表必须能正常解析**，
    # 且值等于注释前面的那个数。若有人把这个参数去掉，这条会立刻红 ——
    # 这正是我们要的警报，因为去掉它会让配置里的注释变成隐形地雷。
    cfg_b_inline_comment = StringIO("""[TurntableAngles]
turntable_drop_point = 90.0, 88.5   # 固定落料点（装置坐标 mm）
1 = -112.5   # 脉宽 681µs
2 = -67.5    # 脉宽 1009µs
3 = -22.5    # 脉宽 1336µs
4 = 22.5     # 脉宽 1664µs
5 = 67.5     # 脉宽 1991µs
6 = 112.5    # 脉宽 2319µs
""")
    strategy_b_inline = _selftest_load(cfg_b_inline_comment.getvalue())
    assert isinstance(strategy_b_inline, TurntableStrategy)
    assert strategy_b_inline.get_angle(1) == -112.5, "行内注释把值带进 float() 了"
    assert strategy_b_inline.get_angle(6) == 112.5
    assert strategy_b_inline.get_drop_point(1) == (900, 885), "落料点的行内注释未被剥掉"
    for _b in range(1, 7):
        assert strategy_b_inline.get_angle(_b) is not None, "有格子被静默跳过"
    print("✅ 行内注释正确剥除自检通过（2026-10-23 修复后行为）")

    # 反向对照：注释单独占行也必须照常工作（两种写法都支持）。
    cfg_b_own_line_comment = StringIO("""[TurntableAngles]
turntable_drop_point = 0, 0
# 这是单独占行的注释，不影响解析
1 = -112.5
2 = -67.5
3 = -22.5
4 = 22.5
5 = 67.5
6 = 112.5
""")
    strategy_b2 = _selftest_load(cfg_b_own_line_comment.getvalue())
    assert isinstance(strategy_b2, TurntableStrategy)
    assert strategy_b2.get_angle(1) == -112.5
    assert strategy_b2.get_angle(6) == 112.5
    for _b in range(1, 7):
        assert strategy_b2.get_angle(_b) is not None
    print("✅ 独立注释行自检通过（注释占行也照常工作）")


    # 自检 3：fail-closed（缺货格）
    cfg_bad = "[DropPoints]\n1 = 0, 0\n"   # 只有 1 号，缺 2-6
    try:
        _selftest_load(cfg_bad)
        raise AssertionError("应该抛 SystemExit")
    except SystemExit as exc:
        assert "缺货格" in str(exc), exc
    print("✅ fail-closed 自检通过")

    # ========== 自检 4~10：方案C（TwoPositionTurntableStrategy）==========

    C_OK = """[DropPoints]
1 = -25.0, 87.5
2 = -95.0, 47.5
3 = 45.0, 47.5
4 = -25.0, 87.5
5 = -95.0, 47.5
6 = 45.0, 47.5

[TurntablePositions]
center_us = 1500
us_per_90deg = 655
angle_a = 90
angle_b = -90
settle_s = 1.0
index_side = none
index_pin = 17

[TurntableSides]
1 = a
2 = a
3 = a
4 = b
5 = b
6 = b
"""

    # 自检 4：正常配置（3 个落点 × 2 个位置）
    s_c = _selftest_load(C_OK)
    assert isinstance(s_c, TwoPositionTurntableStrategy)
    assert s_c.requires_turntable_control() and s_c.uses_drop_points()
    assert s_c.get_drop_point(1) == s_c.get_drop_point(4) == (-250, 875)
    assert s_c.get_drop_point(2) == s_c.get_drop_point(5) == (-950, 475)
    assert s_c.get_drop_point(3) == s_c.get_drop_point(6) == (450, 475)
    assert s_c.side_for_box(1) == SIDE_A and s_c.side_for_box(4) == SIDE_B
    assert s_c.pulse_for_box(1) == 845 and s_c.pulse_for_box(4) == 2155
    assert s_c.turntable_config.coverage() == (845, 2155)
    assert len(s_c.side_of_box()) == 6
    print("✅ 方案C 正常配置自检通过（A=845µs / B=2155µs，3 落点孪生）")

    # 自检 5~9：五条 fail-closed
    def _must_fail(text: str, needle: str, tag: str) -> None:
        try:
            _selftest_load(text)
        except (SystemExit, RuntimeError) as exc:   # TurntableError 是 RuntimeError 子类
            assert needle in str(exc), f"{tag}: 报错文案里没有 {needle!r}：{exc}"
        else:
            raise AssertionError(f"{tag}: 应该抛 SystemExit / TurntableError")

    _must_fail(C_OK.replace("[TurntableSides]", "[NoSides]"),
               "缺 [TurntableSides]", "缺侧表")
    _must_fail(C_OK.replace("5 = b", "5 = c"), "非法", "侧名非法")
    _must_fail(C_OK.replace("4 = b\n5 = b\n6 = b", "4 = a\n5 = a\n6 = a"),
               "一个货格都没有", "一侧为空")
    _must_fail(C_OK.replace("4 = b", "4 = a"), "孪生一致性", "孪生错位（同落点两个 a）")
    _must_fail(C_OK.replace("angle_b = -90", "angle_b = -180"), "超出", "角度越界（-180°→2810µs）")
    print("✅ 方案C fail-closed 自检通过（缺侧表 / 侧名非法 / 一侧为空 / 孪生错位 / 角度越界）")

    # 自检 10：方案A 回归 —— 只有 [DropPoints] 的配置，行为必须不变
    s_a2 = _selftest_load("""[DropPoints]
1 = 1.0, 2.0
2 = 3.0, 4.0
3 = 5.0, 6.0
4 = 7.0, 8.0
5 = 9.0, 10.0
6 = 11.0, 12.0
""")
    assert isinstance(s_a2, FixedBoxStrategy)
    assert not isinstance(s_a2, TwoPositionTurntableStrategy)
    assert not s_a2.requires_turntable_control()
    assert s_a2.uses_drop_points()
    assert s_a2.get_drop_point(1) == (10, 20)
    print("✅ 方案A 回归自检通过（无 [TurntablePositions] 时行为与接线前一致）")

    print("\n🎉 所有自检通过")
