#!/bin/bash
cd /home/pi

# ── 用法 ─────────────────────────────────────────────────────────────────
#   bash p_go8.sh          起轮：视觉快照 → HOME 门禁 → **送滑台到 PARK** → 起链
#   bash p_go8.sh back     收轮后回 HOME（PARK → HOME）
# ── 2026-09-22 停靠位开关 ────────────────────────────────────────────────
# 固件（源码已改、【待烧】）把【每件程序的起止位】从 HOME 改成 PARK=(-95.0,+47.5)
# （第二落点）—— 夹爪停在那儿在相机画面之外，不会再被判成"黑色件"。
# ⚠️ 上电原点 HOME(-95.0,-97.5) 【没动】；要送滑台过去这件事由本脚本承担。
# 🔴 AVOIDANCE=0 只有在【固件也一起回退到 HOME 版】时才安全。单独关掉它 ⇒
#    固件按"起点=PARK"发增量，而滑台还在 HOME ⇒ 第一段整体错 145mm ⇒ 顶死堵转。
AVOIDANCE=1

if [ "${1:-}" = "back" ]; then
  # 收轮后回 HOME（PARK → HOME）：-145.0mm ⇒ 负位移必须显式 --allow-neg。
  echo "=== 收轮回 HOME：PARK(-95.0,+47.5) → HOME(-95.0,-97.5) = -145.0mm ==="
  python3 /home/pi/pi_goto.py 0 -145 --allow-neg || {
    echo ">>> 回 HOME 失败；滑台可能仍停在 PARK。下一轮起链前必须人工确认在 HOME。"
    exit 1
  }
  echo ">>> 已回 HOME。"
  exit 0
fi

echo "=== 视觉快照 ==="
# ⚠️ 这一步跑在门禁【之前】⇒ 此刻滑台还在 HOME，夹爪在相机画面里，
#    可能被判成"黑色件"而把「可见件数」撑大。它只是"台上有没有件"的粗筛；
#    **链自己的那一次快照才是权威的** —— 那时滑台已经停在 PARK（画面里没有夹爪）。
OUT=$(timeout 14 python3 p_look2.py 2>/dev/null)
echo "$OUT"
N=$(echo "$OUT" | grep -c 'box_id=')
echo "可见件数 = $N"
if [ "$N" -eq 0 ]; then
  echo ">>> 台上没有件，先不起链。"
  exit 0
fi
echo
echo "=== 起链 ==="

# ── HOME 门禁（2026-09-21）────────────────────────────────────────────────
# 板子无编码器、不寻零 ⇒ 软件**无法**判断 XY 是否真的在 HOME；起点错了会让
# 第一段增量运动整体偏移，可能顶死堵转并使开环坐标永久失准。
# 新版 run_chain.py 的 --start-round 要求 stdin 精确输入 HOME，非交互一律拒绝；
# 而 nohup 会把 stdin 变成 /dev/null ⇒ 旧写法（nohup ... --start-round &）直接拒启动。
# 这里由操作员在终端确认一次，再把 HOME 喂给链 —— 人确认这一步**没有被削弱**。
# 🔴 2026-09-22：期望起点【仍然是】X/Y 负方向最里角 —— **上电原点 HOME 没有改**。
#   同日曾试过把 HOME 迁到 Y 正端停车位 +85.5：独立审核判弊大于利，**已回退**
#   （记录见 App/Inc/ec_motion_plan.h:195-207）⇒ 下面这行提示不用改，别按 +85.5 推。
#   真正改掉的是【每件程序的起止位】：leg1 起点 / leg3 终点 由 HOME 改成
#   PARK = (-95.0, +47.5)（第二落点）⇒ 滑台必须先被送到 PARK（见本脚本门禁之后那条）。
echo "!!! 期望起点（当前固件）：X = -95.0mm, Y = -97.5mm —— X/Y 都推到【负方向最里角】顶住 !!!"
echo "!!! ⚠️ 固件的【起止位】已改为 PARK(-95.0,+47.5)，由本脚本自动送过去；别手动改期望起点 !!!"
printf '确认滑台已在 HOME 后输入 HOME（其他输入均退出）：'
read -r ANS
if [ "$ANS" != "HOME" ]; then
  echo ">>> 未确认 HOME，拒绝起链。"
  exit 1
fi

# ── 送滑台到停靠位 PARK（2026-09-22）─────────────────────────────────────
# 门禁刚由操作员确认"滑台在 HOME(-95.0,-97.5)" ⇒ 现在按增量把它送到 PARK：
#   Y: -97.5 → +47.5 = +145.0mm = 11600 步 ｜ X 不动（PARK_X = HOME_X = -950）
# ⚠️ pi_goto.py 的参数是 <dx_mm> <dy_mm>（**X 在前**）⇒ 必须是 "0 145"，
#    写成 "145 0" 会去推 X 正方向 = 完全错误的轴。
# ⚠️ 它只发 MOVE、**不经状态机** ⇒ 首次实跑必须有人在场、手放急停旁。
if [ "$AVOIDANCE" = "1" ]; then
  echo "=== 送滑台 HOME → PARK（+145.0mm / 11600 步）==="
  python3 /home/pi/pi_goto.py 0 145 || {
    echo ">>> 送到停靠位失败，拒绝起链。"
    exit 1
  }
  echo ">>> 已到停靠位 (-95.0, +47.5)，相机画面里应看不到夹爪。"
  echo ">>> ⚠️ 必须目视确认：上面输出里 STEP_RESULT=1，且滑台朝 +Y 走了约 145mm。"
  echo ">>>    若不是 1（2=超时 3=安全停），立刻 Ctrl-C 并停链 —— 位置不对会让 leg1 整体偏移。"
else
  echo "!!! AVOIDANCE=0：跳过 HOME→PARK。"
  echo "!!! ⚠️ 仅当【固件也已回退到 HOME 版】时才安全；否则 leg1 假定起点在 PARK，"
  echo "!!!    第一段整体错 145mm ⇒ 顶死堵转。"
fi

mkdir -p /home/pi/logs
cd /home/pi/电控
export PYTHONPATH=/home/pi/电控/src
LOG=/home/pi/logs/round-R8-$(date +%H%M%S).log
echo "$LOG" > /home/pi/logs/R8-latest.txt
echo HOME | nohup python3 deploy/run_chain.py \
  --port /dev/serial0 \
  --image-dir /home/pi/images \
  --names-file /home/pi/电控/deploy/names.json \
  --frame-output fb0 \
  --font /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
  --round-id R8 --round-task-id 1 \
  --pick-strategy order --start-round -v \
  > "$LOG" 2>&1 &
echo "PID=$!  日志=$LOG"
sleep 30
echo
echo "=== 前 30 秒（去刷屏）==="
grep -vE 'NACK_SINGLE_TASK_ONLY|越界：pixel_to_device' "$LOG" | head -40

echo
echo "=== 收轮后回 HOME（必做）==="
echo "  轮次结束后执行：  bash /home/pi/p_go8.sh back"
echo "  固件每件结束会自己停在 PARK(-95.0,+47.5)；而上面那条 +145mm 是【从 HOME 量起】的"
echo "  ⇒ 不收轮回 HOME 就直接再跑本脚本 ⇒ 会从 PARK 再走 +145mm ⇒ 顶死堵转。"
echo "  例外：若本轮之后会【断电并手推到最里角】重启，则不必跑 back（门禁那步已经把它归零）。"