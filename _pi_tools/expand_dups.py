#!/usr/bin/env python3
"""把「代表帧的判定」自动铺满所有重复帧 —— 保证 161 张新图全部有标签。

## 为什么需要

161 帧里有 49 帧是「像素级重复」（同一摆放，1 秒间隔拍多张）。
我只需判 112 个唯一布局，其余 49 帧用 COPY 自动继承标签。

本脚本读 `dup_groups.json`（重复分组）+ `my_shapes.json`（我的判定），
把每个组里**代表帧的判定**复制到**同组其他帧**，产出 `my_shapes_full.json`。

## 用法

```bash
python _pi_tools/expand_dups.py            # 生成 my_shapes_full.json
python _pi_tools/expand_dups.py --dry-run
```
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "_label_ws_6c"
SHEETS = WS / "_sheets"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    gf = SHEETS / "dup_groups.json"
    sf = SHEETS / "my_shapes.json"
    if not gf.is_file() or not sf.is_file():
        print("❌ 缺 dup_groups.json 或 my_shapes.json")
        return 1

    groups = json.loads(gf.read_text(encoding="utf-8"))
    shapes = json.loads(sf.read_text(encoding="utf-8"))

    # 追加式补丁：_sheets/patch_*.json 会按文件名顺序合并进来。
    # 这样每批判定只需写一个很小的补丁文件，不必重写整份 my_shapes.json。
    patches = sorted(SHEETS.glob("patch_*.json"))
    n_patch = 0
    for pf in patches:
        try:
            extra = json.loads(pf.read_text(encoding="utf-8"))
        except Exception as exc:
            print("  ⚠️ 补丁读取失败 %s: %s" % (pf.name, exc))
            continue
        for k, v in extra.items():
            if k not in shapes:
                shapes[k] = v
                n_patch += 1
    if n_patch:
        print("  并入补丁: %d 条（来自 %d 个 patch 文件）"
              % (n_patch, len(patches)))

    # 自动筛掉的帧（空托盘 / 手造成的巨型框 / 物件过多）直接作为 SKIP 并入
    af = SHEETS / "auto_skip.json"
    if af.is_file():
        auto = json.loads(af.read_text(encoding="utf-8"))
        n_auto = 0
        for fname in auto:
            if fname not in shapes:
                shapes[fname] = "SKIP"
                n_auto += 1
        if n_auto:
            print("  并入 auto_skip: %d 帧标 SKIP" % n_auto)

    out = dict(shapes)
    n_filled = 0
    n_pending_group = 0
    pending = []

    for grp in groups:
        rep = grp[0]
        if rep not in shapes:
            n_pending_group += 1
            pending.append(rep)
            continue
        val = shapes[rep]
        for other in grp[1:]:
            if other in out:
                continue
            # ⚠️ 一律用 COPY:代表帧，不要直接复制编号字典。
            #    因为重复帧自己在 boxes_all.json 里没有框数据（只检测了代表帧），
            #    直接复制字典会导致 merge 阶段「没有检测结果」。
            out[other] = "COPY:%s" % rep
            n_filled += 1

    allf = sorted(p.name for p in (WS / "images").glob("img_*.jpg"))
    missing = [f for f in allf if f not in out]

    print("=" * 74)
    print("  重复帧标签铺满%s" % ("（DRY-RUN）" if args.dry_run else ""))
    print("=" * 74)
    print("  重复分组     : %d 组" % len(groups))
    print("  我的判定     : %d 帧" % len(shapes))
    print("  自动铺满     : %d 帧" % n_filled)
    print("  合计有标签   : %d / %d 帧" % (len(allf) - len(missing), len(allf)))
    print()
    if n_pending_group:
        print("  ⏳ 还有 %d 组代表帧未判（这些组暂时无标签）:" % n_pending_group)
        for r in pending[:12]:
            print("      %s" % r)
        if len(pending) > 12:
            print("      …还有 %d 个" % (len(pending) - 12))
        print()
    if missing and not n_pending_group:
        print("  ⚠️ 仍未覆盖 %d 帧（可能是分组外）: %s"
              % (len(missing), ", ".join(missing[:8])))

    if not args.dry_run:
        of = SHEETS / "my_shapes_full.json"
        of.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print("  ✅ 已写 %s" % of)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
