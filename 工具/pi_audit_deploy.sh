#!/bin/bash
# 枚举树莓派上所有 electrical_control 副本及其签名，判定运行时真正的加载来源
echo "=== 所有 electrical_control/__init__.py ==="
sudo find /home/pi /opt /usr/local/lib /usr/lib -type f \
  -path '*/electrical_control/__init__.py' 2>/dev/null

echo
echo "=== 每个 display_hdmi.py 的签名 ==="
for f in $(sudo find /home/pi /opt -type f -name 'display_hdmi.py' \
             -path '*electrical_control*' 2>/dev/null); do
  b=$(stat -c%s "$f"); l=$(wc -l < "$f")
  t=$(grep -c 'TwoStageDisplay' "$f"); r=$(grep -c 'Image\.Resampling\.LANCZOS' "$f")
  printf '%s\n    bytes=%s lines=%s TwoStage=%s DirectResampling=%s\n' "$f" "$b" "$l" "$t" "$r"
done

echo
echo "=== run_chain.py 副本 ==="
sudo find /home/pi /opt -name 'run_chain.py' 2>/dev/null

echo
echo "=== slots=True 残留（Python 3.9 不兼容）==="
sudo grep -rlE '@dataclass.*slots[[:space:]]*=' /home/pi /opt 2>/dev/null | head -20

echo
echo "=== 相关 systemd 服务 ==="
systemctl list-units --type=service --all 2>/dev/null | grep -iE 'ec|chain|sort' | head

echo
echo "=== 正在跑的 python 进程 ==="
ps -eo pid,user,args | grep -E '[r]un_chain|[e]lectrical_control' | head

echo
echo "=== 树莓派 python / Pillow ==="
/usr/bin/python3 -c 'import sys, PIL, serial; print(sys.version); print("Pillow", PIL.__version__); print("pyserial", serial.__version__)' 2>&1
