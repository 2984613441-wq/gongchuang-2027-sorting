#!/bin/sh
# 复现故障并取 AXIS 现场。流程：基线 → 起链 → 观察 25s → 停链 → 读 AXIS。
# 关键：取读数前绝不复位（复位会清掉 .bss 里的故障锁存）。
echo "########## 0) 板子应答预检（最多等 40 秒，未应答则不启动链路）##########"
if ! python3 /home/pi/pi_wait_board.py 40; then
    echo "❌ 预检未通过，拒绝启动链路（避免又跑出一堆『无应答』假象）"
    exit 3
fi

echo "########## 1) 启动前基线（记下 TICK_MS）##########"
python3 /home/pi/pi_axis_poll.py 4
echo "现在时间: $(date '+%H:%M:%S')"

echo "########## 2) 启动链路 ##########"
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 1
rm -f /tmp/chain.log
cd /home/pi/电控 || exit 1
PYTHONPATH=src nohup python3 deploy/run_chain.py \
    --config /home/pi/sorting_config.ini \
    --port /dev/serial0 \
    --image-dir /home/pi/images \
    --names-file /home/pi/电控/deploy/names.json \
    --frame-output fb0 \
    --font /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    --round-id r1 --round-task-id 1 \
    --start-round > /tmp/chain.log 2>&1 &
echo "链路已启动: $(date '+%H:%M:%S')"

echo "########## 3) 观察 25 秒 ##########"
sleep 25
echo "ITEM_TASK sent 次数 : $(grep -c 'ITEM_TASK sent' /tmp/chain.log)"
echo "BARRIER_READY 次数  : $(grep -c 'BARRIER_READY' /tmp/chain.log)"
echo "inbound MOTION_DONE : $(grep -c 'inbound: MOTION_DONE' /tmp/chain.log)"

echo "########## 4) 停链（必须停，否则串口被占）##########"
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
pgrep -af 'run_chain' | grep python3 || echo "链路已停"
echo "停链时间: $(date '+%H:%M:%S')"

echo "########## 5) ★ AXIS 故障现场（勿断电/勿按 RESET）★ ##########"
python3 /home/pi/pi_axis_poll.py 25

echo "########## 6) 日志尾部 ##########"
tail -20 /tmp/chain.log
