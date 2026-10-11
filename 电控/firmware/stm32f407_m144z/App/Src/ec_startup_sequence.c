/* ec_startup_sequence.c - Safety startup chain implementation
 *
 * Implements POST, homing ("power-on position = origin"), and barrier
 * avoidance checks that generate the events previously auto-injected in
 * ec_app.c:108-131.
 *
 * ============================ 2026-09-19 用户裁决 ============================
 * X/Y **不装限位开关/编码器**，原点方案 = **乙. 上电位置即 HOME**：
 *   固件会把开机时机构当前位置直接认定为 HOME。操作要求：**上电前人工把 X/Y
 *   推到各自负方向最里角**（设备中心系 -95.0mm,-97.5mm），然后上电；此后不寻零。
 *
 * 因此本文件不再检查任何限位输入（X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN）。
 * 对应地，ec_axis_driver.c / ec_demo.c / ec_servo_test.c / ec_step_test.c 的
 * 安全遮罩也已从"6 限位 + ESTOP"收敛为"仅 ESTOP"。
 *
 * ⚠️ 由此产生的**唯一运动保护**是软件侧的：
 *   1) EC_INPUT_ESTOP_FB —— 急停反馈
 *   2) EC_MOTION_WORKSPACE_LIMIT_MM10 = 1450（ec_motion_plan.h:31）—— 越界坐标
 *      直接拒绝建程序（ec_motion_plan_build 返回 false）
 *   3) 计数步超时 EC_AXIS_MOVE_TIMEOUT_MARGIN_MS + 赛规 15 秒失活监控
 *
 * ⚠️ 已知残留风险：**丢步**时实际位置会与指令位置漂移，软件域限制无法察觉。
 *    因为没有硬件限位可复核，长时间跑动后建议人工回中并重新上电。
 * ==========================================================================
 */

#include "ec_startup_sequence.h"
#include "ec_board.h"
#include "ec_inputs.h"

#include <stdbool.h>
#include <stdint.h>

#define POST_TIMEOUT_MS     UINT32_C(2000)
/* 方案 A 下无需等待任何开关触发，只留一个稳定窗口供滤波/人工确认 */
#define HOMING_SETTLE_MS    UINT32_C(500)
/* BARRIER_TIMEOUT_MS 已于 2026-09-16 删除：挡板取消后，本阶段不再有
 * "等反馈直到超时"这回事 —— 见 ec_startup_sequence_poll_barrier()。 */

typedef enum {
    POST_IDLE = 0,
    POST_RUNNING,
    POST_PASSED,
    POST_FAILED,
} ec_post_state_t;

typedef enum {
    HOMING_IDLE = 0,
    HOMING_RUNNING,
    HOMING_PASSED,
    HOMING_FAILED,
} ec_homing_state_t;

typedef enum {
    BARRIER_IDLE = 0,
    BARRIER_RUNNING,
    BARRIER_PASSED,
    BARRIER_FAILED,
} ec_barrier_state_t;

static ec_post_state_t post_state = POST_IDLE;
static ec_homing_state_t homing_state = HOMING_IDLE;
static ec_barrier_state_t barrier_state = BARRIER_IDLE;

static uint32_t post_start_ms;
static uint32_t homing_start_ms;

void ec_startup_sequence_init(void)
{
    post_state = POST_IDLE;
    homing_state = HOMING_IDLE;
    barrier_state = BARRIER_IDLE;
}

void ec_startup_sequence_begin_post(uint32_t now_ms)
{
    if (post_state != POST_IDLE) {
        return;
    }
    post_state = POST_RUNNING;
    post_start_ms = now_ms;
}

void ec_startup_sequence_begin_homing(uint32_t now_ms)
{
    if (homing_state != HOMING_IDLE) {
        return;
    }
    homing_state = HOMING_RUNNING;
    homing_start_ms = now_ms;
    /* 方案乙（2026-09-19 用户裁决，**以此为准**）：上电位置即原点，不做寻零运动。
     * 不移动任何轴，只等待 HOMING_SETTLE_MS 稳定窗口后认定原点已建立。
     * 人工责任：**上电前把 X/Y 推到各自负方向最里角顶住** =
     *           设备中心系 (-95.0mm, -97.5mm)（也就是 HOME）。
     * 🔴 2026-09-22：一度改为「X 顶负端 + Y 推正端停车位 (+85.5)」，**已独立审核并回退**。
     *    原因：+85.5 不是硬限位 ⇒ 上电原点失去可复现的绝对基准（详见 ec_motion_plan.h:193 前的记录）。
     * 🔴 2026-09-22 更正：本行原写「摆到装置中心」——那是**已被推翻的方案 A**
     *    （上电原点 = 装置中心 (0,0)）。照它做会让整场比赛的坐标整体偏 95.0mm。
     *    同文件 :159-167（poll_homing）与文件头 :8-10 一直是正确的，只有本行是漏网的旧文案。 */
}

void ec_startup_sequence_begin_barrier(uint32_t now_ms)
{
    (void)now_ms;   /* 计时变量已随挡板取消一并删除（2026-09-16） */

    if (barrier_state != BARRIER_IDLE) {
        return;
    }
    barrier_state = BARRIER_RUNNING;
    /* 挡板已取消（用户 2026-09-15 裁决）。本阶段不再"命令挡板到位并等反馈"，
     * 只在 poll_barrier 里立即放行 —— 见该函数的说明。 */
}

ec_startup_result_t ec_startup_sequence_poll_post(uint32_t now_ms,
                                                   uint16_t active_inputs)
{
    if (post_state != POST_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    /* POST checks (2026-09-15: 限位检查已移除，见文件头说明)。
     * Checks performed:
     * 1. ESTOP not active
     * 2. Power permission present (when the GPIO is wired)
     *
     * Future expansion: driver enable verification, servo response, screen comm.
     */

    /* Check 1: ESTOP must not be active */
    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* Check 2: Power permission must be present */
    if ((active_inputs & EC_INPUT_POWER_PERMISSION) != 0U) {
        /* active_inputs is active-low: a set bit means the input line is low
         * and power permission has been lost. */
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* POST passed: basic checks complete, allow minimum 50ms for stability */
    if ((uint32_t)(now_ms - post_start_ms) >= 50U) {
        post_state = POST_PASSED;
        return EC_STARTUP_PASSED;
    }

    /* Timeout check */
    if ((uint32_t)(now_ms - post_start_ms) >= POST_TIMEOUT_MS) {
        post_state = POST_FAILED;
        return EC_STARTUP_FAILED;
    }

    return EC_STARTUP_RUNNING;
}

ec_startup_result_t ec_startup_sequence_poll_homing(uint32_t now_ms,
                                                     uint16_t active_inputs)
{
    if (homing_state != HOMING_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    /* 方案乙（2026-09-19 用户裁决）：**上电位置即 HOME**。
     *
     * 不再检查 X_HOME/Y_HOME，也不做寻零运动 —— 上电时机构所在位置直接
     * 认定为 HOME(-95.0mm,-97.5mm)。因此本阶段只做两件事：
     *   1. 确认 ESTOP 未触发、电源许可仍在（安全前置条件）
     *   2. 等满 HOMING_SETTLE_MS 稳定窗口后宣告原点已建立
     *
     * 人工责任：**上电前必须把 X/Y 推到各自负方向最里角**，否则整场比赛的
     *           设备坐标都会整体平移，落点全部偏移。
     */

    /* 安全前置条件：ESTOP 触发即失败 */
    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        homing_state = HOMING_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* 安全前置条件：电源许可丢失即失败 */
    if ((active_inputs & EC_INPUT_POWER_PERMISSION) != 0U) {
        homing_state = HOMING_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* 稳定窗口到期即认定原点已建立（无开关可等，故无超时失败分支） */
    if ((uint32_t)(now_ms - homing_start_ms) >= HOMING_SETTLE_MS) {
        homing_state = HOMING_PASSED;
        return EC_STARTUP_PASSED;
    }

    return EC_STARTUP_RUNNING;
}

ec_startup_result_t ec_startup_sequence_poll_barrier(uint32_t now_ms,
                                                      uint16_t active_inputs)
{
    (void)now_ms;

    if (barrier_state != BARRIER_RUNNING) {
        return EC_STARTUP_IDLE;
    }

    if ((active_inputs & EC_INPUT_ESTOP_FB) != 0U) {
        barrier_state = BARRIER_FAILED;
        return EC_STARTUP_FAILED;
    }

    /* 2026-09-16：用户 09-15 裁决【两种主方案都不装挡板】—— 挡板及其位置
     * 反馈在硬件上已不存在，本阶段没有可等待的反馈。
     *
     * 原实现在此等 5 秒后必然 BARRIER_FAILED，经 ec_app.c:382-395 注入
     * EMERGENCY_STOP → FAULT。而 BARRIER_AVOIDANCE_VERIFIED 是通往
     * WAIT_TASK 的【唯一】路径（ec_state_machine.c:107-111），WAIT_TASK 又是
     * 接受 ITEM_TASK 的【唯一】状态（ec_state_machine.c:140）。于是启动序列
     * 永远走不到 WAIT_TASK，状态机拒收一切 ITEM_TASK —— 机构完全不动。
     *
     * 挡板既已取消，本阶段直接放行。
     * ESTOP 判定保留在此；此外 ec_axis_driver 的 EC_AXIS_SAFETY_MASK
     * （EC_INPUT_ESTOP_FB）在 arming 前还会再判一次。 */
    barrier_state = BARRIER_PASSED;
    return EC_STARTUP_PASSED;
}

void ec_startup_sequence_reset(void)
{
    post_state = POST_IDLE;
    homing_state = HOMING_IDLE;
    barrier_state = BARRIER_IDLE;
}
