#!/bin/bash
# 验证树莓派上的 sorting_config.ini 可被正确加载（方案A / DropPoints）
cd /home/pi/电控/deploy || exit 1
echo "=== 配置关键行 ==="
grep -nE '^stm32_port|^\[DropPoints\]|^1 = ' sorting_config.ini

echo
echo "=== 加载实测 ==="
PYTHONPATH=/home/pi/电控/src python3 - <<'PY'
import configparser
from electrical_control.rpi.drop_strategy import load_strategy_from_config

path = "sorting_config.ini"
cfg = configparser.ConfigParser()
cfg.read(path, encoding="utf-8")
print("sections:", [s for s in cfg.sections() if s in ("DropPoints", "TurntableAngles")])

strategy = load_strategy_from_config(path)
print("strategy:", type(strategy).__name__)
for b in range(1, 7):
    print("  box %d ->" % b, strategy.point_for(b) if hasattr(strategy, "point_for") else "?")
print("CONFIG_OK")
PY
