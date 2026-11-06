"""探针：调试投票逻辑"""
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

print("=== 探针1：majority 模式 2帧class_id=2 ===")
src = SocketVisionSource(
    round_id=1, task_id=1,
    image_id_for_class=dummy_image_id,
    drop_point_for_box=dummy_drop_point,
    class_vote_enabled=True,
    class_vote_frames=3,
    class_vote_quorum=2,
    class_vote_mode="majority",
)

batch1 = _batch(1, 2)
ctx1 = src._expand(batch1)
print(f"第1帧：ctx={len(ctx1)}, history={src._vote_history}, seen={src._vote_seen}")

batch2 = _batch(1, 2)  # 同一 seq，同一位置
ctx2 = src._expand(batch2)
print(f"第2帧：ctx={len(ctx2)}, history={src._vote_history}, seen={src._vote_seen}")
print(f"stats={src.vote_stats()}")

print("\n=== 探针2：超时测试（max_wait=3） ===")
src2 = SocketVisionSource(
    round_id=1, task_id=1,
    image_id_for_class=dummy_image_id,
    drop_point_for_box=dummy_drop_point,
    class_vote_enabled=True,
    class_vote_frames=3,
    class_vote_quorum=2,
    class_vote_max_wait_frames=3,
    class_vote_mode="majority",
)

for i, cid in enumerate([2, 3, 4], 1):
    batch = _batch(1, cid)
    ctx = src2._expand(batch)
    print(f"第{i}帧 class_id={cid}: ctx={len(ctx)}, seen={src2._vote_seen}, timeout={src2.vote_stats()['timeout']}")
