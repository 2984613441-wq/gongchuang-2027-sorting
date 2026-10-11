#!/bin/bash
# 把整个 electrical_control 包同步到树莓派（同版本、清缓存、再验证）
set -u
SRC=/home/pi/_stage/electrical_control
DST=/home/pi/电控/src/electrical_control
echo "=== 同步包（本地 → 树莓派）==="
cp -r "$SRC/." "$DST/" || exit 1
echo "已同步。关键文件："
for f in "$DST/rpi/socket_vision_source.py" "$DST/rpi/vision_ingest.py" "$DST/rpi/pixel_to_device.py" "$DST/rpi/display_hdmi.py"; do
    [ -f "$f" ] && echo "  $(wc -c < "$f") B  $f"
done
grep -c "grasp_point_for_target" "$DST/rpi/socket_vision_source.py" | sed 's/^/  socket_vision_source 里 grasp_point_for_target 出现次数: /'
echo
echo "=== 清 __pycache__ ==="
find /home/pi/电控 -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
echo done
echo
echo "=== 端到端验证 ==="
cd /home/pi/电控 || exit 1
PYTHONPATH=src:/home/pi/电控/deploy python3 - <<'PY'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, "deploy")
import run_chain
from electrical_control.protocol import encode_item_task_payload

CFG = run_chain.DEFAULT_CONFIG_PATH
pick = run_chain.load_fixed_pick_point(CFG)
drops = run_chain.load_drop_points(CFG)
print("PickPoint =", pick, " DropPoints =", drops)
source = run_chain.build_socket_source(
    round_id="round-1", round_task_id=1,
    drop_point_for_box=lambda box: drops.get(box),
    fixed_pick_point=pick,
)
source.set_permitted(True)
source.ingest(bytes.fromhex("010001035a00b40078ff"))   # box_id=3
task = source.next_if_permitted()
if task is None:
    print("FAIL: 没产出任务"); raise SystemExit(1)
p = task.payload
print("target_seq =", p.target_seq, " class_id =", p.class_id, " image_id =", p.image_id)
print("落料点     =", (p.x_position, p.y_position))
print("抓取点     =", (p.pick_x_position, p.pick_y_position))
print("可序列化   = OK，%d 字节" % len(encode_item_task_payload(p)))
print("再取一次   =", source.next_if_permitted(), "（应为 None）")
PY
