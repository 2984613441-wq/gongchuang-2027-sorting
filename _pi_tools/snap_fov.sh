#!/bin/sh
# 在 MaixCAM 上抓一张 FOV 照片（先释放相机）
set -u
echo "--- 释放相机 ---"
for pat in launcher_daemon launcher benchmark; do
    for pid in $(ps | grep "$pat" | grep -v grep | awk '{print $1}'); do
        echo "  kill $pat pid=$pid"
        kill "$pid" 2>/dev/null
    done
done
sleep 2

echo "--- 抓图 ---"
NO_DISP=1 WARMUP_S=2.5 python3 /root/snap.py /root/snap_fov.jpg 1280 720 2>&1 \
    | grep -aE "saved|resolution|camera|预热" | head -n 6

echo "--- 结果 ---"
ls -la /root/snap_fov.jpg 2>/dev/null || echo "  文件不存在"
