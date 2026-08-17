#include "ec_diag.h"
#include "ec_step_test.h"

#include <stdio.h>
#include <string.h>

#ifndef EC_DIAGNOSTIC_BUILD
#define EC_DIAGNOSTIC_BUILD 0
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
    if (strcmp(line, "HELP") == 0) {
        ec_diag_port_write("HELP STATUS INPUTS STEP X STEP Y STEP Z STEP STOP\r\n");
    } else if (strcmp(line, "STATUS") == 0) {
        char output[64];
        (void)snprintf(output, sizeof(output), "STATUS SAFE_LOCK=1 STEP_AXIS=%u\r\n",
                       (unsigned)ec_step_test_active_axis());
        ec_diag_port_write(output);
    } else if (strcmp(line, "INPUTS") == 0) {
        write_inputs();
    } else if (strcmp(line, "STEP X") == 0) {
        ec_diag_port_write(ec_step_test_start(EC_AXIS_X) ? "OK STEP X\r\n" : "ERR STEP_START\r\n");
    } else if (strcmp(line, "STEP Y") == 0) {
        ec_diag_port_write(ec_step_test_start(EC_AXIS_Y) ? "OK STEP Y\r\n" : "ERR STEP_START\r\n");
    } else if (strcmp(line, "STEP Z") == 0) {
        ec_diag_port_write(ec_step_test_start(EC_AXIS_Z) ? "OK STEP Z\r\n" : "ERR STEP_START\r\n");
    } else if (strcmp(line, "STEP STOP") == 0) {
        ec_step_test_stop();
        ec_diag_port_write("OK STEP STOP\r\n");
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
