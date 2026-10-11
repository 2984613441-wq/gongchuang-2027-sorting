#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去掉两个 ini 的 UTF-8 BOM（我的上一版脚本用 utf-8-sig 写出，加了 BOM，
导致 configparser 报 'File contains no section headers'，标定整体失效）。
读入时用 utf-8-sig（自动吞掉 BOM），写出时用 utf-8（不加 BOM）。"""
import configparser
import sys

FILES = [
    "/home/pi/电控/calibration_config.ini",
    "/home/pi/sorting_config.ini",
]

for path in FILES:
    raw = open(path, "rb").read()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    if had_bom:
        open(path, "wb").write(text.encode("utf-8"))
        print("%s  有BOM -> 已去除" % path)
    else:
        print("%s  无BOM（未动）" % path)

    # 复核：configparser 必须能读
    cfg = configparser.ConfigParser()
    try:
        cfg.read_string(text)
        print("   可解析；节 = %s" % cfg.sections())
    except Exception as exc:  # noqa: BLE001
        print("   !! 仍无法解析: %s" % exc)
        sys.exit(1)

# 复核关键值
cfg = configparser.ConfigParser()
cfg.read(FILES[0], encoding="utf-8-sig")
print()
print("tx          =", cfg.get("CameraCalibration", "tx"))
cfg2 = configparser.ConfigParser()
cfg2.read(FILES[1], encoding="utf-8-sig")
print("[DropPoints] =", dict(cfg2.items("DropPoints")))
