#!/bin/sh
# 监听 GPIO14/15 电平变化 N 秒，只在数值变化时打印（带完整功能/上下拉信息）。
# 用途：让操作者拔插杜邦线，精确捕捉「外部负载拉低 RX」的瞬间。
# 只读，不向任何设备写字节。
N="${1:-200}"
i=0
LAST="__init__"
echo "start $(date +%H:%M:%S) window=${N}s"
while [ "$i" -lt "$N" ]; do
    RAW=$(raspi-gpio get 14,15 2>/dev/null)
    CUR=$(printf '%s\n' "$RAW" | sed 's/.*level=/L/; s/ fsel.*//' | tr '\n' ',')
    if [ "$CUR" != "$LAST" ]; then
        echo "--- $(date +%H:%M:%S) 变化 ---"
        printf '%s\n' "$RAW"
        LAST="$CUR"
    fi
    i=$((i+1))
    sleep 0.5
done
echo "end $(date +%H:%M:%S) 最终状态:"
raspi-gpio get 14,15
