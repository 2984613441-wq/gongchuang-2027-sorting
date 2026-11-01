#!/usr/bin/env python3
"""把「我从 200px 拼图判的形」写成 labelImg 可复核的标签。

## 与 make_review_v7.py 的区别

  make_review_v7.py  → 用 v7 预测当预标注（在**新构图**下域偏移严重，
                       实测把六棱柱/黄方块/红方块全判成 cylinder）
  本脚本              → 用 label_overrides_20261028.py 里**我逐格判读**的结果

⇒ 复核工作区的标签应当以本脚本为准。

## 输出（覆盖 _review_20261028/labels/*.txt）

    <out>/images/*.jpg      帧（若不存在则从 all/ 复制）
    <out>/labels/*.txt      YOLO 标注（我判的）
    <out>/classes.txt       六类（无 BOM）
    <out>/pred_info.json    每个框的来源说明

## 用法

    python _pi_tools/make_review_from_overrides.py --base _new_capture_20261028 --out _review_20261028
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "_pi_tools"))

ZH = {"cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
      "pentagonal_prism": "五棱柱", "cone": "圆锥", "tetrahedron": "正四面体"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overrides", default="label_overrides_20261028",
                    help="判读结果模块名（_pi_tools 下），默认 20261028 那批")
    args = ap.parse_args(argv)

    # 动态导入判读结果模块（20261028 与 20261028b 两批结构相同）
    import importlib
    ov = importlib.import_module(args.overrides)
    build_class_map = ov.build_class_map
    CLASS_NAMES = ov.CLASS_NAMES

    base = Path(args.base)
    if not base.is_absolute():
        base = ROOT / base
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    all_dir = base / "all"
    idx_path = base / "_crops" / "index.json"
    if not idx_path.is_file():
        print("❌ 缺 %s（先跑 make_object_montages.py）" % idx_path)
        return 1

    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    gid2cls = build_class_map()

    # frame -> [(cls, x,y,w,h)]
    per_frame: dict[str, list] = defaultdict(list)
    n_skip = 0
    for it in idx:
        g = int(it["gid"])
        if g not in gid2cls:
            n_skip += 1
            continue
        per_frame[it["frame"]].append(
            (gid2cls[g], int(it["x"]), int(it["y"]), int(it["w"]), int(it["h"])))

    img_dir = out / "images"
    lbl_dir = out / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    W, H = 1280.0, 720.0
    n_frame = 0
    n_box = 0
    cnt = Counter()
    info = {}

    # 先清掉旧的 txt（避免残留 v7 预标注）
    for old in lbl_dir.glob("*.txt"):
        if old.name != "classes.txt":
            old.unlink()

    for fname, boxes in sorted(per_frame.items()):
        src = all_dir / fname
        if not src.is_file():
            print("  ⚠️ 缺图: %s" % fname)
            continue
        dst = img_dir / fname
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
        lines = []
        recs = []
        for cls, x, y, w, h in boxes:
            cx = (x + w / 2.0) / W
            cy = (y + h / 2.0) / H
            bw, bh = w / W, h / H
            cx = min(max(cx, 0.0), 1.0)
            cy = min(max(cy, 0.0), 1.0)
            bw = min(max(bw, 1e-6), 1.0)
            bh = min(max(bh, 1e-6), 1.0)
            lines.append("%d %.6f %.6f %.6f %.6f" % (cls, cx, cy, bw, bh))
            cnt[CLASS_NAMES[cls]] += 1
            recs.append({"cls": CLASS_NAMES[cls], "zh": ZH[CLASS_NAMES[cls]]})
        (lbl_dir / (Path(fname).stem + ".txt")).write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        info[fname] = recs
        n_frame += 1
        n_box += len(lines)

    # 空标签帧（v7 没找到物件的）也保留，供用户确认是否废帧
    for src in sorted(all_dir.glob("*.jpg")):
        lp = lbl_dir / (src.stem + ".txt")
        if lp.exists():
            continue
        dst = img_dir / src.name
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
        lp.write_text("", encoding="utf-8")

    def write_no_bom(p: Path, text: str) -> None:
        p.write_bytes(text.encode("utf-8"))

    cls_text = "\n".join(CLASS_NAMES) + "\n"
    write_no_bom(out / "classes.txt", cls_text)
    write_no_bom(out / "predefined_classes.txt", cls_text)
    write_no_bom(lbl_dir / "classes.txt", cls_text)
    (out / "pred_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    n_lbl_files = len(list(lbl_dir.glob("*.txt"))) - 1   # 减掉 classes.txt
    n_empty = n_lbl_files - n_frame
    print("=" * 74)
    print("  ✅ 复核工作区已更新（标签来自我在 200px 拼图上的逐格判读）")
    print("=" * 74)
    print("  有标签帧 : %d" % n_frame)
    print("  标注框   : %d" % n_box)
    print("  跳过(X)  : %d 个裁片（手指/电线/废裁片）" % n_skip)
    print("  空标签帧 : %d（v7 未检出，请确认是否废帧）" % n_empty)
    print()
    print("  类别分布（我判的）:")
    for k in CLASS_NAMES:
        if cnt.get(k):
            print("    %-18s %3d  (%s)" % (k, cnt[k], ZH[k]))
    print()
    print("  图片目录: %s" % img_dir)
    print("  标签目录: %s" % lbl_dir)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
