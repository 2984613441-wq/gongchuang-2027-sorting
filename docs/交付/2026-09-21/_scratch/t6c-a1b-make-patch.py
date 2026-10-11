"""临时（T6c/A1b）：生成两份可直接 `git apply -p1` 的补丁。

用纯 difflib（不调 subprocess、不碰 git index —— 这个工作区里有别的节点在并发改
文件，动 index 风险太大）。补丁路径写死成 `a/<rel>` / `b/<rel>`，故从仓库根
`git apply -p1` / `patch -p1` 都能直接吃。
"""

from __future__ import annotations

import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]          # 工创赛/
OUT = ROOT / "docs" / "交付" / "2026-09-21"
OLD = OUT / "_patchgen" / "old"
NEW = ROOT

PATCH_A = OUT / "补丁-T6c-屏幕帧numpy化-2026-09-21.patch"
PATCH_B = OUT / "补丁-A1b-夹取顺序行扫描-2026-09-21.patch"

HDR_A = """\
# 补丁 T6c —— display_hdmi.encode_frame 改 numpy 向量化（**逐字节等价**）
#
# 落点 : 电控/src/electrical_control/rpi/display_hdmi.py
#        电控/tests/rpi/test_framebuffer_pack.py（验收语料换成逐像素唯一图样帧）
# 应用 : 在仓库根执行  git apply -p1 "docs/交付/2026-09-21/补丁-T6c-屏幕帧numpy化-2026-09-21.patch"
#        先干跑  git apply --check -p1 <同一文件>
# 回退 : 从 docs/交付/2026-09-21/T6c-A1b-原始备份/ 覆盖回去（见交付说明 §回退）
# 验收 : D:\\python.exe 电控/tools/fb_encode_parity.py   ⇒ 6/6 逐字节相同
#
"""
HDR_B = """\
# 补丁 A1b —— 夹取顺序改「行扫描」（Y 从大到小 → 同行 X 从小到大）
#
# 落点 : 电控/src/electrical_control/pick_strategy/selector.py（新增排序键/排序函数）
#        电控/src/electrical_control/pick_strategy/__init__.py（导出）
#        电控/src/electrical_control/pick_strategy/chain_adapter.py（接入点：换函数）
#        电控/tests/pick_strategy/test_row_scan_order.py（新增，8 条判据）
# 应用 : 在仓库根执行  git apply -p1 "docs/交付/2026-09-21/补丁-A1b-夹取顺序行扫描-2026-09-21.patch"
# 回退 : 从 docs/交付/2026-09-21/T6c-A1b-原始备份/ 覆盖回去（见交付说明 §回退）
# 验收 : D:\\python.exe -m pytest 电控/tests/pick_strategy -q
# 注意 : `--pick-strategy` 默认仍是 off ⇒ 不启用时行为与接入前逐字节一致
#
"""

CASES = (
    (PATCH_A, HDR_A, (
        "电控/src/electrical_control/rpi/display_hdmi.py",
        "电控/tests/rpi/test_framebuffer_pack.py",
    )),
    (PATCH_B, HDR_B, (
        "电控/src/electrical_control/pick_strategy/selector.py",
        "电控/src/electrical_control/pick_strategy/__init__.py",
        "电控/src/electrical_control/pick_strategy/chain_adapter.py",
        "电控/tests/pick_strategy/test_row_scan_order.py",   # 新文件
    )),
)


def _lines(path: Path):
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def main() -> int:
    for out_path, header, rels in CASES:
        parts = [header]
        for rel in rels:
            new_path = NEW / rel
            old_path = OLD / rel
            exists = old_path.exists()
            diff = difflib.unified_diff(
                _lines(old_path) if exists else [],
                _lines(new_path),
                fromfile=f"a/{rel}" if exists else "/dev/null",
                tofile=f"b/{rel}",
                n=3,
            )
            body = list(diff)
            if not body:
                raise SystemExit(f"{rel} 没有差异 —— 补丁不该是空的")
            parts.append(f"diff --git a/{rel} b/{rel}\n")
            if not exists:
                parts.append("new file mode 100644\n")
            parts.extend(body)
        # 必须写字节：Windows 上 write_text 会把 \n 翻成 \r\n，补丁每行都会多一个
        # \r ⇒ 上下文行全都对不上（"patch does not apply"）。
        out_path.write_bytes("".join(parts).encode("utf-8"))
        print(f"{out_path.relative_to(ROOT)}  "
              f"{sum(1 for line in parts if line.startswith('@@'))} 个 hunk, "
              f"{sum(1 for line in parts if line.startswith('+++'))} 个文件, "
              f"{out_path.stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
