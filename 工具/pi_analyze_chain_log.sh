#!/bin/sh
# 先停链（安全），再把日志留档，然后统计板子究竟发回了哪些事件类型。
cp /tmp/chain.log /tmp/chain_run1.log 2>/dev/null
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2

echo "=== 链路是否已停 ==="
pgrep -af 'run_chain' | grep python3 || echo "已停止"

LOG=/tmp/chain_run1.log
echo "=== 留档日志行数 ==="
wc -l < "$LOG"

echo "=== inbound 事件类型统计（板子发来了什么）==="
grep -o 'inbound: [A-Z_]*' "$LOG" | sort | uniq -c

echo "=== 是否收到过 MOTION_DONE ==="
grep -c 'inbound: MOTION_DONE' "$LOG" || echo 0

echo "=== ITEM_TASK sent 次数 ==="
grep -c 'ITEM_TASK sent' "$LOG" || echo 0

echo "=== 落点/抓取点明细 ==="
grep 'ITEM_TASK sent' "$LOG"

echo "=== 所有 inbound 行（前 40 条）==="
grep -n 'inbound' "$LOG" | head -40

echo "=== ERROR / FAULT / Traceback ==="
grep -nE 'ERROR|FAULT|Traceback|Exception' "$LOG" | head -20

echo "=== BARRIER_READY 行（前 12 条）==="
grep -n 'BARRIER_READY' "$LOG" | head -12
