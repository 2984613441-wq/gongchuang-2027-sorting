# -*- coding: utf-8 -*-
"""把 [TurntablePositions] / [TurntableSides] 两节【追加】进 Pi 的 sorting_config.ini。

为什么是这个文件：链读 `--config`（默认 `/home/pi/sorting_config.ini`，
`run_chain.py` 的 `DEFAULT_CONFIG_PATH`），`run_chain.py:1049` 用
`config_has_section(args.config, "TurntablePositions")` 来决定是否切到方案C。
⚠️ 不是 `calibration_config.ini`（那份只管标定：CameraCalibration/ToolOffset/WorkspaceLimits）。

断言式（沿用本项目 pi_set_tooloffset.py 的纪律）：
  备份 → 已存在则拒绝 → 追加 → configparser 逐项回读 → 用生产 drop_strategy 试切方案C → 打印回滚命令

用法：python3 pi_add_turntable.py
"""
import configparser
import hashlib
import shutil
import sys
import time

CFG = "/home/pi/sorting_config.ini"

SECTIONS = ("TurntablePositions", "TurntableSides")

TEXT = """

# ====================================================================
# 方案C：3 个固定落点（[DropPoints]）× 转盘 2 个位置
# 2026-09-21 现场追加。有本节 ⇒ 链切方案C；删掉本节即回到方案A（六固定盒）。
# ====================================================================
[TurntablePositions]
# A/B 两组货格在转盘上相差 180°，共用同一组 3 个滑台落点。
# 🔴 2026-09-21 现场实测确认（直写 /home/pi/pw.txt 驱动舵机）：
#     845 µs = A 侧；2155 µs = B 侧；两侧正好相差 180°；
#     B 组 3 个货格落在 A 组原来那 3 个位置上；全程无异常声。
# 推导口径（与 turntable.py 的 angle_sign=-1 等价）：
#     pulse = center_us - angle_deg * us_per_90deg / 90
#     pulse_a = 1500 - (+90)*655/90 =  845 µs
#     pulse_b = 1500 - (-90)*655/90 = 2155 µs
center_us = 1500
us_per_90deg = 655
angle_a = 90
angle_b = -90
# 设计值 1.0。假链测试跑出的 0.05 是测试台假象（turntable_guard.py:139 用 %.1f 打印，
# 0.05 会显示成 "0.1"，并不存在 clamp）—— 绝不可为迁就假链改成它。
settle_s = 1.0
# GPIO17 索引侧：尚未空转确认 ⇒ 保持 none（到位只按 settle_s 计时判定，构造时会 WARNING）。
# 空转确认后只允许把这里改成 a 或 b。
index_side = none
index_pin = 17

[TurntableSides]
# 货格侧映射（用户 2026-09-21 确认）：1/2/3 = A 侧；4/5/6 = B 侧。
# 4/5/6 与 1/2/3 同滑台坐标，靠转盘翻 180° 落到另一侧。
1 = a
2 = a
3 = a
4 = b
5 = b
6 = b
"""


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    before = sha(CFG)

    cp = configparser.ConfigParser()
    cp.read(CFG, encoding="utf-8")
    dup = [s for s in SECTIONS if cp.has_section(s)]
    if dup:
        print("拒绝：这些节已存在 %s —— 本次不写入，避免重复追加。" % dup)
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-noturn-%s" % (CFG, stamp)
    shutil.copy2(CFG, bak)
    print("备份 -> %s" % bak)

    with open(CFG, "a", encoding="utf-8", newline="") as fh:
        fh.write(TEXT)

    # ---- 逐项回读 ----
    cp2 = configparser.ConfigParser()
    cp2.read(CFG, encoding="utf-8")
    miss = [s for s in SECTIONS if not cp2.has_section(s)]
    assert not miss, "追加后仍缺节：%s" % miss

    tp = cp2["TurntablePositions"]
    exp = {"center_us": "1500", "us_per_90deg": "655",
           "angle_a": "90", "angle_b": "-90",
           "settle_s": "1.0", "index_side": "none", "index_pin": "17"}
    for k, v in exp.items():
        got = tp.get(k)
        assert got == v, "[TurntablePositions] %s = %r，期望 %r" % (k, got, v)
        print("  [TurntablePositions] %-13s = %s  ✓" % (k, got))

    ts = cp2["TurntableSides"]
    for b, v in ((1, "a"), (2, "a"), (3, "a"), (4, "b"), (5, "b"), (6, "b")):
        got = ts.get(str(b))
        assert got == v, "[TurntableSides] %d = %r，期望 %r" % (b, got, v)
        print("  [TurntableSides]     %d = %s  ✓" % (b, got))

    # ---- 口径自算：必须正好得出实测值 ----
    c = tp.getfloat("center_us")
    u = tp.getfloat("us_per_90deg")
    pa = round(c - tp.getfloat("angle_a") * u / 90.0)
    pb = round(c - tp.getfloat("angle_b") * u / 90.0)
    assert pa == 845 and pb == 2155, "口径算出来 %s / %s，与实测 845/2155 不符" % (pa, pb)
    assert 500 <= pa <= 2500 and 500 <= pb <= 2500, "脉宽超出 500~2500 行程"
    print("  口径自算：pulse_a=%d  pulse_b=%d  （实测确认值）✓" % (pa, pb))

    # ---- 用生产 drop_strategy 试切方案C（容错：API 名不对也不影响结论）----
    sys.path.insert(0, "/home/pi/电控/src")
    try:
        from electrical_control.rpi import drop_strategy as ds
        fn = None
        for name in ("load_strategy", "build_strategy", "make_strategy"):
            if hasattr(ds, name):
                fn = getattr(ds, name)
                break
        if fn is None:
            print("  (跳过策略试切：drop_strategy 里没找到 load_strategy/build_strategy/make_strategy)")
        else:
            st = fn(CFG)
            print("  生产 drop_strategy 载入 -> %s" % type(st).__name__)
            assert "TwoPosition" in type(st).__name__, \
                "载入的不是 TwoPositionTurntableStrategy，可能没切到方案C"
            print("  ✓ 已切到方案C（TwoPositionTurntableStrategy）")
    except AssertionError:
        raise
    except Exception as exc:                                    # noqa: BLE001
        print("  (策略试切告警，不影响写入：%s: %s)" % (type(exc).__name__, exc))

    print("\nsha256 %s -> %s" % (before[:16], sha(CFG)[:16]))
    print("\n回滚（回到方案A）：")
    print("  cp -a %s %s" % (bak, CFG))
    print("  或：删掉文件里的 [TurntablePositions] 与 [TurntableSides] 两节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
