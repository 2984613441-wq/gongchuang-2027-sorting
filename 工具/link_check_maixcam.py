#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连 MaixCAM 的 9001 只读监控口，抓 N 秒 JSON 检测流并给出结论。

价值：这是**唯一能脱离树莓派**验证 MaixCAM 是否活着的一条路。
树莓派不在线时，只要 MaixCAM 在跑 main.py，9001 就会每帧推一行 JSON。

协议（视觉/src/maixcam_deploy/main.py:281，与 工具/monitor_gui.py 对齐）：
    {"fps":..,"count":..,"conf_th":..,"iou_th":..,"task_id":..,
     "detections":[{"class_id":0,"class_name":"cube","confidence":0.87,"center":[x,y]},..]}\n
9001 是**只读旁路**：连上只是收，不影响检测与 8765 生产通道；本脚本也不下发任何
调参/截图命令（那是 monitor_gui 的事）。

用法：
    py -3 工具/link_check_maixcam.py                          # 默认 172.20.10.2:9001，抓 10 秒
    py -3 工具/link_check_maixcam.py --host 192.168.1.20 -t 20
    py -3 工具/link_check_maixcam.py --self-test              # 不联网，跑解析自检

依赖：无（纯标准库）。未验证：只在主机侧跑过 --self-test 与 --help，没连过真机。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time


class StreamStats:
    def __init__(self) -> None:
        self.lines = 0
        self.bad_json = 0
        self.missing_keys = 0
        self.det_frames = 0          # 至少 1 个目标的帧数
        self.empty_frames = 0        # count=0 的帧数
        self.total_dets = 0
        self.by_class: dict[int, int] = {}
        self.by_name: dict[str, int] = {}
        self.fps_values: list[float] = []
        self.task_ids = set()
        self.conf_min = None
        self.conf_max = None
        self.first_t = None
        self.last_t = None
        self.sample_raw = None

    def feed_line(self, line: str, now: float) -> None:
        line = line.strip()
        if not line:
            return
        if self.sample_raw is None:
            self.sample_raw = line
        self.lines += 1
        if self.first_t is None:
            self.first_t = now
        self.last_t = now
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            self.bad_json += 1
            return
        if not isinstance(msg, dict) or "detections" not in msg:
            self.missing_keys += 1
            return
        dets = msg.get("detections") or []
        if msg.get("count") is not None and int(msg["count"]) != len(dets):
            self.missing_keys += 1     # count 与数组长度不一致：别急着信 count
        if isinstance(msg.get("fps"), (int, float)):
            self.fps_values.append(float(msg["fps"]))
        if msg.get("task_id") is not None:
            self.task_ids.add(msg["task_id"])
        if dets:
            self.det_frames += 1
            self.total_dets += len(dets)
            for d in dets:
                cid = d.get("class_id")
                name = str(d.get("class_name", cid))
                self.by_class[cid] = self.by_class.get(cid, 0) + 1
                self.by_name[name] = self.by_name.get(name, 0) + 1
                conf = d.get("confidence")
                if isinstance(conf, (int, float)):
                    self.conf_min = conf if self.conf_min is None else min(self.conf_min, conf)
                    self.conf_max = conf if self.conf_max is None else max(self.conf_max, conf)
        else:
            self.empty_frames += 1


def report(stats: StreamStats, seconds: float, connected: bool, error: str | None) -> None:
    print("=" * 66)
    print(f"结论（{seconds:g} 秒窗口）")
    if not connected:
        print(f"  [不通] 连不上: {error}")
        print("    依次查：① IP 对不对（MaixCAM 屏幕/路由器里看）")
        print("            ② 电脑和 MaixCAM 在同一网段吗（ping 一下）")
        print("            ③ MaixCAM 上 main.py 在跑吗、ENABLE_MONITOR=1 吗（比赛时会关掉它！）")
        print("            ④ MONITOR_PORT 还是 9001 吗")
        print("            ⑤ 电脑防火墙/热点隔离挡了入站吗")
        return
    print("  [通] TCP 连上了 9001。")
    if stats.lines == 0:
        print("       但一行数据都没收到：进程可能在跑但检测循环卡在别处")
        print("       （例如 ENABLE_NETWORK=1 而 8765 连不上，每帧 connect 超时拖慢循环）。")
        return
    span = max((stats.last_t or 0) - (stats.first_t or 0), 1e-6)
    print(f"  收到 {stats.lines} 行 JSON（{stats.lines / span:.1f} 行/秒），"
          f"坏 JSON {stats.bad_json} 行，缺 detections 字段 {stats.missing_keys} 行。")
    if stats.bad_json:
        print("  ⚠️ 有坏 JSON：多半是 TCP 分包把一行切开了（本脚本按 \n 重组，偶发属正常；")
        print("     若占比很高说明 9001 那头在推非 JSON 的东西）。")
    if stats.fps_values:
        print(f"  MaixCAM 自报 fps: 首={stats.fps_values[0]:.1f} "
              f"末={stats.fps_values[-1]:.1f} 最高={max(stats.fps_values):.1f}")
    if stats.task_ids:
        print(f"  task_id: {sorted(stats.task_ids)}（须与树莓派 --round-task-id 相等）")
    print(f"  有目标的帧 {stats.det_frames} / 空帧 {stats.empty_frames}")
    if stats.total_dets:
        dist = " ".join(f"{k}×{v}" for k, v in sorted(stats.by_class.items(), key=lambda kv: str(kv[0])))
        print(f"  共 {stats.total_dets} 个检测框，类别分布: {dist}")
        print(f"  置信度范围: {stats.conf_min:.3f} ~ {stats.conf_max:.3f}")
    else:
        print("  ⚠️ 全程 0 目标：检测循环在跑（有 JSON 流）但没有目标。")
        print("     可能：镜头前真的没货 / 没对准 / 光照太差 / conf_th 太高。")
        print("     试：放一个货在镜头正前方 20cm，看数字是否变化。")
    if stats.sample_raw:
        print(f"  首行样例: {stats.sample_raw[:160]}")


def run(args) -> int:
    t0 = time.monotonic()
    stats = StreamStats()
    sock = None
    error = None
    try:
        sock = socket.create_connection((args.host, args.port), timeout=args.timeout)
        sock.settimeout(0.5)
        print(f"已连接 {args.host}:{args.port}，抓 {args.duration:g} 秒…")
    except OSError as exc:
        error = f"{exc!r}"
    if sock is None:
        report(stats, 0.0, False, error)
        return 2

    buf = b""
    try:
        while time.monotonic() - t0 < args.duration:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                error = f"接收中断 {exc!r}"
                break
            if not chunk:
                error = ("对端关闭了连接（收到数据后关闭＝正常收尾；"
                         "一行都没收到就说明 MaixCAM 上进程退了/没在跑）")
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                stats.feed_line(line.decode("utf-8", errors="replace"), time.monotonic())
    except KeyboardInterrupt:
        print("\nCtrl-C 停止。")
    finally:
        try:
            sock.close()
        except OSError:
            pass

    report(stats, time.monotonic() - t0, True, error)
    if error:
        print(f"  注：{error}")
    return 0


# --------------------------------------------------------------------------- #
def self_test() -> int:
    s = StreamStats()
    t = 0.0
    s.feed_line('{"fps": 21.3, "count": 2, "conf_th": 0.5, "iou_th": 0.45, "task_id": 7, '
                '"detections": [{"class_id": 3, "class_name": "cube", "confidence": 0.87, '
                '"center": [640, 360]}, {"class_id": 0, "class_name": "cuboid", '
                '"confidence": 0.61, "center": [100, 200]}]}', t)
    s.feed_line('{"fps": 21.0, "count": 0, "task_id": 7, "detections": []}', t + 0.05)
    s.feed_line('{"fps": 21.0, "count": 0, "task_id": 7, "detections": []', t + 0.1)   # 坏 JSON
    s.feed_line('{"hello": 1}', t + 0.15)                                              # 缺字段
    s.feed_line('   ', t + 0.2)                                                        # 空行忽略
    assert s.lines == 4, s.lines
    assert s.bad_json == 1 and s.missing_keys == 1, (s.bad_json, s.missing_keys)
    assert s.det_frames == 1 and s.empty_frames == 1, (s.det_frames, s.empty_frames)
    assert s.by_class == {3: 1, 0: 1}, s.by_class
    assert s.task_ids == {7} and s.conf_min == 0.61 and s.conf_max == 0.87
    # count 与 detections 长度不一致必须被标出来
    s2 = StreamStats()
    s2.feed_line('{"count": 5, "detections": []}', 0.0)
    assert s2.missing_keys == 1, s2.missing_keys
    print("自检通过：正常帧/空帧/坏 JSON/缺字段/空行 统计全部符合预期。")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="连 MaixCAM 9001 只读监控口，抓 N 秒 JSON 检测流并给结论（不需要树莓派在线）",
    )
    p.add_argument("--host", default="172.20.10.2", help="MaixCAM IP，默认 172.20.10.2")
    p.add_argument("--port", type=int, default=9001, help="监控端口，默认 9001")
    p.add_argument("-t", "--duration", type=float, default=10.0, help="抓取秒数，默认 10")
    p.add_argument("--timeout", type=float, default=3.0, help="连接超时秒数，默认 3")
    p.add_argument("--self-test", action="store_true", dest="self_test", help="不联网，跑解析自检")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
