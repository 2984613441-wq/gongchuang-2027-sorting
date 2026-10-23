#include "ec_diag.h"
#include "ec_app.h"
#include "ec_axis_driver.h"
#include "ec_board.h"
#include "ec_barrier_test.h"
#include "ec_drop_servo.h"
#include "ec_group_test.h"
#include "ec_light_ws2812.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"
#include "ec_tof.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* TOF 命令需要 HAL_GetTick()（算 age_ms）。
 * 真机构建解析到真实 HAL；主机测试解析到 tests/host_stubs/stm32f4xx_hal.h
 * （它只声明 HAL_GetTick，由 host_stubs/hal_stub.c 实现）。 */
#include "stm32f4xx_hal.h"

#ifndef EC_DIAGNOSTIC_BUILD
#define EC_DIAGNOSTIC_BUILD 0
#endif

#ifndef EC_MOTION_TEST_BUILD
#define EC_MOTION_TEST_BUILD 0
#endif

#ifndef EC_SERVO_TEST_BUILD
#define EC_SERVO_TEST_BUILD 0
#endif

#ifndef EC_GROUP_TEST_BUILD
#define EC_GROUP_TEST_BUILD 0
#endif

#ifndef EC_BARRIER_TEST_BUILD
#define EC_BARRIER_TEST_BUILD 0
#endif

#define EC_DIAG_LINE_CAPACITY 64U
#define EC_DIAG_RX_CAPACITY 128U

#if EC_DIAGNOSTIC_BUILD
static char rx_line[EC_DIAG_LINE_CAPACITY];
static size_t rx_used;
static uint8_t line_overflow;
static volatile uint8_t rx_bytes[EC_DIAG_RX_CAPACITY];
static volatile uint16_t rx_head;
static volatile uint16_t rx_tail;
static volatile uint8_t rx_queue_overflow;
static uint32_t last_status_ms;

#if EC_SERVO_TEST_BUILD
typedef struct {
    const char *command;
    uint16_t pulse_us;
} ec_servo_command_t;

static bool servo_pulse_from_command(const char *line, uint16_t *pulse_us)
{
    static const ec_servo_command_t commands[] = {
        /* 2026-09-19 新增 P900/P950：探 P1000 之上的"完全张开"端点。
         * ⚠️ 必须与 ec_servo_test.c 的 is_allowed_pulse() 同步，否则命令能解析却被拒。 */
        /* 2026-09-21 新增 P750/P800/P850/P870：用户要求把张开脉宽压到 750。
         * 750 是未验证值，故同时开放 800/850/870 做"命中即回退"的扫描档。 */
        /* 2026-09-21 三改：用户现场目视 P750 仍"不够开"，追加 650/675/700/725 四档。
         * ⚠️ 必须与 ec_servo_test.c 的 is_allowed_pulse() 同步（见上）。 */
        /* 2026-09-21 四改：用户继续要求更低（625）⇒ 追加 550/575/600/625 四档。
         * ⚠️ 必须与 ec_servo_test.c 的 is_allowed_pulse() 同步。 */
        { "SERVO PB10 P550",  UINT16_C(550) },
        { "SERVO PB10 P575",  UINT16_C(575) },
        { "SERVO PB10 P600",  UINT16_C(600) },
        { "SERVO PB10 P625",  UINT16_C(625) },
        { "SERVO PB10 P650",  UINT16_C(650) },
        { "SERVO PB10 P675",  UINT16_C(675) },
        { "SERVO PB10 P700",  UINT16_C(700) },
        { "SERVO PB10 P725",  UINT16_C(725) },
        { "SERVO PB10 P750",  UINT16_C(750) },
        { "SERVO PB10 P800",  UINT16_C(800) },
        { "SERVO PB10 P850",  UINT16_C(850) },
        { "SERVO PB10 P870",  UINT16_C(870) },
        { "SERVO PB10 P900",  UINT16_C(900) },
        { "SERVO PB10 P950",  UINT16_C(950) },
        { "SERVO PB10 P1000", UINT16_C(1000) },
        { "SERVO PB10 P1100", UINT16_C(1100) },
        { "SERVO PB10 P1200", UINT16_C(1200) },
        { "SERVO PB10 P1300", UINT16_C(1300) },
        { "SERVO PB10 P1500", UINT16_C(1500) },
        { "SERVO PB10 P1700", UINT16_C(1700) },
        { "SERVO PB10 P1900", UINT16_C(1900) }
    };
    size_t i;

    for (i = 0U; i < (sizeof(commands) / sizeof(commands[0])); ++i) {
        if (strcmp(line, commands[i].command) == 0) {
            *pulse_us = commands[i].pulse_us;
            return true;
        }
    }
    return false;
}
#endif

#if EC_GROUP_TEST_BUILD
typedef struct {
    const char *command;
    ec_direction_t x_direction;
    ec_direction_t y_direction;
    uint16_t servo_pulse_us;
} ec_group_command_t;

static bool group_values_from_command(const char *line,
                                      ec_direction_t *x_direction,
                                      ec_direction_t *y_direction,
                                      uint16_t *servo_pulse_us)
{
    static const ec_group_command_t commands[] = {
        { "GROUP START XDIR0 YDIR0 OPEN", EC_DIRECTION_0, EC_DIRECTION_0, UINT16_C(1100) },
        { "GROUP START XDIR0 YDIR0 CLOSE", EC_DIRECTION_0, EC_DIRECTION_0, UINT16_C(1900) },
        { "GROUP START XDIR0 YDIR1 OPEN", EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1100) },
        { "GROUP START XDIR0 YDIR1 CLOSE", EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1900) },
        { "GROUP START XDIR1 YDIR0 OPEN", EC_DIRECTION_1, EC_DIRECTION_0, UINT16_C(1100) },
        { "GROUP START XDIR1 YDIR0 CLOSE", EC_DIRECTION_1, EC_DIRECTION_0, UINT16_C(1900) },
        { "GROUP START XDIR1 YDIR1 OPEN", EC_DIRECTION_1, EC_DIRECTION_1, UINT16_C(1100) },
        { "GROUP START XDIR1 YDIR1 CLOSE", EC_DIRECTION_1, EC_DIRECTION_1, UINT16_C(1900) }
    };
    size_t i;

    for (i = 0U; i < (sizeof(commands) / sizeof(commands[0])); ++i) {
        if (strcmp(line, commands[i].command) == 0) {
            *x_direction = commands[i].x_direction;
            *y_direction = commands[i].y_direction;
            *servo_pulse_us = commands[i].servo_pulse_us;
            return true;
        }
    }
    return false;
}
#endif

#if EC_BARRIER_TEST_BUILD
static bool parse_barrier_pulse(const char *text, uint16_t *pulse_us)
{
    unsigned long value = 0UL;
    size_t i;

    if ((text == NULL) || (text[0] != 'P') || (text[1] == '\0')) {
        return false;
    }
    for (i = 1U; text[i] != '\0'; ++i) {
        unsigned char c = (unsigned char)text[i];
        if ((c < (unsigned char)'0') || (c > (unsigned char)'9')) {
            return false;
        }
        value = (value * 10UL) + (unsigned long)(c - (unsigned char)'0');
        if (value > EC_BARRIER_PULSE_MAX_US) return false;
    }
    if (value < EC_BARRIER_PULSE_MIN_US) return false;
    *pulse_us = (uint16_t)value;
    return true;
}

static bool parse_barrier_channel_command(const char *line, uint8_t *mask,
                                          uint16_t *pulse_us)
{
    static const char *const prefixes[4] = {
        "BARRIER 1 P", "BARRIER 2 P", "BARRIER 3 P", "BARRIER 4 P"
    };
    size_t i;

    for (i = 0U; i < 4U; ++i) {
        if (strncmp(line, prefixes[i], 11U) == 0) {
            if (!parse_barrier_pulse(line + 10U, pulse_us)) return false;
            *mask = (uint8_t)(UINT8_C(1) << i);
            return true;
        }
    }
    return false;
}
#endif

static bool parse_move_steps_command(const char *line, ec_axis_t *axis,
                                     ec_direction_t *direction,
                                     uint32_t *steps, uint32_t *hz)
{
    const char *p = line;
    char *end = NULL;
    char axis_char;
    unsigned long dir_value;
    unsigned long steps_value;
    unsigned long hz_value;

    if (strncmp(p, "MOVE ", 5U) != 0) return false;
    p += 5U;
    axis_char = *p;
    p++;
    if (*p != ' ') return false;
    p++;
    if (strncmp(p, "DIR", 3U) != 0) return false;
    p += 3U;
    dir_value = strtoul(p, &end, 10);
    if ((end == p) || (*end != ' ')) return false;
    p = end + 1U;
    if (strncmp(p, "STEPS ", 6U) != 0) return false;
    p += 6U;
    steps_value = strtoul(p, &end, 10);
    if ((end == p) || (*end != ' ')) return false;
    p = end + 1U;
    if (strncmp(p, "HZ ", 3U) != 0) return false;
    p += 3U;
    hz_value = strtoul(p, &end, 10);
    if ((end == p) || (*end != '\0')) return false;

    if (axis_char == 'X') {
        *axis = EC_AXIS_X;
    } else if (axis_char == 'Y') {
        *axis = EC_AXIS_Y;
    } else {
        return false;
    }
    if ((dir_value != 0UL) && (dir_value != 1UL)) return false;
    if ((steps_value == 0UL) ||
        (steps_value > (unsigned long)EC_STEP_MAX_STEPS)) {
        return false;
    }
    if ((hz_value < (unsigned long)EC_STEP_MIN_HZ) ||
        (hz_value > (unsigned long)EC_STEP_MAX_HZ)) {
        return false;
    }
    *direction = (dir_value == 0UL) ? EC_DIRECTION_0 : EC_DIRECTION_1;
    *steps = (uint32_t)steps_value;
    *hz = (uint32_t)hz_value;
    return true;
}

static bool step_test_busy(void)
{
    return (ec_step_test_mode() != EC_STEP_TEST_IDLE) ||
           ec_motion_test_is_armed();
}

#if EC_GROUP_TEST_BUILD
static bool servo_test_busy(void)
{
    return ec_servo_test_mode() != EC_SERVO_TEST_IDLE;
}
#endif

static bool barrier_test_busy(void)
{
#if EC_BARRIER_TEST_BUILD
    return ec_barrier_test_blocks_other();
#else
    return false;
#endif
}

#if EC_BARRIER_TEST_BUILD
static bool servo_active_now(void)
{
    return ec_servo_test_mode() != EC_SERVO_TEST_IDLE;
}
#endif

static bool group_test_busy(void)
{
#if EC_GROUP_TEST_BUILD
    return ec_group_test_blocks_single();
#else
    return false;
#endif
}

static void stop_all_tests(void)
{
    ec_step_test_stop();
    ec_servo_test_stop();
#if EC_GROUP_TEST_BUILD
    ec_group_test_stop();
#endif
#if EC_BARRIER_TEST_BUILD
    ec_barrier_test_stop();
#endif
}

static void write_inputs(void)
{
    char output[96];
    ec_input_snapshot_t input = ec_board_read_inputs();
    (void)snprintf(output, sizeof(output),
                   "INPUTS RAW=%04X STABLE=%04X ACTIVE=%04X\r\n",
                   (unsigned)input.raw_mask, (unsigned)input.stable_mask,
                   (unsigned)input.active_mask);
    ec_diag_port_write(output);
}

/* Keep the STATUS value readable while retaining the enum mapping in one place. */
static const char *ec_app_state_name(ec_state_t state)
{
    switch (state) {
    case EC_STATE_FAULT_LOCK: return "FAULT_LOCK";
    case EC_STATE_POWER_ON: return "POWER_ON";
    case EC_STATE_POST: return "POST";
    case EC_STATE_HOMING: return "HOMING";
    case EC_STATE_READY: return "READY";
    case EC_STATE_PREPARE_BARRIER: return "PREPARE_BARRIER";
    case EC_STATE_WAIT_TASK: return "WAIT_TASK";
    case EC_STATE_VALIDATE_TASK: return "VALIDATE_TASK";
    case EC_STATE_EXECUTING: return "EXECUTING";
    case EC_STATE_WAIT_ITEM_RESULT: return "WAIT_ITEM_RESULT";
    case EC_STATE_WAIT_DISPLAY_ACK: return "WAIT_DISPLAY_ACK";
    case EC_STATE_COMPLETE: return "COMPLETE";
    default: return "UNKNOWN";
    }
}

static void consume_rx_byte(uint8_t byte)
{
    if ((byte == '\r') || (byte == '\n')) {
        if ((rx_used != 0U) || (line_overflow != 0U)) {
            rx_line[rx_used] = '\0';
            if (line_overflow != 0U) {
                stop_all_tests();
                ec_diag_port_write("ERR LINE_TOO_LONG\r\n");
            } else {
                ec_diag_process_line(rx_line);
            }
            rx_used = 0U;
            line_overflow = 0U;
        }
        return;
    }

    if (line_overflow != 0U) return;
    if (rx_used + 1U >= EC_DIAG_LINE_CAPACITY) {
        line_overflow = 1U;
        return;
    }
    rx_line[rx_used++] = (char)byte;
}

void ec_diag_init(void)
{
    rx_used = 0U;
    line_overflow = 0U;
    rx_head = 0U;
    rx_tail = 0U;
    rx_queue_overflow = 0U;
    last_status_ms = 0U;
}

void ec_diag_process_line(const char *line)
{
#if EC_SERVO_TEST_BUILD
    uint16_t servo_pulse_us = 0U;
#endif
#if EC_GROUP_TEST_BUILD
    ec_direction_t group_x_direction = EC_DIRECTION_0;
    ec_direction_t group_y_direction = EC_DIRECTION_0;
    uint16_t group_servo_pulse_us = 0U;
#endif
#if EC_BARRIER_TEST_BUILD
    uint16_t barrier_pulse_us = 0U;
    uint8_t barrier_channel_mask = 0U;
#endif
    ec_axis_t move_axis = EC_AXIS_NONE;
    ec_direction_t move_direction = EC_DIRECTION_0;
    uint32_t move_steps = 0U;
    uint32_t move_hz = 0U;

    if (strcmp(line, "HELP") == 0) {
        ec_diag_port_write(
            "HELP PING STATUS INPUTS TOF TOFDBG TOFRAW TOFSEND "
            "LIGHT ON|OFF LIGHT LV 0-255 LIGHT RGB r g b LIGHT? GRIP n t "
            "DROP OPEN|CLOSE|MID|POS us|? "
            "STEP X|Y STEP STOP MOTION ARM "
            "MOVE X|Y DIR0|DIR1 MOVE X|Y DIR0|DIR1 STEPS n HZ f "
            "MOVE XY XDIR0|XDIR1 STEPS n YDIR0|YDIR1 STEPS m HZ f "
            "SPEED hz|? " "INTERP ON|OFF|? "
            "SERVO ARM SERVO PB10 "
            "P1000|P1100|P1200|P1300|P1500|P1700|P1900 "
            "SERVO STOP GROUP ARM GROUP START XDIR0|XDIR1 "
            "YDIR0|YDIR1 OPEN|CLOSE GROUP STOP BARRIER ARM "
            "BARRIER P|ALL P|1 P|2 P|3 P|4 P BARRIER COLLECT P|AVOID P "
            "BARRIER STOP STOP ALL\r\n");
    } else if (strcmp(line, "PING") == 0) {
        ec_diag_port_write("OK PONG\r\n");
    } else if (strcmp(line, "LIGHT ON") == 0) {
        /* 2026-09-18 新增：台架直控补光灯。
         * 2026-10-18 变更：实物为 WS2812（16 颗），改为发送 GRB 帧点亮白光。 */
        ec_board_light_set(true);
        ec_diag_port_write("OK LIGHT ON\r\n");
    } else if (strcmp(line, "LIGHT OFF") == 0) {
        ec_board_light_set(false);
        ec_diag_port_write("OK LIGHT OFF\r\n");
    } else if (strncmp(line, "LIGHT LV ", 9U) == 0) {
        /* 2026-10-18 新增：设白光亮度 0-255（16 颗 × 0.3W，全白约 1A @5V）。 */
        unsigned lv = 0U;
        if ((sscanf(line, "LIGHT LV %u", &lv) == 1) &&
            (lv <= EC_WS2812_LEVEL_MAX)) {
            (void)ec_ws2812_set_white_level((uint8_t)lv);
            ec_diag_port_write("OK LIGHT LV\r\n");
        } else {
            ec_diag_port_write("ERR LIGHT_USAGE LIGHT LV <0-255>\r\n");
        }
    } else if (strncmp(line, "LIGHT RGB ", 10U) == 0) {
        /* 2026-10-18 新增：设任意颜色（调试/状态指示用）。 */
        unsigned r = 0U;
        unsigned g = 0U;
        unsigned b = 0U;
        if ((sscanf(line, "LIGHT RGB %u %u %u", &r, &g, &b) == 3) &&
            (r <= 255U) && (g <= 255U) && (b <= 255U)) {
            ec_ws2812_fill((uint8_t)r, (uint8_t)g, (uint8_t)b);
            ec_diag_port_write("OK LIGHT RGB\r\n");
        } else {
            ec_diag_port_write("ERR LIGHT_USAGE LIGHT RGB <r> <g> <b> 0-255\r\n");
        }
    } else if (strcmp(line, "LIGHT?") == 0) {
        char output[48];
        (void)snprintf(output, sizeof(output), "OK LIGHT LV=%u LED=%u\r\n",
                       (unsigned)ec_ws2812_white_level(),
                       (unsigned)EC_WS2812_LED_COUNT);
        ec_diag_port_write(output);
    } else if (strncmp(line, "GRIP ", 5U) == 0) {
        /* 2026-09-18 新增：台架直控自适应夹爪总线舵机（HX-06L，USART3/PB10）。
         * 用法：GRIP <位置 0-1000> <时间 ms>
         * 出厂参考值：400 = 张开最大(升) / 500 = 中位 / 640 = 闭合(降)。
         * 机械为单自由度：开即升、闭即降。 */
        unsigned pos = 0U;
        unsigned tms = 0U;
        if ((sscanf(line, "GRIP %u %u", &pos, &tms) == 2) &&
            (pos <= EC_BUS_SERVO_POS_MAX) &&
            (tms <= EC_BUS_SERVO_TIME_MAX_MS)) {
            ec_diag_port_write(ec_grip_port_move((uint16_t)pos,
                                                 (uint16_t)tms) ?
                               "OK GRIP MOVING\r\n" :
                               "ERR GRIP_SEND_FAILED\r\n");
        } else {
            ec_diag_port_write("ERR GRIP_USAGE GRIP <pos 0-1000> <time_ms>\r\n");
        }
    } else if (strncmp(line, "DROP", 4U) == 0) {
        /* 2026-10-22 新增：XY 最远端【落料舵机】台架直控（PE5 / TIM9_CH1 / 50Hz）。
         * 用法：
         *   DROP OPEN       放行（脉宽 = EC_DROP_SERVO_OPEN_US）
         *   DROP CLOSE      挡住（脉宽 = EC_DROP_SERVO_CLOSE_US）
         *   DROP MID        中位（1500µs，上电安全位）
         *   DROP POS <us>   任意脉宽（500~2500，越界 ERR）
         *   DROP?           查询当前已下发脉宽与就绪状态
         *
         * ⚠️ 舵机型号未知（用户 2026-10-22：暂时不知道）。
         *    OPEN / CLOSE / MID 三个值目前都是 1500µs 占位，
         *    **发 OPEN/CLOSE 不会有任何动作**，必须等型号确定后
         *    在 ec_drop_servo.h 里填实测脉宽再试。
         *    本命令只用于验证通道通了、脉宽可下发。 */
        if (strcmp(line, "DROP?") == 0) {
            char output[96];
            (void)snprintf(output, sizeof(output),
                           "OK DROP ready=%u current_us=%u open_us=%u close_us=%u\r\n",
                           (unsigned)(ec_drop_servo_is_ready() ? 1U : 0U),
                           (unsigned)ec_drop_servo_current_us(),
                           (unsigned)EC_DROP_SERVO_OPEN_US,
                           (unsigned)EC_DROP_SERVO_CLOSE_US);
            ec_diag_port_write(output);
        } else if (strcmp(line, "DROP OPEN") == 0) {
            ec_diag_port_write(ec_drop_servo_open() ?
                               "OK DROP MOVING\r\n" :
                               "ERR DROP_NOT_READY\r\n");
        } else if (strcmp(line, "DROP CLOSE") == 0) {
            ec_diag_port_write(ec_drop_servo_close() ?
                               "OK DROP MOVING\r\n" :
                               "ERR DROP_NOT_READY\r\n");
        } else if (strcmp(line, "DROP MID") == 0) {
            ec_diag_port_write(ec_drop_servo_mid() ?
                               "OK DROP MOVING\r\n" :
                               "ERR DROP_NOT_READY\r\n");
        } else if (strncmp(line, "DROP POS ", 9U) == 0) {
            unsigned us = 0U;
            if ((sscanf(line, "DROP POS %u", &us) == 1) &&
                (us >= EC_DROP_SERVO_MIN_US) && (us <= EC_DROP_SERVO_MAX_US)) {
                if (ec_drop_servo_set_us((uint16_t)us)) {
                    char output[64];
                    (void)snprintf(output, sizeof(output),
                                   "OK DROP POS %u\r\n", us);
                    ec_diag_port_write(output);
                } else {
                    ec_diag_port_write("ERR DROP_NOT_READY\r\n");
                }
            } else {
                /* 2026-10-22：文案改为引用常量，避免日后改范围时文案失同步。
                 * 当前范围 = EC_DROP_SERVO_MIN_US..MAX_US（MG996R 270° 量程，留端点余量）。 */
                char output[72];
                (void)snprintf(output, sizeof(output),
                               "ERR DROP_RANGE DROP POS %u-%u\r\n",
                               (unsigned)EC_DROP_SERVO_MIN_US,
                               (unsigned)EC_DROP_SERVO_MAX_US);
                ec_diag_port_write(output);
            }
        } else {
            ec_diag_port_write("ERR DROP_USAGE DROP OPEN|CLOSE|MID|POS us|?\r\n");
        }
    } else if (strcmp(line, "TOF") == 0) {
        /* 2026-10-17 新增：读取 ToF（MINIF/DVP0501C1, UART4）最新一帧。
         * 2026-10-18 增加 raw / uart_err 两个诊断字段：
         *   raw=0              ⇒ 物理层没信号（查供电/接线/引脚）
         *   raw>0 但 frames=0  ⇒ 字节到了，但协议或波特率不对 */
        char output[192];
        uint16_t dist_mm = 0U;
        uint8_t conf = 0U;
        uint32_t age_ms = 0U;
        bool fresh = ec_tof_latest(&dist_mm, &conf, &age_ms, HAL_GetTick());

        (void)snprintf(output, sizeof(output),
                       "%s TOF valid=%u dist_mm=%u conf=%u age_ms=%lu frames=%lu "
                       "errors=%lu raw=%lu uart_err=%lu\r\n",
                       fresh ? "OK" : "STALE",
                       fresh ? 1U : 0U,
                       (unsigned)dist_mm,
                       (unsigned)conf,
                       (unsigned long)age_ms,
                       (unsigned long)ec_tof_frames(),
                       (unsigned long)ec_tof_errors(),
                       (unsigned long)ec_tof_raw_bytes(),
                       (unsigned long)ec_tof_uart_errors());
        ec_diag_port_write(output);
    } else if (strcmp(line, "TOFDBG") == 0) {
        /* 2026-10-18 新增：UART4 硬件状态。
         * CR1: bit5=RXNEIE(接收中断使能) bit13=UE(串口使能) bit2=RE(接收使能)
         * SR : bit5=RXNE(收到字节) bit3=ORE(溢出) bit1=FE(帧错) bit2=NE(噪声)
         * 若 CR1 里 UE/RE/RXNEIE 没开 ⇒ 软件没在收，不是硬件问题。
         *
         * ⚠️ 寄存器直读依赖真实的 STM32 HAL。主机测试用的
         * tests/host_stubs/stm32f4xx_hal.h 只提供 HAL_GetTick()，
         * 没有 UART_HandleTypeDef，也没有 huart4 的定义。
         * USE_HAL_DRIVER 只由 Keil 工程定义，故用它区分真机与主机测试：
         *   真机 → 输出完整寄存器快照
         *   主机测试 → 输出提示串，保持可编译、可链接 */
#if defined(USE_HAL_DRIVER)
        char output[192];
        extern UART_HandleTypeDef huart4;
        (void)snprintf(output, sizeof(output),
                       "TOFDBG gState=0x%02X RxState=0x%02X CR1=0x%08lX SR=0x%08lX "
                       "raw=%lu uart_err=%lu\r\n",
                       (unsigned)huart4.gState,
                       (unsigned)huart4.RxState,
                       (unsigned long)huart4.Instance->CR1,
                       (unsigned long)huart4.Instance->SR,
                       (unsigned long)ec_tof_raw_bytes(),
                       (unsigned long)ec_tof_uart_errors());
        ec_diag_port_write(output);
#else
        ec_diag_port_write("TOFDBG UNAVAILABLE (host build)\r\n");
#endif
    } else if (strcmp(line, "TOFRAW") == 0) {
        /* 2026-10-18 新增：ToF 原始字节快照 + 最近一次被拒行的现场。
         * 用途：出现「errors 狂涨、frames 不动」时，直接看 ToF 到底在发什么。
         * 输出：
         *   TOFRAW n=64 hex=20 33 32 37 2C ...
         *   TOFREJ reason=4 line=[327, 61]
         * 原因码：1=无逗号 2=距离解析失败 3=置信度解析失败 4=超范围 5=行超长 */
        char out[384];
        uint8_t buf[EC_TOF_RAW_RING];
        uint8_t n = ec_tof_raw_ring(buf, (uint8_t)sizeof(buf));
        uint8_t i;
        size_t pos;
        int w;

        w = snprintf(out, sizeof(out), "TOFRAW n=%u hex=", (unsigned)n);
        pos = (w > 0) ? (size_t)w : 0U;
        if (pos > sizeof(out) - 1U) {
            pos = sizeof(out) - 1U;
        }
        for (i = 0U; (i < n) && (pos + 4U < sizeof(out)); i++) {
            w = snprintf(&out[pos], sizeof(out) - pos, "%02X ", (unsigned)buf[i]);
            if (w > 0) {
                pos += (size_t)w;
            }
        }
        ec_diag_port_write(out);

        {
            char rej_line[EC_TOF_LINE_MAX];
            uint8_t reason = ec_tof_last_reject(rej_line, (uint8_t)sizeof(rej_line));
            (void)snprintf(out, sizeof(out), "TOFREJ reason=%u line=[%s]\r\n",
                           (unsigned)reason, rej_line);
            ec_diag_port_write(out);
        }
    } else if (strcmp(line, "TOFSEND") == 0) {
        /* 2026-10-18 新增：UART4 自环测试。把 PC10 与 PC11 短接后执行本命令，
         * 再发 TOF：raw 从 0 变成 8 就证明 STM32 侧收发链路完好。 */
        ec_tof_send_test();
        ec_diag_port_write(
            "OK TOFSEND sent=8 (short PC10-PC11, then TOF.raw should +8)\r\n");
    } else if (strcmp(line, "STATUS") == 0) {
        char output[512];
        (void)snprintf(output, sizeof(output),
                       "STATUS SAFE_LOCK=1 MOTION_TEST=%u SERVO_TEST=%u "
                       "ARMED=%u MODE=%u STEP_AXIS=%u STEP_TARGET=%lu "
                       "STEP_REMAIN=%lu STEP_RESULT=%u SERVO_ARMED=%u "
                       "SERVO_ACTIVE=%u SERVO_US=%u GROUP_TEST=%u "
                       "GROUP_ARMED=%u GROUP_ACTIVE=%u GROUP_XDIR=%u "
                       "GROUP_YDIR=%u GROUP_SERVO_US=%u BARRIER_TEST=%u "
                       "BARRIER_ARMED=%u BARRIER_ACTIVE=%u BARRIER_MASK=%u "
                       "BARRIER_US=%u APP_STATE=%s\r\n",
                       (unsigned)EC_MOTION_TEST_BUILD,
                       (unsigned)EC_SERVO_TEST_BUILD,
                       ec_motion_test_is_armed() ? 1U : 0U,
                       (unsigned)ec_step_test_mode(),
                       (unsigned)ec_step_test_active_axis(),
                       (unsigned long)ec_motion_test_step_target(),
                       (unsigned long)ec_motion_test_step_remaining(),
                       (unsigned)ec_motion_test_step_result(),
                       ec_servo_test_is_armed() ? 1U : 0U,
                       ec_servo_test_is_running() ? 1U : 0U,
                       (unsigned)ec_servo_test_active_pulse_us(),
                       (unsigned)EC_GROUP_TEST_BUILD,
#if EC_GROUP_TEST_BUILD
                       ec_group_test_is_armed() ? 1U : 0U,
                       ec_group_test_is_active() ? 1U : 0U,
                       (unsigned)ec_group_test_x_direction(),
                       (unsigned)ec_group_test_y_direction(),
                       (unsigned)ec_group_test_servo_pulse_us(),
#else
                       0U, 0U, 0U, 0U, 0U,
#endif
#if EC_BARRIER_TEST_BUILD
                       (unsigned)EC_BARRIER_TEST_BUILD,
                       ec_barrier_test_is_armed() ? 1U : 0U,
                       ec_barrier_test_is_active() ? 1U : 0U,
                       (unsigned)ec_barrier_test_active_mask(),
                       (unsigned)ec_barrier_test_pulse_us(),
                       ec_app_state_name(ec_app_state()));
#else
                       0U, 0U, 0U, 0U, 0U,
                       ec_app_state_name(ec_app_state()));
#endif
        ec_diag_port_write(output);
    } else if (strcmp(line, "AXIS") == 0) {
        /* 2026-09-18 新增（**纯诊断**）：生产运动路径的锁存故障现场。
         *
         * 起因：STATUS 的 STEP_* 全部来自诊断模块 ec_motion_test_*（本文件 :383-397），
         * 生产路径 ec_axis_driver 在线上此前**零可观测性**。实机现象是「板子受理
         * ITEM_TASK 后 5 秒内进 FAULT_LOCK、且从不发 MOTION_DONE」，而这个故障原因
         * 从板子外部无论如何都拿不到 —— 加了本命令才能定案。
         *
         * 读的是 fault() 锁存的快照（ec_axis_driver.c 的 latch_fault_diag），
         * 该快照**不被 ec_axis_driver_init() 清除**，所以即使故障已被 ITEM_TASK
         * 重传恢复，这里依然能读到当时的 result / 第几步 / 什么步 / 等了多久。 */
        {
            const ec_axis_driver_diag_t *dg = ec_axis_driver_diag();
            char axis_out[384];
            (void)snprintf(axis_out, sizeof(axis_out),
                           "AXIS FAULTS=%lu TICK_MS=%lu STATE=%u RESULT=%u "
                           "PROGRESS=%lu "
                           "MOVES=%lu LAST_RESULT=%u LAST_STEP=%u LAST_LEN=%u "
                           "LAST_KIND=%u LAST_AXIS=%u LAST_STEPS=%lu "
                           "LAST_PULSE_US=%u LAST_ELAPSED_MS=%lu "
                           "LAST_TIMEOUT_MS=%lu\r\n",
                           (unsigned long)dg->fault_count,
                           (unsigned long)ec_step_port_now_ms(),
                           (unsigned)ec_axis_driver_state(),
                           (unsigned)ec_axis_driver_result(),
                           (unsigned long)ec_axis_driver_progress(),
                           (unsigned long)ec_axis_driver_completed_move_count(),
                           (unsigned)dg->last_result,
                           (unsigned)dg->last_step_index,
                           (unsigned)dg->last_program_length,
                           (unsigned)dg->last_kind,
                           (unsigned)dg->last_axis,
                           (unsigned long)dg->last_steps,
                           (unsigned)dg->last_pulse_us,
                           (unsigned long)dg->last_elapsed_ms,
                           (unsigned long)dg->last_timeout_ms);
            ec_diag_port_write(axis_out);

            /* 2026-09-22：补上【非 fault 路径】的停轴现场。
             * 上面那行读的是 fault() 锁存；「轴被孤立」保护走 stop() 不写锁存
             * ⇒ 此前这条最关键的失败路径在 AXIS 里完全不可见。
             * 只在真的发生过时打第二行，避免常态下多占串口带宽。 */
            {
                ec_app_stop_snapshot_t snap;
                if (ec_app_last_stop_snapshot(&snap)) {
                    /* 128 = 定长部分约 78 字符 + 7 个数字域（最长 10 位）+ NUL，留足余量。
                     * 本函数已是全项目最大栈帧（宿主实测 1216 B），缓冲区不再放大它。 */
                    char stop_out[128];
                    (void)snprintf(
                        stop_out, sizeof(stop_out),
                        "STOPCAUSE=ORPHAN APP_STATE=%u DRV_STATE=%u FAULT=%u "
                        "STEP=%u MOVES=%lu INPUTS=%04X TICK_MS=%lu\r\n",
                        (unsigned)snap.app_state,
                        (unsigned)snap.driver_state,
                        (unsigned)snap.fault_reason,
                        (unsigned)snap.step_index,
                        (unsigned long)snap.moves,
                        (unsigned)snap.active_inputs,
                        (unsigned long)snap.tick_ms);
                    ec_diag_port_write(stop_out);
                    /* 2026-09-22 第二批：窗口/续命现场，另起一行（复用同一缓冲，不增栈）。
                     * 首战读数 = FAULT=6(DEADLINE_EXPIRED)，据此判定"为什么没被续命"：
                     *   WD=0        ⇒ 窗口当时是关的（那就不该触发判据，说明另有蹊跷）
                     *   SILENT_MS   ⇒ 静默了多久（≥15000 即触发判据）
                     *   MOVES_AT_ARM 与 MOVES 之差 = 窗口期内完成了几次计数移动
                     *     差 0 ⇒ 根本没有续命机会（腿没走完 / 计数没涨）
                     *     差 >0 但 SILENT 仍 ≥15000 ⇒ 续命被门拒了（token 不涨或窗口未开） */
                    (void)snprintf(
                        stop_out, sizeof(stop_out),
                        "WINDOW WD=%u SILENT_MS=%lu LAST_OBS=%lu MOVES_AT_ARM=%lu\r\n",
                        (unsigned)snap.wd_active,
                        (unsigned long)snap.silent_ms,
                        (unsigned long)snap.last_obs_ms,
                        (unsigned long)snap.moves_at_arm);
                    ec_diag_port_write(stop_out);
                    /* 2026-09-22 第三批：A0 位置门 + 「离开 EXECUTING」的去向/原因。
                     * 次战读数 WD=0/SILENT_MS=0 证明第二次卡顿不是 15 秒窗，
                     * 这两个字节直接指认是谁把它踢出 EXECUTING 的。 */
                    (void)snprintf(
                        stop_out, sizeof(stop_out),
                        "EXIT POS_VALID=%u EXEC_EXIT_TO=%u EXEC_EXIT_REASON=%u\r\n",
                        (unsigned)snap.position_valid,
                        (unsigned)snap.exec_exit_to,
                        (unsigned)snap.exec_exit_reason);
                    ec_diag_port_write(stop_out);
                    /* 复用同一缓冲取上一次现场（第二次卡顿会覆盖 last，实测丢过线索） */
                    if (ec_app_stop_snapshot_at(1U, &snap)) {
                        (void)snprintf(
                            stop_out, sizeof(stop_out),
                            "PREV_STOP APP_STATE=%u FAULT=%u STEP=%u MOVES=%lu "
                            "WD=%u SILENT_MS=%lu EXIT_TO=%u\r\n",
                            (unsigned)snap.app_state,
                            (unsigned)snap.fault_reason,
                            (unsigned)snap.step_index,
                            (unsigned long)snap.moves,
                            (unsigned)snap.wd_active,
                            (unsigned long)snap.silent_ms,
                            (unsigned)snap.exec_exit_to);
                        ec_diag_port_write(stop_out);
                    }
                }
            }
        }
    } else if (strcmp(line, "INPUTS") == 0) {
        write_inputs();
    } else if (strcmp(line, "STEP X") == 0) {
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ? "ERR TEST_BUSY\r\n" :
                           (!ec_motion_test_is_armed() ? "ERR NOT_ARMED\r\n" :
                            (ec_step_test_start(EC_AXIS_X) ? "OK STEP X\r\n" : "ERR STEP_START\r\n")));
    } else if (strcmp(line, "STEP Y") == 0) {
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ? "ERR TEST_BUSY\r\n" :
                           (!ec_motion_test_is_armed() ? "ERR NOT_ARMED\r\n" :
                            (ec_step_test_start(EC_AXIS_Y) ? "OK STEP Y\r\n" : "ERR STEP_START\r\n")));
    } else if (strcmp(line, "STEP STOP") == 0) {
        stop_all_tests();
        ec_diag_port_write("OK STEP STOP\r\n");
    } else if (strcmp(line, "STOP ALL") == 0) {
        stop_all_tests();
        ec_diag_port_write("OK STOP ALL\r\n");
#if EC_MOTION_TEST_BUILD
    } else if (strcmp(line, "MOTION ARM") == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ?
                           "ERR TEST_BUSY\r\n" :
                           (ec_motion_test_arm(inputs.active_mask) ?
                           "OK MOTION ARMED 10S\r\n" :
                           "ERR MOTION_INHIBITED\r\n"));
    } else if (strcmp(line, "INTERP?") == 0) {
        /* 2026-10-23：查生产路径是否走 XY 插补（R3 生产接入开关）*/
        ec_diag_port_write(ec_app_xy_interp_enabled() ?
                           "OK INTERP on\r\n" : "OK INTERP off\r\n");
    } else if (strcmp(line, "INTERP ON") == 0) {
        /* 切到插补版计划：三段 XY 移动改「两轴同时起步」（12 步 → 9 步）。
         * 只在【下一件】生效 —— 当前正在执行的那件 program 已建好，不受影响。
         * ⚠️ 掉电恢复 off。默认就是 off（串行版，与接入前逐字节相同）。 */
        ec_app_set_xy_interp_enabled(true);
        ec_diag_port_write("OK INTERP on\r\n");
    } else if (strcmp(line, "INTERP OFF") == 0) {
        ec_app_set_xy_interp_enabled(false);
        ec_diag_port_write("OK INTERP off\r\n");
    } else if (strcmp(line, "SPEED?") == 0) {
        /* 2026-10-23：查当前巡航频率（T8 安全速度实测用）*/
        char output[64];
        (void)snprintf(output, sizeof(output), "OK SPEED cruise_hz=%lu\r\n",
                       (unsigned long)ec_step_port_get_cruise_hz());
        ec_diag_port_write(output);
    } else if (strncmp(line, "SPEED ", 6U) == 0) {
        /* 2026-10-23：设巡航频率。烧一次固件后可任意扫档，不用反复重烧。
         *
         * 与 MOVE 的 HZ 的区别：
         *   MOVE ... HZ f  → f **基本无效**（只在轨迹规划失败时兜底）
         *   SPEED hz       → 真正改轨迹曲线的巡航上限，**下一条运动生效**
         *
         * 合法域 201..10000（必须高于曲线起止频率 200Hz）。
         * 提档后必须用方框测试验证复位，见 /home/pi/square_clear.py。 */
        unsigned long hz = 0UL;
        if (sscanf(line, "SPEED %lu", &hz) != 1) {
            ec_diag_port_write("ERR SPEED_USAGE SPEED hz|?\r\n");
        } else if (!ec_step_port_set_cruise_hz((uint32_t)hz)) {
            ec_diag_port_write("ERR SPEED_RANGE SPEED 201-10000\r\n");
        } else {
            char output[64];
            (void)snprintf(output, sizeof(output), "OK SPEED cruise_hz=%lu\r\n", hz);
            ec_diag_port_write(output);
        }
    } else if (strncmp(line, "MOVE XY ", 8U) == 0) {
        /* 2026-10-22 新增：XY 双轴联动【直线合成】。
         *
         * 用法：MOVE XY XDIR0|XDIR1 STEPS nx YDIR0|YDIR1 STEPS ny HZ f
         *
         * HZ f 是【较长那条腿】的频率；较短那条腿按步数比降频，
         * 使两轴**同时到达** ⇒ 合成轨迹是直线，而不是"先走完短腿再走长腿"的折线。
         *
         * 例：X 4000 步 / Y 2000 步 / HZ 500
         *     → freq_x = 500, freq_y = 250
         *     → 两轴都恰好 8.0s 走完 ⇒ 斜线（不是折线）
         *
         * ⚠️ 底层 ec_step_port_start_counted_xy() 不做几何插补，只保证"同时启动、
         *    各自独立频率、各自计数到 0"。所以直线效果完全靠上面的频率比实现。
         * ⚠️ 降频后若低于 EC_STEP_MIN_HZ 会被抬到下限，此时两轴不再同时到达，
         *    轨迹会略微偏离直线（在步数比极端时才会发生）。
         *
         * 安全：与单轴 MOVE 一样需要先 MOTION ARM（10 秒窗口），消费一次窗口。 */
        unsigned xd = 0U;
        unsigned yd = 0U;
        unsigned long xs = 0UL;
        unsigned long ys = 0UL;
        unsigned long hz = 0UL;

        if (sscanf(line, "MOVE XY XDIR%u STEPS %lu YDIR%u STEPS %lu HZ %lu",
                   &xd, &xs, &yd, &ys, &hz) != 5) {
            ec_diag_port_write("ERR MOVE_XY_USAGE "
                               "MOVE XY XDIR0|XDIR1 STEPS n YDIR0|YDIR1 STEPS m HZ f\r\n");
        } else if ((xd > 1U) || (yd > 1U) ||
                   (xs == 0UL) || (xs > (unsigned long)EC_STEP_MAX_STEPS) ||
                   (ys == 0UL) || (ys > (unsigned long)EC_STEP_MAX_STEPS) ||
                   (hz < (unsigned long)EC_STEP_MIN_HZ) ||
                   (hz > (unsigned long)EC_STEP_MAX_HZ)) {
            ec_diag_port_write("ERR MOVE_XY_RANGE\r\n");
        } else {
            unsigned long major = (xs > ys) ? xs : ys;
            /* steps*hz 最大 16000*10000 = 1.6e8，32 位 unsigned long 足够 */
            uint32_t fx = (uint32_t)((xs * hz) / major);
            uint32_t fy = (uint32_t)((ys * hz) / major);

            if (fx < (uint32_t)EC_STEP_MIN_HZ) {
                fx = (uint32_t)EC_STEP_MIN_HZ;
            }
            if (fy < (uint32_t)EC_STEP_MIN_HZ) {
                fy = (uint32_t)EC_STEP_MIN_HZ;
            }

            if (barrier_test_busy() || group_test_busy()) {
                ec_diag_port_write("ERR TEST_BUSY\r\n");
            } else if (ec_motion_test_start_steps_xy2(
                           (xd == 0U) ? EC_DIRECTION_0 : EC_DIRECTION_1,
                           (uint32_t)xs,
                           (yd == 0U) ? EC_DIRECTION_0 : EC_DIRECTION_1,
                           (uint32_t)ys,
                           fx, fy,
                           ec_board_read_inputs().active_mask)) {
                char output[96];
                (void)snprintf(output, sizeof(output),
                               "OK MOTION XY STARTING fx=%lu fy=%lu\r\n",
                               (unsigned long)fx, (unsigned long)fy);
                ec_diag_port_write(output);
            } else {
                ec_diag_port_write("ERR MOTION_NOT_ARMED_OR_INHIBITED\r\n");
            }
        }
    } else if (parse_move_steps_command(line, &move_axis, &move_direction,
                                        &move_steps, &move_hz)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write((barrier_test_busy() || group_test_busy()) ?
                           "ERR TEST_BUSY\r\n" :
                           (ec_motion_test_start_steps(move_axis,
                                                       move_direction,
                                                       move_steps,
                                                       move_hz,
                                                       inputs.active_mask) ?
                            "OK MOTION STARTING\r\n" :
                            "ERR MOTION_NOT_ARMED_OR_INHIBITED\r\n"));
    } else if ((strcmp(line, "MOVE X DIR0") == 0) ||
               (strcmp(line, "MOVE X DIR1") == 0) ||
               (strcmp(line, "MOVE Y DIR0") == 0) ||
               (strcmp(line, "MOVE Y DIR1") == 0)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_axis_t axis = (line[5] == 'X') ? EC_AXIS_X : EC_AXIS_Y;
        ec_direction_t direction = (line[10] == '1') ?
                                   EC_DIRECTION_1 : EC_DIRECTION_0;
        ec_diag_port_write((barrier_test_busy() || group_test_busy()) ?
                           "ERR TEST_BUSY\r\n" :
                           (ec_motion_test_start(axis, direction,
                                                inputs.active_mask) ?
                           "OK MOTION STARTING\r\n" :
                           "ERR MOTION_NOT_ARMED_OR_INHIBITED\r\n"));
#else
    } else if ((strcmp(line, "MOTION ARM") == 0) ||
               (strncmp(line, "MOVE ", 5U) == 0)) {
        ec_diag_port_write("ERR MOTION_TEST_DISABLED\r\n");
#endif
#if EC_SERVO_TEST_BUILD
    } else if (strcmp(line, "SERVO ARM") == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_servo_test_arm(inputs.active_mask,
                                             step_test_busy() ||
                                             barrier_test_busy() ||
                                             group_test_busy()) ?
                           "OK SERVO ARMED 10S\r\n" :
                           "ERR SERVO_INHIBITED_OR_BUSY\r\n");
    } else if (servo_pulse_from_command(line, &servo_pulse_us)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_servo_test_start(servo_pulse_us,
                                               inputs.active_mask,
                                               step_test_busy() ||
                                               barrier_test_busy() ||
                                               group_test_busy()) ?
                           "OK SERVO STARTING 2S\r\n" :
                           "ERR SERVO_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
    } else if (strcmp(line, "SERVO STOP") == 0) {
        if (group_test_busy() || barrier_test_busy()) {
            ec_diag_port_write("ERR TEST_BUSY\r\n");
        } else {
            ec_servo_test_stop();
            ec_diag_port_write("OK SERVO STOP\r\n");
        }
#else
    } else if (strncmp(line, "SERVO ", 6U) == 0) {
        ec_diag_port_write("ERR SERVO_TEST_DISABLED\r\n");
#endif
#if EC_GROUP_TEST_BUILD
    } else if (strcmp(line, "GROUP ARM") == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_group_test_arm(inputs.active_mask,
                                             step_test_busy(),
                                             servo_test_busy() ||
                                             barrier_test_busy()) ?
                           "OK GROUP ARMED 10S\r\n" :
                           "ERR GROUP_INHIBITED_OR_BUSY\r\n");
    } else if (group_values_from_command(line, &group_x_direction,
                                         &group_y_direction,
                                         &group_servo_pulse_us)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_group_test_start(group_x_direction,
                                               group_y_direction,
                                               group_servo_pulse_us,
                                               inputs.active_mask,
                                               step_test_busy(),
                                               servo_test_busy() ||
                                               barrier_test_busy()) ?
                           "OK GROUP STARTING\r\n" :
                           "ERR GROUP_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
    } else if (strcmp(line, "GROUP STOP") == 0) {
        ec_group_test_stop();
        ec_diag_port_write("OK GROUP STOP\r\n");
#else
    } else if (strncmp(line, "GROUP ", 6U) == 0) {
        ec_diag_port_write("ERR GROUP_TEST_DISABLED\r\n");
#endif
#if EC_BARRIER_TEST_BUILD
    } else if (strcmp(line, "BARRIER ARM") == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_barrier_test_arm(inputs.active_mask,
                                               step_test_busy() ||
                                               servo_active_now() ||
                                               group_test_busy()) ?
                           "OK BARRIER ARMED 10S\r\n" :
                           "ERR BARRIER_INHIBITED_OR_BUSY\r\n");
    } else if ((strncmp(line, "BARRIER P", 9U) == 0) ||
               (strncmp(line, "BARRIER ALL P", 13U) == 0)) {
        const char *pulse_text = (line[8] == 'P') ? line + 8U : line + 12U;
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        if (!parse_barrier_pulse(pulse_text, &barrier_pulse_us)) {
            ec_diag_port_write("ERR BAD_COMMAND\r\n");
        } else {
            ec_diag_port_write(ec_barrier_test_start(UINT8_C(0x0F),
                                                     barrier_pulse_us,
                                                     inputs.active_mask,
                                                     step_test_busy() ||
                                                     servo_active_now() ||
                                                     group_test_busy()) ?
                               "OK BARRIER SET ALL\r\n" :
                               "ERR BARRIER_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
        }
    } else if (parse_barrier_channel_command(line, &barrier_channel_mask,
                                             &barrier_pulse_us)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_diag_port_write(ec_barrier_test_start(barrier_channel_mask,
                                                 barrier_pulse_us,
                                                 inputs.active_mask,
                                                 step_test_busy() ||
                                                 servo_active_now() ||
                                                 group_test_busy()) ?
                           "OK BARRIER SET CHANNEL\r\n" :
                           "ERR BARRIER_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
    } else if (strncmp(line, "BARRIER COLLECT P", 17U) == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        if (!parse_barrier_pulse(line + 16U, &barrier_pulse_us)) {
            ec_diag_port_write("ERR BAD_COMMAND\r\n");
        } else {
            ec_diag_port_write(ec_barrier_test_start(UINT8_C(0x0F),
                                                     barrier_pulse_us,
                                                     inputs.active_mask,
                                                     step_test_busy() ||
                                                     servo_active_now() ||
                                                     group_test_busy()) ?
                               "OK BARRIER COLLECT\r\n" :
                               "ERR BARRIER_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
        }
    } else if (strncmp(line, "BARRIER AVOID P", 15U) == 0) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        if (!parse_barrier_pulse(line + 14U, &barrier_pulse_us)) {
            ec_diag_port_write("ERR BAD_COMMAND\r\n");
        } else {
            ec_diag_port_write(ec_barrier_test_start(UINT8_C(0x0F),
                                                     barrier_pulse_us,
                                                     inputs.active_mask,
                                                     step_test_busy() ||
                                                     servo_active_now() ||
                                                     group_test_busy()) ?
                               "OK BARRIER AVOID\r\n" :
                               "ERR BARRIER_NOT_ARMED_INHIBITED_OR_BUSY\r\n");
        }
    } else if (strcmp(line, "BARRIER STOP") == 0) {
        ec_barrier_test_stop();
        ec_diag_port_write("OK BARRIER STOP\r\n");
#else
    } else if (strncmp(line, "BARRIER ", 8U) == 0) {
        ec_diag_port_write("ERR BARRIER_TEST_DISABLED\r\n");
#endif
    } else {
        ec_diag_port_write("ERR BAD_COMMAND\r\n");
    }
}

void ec_diag_on_rx_byte(uint8_t byte)
{
    uint16_t next = (uint16_t)(rx_head + 1U);
    if (next >= EC_DIAG_RX_CAPACITY) next = 0U;
    if (next == rx_tail) {
        rx_queue_overflow = 1U;
        return;
    }
    rx_bytes[rx_head] = byte;
    rx_head = next;
}

void ec_diag_poll(void)
{
    if (rx_queue_overflow != 0U) {
        stop_all_tests();
        rx_queue_overflow = 0U;
        rx_tail = rx_head;
        rx_used = 0U;
        line_overflow = 0U;
        ec_diag_port_write("ERR RX_OVERFLOW\r\n");
        return;
    }

    while (rx_tail != rx_head) {
        uint8_t byte = rx_bytes[rx_tail];
        uint16_t next = (uint16_t)(rx_tail + 1U);
        if (next >= EC_DIAG_RX_CAPACITY) next = 0U;
        rx_tail = next;
        consume_rx_byte(byte);
    }
}

void ec_diag_tick(uint32_t now_ms)
{
    if ((uint32_t)(now_ms - last_status_ms) >= UINT32_C(1000)) {
        last_status_ms = now_ms;
        ec_diag_process_line("STATUS");
    }
}
#else
void ec_diag_init(void) { }
void ec_diag_process_line(const char *line) { (void)line; }
void ec_diag_on_rx_byte(uint8_t byte) { (void)byte; }
void ec_diag_poll(void) { }
void ec_diag_tick(uint32_t now_ms) { (void)now_ms; }
#endif
