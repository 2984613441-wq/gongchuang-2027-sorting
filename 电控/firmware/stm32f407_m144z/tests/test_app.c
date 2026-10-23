#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_inputs.h"
#include "ec_motion_plan.h"
#include "ec_protocol.h"
#include "ec_protocol_gateway.h"
#include "test_support.h"

#include <stddef.h>

static unsigned safe_state_calls;
static unsigned input_poll_calls;
static unsigned uart_start_calls;
static unsigned uart_tx_calls;

/* --- board doubles --- */
void ec_board_enter_safe_state(void) { safe_state_calls++; }
void ec_board_poll_inputs(uint32_t now_ms) { (void)now_ms; input_poll_calls++; }
void ec_board_uart_start_rx(void) { uart_start_calls++; }
/* 2026-09-16（ACK 回归）：只数 uart_tx_calls 的话，"ACK 被丢掉" 和
 * "STATUS 之类的别的帧被发出" 在计数上长得一模一样 —— 这正是 ACK(ACCEPTED)
 * 丢失能长期活在测试盲区里的原因。所以这里把每一帧真的解出来，记录
 * command / ACK-NACK 的 reason+target_seq / 外层 frame_seq(=网关 tx_seq)。
 * 生产侧一帧就是 ec_app_flush_tx() 的一次 transmit（tx_buf 里只有一帧）。 */
typedef struct {
    bool decoded;
    size_t len;
    uint8_t command;
    uint8_t reason;       /* ACK/NACK payload byte 0 */
    uint8_t target_seq;   /* ACK/NACK payload byte 1 */
    uint16_t frame_seq;   /* outbound STM32 tx_seq (interface-contract sec. 3) */
} tx_frame_record_t;

#define TX_RECORD_MAX 64U
#define TX_ANY UINT8_C(0xFF)   /* tx_count()/tx_find() 里的"任意值"通配 */

static tx_frame_record_t tx_records[TX_RECORD_MAX];
static unsigned tx_record_count;

static void tx_records_reset(void)
{
    unsigned i;

    for (i = 0U; i < TX_RECORD_MAX; ++i) {
        tx_records[i].decoded = false;
        tx_records[i].len = 0U;
        tx_records[i].command = 0U;
        tx_records[i].reason = 0U;
        tx_records[i].target_seq = 0U;
        tx_records[i].frame_seq = 0U;
    }
    tx_record_count = 0U;
}

/* 发送记录里 command 匹配（ACK/NACK 还要 reason/target_seq 匹配）的帧数。 */
static unsigned tx_count(uint8_t command, uint8_t reason, uint8_t target_seq)
{
    unsigned i;
    unsigned found = 0U;

    for (i = 0U; i < tx_record_count; ++i) {
        const tx_frame_record_t *rec = &tx_records[i];

        if (!rec->decoded || (rec->command != command)) continue;
        if ((reason != TX_ANY) && (rec->reason != reason)) continue;
        if ((target_seq != TX_ANY) && (rec->target_seq != target_seq)) continue;
        ++found;
    }
    return found;
}

/* 第一条匹配的发送记录；没有则 NULL。 */
static const tx_frame_record_t *tx_find(uint8_t command, uint8_t reason,
                                        uint8_t target_seq)
{
    unsigned i;

    for (i = 0U; i < tx_record_count; ++i) {
        const tx_frame_record_t *rec = &tx_records[i];

        if (!rec->decoded || (rec->command != command)) continue;
        if ((reason != TX_ANY) && (rec->reason != reason)) continue;
        if ((target_seq != TX_ANY) && (rec->target_seq != target_seq)) continue;
        return rec;
    }
    return NULL;
}

void ec_board_uart_transmit(const uint8_t *data, size_t length)
{
    ec_proto_frame_t frame;
    tx_frame_record_t *rec;

    uart_tx_calls++;

    if ((data == NULL) || (tx_record_count >= TX_RECORD_MAX)) {
        return;   /* 记不下就只丢记录，不去影响被测逻辑 */
    }

    rec = &tx_records[tx_record_count];
    rec->len = length;
    rec->decoded = ec_proto_decode(data, length, &frame);
    if (rec->decoded) {
        rec->command = frame.command;
        rec->frame_seq = frame.frame_seq;
        if ((frame.command == EC_CMD_ACK) || (frame.command == EC_CMD_NACK)) {
            (void)ec_proto_decode_ack(frame.payload, frame.payload_len,
                                      &rec->reason, &rec->target_seq);
        }
    }
    ++tx_record_count;
}

/* P0-FIX (ec_board.h): UART RX ring-buffer doubles. The tests feed frames
 * straight into ec_app_on_uart_rx_byte(), so the ring is always empty. */
bool ec_board_uart_rx_available(void) { return false; }
uint8_t ec_board_uart_rx_read(void) { return 0U; }

/* Active-input mask, shared with test_diag.c's ec_board_read_inputs double. */
extern uint16_t fake_active_inputs;

/* --- axis_driver doubles --- */
static ec_axis_state_t fake_axis_state;
static ec_axis_result_t fake_axis_result;
static uint32_t fake_axis_progress;
static bool fake_axis_progress_advance;

void ec_axis_driver_init(void)
{
    fake_axis_state = EC_AXIS_STATE_IDLE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    fake_axis_progress = 0U;
    fake_axis_progress_advance = false;
}

ec_axis_result_t ec_axis_driver_start_pick_place(const ec_axis_pick_place_t *p)
{
    (void)p;
    fake_axis_state = EC_AXIS_STATE_MOVING;
    fake_axis_result = EC_AXIS_RESULT_OK;
    fake_axis_progress = 0U;
    fake_axis_progress_advance = false;
    return EC_AXIS_RESULT_OK;
}

ec_axis_result_t ec_axis_driver_poll(uint32_t now_ms, uint16_t active_inputs)
{
    (void)now_ms;
    (void)active_inputs;
    if (fake_axis_progress_advance) {
        ++fake_axis_progress;
        fake_axis_progress_advance = false;
    }
    return fake_axis_result;
}

/* P0-FIX (ec_safety_adapter.c): SAFE_LOCK -> STOP_ALL calls
 * ec_axis_driver_stop(). Mirror the production driver's reset. */
void ec_axis_driver_stop(void)
{
    fake_axis_state = EC_AXIS_STATE_IDLE;
    fake_axis_result = EC_AXIS_RESULT_OK;
}

ec_axis_state_t ec_axis_driver_state(void) { return fake_axis_state; }
ec_axis_result_t ec_axis_driver_result(void) { return fake_axis_result; }
uint32_t ec_axis_driver_progress(void) { return fake_axis_progress; }
uint32_t ec_axis_driver_completed_move_count(void) { return fake_axis_progress; }

/* --- motion_plan double --- */
static int16_t fake_plan_x;
static int16_t fake_plan_y;
static unsigned fake_plan_calls;

/* P3 (2026-09-16): the production signature is the 5-argument pick+place form
 * (ec_motion_plan.h); this double was still the old 3-argument shape and no
 * longer compiled. Record both pairs so a test can tell the grasp point from
 * the drop point. */
static int16_t fake_plan_pick_x;
static int16_t fake_plan_pick_y;

bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t pick_x_mm10, int16_t pick_y_mm10,
                          int16_t place_x_mm10, int16_t place_y_mm10)
{
    (void)out;
    fake_plan_pick_x = pick_x_mm10;
    fake_plan_pick_y = pick_y_mm10;
    fake_plan_x = place_x_mm10;
    fake_plan_y = place_y_mm10;
    ++fake_plan_calls;
    return true;
}

/* A2-FIX (2026-09-22): ec_motion_plan 新增的类别开度接口，test_app.c 需补充 double。
 * 真实实现在 ec_motion_plan.c:147-174；此处返回固定的待机开度作为测试桩。 */
uint16_t ec_motion_plan_open_us_for_class(uint8_t class_id)
{
    (void)class_id;
    return EC_AXIS_GRIPPER_STANDBY_US;  /* 625µs，适用于所有测试场景 */
}

/* A2-FIX (2026-09-22): 带 open_pulse_us 参数的 build 接口，ec_app.c 调用此版本。
 * 真实实现在 ec_motion_plan.c:176-332；此处复用旧版 ec_motion_plan_build 的逻辑。 */
bool ec_motion_plan_build_with_open(ec_axis_pick_place_t *out,
                                   int16_t pick_x_mm10, int16_t pick_y_mm10,
                                   int16_t place_x_mm10, int16_t place_y_mm10,
                                   uint16_t open_pulse_us)
{
    (void)open_pulse_us;  /* 测试桩忽略开度参数 */
    return ec_motion_plan_build(out, pick_x_mm10, pick_y_mm10,
                               place_x_mm10, place_y_mm10);
}

/* 2026-10-23：XY 插补版计划（ec_app.c 在 xy_interp_enabled 时调用）。
 * 真实实现见 ec_motion_plan.c 的 ec_motion_plan_build_with_open_interp；
 * 本目标不链接 ec_motion_plan.c ⇒ 这里给桩，转发到同一份 ec_motion_plan_build 逻辑。
 * 默认 xy_interp_enabled == false，正常 test_app 用例走不到这里；
 * 桩存在只是为了让链接通过，并让 INTERP 开关路径也能被覆盖到。 */
bool ec_motion_plan_build_with_open_interp(ec_axis_pick_place_t *out,
                                          int16_t pick_x_mm10, int16_t pick_y_mm10,
                                          int16_t place_x_mm10, int16_t place_y_mm10,
                                          uint16_t open_pulse_us)
{
    (void)open_pulse_us;
    return ec_motion_plan_build(out, pick_x_mm10, pick_y_mm10,
                               place_x_mm10, place_y_mm10);
}

/* A2-FIX (2026-09-22): ec_axis_driver 诊断接口，ec_diag.c 调用。
 * 真实实现在 ec_axis_driver.c:459-462 返回静态 diag；此处返回零初始化的临时结构。 */
static ec_axis_driver_diag_t fake_diag;
const ec_axis_driver_diag_t *ec_axis_driver_diag(void)
{
    return &fake_diag;
}

/* Feed one well-formed ITEM_TASK frame byte-by-byte through the UART router. */
static void feed_item_task(void)
{
    ec_proto_item_task_t item;
    ec_proto_frame_t frame;
    uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];
    uint8_t buf[64];
    size_t len;
    size_t i;

    item.target_seq = 1U;
    item.class_id = 1U;
    item.image_id = 1U;
    item.x_mm10 = 100;
    item.y_mm10 = 100;
    item.grip_angle = EC_PROTO_ITEM_TASK_ANGLE_NONE;
    /* P3: the grasp point is part of the 12-byte payload; leaving these
     * uninitialised would make ec_proto_encode_item_task() fail at random. */
    item.pick_x_mm10 = -200;
    item.pick_y_mm10 = 50;

    TEST_ASSERT(ec_proto_encode_item_task(&item, payload, sizeof(payload)));

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 1U;   /* matches the first round_id */
    frame.frame_seq = 1U;
    frame.command = EC_CMD_ITEM_TASK;
    frame.payload = payload;
    frame.payload_len = EC_PROTO_ITEM_TASK_PAYLOAD_LEN;

    len = ec_proto_encode(&frame, buf, sizeof(buf));
    TEST_ASSERT(len != 0U);
    for (i = 0U; i < len; ++i) {
        ec_app_on_uart_rx_byte(buf[i]);
    }
}

/* P0-FIX boot chain (2026-08-28)：POST / HOMING / BARRIER 不再自动放行，
 * 由 ec_startup_sequence.c 做真检查。
 *
 * 本用例走的就是那条真链（2026-09-16 挡板取消后的形态）：
 *   START -> POWER_ON/POST（50 ms 稳定窗口；限位检查已于 2026-09-15 移除）
 *   -> HOMING（方案 A：上电位置即原点，等满 500 ms 稳定窗口即通过，不开关量）
 *   -> PREPARE_BARRIER -> BARRIER_READY -> WAIT_TASK。
 *
 * 挡板取消后 ec_startup_sequence_poll_barrier() 直接放行，所以 PREPARE_BARRIER
 * 只存在一瞬：同一次 ec_app_poll() 里就走到 WAIT_TASK，并发出本启动链唯一的
 * 一帧 BARRIER_READY。本用例把这两点钉死。
 *
 * 已作废的历史期望（别再改回去）：挡板未取消时要等 5 s 反馈超时 ->
 * EMERGENCY_STOP -> FAULT_LOCK，主机上永远到不了 WAIT_TASK；那时 app 层的
 * ITEM_TASK 正向路径只能靠网关层用例（电控/stm32_logic/tests/
 * test_protocol_gateway.c）覆盖。挡板取消后 app 层能真走到 WAIT_TASK，
 * ACK(ACCEPTED) 的回归用例就落在这里（见本文件 test_ack_accepted_reaches_uart）。 */
static void test_startup_sequence(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    tx_records_reset();
    fake_active_inputs = 0U;
    ec_app_init();
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);

    /* FAULT_LOCK + START -> POWER_ON (POST begins). */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    /* POST：限位检查已于 2026-09-15 移除，50 ms 稳定窗口后即通过。 */
    ec_app_poll(100U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);

    /* HOMING（方案 A：上电位置即原点）：不再要求 X_HOME/Y_HOME，
     * 等满 500 ms 稳定窗口即通过，与输入状态无关。 */
    fake_active_inputs = 0U;
    ec_app_poll(499U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);

    /* 挡板取消 -> 同一次 poll 里 PREPARE_BARRIER 直接放行到 WAIT_TASK。 */
    ec_app_poll(500U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_TASK);
    TEST_ASSERT(uart_tx_calls == 1U);   /* 恰好一帧：BARRIER_READY */
    TEST_ASSERT(tx_count(EC_CMD_BARRIER_READY, TX_ANY, TX_ANY) == 1U);

    /* 站在 WAIT_TASK 继续空转：不得再有帧出去（例如把 BARRIER_READY 重发）。 */
    ec_app_poll(1000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_TASK);
    TEST_ASSERT(uart_tx_calls == 1U);
}

/* P0-FIX property: an ITEM_TASK arriving before the machine is verified ready
 * (WAIT_TASK) must NOT start motion. Outside WAIT_TASK the gateway answers with
 * a NACK (or a cached-response replay) instead of arming the motion planner;
 * in FAULT_LOCK it now establishes the round instead.
 *
 * 已作废的历史期望（别再改回去）：2026-09-18 之前这里断言「FAULT_LOCK 下丢弃该帧、
 * 状态保持 FAULT_LOCK」。该行为已被用户明确要求推翻 —— 本机不接任何物理按键
 * （不要 PA4），轮次只能靠树莓派发来的 ITEM_TASK 建立，见 ec_state_machine.c:76-86。
 * 旧行为正是 NACK_WRONG_ROUND 与「轮次永远建不起来」的成因。
 * 本用例钉死不动的，是 P0 安全性质本身：**绝不启动运动**。 */
static void test_item_task_rejected_before_ready(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    fake_active_inputs = 0U;
    ec_app_init();

    /* FAULT_LOCK + 安全条件成立 + 新 task_id -> 学习轮次并进入 POST。
     * 不发任何帧（BEGIN_POST 既不是 EMIT_* 也不是 ACK/NACK），更不启动运动。 */
    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    TEST_ASSERT(uart_tx_calls == 0U);
    TEST_ASSERT(fake_plan_calls == 0U);
    TEST_ASSERT(fake_axis_state != EC_AXIS_STATE_MOVING);

    /* In POWER_ON (POST running) the gateway rejects with a NACK: the app must
     * stay in POST and must not arm motion or reach the motion planner. */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    TEST_ASSERT(uart_tx_calls >= 1U);   /* NACK(REJECT_NEW_TASK) emitted */
    TEST_ASSERT(fake_plan_calls == 0U);
    TEST_ASSERT(fake_axis_state != EC_AXIS_STATE_MOVING);
}

/* --- rolling no-motion watchdog tests (design 2026-08-30 §3.4) ---
 *
 * These drive the REAL app chain (START -> POST -> HOMING -> barrier seam ->
 * WAIT_TASK -> ITEM_TASK -> EXECUTING) and control time through the
 * injectable HAL tick (test_set_tick) plus the now_ms passed to ec_app_poll.
 * The motion-start base is HAL_GetTick() read at START_MOTION, so every
 * watchdog test sets the tick before feed_item_task() and passes matching
 * now_ms values to the polls.
 */

/* Feed one DISPLAY_ACK frame (EC_CMD_DISPLAY_ACK, from PI) with the given
 * render result and display-content CRC. The frame-level CRC is always valid;
 * a caller who wants an invalid ACK corrupts render_result or display_crc32. */
static void feed_display_ack(uint32_t display_crc32, uint8_t render_result)
{
    ec_proto_display_ack_t ack;
    ec_proto_frame_t frame;
    uint8_t payload[EC_DISPLAY_ACK_PAYLOAD_LEN];
    uint8_t buf[64];
    size_t len;
    size_t i;

    ack.target_seq = 1U;               /* the item accepted in feed_item_task */
    ack.render_result = render_result;
    ack.display_crc32 = display_crc32;

    (void)ec_proto_encode_display_ack(&ack, payload, sizeof(payload));

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 1U;                /* matches the current round */
    frame.frame_seq = 2U;
    frame.command = EC_CMD_DISPLAY_ACK;
    frame.payload = payload;
    frame.payload_len = EC_DISPLAY_ACK_PAYLOAD_LEN;

    len = ec_proto_encode(&frame, buf, sizeof(buf));
    TEST_ASSERT(len != 0U);
    for (i = 0U; i < len; ++i) {
        ec_app_on_uart_rx_byte(buf[i]);
    }
}

/* Valid display-content CRC for the item latched by feed_item_task after a
 * SUCCESS result was recorded (target_seq=1, class_id=1, image_id=1,
 * success_count=1, result=SUCCESS). */
static uint32_t valid_display_ack_crc(void)
{
    return ec_proto_display_content_crc32(1U, 1U, 1U, 1U, EC_RESULT_SUCCESS);
}

/* Boot the REAL chain to WAIT_TASK (same step-by-step shape as
 * test_startup_sequence) and stop there, with the boot's own BARRIER_READY
 * already on the wire. The tick is reset first because the boot timers are
 * measured from the HAL_GetTick() read at each begin_* - a previous test's
 * tick must not leak in.
 *
 * 2026-09-16：挡板取消后主机侧能真走到 WAIT_TASK，原来那条
 * ec_app_test_force_barrier_verified() 测试缝已无必要（且是空操作），故删去。 */
static void boot_to_wait_task(void)
{
    fake_active_inputs = 0U;
    ec_app_init();
    test_set_tick(0U);

    /* FAULT_LOCK + START -> POWER_ON (POST begins). */
    fake_active_inputs = EC_INPUT_START;
    ec_app_poll(1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_POWER_ON);
    fake_active_inputs = 0U;

    /* POST 通过（限位检查已移除，50 ms 稳定窗口）。 */
    ec_app_poll(100U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);

    /* HOMING 通过（方案 A：上电位置即原点，500 ms 稳定窗口，不依赖开关量）；
     * 挡板取消后同一次 poll 里一路走到 WAIT_TASK。 */
    fake_active_inputs = 0U;
    ec_app_poll(499U);
    TEST_ASSERT(ec_app_state() == EC_STATE_HOMING);
    ec_app_poll(500U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_TASK);
    fake_active_inputs = 0U;
}

/* Deliver the first ITEM_TASK from WAIT_TASK. Returns with the machine in
 * EXECUTING and the rolling watchdog armed at motion_start_tick (HAL_GetTick
 * read at START_MOTION). */
static void start_motion_at(uint32_t motion_start_tick)
{
    boot_to_wait_task();

    test_set_tick(motion_start_tick);
    feed_item_task();
    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == motion_start_tick);
}

/* Shared by the compile-time-disabled test executable. Keeping the motion
 * setup in this file means both macro configurations exercise the same app
 * path and axis/board doubles. */
void test_app_start_motion_at(uint32_t motion_start_tick)
{
    start_motion_at(motion_start_tick);
}

/* ==================== ACK(ACCEPTED) 上线回归（2026-09-16）====================
 * 缺陷：ec_gateway_feed_byte() 与 ec_gateway_inject() 都在入口把 g->tx_len 清 0。
 * 喂一帧合法 ITEM_TASK 时 feed_byte 先把 ACK(ACCEPTED) 排进 tx_buf 并返回
 * state == VALIDATE_TASK；紧接着 ec_app_handle_transition() 的 VALIDATE_TASK 块
 * 为了推进状态机又注入 TASK_SAFETY_VALIDATED —— 那是第二次 ec_gateway_inject()，
 * 入口清空把刚排好的 ACK 直接丢掉，末尾那次 ec_app_flush_tx() 于是无帧可发。
 * 症状：喂一帧合法 ITEM_TASK，UART 上只有启动期的 BARRIER_READY，一个 ACK 都没有，
 * Pi 侧只能等超时。
 * 修复：ec_app.c 的 VALIDATE_TASK 块内、把控制权交回 gateway 之前先调用
 * ec_app_flush_tx()（ec_app.c:268）。
 * 下面三个用例修复前必红、修复后必绿。 */

/* 把"无关字节"送进网关：0xA5 打开组帧，随后的 0x00/0xFF 过不了第二字节校验，
 * 被 ec_gateway_feed_byte() 丢掉。两个字节都真的会进网关 —— 这正是要点：入口的
 * tx_len 清空是"上一帧已经发完"的唯一标记。
 * 注意 0x00/0xFF 必须带 0xA5 前缀：单个非 0xA5 字节会被 ec_app_on_uart_rx_byte()
 * 路由到 ASCII 诊断解析器，根本碰不到网关，那样的断言等于空转。 */
static void feed_noise_through_gateway(void)
{
    static const uint8_t noise[] = {
        UINT8_C(0x00), UINT8_C(0xFF), UINT8_C(0x00), UINT8_C(0xFF),
        UINT8_C(0x00), UINT8_C(0xFF), UINT8_C(0x00), UINT8_C(0xFF),
    };
    size_t i;

    for (i = 0U; i < sizeof(noise); ++i) {
        ec_app_on_uart_rx_byte(EC_PROTO_HEADER_0);
        ec_app_on_uart_rx_byte(noise[i]);
    }
}

/* 用例 1：走到 WAIT_TASK，喂一帧合法 ITEM_TASK，UART 上必须真的出现
 * ACK(command 0x05) + reason=ACCEPTED(0x00) + target_seq=1。 */
static void test_ack_accepted_reaches_uart(void)
{
    boot_to_wait_task();
    tx_records_reset();

    feed_item_task();

    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);
    TEST_ASSERT(tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U);
    TEST_ASSERT(tx_find(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) != NULL);
}

/* 用例 2（反例）：ACK 恰好出现一次。
 * 喂完 ITEM_TASK（应发 1 次 ACK）再灌一批无关字节：只要入口清空还在，tx_buf 里
 * 的陈旧帧就不可能在后续字节上被重新 flush。反过来，谁把入口清空删掉，app 循环
 * 尾部那次 ec_app_flush_tx() 就会每字节重发一次那个 ACK（重发风暴），本断言立刻
 * 变红。 */
static void test_ack_not_resent_on_gateway_noise(void)
{
    boot_to_wait_task();
    tx_records_reset();

    feed_item_task();
    TEST_ASSERT(tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U);

    feed_noise_through_gateway();

    TEST_ASSERT(tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U);
    TEST_ASSERT(tx_count(EC_CMD_ACK, TX_ANY, TX_ANY) == 1U);
    TEST_ASSERT(tx_record_count == 1U);   /* 一个字节都没多打 */
}

/* 用例 3：同一身份的重复帧 -> 重放缓存里的 ACK，且 tx_seq 不递增（E-5）。
 * 状态机在 state != WAIT_TASK 且 identity 与当前 item 相同时走
 * EC_ACTION_RESEND_CACHED_RESPONSE：把缓存的原始字节原样重发（不占新 tx_seq），
 * 而不是重新生成一帧。 */
static void test_duplicate_item_task_replays_ack_without_new_seq(void)
{
    const tx_frame_record_t *first;
    uint16_t first_seq;
    unsigned next;

    boot_to_wait_task();
    tx_records_reset();

    feed_item_task();
    first = tx_find(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U);
    TEST_ASSERT(first != NULL);
    first_seq = first->frame_seq;

    /* 完全相同的一帧（task_id / frame_seq / payload 全同 -> 同一个 dedup 身份）。 */
    next = tx_record_count;
    feed_item_task();

    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);   /* 不重入执行 */
    TEST_ASSERT(tx_record_count == next + 1U);
    TEST_ASSERT(tx_records[next].decoded);
    TEST_ASSERT(tx_records[next].command == EC_CMD_ACK);
    TEST_ASSERT(tx_records[next].reason == EC_ACK_REASON_ACCEPTED);
    TEST_ASSERT(tx_records[next].target_seq == 1U);
    TEST_ASSERT(tx_records[next].frame_seq == first_seq);   /* tx_seq 未递增 */

    /* 这里恰好是"入口清空"最灵敏的位置：刚重放的缓存帧还留在 tx_buf（tx_len
     * 非 0，且其后没有 inject 再清）。谁删掉入口清空，下面的无关字节就会把这一帧
     * 一次次重发出来。 */
    feed_noise_through_gateway();
    TEST_ASSERT(tx_record_count == next + 1U);
}

/* A heartbeat is intentionally ignored by the gateway. It must not move the
 * rolling base while an item is executing. */
static void feed_heartbeat(void)
{
    ec_proto_frame_t frame;
    uint8_t buf[EC_PROTO_FRAME_OVERHEAD];
    size_t len;
    size_t i;

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = 1U;
    frame.frame_seq = 99U;
    frame.command = EC_CMD_HEARTBEAT;
    frame.payload = NULL;
    frame.payload_len = 0U;
    len = ec_proto_encode(&frame, buf, sizeof(buf));
    TEST_ASSERT(len == EC_PROTO_FRAME_OVERHEAD);
    for (i = 0U; i < len; ++i) {
        ec_app_on_uart_rx_byte(buf[i]);
    }
}

/* 🔴 2026-09-22 失活窗语义变更 —— 读这段，否则会误以为下面 9 条断言被"消音"了。
 *
 *   `ec_app.c:717-721` 已改为：轴处于 MOVING/GRIPPING 时**不计时、不判** 15s 失活窗。
 *   依据赛规 R-R04（要求汇总.md:102：「超过 15 秒装置【没有动作】…本轮比赛结束」）：
 *   装置**正在动**时"没有动作"不成立 ⇒ 运动期间本就不该判；现场证据见 ec_app.c:701-716。
 *
 *   ⇒ 本文件下面这批「失活窗记账」用例原先靠 `start_motion_at()`（:139）把轴留在
 *     MOVING，在新判据下**永远等不到 FAULT_LOCK**（旧版运动期间也判，所以当时是对的）。
 *   ⇒ 它们的真实语义是「**机器停下来之后**静默 15s ⇒ 本轮收场」（与显示阶段同一口径），
 *     故在期待收场前显式把轴置为已停，把这条**前置条件**写明 —— 这是语义变更留痕，
 *     不是把断言改松：一旦有人把运动期间重新改成"会判"，本 helper 之外的那些用例不受影响，
 *     而"运动 15s 不判"另有 test_deadline_moving_axis_is_never_judged() 专门钉住。
 *
 * ⚠️ B1 已知缺口（**不是**被这段改动掩盖的）：堵转/联轴器脱落时脉冲照发、软件步数
 *   计数器照样减到 0 ⇒ 轴一直停在 MOVING ⇒ 本判据**检不出堵转**。该缺口已在
 *   docs/交付/2026-09-22/派工-剩余任务-20260922-晨.md 的 B1 立项；正解是
 *   "窗口在轴开始动时打开、只认计数移动完成续命"，改完这条缺口应被覆盖。
 *   **本 helper 不改变该缺口**，只是把"这些用例考的是停机后的窗口"写清楚。 */
static void stop_axis_before_deadline_lock(void)
{
    fake_axis_state = EC_AXIS_STATE_DONE;
}

/* 2026-09-22 新增：把"运动期间不判失活窗"这条**新行为本身**钉住。
 * 这是 B1 缺口那一侧的可执行记录：机器一直 MOVING + 静默远超 15s ⇒ 状态**不许**变成
 * FAULT_LOCK（否则就退回"运动期间误判"的旧 bug，那正是今晚 6 件全过之前死机的成因）。
 * 缺口（堵转检不出）见上面 helper 的 B1 段。 */
static void test_deadline_moving_axis_is_never_judged(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);
    /* 前置条件显式声明，不依赖 fake 的副作用：轴此刻在 MOVING。 */
    fake_axis_state = EC_AXIS_STATE_MOVING;

    /* 静默远超 15s，但轴仍在 MOVING ⇒ 不得判。 */
    ec_app_poll(1000U + 15000U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(1000U + 60000U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);

    /* 轴一停，窗口立刻恢复判据（同一次 poll 内）。 */
    stop_axis_before_deadline_lock();
    ec_app_poll(1000U + 60000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* The executor reports a newly completed actuator step by increasing its
 * progress count. The app must feed that count into the watchdog exactly once
 * for the observed increase, without waiting for MOTION_DONE. */
static void test_deadline_completed_axis_step_extends(void)
{
    start_motion_at(1000U);
    test_set_tick(6000U);
    ec_app_progress_source_set_enabled(true);

    fake_axis_progress_advance = true; /* one completed single-axis move */
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_EXECUTING);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 6000U);

    /* A later step completion is another strictly newer token. */
    test_set_tick(12000U);
    fake_axis_progress_advance = true;
    ec_app_poll(12000U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 12000U);

    ec_app_poll(26999U); /* 14,999 ms after the second completion */
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(27000U); /* exactly 15 s of silence */
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 1: a new valid observable-progress token re-bases the window.
 * Motion starts at t=0 (base 1000); a token at t=10 s moves the base to
 * 11000; t=24.9 s is still inside (10+15 > 24.9); t=25 s locks (15 s since
 * the last progress). */
static void test_deadline_token_extends(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true); /* bench-validated source on */

    test_set_tick(11000U);
    ec_app_note_observable_progress(1U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    ec_app_poll(25900U); /* t = 24.9 s after motion start */
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(26000U); /* t = 25.0 s after motion start */
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 2: the same token delivered twice never re-extends. The second
 * delivery at t=20 s must be dropped (dedup), so the base stays at 11000 and
 * the window locks at t=25 s (not t=35 s). */
static void test_deadline_duplicate_token(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(11000U);
    ec_app_note_observable_progress(7U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    /* Same token re-delivered at t=20 s: must NOT refresh the base. */
    test_set_tick(21000U);
    ec_app_note_observable_progress(7U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    ec_app_poll(25900U); /* t = 24.9 s after motion start */
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(26000U); /* t = 25.0 s after motion start */
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* A numerically older token is stale even when it arrives much later. */
static void test_deadline_older_token(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(11000U);
    ec_app_note_observable_progress(10U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    test_set_tick(21000U);
    ec_app_note_observable_progress(9U); /* stale: must not re-base */
    TEST_ASSERT(ec_app_test_last_observable_ms() == 11000U);

    ec_app_poll(25999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(26000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* A token received before a motion window is open must not arm the watchdog.
 * This is a separate gate from the compile-time and runtime source switches. */
static void test_deadline_token_cannot_open_window(void)
{
    ec_app_init();
    ec_app_progress_source_set_enabled(true);
    test_set_tick(5000U);

    ec_app_note_observable_progress(1U);

    TEST_ASSERT(!ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 0U);
}

/* Test 3: exactly 15000 ms since the last observable progress locks. */
static void test_deadline_exact_15s(void)
{
    start_motion_at(1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 4: a valid token at 14.9 s restarts the full 15 s countdown. */
static void test_deadline_149s_token(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(15900U);
    ec_app_note_observable_progress(2U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 15900U);

    ec_app_poll(30899U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(30900U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* HEARTBEAT and a retransmitted ITEM_TASK are communication events only; they
 * cannot refresh the actuator-progress base. */
static void test_deadline_heartbeat_and_retransmit_no_extend(void)
{
    start_motion_at(1000U);
    ec_app_progress_source_set_enabled(true);

    test_set_tick(11000U);
    feed_heartbeat();
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    /* The exact item identity is a retransmission and therefore only replays
     * the cached response; it is not a new actuator event. */
    feed_item_task();
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 5: MOTION_DONE neither clears nor restarts the window - the display
 * phase keeps the remaining budget of the same rolling window (base 1000),
 * so it locks at t=16 s, not 16+15 s. */
static void test_deadline_motion_done_no_restart(void)
{
    start_motion_at(1000U);

    /* Motion completes at t=6 s: MOTION_DONE -> WAIT_ITEM_RESULT -> (item
     * result recorded) -> WAIT_DISPLAY_ACK. */
    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 6a: an invalid DISPLAY_ACK (render_result != RENDERED) emits a NACK
 * and never refreshes the base: the window still locks at t=16 s. */
static void test_deadline_invalid_ack_no_extend(void)
{
    unsigned tx_before;

    start_motion_at(1000U);

    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);

    tx_before = uart_tx_calls;
    feed_display_ack(0U, 0x01U); /* not RENDERED -> validation fails */
    TEST_ASSERT(uart_tx_calls > tx_before);   /* NACK emitted */
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);
    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 6b: the first valid DISPLAY_ACK closes the case (watchdog off); the
 * same ACK re-delivered only RESENDs - it never re-arms or re-extends. */
static void test_deadline_duplicate_ack_no_reatm(void)
{
    uint32_t valid_crc;

    start_motion_at(1000U);

    fake_axis_state = EC_AXIS_STATE_DONE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    ec_app_poll(6000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_WAIT_DISPLAY_ACK);

    valid_crc = valid_display_ack_crc();
    feed_display_ack(valid_crc, EC_DISPLAY_ACK_RENDERED);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    TEST_ASSERT(!ec_app_test_watchdog_active());

    /* Same ACK again: cached resend only, no re-arm, no re-entry. */
    feed_display_ack(valid_crc, EC_DISPLAY_ACK_RENDERED);
    TEST_ASSERT(ec_app_state() == EC_STATE_PREPARE_BARRIER);
    TEST_ASSERT(!ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);
}

/* Test 7: uint32 tick wraparound. Base near UINT32_MAX (0xFFFFFF00); after
 * the tick wraps, (now - base) must still be computed wrap-safe:
 * 0x00000010 - 0xFFFFFF00 = 0x110 = 272 ms (< 15000, no lock);
 * 0x00003997 -> 14999 ms (no lock); 0x00003998 -> 15000 ms (lock). */
static void test_deadline_tick_wraparound(void)
{
    start_motion_at(0xFFFFFF00U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 0xFFFFFF00U);

    ec_app_poll(0x00000010U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);

    ec_app_poll(0x00003997U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);

    stop_axis_before_deadline_lock();
    ec_app_poll(0x00003998U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

/* Test 9: runtime fail-closed - an enabled build can explicitly turn its
 * adapter off; a token is then a no-op. The independent macro=0 target proves
 * the compile-time lock.
 * ⚠️ 2026-09-22：原文"motion outrunning the 15 s window still locks"已**不成立** ——
 *    运动期间现在不判（见 stop_axis_before_deadline_lock 的说明）⇒ 本用例现为
 *    "轴停下后，进度源关掉的窗口照样按 15s 收场"。 */
static void test_deadline_fail_closed(void)
{
    start_motion_at(1000U);

    /* In an enabled build this is the runtime kill-switch case. The separate
     * macro=0 target below proves that no runtime setter can open a compiled-
     * out token path. */
    ec_app_progress_source_set_enabled(false);

    test_set_tick(11000U);
    ec_app_note_observable_progress(1U);
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U); /* no-op */

    ec_app_poll(15999U);
    TEST_ASSERT(ec_app_state() != EC_STATE_FAULT_LOCK);
    stop_axis_before_deadline_lock();
    ec_app_poll(16000U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);
}

void test_app(void)
{
    safe_state_calls = input_poll_calls = uart_start_calls = uart_tx_calls = 0U;
    fake_axis_state = EC_AXIS_STATE_IDLE;
    fake_axis_result = EC_AXIS_RESULT_OK;
    fake_axis_progress = 0U;
    fake_axis_progress_advance = false;
    fake_plan_x = 0;
    fake_plan_y = 0;
    fake_plan_calls = 0U;
    fake_active_inputs = 0U;

    ec_app_init();
    TEST_ASSERT(safe_state_calls == 1U);
    TEST_ASSERT(uart_start_calls == 1U);
    TEST_ASSERT(input_poll_calls == 1U);
    TEST_ASSERT(ec_app_state() == EC_STATE_FAULT_LOCK);

    ec_app_poll(9U);
    TEST_ASSERT(input_poll_calls == 1U);
    ec_app_poll(10U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(19U);
    TEST_ASSERT(input_poll_calls == 2U);
    ec_app_poll(20U);
    TEST_ASSERT(input_poll_calls == 3U);

    test_startup_sequence();
    test_item_task_rejected_before_ready();

    /* ACK(ACCEPTED) 回归（缺陷：VALIDATE_TASK 块内的二次 inject 丢帧）。 */
    test_ack_accepted_reaches_uart();
    test_ack_not_resent_on_gateway_noise();
    test_duplicate_item_task_replays_ack_without_new_seq();

    /* Rolling no-motion watchdog (design §3.4, 8 cases). */
    test_deadline_completed_axis_step_extends();
    test_deadline_moving_axis_is_never_judged();
    test_deadline_token_extends();
    test_deadline_duplicate_token();
    test_deadline_older_token();
    test_deadline_token_cannot_open_window();
    test_deadline_exact_15s();
    test_deadline_149s_token();
    test_deadline_heartbeat_and_retransmit_no_extend();
    test_deadline_motion_done_no_restart();
    test_deadline_invalid_ack_no_extend();
    test_deadline_duplicate_ack_no_reatm();
    test_deadline_tick_wraparound();
    test_deadline_fail_closed();
}
