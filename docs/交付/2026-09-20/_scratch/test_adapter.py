import sys
sys.path.insert(0, 'src')
from electrical_control.protocol.item_context import ItemTaskPayload
from electrical_control.pick_strategy.chain_adapter import payload_orderer_from_ini

orderer = payload_orderer_from_ini('deploy/pick_strategy.ini')
print("排序器构造:", "OK" if orderer else "None(未启用)")
if orderer is None:
    sys.exit(1)

# 装置坐标 = pick/10 - ToolOffset(-120.5,-43.5) = pick/10 + 120.5 / +43.5
# 目标：三件装置 y 分别 = 0 / 30 / 55（无壁边在 y_max=62.5 那侧）
def P(seq, cls, dev_y):
    return ItemTaskPayload(
        target_seq=seq, class_id=cls, image_id=cls,
        x_position=0, y_position=0, grip_angle=0xFF,
        pick_x_position=-1205,                 # 装置 x = 0
        pick_y_position=int((dev_y - 43.5) * 10),
    )

items = (P(1, 1, 0.0), P(2, 2, 55.0), P(3, 3, 30.0))
print("输入顺序 target_seq:", [p.target_seq for p in items])
out = orderer(items)
print("策略排序后     :", [p.target_seq for p in out])
print("件数不变:", len(out) == len(items))
print("期望：55 那件(=seq2)排最前 →", "✅ 通过" if out[0].target_seq == 2 else "❌ 不符")

# 单件必须原样返回
one = (P(9, 9, 10.0),)
print("单件原样返回:", orderer(one) == one)

# 无抓取点的件必须留在队尾且不丢
def Q(seq, cls):
    return ItemTaskPayload(target_seq=seq, class_id=cls, image_id=cls,
                           x_position=0, y_position=0, grip_angle=0xFF,
                           pick_x_position=None, pick_y_position=None)
mixed = (P(1, 1, 0.0), Q(7, 7), P(2, 2, 55.0))
o2 = orderer(mixed)
print("含缺抓取点件 → 输出 seq:", [p.target_seq for p in o2], "件数不变:", len(o2) == 3)
print("缺抓取点件在队尾:", o2[-1].target_seq == 7)
