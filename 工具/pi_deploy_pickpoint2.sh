#!/bin/bash
# 部署新的 [PickPoint] 并验证
cp /home/pi/_stage/sorting_config.ini /home/pi/sorting_config.ini || exit 1
echo "已部署 /home/pi/sorting_config.ini ($(wc -c < /home/pi/sorting_config.ini) B)"
grep -A1 '^\[PickPoint\]' /home/pi/sorting_config.ini | head -3
grep -E '^[xy] = ' /home/pi/sorting_config.ini
echo "--- 验证解析 ---"
cd /home/pi/电控 || exit 1
PYTHONPATH=src:deploy python3 - <<'PY'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, "deploy")
import run_chain
p = run_chain.load_fixed_pick_point("/home/pi/sorting_config.ini")
print("PickPoint (0.1mm) =", p, " -> mm =", (p[0]/10.0, p[1]/10.0) if p else None)
d = run_chain.load_drop_points("/home/pi/sorting_config.ini")
print("DropPoints =", d)
# 用 1.09 mm/px 反算它会落在哪个像素（人工核对用）
if p:
    px = 144.5 + p[0]/10.0/1.09
    py = 232.0 - p[1]/10.0/1.08   # 装置 Y 越大 → 像素 v 越小
    print("预计像素 = (%.0f, %.0f)  [画面 0~319，应在中间区域]" % (px, py))
PY
