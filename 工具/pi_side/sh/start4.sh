#!/bin/bash
echo "=== 0. 清理 ==="
pgrep -af "deploy/run_chain.py" && { pkill -f "deploy/run_chain.py"; sleep 3; } || echo "(链未运行)"
pgrep -af "deploy/run_chain.py" || echo "确认已停"
sudo fuser /dev/serial0 2>&1 || echo "(串口空闲)"
echo ""
echo "=== 1. 板子状态（只读）==="
python3 - <<'PYEOF'
import serial, time
s = serial.Serial("/dev/serial0", 115200, timeout=0.5); time.sleep(0.3)
def send(c, w=0.5):
    s.reset_input_buffer(); s.write((c+"\r\n").encode("ascii")); time.sleep(w)
    return s.read(3000).decode("ascii","replace").strip()
p=""
for i in range(6):
    p = send("PING", 0.4)
    if p: break
    time.sleep(0.15)
print("PING ->", p.splitlines()[0] if p else "(无应答)")
print("AXIS ->", (send("AXIS",0.6).splitlines() or ["(无)"])[0])
ln = (send("STATUS",0.6).splitlines() or [""])[0]
print(" ".join(t for t in ln.split() if t.startswith(("STEP_","APP_STATE"))))
s.close()
PYEOF
echo ""
echo "=== 2. 起链（round-id R3 / task-id 1 / 夹取策略 order / 屏幕 fb0）==="
cd /home/pi/电控
export PYTHONPATH=/home/pi/电控/src
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

echo HOME | setsid nohup python3 deploy/run_chain.py \
  --port /dev/serial0 --image-dir /home/pi/images \
  --names-file /home/pi/电控/deploy/names.json \
  --frame-output fb0 \
  --round-id R3 --round-task-id 1 \
  --pick-strategy order \
  --start-round -v > /home/pi/logs/round3.log 2>&1 &
sleep 15
echo "--- 进程 ---"
pgrep -af "deploy/run_chain.py" || echo "(未启动!)"
echo "--- 日志尾部 18 行 ---"
tail -n 18 /home/pi/logs/round3.log