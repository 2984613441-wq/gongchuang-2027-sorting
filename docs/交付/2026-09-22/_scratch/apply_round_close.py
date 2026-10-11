# -*- coding: utf-8 -*-
"""把两支钟的收场判据抽成纯函数 `_round_close_reason`，并让主循环调用它。

为什么要抽出来：这段逻辑决定"一轮比赛是否就此结束"，是最不能靠肉眼看的东西。
抽成纯函数之后 `电控/deploy/selftest_round_close.py` 可以用 assert 把它锁死
（含"正常件周期不得误判"这条最容易踩的边界）。

原子性：每处 old 恰好匹配 1 次，否则一个字节都不写。
"""
import hashlib
import pathlib
import sys

TARGET = pathlib.Path(r"C:\Users\29845\Desktop\工创赛\电控\deploy\run_chain.py")

FUNC_OLD = '''def _nack_is_retryable(event: str) -> bool:
    """True = 原样重发值得试；False = 重发必然再被拒（调用方应 fail-closed 收场）。

    未知原因码（``NACK_UNKNOWN(0xNN)``）一律返回 False —— 不认识的拒绝不许进重试循环。
    """
    return event in _NACK_RETRYABLE
'''

FUNC_NEW = '''def _nack_is_retryable(event: str) -> bool:
    """True = 原样重发值得试；False = 重发必然再被拒（调用方应 fail-closed 收场）。

    未知原因码（``NACK_UNKNOWN(0xNN)``）一律返回 False —— 不认识的拒绝不许进重试循环。
    """
    return event in _NACK_RETRYABLE


def _round_close_reason(
    *,
    now: float,
    inflight_since: float | None,
    idle_since: float,
    inflight_timeout_s: float,
    round_idle_timeout_s: float,
) -> str | None:
    """两支钟的收场判据（纯函数；自检见 deploy/selftest_round_close.py）。

    返回 ``"inflight"`` / ``"idle"`` / ``None``。

    * **在飞钟优先且在飞时独占**：只要还有运动在飞（``inflight_since is not None``），
      就**只看**"板子静默"这一条，空闲钟完全不参与 —— 否则一件正常的 12~15s 件
      会被空闲钟当成"台面没件了"而误判本轮结束（那是把好轮判死）。
    * 阈值 ``<= 0`` = 关闭该支钟（回到"无限等 / 无限重传"的旧行为）。
    * 边界取 ``>=``：正好等于阈值即判到点（与固件 15s 窗的 ``>=`` 口径一致）。
    """
    if inflight_since is not None:
        if (inflight_timeout_s > 0) and ((now - inflight_since) >= inflight_timeout_s):
            return "inflight"
        return None
    if (round_idle_timeout_s > 0) and ((now - idle_since) >= round_idle_timeout_s):
        return "idle"
    return None
'''

LOOP_OLD = '''        now_mono = time.monotonic()
        if inflight_since is not None:
            if (inflight_timeout_s > 0) and ((now_mono - inflight_since) >= inflight_timeout_s):
                cl.record(
                    FAULT,
                    now=time.monotonic(),
                    detail=f"在飞 {now_mono - inflight_since:.1f}s 无 MOTION_DONE（阈值 "
                    f"{inflight_timeout_s:.1f}s）：判板子静默",
                )
                logger.error(
                    "在飞 %.1fs 无 MOTION_DONE/ITEM_RESULT（阈值 %.1fs）⇒ 判板子静默，"
                    "干净收场，退出码 1。**不向 STM32 发任何停止/复位命令**",
                    now_mono - inflight_since, inflight_timeout_s,
                )
                return 1
        elif (round_idle_timeout_s > 0) and ((now_mono - idle_since) >= round_idle_timeout_s):
'''

LOOP_NEW = '''        now_mono = time.monotonic()
        close_reason = _round_close_reason(
            now=now_mono,
            inflight_since=inflight_since,
            idle_since=idle_since,
            inflight_timeout_s=inflight_timeout_s,
            round_idle_timeout_s=round_idle_timeout_s,
        )
        if close_reason == "inflight":
            assert inflight_since is not None  # _round_close_reason 的契约
            cl.record(
                FAULT,
                now=time.monotonic(),
                detail=f"在飞 {now_mono - inflight_since:.1f}s 无 MOTION_DONE（阈值 "
                f"{inflight_timeout_s:.1f}s）：判板子静默",
            )
            logger.error(
                "在飞 %.1fs 无 MOTION_DONE/ITEM_RESULT（阈值 %.1fs）⇒ 判板子静默，"
                "干净收场，退出码 1。**不向 STM32 发任何停止/复位命令**",
                now_mono - inflight_since, inflight_timeout_s,
            )
            return 1
        elif close_reason == "idle":
'''


def main() -> int:
    raw = TARGET.read_bytes()
    print(f"目标 : {TARGET}")
    print(f"改前 : {len(raw)} B  sha256 {hashlib.sha256(raw).hexdigest()[:16]}")
    text = raw.decode("utf-8")

    pairs = [("FUNC 抽出 _round_close_reason", FUNC_OLD, FUNC_NEW),
             ("LOOP 主循环改调纯函数", LOOP_OLD, LOOP_NEW)]
    bad = []
    for label, old, _new in pairs:
        n = text.count(old)
        if n != 1:
            bad.append(f"  ❌ {label}: 匹配 {n} 次（必须 1 次）")
        else:
            print(f"  ✅ {label}: 匹配 1 处")
    if bad:
        print("\n".join(bad))
        print("\n>>> 校验失败，未写入任何内容")
        return 2

    for _label, old, new in pairs:
        text = text.replace(old, new, 1)

    TARGET.write_bytes(text.encode("utf-8"))
    out = TARGET.read_bytes()
    print(f"\n改后 : {len(out)} B  sha256 {hashlib.sha256(out).hexdigest()[:16]}"
          f"  {text.count(chr(10))} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
