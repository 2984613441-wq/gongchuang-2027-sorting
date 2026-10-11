# -*- coding: utf-8 -*-
"""两支钟收场判据 + NACK 原因码分类的独立自检（无依赖，直接跑）。

    cd 电控 && python3 deploy/selftest_round_close.py

为什么必须有这个文件：`_round_close_reason` 决定"一轮比赛是否就此结束"。
判错的方向只有两种，两种都很贵：
  * 该结束时没结束 ⇒ 现场空转/无限重传（就是 N2 要治的病）；
  * 不该结束时结束了 ⇒ **把好轮判死**（比空转严重得多）。
所以这里把两个方向都钉死，尤其是"正常件周期内不得误判"这条边界。

对应问题：docs/交付/2026-09-22/全系统现状-2026-09-22-通读全仓后.md 的 F3 / F6 / N2。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_chain import _nack_is_retryable, _round_close_reason  # noqa: E402

# 现场实测的关键数字（docs 里的原始证据，改这里必须同时改文档）
WORST_SINGLE_ITEM_S = 15.154   # 2026-09-21 18:55 轮：第一件 发令→MOTION_DONE
NORMAL_ITEM_S = 12.8           # 2026-09-21 20:12 轮：正常件
TYPICAL_ITEM_GAP_S = 0.93      # 正常件间间隔实测 0.90~0.93s

DEFAULT_IDLE = 15.0
DEFAULT_INFLIGHT = 20.0

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"  ❌ {label}: 得到 {got!r}，期望 {want!r}")
    else:
        print(f"  ✅ {label}")


def main() -> int:
    print("== 1. 默认阈值下：最坏的那一件【不得】被误判 ==")
    # 发令后 12.8s：还在飞，两块钟都不该响
    check("正常件 12.8s 在飞 → 不结束",
          _round_close_reason(now=NORMAL_ITEM_S, inflight_since=0.0, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    # 发令后 15.154s（实测最坏单件）：仍然 > 15s，空闲钟若参与就会误判 ⇒ 必须 None
    check("最坏件 15.154s 在飞 → 不结束（空闲钟不得参与）",
          _round_close_reason(now=WORST_SINGLE_ITEM_S, inflight_since=0.0, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    check("在飞 19.999s → 不结束",
          _round_close_reason(now=19.999, inflight_since=0.0, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    check("在飞 20.000s → 判板子静默（>= 口径）",
          _round_close_reason(now=20.000, inflight_since=0.0, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), "inflight")

    print("\n== 2. 没有运动在飞时：空闲钟 ==")
    check("空闲 0.93s（正常件间间隔）→ 不结束",
          _round_close_reason(now=TYPICAL_ITEM_GAP_S, inflight_since=None, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    check("空闲 14.999s → 不结束",
          _round_close_reason(now=14.999, inflight_since=None, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    check("空闲 15.000s → 判本轮结束（>= 口径）",
          _round_close_reason(now=15.000, inflight_since=None, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), "idle")

    print("\n== 3. 在飞期间空闲钟即使早已超时也不得抢先 ==")
    check("空闲基线很老(>15s) 但此刻在飞 1s → 不结束",
          _round_close_reason(now=100.0, inflight_since=99.0, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=DEFAULT_IDLE), None)

    print("\n== 4. 0 = 关闭该支钟（回到旧行为） ==")
    check("in-flight 超时=0 → 永不判静默",
          _round_close_reason(now=1e6, inflight_since=0.0, idle_since=0.0,
                              inflight_timeout_s=0.0,
                              round_idle_timeout_s=DEFAULT_IDLE), None)
    check("空闲超时=0 → 永不判本轮结束",
          _round_close_reason(now=1e6, inflight_since=None, idle_since=0.0,
                              inflight_timeout_s=DEFAULT_INFLIGHT,
                              round_idle_timeout_s=0.0), None)

    print("\n== 5. NACK 原因码分类 ==")
    # 可重试：板子还没准备好收这一件（2026-09-21 那条补丁要救的场景，必须保留）
    for ev in ("NACK_SINGLE_TASK_ONLY", "NACK_ACK_NOT_APPLICABLE"):
        check(f"{ev} → 可重试", _nack_is_retryable(ev), True)
    # 不可重试：重发同一字节必然再被拒 ⇒ 必须 fail-closed，否则无限循环
    for ev in ("NACK_WRONG_ROUND", "NACK_STALE_OR_ORDER", "NACK_TASK_REJECTED",
               "NACK_UNEXPECTED_MESSAGE", "NACK_UNKNOWN(0x7F)", "NACK_",
               "ACK_ACCEPTED"):
        check(f"{ev} → 不可重试", _nack_is_retryable(ev), False)

    print()
    if failures:
        print("\n".join(failures))
        print(f"\n>>> 自检 FAILED（{len(failures)} 条）")
        return 1
    print(">>> 自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
