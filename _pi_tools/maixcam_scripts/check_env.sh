#!/bin/sh
# MaixCAM 环境自检 —— 跑 yolo_v4_bench.py 前确认没有东西占着相机
#
# 用法（在 MaixCAM 上）：
#   sh /root/check_env.sh
#
# 或在 PC 上：
#   ssh root@172.20.10.9 "sh /root/check_env.sh"

echo "=============================================================="
echo "  MaixCAM 环境自检"
echo "=============================================================="

echo
echo "=== 1) 占着相机/显示的进程 ==="
FOUND=0
for pat in launcher_daemon maixvision yolo_view main.py; do
    P=$(ps 2>/dev/null | grep -i "$pat" | grep -v grep)
    if [ -n "$P" ]; then
        echo "  ⚠️ $pat:"
        echo "$P" | sed 's/^/      /'
        FOUND=1
    fi
done
if [ "$FOUND" = "0" ]; then
    echo "  ✅ 没有冲突进程"
else
    echo
    echo "  ⇒ 如果跑脚本报「相机打不开」，先执行："
    echo "      killall launcher_daemon"
fi

echo
echo "=== 2) 内存 ==="
free -m 2>/dev/null | head -3 | sed 's/^/  /'

echo
echo "=== 3) 模型文件 ==="
ls -l /root/my_models/yolo11n_6c_v4_448_cv181x.* 2>/dev/null | sed 's/^/  /' \
    || echo "  ❌ 没找到 v4 模型"

echo
echo "=== 4) 测试脚本 ==="
ls -l /root/yolo_v4_bench.py 2>/dev/null | sed 's/^/  /' \
    || echo "  ❌ 没找到 yolo_v4_bench.py"

echo
echo "=== 5) 显示分辨率 ==="
python3 - <<'PYEOF' 2>&1 | grep -E "display|camera|WARN|ERROR" | sed 's/^/  /'
from maix import display
d = display.Display()
print("display %dx%d" % (d.width(), d.height()))
PYEOF

echo
echo "=== 6) 相机可读性（会短暂占用相机）==="
python3 - <<'PYEOF' 2>&1 | grep -E "camera|Frame|ERROR|WARN" | sed 's/^/  /'
from maix import camera, image
c = camera.Camera(1280, 720, image.Format.FMT_RGB888)
f = c.read()
if f is None:
    print("ERROR camera returned None")
else:
    print("camera OK %dx%d" % (f.width(), f.height()))
PYEOF

echo
echo "=============================================================="
echo "  自检结束"
echo "=============================================================="
