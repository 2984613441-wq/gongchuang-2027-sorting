#!/bin/bash
# 带 -v(DEBUG) 跑一小段链路，抓出「为什么一件都发不出去」。
# 与 pi_start_chain.sh 参数完全一致，只多一个 -v。用完自动停链。
cd /home/pi/电控 || exit 1

pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2

LOG=/tmp/chain_v.log
rm -f "$LOG"

# ── HOME 门禁（2026-09-21）──────────────────────────────────────────────
# 板子无编码器、不寻零 ⇒ 软件无法判断 XY 是否真的在 HOME；起点错了会让第一段
# 增量运动整体偏移，可能顶死堵转并使开环坐标永久失准。新版 run_chain.py 的
# --start-round 要求 stdin 精确输入 HOME，非交互一律拒绝（nohup 会把 stdin
# 变成 /dev/null）。这里由操作员确认一次再把 HOME 喂给链。
# 见 docs/交付/2026-09-21/交接-2026-09-21-深夜-转盘部署与标定.md §10.5
echo "!!! 期望起点：X=-95.0mm, Y=-97.5mm（X/Y 负方向最里角，均顶住）!!!"
printf '确认滑台已在 HOME 后输入 HOME（其他输入均退出）：'
read -r ANS
if [ "$ANS" != "HOME" ]; then echo ">>> 未确认 HOME，拒绝起链。"; exit 1; fi

echo HOME | PYTHONPATH=src nohup python3 deploy/run_chain.py \
    --config /home/pi/sorting_config.ini \
    --port /dev/serial0 \
    --image-dir /home/pi/images \
    --names-file /home/pi/电控/deploy/names.json \
    --frame-output fb0 \
    --font /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    --round-id r1 --round-task-id 1 \
    --start-round -v > "$LOG" 2>&1 &

sleep 14

echo "############ 关键行（box_id / 拒识 / 抓取点 / TSP / payload / ITEM_TASK）############"
grep -inE 'box_id|拒识|抓取点|TSP|payload|ITEM_TASK|next_task|task' "$LOG" | tail -40

echo
echo "############ 全部 WARNING / ERROR / DEBUG 计数 ############"
echo "WARNING: $(grep -c 'WARNING' "$LOG")   ERROR: $(grep -c 'ERROR' "$LOG")   DEBUG: $(grep -c 'DEBUG' "$LOG")"

echo
echo "############ 去重后的 DEBUG 消息种类（看有没有刷屏的那条）############"
grep 'DEBUG' "$LOG" | sed 's/.*DEBUG *//' | sed 's/[0-9]\+/N/g' | sort | uniq -c | sort -rn | head -15

echo
echo "############ 日志尾部 ############"
tail -12 "$LOG"

echo
echo "############ 收尾：停链 ############"
pkill -f 'deploy/run_chain.py' && echo '已停' || echo '没找到进程'
