#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""裸监听 TCP 8765，把 MaixCAM 发来的字节按 BATCH_TARGETS 布局解出来。

为什么要有它：树莓派上跑 run_chain.py 才会监听 8765，而 run_chain 真实模式有 8 道
fail-closed 门（图片目录/落点表/字体…）过不去。本脚本**不依赖 run_chain、不依赖任何
配置文件**，只回答一件事：MaixCAM 连得上吗？字节到底长什么样？

线格式（视觉/src/maixcam_deploy/main.py:342 encode_batch_targets，与
电控/src/electrical_control/rpi/vision_ingest.py:40 的解析规则一致）：
    target_count(1) + task_id(2, BE) + target[N]
    每个 target 7 字节: class_id(1) conf(1,0-100) X(2,BE) Y(2,BE) angle(1,=0xFF)
⚠️ 8765 上**没有外层帧**（不是 0xA5 5A 那种协议帧），就是上面这段裸字节流，
   TCP 是字节流所以靠 count 字节自定界。

严格校验：本脚本按 parse_batch_targets 的同款规则拒绝非法批次 —— 它拒绝的批次，
树莓派 run_chain 也会**整批丢掉**（fail-closed），所以这里的报错就是线上会踩的坑。

用法（树莓派或 PC 都能跑，PC 也能模拟"我可以是那个监听端"）：
    python3 工具/link_listen_8765.py                     # 监听 0.0.0.0:8765，Ctrl-C 停
    python3 工具/link_listen_8765.py -t 20               # 只监听 20 秒
    python3 工具/link_listen_8765.py --raw               # 只 dump hex，不解析
    python3 工具/link_listen_8765.py --port 18765        # 换端口（PC 上避免和别的冲突）
    python3 工具/link_listen_8765.py --self-test         # 不监听，跑解析自检

依赖：无（纯标准库）。未验证：只在主机侧跑过 --self-test 与 --help，没接真机。
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

HEADER_BYTES = 3
TARGET_BYTES = 7
ACTIVE_CLASS_IDS = frozenset({0, 2, 3, 4, 5, 6})   # 1=cuboid 本轮缺失
ANGLE_NONE = 0xFF


class BatchError(ValueError):
    """批次违反冻结布局（线上会被树莓派整批丢掉）。"""


def parse_batch(data: bytes) -> dict:
    """按冻结布局解析一个 BATCH_TARGETS 数据区；非法则抛 BatchError。"""
    data = bytes(data)
    if len(data) < HEADER_BYTES:
        raise BatchError(f"长度 {len(data)} < 3 字节头")
    count = data[0]
    task_id = int.from_bytes(data[1:3], "big")
    expected = HEADER_BYTES + count * TARGET_BYTES
    if len(data) != expected:
        raise BatchError(f"长度 {len(data)} != 期望 {expected}（count={count}）")
    targets = []
    for i in range(count):
        off = HEADER_BYTES + i * TARGET_BYTES
        class_id, conf, angle = data[off], data[off + 1], data[off + 6]
        x = int.from_bytes(data[off + 2:off + 4], "big")
        y = int.from_bytes(data[off + 4:off + 6], "big")
        if class_id not in ACTIVE_CLASS_IDS:
            raise BatchError(f"第 {i + 1} 个目标 class_id={class_id} 不在冻结集 {sorted(ACTIVE_CLASS_IDS)}")
        if conf > 100:
            raise BatchError(f"第 {i + 1} 个目标 confidence={conf} 越界（应 0-100）")
        if angle != ANGLE_NONE:
            raise BatchError(f"第 {i + 1} 个目标 angle=0x{angle:02X} != 0xFF（夹爪不旋转）")
        targets.append({"seq": i + 1, "class_id": class_id, "conf": conf, "x": x, "y": y})
    return {"count": count, "task_id": task_id, "targets": targets}


def recv_exact(conn: socket.socket, nbytes: int) -> bytes | None:
    """收满 nbytes 字节；对端关闭返回 None。"""
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = conn.recv(nbytes - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def hexdump(data: bytes) -> str:
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{data.hex(' ').upper():<48} |{printable}|"


def summarize(stats: dict, seconds: float) -> None:
    print("=" * 70)
    print(f"结论（监听 {seconds:g} 秒）")
    if not stats["clients"]:
        print("  [不通] 没有任何客户端连上来。")
        print("    依次查：① MaixCAM 上的 GATEWAY_HOST 是不是本机 IP（默认写死 172.20.10.8）")
        print("            ② 两端在同一网段吗（ping / ip a）")
        print("            ③ MaixCAM 进程在跑吗、ENABLE_NETWORK=1 吗（=0 时根本不连）")
        print("            ④ 本机防火墙挡了入站吗（sudo ufw status / iptables -L）")
        print("            ⑤ 监听端口和 GATEWAY_PORT 都是 8765 吗")
        return
    print(f"  [通] 有 {stats['clients']} 个客户端连上来过 —— 网络可达。")
    if stats["batches"] == 0:
        print("       但一个完整批次都没解出来：看上面的 [丢] 行（半截/非法），")
        print("       或对端连上后没发数据（MaixCAM 侧 ENABLE_NETWORK=0 / 检测循环卡住）。")
        return
    rate = stats["batches"] / max(seconds, 1e-6)
    print(f"  收到 {stats['batches']} 个批次 / {stats['targets']} 个目标，"
          f"平均 {rate:.1f} 批次/秒，共 {stats['bytes']} 字节。")
    print(f"  task_id 取值: {sorted(stats['task_ids'])}（树莓派的 round-task-id 必须与之相等，否则整批丢）")
    if stats["empty"]:
        print(f"  其中 {stats['empty']} 个是 count=0 心跳帧（无货时每 500ms 一帧，属正常）。")
    if stats["by_class"]:
        dist = " ".join(f"{k}×{v}" for k, v in sorted(stats["by_class"].items()))
        print(f"  类别分布: {dist}")
    else:
        print("  ⚠️ 所有批次都是 0 目标 —— 镜头前没有货，或模型/阈值不对（对照 S4 的 9001 监控）。")
    if stats["max_gap"] > 2.0:
        print(f"  ⚠️ 最大批次间隔 {stats['max_gap']:.1f} 秒 —— 像是断线重连或检测卡顿。")


def listen(args) -> int:
    if args.raw:
        print("--raw 模式：只 dump 原始 hex，不解析（排查「帧格式不对」时用）。")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((args.host, args.port))
    except OSError as exc:
        print(f"错误: 绑定 {args.host}:{args.port} 失败: {exc!r}", file=sys.stderr)
        print("  端口被占用？树莓派上 run_chain.py 可能正在监听 8765 —— 两者只能有一个。", file=sys.stderr)
        print("  另可改用 --port 18765 先自测（MaixCAM 那边 GATEWAY_PORT 也要跟着改）。", file=sys.stderr)
        return 2
    srv.listen(1)
    srv.settimeout(1.0)
    print(f"正在监听 {args.host}:{args.port}（Ctrl-C 结束）"
          + (f"，{args.duration:g} 秒后自动停" if args.duration else ""))

    stats = {"clients": 0, "batches": 0, "targets": 0, "bytes": 0, "empty": 0,
             "by_class": {}, "task_ids": set(), "max_gap": 0.0}
    last_t = None
    t0 = time.monotonic()
    try:
        while True:
            if args.duration and time.monotonic() - t0 >= args.duration:
                print(f"到 {args.duration:g} 秒，停止监听。")
                break
            if args.max_batches and stats["batches"] >= args.max_batches:
                print(f"已收满 {args.max_batches} 个批次，停止监听。")
                break
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            stats["clients"] += 1
            print(f">>> 客户端连接: {addr[0]}:{addr[1]}")
            conn.settimeout(2.0)
            with conn:
                while True:
                    if args.duration and time.monotonic() - t0 >= args.duration:
                        break
                    if args.raw:
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            continue
                        except OSError as exc:
                            print(f"    读取失败: {exc!r}")
                            break
                        if not chunk:
                            break
                        stats["bytes"] += len(chunk)
                        print(f"    {len(chunk):4d}B  {hexdump(chunk)}")
                        continue
                    try:
                        head = recv_exact(conn, 1)
                        if head is None:
                            break
                        rest = recv_exact(conn, (HEADER_BYTES - 1) + head[0] * TARGET_BYTES)
                        if rest is None:
                            print("    [丢] 对端在批次中途断开：只收到 count 字节 "
                                  f"count={head[0]}，缺 {(HEADER_BYTES - 1) + head[0] * TARGET_BYTES} 字节。")
                            break
                    except socket.timeout:
                        continue
                    except OSError as exc:
                        print(f"    读取失败: {exc!r}")
                        break
                    raw = head + rest
                    stats["bytes"] += len(raw)
                    now = time.monotonic()
                    if last_t is not None:
                        stats["max_gap"] = max(stats["max_gap"], now - last_t)
                    last_t = now
                    try:
                        batch = parse_batch(raw)
                    except BatchError as exc:
                        print(f"    [丢] 非法批次（线上树莓派也会整批丢）: {exc}")
                        print(f"         raw={hexdump(raw)}")
                        continue
                    stats["batches"] += 1
                    stats["targets"] += batch["count"]
                    stats["task_ids"].add(batch["task_id"])
                    if batch["count"] == 0:
                        stats["empty"] += 1
                    print(f"[批次 {stats['batches']}] count={batch['count']} "
                          f"task_id={batch['task_id']} len={len(raw)}B")
                    if args.task_id is not None and batch["task_id"] != args.task_id:
                        print(f"    [注意] task_id={batch['task_id']} != --task-id {args.task_id}"
                              f"（树莓派会整批丢）")
                    for t in batch["targets"]:
                        stats["by_class"][t["class_id"]] = stats["by_class"].get(t["class_id"], 0) + 1
                        print(f"    #{t['seq']} class_id={t['class_id']} conf={t['conf']:3d} "
                              f"x={t['x']:4d} y={t['y']:4d} angle=0xFF")
            print("<<< 客户端断开")
    except KeyboardInterrupt:
        print("\nCtrl-C 停止。")
    finally:
        srv.close()
    summarize(stats, args.duration or (time.monotonic() - t0))
    return 0


# --------------------------------------------------------------------------- #
def build_batch(task_id: int, targets) -> bytes:
    body = bytearray([len(targets)])
    body += int(task_id).to_bytes(2, "big")
    for class_id, conf, x, y in targets:
        body += bytes((class_id, conf)) + x.to_bytes(2, "big") + y.to_bytes(2, "big") + b"\xff"
    return bytes(body)


def self_test() -> int:
    raw = build_batch(7, [(3, 87, 640, 360), (0, 51, 100, 200)])
    assert len(raw) == 3 + 2 * 7, len(raw)
    b = parse_batch(raw)
    assert b["task_id"] == 7 and b["count"] == 2
    assert b["targets"][0] == {"seq": 1, "class_id": 3, "conf": 87, "x": 640, "y": 360}
    assert parse_batch(build_batch(9, []))["count"] == 0        # 心跳空帧

    bad_angle = bytearray(raw)
    bad_angle[3 + 6] = 0x00                      # 第 1 个目标的 angle 字节（3 头 + 6 偏移）

    for bad, why in (
        (raw[:-1], "长度短一字节"),
        (build_batch(7, [(1, 50, 1, 1)]), "class_id=1 不在冻结集"),
        (build_batch(7, [(3, 101, 1, 1)]), "confidence>100"),
        (bytes(bad_angle), "angle!=0xFF"),
        (b"\x01\x00", "连头都不够"),
    ):
        try:
            parse_batch(bad)
        except BatchError:
            pass
        else:
            raise AssertionError(f"应当拒绝但没拒绝: {why}")
    print("自检通过：合法批次数值解析、空帧、5 类非法批次 全部符合预期。")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="裸监听 TCP 8765 并按 BATCH_TARGETS 布局解析（不依赖 run_chain/任何配置）",
    )
    p.add_argument("--host", default="0.0.0.0", help="绑定地址，默认 0.0.0.0（所有网卡）")
    p.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    p.add_argument("-t", "--duration", type=float, default=0.0,
                   help="监听秒数，0=一直听（Ctrl-C 停）")
    p.add_argument("--max-batches", type=int, default=0, dest="max_batches",
                   help="收满 N 个批次就停，0=不限")
    p.add_argument("--raw", action="store_true", help="只 dump hex，不解析")
    p.add_argument("--task-id", type=int, default=None, dest="task_id",
                   help="期望的 task_id；不等于它的批次会被标出来（树莓派会丢）")
    p.add_argument("--self-test", action="store_true", dest="self_test", help="不监听，跑解析自检")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    return listen(args)


if __name__ == "__main__":
    raise SystemExit(main())
