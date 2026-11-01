#!/usr/bin/env python3
"""构建副相机复核工程 `_review_20261030c`（labelImg 用，颜色口径）。

## 口径说明

副相机在生产链里只做「存在性 + 颜色」确证（见交接文档 §13/§17），
所以这里 **class = 颜色**，不是 6 类形状：

    0 red / 1 yellow / 2 green / 3 blue / 4 white

来源：
    _dataset_cam2\\cam2_20261030-124653_curated   48 张
    _dataset_cam2\\cam2_20261030-124920_curated   55 张
    _labels_cam2\\cam2_20261030-124653\\labels    179 框
    _labels_cam2\\cam2_20261030-124920\\labels    184 框

两个会话的图片重名（都叫 img_000xx），所以统一加会话后缀前缀
`124653__` / `124920__`，避免互相覆盖。
"""

from __future__ import annotations

import glob
import json
import os
import shutil

OUT = "_review_20261030c"
SESSIONS = [
    ("124653", r"_dataset_cam2\cam2_20261030-124653_curated", r"_labels_cam2\cam2_20261030-124653\labels"),
    ("124920", r"_dataset_cam2\cam2_20261030-124920_curated", r"_labels_cam2\cam2_20261030-124920\labels"),
]
COLS = ["red", "yellow", "green", "blue", "white"]
SHORT = {"red": "red", "yellow": "yellow", "green": "green", "blue": "blue", "white": "white"}

README = """副相机复核（2026-10-30 采集）labelImg 工程
=====================================================
口径：**class = 颜色**（副相机只做存在性+颜色确证，形状由主相机负责）
类别顺序：red(0) yellow(1) green(2) blue(3) white(4)
来源：两次采集会话 124653(48张) + 124920(55张) = 103 张，预标 363 框
文件名前缀：124653__ / 124920__（两个会话原本图片重名）

【已知缺陷，复核重点】
 1. **白件没有预标**（白件与白托盘同色，自动规则跳过）→ 看到白色件请手动补框，类选 white
 2. 托盘左右分格框边缘有零星**假框**（橘色/绿色误判）→ 删掉
 3. 画面最下沿被切的件可能**漏框** → 补
 4. 有若干**手部帧**（手在画面里拿件）→ 你判断：留（框住件）或整帧清空作废
 5. 颜色误判：绿/黄在暖光下可能互串 → 双击框改类

【快捷键】W 画框 / Ctrl+S 保存 / D 下一张 / A 上一张 / 双击框改类 / Del 删框 / Ctrl+R 清空 / Ctrl+Shift+P 显示标签

【改完】关掉窗口，labels/ 即最终结果。
"""


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "images"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "labels"), exist_ok=True)

    classes_txt = "\n".join(COLS) + "\n"
    for rel in ("classes.txt", "predefined_classes.txt",
                os.path.join("images", "classes.txt"), os.path.join("labels", "classes.txt")):
        with open(os.path.join(OUT, rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(classes_txt)
    with open(os.path.join(OUT, "复核说明.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(README)

    info, nimg, nbox, stat = {}, 0, 0, {}
    for tag, img_dir, lab_dir in SESSIONS:
        for p in sorted(glob.glob(os.path.join(img_dir, "*.jpg"))):
            base = os.path.basename(p)
            new = "%s__%s" % (tag, base)
            shutil.copy2(p, os.path.join(OUT, "images", new))
            nimg += 1
            lp = os.path.join(lab_dir, os.path.splitext(base)[0] + ".txt")
            boxes = []
            if os.path.exists(lp):
                lines = []
                for ln in open(lp, encoding="utf-8"):
                    t = ln.split()
                    if len(t) != 5:
                        continue
                    ci = int(t[0])
                    if ci < 0 or ci >= len(COLS):
                        continue
                    lines.append(" ".join(t) + "\n")
                    cx, cy, w, h = map(float, t[1:5])
                    boxes.append({"cls": COLS[ci], "cx": cx, "cy": cy, "w": w, "h": h})
                    stat[COLS[ci]] = stat.get(COLS[ci], 0) + 1
                    nbox += 1
                with open(os.path.join(OUT, "labels", os.path.splitext(new)[0] + ".txt"),
                          "w", encoding="utf-8", newline="\n") as f:
                    f.writelines(lines)
            info[new] = boxes

    with open(os.path.join(OUT, "pred_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)

    print("=" * 62)
    print("构建完成：%s" % OUT)
    print("  图片 %d 张｜预标框 %d 个" % (nimg, nbox))
    print("  颜色分布：" + "  ".join("%s=%d" % (c, stat.get(c, 0)) for c in COLS))
    print("  classes 顺序：" + " ".join("%s(%d)" % (c, i) for i, c in enumerate(COLS)))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
