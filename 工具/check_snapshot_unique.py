#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删前唯一性核对：快照目录里的文件，主树里还有没有对应的？

做法：对【快照】与【主树】各自算 MD5 集合，找出"快照里有、主树里没有"的文件。
      —— 这些就是"唯一副本"，删快照就会丢。

用法：
    py -3 工具/check_snapshot_unique.py <快照目录1> [<快照目录2> ...]
主树 = 工作区根，自动排除 archive/ 与 .git/。
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("archive", ".git")
MB = 1 << 20

# 可重编即有的编译产物/构建垃圾 —— 它们的"唯一"毫无价值
BUILD_EXT = {
    ".o", ".obj", ".crf", ".ilk", ".pdb", ".a", ".lib", ".d", ".dep", ".map",
    ".axf", ".hex", ".bin", ".exe", ".su", ".tlog", ".lst", ".iex", ".sct",
    ".lnp", ".htm", ".build_log.htm", ".recipe", ".make", ".pyc",
}
BUILD_NAME_HINT = ("lastbuildstate", ".build_log", ".htm")


def is_build_junk(p: Path) -> bool:
    n = p.name.lower()
    if p.suffix.lower() in BUILD_EXT:
        return True
    return any(h in n for h in BUILD_NAME_HINT)


def hashes(base: Path, exclude_archive: bool = True):
    """返回 {md5: [相对路径,...]}"""
    out: dict[str, list[str]] = {}
    n = 0
    for dirpath, dirnames, filenames in os.walk(base):
        rel = Path(dirpath).relative_to(base)
        if exclude_archive and rel.parts and rel.parts[0] in SKIP:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP and d != "__pycache__"]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size == 0:
                    continue
                h = hashlib.md5()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
            except OSError:
                continue
            out.setdefault(h.hexdigest(), []).append(str(p.relative_to(base)))
            n += 1
    return out, n


def main() -> int:
    snaps = [Path(a) for a in sys.argv[1:]]
    if not snaps:
        print("用法: py -3 工具/check_snapshot_unique.py <快照目录> [...]")
        return 2

    print("正在给主树算 MD5（排除 archive/ 与 .git/）…")
    main_h, mn = hashes(ROOT)
    print(f"  主树: {mn} 个文件 / {len(main_h)} 个唯一内容\n")

    for s in snaps:
        if not s.exists():
            print(f"[跳过] 不存在: {s}")
            continue
        print("=" * 78)
        print(f"快照: {s}")
        snap_h, sn = hashes(s, exclude_archive=False)
        unique = []
        for h, rels in snap_h.items():
            if h not in main_h:
                for r in rels:
                    unique.append((s / r, r))
        total = sum(p.stat().st_size for p, _ in unique) if unique else 0
        junk = [(p, r) for p, r in unique if is_build_junk(p)]
        real = [(p, r) for p, r in unique if not is_build_junk(p)]
        junk_mb = sum(p.stat().st_size for p, _ in junk) / MB
        real_mb = sum(p.stat().st_size for p, _ in real) / MB
        print(f"  文件数 {sn}；主树里找不到对应内容的: {len(unique)} 个 / {total/MB:,.2f} MB")
        print(f"    ├─ 编译产物/构建垃圾 : {len(junk):>5} 个 / {junk_mb:>8,.2f} MB   （可重编，删掉无损失）")
        print(f"    └─ 真内容（要看！）  : {len(real):>5} 个 / {real_mb:>8,.2f} MB")
        if real:
            real.sort(key=lambda x: -x[0].stat().st_size)
            print("  —— 真内容·唯一副本（按体积，前 40）——")
            for p, r in real[:40]:
                print(f"    {p.stat().st_size/MB:>9,.3f} MB  {r}")
            if len(real) > 40:
                print(f"    … 还有 {len(real)-40} 个")
        else:
            print("  ✅ 除编译产物外，全部内容在主树里都有 ⇒ 可安全删")
    return 0


if __name__ == "__main__":
    sys.exit(main())
