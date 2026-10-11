#!/bin/bash
# 端到端验证：视觉帧 → 抓取点 → 可序列化的 ITEM_TASK（不碰串口、不碰 STM32）
cd /home/pi/电控 || exit 1
PYTHONPATH=src:/home/pi/电控/deploy python3 - <<'PY'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, "deploy")
import run_chain
from electrical_control.rpi.vision_ingest import parse_batch_targets
from electrical_control.protocol import encode_item_task_payload

CFG = run_chain.DEFAULT_CONFIG_PATH
pick = run_chain.load_fixed_pick_point(CFG)
drops = run_chain.load_drop_points(CFG)
source = run_chain.build_socket_source(
    round_id="round-1", round_task_id=1,
    drop_point_for_box=lambda box: drops.get(box),
    fixed_pick_point=pick,
)
source.set_permitted(True)
# box_id=3 的一帧（校赛模式：id 字节就是货格号）
source.ingest(bytes.fromhex("010001035a00b40078ff"))
task = source.next_if_permitted()
if task is None:
    print("FAIL: 没产出任务（抓取点或落点解析失败）")
    raise SystemExit(1)
p = task.payload
print("target_seq =", p.target_seq, " class_id =", p.class_id, " image_id =", p.image_id)
print("落料点     =", (p.x_position, p.y_position))
print("抓取点     =", (p.pick_x_position, p.pick_y_position))
raw = encode_item_task_payload(p)
print("可序列化   = OK，%d 字节" % len(raw))
print("再取一次   =", source.next_if_permitted(), "（应为 None，一帧只取一件）")
PY
