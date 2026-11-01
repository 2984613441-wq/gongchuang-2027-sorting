#!/usr/bin/env python3
"""修复 labelImg 设置文件（被上一条命令清空了内容）。

## 背景

上一条一行命令里用了 `Settings().load()`，而 labelImg 的 `load()` 内部是
`except: print('Loading setting failed')` —— 你看到的 **Loading setting failed**
说明它没读出来，随后我又 `save()`，于是把 `~/.labelImgSettings.pkl` 覆盖成了
**只剩 paintlabel 一个键**，`labelFileFormat=YOLO` 也被清掉了。

本脚本**不读取旧文件**，直接写一份完整、类型正确的设置：

    labelFileFormat = YOLO（2）      ← 关键，否则保存会变 XML
    paintlabel      = True           ← 框上显示类别名
    lastOpenDir     = 复核工程的 images
    savedir         = 复核工程的 labels
    autosave        = False

## 用法（先关掉 labelImg 再跑）

    "D:\\Anaconda\\envs\\labelimg\\python.exe" _fix_labelimg_settings.py

    # 只测不写（写到临时文件，用于自检）
    "D:\\Anaconda\\envs\\labelimg\\python.exe" _fix_labelimg_settings.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys

SP = r"D:\Anaconda\envs\labelimg\Lib\site-packages"
IMAGES = r"C:\Users\29845\Desktop\工创赛\_review_20261030b\images"
LABELS = r"C:\Users\29845\Desktop\工创赛\_review_20261030b\labels"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="", help="设置文件路径（默认 ~/.labelImgSettings.pkl）")
    ap.add_argument("--dry-run", action="store_true", help="写到临时文件，不动真实设置")
    args = ap.parse_args()

    if SP not in sys.path:
        sys.path.insert(0, SP)
    try:
        from libs.labelFile import LabelFileFormat       # 需要 PyQt5，labelimg 环境里有
    except Exception as e:
        print("❌ 无法导入 labelImg 模块（必须用 labelimg 环境的 python）: %r" % e)
        return 1

    path = args.path or os.path.join(os.path.expanduser("~"), ".labelImgSettings.pkl")
    if args.dry_run:
        path = os.path.join(os.getcwd(), "_tmp_labelImgSettings.pkl")

    data = {
        "labelFileFormat": LabelFileFormat.YOLO,
        "paintlabel": True,
        "autosave": False,
        "singleclass": False,
        "advanced": False,
        "draw/square": False,
        "lastOpenDir": IMAGES,
        "savedir": LABELS,
        "filename": "",
        "recentFiles": [],
    }
    if os.path.exists(path) and not args.dry_run:
        bak = path + ".bak-fix"
        try:
            os.replace(path, bak)
            print("旧设置已备份：%s" % bak)
        except Exception as e:
            print("⚠️ 备份失败（继续写新文件）：%r" % e)
    with open(path, "wb") as f:
        pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)
    print("已写入：%s" % path)

    # 回读验证
    with open(path, "rb") as f:
        back = pickle.load(f)
    fmt = back.get("labelFileFormat")
    print("回读：labelFileFormat=%s(%s)  paintlabel=%s" % (fmt, getattr(fmt, "value", "?"),
                                                          back.get("paintlabel")))
    print("      lastOpenDir=%s" % back.get("lastOpenDir"))
    print("      savedir    =%s" % back.get("savedir"))
    ok = back.get("paintlabel") is True and getattr(fmt, "name", "") == "YOLO"
    print("结果：" + ("✅ 正确（YOLO + 显示标签）" if ok else "❌ 异常"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
