# -*- coding: utf-8 -*-
"""单件周期时间分析：串行 vs XY 联动，以及提速幅度。

依据（全部来自固件源码，非估算）：
  - steps_per_mm = 80
  - 巡航 = EC_STEP_CRUISE_HZ_DEFAULT（现 8000 Hz）
  - 起止频率 200 Hz、加/减速 10000 Hz/s（ec_step_profile_plan 的实参）
  - 曲线时长公式见 ec_step_profile_plan

跑：python _pi_tools/analyze_cycle_time.py
"""
import math

STEPS_PER_MM = 80
START_HZ = 200.0
END_HZ = 200.0
ACCEL = 10000.0
DECEL = 10000.0

# 12 步计划里固定的时间开销（源码常量）
GRIPPER_SETTLE_MS = 600      # EC_AXIS_GRIPPER_SETTLE_MS：每个舵机步 settle
SERVO_STEPS = 5              # [0][2][4][6][7]
PICK_DWELL_MS = 200          # EC_AXIS_PICK_DWELL_MS：[3] 纯等待
WAIT_STEPS_MS = PICK_DWELL_MS

# 关键坐标（0.1mm）
PARK = (-950, 475)           # EC_MOTION_PARK_*：程序起止位
HOME = (-950, -975)          # 上电原点（不参与每件循环）
# 取料点：sorting_config.ini [PickPoint] x=0.0 y=-45.0
PICK = (0, -450)
# 落料点：暂定最远端（方案B 固定落点）
PLACE = (900, 885)


def leg_time_ms(steps: int, cruise_hz: float) -> float:
    """单轴按固件曲线跑 steps 步所需时间（ms）。

    曲线用 ec_step_profile_plan(profile, steps, 200, cruise, 200, 10000, 10000)：
      · 加速段步数 a = (cruise² − start²) / (2·accel)
      · 减速段步数 d = (cruise² − end²)   / (2·decel)
      · 若 a + d <= steps：梯形（有巡航段）
      · 否则：三角形（峰值降为 v，v² = (2·a·d·N + d·s² + a·e²)/(a+d)）
    """
    s, e, a, d = START_HZ, END_HZ, ACCEL, DECEL
    if steps <= 0:
        return 0.0
    accel_steps = (cruise_hz ** 2 - s ** 2) / (2.0 * a)
    decel_steps = (cruise_hz ** 2 - e ** 2) / (2.0 * d)
    if accel_steps + decel_steps <= steps:
        # 梯形
        cruise_steps = steps - accel_steps - decel_steps
        t_accel = (cruise_hz - s) / a
        t_decel = (cruise_hz - e) / d
        t_cruise = cruise_steps / cruise_hz
        total_s = t_accel + t_cruise + t_decel
    else:
        # 三角形：求峰值
        N = float(steps)
        v2 = (2.0 * a * d * N + d * s ** 2 + a * e ** 2) / (a + d)
        v = math.sqrt(max(v2, 0.0))
        t_accel = (v - s) / a
        t_decel = (v - e) / d
        total_s = t_accel + t_decel
    return total_s * 1000.0


def leg_steps(a, b):
    return (abs(b[0] - a[0]) * STEPS_PER_MM // 10,
            abs(b[1] - a[1]) * STEPS_PER_MM // 10)


def main():
    legs = [
        ("PARK→PICK ", PARK, PICK),
        ("PICK→PLACE", PICK, PLACE),
        ("PLACE→PARK", PLACE, PARK),
    ]

    print("=" * 78)
    print("单件 12 步计划的时间账")
    print("=" * 78)
    fixed_ms = SERVO_STEPS * GRIPPER_SETTLE_MS + WAIT_STEPS_MS
    print(f"固定开销：{SERVO_STEPS} 个舵机步 × {GRIPPER_SETTLE_MS}ms "
          f"+ {WAIT_STEPS_MS}ms 等待 = {fixed_ms} ms")

    for cruise in (5000, 8000):
        print(f"\n── 巡航 {cruise} Hz " + "─" * 50)
        seq_ms = 0.0
        par_ms = 0.0
        for name, src, dst in legs:
            sx, sy = leg_steps(src, dst)
            tx = leg_time_ms(sx, cruise)
            ty = leg_time_ms(sy, cruise)
            seq_ms += tx + ty               # 串行：先走完一个轴再走另一个
            par_ms += max(tx, ty)           # 联动：两轴同时，取长的
            print(f"  {name}  {sx:>6} x-steps → {tx:7.0f}ms | "
                  f"{sy:>6} y-steps → {ty:7.0f}ms | "
                  f"串行 {tx + ty:7.0f} | 联动 {max(tx, ty):7.0f}")
        total_seq = fixed_ms + seq_ms
        total_par = fixed_ms + par_ms
        print(f"  {'-' * 74}")
        print(f"  串行合计: {total_seq:7.0f} ms = {total_seq/1000:.2f} s")
        print(f"  联动合计: {total_par:7.0f} ms = {total_par/1000:.2f} s")
        print(f"  联动节省: {total_seq - total_par:7.0f} ms "
              f"({(total_seq-total_par)/total_seq*100:.1f}%)")

    print("\n" + "=" * 78)
    print("13 件预算对比（赛规：3 分钟 = 180 s，13 个物料）")
    print("=" * 78)
    budget_per_item = 180.0 / 13.0
    print(f"  每件预算: {budget_per_item:.2f} s")
    for cruise in (5000, 8000):
        for mode, label in ((False, "串行"), (True, "联动")):
            seq_ms = par_ms = 0.0
            for _name, src, dst in legs:
                sx, sy = leg_steps(src, dst)
                tx = leg_time_ms(sx, cruise)
                ty = leg_time_ms(sy, cruise)
                seq_ms += tx + ty
                par_ms += max(tx, ty)
            per_item = (fixed_ms + (par_ms if mode else seq_ms)) / 1000.0
            total = per_item * 13
            margin = 180.0 - total
            status = "✅ 够" if margin > 0 else "❌ 超时"
            print(f"  {cruise}Hz {label}: 每件 {per_item:5.2f}s ⇒ 13 件 "
                  f"{total:6.1f}s  余量 {margin:+6.1f}s  {status}")

    print("\n" + "=" * 78)
    print("固定开销削减空间（GRIPPER_SETTLE_MS 的敏感度）")
    print("=" * 78)
    for settle in (600, 500, 400, 300, 200):
        f = SERVO_STEPS * settle + WAIT_STEPS_MS
        seq_ms = par_ms = 0.0
        for _name, src, dst in legs:
            sx, sy = leg_steps(src, dst)
            tx = leg_time_ms(sx, 8000)
            ty = leg_time_ms(sy, 8000)
            seq_ms += tx + ty
            par_ms += max(tx, ty)
        par_total = (f + par_ms) / 1000.0
        print(f"  settle={settle:3d}ms (5 步共 {SERVO_STEPS*settle:4d}ms): "
              f"每件 {par_total:5.2f}s ⇒ 13 件 {par_total*13:6.1f}s")
    print("\n  ⚠️ settle 不能盲降：它是舵机从收到脉宽到机械到位的时间。")
    print("     降过头 ⇒ 夹爪没到位就移动 ⇒ 夹空或撞飞。必须先实测合拢时间（R4）。")


if __name__ == "__main__":
    main()
