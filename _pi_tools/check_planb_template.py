# -*- coding: utf-8 -*-
"""校验方案B 配置模板能被真实解析器正确加载（一次性检查脚本）。"""
import sys

from electrical_control.rpi.drop_strategy import load_strategy_from_config

path = sys.argv[1]
s = load_strategy_from_config(path)

print("策略类       :", type(s).__name__)
print("需转盘控制   :", s.requires_turntable_control())
print("用DropPoints :", s.uses_drop_points())
print("落点(0.1mm)  :", s.get_drop_point(1))
print("角度表       :", [(b, s.get_angle(b)) for b in range(1, 7)])

ok = (
    type(s).__name__ == "TurntableStrategy"
    and s.requires_turntable_control()
    and not s.uses_drop_points()
    and s.get_drop_point(1) == (900, 885)          # 90.0mm / 88.5mm -> 0.1mm
    and all(s.get_angle(b) is not None for b in range(1, 7))
)
print()
print("=== 模板校验:", "PASS" if ok else "FAIL", "===")
sys.exit(0 if ok else 1)
