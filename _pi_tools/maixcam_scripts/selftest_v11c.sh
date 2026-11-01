#!/bin/sh
# 自测：用 python3 -u（无缓冲），否则被 kill 时 print 的缓冲区会丢失

killall launcher_daemon 2>/dev/null
sleep 1
cd /root || exit 1
rm -f /tmp/v11_test3.log
python3 -u yolo_v11_cn_view.py > /tmp/v11_test3.log 2>&1 &
PID=$!
sleep 15
kill "$PID" 2>/dev/null
sleep 1
kill -9 "$PID" 2>/dev/null
sleep 1

echo "=== 全部行数 ==="
wc -l < /tmp/v11_test3.log 2>/dev/null

echo
echo "=== 脚本自身输出（过滤 sensor/ISP 噪声）==="
grep -vE 'parse_|SAMPLE_|cvi_bin|gerritId|commitId|md5:|sensorNum|sensorName|PQ|awb|isp|ISP|ViPipe|WB |Golden|R:[0-9]|Cmodel|device\[|Max Shared|version:|Build at|bm_|load cvimodel|model info|type:|input |mean:|scale:|labels num|Max SharedMem|try release|_mmf|maix multi-media|stSnsrMode|GC4653|===+GC|^\s*$|\*+' /tmp/v11_test3.log | head -50

echo
echo "=== Traceback 检查 ==="
if grep -q 'Traceback' /tmp/v11_test3.log; then
    grep -A5 'Traceback' /tmp/v11_test3.log | head -20
else
    echo "  ✅ 无 Traceback"
fi
