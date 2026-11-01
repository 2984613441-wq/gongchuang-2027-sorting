#!/usr/bin/env python3
"""auto_capture.py 的变化检测逻辑离线验证（不依赖 maix）。

把主循环的判定逻辑抽成一个纯函数，用模拟帧序列验证三种场景：
  1. 放一次料、不动         -> 应恰好保存 1 张
  2. 放好不动 60 帧         -> 不应重复保存
  3. 放料 -> 挪走 -> 再放   -> 应保存 >= 2 张

用法：python _pi_tools/test_auto_capture_logic.py
"""

# 与 auto_capture.py 的配置保持一致
CHANGE_TH = 8.0
STABLE_TH = 3.0
STABLE_FRAMES = 10
SAVE_MIN_DIFF = 5.0
COOLDOWN_S = 1.5
FPS = 30.0


def simulate(frames, dt=1.0 / FPS):
    """frames: 每帧一个 (motion, content) 二元组，返回 (保存张数, 事件列表)。

    motion  = 与上一帧的差（判"现在在不在动"）
    content = 与上次保存帧的差（判"内容是否真变了"）
    """
    ref_set = False
    stable_streak = 0
    count = 0
    last_save = 0.0
    now = 0.0
    events = []

    for idx, (motion, content) in enumerate(frames):
        now += dt
        if not ref_set:
            ref_set = True
            last_save = now
            events.append("base@%.2fs" % now)
            continue

        in_cooldown = (now - last_save) < COOLDOWN_S

        if motion < STABLE_TH:
            stable_streak += 1
            state = "STABLE"
        else:
            stable_streak = 0
            state = "MOVE"

        should_save = (
            state == "STABLE"
            and stable_streak >= STABLE_FRAMES
            and content >= SAVE_MIN_DIFF
            and not in_cooldown
        )
        if should_save:
            count += 1
            last_save = now
            stable_streak = 0
            events.append("SAVE#%d@%.2fs(mot=%.1f,con=%.1f)"
                          % (count, now, motion, content))

    return count, events


def scenario(name, frames, want_exact=None, want_min=None):
    n, ev = simulate(frames)
    if want_exact is not None:
        ok = (n == want_exact)
        expect = "== %d" % want_exact
    else:
        ok = (n >= want_min)
        expect = ">= %d" % want_min
    print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    print("         保存 %d 张（期望 %s）" % (n, expect))
    for e in ev:
        print("           " + e)
    print()
    return ok


def main() -> int:
    print("=" * 68)
    print("  auto_capture.py 变化检测逻辑验证")
    print("=" * 68)
    print()

    results = []

    # 场景 1：空托盘 -> 放料过程 -> 静止（物件一直在，content 保持大）
    f1 = ([(0.2, 0.2)] * 20        # 空托盘，完全静止
          + [(20.0, 20.0)] * 20    # 放料过程中，帧间差大
          + [(0.5, 30.0)] * 30)    # 放好静止，但 content 仍大（物件在）
    results.append(scenario("场景1 放一次料后不动", f1, want_exact=1))

    # 场景 2：放好之后长时间不动（60 帧），不应重复保存
    f2 = ([(0.2, 0.2)] * 10
          + [(20.0, 20.0)] * 20
          + [(0.5, 30.0)] * 60)
    results.append(scenario("场景2 放好不动60帧（防重复）", f2, want_exact=1))

    # 场景 3：放一次 -> 挪走（content 回落）-> 再放一次
    f3 = ([(0.2, 0.2)] * 10
          + [(20.0, 20.0)] * 20
          + [(0.5, 30.0)] * 30     # 第一次保存
          + [(15.0, 15.0)] * 20    # 挪走
          + [(0.5, 25.0)] * 30)    # 第二次放好 -> 再保存
    results.append(scenario("场景3 放料->挪走->再放", f3, want_min=2))

    # 场景 4：只抖动但没有实质内容变化（content 一直很小）-> 不应保存
    f4 = ([(0.2, 0.2)] * 10
          + [(2.0, 2.0)] * 40)     # motion<STABLE_TH 但 content<SAVE_MIN_DIFF
    results.append(scenario("场景4 轻微抖动无实质变化（防误存）",
                            f4, want_exact=0))

    print("=" * 68)
    n_ok = sum(1 for r in results if r)
    print("  %d/%d 通过" % (n_ok, len(results)))
    print("=" * 68)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
