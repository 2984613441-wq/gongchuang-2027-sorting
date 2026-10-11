#!/bin/bash
mkdir -p /home/pi/logs
cd /home/pi/电控
export PYTHONPATH=/home/pi/电控/src
LOG=/home/pi/logs/round-R7-$(date +%H%M%S).log
echo "$LOG" > /home/pi/logs/R7-latest.txt
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

echo HOME | nohup python3 deploy/run_chain.py \
  --port /dev/serial0 \
  --image-dir /home/pi/images \
  --names-file /home/pi/电控/deploy/names.json \
  --frame-output fb0 \
  --font /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
  --round-id R7 --round-task-id 1 \
  --pick-strategy order --start-round -v \
  > "$LOG" 2>&1 &
echo "PID=$!  日志=$LOG"
sleep 25
echo "================= 前 25 秒（过滤掉重复的越界刷屏）================="
grep -v '越界：pixel_to_device' "$LOG" | head -45
echo "..."
echo "越界刷屏行数 = $(grep -c '越界：pixel_to_device' "$LOG")"