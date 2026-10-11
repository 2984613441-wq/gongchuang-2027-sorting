#!/usr/bin/env python3
"""run_chain 三处 fail-closed 加固的主机自检（无需硬件、无需 pytest）。

用法（工作区根目录，或任意目录）：:

    py -3 电控/deploy/selftest_failclosed.py

脚本自己把 `电控/deploy` 与 `电控/src` 塞进 sys.path，不需要设 PYTHONPATH。
每项都是"改前会怎样 / 改后会怎样"的对照断言；任何一项失败 → 退出码 1。

覆盖：
  ① --frame-output auto/fb0 在生产模式下 fail-fast（不再静默降级为 none）
  ② 未知 box_id 只丢那一件，不再把整条链带走（KeyError → 跳过）
  ③ motion_config.json 能加载（台账 E-14）
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))            # run_chain.py
sys.path.insert(0, str(_HERE.parent / "src"))  # electrical_control

import run_chain  # noqa: E402
from electrical_control.rpi.vision_ingest import (  # noqa: E402
    BatchTargets,
    VisionTarget,
    build_item_task_queue,
)
from electrical_control.scheduler.motion_config import (  # noqa: E402
    MotionConfig,
    load_motion_config,
)

CHECKS = 0


def ok(label: str) -> None:
    global CHECKS
    CHECKS += 1
    print(f"  ✅ {label}")


def expect_systemexit(label: str, fn) -> str:
    try:
        fn()
    except SystemExit as exc:
        ok(f"{label} → SystemExit: {str(exc).splitlines()[0]}")
        return str(exc)
    raise AssertionError(f"{label} 应当 SystemExit，实际没有")


def new_logger(sink: list) -> logging.Logger:
    logger = logging.getLogger(f"selftest.{len(sink)}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    class Capture(logging.Handler):
        def emit(self, record):
            sink.append(record)

    logger.addHandler(Capture())
    return logger


print("① --frame-output：生产模式不静默降级")
silent = new_logger([])
expect_systemexit(
    '生产模式 --frame-output auto',
    lambda: run_chain.build_frame_output("auto", "frames", silent, demo=False),
)
assert run_chain.build_frame_output("auto", "frames", silent, demo=True) is not None
ok("--fake-link + auto 仍可用（主机测试路径保留）")

expect_systemexit(
    "生产模式 --frame-output fb0（本机无 /dev/fb0）",
    lambda: run_chain.build_frame_output("fb0", "frames", silent, demo=False),
)
warn_sink: list = []
run_chain.build_frame_output("none", "frames", new_logger(warn_sink), demo=False)
assert any(r.levelno == logging.WARNING for r in warn_sink), "生产模式用 none 必须告警"
ok("生产模式 --frame-output none → WARNING（不再是无声全黑）")

print("② 未知 box_id：丢一件，不丢整条链")
drop_points = {1: (100, 200), 2: (300, 400)}
batch = BatchTargets(
    task_id=7,
    targets=(
        VisionTarget(1, 2, box_id=1),   # 已知
        VisionTarget(2, 4, box_id=99),  # 未知 → 拒识
        VisionTarget(3, 5, box_id=-1),  # 未知（负数，绝不可能在表里）
        VisionTarget(4, 6, box_id=2),   # 已知
    ),
)
image_id_for_class = run_chain._identity_image_id

# 改前：直接传 __getitem__ → KeyError 冒到 run() 兜底，整条链退出
try:
    build_item_task_queue(
        batch,
        image_id_for_class=image_id_for_class,
        drop_point_for_box=drop_points.__getitem__,
    )
except KeyError as exc:
    ok(f"改前行为复现：drop_points.__getitem__ → KeyError({exc}) 冒泡出 build_item_task_queue")
else:
    raise AssertionError("改前行为应当抛 KeyError")

# 改后：未知 box_id 记 warning 并跳过，其余照发
probe_sink: list = []
probe = run_chain.make_drop_point_lookup(drop_points, new_logger(probe_sink))
assert probe(1) == (100, 200)
assert probe(99) is None
assert len(probe_sink) == 1 and probe_sink[0].levelno == logging.WARNING
ok(f"未命中时返回 None 并记 WARNING：{probe_sink[0].getMessage()}")

lookup_sink: list = []
queue = build_item_task_queue(
    batch,
    image_id_for_class=image_id_for_class,
    drop_point_for_box=run_chain.make_drop_point_lookup(drop_points, new_logger(lookup_sink)),
)
assert [q.target_seq for q in queue] == [1, 4], [q.target_seq for q in queue]
assert [q.x_position for q in queue] == [100, 300]
assert all(q.grip_angle == 0xFF for q in queue)
warns = [r for r in lookup_sink if r.levelno == logging.WARNING]
assert len(warns) == 2, [r.getMessage() for r in lookup_sink]
assert "99" in warns[0].getMessage() and "-1" in warns[1].getMessage()
ok("改后行为：2 件未知被跳过（target_seq 2/3），2 件已知照发，各记 1 条 WARNING")
ok("已知 box_id 坐标语义未变：(100,200) / (300,400)，grip_angle=0xFF")

# 真实链路那一跳：SocketVisionSource 里 box_id = class_id（占位），而
# ACTIVE_CLASS_IDS 含 0 —— box_id=0 永远不在 [DropPoints]（只收 1..6），
# 所以"未知 box_id"不是假想，是每轮只要出现 class_id=0 就必现。
# 改前：next_if_permitted() → _expand() → KeyError(0) → 冒到 run() 兜底，整条链退出。
from electrical_control.rpi.socket_vision_source import SocketVisionSource  # noqa: E402

wire = bytes(
    [2, 0x00, 0x07]                      # count=2, task_id=7
    + [2, 50, 0x01, 0x00, 0x01, 0x00, 0xFF]   # class_id=2 → box_id=2（已知）
    + [0, 50, 0x00, 0x00, 0x00, 0x00, 0xFF]   # class_id=0 → box_id=0（永不在表里）
)
source = SocketVisionSource(
    round_id="r1", task_id=7, image_id_for_class=image_id_for_class,
    drop_point_for_box=run_chain.make_drop_point_lookup(drop_points, new_logger([])),
)
source.set_permitted(True)
source.ingest(wire)
ctx = source.next_if_permitted()
assert ctx is not None and ctx.payload.target_seq == 1, ctx
assert source.next_if_permitted() is None, "box_id=0 的件必须被丢掉"
assert ctx.payload.x_position == 300 and ctx.payload.y_position == 400
ok("真实链路 SocketVisionSource：class_id=0（box_id=0）被拒识，第 2 件照发")

print("③ motion_config.json（台账 E-14）")
json_path = _HERE.parent / "motion_config.json"
cfg = load_motion_config(str(json_path))
assert isinstance(cfg, MotionConfig), type(cfg)
assert cfg.motion_speed_mm_per_s == 50.0 and cfg.pick_action_time_s == 2.0
ok(f"加载成功：{json_path.name} → MotionConfig({cfg.motion_speed_mm_per_s}, "
   f"{cfg.pick_action_time_s}, {cfg.z_axis_time_s})，4 个 _ 元数据键被过滤")

with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                 encoding="utf-8") as fh:
    json.dump({"motion_speed_mm_s": 1.0}, fh)  # 真·拼写错误
typo_path = fh.name
try:
    load_motion_config(typo_path)
except TypeError:
    ok("参数名写错仍然响亮报错（TypeError）——没有静默退回未标定默认值")
else:
    raise AssertionError("拼错的参数名应当抛 TypeError")
finally:
    os.unlink(typo_path)

print(f"\n全部通过：{CHECKS} 项 ✅")
sys.exit(0)
