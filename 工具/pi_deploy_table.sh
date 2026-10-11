#!/bin/bash
# 部署「累计分拣统计表」到树莓派并上屏验收。
#   用法（在树莓派上）：bash /home/pi/pi_deploy_table.sh
# 前置：本脚本只做「搬文件 + 停 lightdm + 写一帧表」，不碰串口、不碰 STM32。
set -u

STAGE=/home/pi/_stage
SRC=/home/pi/电控/src/electrical_control/rpi
IMAGES=/home/pi/object_images

echo "=== 1. 停 lightdm（它占着 fb，不停会被盖回去）==="
sudo systemctl stop lightdm
sleep 1
systemctl is-active lightdm || true

echo
echo "=== 2. 装新 display_hdmi.py ==="
ls -l "$STAGE/display_hdmi.py"
if [ -f "$SRC/display_hdmi.py" ]; then
    cp -n "$SRC/display_hdmi.py" "$SRC/display_hdmi.py.bak-table" 2>/dev/null || true
    echo "已备份原文件到 display_hdmi.py.bak-table（若已存在则不覆盖）"
fi
cp "$STAGE/display_hdmi.py" "$SRC/display_hdmi.py"
ls -l "$SRC/display_hdmi.py"
# 清 __pycache__：旧字节码会让「文件换了但行为没换」
find /home/pi/电控/src -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo
echo "=== 3. 预置图片 ==="
ls -l "$IMAGES"

echo
echo "=== 4. 自检：fb 真实格式 ==="
cd /home/pi/电控 || exit 1
PYTHONPATH=src python3 -m electrical_control.rpi.display_hdmi --info || exit 2

echo
echo "=== 5. 写统计表上屏（演示计数）==="
PYTHONPATH=src python3 -m electrical_control.rpi.display_hdmi --table "$IMAGES" --fb /dev/fb0 || exit 3

echo
echo "=== 完成。屏上应是：标题「分拣统计」+ 表头「序号|预置图片|分拣个数」+ 六行 1..6 ==="
echo "演示计数：1=2  2=0  3=1  4=0  5=3  6=0"
echo "看完让画面消失：sudo systemctl start lightdm"
