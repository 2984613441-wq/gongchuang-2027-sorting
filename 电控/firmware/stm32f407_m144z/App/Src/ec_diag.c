#include "ec_diag.h"
#include "ec_barrier_test.h"
#include "ec_group_test.h"
#include "ec_servo_test.h"
#include "ec_step_test.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
        { "GROUP START XDIR0 YDIR0 OPEN", EC_DIRECTION_0, EC_DIRECTION_0, UINT16_C(1000) },
        { "GROUP START XDIR0 YDIR0 CLOSE", EC_DIRECTION_0, EC_DIRECTION_0, UINT16_C(1900) },
        { "GROUP START XDIR0 YDIR1 OPEN", EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1000) },
        { "GROUP START XDIR0 YDIR1 CLOSE", EC_DIRECTION_0, EC_DIRECTION_1, UINT16_C(1900) },
        { "GROUP START XDIR1 YDIR0 OPEN", EC_DIRECTION_1, EC_DIRECTION_0, UINT16_C(1000) },
        { "GROUP START XDIR1 YDIR0 CLOSE", EC_DIRECTION_1, EC_DIRECTION_0, UINT16_C(1900) },
        { "GROUP START XDIR1 YDIR1 OPEN", EC_DIRECTION_1, EC_DIRECTION_1, UINT16_C(1000) },
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
    } else if (axis_char == 'Z') {
        *axis = EC_AXIS_Z;
    } else {
        return false;
    }
    if ((dir_value != 0UL) && (dir_value != 1UL)) return false;
    if ((steps_value == 0UL) || (steps_value > 1000000UL)) return false;
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
            "HELP PING STATUS INPUTS STEP X|Y|Z STEP STOP MOTION ARM "
            "MOVE X|Y|Z DIR0|DIR1 MOVE X|Y|Z DIR0|DIR1 STEPS n HZ f "
            "SERVO ARM SERVO PB10 "
            "P1000|P1100|P1200|P1300|P1500|P1700|P1900 "
            "SERVO STOP GROUP ARM GROUP START XDIR0|XDIR1 "
            "YDIR0|YDIR1 OPEN|CLOSE GROUP STOP BARRIER ARM "
            "BARRIER P|ALL P|1 P|2 P|3 P|4 P BARRIER COLLECT P|AVOID P "
            "BARRIER STOP STOP ALL\r\n");
    } else if (strcmp(line, "PING") == 0) {
        ec_diag_port_write("OK PONG\r\n");
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
                       "BARRIER_US=%u\r\n",
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
                       (unsigned)ec_barrier_test_pulse_us());
#else
                       0U, 0U, 0U, 0U, 0U);
#endif
        ec_diag_port_write(output);
    } else if (strcmp(line, "INPUTS") == 0) {
        write_inputs();
    } else if (strcmp(line, "STEP X") == 0) {
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ? "ERR TEST_BUSY\r\n" :
                           (ec_step_test_start(EC_AXIS_X) ? "OK STEP X\r\n" : "ERR STEP_START\r\n"));
    } else if (strcmp(line, "STEP Y") == 0) {
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ? "ERR TEST_BUSY\r\n" :
                           (ec_step_test_start(EC_AXIS_Y) ? "OK STEP Y\r\n" : "ERR STEP_START\r\n"));
    } else if (strcmp(line, "STEP Z") == 0) {
        ec_diag_port_write((ec_servo_test_blocks_step() || barrier_test_busy() || group_test_busy()) ? "ERR TEST_BUSY\r\n" :
                           (ec_step_test_start(EC_AXIS_Z) ? "OK STEP Z\r\n" : "ERR STEP_START\r\n"));
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
               (strcmp(line, "MOVE Y DIR1") == 0) ||
               (strcmp(line, "MOVE Z DIR0") == 0) ||
               (strcmp(line, "MOVE Z DIR1") == 0)) {
        ec_input_snapshot_t inputs = ec_board_read_inputs();
        ec_axis_t axis = (line[5] == 'X') ? EC_AXIS_X :
                         ((line[5] == 'Y') ? EC_AXIS_Y : EC_AXIS_Z);
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
