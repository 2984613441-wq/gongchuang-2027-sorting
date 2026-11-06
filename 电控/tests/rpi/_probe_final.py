"""最终探针：演示三个修复效果"""
from electrical_control.rpi import BatchTargets, VisionTarget
from electrical_control.rpi.socket_vision_source import SocketVisionSource


def _batch(seq, cid, px=100, py=100):
    return BatchTargets(
        task_id=1,
        targets=(VisionTarget(seq, cid, confidence=90, pixel_x=px, pixel_y=py, box_id=1),),
    )


def dummy_image_id(cid):
    return 1

def dummy_drop_point(box_id):
    return (100, 100)


print("=" * 70)
print("探针1：交替10帧 unanimous → accepted=0（问题1修复）")
print("=" * 70)
src1 = SocketVisionSource(
    round_id=1, task_id=1,
    image_id_for_class=dummy_image_id,
    drop_point_for_box=dummy_drop_point,
    class_vote_enabled=True,
    class_vote_frames=3,
    class_vote_mode="unanimous",  # 默认模式
)

for i in range(10):
    cid = 2 if i % 2 == 0 else 3
    batch = _batch(1, cid)
    ctx = src1._expand(batch)
    print(f"第{i+1}帧 class_id={cid}: 采纳={len(ctx)}")

stats1 = src1.vote_stats()
print(f"\n[OK] 结果：accepted={stats1['accepted']}（预期=0），rejected={stats1['rejected_no_quorum']}")
assert stats1['accepted'] == 0, "交替类别应全部拒绝"


print("\n" + "=" * 70)
print("探针2：默认参数持续摇摆8帧 → timeout>0（问题2修复）")
print("=" * 70)
src2 = SocketVisionSource(
    round_id=1, task_id=1,
    image_id_for_class=dummy_image_id,
    drop_point_for_box=dummy_drop_point,
    class_vote_enabled=True,
    class_vote_frames=3,
    class_vote_max_wait_frames=6,  # 默认
    class_vote_mode="unanimous",
)

for i in range(8):
    cid = [2, 3, 4][i % 3]
    batch = _batch(1, cid)
    ctx = src2._expand(batch)
    stats = src2.vote_stats()
    print(f"第{i+1}帧 class_id={cid}: timeout={stats['timeout']}, seen={src2._vote_seen}")

stats2 = src2.vote_stats()
print(f"\n[OK] 结果：timeout={stats2['timeout']}（预期>=1）")
assert stats2['timeout'] >= 1, "超过 max_wait=6 应触发超时"


print("\n" + "=" * 70)
print("探针3：换轮后历史清空（问题3修复）")
print("=" * 70)
src3 = SocketVisionSource(
    round_id=1, task_id=1,
    image_id_for_class=dummy_image_id,
    drop_point_for_box=dummy_drop_point,
    class_vote_enabled=True,
    class_vote_frames=3,
    class_vote_mode="unanimous",
)

# 第1轮：2帧 class_id=2
src3._expand(_batch(1, 2))
src3._expand(_batch(1, 2))
print(f"第1轮结束：history={len(src3._vote_history)}, seen={src3._vote_seen}")

# 换轮
src3.set_permitted(False)
src3.set_permitted(True)
print(f"换轮后：history={len(src3._vote_history)}, seen={src3._vote_seen}")

# 第2轮：只1帧
ctx = src3._expand(_batch(1, 2))
print(f"第2轮第1帧：采纳={len(ctx)}（预期=0，历史已清空）")
assert len(ctx) == 0, "换轮后历史应清空"

# 第2轮：再2帧 → 满窗口
src3._expand(_batch(1, 2))
ctx = src3._expand(_batch(1, 2))
print(f"第2轮第3帧：采纳={len(ctx)}（预期=1，新轮3帧满窗口）")
assert len(ctx) == 1, "新轮3帧一致应采纳"

print(f"\n[OK] 结果：换轮清空成功，新轮独立计数正确")

print("\n" + "=" * 70)
print("[SUCCESS] 所有探针通过！")
print("=" * 70)
