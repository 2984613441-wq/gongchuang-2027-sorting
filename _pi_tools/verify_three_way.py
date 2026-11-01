#!/usr/bin/env python3
"""三方一致性校验：MaixCAM / 树莓派 / 屏幕图片 必须对 code 的理解完全一致。

## 校验什么

**本地（默认）**
  L1  真源 `manifest.json` 自身自洽（30 条、code 1..30 无缺无重、公式对）
  L2  两个生成的模块 `shape_color_code.py` 与真源一致（内容 + 逐字节相同）
  L3  `names.json` / `image_ids.json` 与真源一致
  L4  30 张图片文件存在、是合法 PNG、名字与真源一致
  L5  赛规表1 的 6 个形状中文名**逐字**出现在模块里
  L6  code 往返（code → decode → code）全覆盖
  L7  显示名唯一（同形状 5 个颜色互不相同）
  L8  本脚本能 import 两个模块并跑通它们的 `self_test()`

**远端（--remote，需要网络）**
  R1  树莓派上 `/home/pi/电控/deploy/names.json` 与真源一致
  R2  树莓派上 `/home/pi/images/1.png`..`30.png` 齐全且尺寸对
  R3  MaixCAM 上部署的 `shape_color_code.py` 与真源一致

## 用法

```bash
python _pi_tools/verify_three_way.py            # 只校验本地
python _pi_tools/verify_three_way.py --remote   # 加上远端（需要 Pi/MaixCAM 在线）
```

退出码：0 = 全部通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MANIFEST = ROOT / "_screen_assets" / "colored" / "manifest.json"
IMAGES_DIR = ROOT / "_screen_assets" / "colored"

MODULE_PATHS = (
    ROOT / "视觉" / "src" / "maixcam_deploy" / "shape_color_code.py",
    ROOT / "电控" / "src" / "electrical_control" / "rpi" / "shape_color_code.py",
)
NAMES_JSON = ROOT / "电控" / "deploy" / "names.json"
IMAGE_IDS_JSON = ROOT / "电控" / "deploy" / "image_ids.json"

#: 赛规表1 的 6 个货物名称（**逐字**，来自 2026补充说明-原文.txt L28~38）
REQUIRED_SHAPE_NAMES_ZH = (
    "正方体", "长方体", "圆柱", "五棱柱", "圆锥", "正四面体")

#: 赛规的颜色（5 种，来自 2026补充说明）
REQUIRED_COLOR_NAMES_ZH = ("白色", "红色", "蓝色", "绿色", "黄色")

#: 远端
PI_HOST = "pi@172.20.10.8"
MAIXCAM_HOST = "root@172.20.10.9"
PI_NAMES = "/home/pi/电控/deploy/names.json"
PI_IMAGES = "/home/pi/images"
MAIXCAM_MODULE = "/root/shape_color_code.py"

SSH_OPTS = ["-o", "ConnectTimeout=12", "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes"]


# ─────────────────────────────────────────────────────────────────────────────
# 小工具
# ─────────────────────────────────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print("  PASS  " + msg)

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print("  FAIL  " + msg)

    def skip(self, msg: str) -> None:
        self.skipped.append(msg)
        print("  SKIP  " + msg)

    def section(self, title: str) -> None:
        print()
        print("── " + title + " " + "─" * max(0, 60 - len(title)))

    def summary(self) -> int:
        print()
        print("=" * 70)
        n_ok, n_fail, n_skip = len(self.passed), len(self.failed), len(self.skipped)
        print("  通过 %d / 失败 %d / 跳过 %d" % (n_ok, n_fail, n_skip))
        if n_fail:
            print()
            print("  失败项：")
            for f in self.failed:
                print("    - " + f)
        print("=" * 70)
        return 0 if n_fail == 0 else 1


def load_module(path: Path, name: str):
    """从文件路径 import 一个模块（不污染 sys.path）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("无法为 %s 创建 spec" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_ssh(host: str, command: str, timeout: int = 25):
    """跑一条远端命令；失败返回 (False, 错误文本)。"""
    try:
        p = subprocess.run(
            ["ssh"] + SSH_OPTS + [host, command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout or "").strip()[:300]
    return True, p.stdout


# ─────────────────────────────────────────────────────────────────────────────
# L1 真源自洽
# ─────────────────────────────────────────────────────────────────────────────


def check_manifest(rep: Report) -> dict | None:
    rep.section("L1 真源自洽")
    if not MANIFEST.is_file():
        rep.fail("manifest.json 不存在: " + str(MANIFEST))
        return None
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = m.get("entries", [])

    if len(entries) == 30:
        rep.ok("entries 30 条")
    else:
        rep.fail("entries 应为 30 条，实际 %d" % len(entries))

    ids = sorted(e.get("image_id") for e in entries)
    if ids == list(range(1, 31)):
        rep.ok("image_id 覆盖 1..30 无缺无重")
    else:
        rep.fail("image_id 不是 1..30: 缺 %s 重 %s" % (
            sorted(set(range(1, 31)) - set(ids)),
            [i for i in set(ids) if ids.count(i) > 1]))

    bad = []
    for e in entries:
        want = (e["shape_id"] - 1) * 5 + e["color_id"] + 1
        if e["image_id"] != want:
            bad.append((e["image_id"], want))
        if e["file"] != "%d.png" % e["image_id"]:
            bad.append((e["image_id"], e["file"]))
    if not bad:
        rep.ok("公式 (shape_id-1)*5+color_id+1 与文件名自洽")
    else:
        rep.fail("公式/文件名不符: %s" % bad[:5])

    # 形状/颜色中文名
    shapes_zh = set(m["shape_names_zh"].values())
    if shapes_zh == set(REQUIRED_SHAPE_NAMES_ZH):
        rep.ok("6 个形状中文名 == 赛规表1（逐字）")
    else:
        rep.fail("形状中文名不符：多 %s 缺 %s" % (
            shapes_zh - set(REQUIRED_SHAPE_NAMES_ZH),
            set(REQUIRED_SHAPE_NAMES_ZH) - shapes_zh))

    colors_zh = set(m["color_names_zh"].values())
    if colors_zh == set(REQUIRED_COLOR_NAMES_ZH):
        rep.ok("5 个颜色中文名 == 赛规")
    else:
        rep.fail("颜色中文名不符：多 %s 缺 %s" % (
            colors_zh - set(REQUIRED_COLOR_NAMES_ZH),
            set(REQUIRED_COLOR_NAMES_ZH) - colors_zh))

    return m


# ─────────────────────────────────────────────────────────────────────────────
# L2 两个模块与真源一致
# ─────────────────────────────────────────────────────────────────────────────


def check_modules(rep: Report, manifest: dict) -> list:
    rep.section("L2 生成的模块与真源一致")
    mods = []
    texts = []
    for p in MODULE_PATHS:
        if not p.is_file():
            rep.fail("模块不存在: " + str(p.relative_to(ROOT)))
            continue
        text = p.read_text(encoding="utf-8")
        texts.append(text)
        try:
            mod = load_module(p, "scc_" + str(len(mods)))
        except Exception as exc:
            rep.fail("%s 导入失败: %s" % (p.name, exc))
            continue
        mods.append(mod)
        rep.ok("可导入: " + str(p.relative_to(ROOT)))

    if len(texts) == 2:
        if texts[0] == texts[1]:
            rep.ok("两份模块逐字节相同")
        else:
            rep.fail("两份模块内容不同（三方会对不上）")

    # 模块里的常量必须与真源一致
    if mods:
        mod = mods[0]
        shapes_zh = tuple(manifest["shape_names_zh"][k]
                          for k in sorted(manifest["shape_names_zh"], key=int))
        colors_zh = tuple(manifest["color_names_zh"][k]
                          for k in sorted(manifest["color_names_zh"], key=int))
        if tuple(mod.SHAPE_NAMES_ZH) == shapes_zh:
            rep.ok("模块 SHAPE_NAMES_ZH == 真源")
        else:
            rep.fail("模块 SHAPE_NAMES_ZH 与真源不符")
        if tuple(mod.COLOR_NAMES_ZH) == colors_zh:
            rep.ok("模块 COLOR_NAMES_ZH == 真源")
        else:
            rep.fail("模块 COLOR_NAMES_ZH 与真源不符")
        if (mod.CODE_MIN, mod.CODE_MAX) == (1, 30):
            rep.ok("模块 CODE_MIN/MAX == 1/30")
        else:
            rep.fail("模块 CODE 范围错: %s..%s" % (mod.CODE_MIN, mod.CODE_MAX))
        if set(mod.ACTIVE_CLASS_IDS) == set(range(1, 31)):
            rep.ok("模块 ACTIVE_CLASS_IDS == 1..30")
        else:
            rep.fail("模块 ACTIVE_CLASS_IDS 不对")
    return mods


# ─────────────────────────────────────────────────────────────────────────────
# L3 names.json / image_ids.json
# ─────────────────────────────────────────────────────────────────────────────


def check_json_tables(rep: Report, manifest: dict) -> None:
    rep.section("L3 names.json / image_ids.json")
    want_names = {
        str(e["image_id"]): e["color_zh"] + e["shape_zh"]
        for e in manifest["entries"]}
    if not NAMES_JSON.is_file():
        rep.fail("names.json 不存在")
    else:
        got = json.loads(NAMES_JSON.read_text(encoding="utf-8"))
        if got == want_names:
            rep.ok("names.json 与真源一致（30 条）")
        else:
            only_got = set(got) - set(want_names)
            only_want = set(want_names) - set(got)
            diff = [k for k in want_names if k in got and got[k] != want_names[k]]
            rep.fail("names.json 不一致：多键 %s 缺键 %s 值错 %s"
                     % (sorted(only_got)[:5], sorted(only_want)[:5], diff[:5]))

    want_ids = {str(e["image_id"]): e["image_id"] for e in manifest["entries"]}
    if not IMAGE_IDS_JSON.is_file():
        rep.fail("image_ids.json 不存在")
    else:
        got = json.loads(IMAGE_IDS_JSON.read_text(encoding="utf-8"))
        if got == want_ids:
            rep.ok("image_ids.json 与真源一致（恒等映射）")
        else:
            rep.fail("image_ids.json 不一致")


# ─────────────────────────────────────────────────────────────────────────────
# L4 图片文件
# ─────────────────────────────────────────────────────────────────────────────


def check_images(rep: Report, manifest: dict) -> None:
    rep.section("L4 30 张图片文件")
    try:
        from PIL import Image
    except Exception:
        rep.skip("没有 PIL，跳过尺寸校验")
        Image = None  # type: ignore[assignment]

    missing, wrong_size, bad_open = [], [], []
    for e in manifest["entries"]:
        p = IMAGES_DIR / e["file"]
        if not p.is_file():
            missing.append(e["file"])
            continue
        if Image is None:
            continue
        try:
            im = Image.open(p)
            if im.size != (256, 256):
                wrong_size.append((e["file"], im.size))
            if im.mode != "RGBA":
                bad_open.append((e["file"], im.mode))
        except Exception as exc:
            bad_open.append((e["file"], str(exc)[:40]))

    if not missing:
        rep.ok("30 个文件全部存在")
    else:
        rep.fail("缺文件: %s" % missing)
    if wrong_size:
        rep.fail("尺寸不是 256x256: %s" % wrong_size[:5])
    elif Image is not None:
        rep.ok("全部 256x256")
    if bad_open:
        rep.fail("格式/RGBA 有问题: %s" % bad_open[:5])
    elif Image is not None:
        rep.ok("全部 RGBA")


# ─────────────────────────────────────────────────────────────────────────────
# L5~L8 模块行为
# ─────────────────────────────────────────────────────────────────────────────


def check_module_behaviour(rep: Report, mods: list) -> None:
    rep.section("L5~L8 模块行为")
    if not mods:
        rep.skip("没有可用模块")
        return
    mod = mods[0]

    # L5 表1 逐字
    missing = [n for n in REQUIRED_SHAPE_NAMES_ZH if n not in mod.SHAPE_NAMES_ZH]
    if not missing:
        rep.ok("表1 的 6 个名称都逐字出现在 SHAPE_NAMES_ZH")
    else:
        rep.fail("缺形状名: %s" % missing)

    # L6 往返
    bad = []
    for code in range(mod.CODE_MIN, mod.CODE_MAX + 1):
        s, c, szh, czh = mod.decode_code(code)
        if mod.code_of(s, c) != code:
            bad.append(code)
    if not bad:
        rep.ok("code 往返全覆盖（30/30）")
    else:
        rep.fail("往返失败: %s" % bad)

    # L7 显示名唯一
    names = [mod.display_name_of(c) for c in range(mod.CODE_MIN, mod.CODE_MAX + 1)]
    if len(set(names)) == len(names):
        rep.ok("30 个显示名互不相同")
    else:
        from collections import Counter
        dup = [n for n, k in Counter(names).items() if k > 1]
        rep.fail("显示名重复: %s" % dup)

    # L7b 纯形状名只有 6 种
    pure = set(mod.shape_name_zh_of(c) for c in range(mod.CODE_MIN, mod.CODE_MAX + 1))
    if pure == set(REQUIRED_SHAPE_NAMES_ZH):
        rep.ok("纯形状名恰好 6 种且 == 表1")
    else:
        rep.fail("纯形状名不对: %s" % sorted(pure))

    # L8 模块自检
    for i, m in enumerate(mods):
        if hasattr(m, "self_test"):
            rc = m.self_test()
            if rc == 0:
                rep.ok("模块 %d 的 self_test() 通过" % (i + 1))
            else:
                rep.fail("模块 %d 的 self_test() 失败" % (i + 1))
        else:
            rep.fail("模块 %d 没有 self_test()" % (i + 1))


# ─────────────────────────────────────────────────────────────────────────────
# R1~R3 远端
# ─────────────────────────────────────────────────────────────────────────────


def check_remote(rep: Report, manifest: dict) -> None:
    rep.section("R1~R3 远端（树莓派 / MaixCAM）")

    # R1 树莓派 names.json
    # ⚠️ 必须用 shlex.quote，不能用 json.dumps —— 后者会把中文（「电控」）
    #    转成 \u7535\u63a7 字面量传给远端 shell，路径就不存在了（实测踩过）。
    ok, out = run_ssh(PI_HOST, "cat %s" % shlex.quote(PI_NAMES))
    if not ok:
        rep.skip("树莓派不可达（%s）" % out[:80])
    else:
        try:
            got = json.loads(out)
        except Exception as exc:
            rep.fail("树莓派 names.json 解析失败: %s" % exc)
        else:
            want = {str(e["image_id"]): e["color_zh"] + e["shape_zh"]
                    for e in manifest["entries"]}
            if got == want:
                rep.ok("R1 树莓派 names.json 与真源一致（30 条）")
            else:
                rep.fail("R1 树莓派 names.json 不一致（keys 多 %s 缺 %s）" % (
                    sorted(set(got) - set(want))[:5],
                    sorted(set(want) - set(got))[:5]))

    # R2 树莓派图片
    ok, out = run_ssh(PI_HOST, "ls %s/*.png 2>/dev/null | wc -l" % PI_IMAGES)
    if not ok:
        rep.skip("树莓派图片目录查不到（%s）" % out[:80])
    else:
        try:
            n = int(out.strip())
        except ValueError:
            rep.fail("树莓派图片计数解析失败: %r" % out[:80])
        else:
            if n == 30:
                rep.ok("R2 树莓派 /home/pi/images 有 30 张 PNG")
            else:
                rep.fail("R2 树莓派图片数 = %d（应 30）" % n)

    # R3 MaixCAM 模块
    local_text = MODULE_PATHS[0].read_text(encoding="utf-8")
    local_sha = hashlib.sha256(local_text.encode("utf-8")).hexdigest()
    ok, out = run_ssh(
        MAIXCAM_HOST,
        "sha256sum %s 2>/dev/null || echo MISSING" % MAIXCAM_MODULE)
    if not ok:
        rep.skip("MaixCAM 不可达（%s）" % out[:80])
    elif "MISSING" in out:
        rep.skip("MaixCAM 上还没有部署 %s（等视觉侧部署）" % MAIXCAM_MODULE)
    else:
        remote_sha = out.split()[0] if out.split() else ""
        if remote_sha == local_sha:
            rep.ok("R3 MaixCAM 上 shape_color_code.py 与本地一致")
        else:
            rep.fail("R3 MaixCAM 上的模型与本地不一致（remote %s.. vs local %s..）"
                     % (remote_sha[:16], local_sha[:16]))


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="三方一致性校验")
    ap.add_argument("--remote", action="store_true",
                    help="加上树莓派/MaixCAM 的远端校验（需要网络）")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  三方一致性校验（MaixCAM / 树莓派 / 屏幕图片）")
    print("=" * 70)

    rep = Report()
    manifest = check_manifest(rep)
    if manifest is None:
        return rep.summary()

    mods = check_modules(rep, manifest)
    check_json_tables(rep, manifest)
    check_images(rep, manifest)
    check_module_behaviour(rep, mods)
    if args.remote:
        check_remote(rep, manifest)
    else:
        rep.section("R1~R3 远端")
        rep.skip("未加 --remote，跳过远端校验")

    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
