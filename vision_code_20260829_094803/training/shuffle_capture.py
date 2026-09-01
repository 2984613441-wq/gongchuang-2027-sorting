#!/usr/bin/env python3
"""把工作区采集照片拍平 + 打乱浏览顺序，供 LabelImg 人工标注。

读取 capture/<session_*>/img_*.jpg（可选同名 .txt 预标注），拍平到单个
目录，用 seed=42 随机打乱后按 img_00000..img_00187 顺序重命名，
jpg 与 txt 始终保持同名对应。没有预标注的图片补一个空 .txt，让标注
工具对所有图片一视同仁（0 框 = 从零标）。

输出目录：img_%05d.jpg + img_%05d.txt + classes.txt（7 类，顺序与模型一致）。
"""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

CLASSES = (
    "cube",
    "cuboid",
    "cylinder",
    "hexagonal_prism",
    "pentagonal_prism",
    "square_pyramid",
    "triangular_prism",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True,
                        help="采集根目录（含 session_*/ 子目录）")
    parser.add_argument("--out", type=Path, required=True,
                        help="输出目录（拍平 + 打乱后的图片/标签）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    jpgs = sorted(args.capture.glob("session_*/img_*.jpg"))
    if not jpgs:
        raise SystemExit(f"未在 {args.capture} 下找到 session_*/img_*.jpg")

    pairs: list[tuple[Path, Path | None]] = []
    for jpg in jpgs:
        txt = jpg.with_suffix(".txt")
        pairs.append((jpg, txt if txt.is_file() else None))

    rng = random.Random(args.seed)
    rng.shuffle(pairs)

    args.out.mkdir(parents=True, exist_ok=True)
    # 清掉可能残留的旧文件，避免重跑时留下高位编号的陈旧图片
    for stale in args.out.glob("img_*.jpg"):
        stale.unlink()
    for stale in args.out.glob("img_*.txt"):
        stale.unlink()
    (args.out / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")

    n_labeled = 0
    for i, (jpg, txt) in enumerate(pairs):
        new_jpg = args.out / f"img_{i:05d}.jpg"
        new_txt = args.out / f"img_{i:05d}.txt"
        shutil.copy2(jpg, new_jpg)
        if txt is not None:
            shutil.copy2(txt, new_txt)
            n_labeled += 1
        else:
            new_txt.write_text("", encoding="utf-8")

    print(f"shuffled {len(pairs)} images -> {args.out}")
    print(f"  with draft label : {n_labeled}")
    print(f"  empty label      : {len(pairs) - n_labeled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
