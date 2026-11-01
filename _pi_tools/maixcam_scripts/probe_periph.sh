#!/bin/sh
# 查 MaixCAM 有哪些可控 GPIO / PWM（给补光灯控制用）
#
# 用法：sh /root/probe_periph.sh

echo "=============================================================="
echo "  MaixCAM 外设探测（找补光灯能接哪个口）"
echo "=============================================================="

echo
echo "=== 1) GPIO 芯片与线路 ==="
if [ -d /sys/class/gpio ]; then
    ls /sys/class/gpio/ 2>/dev/null | head -20 | sed 's/^/  /'
else
    echo "  /sys/class/gpio 不存在"
fi
for chip in /sys/class/gpio/gpiochip*; do
    [ -e "$chip" ] || continue
    echo "  $chip:"
    echo "    base=$(cat $chip/base 2>/dev/null) label=$(cat $chip/label 2>/dev/null) ngpio=$(cat $chip/ngpio 2>/dev/null)" | sed 's/^/  /'
done

echo
echo "=== 2) PWM 通道 ==="
if [ -d /sys/class/pwm ]; then
    ls /sys/class/pwm/ 2>/dev/null | sed 's/^/  /'
    for p in /sys/class/pwm/pwmchip*; do
        [ -e "$p" ] || continue
        echo "  $p: npwm=$(cat $p/npwm 2>/dev/null)" | sed 's/^/  /'
    done
else
    echo "  /sys/class/pwm 不存在"
fi

echo
echo "=== 3) 已导出的 GPIO 当前状态 ==="
for g in /sys/class/gpio/gpio[0-9]*; do
    [ -e "$g" ] || continue
    echo "  $(basename $g): dir=$(cat $g/direction 2>/dev/null) val=$(cat $g/value 2>/dev/null)" | sed 's/^/  /'
done

echo
echo "=== 4) MaixPy 外设模块 ==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening" | sed 's/^/  /'
try:
    from maix import peripheral
    print("peripheral 模块可用")
    for n in ("gpio", "pwm", "pinmap"):
        print("  has %s: %s" % (n, hasattr(peripheral, n)))
except Exception as e:
    print("peripheral 导入失败: %s" % e)

try:
    from maix import pinmap
    print("pinmap 模块可用（可查引脚功能表）")
except Exception as e:
    print("pinmap 导入失败: %s" % e)
PYEOF

echo
echo "=== 5) 板子型号 / 设备树里的 LED ==="
cat /proc/device-tree/model 2>/dev/null | tr -d '\0' | sed 's/^/  model: /'
echo
for d in /sys/class/leds/*; do
    [ -e "$d" ] || continue
    echo "  LED: $(basename $d)" | sed 's/^/  /'
    [ -e "$d/brightness" ] && echo "    brightness=$(cat $d/brightness 2>/dev/null) max=$(cat $d/max_brightness 2>/dev/null)" | sed 's/^/  /'
done

echo
echo "=============================================================="
echo "  结论："
echo "    · 如果补光灯是**独立开关/独立电源** → 直接物理开，不用代码"
echo "    · 如果是**接在 MaixCAM 的 GPIO/PWM** → 用上面列出的口写控制脚本"
echo "=============================================================="
