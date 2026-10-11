#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作区"整理体检" —— 找出重复内容 / 备份文件 / 过期目录，为合并与删减提供依据。

设计要点：
  * 只做**只读**扫描，不删不改。
  * 文本文件算 **MD5** 找**逐字节重复**；二进制只统计大小（不读内容）。
  * 输出三张表：① 重复组（按可回收空间排序）② .bak/备份类清单 ③ 目录年龄盘点。
  * 输出刻意用 ASCII 头部 + UTF-8 写入文件，避免 GBK 控制台炸掉。

用法（工作区根目录）：
    py -3 工具/audit_workspace_clutter.py                # 全量（可能慢）
    py -3 工具/audit_workspace_clutter.py --fast         # 只扫 md/txt/json/ini/py 等文本，跳过二进制统计
结果同时写：工具/_audit_out/重复与过期盘点-<日期>.md
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = 1 << 10
MB = 1 << 20

# 不进入的目录（.git / 归档 / 依赖 / 构建 / 供应商大文件）
EXCLUDE_DIRS = {
    ".git", "archive", "node_modules", "__pycache__", ".pytest_cache",
    ".vscode", ".claude", ".pytest-tmp",
}
EXCLUDE_DIR_PREFIX = (
    "pytest-cache-files-", "build-", ".office-backup-",
)
# 供应商资料（3.4 GB 显示屏资料，里面是系统镜像）
EXCLUDE_PATH_PARTS = ("7寸10寸", "系统镜像", "开源参考", ".egg-info", "site-packages")

TEXT_EXT = {
    ".md", ".txt", ".py", ".c", ".h", ".json", ".ini", ".yaml", ".yml",
    ".sh", ".ps1", ".bat", ".csv", ".ino", ".cmake", ".js", ".ts", ".html",
    ".gitkeep", ".cfg", ".toml", ".bak",
}
BIN_EXT_SIZEABLE = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf", ".zip", ".7z", ".rar",
    ".docx", ".xlsx", ".pptx", ".onnx", ".pt", ".hex", ".exe", ".bin",
    ".o", ".obj", ".a", ".crf", ".d", ".map", ".axf", ".so", ".dll",
    ".pyc", ".su", ".tlog", ".lastbuildstate", ".recipe", ".make",
}

FAST = "--fast" in sys.argv


def should_skip_dir(name: str) -> bool:
    if name in EXCLUDE_DIRS:
        return True
    return any(name.startswith(p) for p in EXCLUDE_DIR_PREFIX)


def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = Path(dirpath).relative_to(ROOT)
        parts = set(rel.parts)
        if any(x in str(rel) for x in EXCLUDE_PATH_PARTS):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fn in filenames:
            yield Path(dirpath) / fn


def md5(path: Path) -> str | None:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = ROOT / "工具" / "_audit_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"重复与过期盘点-{today}.md"

    by_hash: dict[str, list[Path]] = defaultdict(list)
    by_ext: dict[str, list[int]] = defaultdict(list)
    baks: list[Path] = []
    text_count = bin_count = 0
    total_bytes = 0

    for p in walk():
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total_bytes += size
        ext = p.suffix.lower()
        by_ext[ext].append(size)
        if "bak" in p.name.lower() or p.name.endswith(".orig") or "_backup" in p.name.lower():
            baks.append(p)
        if ext in TEXT_EXT or ext == "":
            text_count += 1
            h = md5(p)
            if h:
                by_hash[h].append(p)
        else:
            bin_count += 1
            if ext not in BIN_EXT_SIZEABLE and not FAST:
                # 未知类型也试着按文本算一次（小文件）
                if size < 2 << 20:
                    h = md5(p)
                    if h:
                        by_hash[h].append(p)

    dup_groups = [(h, ps) for h, ps in by_hash.items() if len(ps) > 1]
    dup_groups.sort(key=lambda kv: -sum(p.stat().st_size for p in kv[1][1:]))
    dup_bytes = sum(sum(p.stat().st_size for p in ps[1:]) for _, ps in dup_groups)

    lines: list[str] = []
    A = lines.append
    A(f"# 工作区整理体检 · {today}")
    A("")
    A(f"- 扫描根：`{ROOT}`")
    A(f"- 文本文件（算了 MD5）：**{text_count}**；二进制文件：**{bin_count}**")
    A(f"- 扫描总量：**{total_bytes/MB:,.0f} MB**")
    A(f"- **逐字节重复组：{len(dup_groups)} 组 ⇒ 可回收 {dup_bytes/MB:,.1f} MB**")
    A(f"- 备份类文件（名字含 bak/orig/_backup）：**{len(baks)}**")
    A("")
    A("> 说明：只统计**逐字节完全相同**的文件；同名不同内容的未计入。")
    A("")

    A("## 一、重复内容组（按可回收空间排序，只列前 60 组）")
    A("")
    A("| # | 大小/个 | 份数 | 可回收 | 保留（建议） | 重复副本 |")
    A("|---|---:|---:|---:|---|---|")
    for i, (h, ps) in enumerate(dup_groups[:60], 1):
        ps_sorted = sorted(ps, key=lambda x: len(x.parts))
        keep = ps_sorted[0].relative_to(ROOT)
        dups = "; ".join(str(x.relative_to(ROOT)) for x in ps_sorted[1:5])
        if len(ps_sorted) > 5:
            dups += f" …(+{len(ps_sorted)-5})"
        one = ps_sorted[0].stat().st_size
        A(f"| {i} | {one/KB:,.1f} KB | {len(ps)} | {one*(len(ps)-1)/KB:,.1f} KB | `{keep}` | {dups} |")
    A("")

    A("## 二、备份类文件清单（`.bak*` / `.orig` / `_backup`）")
    A("")
    A("| 路径 | 大小 | 修改时间 |")
    A("|---|---:|---|")
    for p in sorted(baks, key=lambda x: str(x)):
        st = p.stat()
        A(f"| `{p.relative_to(ROOT)}` | {st.st_size/KB:,.1f} KB | "
          f"{datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M} |")
    A("")

    A("## 三、按扩展名的体量（前 25）")
    A("")
    A("| 扩展名 | 文件数 | 合计 |")
    A("|---|---:|---:|")
    for ext, sizes in sorted(by_ext.items(), key=lambda kv: -sum(kv[1]))[:25]:
        A(f"| `{ext or '(无)'}` | {len(sizes)} | {sum(sizes)/MB:,.1f} MB |")
    A("")

    A("## 四、目录年龄盘点（只列有 .md 的目录）")
    A("")
    A("| 目录 | .md 数 | 最早 | 最新 |")
    A("|---|---:|---|---|")
    md_by_dir: dict[str, list[float]] = defaultdict(list)
    for p in walk():
        if p.suffix.lower() == ".md":
            md_by_dir[str(p.parent.relative_to(ROOT))].append(p.stat().st_mtime)
    for d, ts in sorted(md_by_dir.items(), key=lambda kv: -max(kv[1])):
        A(f"| `{d}` | {len(ts)} | {datetime.fromtimestamp(min(ts)):%m-%d} | "
          f"{datetime.fromtimestamp(max(ts)):%m-%d} |")
    A("")

    text = "\n".join(lines)
    out.write_text(text, encoding="utf-8")

    # 控制台只打 ASCII 摘要（避免 GBK 报错）
    print("=" * 70)
    print("workspace clutter audit (read-only)")
    print("=" * 70)
    print(f"  text files hashed      : {text_count}")
    print(f"  binary files           : {bin_count}")
    print(f"  total scanned          : {total_bytes/MB:,.0f} MB")
    print(f"  duplicate groups       : {len(dup_groups)}")
    print(f"  reclaimable (exact dup): {dup_bytes/MB:,.1f} MB")
    print(f"  backup-ish files       : {len(baks)}")
    print()
    print("  top duplicate groups:")
    for i, (h, ps) in enumerate(dup_groups[:15], 1):
        ps_sorted = sorted(ps, key=lambda x: len(x.parts))
        print(f"   {i:2d}. x{len(ps):<3} {ps_sorted[0].stat().st_size/KB:>10,.1f} KB  "
              f"{ps_sorted[0].relative_to(ROOT)}")
    print()
    print(f"  full report -> {out.relative_to(ROOT)}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
