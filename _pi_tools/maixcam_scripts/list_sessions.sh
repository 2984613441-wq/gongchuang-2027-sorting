#!/bin/sh
# 列出 MaixCAM 上所有采集 session 及帧数，并给出最新 session 的文件清单
echo "=== 所有 session ==="
for d in /root/dataset_tilt30/*/; do
    [ -d "$d" ] || continue
    n=$(ls "$d"*.jpg 2>/dev/null | wc -l)
    echo "  $(basename "$d") : $n 张"
done

echo
echo "=== 最新 session ==="
NEW=$(ls -dt /root/dataset_tilt30/*/ 2>/dev/null | head -1)
if [ -z "$NEW" ]; then
    echo "  没有 session"
    exit 0
fi
echo "  $NEW"
TOTAL=$(ls "$NEW"*.jpg 2>/dev/null | wc -l)
echo "  帧数: $TOTAL"

echo
echo "=== 前 3 个文件 ==="
ls -t "$NEW"*.jpg 2>/dev/null | head -3 | while read f; do
    sz=$(wc -c < "$f")
    echo "    $sz  $f"
done

echo
echo "=== 磁盘 ==="
df -h /root | tail -1
