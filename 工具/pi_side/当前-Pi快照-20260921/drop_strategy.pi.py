"""落料策略抽象：方案A（六固定盒）vs 方案B（转盘选格）的统一接口。

设计原则（P11-A §1.2）：
- 配置驱动：切换方案 A/B 只改 sorting_config.ini，不改代码分支
- fail-closed：未知 box_id 返回 None → 拒识该件、记日志、链路继续
- 零预留代码：不写无人调用的桩；FixedBoxStrategy 就是当前 run_chain.py 的行为

方案判定：
- 存在 [TurntableAngles] 节 → 方案B（TurntableStrategy）
- 否则 → 方案A（FixedBoxStrategy，读 [DropPoints]）
"""

from __future__ import annotations

import configparser
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


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


def load_strategy_from_config(config_path: str | Path) -> DropStrategy:
    """从 sorting_config.ini 加载落料策略（A/B 自动识别）。

    方案判定：
    - 存在 [TurntableAngles] 节 → TurntableStrategy
    - 否则 → FixedBoxStrategy（读 [DropPoints]）

    fail-closed：
    - 方案A：[DropPoints] 缺货格 1-6 任一项 → raise SystemExit
    - 方案B：[TurntableAngles] 缺货格或 turntable_drop_point 无效 → raise SystemExit
    """
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

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
    else:
        # 方案A：六固定盒
        if not cfg.has_section("DropPoints"):
            raise SystemExit(
                f"方案A 缺 [DropPoints]：{config_path} 必须配置六盒落点"
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
                f"方案A 六盒落点表不完整：{config_path} [DropPoints] 缺货格 {missing}"
            )
        return FixedBoxStrategy(drop_points)


# ========== 自检（可直接 python drop_strategy.py 运行）==========
if __name__ == "__main__":
    from io import StringIO

    # 自检 1：方案A（FixedBoxStrategy）
    cfg_a = StringIO("""[DropPoints]
1 = 10.5, 20.3
2 = 30.0, 40.0
3 = 50.0, 60.0
4 = 70.0, 80.0
5 = 90.0, 100.0
6 = 110.0, 120.0
""")
    tmp_a = Path("_test_a.ini")
    tmp_a.write_text(cfg_a.getvalue(), encoding="utf-8")
    strategy_a = load_strategy_from_config(tmp_a)
    assert isinstance(strategy_a, FixedBoxStrategy)
    assert strategy_a.get_drop_point(1) == (105, 203)  # mm → 0.1mm
    assert strategy_a.get_drop_point(99) is None
    assert not strategy_a.requires_turntable_control()
    tmp_a.unlink()
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
    tmp_b = Path("_test_b.ini")
    tmp_b.write_text(cfg_b.getvalue(), encoding="utf-8")
    strategy_b = load_strategy_from_config(tmp_b)
    assert isinstance(strategy_b, TurntableStrategy)
    assert strategy_b.get_drop_point(2) == (0, 0)  # 所有货格同一落料点
    assert strategy_b.get_angle(2) == 60.0
    assert strategy_b.get_angle(99) is None
    assert strategy_b.requires_turntable_control()
    tmp_b.unlink()
    print("✅ TurntableStrategy 自检通过")

    # 自检 3：fail-closed（缺货格）
    cfg_bad = StringIO("[DropPoints]\n1 = 0, 0\n")  # 只有1号，缺2-6
    tmp_bad = Path("_test_bad.ini")
    tmp_bad.write_text(cfg_bad.getvalue(), encoding="utf-8")
    try:
        load_strategy_from_config(tmp_bad)
        assert False, "应该抛 SystemExit"
    except SystemExit as exc:
        assert "缺货格" in str(exc)
    tmp_bad.unlink()
    print("✅ fail-closed 自检通过")

    print("\n🎉 所有自检通过")
