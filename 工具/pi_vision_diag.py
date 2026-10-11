#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用抓包得到的真实 10 字节，在树莓派上离线复现「为什么这件被静默丢弃」。

真实抓包（2026-09-19，40 次连接全部相同结构）：
    01 00 01 | 01 64 00 94 00 80 ff
    count=1  task_id=1   target 7 字节

按代码顺序逐步打印，定位到底是哪一步返回 None / 空。
"""
import sys
import traceback

sys.path.insert(0, "/home/pi/电控/src")

DATA = bytes([0x01, 0x00, 0x01,   # target_count=1, task_id=1 (BE)
              0x01, 0x64, 0x00, 0x94, 0x00, 0x80, 0xFF])  # target 7B

print("=" * 60)
print("1) parse_batch_targets")
try:
    from electrical_control.rpi.vision_ingest import parse_batch_targets
    batch = parse_batch_targets(DATA)
    print("   task_id =", batch.task_id)
    print("   targets =", len(batch.targets))
    for i, t in enumerate(batch.targets):
        print("   target[%d]:" % i)
        for f in ("box_id", "class_id", "pixel_x", "pixel_y", "target_seq",
                  "width", "height", "confidence"):
            if hasattr(t, f):
                print("      %-12s = %r" % (f, getattr(t, f)))
except Exception:
    print("   !! 解析异常")
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 60)
print("2) 像素->毫米换算")
try:
    from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter
    conv = PixelToDeviceConverter("/home/pi/电控/calibration_config.ini")
    print("   is_calibrated =", conv.is_calibrated)
    print("   object_heights =", getattr(conv, "object_heights", None))
    for i, t in enumerate(batch.targets):
        try:
            got = conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id)
        except Exception:
            got = "!! 抛异常"
            traceback.print_exc()
        print("   target[%d] pixel=(%s,%s) box_id=%s  ->  %r"
              % (i, t.pixel_x, t.pixel_y, t.box_id, got))
        if got is None:
            print("      ^^^^ 这里返回 None = 该件被静默丢弃（vision_ingest.py:242-244）")
except Exception:
    print("   !! 换算层导入/构造异常")
    traceback.print_exc()

print()
print("=" * 60)
print("3) 落点表查询（确认 box_id 在 [DropPoints] 里）")
try:
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read("/home/pi/sorting_config.ini", encoding="utf-8-sig")
    if cfg.has_section("DropPoints"):
        for k, v in cfg.items("DropPoints"):
            print("   %s = %s" % (k, v))
    else:
        print("   !! 没有 [DropPoints] 节")
    print("   [PickPoint] 存在 =", cfg.has_section("PickPoint"))
except Exception:
    traceback.print_exc()
