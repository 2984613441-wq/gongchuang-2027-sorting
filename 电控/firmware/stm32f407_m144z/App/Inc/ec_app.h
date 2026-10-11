#ifndef EC_APP_H
#define EC_APP_H

#include "ec_state_machine.h"

#include <stdbool.h>
#include <stdint.h>

/* Progress-source adapter switch (docs/design/2026-08-30-motion-time-budget.md
 * §3.3.2): only a bench-validated actuator-completion source may extend the
 * rolling no-motion watchdog window.
 *
 * 🔴 2026-09-21 用户裁决：**改为 1U（打开）**，三个落点变远后单件窗口内用量逼近/超过
 *    15 s，而赛规原文是「15 秒**没有动作** 或 没有显示」⇒ 连续运动本就不算失活。
 *    打开后固件口径回到赛规口径：每次计数移动完成即续命，只有**真的连续 15 秒没动**
 *    才 DEADLINE_EXPIRED。
 *    ⚠️ 打开需要**三处同时**：本宏 = 1U、Keil 工程宏
 *       （MDK-ARM/diankongv1.0.uvprojx 的 EC_APP_PROGRESS_SOURCE_ENABLED=1）、
 *       运行时开关（ec_app_init 里 progress_source_enabled = true）。
 *       少任何一处都仍然是"不续命"的老行为。
 *    ⚠️ 被观测的 token 只有"X/Y 计数移动自然完成"这一个来源（见 ec_app.c:499-512），
 *       舵机整定、WAIT、心跳、ACK 都不能续命 ⇒ 真的卡住不动仍会超时。
 *    ⚠️ HIL-PROGRESS-001（本注释原先要求的台架证据）**尚未做**；本次是按用户现场
 *       裁决先行打开，判据 = 跑一整轮 0 DEADLINE_EXPIRED / 0 FAULT_LOCK。 */
#ifndef EC_APP_PROGRESS_SOURCE_ENABLED
#define EC_APP_PROGRESS_SOURCE_ENABLED 1U
#endif

void ec_app_init(void);
void ec_app_poll(uint32_t now_ms);
void ec_app_on_uart_rx_byte(uint8_t byte);
ec_state_t ec_app_state(void);

/* Rolling no-motion watchdog (design §3.3): feed a bench-validated observable
 * progress token to re-base the 15 s window. No-op while the progress source
 * is disabled. Duplicate or stale tokens never re-extend; tokens delivered
 * outside an open window are ignored. */
void ec_app_note_observable_progress(uint32_t token);

/* Runtime progress-source adapter switch. When
 * EC_APP_PROGRESS_SOURCE_ENABLED is 0 this is a locked no-op (fail-closed);
 * when 1, it toggles the source that ec_app_note_observable_progress() feeds
 * on. An enabled build boots OFF pending HIL evidence; callers may turn it on
 * only after that evidence is recorded, or turn it off as a kill switch. */
void ec_app_progress_source_set_enabled(bool enabled);

/* Host-test seam (compiled out of production builds - the Keil target never
 * defines EC_APP_TEST_HOOKS). The app boot chain cannot reach WAIT_TASK on
 * the host because no barrier-feedback input is mapped; the test target uses
 * ec_app_test_force_barrier_verified() to stand in for the startup
 * sequence's BARRIER_AVOIDANCE_VERIFIED, and the two read-only probes to
 * assert the watchdog state exactly. */
#ifndef EC_APP_TEST_HOOKS
#define EC_APP_TEST_HOOKS 0
#endif
#if EC_APP_TEST_HOOKS
void ec_app_test_force_barrier_verified(void);
bool ec_app_test_watchdog_active(void);
uint32_t ec_app_test_last_observable_ms(void);
#endif

/* 2026-09-22 新增：非 fault 路径的「停轴现场」快照。
 *
 * 为什么需要它：ec_axis_driver_diag() 只在 ec_axis_driver 走 fault() 时才被填；
 * 而「轴被孤立」保护（ec_app_poll_motion 里离开可执行三态时）走的是
 * ec_axis_driver_stop() —— stop 不是 fault ⇒ 那份诊断永远读不到这条路径。
 * 实测后果：现场只剩 FAULTS=0 / LAST_*=0 / PROGRESS=0，查不出是哪一条原因，
 * 2026-09-21 的交接只能把它标成「拦路虎」。
 * 本快照专门补这一条路径，让「卡一下」第一次可读。
 *
 * 记录时机：调用 ec_axis_driver_stop() 之前（stop() 会把 progress 清零）。 */
typedef struct {
    uint8_t  valid;          /* 1 = 以下字段有效（只保留最近一次） */
    uint8_t  app_state;      /* 离开可执行三态时应用层所处的状态（ec_state_t） */
    uint8_t  driver_state;   /* 当时的轴驱动状态（EC_AXIS_STATE_MOVING / _GRIPPING） */
    uint8_t  fault_reason;   /* 最近一次锁机原因（ec_fault_reason_t；仅 FAULT_LOCK 时更新） */
    uint16_t active_inputs;  /* 停轴瞬间的有效输入掩码（ESTOP_FB = 0x0040） */
    uint16_t step_index;     /* 停在第几步（= 当时的 PROGRESS） */
    uint32_t moves;          /* 累计完成的计数移动数（MOVES） */
    uint32_t tick_ms;        /* 停轴时刻（对 Pi 日志时间用） */
    /* ── 2026-09-22 第二批（首战读数 FAULT=6=DEADLINE_EXPIRED 之后补）───
     * 首战证明"15 秒窗"才是真因，但"为什么没被续命"还差这几个数。 */
    uint8_t  wd_active;      /* 停轴时 watchdog_active（续命第一道门；也是判据的前置） */
    uint8_t  reserved;       /* 对齐填充 */
    uint32_t last_obs_ms;    /* 窗口基准 last_observable_ms（最后一条有效进展的时刻） */
    uint32_t silent_ms;      /* tick_ms - last_obs_ms：静默了多久（≥15000 即触发判据） */
    uint32_t moves_at_arm;   /* 本次开窗时的 MOVES ⇒ moves-moves_at_arm = 窗口期内完成了几次计数移动 */
    /* ── 2026-09-22 第三批 ── */
    uint8_t  position_valid;   /* A0：位置是否仍可信。异常停止（进 FAULT_LOCK）后为 0 */
    uint8_t  exec_exit_to;     /* 最近一次"离开 EXECUTING"到达的状态（0 = 尚未记录） */
    uint8_t  exec_exit_reason; /* 那次离开时的 fault_reason（0 = NONE；非粘性） */
    uint8_t  pad0;
} ec_app_stop_snapshot_t;

/* 取最近一次保护性停轴的现场；从未发生过则返回 false 且不改 *out。 */
bool ec_app_last_stop_snapshot(ec_app_stop_snapshot_t *out);

/* 取【上一次】保护性停轴的现场（第二次卡顿会覆盖 last ⇒ 靠它保住第一次那条线索）。
 * 形参 which = 1 取上次。返回 false 表示没有更早的记录。 */
bool ec_app_stop_snapshot_at(uint8_t which, ec_app_stop_snapshot_t *out);

#endif
