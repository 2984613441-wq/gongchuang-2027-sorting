#!/bin/sh
# ============================================================================
# MaixCAM 视觉单次运行器（用于灯光下的识别测试）
#
# 为什么需要它：
#   · MaixCAM 默认跑着 launcher_daemon（桌面启动器），它**占着相机**。
#     直接跑视觉会打不开摄像头，而且旧版会变成"无限崩溃循环"把 CPU 打满。
#   · vision_supervisor.sh 有 free_camera() 但那套是给开机自启用的，
#     这里要的是"跑一次、看得见结果、完了把桌面还回来"。
#
# 用法（在 MaixCAM 上）：
#   sh /root/run_vision_once.sh                 # 跑默认（1280 新版）
#   sh /root/run_vision_once.sh /root/xxx.py    # 跑指定脚本
#   FRAME_W=640 DETECT_SIZE=224 sh /root/run_vision_once.sh   # 降分辨率
#
# 环境变量：
#   FRAME_W / FRAME_H / DETECT_SIZE  透传给视觉脚本
#   USE_GEOMETRY_SHAPE=1             启用几何形状判定（需 shape_geometry_lite.py 在同目录）
#   DURATION                         运行秒数（默认 30，到点自动停）
#   RESTORE_LAUNCHER                 结束后是否恢复桌面（默认 1）
#
# 日志：/var/log/vision-once.log
# ============================================================================
set -u

SENDER="${1:-/root/stage1_color_v6_send.py}"
LOG=/var/log/vision-once.log
DURATION="${DURATION:-30}"
RESTORE_LAUNCHER="${RESTORE_LAUNCHER:-1}"

if [ ! -f "$SENDER" ]; then
    echo "❌ 脚本不存在: $SENDER" >&2
    exit 1
fi

echo "=== run_vision_once $(date '+%F %T') ===" | tee -a "$LOG"
echo "  SENDER=$SENDER" | tee -a "$LOG"
echo "  FRAME_W=${FRAME_W:-<默认>} FRAME_H=${FRAME_H:-<默认>} DETECT_SIZE=${DETECT_SIZE:-<默认>}" | tee -a "$LOG"
echo "  USE_GEOMETRY_SHAPE=${USE_GEOMETRY_SHAPE:-0} DURATION=${DURATION}s" | tee -a "$LOG"

# ── 1) 释放相机：kill 桌面启动器（与 S99vision 的 free_camera 同策略）──
echo "[1/4] 释放相机（kill launcher）..." | tee -a "$LOG"
for round in 1 2; do
    for pat in launcher_daemon launcher benchmark; do
        for p in $(ps | grep "$pat" | grep -v grep | awk '{print $1}'); do
            echo "    kill $pat pid=$p" | tee -a "$LOG"
            kill "$p" 2>/dev/null
        done
    done
    sleep 2
done

# ── 2) 确认没有别的视觉程序占着 ──────────────────────────────────────────
echo "[2/4] 检查残留视觉进程..." | tee -a "$LOG"
for p in $(ps | grep '[s]tage1_color_v6_send' | awk '{print $1}'); do
    echo "    kill 残留 sender pid=$p" | tee -a "$LOG"
    kill "$p" 2>/dev/null
done
sleep 1

# ── 3) 跑视觉（限时）─────────────────────────────────────────────────────
echo "[3/4] 启动视觉（${DURATION}s 后自动停）..." | tee -a "$LOG"
T0=$(date +%s)
# ⚠️ MaixCAM 的 busybox **没有 timeout 命令**（实测 exit 127）。
#    不能用 `timeout N cmd`；改成后台跑 + sleep + kill。
python3 "$SENDER" >> "$LOG" 2>&1 &
SENDER_PID=$!
echo "    sender pid=$SENDER_PID" | tee -a "$LOG"
sleep "$DURATION"
if kill -0 "$SENDER_PID" 2>/dev/null; then
    echo "    到时，停止 sender" | tee -a "$LOG"
    kill "$SENDER_PID" 2>/dev/null
    sleep 1
    kill -9 "$SENDER_PID" 2>/dev/null || true
    RC=0            # 正常到时停止，不算失败
else
    wait "$SENDER_PID"
    RC=$?
    echo "    sender 自行退出，退出码=$RC" | tee -a "$LOG"
fi
T1=$(date +%s)
echo "    退出码=$RC  实跑 $((T1 - T0))s" | tee -a "$LOG"
if [ "$RC" -ne 0 ]; then
    echo "    ⚠️ 非零退出，最后 20 行日志：" | tee -a "$LOG"
    tail -n 20 "$LOG" | sed 's/^/      /' | tee -a "$LOG"
fi

# ── 4) 恢复桌面（把相机还回去）─────────────────────────────────────────────
if [ "$RESTORE_LAUNCHER" = "1" ]; then
    echo "[4/4] 恢复桌面启动器..." | tee -a "$LOG"
    # MaixPy 的 launcher 由 init 拉起；直接重启相关服务
    if [ -x /etc/init.d/S99launcher ]; then
        /etc/init.d/S99launcher start >> "$LOG" 2>&1 || true
    else
        # 兜底：后台拉起 launcher（存在则用）
        if [ -x /maixapp/apps/launcher/launcher_daemon ]; then
            /maixapp/apps/launcher/launcher_daemon >> "$LOG" 2>&1 &
        fi
    fi
else
    echo "[4/4] 按 RESTORE_LAUNCHER=0 跳过恢复（相机将继续空闲）" | tee -a "$LOG"
fi

echo "=== 完成。日志尾部： ===" | tee -a "$LOG"
tail -n 25 "$LOG"
