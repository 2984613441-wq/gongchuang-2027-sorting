# -*- coding: utf-8 -*-
"""只读核对：链会不会把 /home/pi/sorting_config.ini 认成【方案C】。

链的判断在 run_chain.py:1049 —— `config_has_section(args.config, "TurntablePositions")`，
其中 args.config 默认 /home/pi/sorting_config.ini。
本脚本用同一份配置、同一个生产载入器走一遍，把策略类与每个货格的落点/侧/脉宽打出来。
不改任何文件、不发任何运动。

用法：python3 /home/pi/check_turntable_strategy.py
"""
import sys

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.drop_strategy import (        # noqa: E402
    load_strategy_from_config,
)

CFG = "/home/pi/sorting_config.ini"

strategy = load_strategy_from_config(CFG)
name = type(strategy).__name__

print("配置文件   =", CFG)
print("策略类     =", name)
print("需要控转盘 =", strategy.requires_turntable_control())
print("用落点表   =", strategy.uses_drop_points())

side_for = getattr(strategy, "side_for_box", lambda b: "(无此方法)")
pulse_for = getattr(strategy, "pulse_for_box", lambda b: "(无此方法)")
print()
for box in range(1, 7):
    print("  货格 %d  落点=%-16s  侧=%-3s  脉宽=%s"
          % (box, strategy.get_drop_point(box), side_for(box), pulse_for(box)))

assert "TwoPositionTurntableStrategy" in name, \
    "载入的是 %s，不是方案C —— 链不会转盘" % name
assert strategy.requires_turntable_control() is True, "requires_turntable_control 不是 True"

print("\n[PASS] 链会切到方案C（转盘会转）")
