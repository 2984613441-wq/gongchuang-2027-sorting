#!/bin/sh
# MaixCAM 生产发送端启动脚本（2026-11-07）
#
# 用法（设备上）：
#   sh /root/start_send.sh                        # 默认：发 Pi、shape 模式（配 Pi box_id 校赛模式）
#   sh /root/start_send.sh 172.20.10.8 code        # V1.0：code 模式（配 Pi --id-byte-mode code + 动态分配）
#   sh /root/start_send.sh 172.20.10.3 shape       # 调试：发 PC 的三路窗口
#
# 要点：
#  1) launcher 会独占相机 ⇒ 必须先 killall launcher_daemon；
#  2) 快照口 8766（挡板巡检 / 三路窗口 / M3 标定都要用）；
#  3) 模型固定 main_v2（448, cv181x）。
#  4) ⚠️ 模式必须与树莓派一致：
#       shape ⇒ Pi 默认（BATCH_ID_BYTE_MODE=box_id）
#       code  ⇒ Pi 用 --id-byte-mode code --slot-mode dynamic
PI_HOST=${1:-172.20.10.8}
ID_MODE=${2:-shape}
MODEL=/root/my_models/yolo11n_6c_main_v2_448_cv181x.mud

case "$ID_MODE" in
  shape|code) ;;
  *) echo "ID_MODE 只能是 shape 或 code，收到：$ID_MODE" >&2; exit 2 ;;
esac

if [ ! -f "$MODEL" ]; then
  echo "模型不存在：$MODEL" >&2
  exit 1
fi

killall launcher_daemon 2>/dev/null
sleep 1
cd /root || exit 1
pkill -f yolo_v11_send.py 2>/dev/null
sleep 1
setsid nohup python3 -u yolo_v11_send.py \
  --model "$MODEL" \
  --host "$PI_HOST" --port 8765 \
  --id-mode "$ID_MODE" --snap-port 8766 \
  >/tmp/send.log 2>&1 </dev/null &

sleep 2
echo "已启动 yolo_v11_send.py（id-mode=$ID_MODE，发 $PI_HOST:8765，快照 :8766）"
echo "日志：/tmp/send.log"
tail -n 8 /tmp/send.log 2>/dev/null
