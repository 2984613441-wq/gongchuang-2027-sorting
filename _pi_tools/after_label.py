#!/usr/bin/env python3
"""标注完成后：校验标签 → 合并进数据集 → 报告 → 给出重训命令。

## 用它做什么

在 labelImg 里标完（也删掉了烂图）之后，跑这一个脚本：

```
1. 校验每个 .txt（格式、类别范围、坐标是否 0~1、框面积是否离谱）
2. 找出「有图无标签」「有标签无图」的不一致
3. 统计各类实例数
4. 把新的图+标签合并进 _dataset_yolo_6c_v2（保留原 471 张）
5. 写 data.yaml
6. 打印重训命令
```

## 用法

```bash
# 只看校验结果，不合并（先跑这个看有没有问题）
python _pi_tools/after_label.py --check-only

# 校验通过后合并
python _pi_tools/after_label.py

# 指定新图放 training 还是 val
python _pi_tools/after_label.py --new-to val --val-ratio 0.0
```

默认：**新图全部进 train**（数据少时优先保训练量）。
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 默认标注工作区：images/ 与 labels/ 分开（与 _label_kit 的 proven 结构一致）
#:   _label_review_all/images/   ← 712 张（161 新 + 551 旧）
#:   _label_review_all/labels/   ← 472 个 .txt（551 旧转成 6 类 + 新的）
LABEL_WS = ROOT / "_label_review_all" / "images"
LABELS_WS = ROOT / "_label_review_all" / "labels"

BASE_DS = ROOT / "_dataset_yolo_6c"
OUT_DS = ROOT / "_dataset_yolo_6c_v2"

#: 这些文件名不是标注，跳过
SKIP_TXT = {"classes", "obj", "labels"}

# 6 类（顺序必须与 data.yaml 一致）
CLASS_NAMES = ["cube", "cuboid", "cylinder", "pentagonal_prism",
               "cone", "tetrahedron"]
CLASS_NAMES_ZH = ["正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体"]
NC = len(CLASS_NAMES)

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# 合理性阈值
MIN_BOX_W_H = 0.005      # 归一化宽/高最小值（≈2px @448）
MIN_BOX_AREA = 1e-4      # 归一化面积最小值
MAX_BOX_AREA = 0.95      # 归一化面积最大值

DATA_YAML = """# 6 类 YOLO 数据集 v2（原 471 张 + 手工标注的新图）
# 生成: _pi_tools/after_label.py
#
# ⚠️ cone(class 4) 实例数取决于你标的数量；若为 0 则该类仍检不出

path: {path}
train: images/train
val: images/val

nc: 6
names:
  0: cube
  1: cuboid
  2: cylinder
  3: pentagonal_prism
  4: cone
  5: tetrahedron
"""


def find_image(dir_: Path, stem: str) -> Path | None:
    for ext in IMG_EXTS:
        p = dir_ / (stem + ext)
        if p.is_file():
            return p
    return None


def validate_label(lf: Path) -> tuple[list[str], list[str]]:
    """校验一个标签文件。返回 (合法的行, 问题列表)。"""
    good: list[str] = []
    problems: list[str] = []
    try:
        lines = lf.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [], ["读不了: %s" % exc]

    for i, raw in enumerate(lines, 1):
        ln = raw.strip()
        if not ln:
            continue
        parts = ln.split()
        if len(parts) != 5:
            problems.append("第 %d 行字段数 %d≠5" % (i, len(parts)))
            continue
        try:
            cid = int(float(parts[0]))
            cx, cy, w, h = (float(x) for x in parts[1:5])
        except ValueError:
            problems.append("第 %d 行无法解析" % i)
            continue

        if not (0 <= cid < NC):
            problems.append("第 %d 行类别 %d 超出 0~%d" % (i, cid, NC - 1))
            continue
        if not all(0.0 <= v <= 1.0 for v in (cx, cy, w, h)):
            problems.append("第 %d 行坐标超 0~1: %.3f %.3f %.3f %.3f"
                            % (i, cx, cy, w, h))
            continue
        if w < MIN_BOX_W_H or h < MIN_BOX_W_H:
            problems.append("第 %d 行框太小: %.4f×%.4f" % (i, w, h))
            continue
        area = w * h
        if area < MIN_BOX_AREA:
            problems.append("第 %d 行面积太小: %.6f" % (i, area))
            continue
        if area > MAX_BOX_AREA:
            problems.append("第 %d 行面积太大: %.3f（可能标错）" % (i, area))
            continue

        good.append("%d %.6f %.6f %.6f %.6f" % (cid, cx, cy, w, h))
    return good, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="标注后校验+合并数据集")
    ap.add_argument("--src", default=str(LABEL_WS),
                    help="图片目录（含 .jpg）")
    ap.add_argument("--labels-dir", default=str(LABELS_WS),
                    help="标签目录（默认 _label_ws_6c/labels；"
                         "若与 --src 相同则放到图旁边）")
    ap.add_argument("--check-only", action="store_true",
                    help="只校验不合并")
    ap.add_argument("--out", default=str(OUT_DS))
    ap.add_argument("--new-to", choices=["train", "val", "split"],
                    default="train",
                    help="新图放哪（默认全进 train）")
    ap.add_argument("--val-ratio", type=float, default=0.15,
                    help="--new-to split 时的验证集比例")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    src = Path(args.src)
    if not src.is_dir():
        print("❌ 标注目录不存在: %s" % src)
        return 1

    print("=" * 76)
    print("  标注后校验")
    print("=" * 76)
    print("  目录: %s" % src)
    print()

    # ── 1. 清点 ────────────────────────────────────────────────────
    ldir = Path(args.labels_dir) if args.labels_dir else src
    if not ldir.is_dir():
        print("⚠️ 标签目录不存在: %s（可能还没标）" % ldir)
        ldir = src

    imgs: dict[str, Path] = {}
    for ext in IMG_EXTS:
        for p in src.glob("*" + ext):
            imgs[p.stem] = p
    txts: dict[str, Path] = {
        p.stem: p for p in ldir.glob("*.txt")
        if p.stem.lower() not in SKIP_TXT
    }

    print("  图片目录  : %s" % src)
    print("  标签目录  : %s" % ldir)
    print("  图片      : %d 张" % len(imgs))
    print("  标签文件  : %d 个" % len(txts))
    print()

    no_label = sorted(set(imgs) - set(txts))
    no_image = sorted(set(txts) - set(imgs))
    if no_label:
        print("  ⚠️ 有图无标签（%d）：" % len(no_label))
        for s in no_label[:10]:
            print("      %s" % imgs[s].name)
        if len(no_label) > 10:
            print("      …还有 %d 个" % (len(no_label) - 10))
        print("      ⇒ 如果这些是你要删的烂图，直接在资源管理器删掉即可")
        print("      ⇒ 如果忘了标，回 labelImg 补")
    if no_image:
        print("  ⚠️ 有标签无图（%d）：" % len(no_image))
        for s in no_image[:10]:
            print("      %s.txt" % s)
    print()

    # ── 2. 校验标签 ────────────────────────────────────────────────
    cls_cnt = Counter()
    total_boxes = 0
    bad_files = 0
    for stem, lf in sorted(txts.items()):
        if stem not in imgs:
            continue
        good, problems = validate_label(lf)
        if problems:
            bad_files += 1
            print("  ⚠️ %s：" % lf.name)
            for pr in problems[:5]:
                print("        %s" % pr)
            if len(problems) > 5:
                print("        …还有 %d 条" % (len(problems) - 5))
        for g in good:
            cls_cnt[int(g.split()[0])] += 1
            total_boxes += 1

    print()
    print("  ── 标注统计 ──")
    print("  有效框  : %d 个" % total_boxes)
    print("  有问题  : %d 个文件" % bad_files)
    print()
    print("  %-4s %-16s %-6s %-8s %s" % ("id", "类名", "中文", "实例数", "状态"))
    for cid, (en, zh) in enumerate(zip(CLASS_NAMES, CLASS_NAMES_ZH)):
        n = cls_cnt.get(cid, 0)
        if en == "cone":
            st = "❌ 零数据" if n == 0 else ("✅" if n >= 30 else "⚠️ 偏少")
        else:
            st = "✅" if n >= 20 else ("⚠️ 偏少" if n > 0 else "❌ 零数据")
        print("  %-4d %-16s %-6s %-8d %s" % (cid, en, zh, n, st))
    print()

    if args.check_only:
        print("=" * 76)
        print("  （--check-only，不合并）")
        print("  看起来没问题就跑：python _pi_tools/after_label.py")
        print("=" * 76)
        return 0

    # ── 3. 合并 ────────────────────────────────────────────────────
    base = Path(BASE_DS)
    if not base.is_dir():
        print("❌ 基础数据集不存在: %s" % base)
        return 1
    out = Path(args.out)
    if out.is_dir() and not args.overwrite:
        print("⚠️ 输出已存在: %s" % out)
        print("   加 --overwrite 覆盖")
        return 1
    if out.is_dir():
        shutil.rmtree(out)

    print("=" * 76)
    print("  合并数据集")
    print("=" * 76)
    print("  基础: %s" % base)
    print("  输出: %s" % out)
    print()

    # 先复制基础数据集
    for split in ("train", "val"):
        for sub in ("images", "labels"):
            d = out / sub / split
            d.mkdir(parents=True, exist_ok=True)
            sd = base / sub / split
            if sd.is_dir():
                for f in sd.iterdir():
                    if f.is_file():
                        shutil.copy2(f, d / f.name)
        n_i = len(list((out / "images" / split).iterdir()))
        n_l = len(list((out / "labels" / split).iterdir()))
        print("  基础 %-6s : %d 图 / %d 标签" % (split, n_i, n_l))

    # 新图分配
    stems = [s for s in imgs if s in txts]
    if args.new_to == "split":
        random.Random(args.seed).shuffle(stems)
        n_val = max(1, int(len(stems) * args.val_ratio))
        assign = {s: ("val" if i < n_val else "train")
                  for i, s in enumerate(stems)}
    else:
        assign = {s: args.new_to for s in stems}

    n_added = Counter()
    for stem, split in assign.items():
        img = imgs[stem]
        lf = txts[stem]
        good, _ = validate_label(lf)
        if not good:
            continue
        shutil.copy2(img, out / "images" / split / img.name)
        (out / "labels" / split / (stem + ".txt")).write_text(
            "\n".join(good) + "\n", encoding="utf-8")
        n_added[split] += 1

    print()
    for split in ("train", "val"):
        n_i = len(list((out / "images" / split).iterdir()))
        n_l = len(list((out / "labels" / split).iterdir()))
        print("  合并后 %-6s : %d 图 / %d 标签  （新增 %d）"
              % (split, n_i, n_l, n_added.get(split, 0)))

    # data.yaml
    (out / "data.yaml").write_text(
        DATA_YAML.format(path=str(out).replace("\\", "/")), encoding="utf-8")
    print()
    print("  ✅ 已写 data.yaml")

    # 全量类别统计
    print()
    print("  ── 合并后各类实例数 ──")
    final_cnt = Counter()
    for split in ("train", "val"):
        for lf in (out / "labels" / split).glob("*.txt"):
            for ln in lf.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    final_cnt[int(ln.split()[0])] += 1
                except Exception:
                    pass
    for cid, en in enumerate(CLASS_NAMES):
        print("    %d %-18s %5d" % (cid, en, final_cnt.get(cid, 0)))

    print()
    print("=" * 76)
    print("  ✅ 合并完成")
    print("=" * 76)
    print("  下一步（重训）：")
    print()
    print("    python _pi_tools/train_6class.py --dataset %s "
          "--epochs 120 --name yolo11n_6c_v2 --batch 32 --imgsz 448"
          % out.relative_to(ROOT))
    print()
    print("  训练完再转 cvimodel：")
    print("    python _pi_tools/export_onnx_crop.py "
          "--pt _runs/yolo11n_6c_v2/weights/best.pt --imgsz 448")
    print("    wsl -d Ubuntu -e bash /mnt/c/Users/29845/Desktop/工创赛/"
          "_deploy_maixcam/wsl_convert_6c.sh")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
