#!/bin/sh
# MaixCAM 端一键排查（2026-09-22 DSH 出）
#
# 用法（在相机上，或从你的电脑 ssh 进去跑）：
#     sh /root/cam_diag.sh              # 默认查 172.20.10.8:8765
#     sh /root/cam_diag.sh 192.168.1.5  # 指定树莓派 IP
#
# 判读（重要）：
#   · 第 1 节 stage1_color 只应有 **1 个**；>1 ⇒ 会抢摄像头/内存 ⇒ OOM + SIGSEGV
#     （监督器已拉起一个时，别再手动跑第二个；手动测要先 /etc/init.d/S99vision stop）
#   · 第 2 节 starting sender 若 >1 且在涨 / OOM>0 / SIGSEGV>0 ⇒ 在崩溃循环 ⇒ 查"谁占着摄像头"
#   · 第 6 节 ConnectionRefused ⇒ 网络通、只是对面没人监听；timed out ⇒ 网络或路由不通

PI="${1:-172.20.10.8}"

echo "=== 1) 相关进程（stage1 只应有 1 个）==="
ps | grep -E 'launcher_daemon|benchmark/main|vision_supervisor|stage1_color' | grep -v grep

echo "=== 2) 日志计数（涨 / >0 ⇒ 异常）==="
for pat in "starting sender" "Out of memory" "SIGSEGV" "camera open failed"; do
    n=$(grep -c "$pat" /var/log/vision-sender.log 2>/dev/null)
    [ -z "$n" ] && n=0
    printf '  %-18s = %s\n' "$pat" "$n"
done

echo "=== 3) 日志尾部 8 行 ==="
tail -8 /var/log/vision-sender.log 2>/dev/null

echo "=== 4) 内存（MemAvailable 太低 ⇒ OOM 的根源）==="
head -3 /proc/meminfo

echo "=== 5) 摄像头设备 ==="
ls -l /dev/video* 2>/dev/null || echo "  （无 /dev/video*）"

echo "=== 6) 网络 ==="
ip -4 addr show 2>/dev/null | grep 'inet ' | head -3
echo -n "  到 ${PI}:8765 的 TCP 连接："
python3 - "$PI" <<'PY'
import socket, sys
h = sys.argv[1]
s = socket.socket(); s.settimeout(4)
try:
    s.connect((h, 8765)); print("连上了（对面有监听 ✓）")
except Exception as e:
    print("%s: %s" % (type(e).__name__, e))
    print("  判读：ConnectionRefused ⇒ 网络通、只是没人监听 ✓；timeout ⇒ 网络/路由不通 ✗")
PY

echo "=== 7) 自启配置 ==="
echo -n "  auto_start.txt = "; cat /maixapp/auto_start.txt
echo -n "  /etc/init.d/S99vision : "; ls -l /etc/init.d/S99vision 2>/dev/null || echo "无"
echo -n "  /root/vision_supervisor.sh : "; ls -l /root/vision_supervisor.sh 2>/dev/null || echo "无"
echo -n "  rc.local 是否挂了监督器 : "; grep -c vision_supervisor /etc/rc.local 2>/dev/null
echo "=== 完 ==="
