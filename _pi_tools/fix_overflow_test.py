#!/usr/bin/env python3
"""把 test_group_table.py 里 test_fault_injection_overflow 的硬编码 4 改成常量。

背景：2026-10-26 用户裁决把 MAX_COUNT_PER_BOX 从 4 改成 3，
      而该测试硬编码了 4 ⇒ 测试失败。改成读常量，以后改 Cmax 不用再改测试。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "电控" / "tests" / "rpi" / "test_group_table.py"

NEW_FUNC = '''def test_fault_injection_overflow():
    """故障注入 4：1 类超过 MAX_COUNT_PER_BOX 件 ⇒ 返回 FULL。

    注：2026-10-26 用户裁决把 MAX_COUNT_PER_BOX 从 4 改成 3
        （留落料不可观测的余量）。
        本测试改用常量而不是硬编码 4，这样以后改 Cmax 不用再改测试。
    """
    table = GroupTable(round_id="test-round")
    cmax = table.MAX_COUNT_PER_BOX

    box_id, res = table.assign(1)
    assert res == "OK"

    # 落下 cmax 件
    for _ in range(cmax):
        ok = table.on_drop_ok(1)
        assert ok is True

    # 检查已满
    box = table.get_box_state(box_id)
    assert box.dropped_count == cmax
    assert box.state == "FULL"

    # 尝试再分配下一件 ⇒ 必须 FULL
    box_id2, res2 = table.assign(1)
    assert res2 == "FULL"
    assert box_id2 is None
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    start = text.find("def test_fault_injection_overflow()")
    if start < 0:
        print("❌ 找不到 test_fault_injection_overflow")
        return 1

    # 找到下一个顶层 def（作为这个函数的结束）
    nxt = text.find("\ndef test_", start + 10)
    if nxt < 0:
        print("❌ 找不到下一个测试函数作为边界")
        return 1

    old_block = text[start:nxt]
    print("=== 原函数（%d 字符）===" % len(old_block))
    for line in old_block.splitlines():
        print("  " + line)
    print()

    # 保留后面两个空行 + 注释分隔
    text = text[:start] + NEW_FUNC + "\n" + text[nxt:]

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print("✅ 已替换")
    print()

    # 回读确认
    check = TARGET.read_text(encoding="utf-8")
    if "cmax = table.MAX_COUNT_PER_BOX" in check:
        print("✅ 回读确认：已使用常量")
    else:
        print("❌ 回读确认失败")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
