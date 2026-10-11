#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 跨语言字节一致性 + 8 字节旧载荷 fail-closed 验证。

用法（在仓库任意位置执行）：
    py -3 电控/stm32_logic/tests/p3_cross_language_check.py

它做三件事，任一不满足即以非 0 退出：
  1. 用 gcc 编译 C 侧向量 CLI（tests/item_task_vector_cli.c），
     取回 C 侧对同一 (task_id, frame_seq, 全字段) 编码出的【整帧字节，含 CRC】；
  2. 用工程内 Python codec（electrical_control.protocol）编码同一组字段，
     要求与 C 侧逐字节相同；
  3. 把 8 字节旧载荷分别喂给 C 解码器与 Python 解码器，要求【双方都拒绝】
     （C 返回 false / Python 抛 PayloadError）——fail-closed 证明。

环境变量 CC 可指定编译器；找不到编译器时本脚本以退出码 3 明确报错，
不会静默跳过。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LOGIC = _HERE.parent
_REPO = _LOGIC.parent.parent
sys.path.insert(0, str(_REPO / "电控" / "src"))

from electrical_control.protocol import (  # noqa: E402
    ItemTaskPayload,
    PayloadError,
    decode_item_task_payload,
    encode_item_task_frame,
    encode_item_task_payload,
)

# 与 tests/item_task_vector_cli.c 的 vectors[] 一一对应，改一处必须改两处。
VECTORS = (
    # name, task_id, frame_seq, target_seq, class_id, x, y, pick_x, pick_y
    ("GOLDEN", 0x0007, 0x000B, 0x01, 0x02, -1000, 1000, 250, -250),
    ("BOUND", 0x1234, 0x00FF, 0xFF, 0x02, 1450, -1450, -1450, 1450),
)

# P3 之前的 8 字节线格式载荷（落料点 + 角度，无抓取点）。
OLD_8_BYTE_PAYLOAD = bytes.fromhex("01 02 02 FC 18 03 E8 FF")


def build_cli(workdir: Path) -> Path:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        raise SystemExit("退出码 3：找不到 C 编译器（gcc/cc），无法做跨语言一致性验证")
    exe = workdir / ("item_task_vector_cli.exe" if os.name == "nt" else "item_task_vector_cli")
    cmd = [
        cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-I", str(_LOGIC / "include"),
        str(_HERE / "item_task_vector_cli.c"),
        str(_LOGIC / "src" / "ec_protocol.c"),
        str(_LOGIC / "src" / "ec_crc32.c"),
        "-o", str(exe),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        raise SystemExit("退出码 4：C 向量 CLI 编译失败")
    return exe


def python_frame(task_id, frame_seq, target_seq, class_id, x, y, pick_x, pick_y):
    payload = encode_item_task_payload(
        ItemTaskPayload(
            target_seq=target_seq,
            class_id=class_id,
            image_id=class_id,  # 冻结 1:1 不变式
            x_position=x,
            y_position=y,
            grip_angle=0xFF,
            pick_x_position=pick_x,
            pick_y_position=pick_y,
        )
    )
    frame = encode_item_task_frame(task_id=task_id, frame_seq=frame_seq, payload=payload)
    return payload, frame


def main() -> int:
    exe = build_cli(Path(os.environ.get("TMPDIR", "/tmp")))
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout

    c_vectors = {}
    old8_verdict = None
    for line in out.splitlines():
        if line.startswith("OLD8 "):
            old8_verdict = line.split()[1]
            continue
        name, rest = line.split(" ", 1)
        payload_hex, frame_hex = (part.strip() for part in rest.split("|"))
        c_vectors[name] = (payload_hex, frame_hex)

    failures = []

    print("=== 1/2 跨语言逐字节一致性（含 CRC）")
    for name, *fields in VECTORS:
        py_payload, py_frame = python_frame(*fields)
        py_payload_hex = py_payload.hex(" ").upper()
        py_frame_hex = py_frame.hex(" ").upper()
        c_payload_hex, c_frame_hex = c_vectors[name]
        same_payload = c_payload_hex == py_payload_hex
        same_frame = c_frame_hex == py_frame_hex
        print(f"[{name}] payload ({len(py_payload)}B)  C == Py : {same_payload}")
        print(f"          C : {c_payload_hex}")
        print(f"          Py: {py_payload_hex}")
        print(f"       整帧 ({len(py_frame)}B, 含 CRC) C == Py : {same_frame}")
        print(f"          C : {c_frame_hex}")
        print(f"          Py: {py_frame_hex}")
        if not (same_payload and same_frame):
            failures.append(f"{name}: C/Python 字节不一致")
        if len(py_frame) != 26:
            failures.append(f"{name}: 整帧长度 {len(py_frame)} != 26")

    print()
    print("=== 2/2 8 字节旧载荷 fail-closed")
    print(f"C  ec_proto_decode_item_task(8B)      -> {old8_verdict}")
    if old8_verdict != "REJECTED":
        failures.append("C 侧接受了 8 字节旧载荷")
    try:
        decoded = decode_item_task_payload(OLD_8_BYTE_PAYLOAD)
    except PayloadError as exc:
        print(f"Py decode_item_task_payload(8B)       -> PayloadError: {exc}")
    else:
        print(f"Py decode_item_task_payload(8B)       -> 未拒绝: {decoded!r}")
        failures.append("Python 侧接受了 8 字节旧载荷")

    print()
    if failures:
        for item in failures:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1
    print("OK：C / Python 逐字节一致（含 CRC），8 字节旧载荷双方均拒绝（fail-closed）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
