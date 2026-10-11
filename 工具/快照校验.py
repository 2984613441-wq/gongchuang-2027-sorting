#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作区快照 / 差异校验 —— 用来证明派出去的 AI 到底有没有写文件。

读文件不会改变 size/mtime，写文件会。所以比对 (大小, 修改时间) 就能查出：
  · 新增了什么（含 __pycache__ / .pytest_cache —— 这本身就是「跑了测试」的铁证）
  · 改了什么
  · 删了什么

用法（在本工作区根目录）：
    py -3 工具\\快照校验.py            # 拍快照（派工前做一次）
    py -3 工具\\快照校验.py --diff     # 与最近一次快照比对（派工后做）

快照落盘：docs/交付/2026-09-20/工作区快照-派工前.txt
（默认只认第一份快照作为基线，不覆盖 —— 想重建基线就加 --force）
"""

import hashlib
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "docs" / "交付" / "2026-09-20" / "工作区快照-派工前.txt"

# 与本次派工无关的巨型/外发目录，不进快照
SKIP_DIRS = {
    ".git", "archive", "备份", "_incoming", "node_modules",
    "外发-给朋友-2026-09-20", "派工-多AI并行-2026-09-20",
    "7寸10寸 1024x600分辨率显示屏客户资料",
}
SKIP_SUFFIX = (".7z", ".zip", ".iso", ".img")


def scan():
    rows = []
    errors = []
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_dir() or p == SNAP:      # 把自己排除，否则 diff 永远显示"新增 1 个"
            continue
        try:
            st = p.stat()
        except OSError as e:            # ACL 拒绝访问的 pytest 缓存目录
            errors.append(f"{p.relative_to(ROOT)}\t{e.__class__.__name__}")
            continue
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        rows.append(f"{rel}\t{st.st_size}\t{int(st.st_mtime)}")
    rows.sort()
    return rows, errors


def main() -> int:
    do_diff = "--diff" in sys.argv
    force = "--force" in sys.argv

    if do_diff:
        if not SNAP.is_file():
            print(f"还没有基线快照：{SNAP}\n先跑一次 py -3 工具\\快照校验.py", file=sys.stderr)
            return 1
        base = {}
        for line in SNAP.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            rel, size, mt = line.split("\t")
            base[rel] = (int(size), int(mt))

        now_rows, errors = scan()
        now = {}
        for line in now_rows:
            rel, size, mt = line.split("\t")
            now[rel] = (int(size), int(mt))

        added = sorted(set(now) - set(base))
        removed = sorted(set(base) - set(now))
        changed = sorted(k for k in set(now) & set(base) if now[k] != base[k])

        print(f"基线：{SNAP.name}（{len(base):,} 个文件）")
        print(f"现在：{len(now):,} 个文件\n")

        if not (added or removed or changed):
            print("✅ 干净：没有任何文件被新增 / 修改 / 删除 —— 派工期间无人写盘。")
        else:
            print(f"🔴 检出变动：新增 {len(added)} ｜ 修改 {len(changed)} ｜ 删除 {len(removed)}\n")
            for tag, items in (("新增", added), ("修改", changed), ("删除", removed)):
                if not items:
                    continue
                print(f"【{tag}】{len(items)} 个")
                for k in items[:80]:
                    print(f"   {k}")
                if len(items) > 80:
                    print(f"   … 另有 {len(items) - 80} 个（完整列表请重跑并重定向输出）")
                print()
            print("💡 __pycache__ / .pytest_cache 出现 = 有人跑过测试或导入过模块。")
        if errors:
            print(f"\n（另有 {len(errors)} 个路径因权限无法读取，已忽略）")
        return 0

    # ---- 拍快照 ----
    if SNAP.is_file() and not force:
        print(f"基线快照已存在，不覆盖：{SNAP}")
        print("如确实要重建基线，加 --force（⚠ 会丢掉唯一的派工前证据）。")
        return 0

    SNAP.parent.mkdir(parents=True, exist_ok=True)
    rows, errors = scan()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    SNAP.write_text(
        f"# 工作区快照（派工前基线）\n"
        f"# 生成时间: {stamp}\n"
        f"# 范围: {ROOT}\n"
        f"# 格式: 相对路径 <TAB> 字节数 <TAB> mtime(epoch)\n"
        f"# 排除: {', '.join(sorted(SKIP_DIRS))}\n"
        f"# 用途: 派工后用 `py -3 工具\\快照校验.py --diff` 证明各 AI 有没有写盘\n"
        + "\n".join(rows) + "\n",
        encoding="utf-8", newline="\n",
    )
    total = sum(int(r.split("\t")[1]) for r in rows)
    print(f"OK  基线快照已写入 {SNAP}")
    print(f"    {len(rows):,} 个文件，合计 {total / 1024 / 1024:.1f} MB，{stamp}")
    if errors:
        print(f"    （{len(errors)} 个路径因权限无法读取，已忽略）")
    print("    派工结束后跑：py -3 工具\\快照校验.py --diff")
    # 顺带打印一个整树指纹，便于口头核对
    h = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    print(f"    整树指纹 sha256(路径+大小+mtime) = {h[:32]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
