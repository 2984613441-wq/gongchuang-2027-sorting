#!/usr/bin/env python3
"""单一真源生成器：从 manifest.json 生成三方共用的代码/配置。

## 为什么要有这个脚本

省赛要求视觉侧、树莓派侧、屏幕图片三方对 `code` 的理解**完全一致**：

```
code = (shape_id - 1) * 5 + color_id + 1        # 1..30
  shape_id ∈ 1..6   (1=正方体 2=长方体 3=圆柱 4=五棱柱 5=圆锥 6=正四面体)
  color_id ∈ 0..4   (0=红 1=黄 2=绿 3=蓝 4=白)
```

任何一方错一位 ⇒ 全部错位 ⇒ 屏幕显示错 + 货格分配错 ⇒ **混装 0 分**。

所以：
- **唯一真源** = `_screen_assets/colored/manifest.json`
- **本脚本**从真源生成：
  1. `视觉/src/maixcam_deploy/shape_color_code.py`（MaixCAM 侧）
  2. `电控/src/electrical_control/rpi/shape_color_code.py`（树莓派侧）
     两份**内容完全相同**，只是放在不同目录方便各自 import
  3. `电控/deploy/names.json`（屏幕名称表，30 条带颜色）
  4. `电控/deploy/image_ids.json`（image_id 映射，30 条恒等）
- **校验**由 `_pi_tools/verify_three_way.py` 负责

## 用法

```bash
python _pi_tools/gen_screen_contract.py           # 生成
python _pi_tools/gen_screen_contract.py --check   # 只校验不写（CI 用）
```

## ⚠️ 不要手改生成出来的文件

生成的文件头部都有 `AUTO-GENERATED` 标记。要改就改 `manifest.json` 再跑本脚本。

## 实现说明

模板里用 `@@TOKEN@@` 占位符而不是 `str.format`，因为生成的代码里
本身含大量 Python f-string 的 `{...}`，与 `.format()` 语法冲突（实测踩过）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MANIFEST = ROOT / "_screen_assets" / "colored" / "manifest.json"

# 生成目标
TARGET_MODULE_PATHS = (
    ROOT / "视觉" / "src" / "maixcam_deploy" / "shape_color_code.py",
    ROOT / "电控" / "src" / "electrical_control" / "rpi" / "shape_color_code.py",
)
TARGET_NAMES = ROOT / "电控" / "deploy" / "names.json"
TARGET_IMAGE_IDS = ROOT / "电控" / "deploy" / "image_ids.json"

# 线格式常量（与 vision_ingest.py 对齐，改这里必须同步改那边）
WIRE = {
    "batch_target_bytes": 7,
    "batch_header_bytes": 3,
    "code_min": 1,
    "code_max": 30,
    "angle_fixed": 0xFF,
}


MODULE_TEMPLATE = '''"""三方共用的形状/颜色 <-> code 映射。【AUTO-GENERATED，不要手改】

真源：`_screen_assets/colored/manifest.json`
生成：`_pi_tools/gen_screen_contract.py`
真源摘要：@@DIGEST@@

## code 定义

    code = (shape_id - 1) * 5 + color_id + 1      # 1..30
      shape_id in 1..6   @@SHAPE_LIST@@
      color_id in 0..4   @@COLOR_LIST@@

## 为什么三方必须严格一致

省赛计分规则（`省赛规则.txt` L262-266）：
  - 每个正确分拣的同类货物 5 分
  - **混装任何两类 => 该盒 0 分**

如果 MaixCAM 输出的 code 与树莓派/屏幕图片的表错一位：
  - 屏幕显示错（合规扣分）
  - 货格分配错（**混装 => 0 分**）

## 线格式（冻结，见 interface-contract 5.1）

    BATCH_TARGETS: target_count(1) + task_id(2, BE) + target[N]
    每个 target (7 字节):
      id_byte(1) + confidence(1, 0-100) + X(2, BE) + Y(2, BE) + angle(1, 0xFF)

    id_byte    = code (1..30)
    X/Y        = 像素坐标（只用于去重/排序/重定位，【绝不进运动】）
    angle      = 必须 0xFF（夹爪不旋转）
    confidence = min(颜色置信度, 形状置信度)
"""

from __future__ import annotations

from typing import Final

# ===========================================================================
# 常量（顺序即 code 的编码顺序，**不能改**）
# ===========================================================================

#: 形状名（英文），索引 0..5 对应 shape_id 1..6
SHAPE_NAMES: Final[tuple[str, ...]] = (
@@SHAPE_NAMES_PY@@)

#: 形状名（中文，与赛规表1 逐字一致）
SHAPE_NAMES_ZH: Final[tuple[str, ...]] = (
@@SHAPE_NAMES_ZH_PY@@)

#: 颜色名（英文），索引 0..4 对应 color_id 0..4
COLOR_NAMES: Final[tuple[str, ...]] = (
@@COLOR_NAMES_PY@@)

#: 颜色名（中文）
COLOR_NAMES_ZH: Final[tuple[str, ...]] = (
@@COLOR_NAMES_ZH_PY@@)

#: code 的合法范围（闭区间）
CODE_MIN: Final[int] = @@CODE_MIN@@
CODE_MAX: Final[int] = @@CODE_MAX@@

#: 线格式里 confidence 字节的上限
CONFIDENCE_MAX: Final[int] = 100

#: angle 字节的固定值（夹爪不旋转）
ANGLE_FIXED: Final[int] = @@ANGLE_FIXED@@

#: 视觉线格式每目标字节数
BATCH_TARGET_BYTES: Final[int] = @@BATCH_TARGET_BYTES@@

#: 每轮总物料数（赛规：6 类共 13 个）
ITEMS_PER_ROUND: Final[int] = 13

#: 每类最多件数（赛规 L42-43「不超过4个」）
BOX_CAPACITY_MAX: Final[int] = 4

#: 合法 code 集合（给 vision_ingest 的 ACTIVE_CLASS_IDS 用）
ACTIVE_CLASS_IDS: Final[frozenset[int]] = frozenset(
    range(CODE_MIN, CODE_MAX + 1))


# ===========================================================================
# 异常
# ===========================================================================


class CodeError(ValueError):
    """code / shape / color 越界或不认识。"""


# ===========================================================================
# 编码 / 解码
# ===========================================================================


def code_of(shape: str, color: str) -> int:
    """（形状, 颜色）-> code（1..30）。

    Args:
        shape: 英文形状名，必须在 SHAPE_NAMES 里
        color: 英文颜色名，必须在 COLOR_NAMES 里

    Returns:
        code in [1, 30]

    Raises:
        CodeError: 形状或颜色不认识

    Example:
        >>> code_of("cube", "red")
        1
        >>> code_of("pentagonal_prism", "blue")
        19
        >>> code_of("tetrahedron", "white")
        30
    """
    try:
        sid = SHAPE_NAMES.index(shape)          # 0-based
    except ValueError as exc:
        raise CodeError(
            "不认识的形状 %r，合法值：%s" % (shape, list(SHAPE_NAMES))
        ) from exc
    try:
        cid = COLOR_NAMES.index(color)
    except ValueError as exc:
        raise CodeError(
            "不认识的颜色 %r，合法值：%s" % (color, list(COLOR_NAMES))
        ) from exc
    return sid * len(COLOR_NAMES) + cid + 1


def decode_code(code: int) -> tuple[str, str, str, str]:
    """code（1..30）-> （形状英文, 颜色英文, 形状中文, 颜色中文）。

    Raises:
        CodeError: code 越界

    Example:
        >>> decode_code(1)
        ('cube', 'red', '正方体', '红色')
        >>> decode_code(19)
        ('pentagonal_prism', 'blue', '五棱柱', '蓝色')
    """
    if not isinstance(code, int) or isinstance(code, bool):
        raise CodeError(
            "code 必须是 int，收到 %s: %r" % (type(code).__name__, code))
    if code < CODE_MIN or code > CODE_MAX:
        raise CodeError(
            "code %d 越界（合法 %d..%d）" % (code, CODE_MIN, CODE_MAX))

    idx = code - 1
    n_color = len(COLOR_NAMES)
    sid = idx // n_color
    cid = idx % n_color
    return (
        SHAPE_NAMES[sid], COLOR_NAMES[cid],
        SHAPE_NAMES_ZH[sid], COLOR_NAMES_ZH[cid],
    )


def is_valid_code(code: object) -> bool:
    """code 是否合法（不抛异常版本，供线格式校验用）。"""
    return (
        isinstance(code, int) and not isinstance(code, bool)
        and CODE_MIN <= code <= CODE_MAX
    )


# ===========================================================================
# 派生物（屏幕 / 图片 / 日志）
# ===========================================================================


def image_id_of(code: int) -> int:
    """code -> 屏幕图片的 image_id。

    **恒等映射**（设计决定：code 同时就是 image_id，少一层转换就少一处错位）。
    """
    decode_code(code)   # 借它做越界校验
    return code


def image_file_of(code: int) -> str:
    """code -> 图片文件名（放在 /home/pi/images/ 下）。"""
    return "%d.png" % image_id_of(code)


def display_name_of(code: int) -> str:
    """code -> 屏幕「货物名称」文字。

    用户 2026-10-26 裁决：屏幕显示要**带颜色**（如「红色五棱柱」），
    这样同一形状不同颜色的两行能区分开。

    注意：赛规表1 的「货物名称」是纯形状名（如「五棱柱」）；
    本函数返回「颜色 + 形状」。若评委要求严格逐字，改用 shape_name_zh_of()。
    """
    _s, _c, szh, czh = decode_code(code)
    return czh + szh


def shape_name_zh_of(code: int) -> str:
    """code -> 纯形状中文名（严格等于赛规表1，不含颜色）。"""
    _s, _c, szh, _czh = decode_code(code)
    return szh


def color_name_zh_of(code: int) -> str:
    """code -> 纯颜色中文名。"""
    _s, _c, _szh, czh = decode_code(code)
    return czh


# ===========================================================================
# 自检
# ===========================================================================


def self_test() -> int:
    """内联自检：code 全覆盖 + 往返 + 越界 + 显示名唯一。返回 0 表示通过。"""
    failures: list[str] = []
    n_total = len(SHAPE_NAMES) * len(COLOR_NAMES)

    # 1) code 全覆盖、无重、无缺 + 往返
    seen = set()
    for shape in SHAPE_NAMES:
        for color in COLOR_NAMES:
            code = code_of(shape, color)
            if not is_valid_code(code):
                failures.append("code_of(%s,%s) = %r 不合法" % (shape, color, code))
            if code in seen:
                failures.append("code %d 重复" % code)
            seen.add(code)
            s2, c2, _, _ = decode_code(code)
            if (s2, c2) != (shape, color):
                failures.append(
                    "往返不等：%s/%s -> %d -> %s/%s" % (shape, color, code, s2, c2))
    if len(seen) != n_total:
        failures.append("code 覆盖 %d/%d" % (len(seen), n_total))
    if seen != set(range(CODE_MIN, CODE_MAX + 1)):
        failures.append("code 集合 != %d..%d" % (CODE_MIN, CODE_MAX))

    # 2) 越界必须抛
    for bad in (0, CODE_MAX + 1, -1, 256):
        try:
            decode_code(bad)
        except CodeError:
            pass
        else:
            failures.append("decode_code(%d) 应抛 CodeError 但没抛" % bad)

    # 3) 显示名必须唯一（同形状 5 个颜色的显示名互不相同）
    names = [display_name_of(c) for c in range(CODE_MIN, CODE_MAX + 1)]
    if len(set(names)) != len(names):
        failures.append("display_name_of 有重复（同形状不同色应能区分）")

    # 4) 纯形状名必须只有 6 种
    if len(set(shape_name_zh_of(c) for c in range(CODE_MIN, CODE_MAX + 1))) != 6:
        failures.append("shape_name_zh_of 不是 6 种")

    for f in failures:
        print("  FAIL  " + f)
    if failures:
        print("  %d 项失败" % len(failures))
        return 1
    print("  自检 %d/%d 通过" % (n_total, n_total))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(self_test())
'''


def _digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _py_tuple_body(items, indent: str = "    ") -> str:
    """把 list 渲染成多行 Python tuple 的**内部**（每项一行，已带缩进与换行）。"""
    return "".join('%s"%s",\n' % (indent, x) for x in items)


def build_module_text(manifest: dict) -> tuple[str, str]:
    """返回 (模块文本, 真源摘要)。"""
    shapes = manifest["shapes"]
    shape_names_zh = manifest["shape_names_zh"]
    colors = manifest["colors"]
    color_names_zh = manifest["color_names_zh"]

    shape_ids = sorted(shapes, key=int)
    color_ids = sorted(colors, key=int)

    shape_names = [shapes[k] for k in shape_ids]
    shape_zhs = [shape_names_zh[k] for k in shape_ids]
    color_names = [colors[k] for k in color_ids]
    color_zhs = [color_names_zh[k] for k in color_ids]

    digest = _digest_of(MANIFEST)
    n_codes = len(shape_names) * len(color_names)

    repl = {
        "@@DIGEST@@": digest,
        "@@SHAPE_LIST@@": " / ".join(shape_zhs),
        "@@COLOR_LIST@@": " / ".join(color_zhs),
        "@@SHAPE_NAMES_PY@@": _py_tuple_body(shape_names),
        "@@SHAPE_NAMES_ZH_PY@@": _py_tuple_body(shape_zhs),
        "@@COLOR_NAMES_PY@@": _py_tuple_body(color_names),
        "@@COLOR_NAMES_ZH_PY@@": _py_tuple_body(color_zhs),
        "@@CODE_MIN@@": str(1),
        "@@CODE_MAX@@": str(n_codes),
        "@@ANGLE_FIXED@@": str(WIRE["angle_fixed"]),
        "@@BATCH_TARGET_BYTES@@": str(WIRE["batch_target_bytes"]),
    }

    text = MODULE_TEMPLATE
    for token, value in repl.items():
        text = text.replace(token, value)

    left = text.count("@@")
    if left:
        raise RuntimeError("模板里有 %d 个未替换的占位符" % left)
    return text, digest


def build_names_json(manifest: dict) -> dict:
    """names.json：code(str) -> 显示名（带颜色）。"""
    return {
        str(e["image_id"]): e["color_zh"] + e["shape_zh"]
        for e in manifest["entries"]
    }


def build_image_ids_json(manifest: dict) -> dict:
    """image_ids.json：code(str) -> image_id（恒等）。"""
    return {str(e["image_id"]): e["image_id"] for e in manifest["entries"]}


def _write_if_changed(path: Path, text: str, *, check_only: bool) -> bool:
    """写文件（内容不变则不写）。返回 True = 有差异。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        old = path.read_text(encoding="utf-8")
        if old == text:
            print("  相同  " + str(path.relative_to(ROOT)))
            return False
        print("  变更  " + str(path.relative_to(ROOT)))
    else:
        print("  新建  " + str(path.relative_to(ROOT)))

    if check_only:
        return True

    # UTF-8 无 BOM（Windows 上很重要：BOM 会让 MaixPy / json 解析炸）
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从 manifest.json 生成三方共用契约")
    ap.add_argument("--check", action="store_true",
                    help="只校验是否有差异，不写文件（有差异时退出码 1）")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  单一真源生成器")
    print("=" * 70)
    print("  真源: " + str(MANIFEST.relative_to(ROOT)))

    if not MANIFEST.is_file():
        print("  ❌ 真源不存在: " + str(MANIFEST))
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n_entries = len(manifest.get("entries", []))
    print("  条目: %d" % n_entries)
    if n_entries != 30:
        print("  ⚠️ 预期 30 条（6 形状 x 5 颜色），实际 %d" % n_entries)
    print()

    print("  线格式契约:")
    for k, v in WIRE.items():
        print("    %-20s = %s" % (k, v))
    print()

    module_text, digest = build_module_text(manifest)
    names_text = json.dumps(
        build_names_json(manifest), ensure_ascii=False, indent=2) + "\n"
    image_ids_text = json.dumps(
        build_image_ids_json(manifest), ensure_ascii=False, indent=2) + "\n"

    print("  生成目标:")
    any_diff = False
    for p in TARGET_MODULE_PATHS:
        if _write_if_changed(p, module_text, check_only=args.check):
            any_diff = True
    for p, text in ((TARGET_NAMES, names_text),
                    (TARGET_IMAGE_IDS, image_ids_text)):
        if _write_if_changed(p, text, check_only=args.check):
            any_diff = True

    print()
    print("  真源摘要: " + digest)
    if args.check:
        if any_diff:
            print("  ❌ --check: 有文件与真源不一致")
            return 1
        print("  ✅ --check: 全部一致")
        return 0
    print("  ✅ 生成完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
