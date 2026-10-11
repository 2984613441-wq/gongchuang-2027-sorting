#!/bin/sh
# 2026-09-22 DSH：生产视觉发送程序（stage1_color_v6_send）监督器 —— 带退避版
#
# 为什么要退避：前一版"崩了 2 秒就重拉"在 sender 打不开摄像头时会变成**无限崩溃循环**，
#   把 CVITEK 媒体线程堆起来 ⇒ 相机 load 冲到 15.99 ⇒ 连 ssh 都响应不了（实测踩过）。
#   现在：连续 3 次"活不到 10 秒"就退避 120 秒 ⇒ 相机保持可用，日志留下完整证据。
#
# 暂停/恢复（取证或调试）：
#   暂停： touch /tmp/vision_pause && ps | grep '[s]tage1_color_v6_send' | awk '{print $1}' | xargs -r kill
#   恢复： rm -f /tmp/vision_pause
SENDER=/root/forensic/stage1_color_v6_send.py
LOG=/var/log/vision-sender.log
FAIL=0

while :; do
    if [ -e /tmp/vision_pause ]; then
        sleep 5
        continue
    fi
    if [ ! -f "$SENDER" ]; then
        echo "[supervisor $(date '+%F %T')] SENDER NOT FOUND: $SENDER" >> "$LOG"
        sleep 30
        continue
    fi
    T0=$(date +%s)
    echo "[supervisor $(date '+%F %T')] starting sender" >> "$LOG"
    python3 "$SENDER" >> "$LOG" 2>&1
    T1=$(date +%s)
    RAN=$((T1 - T0))
    if [ "$RAN" -lt 10 ]; then
        FAIL=$((FAIL + 1))
    else
        FAIL=0
    fi
    if [ "$FAIL" -ge 3 ]; then
        echo "[supervisor $(date '+%F %T')] 连续 $FAIL 次快速失败（本次仅活 ${RAN}s）⇒ 退避 120 秒（防打满 CPU）" >> "$LOG"
        sleep 120
        FAIL=0
    else
        echo "[supervisor $(date '+%F %T')] sender 退出（活 ${RAN}s），3 秒后重试（连续快速失败=$FAIL）" >> "$LOG"
        sleep 3
    fi
done
