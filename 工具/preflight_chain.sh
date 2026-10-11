#!/bin/bash
# 只读预检：整链运行前置确认。**绝不打开 /dev/serial0**（只查谁占着它）。
echo "=== host ==="; hostname; date '+%F %T'; whoami
echo "=== 1. 链路进程 ==="
pgrep -af 'run_chai[n].py' || echo "  NO chain running (good)"
echo "=== 2. 谁占着 /dev/serial0 ==="
ls -l /dev/serial0 2>&1
if command -v fuser >/dev/null 2>&1; then fuser -v /dev/serial0 2>&1 || echo "  fuser: 无进程占用"; fi
if command -v lsof >/dev/null 2>&1; then lsof /dev/serial0 2>/dev/null || echo "  lsof: 无进程占用"; fi
echo "=== 3. lightdm（应为 inactive/stopped）==="
systemctl is-active lightdm 2>&1
echo
echo "=== 4. 两份配置：Pi 实读 /home/pi/sorting_config.ini（见 pi_start_chain.sh:8）==="
for INI in /home/pi/sorting_config.ini /home/pi/电控/deploy/sorting_config.ini; do
  echo "--- $INI ---"
  if [ -f "$INI" ]; then
    ls -l "$INI"; md5sum "$INI"
    grep -nE '^(reach_limit_mm|travel_per_leg_mm|maixcam_host|maixcam_port|stm32_port|stm32_baudrate) ?=' "$INI" 2>&1
    echo "  [DropPoints] 实际值:"
    sed -n '/^\[DropPoints\]/,/^\[/p' "$INI" | grep -E '^[1-6] ?=' | sed 's/^/    /'
    echo "  [PickPoint] 实际值:"
    sed -n '/^\[PickPoint\]/,$p' "$INI" | grep -E '^(x|y) ?=' | sed 's/^/    /'
  else
    echo "  不存在"
  fi
done
echo "=== 5. 两份是否一致 ==="
if [ -f /home/pi/sorting_config.ini ] && [ -f /home/pi/电控/deploy/sorting_config.ini ]; then
  diff -q /home/pi/sorting_config.ini /home/pi/电控/deploy/sorting_config.ini && echo "  完全相同" || echo "  *** 不同！（Pi 读上面那份）***"
fi
echo
echo "=== 6. 日志 ==="
for L in /tmp/chain.log /tmp/chain_outer.log; do
  echo "--- $L ---"; ls -l "$L" 2>&1; tail -15 "$L" 2>&1
done
echo "=== 7. 本机网络 ==="
ip -4 addr show 2>/dev/null | grep -E 'inet '
echo "=== 8. MaixCAM 可达性 ==="
for ip in 172.20.10.2 172.20.10.9; do
  if ping -c1 -W1 "$ip" >/dev/null 2>&1; then echo "  $ip OK"; else echo "  $ip FAIL"; fi
done
echo "=== DONE ==="
