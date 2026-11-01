#!/usr/bin/env python3
"""构建副相机「6 类形状」复核工程 `_review_20261030d`（labelImg 用）。

## 为什么是 6 类形状（不是颜色）

`docs/交接文档-全量状态-20261029.md:1096` 明确副相机职责是
「远端件 **存在性 / 颜色 / 形状相容** 确证」；`:1052` CONFIRMED 要求
「颜色一致 + 形状证据相容」；`:1066` 阶段 2 要求「**同类 + 同色**」。

一个 YOLO 框只能带一个类，所以：
  · **形状** → 标进 YOLO（6 类，与主相机同顺序，便于直接比"同类"）
  · **颜色** → 不在标签里，运行时对该框做 HSV 判定（件是纯色，稳、几毫秒）

## 初值来源

`_labels_cam2/<session>/suggest.json`（颜色检测出框 + 轮廓几何给形状猜测）
⇒ 框位置可用，**类别是几何猜测**，`geom_conf` 一起写进 pred_info.json 供你判断先改哪个。

## 用法

    python _build_review_cam2_shape.py
"""

from __future__ import annotations

import glob
import json
import os
import shutil

OUT = "_review_20261030d"
SESSIONS = [
    ("124653", r"_dataset_cam2\cam2_20261030-124653_curated", r"_labels_cam2\cam2_20261030-124653\suggest.json"),
    ("124920", r"_dataset_cam2\cam2_20261030-124920_curated", r"_labels_cam2\cam2_20261030-124920\suggest.json"),
]
CLASSES = ["cube", "cuboid", "cylinder", "pentagonal_prism", "cone", "tetrahedron"]
W, H = 1280, 720

README = """副相机复核（2026-10-30）labelImg 工程 —— 6 类形状
==========================================================
类别顺序（与主相机一致）：cube(0) cuboid(1) cylinder(2) pentagonal_prism(3) cone(4) tetrahedron(5)
颜色不在标签里：运行时对框内做 HSV 判色（副相机只要"同类+同色"证据，见交接文档 §13.2/§13.5）
数据：124653(48张) + 124920(55张) = 103 张；预标框见 pred_info.json

【重要】框位置基本可用，但**类别是几何猜测**（斜侧视，cone/tetra/cube/cuboid 极易混）
  → pred_info.json 里每个框都有 geom_conf（0.35~0.80）：
     · geom_conf >= 0.70：大概对（圆柱/四边面），快速扫一眼
     · geom_conf <= 0.45：**基本都要改**（尤其三角形：cone vs tetrahedron）

【已知缺陷】
 1. **白件没有预标**（白件与白托盘同色）→ 手动补框，类按形状选
 2. 托盘左右分格框边缘的假框 → 删
 3. 画面下沿被切的件可能漏框 → 补
 4. 手部帧：留（框住件）或整帧清空
 5. 重复框/同件双框 → 删一个

【快捷键】W 画框 / Ctrl+S 保存 / D 下一张 / A 上一张 / 双击框改类 / Del 删框
          Ctrl+R 清空 / Ctrl+Shift+P 显示标签文字

【改完】关窗口，labels/ 即最终结果；无标注的帧会被清出数据集（与主相机同规则）
"""


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "images"))
    os.makedirs(os.path.join(OUT, "labels"))
    cls_txt = "\n".join(CLASSES) + "\n"
    for rel in ("classes.txt", "predefined_classes.txt",
                os.path.join("images", "classes.txt"), os.path.join("labels", "classes.txt")):
        with open(os.path.join(OUT, rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(cls_txt)
    with open(os.path.join(OUT, "复核说明.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(README)

    info = {}
    n_img = n_box = 0
    stat = {c: 0 for c in CLASSES}
    by_conf = {"high(>=0.70)": 0, "mid(0.55-0.70)": 0, "low(<0.55)": 0}
    for tag, img_dir, sug_json in SESSIONS:
        sug = json.load(open(sug_json, encoding="utf-8"))
        for p in sorted(glob.glob(os.path.join(img_dir, "*.jpg"))):
            base = os.path.basename(p)
            new = "%s__%s" % (tag, base)
            shutil.copy2(p, os.path.join(OUT, "images", new))
            n_img += 1
            objs = sug.get(base, [])
            lines, recs = [], []
            for r in objs:
                c = r.get("cls")
                if c not in CLASSES:
                    continue
                x1, y1 = r["bx"], r["by"]
                bw, bh = r["bw"], r["bh"]
                cx = (x1 + bw / 2.0) / W
                cy = (y1 + bh / 2.0) / H
                lines.append("%d %.6f %.6f %.6f %.6f\n" % (CLASSES.index(c), cx, cy, bw / W, bh / H))
                gc = float(r.get("geom_conf", 0.0))
                stat[c] += 1
                n_box += 1
                by_conf["high(>=0.70)" if gc >= 0.70 else ("mid(0.55-0.70)" if gc >= 0.55 else "low(<0.55)")] += 1
                recs.append({"cls": c, "color": r.get("color"), "geom_conf": gc,
                             "box_px": [x1, y1, x1 + bw, y1 + bh]})
            with open(os.path.join(OUT, "labels", os.path.splitext(new)[0] + ".txt"),
                      "w", encoding="utf-8", newline="\n") as f:
                f.writelines(lines)
            info[new] = recs

    with open(os.path.join(OUT, "pred_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)

    print("=" * 66)
    print("构建完成：%s" % OUT)
    print("  图片 %d 张｜预标框 %d 个" % (n_img, n_box))
    print("  形状分布：" + "  ".join("%s=%d" % (c, stat[c]) for c in CLASSES))
    print("  置信分层：" + "  ".join("%s=%d" % (k, v) for k, v in by_conf.items()))
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
