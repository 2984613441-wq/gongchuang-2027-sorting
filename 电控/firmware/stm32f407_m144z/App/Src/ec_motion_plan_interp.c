/* ec_motion_plan_interp.c - XY interpolation variant of motion planning.
 *
 * This file provides ec_motion_plan_build_interp(), which generates an
 * independent six-step pick-place sequence, but replaces the production
 * sequential X+Y moves with simultaneous XY_INTERP steps for diagonal
 * trajectories.
 *
 * Time savings: ~29% for diagonal moves, 0% for axial-only moves.
 *
 * [EXPERIMENTAL - 待实测验证]
 *
 * 🔴 2026-09-22 实测确认（别以为它在跑）：**本文件不参与任何现行构建** ——
 *   · Keil 工程 `MDK-ARM/diankongv1.0.uvprojx` 里**没有**它（只在 :469-471 收了
 *     `ec_motion_plan.c`）；`diankongv1.0.uvoptx:390` 同样没有 ⇒ 板子上跑的**不是**这份。
 *   · `tests/CMakeLists.txt` 的 7 个主机测试目标也都不编它 ⇒ ctest 覆盖不到。
 *   ⇒ 只有把路线切到 XY 插补时才生效（见 `docs/XY插补-快速启动.md:84`）。
 *   ⇒ 因此改动本文件的验证手段只有两条：① 与串行版 `ec_motion_plan.c` **逐条对齐**；
 *     ② 单独 `gcc -std=c11 -Wall -Wextra -Werror -pedantic -c` 过一遍（无测试可跑）。
 *   ⚠️ 2026-09-22 已把它的起止位与 PARK 校验同步到串行版（leg1 起点 / leg3 终点 = PARK）。
 */

#include "ec_motion_plan.h"

#include <stddef.h>
#include <string.h>

/* 注：原先这里还复制了一份 mm10_to_steps()（ec_motion_plan.c 的同名 static
 * helper），但本文件从未调用它 —— 已删除。set_xy_interp() 直接用有符号
 * 增量算 target_*_steps，方向和步数都由调用方（ec_axis_driver）解释。 */

static void set_gripper(ec_axis_step_t *step, uint16_t pulse_us)
{
    step->kind = EC_AXIS_STEP_GRIPPER;
    step->axis = EC_AXIS_NONE;
    step->steps = 0U;
    step->direction = EC_DIRECTION_0;
    step->servo_pulse_us = pulse_us;
    step->target_x_steps = 0;
    step->target_y_steps = 0;
}

static void set_xy_interp(ec_axis_step_t *step,
                          int16_t from_x_mm10, int16_t from_y_mm10,
                          int16_t to_x_mm10, int16_t to_y_mm10)
{
    step->kind = EC_AXIS_STEP_XY_INTERP;
    step->axis = EC_AXIS_NONE;
    step->steps = 0U;
    step->direction = EC_DIRECTION_0;
    step->servo_pulse_us = 0U;

    /* Convert mm10 deltas to steps */
    int32_t delta_x = (int32_t)(to_x_mm10 - from_x_mm10);
    int32_t delta_y = (int32_t)(to_y_mm10 - from_y_mm10);

    step->target_x_steps = (delta_x * (int32_t)EC_AXIS_STEPS_PER_MM_X) / 10;
    step->target_y_steps = (delta_y * (int32_t)EC_AXIS_STEPS_PER_MM_Y) / 10;
}

/* True when one waypoint (both axes, 0.1mm) sits inside its axis bounds. Kept local
 * to this translation unit: ec_motion_plan.c's copy is static too.
 * 四个边界显式传入（2026-09-19「甲′」，与串行版同步）：可达域已非对称 ——
 * 负端是 HOME 压线的机械最里角，正端另让 5mm。协议域仍对称 ±1450。 */
static bool within_limits(int16_t x_mm10, int16_t y_mm10,
                          int16_t x_min, int16_t x_max,
                          int16_t y_min, int16_t y_max)
{
    return (x_mm10 >= x_min) && (x_mm10 <= x_max) &&
           (y_mm10 >= y_min) && (y_mm10 <= y_max);
}

bool ec_motion_plan_build_interp(ec_axis_pick_place_t *out,
                                 int16_t pick_x_mm10, int16_t pick_y_mm10,
                                 int16_t place_x_mm10, int16_t place_y_mm10)
{
    if (out == NULL) return false;
    /* 双重域检查，与 ec_motion_plan_build() 保持一致（2026-09-15）：
     * 协议合法域 ±1450 ∩ 机械可达域 X[-950,+900]/Y[-975,+925]，实际生效的是后者
     * （2026-09-19「甲′」改非对称，与串行版同一组宏）。
     * 原先本函数只查 1450 —— 会放行机械够不到的坐标，而 X/Y 已不装限位开关，
     * 越界无任何硬件能发现。
     * 2026-09-16（P2）：与串行版一样，**两组坐标都查**（见 ec_motion_plan.c 同名注释）。 */
    if (!within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10,
                       -EC_MOTION_WORKSPACE_LIMIT_MM10,
                       EC_MOTION_WORKSPACE_LIMIT_MM10) ||
        !within_limits(pick_x_mm10, pick_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10) ||
        !within_limits(place_x_mm10, place_y_mm10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    /* HOME 也要查（2026-09-18，与串行版同步）：HOME 是被下成脉冲的坐标，
     * 但它是编译期常量，上面的双域检查只覆盖取料点与落料点。理由见
     * ec_motion_plan.c 同名注释 —— 常量越界同样会顶限位并带挂主控。
     * ⚠️ HOME 正好压在可达域**负端**边界上（2026-09-19「甲′」）：
     *    负端若被收紧，这里立刻失败、整个规划全废。 */
    if (!within_limits(EC_MOTION_HOME_X_MM10, EC_MOTION_HOME_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    /* 🔴 2026-09-22：PARK 同理由也必须查 —— 它和 HOME 一样是**会被下成脉冲的
     * 编译期常量**（本文件 step[0] 的起点、step[5] 的终点）。照串行版
     * ec_motion_plan.c 的写法 fail-closed：常量不合法 ⇒ 整条计划不成立。
     * ⚠️ 漏查的后果与 X 那次超程事故同一成因：常量越界照样发脉冲 ⇒ 顶死堵转。 */
    if (!within_limits(EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                       -EC_MOTION_REACH_LIMIT_X_MM10,
                       EC_MOTION_REACH_FAR_X_MM10,
                       -EC_MOTION_REACH_LIMIT_Y_MM10,
                       EC_MOTION_REACH_FAR_Y_MM10)) {
        return false;
    }

    (void)memset(out, 0, sizeof(*out));

    /* Interpolated six-step program:
     * step[0]: PARK -> PICK (XY simultaneous)
     * step[1]: gripper open
     * step[2]: gripper close (grab)
     * step[3]: PICK -> PLACE (XY simultaneous)
     * step[4]: gripper open (release)
     * step[5]: PLACE -> PARK (XY simultaneous)
     * step[6]: (unused, kept for array size compatibility)
     * step[7]: (unused)
     *
     * 🔴 2026-09-22：起止位由 HOME 改为 PARK（与串行版 ec_motion_plan.c 同步）。
     *   PARK = 第二落点 (-95.0, +47.5)，在相机画面之外 ⇒ 拍照时夹爪不入画。
     *   ⚠️ HOME 仍是【上电原点】（硬限位，不变量不变），只是不再是程序起止位；
     *     本文件与串行版一样**假定程序开始时滑台在 PARK**。
     */

    set_xy_interp(&out->step[0],
                  EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10,
                  pick_x_mm10, pick_y_mm10);

    set_gripper(&out->step[1], EC_AXIS_GRIPPER_OPEN_US);
    set_gripper(&out->step[2], EC_AXIS_GRIPPER_CLOSE_US);

    /* Same pick_x/pick_y as step 0's endpoint - see ec_motion_plan.c. */
    set_xy_interp(&out->step[3],
                  pick_x_mm10, pick_y_mm10,
                  place_x_mm10, place_y_mm10);

    set_gripper(&out->step[4], EC_AXIS_GRIPPER_OPEN_US);

    set_xy_interp(&out->step[5],
                  place_x_mm10, place_y_mm10,
                  EC_MOTION_PARK_X_MM10, EC_MOTION_PARK_Y_MM10);

    /* The remaining fixed-size array slots stay zero (unused tail). */
    (void)memset(&out->step[6], 0, sizeof(ec_axis_step_t));
    (void)memset(&out->step[7], 0, sizeof(ec_axis_step_t));

    return true;
}
