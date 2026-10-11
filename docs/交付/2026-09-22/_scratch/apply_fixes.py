# -*- coding: utf-8 -*-
"""2026-09-22 全链修复：对 电控/deploy/run_chain.py 做 8 处原子替换。

设计原则：
  * 每处 old 字符串必须**恰好出现 1 次**，否则整体放弃、不落盘（fail-closed）。
  * 只做替换，不重排、不格式化，保证 diff 最小、可逐条复核。
  * 全部改动都在"会不会毁掉一轮"的路径上，改完必须过 py_compile。

对应问题编号（见 docs/交付/2026-09-22/全系统现状-2026-09-22-通读全仓后.md）：
  R1  重新加回两个 CLI 参数（这次带实现）      —— N2 / F6
  R2  主循环前状态：两支钟 + NACK 上限计数器    —— N2 / F3 / F6
  R3  派件时：置在飞钟、清 NACK 计数            —— N2 / F3
  R4  超时重传加状态门 + 新增两支钟收场检查      —— F4 / F6
  R5  MOTION_DONE：清在飞钟、重置空闲钟          —— N2
  R6  ITEM_RESULT 渲染后：重置空闲钟             —— N2
  R7  NACK 分支：原因码判别 + 次数上限           —— F3
  R8  新增 _nack_is_retryable 帮助函数           —— F3
"""
import hashlib
import pathlib
import sys

TARGET = pathlib.Path(r"C:\Users\29845\Desktop\工创赛\电控\deploy\run_chain.py")


# ── R1：CLI 参数 ────────────────────────────────────────────────────────────
R1_OLD = '''        "而 15s 红线从起轮算起，那比顺序错严重得多）。",
    )
    return parser.parse_args(argv)
'''

R1_NEW = '''        "而 15s 红线从起轮算起，那比顺序错严重得多）。",
    )
    parser.add_argument(
        "--round-idle-timeout",
        type=float,
        default=float(_env_int("ROUND_IDLE_TIMEOUT_MS", 15000)) / 1000.0,
        help="**N2-a 空闲收场**：READY 且【当前没有运动在飞】时，连续这么多秒没有可派发的"
        "新件 ⇒ 判本轮结束、干净收场（打汇总 → 退出 0）。"
        "取 15.0 与赛规「15 秒没有动作或没有显示本次分拣信息，本轮结束」同值；"
        "**这一段里没有运动**，所以不会误判件周期。**0 = 关闭**（回到旧行为：无限等）。",
    )
    parser.add_argument(
        "--inflight-timeout",
        type=float,
        default=float(_env_int("INFLIGHT_TIMEOUT_MS", 20000)) / 1000.0,
        help="**N2-b 在飞收场**：发了 ITEM_TASK 之后超过这么多秒仍没收到 MOTION_DONE"
        " ⇒ 判板子静默、记 FAULT、干净收场（不再无限重传，退出 1）。"
        "🔴 **必须大于最坏单件时长**：实测第一件 发令→MOTION_DONE = **15.154s**"
        "（2026-09-21 18:55 轮）⇒ 取 20.0s 留余量。"
        "⚠️ **不要用 15.0 当这个阈值** —— 那会在**正常**的第一件上误判。**0 = 关闭**。",
    )
    return parser.parse_args(argv)
'''

# ── R8：帮助函数（插在 require_home_confirmation 之前）────────────────────
R8_OLD = '''def require_home_confirmation(
    args: argparse.Namespace,
    *,
    input_fn=input,
    output=sys.stderr,
) -> None:
'''

R8_NEW = '''# 🔴 2026-09-22 修复（F3）：NACK 原因码分两类。
#   可重试 = 板子"还没准备好收这一件"（还在收尾上一件 / 还没进到能收的状态），
#            等它一下再发同一帧就能成功 —— 这是 2026-09-21 那条补丁要救的场景，
#            实测每件都会遇到（R3/R4 轮证据），**必须保留**。
#   不可重试 = 重发同一字节必然再被拒（轮次不符 / 顺序不符 / 通用拒收 / 未知码），
#            旧代码在这里会变成 0.3s 一次、约 3 次/秒的**无限循环**，而且
#            sleep 阻塞主循环、每轮还刷新 last_task_sent_at 把 5s 超时架空
#            ⇒ 整轮永久卡死、且永远不补发真正需要重发的 DISPLAY_ACK。
_NACK_RETRYABLE = {
    "NACK_SINGLE_TASK_ONLY",     # 0x12：板子还在处理上一件
    "NACK_ACK_NOT_APPLICABLE",   # 0x13：板子还没进到能收 DISPLAY_ACK 的状态
}


def _nack_is_retryable(event: str) -> bool:
    """True = 原样重发值得试；False = 重发必然再被拒（调用方应 fail-closed 收场）。

    未知原因码（``NACK_UNKNOWN(0xNN)``）一律返回 False —— 不认识的拒绝不许进重试循环。
    """
    return event in _NACK_RETRYABLE


def require_home_confirmation(
    args: argparse.Namespace,
    *,
    input_fn=input,
    output=sys.stderr,
) -> None:
'''

# ── R2：主循环前状态 ───────────────────────────────────────────────────────
R2_OLD = '''    nack_retry_backoff_s = 0.3
    while True:
'''

R2_NEW = '''    nack_retry_backoff_s = 0.3
    # 🔴 2026-09-22 修复（F3）：NACK 重试**必须有上限**（原因码判别见 _nack_is_retryable）。
    #   旧行为无上限 ⇒ 见该函数上方的说明。上限按"每件"计，派件时清零。
    nack_retry_max = 5
    nack_retries = 0
    # 🔴 2026-09-22 新增（N2 / F6）：**两支钟**的整轮收场看门狗。
    #   空闲钟 idle_since：只在【没有运动在飞】时走 ⇒ 只有"台面没件了"才会到点。
    #   在飞钟 inflight_since：从发令起走，收到 MOTION_DONE/ITEM_RESULT 就清
    #                            ⇒ 只有"板子静默"才会到点。
    # ⚠️ 为什么不能用单钟 15s：实测第一件 发令→MOTION_DONE = **15.154s > 15s**（18:55 轮），
    #    单钟 15s 会在**正常**的件上误判 ⇒ 把好轮判死。这是拿实测数据改的设计。
    # ⚠️ 重置只认"MOTION_DONE 到"与"ITEM_RESULT→上屏"；**不认 ITEM_TASK sent**
    #    （只证明主机发了命令，不证明装置动了）。
    # ⚠️ 收场时**不得**向 STM32 发 STOP ALL / HOME / RESET —— 见收场分支的注释。
    # ⚠️ 本改动前，链**永远不会自己退出**：静默时空转、有在飞件时每 5s 重传直到人工 Ctrl-C。
    round_idle_timeout_s = float(args.round_idle_timeout)
    inflight_timeout_s = float(args.inflight_timeout)
    idle_since = time.monotonic()
    inflight_since: float | None = None
    while True:
'''

# ── R3：派件 ───────────────────────────────────────────────────────────────
R3_OLD = '''            done_items += 1
            last_task_sent_at = time.monotonic()
            last_task_context = task
            success_info = None  # 新的一件：清掉上一件遗留的「分拣成功」载荷
'''

R3_NEW = '''            done_items += 1
            last_task_sent_at = time.monotonic()
            last_task_context = task
            success_info = None  # 新的一件：清掉上一件遗留的「分拣成功」载荷
            inflight_since = time.monotonic()  # N2-b：在飞钟从发令起走
            nack_retries = 0                   # F3：NACK 重试上限按件重置
'''

# ── R4：超时重传加状态门 + 两支钟收场检查 ──────────────────────────────────
R4_OLD = '''        # 2) 超时检查：若有活动任务且超时，重传 ITEM_TASK
        if last_task_context is not None and (time.monotonic() - last_task_sent_at) > task_timeout_s:
            logger.warning(
                "ITEM_TASK 超时 %.1fs 无应答，重传 frame_seq=%d",
                task_timeout_s,
                last_task_context.frame_seq,
            )
            raw_resend = outbound.resend_item_task(last_task_context)
            last_task_sent_at = time.monotonic()  # 更新时间，避免每轮都重传
            cl.record(
                TASK,
                now=time.monotonic(),
                round_id=last_task_context.round_id,
                task_id=last_task_context.task_id,
                frame_seq=last_task_context.frame_seq,
                target_seq=last_task_context.payload.target_seq,
                detail=f"ITEM_TASK 重传 ({len(raw_resend)}B), timeout={task_timeout_s}s",
            )

        # 3) 轮询入站：整帧交给网关分发
'''

R4_NEW = '''        # 2) 超时检查：若有活动任务且超时，重传 ITEM_TASK
        # 🔴 2026-09-22 修复（F4）：**必须同时要求"还在等 MOTION_DONE"**。
        #   旧判据只看"有在飞件 + 超时"，于是 MOTION_DONE 早已到达、只差 ITEM_RESULT 时
        #   也会重发同一帧 ⇒ 板子按 dedup 只回缓存 ACK（不是 ITEM_RESULT）⇒
        #   Pi 永远停在 WAIT_ITEM_RESULT、每 5s 重传一次且**无出口**（死锁）；
        #   叠加"板子自愈时会清 dedup、把重发帧当全新首件重新执行运动"，
        #   还会造成**同一件被搬两次**。
        #   同文件另一条重传路径 _should_resend_on_barrier_ready 本来就查状态，这里补齐一致。
        if (last_task_context is not None
                and scheduler.state is SchedulerState.WAIT_MOTION_DONE
                and (time.monotonic() - last_task_sent_at) > task_timeout_s):
            logger.warning(
                "ITEM_TASK 超时 %.1fs 无应答，重传 frame_seq=%d",
                task_timeout_s,
                last_task_context.frame_seq,
            )
            raw_resend = outbound.resend_item_task(last_task_context)
            last_task_sent_at = time.monotonic()  # 更新时间，避免每轮都重传
            cl.record(
                TASK,
                now=time.monotonic(),
                round_id=last_task_context.round_id,
                task_id=last_task_context.task_id,
                frame_seq=last_task_context.frame_seq,
                target_seq=last_task_context.payload.target_seq,
                detail=f"ITEM_TASK 重传 ({len(raw_resend)}B), timeout={task_timeout_s}s",
            )

        # 2b) 整轮收场看门狗（N2 / F6）：两支钟，见循环前注释。
        #     在飞钟优先：发令后板子一直静默 ⇒ 记 FAULT、干净收场（退出 1）。
        #     空闲钟：没有运动在飞、且长时间没有新件 ⇒ 判本轮结束（退出 0）。
        # ⚠️ 两处收场**都不向 STM32 发任何命令**（不发 STOP ALL / HOME / RESET）：
        #    板子应保持现状，由操作员按现场流程处理。
        now_mono = time.monotonic()
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
            cl.record(
                STAGE,
                now=time.monotonic(),
                detail=f"空闲 {now_mono - idle_since:.1f}s 无新件（阈值 "
                f"{round_idle_timeout_s:.1f}s）：判本轮结束",
            )
            logger.info(
                "空闲 %.1fs 无新件（阈值 %.1fs）⇒ 判本轮结束，干净收场，退出码 0。"
                "**不向 STM32 发任何停止/复位命令**",
                now_mono - idle_since, round_idle_timeout_s,
            )
            break

        # 3) 轮询入站：整帧交给网关分发
'''

# ── R5：MOTION_DONE 重置两支钟 ─────────────────────────────────────────────
R5_OLD = '''            # 重置超时计时：已收到 MOTION_DONE，等待 ITEM_RESULT
            last_task_sent_at = time.monotonic()
'''

R5_NEW = '''            # 重置超时计时：已收到 MOTION_DONE，等待 ITEM_RESULT
            last_task_sent_at = time.monotonic()
            # N2：MOTION_DONE 是**可观测进展** ⇒ 清在飞钟、重置空闲钟、清 NACK 计数
            inflight_since = None
            idle_since = time.monotonic()
            nack_retries = 0
'''

# ── R6：ITEM_RESULT 渲染后重置空闲钟 ───────────────────────────────────────
R6_OLD = '''            _render_and_ack(scheduler, outbound, names, image_loader,
                            frame_output, font_path, cl, logger)
'''

R6_NEW = '''            _render_and_ack(scheduler, outbound, names, image_loader,
                            frame_output, font_path, cl, logger)
            # N2：本件已走完整条显示闭环（规则帧 + DISPLAY_ACK）⇒ 重置空闲钟。
            # 下一件若在 round_idle_timeout_s 内不来，就判本轮结束。
            idle_since = time.monotonic()
'''

# ── R7：NACK 分支 ──────────────────────────────────────────────────────────
R7_OLD = '''        elif isinstance(event, str) and event.startswith("NACK"):
            # 🔴 2026-09-21：板子**明确拒收**在飞的那一帧（典型：NACK_SINGLE_TASK_ONLY
            #    —— 它还没进到 WAIT_TASK）。必须**立刻带小退避重发**，
            #    不能等满 task_timeout_s（旧行为每件白拖 ~8s，实测 21~22s/件）。
            cl.record(TASK, now=time.monotonic(), detail=f"inbound {event}（立即重试）")
            logger.warning(
                "inbound %s：板子拒收本帧，%.1fs 后立即重发（不再等 %.1fs 超时）",
                event, nack_retry_backoff_s, task_timeout_s,
            )
            if last_task_context is not None:
                time.sleep(nack_retry_backoff_s)
                try:
                    raw_resend = outbound.resend_item_task(last_task_context)
                except Exception:
                    logger.warning("NACK 后重发失败（保留在飞状态，等超时重传）", exc_info=True)
                else:
                    last_task_sent_at = time.monotonic()
                    cl.record(
                        TASK,
                        now=time.monotonic(),
                        detail=f"NACK({event}) 后立即重发 ({len(raw_resend)}B)",
                    )
            else:
                logger.warning("收到 %s 但没有在飞的件：忽略（不进队列、不动机械）", event)
'''

R7_NEW = '''        elif isinstance(event, str) and event.startswith("NACK"):
            # 🔴 2026-09-21：板子**明确拒收**在飞的那一帧（典型：NACK_SINGLE_TASK_ONLY
            #    —— 它还没进到 WAIT_TASK）。必须**立刻带小退避重发**，
            #    不能等满 task_timeout_s（旧行为每件白拖 ~8s，实测 21~22s/件）。
            # 🔴 2026-09-22 修复（F3）：**加原因码判别 + 次数上限**。
            #    只有"板子还没准备好收这一件"类的原因值得重发（见 _nack_is_retryable）；
            #    WRONG_ROUND / STALE_OR_ORDER / TASK_REJECTED / 未知码这类
            #    重发同一字节必然再被拒 ⇒ 直接 fail-closed 收场，绝不进重试循环。
            retryable = _nack_is_retryable(event)
            nack_retries += 1
            if last_task_context is None:
                logger.warning("收到 %s 但没有在飞的件：忽略（不进队列、不动机械）", event)
            elif not retryable:
                cl.record(
                    FAULT,
                    now=time.monotonic(),
                    detail=f"{event}：该原因重发必然再被拒，fail-closed 收场",
                )
                logger.error(
                    "inbound %s：板子拒收，且**重发同一帧必然再被拒**（原因码类）"
                    "⇒ 本轮收场，不重发（旧行为会在此无限重发）。退出码 1",
                    event,
                )
                return 1
            elif nack_retries > nack_retry_max:
                cl.record(
                    FAULT,
                    now=time.monotonic(),
                    detail=f"{event}：NACK 重试超过 {nack_retry_max} 次，fail-closed 收场",
                )
                logger.error(
                    "inbound %s：NACK 重试已达上限 %d 次 ⇒ 本轮收场（不再重发），退出码 1",
                    event, nack_retry_max,
                )
                return 1
            else:
                cl.record(
                    TASK,
                    now=time.monotonic(),
                    detail=f"inbound {event}（第 {nack_retries}/{nack_retry_max} 次重试）",
                )
                logger.warning(
                    "inbound %s：板子拒收本帧，%.1fs 后重发"
                    "（第 %d/%d 次，不再等 %.1fs 超时）",
                    event, nack_retry_backoff_s, nack_retries, nack_retry_max,
                    task_timeout_s,
                )
                time.sleep(nack_retry_backoff_s)
                try:
                    raw_resend = outbound.resend_item_task(last_task_context)
                except Exception:
                    logger.warning("NACK 后重发失败（保留在飞状态，等超时重传）", exc_info=True)
                else:
                    last_task_sent_at = time.monotonic()
                    cl.record(
                        TASK,
                        now=time.monotonic(),
                        detail=f"NACK({event}) 后重发 ({len(raw_resend)}B)",
                    )
'''


def main() -> int:
    raw = TARGET.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    print(f"目标 : {TARGET}")
    print(f"改前 : {len(raw)} B  sha256 {before[:16]}")

    pairs = [
        ("R1  CLI 参数", R1_OLD, R1_NEW),
        ("R8  _nack_is_retryable", R8_OLD, R8_NEW),
        ("R2  循环前状态", R2_OLD, R2_NEW),
        ("R3  派件", R3_OLD, R3_NEW),
        ("R4  超时门+两支钟", R4_OLD, R4_NEW),
        ("R5  MOTION_DONE 重置", R5_OLD, R5_NEW),
        ("R6  ITEM_RESULT 重置", R6_OLD, R6_NEW),
        ("R7  NACK 分支", R7_OLD, R7_NEW),
    ]

    # 先全部校验，再统一落盘（任何一处不合格 ⇒ 一个字节都不写）
    bad = []
    for label, old, _new in pairs:
        n = text.count(old)
        if n != 1:
            bad.append(f"  ❌ {label}: old 出现 {n} 次（必须恰好 1 次）")
        else:
            print(f"  ✅ {label}: 匹配 1 处")
    if bad:
        print("\n".join(bad))
        print("\n>>> 校验失败，**未写入任何内容**")
        return 2

    for _label, old, new in pairs:
        text = text.replace(old, new, 1)

    TARGET.write_bytes(text.encode("utf-8"))
    after_raw = TARGET.read_bytes()
    print(f"\n改后 : {len(after_raw)} B  sha256 {hashlib.sha256(after_raw).hexdigest()[:16]}")
    print(f"行数 : {text.count(chr(10))} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
