#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 sorting_config.ini 的 [DropPoints] 六个点的 x 统一设为指定值。

用法： python3 pi_set_drops.py 60.0

⚠️ 写出用 utf-8（不带 BOM），写完用 configparser 回读复核。
"""
import configparser
import shutil
import sys
import time

PATH = "/home/pi/sorting_config.ini"

if len(sys.argv) != 2:
    print("用法: python3 pi_set_drops.py <新的 x 值，例如 60.0>")
    sys.exit(2)
new_x = float(sys.argv[1])

stamp = time.strftime("%Y%m%d-%H%M%S")
shutil.copy2(PATH, "%s.bak-%s" % (PATH, stamp))
print("已备份 -> %s.bak-%s" % (PATH, stamp))

lines = open(PATH, "rb").read().decode("utf-8-sig").splitlines()
out = []
in_sec = False
n = 0
for ln in lines:
    st = ln.strip()
    if st.startswith("["):
        in_sec = (st == "[DropPoints]")
        out.append(ln)
        continue
    if in_sec and "=" in st and not st.startswith("#"):
        k, v = st.split("=", 1)
        comment = ("  # " + v.split("#", 1)[1].strip()) if "#" in v else ""
        parts = v.split("#")[0].strip().split(",")
        if len(parts) == 2:
            try:
                y = float(parts[1])
            except ValueError:
                out.append(ln)
                continue
            out.append("%s= %.1f,%.1f%s" % (k.strip(), new_x, y, comment))
            n += 1
            continue
    out.append(ln)

if n == 0:
    print("!! 一个都没改到，中止")
    sys.exit(1)

open(PATH, "wb").write(("\n".join(out) + "\n").encode("utf-8"))
print("已改 %d 个落点，x = %.1f（无 BOM）" % (n, new_x))

cfg = configparser.ConfigParser()
cfg.read(PATH, encoding="utf-8-sig")
print("回读 [DropPoints] =", dict(cfg.items("DropPoints")))
print("节 =", cfg.sections())
