/**
 * @file    ec_tof.c
 * @brief   TinyF / MINIF(DVP0501C1) 激光测距模组驱动实现（STM32 UART4）
 *
 * 协议详见 ec_tof.h 头部注释。要点：ASCII 文本行，`" 327, 61\n"`。
 *
 * 实现方式
 * --------
 *   UART4 单字节中断接收 → 逐字节喂给行缓冲 → 收到 '\n' 解析整行。
 *   解析失败/超范围只累加 error_count，不丢弃上一条好数据（保留最后有效值）。
 */

#include "ec_tof.h"

#include <string.h>

extern UART_HandleTypeDef huart4;

/* 行缓冲：最长 " 4500, 62\n" ≈ 11 字符，留余量给异常长帧。
 * 2026-10-18：本宏已上移到 ec_tof.h，供 ec_diag.c 的 TOFRAW 命令使用。 */

static uint8_t  rx_byte;
static char     line_buf[EC_TOF_LINE_MAX];
static uint8_t  line_len;

static uint16_t s_dist_mm;
static uint8_t  s_conf;
static uint32_t s_last_ms;
static bool     s_have_frame;
static uint32_t s_frames;
static uint32_t s_errors;
static uint32_t s_raw_bytes;    /* 中断里收到的原始字节数（诊断用） */
static uint32_t s_uart_errors;  /* UART4 HAL 错误回调次数 */

/* 2026-10-18 新增：原始字节环形缓冲 + 最近一次被拒行的现场。
 * 目的：ToF 一旦出现「errors 狂涨 / frames 不动」，能直接看到它在发什么。 */
static uint8_t s_raw_ring[EC_TOF_RAW_RING];
static uint8_t s_raw_ring_idx;
static char    s_reject_line[EC_TOF_LINE_MAX];
static uint8_t s_reject_reason;

static void reject(uint8_t reason, const char *line, uint8_t len)
{
    uint8_t n = (len < (EC_TOF_LINE_MAX - 1U)) ? len : (EC_TOF_LINE_MAX - 1U);
    uint8_t i;

    s_errors++;
    s_reject_reason = reason;
    for (i = 0U; i < n; i++) {
        s_reject_line[i] = line[i];
    }
    s_reject_line[n] = '\0';
}

uint8_t ec_tof_raw_ring(uint8_t *out, uint8_t max)
{
    uint8_t n, i;

    if ((out == NULL) || (max == 0U)) {
        return 0U;
    }
    n = (max < EC_TOF_RAW_RING) ? max : (uint8_t)EC_TOF_RAW_RING;
    for (i = 0U; i < n; i++) {
        out[i] = s_raw_ring[(uint8_t)((s_raw_ring_idx + EC_TOF_RAW_RING - n + i)
                                      % EC_TOF_RAW_RING)];
    }
    return n;
}

uint8_t ec_tof_last_reject(char *line, uint8_t max)
{
    uint8_t i = 0U;

    if ((line == NULL) || (max == 0U)) {
        return s_reject_reason;
    }
    while ((i + 1U < max) && (s_reject_line[i] != '\0')) {
        line[i] = s_reject_line[i];
        i++;
    }
    line[i] = '\0';
    return s_reject_reason;
}

/* ------------------------------------------------------------------ */
/* 解析                                                               */
/* ------------------------------------------------------------------ */

static bool parse_uint(const char *s, uint8_t len, uint32_t *out)
{
    uint32_t v = 0U;
    uint8_t i;

    if ((s == NULL) || (out == NULL) || (len == 0U) || (len > 5U)) {
        return false;
    }
    for (i = 0U; i < len; i++) {
        char c = s[i];
        if ((c < '0') || (c > '9')) {
            return false;
        }
        v = (v * 10U) + (uint32_t)(c - '0');
    }
    *out = v;
    return true;
}

/**
 * @brief 解析一行（不含 '\n'，前导空格已被喂字节时去掉）
 *        期望形如 "327, 61"
 */
static void tof_parse_line(const char *s, uint8_t len)
{
    uint8_t comma = 0xFFU;
    uint8_t i;
    uint32_t dist = 0U;
    uint32_t conf = 0U;

    /* 找分隔符 ',' */
    for (i = 0U; i < len; i++) {
        if (s[i] == ',') {
            comma = i;
            break;
        }
    }
    if (comma == 0xFFU) {
        reject(1U, s, len);
        return;
    }

    /* 距离：逗号之前 */
    if (!parse_uint(s, comma, &dist)) {
        reject(2U, s, len);
        return;
    }

    /* 置信度：逗号之后，跳过空格 */
    i = (uint8_t)(comma + 1U);
    while ((i < len) && (s[i] == ' ')) {
        i++;
    }
    if (!parse_uint(&s[i], (uint8_t)(len - i), &conf)) {
        reject(3U, s, len);
        return;
    }

    /* 范围校验 */
    if ((dist < EC_TOF_DIST_MIN_MM) || (dist > EC_TOF_DIST_MAX_MM) ||
        (conf > EC_TOF_CONF_MAX)) {
        reject(4U, s, len);
        return;
    }

    s_dist_mm    = (uint16_t)dist;
    s_conf       = (uint8_t)conf;
    s_last_ms    = HAL_GetTick();
    s_have_frame = true;
    s_frames++;
}

/** 喂一个字节进行状态机 */
static void tof_feed_byte(uint8_t b)
{
    /* 2026-10-18：每个字节先进原始环形缓冲，供 TOFRAW 看现场 */
    s_raw_ring[s_raw_ring_idx] = b;
    s_raw_ring_idx = (uint8_t)((s_raw_ring_idx + 1U) % EC_TOF_RAW_RING);

    if (b == (uint8_t)'\n') {
        if (line_len > 0U) {
            tof_parse_line(line_buf, line_len);
        }
        line_len = 0U;
        return;
    }
    if (b == (uint8_t)'\r') {
        return;                       /* 容忍 CRLF */
    }
    if ((b == (uint8_t)' ') && (line_len == 0U)) {
        return;                       /* 帧头空格 0x20，吃掉 */
    }
    if (line_len < (EC_TOF_LINE_MAX - 1U)) {
        line_buf[line_len++] = (char)b;
    } else {
        reject(5U, line_buf, line_len);
        line_len = 0U;                /* 超长，丢整行 */
    }
}

/* ------------------------------------------------------------------ */
/* 对外接口                                                           */
/* ------------------------------------------------------------------ */

void ec_tof_init(void)
{
    line_len     = 0U;
    s_dist_mm    = 0U;
    s_conf       = 0U;
    s_last_ms    = 0U;
    s_have_frame = false;
    s_frames     = 0U;
    s_errors     = 0U;
    s_raw_bytes  = 0U;
    s_uart_errors = 0U;
    (void)memset(line_buf, 0, sizeof(line_buf));
    /* 2026-10-18：新增诊断状态的初始化 */
    (void)memset(s_raw_ring, 0, sizeof(s_raw_ring));
    (void)memset(s_reject_line, 0, sizeof(s_reject_line));
    s_raw_ring_idx = 0U;
    s_reject_reason = 0U;

    /* 启动单字节中断接收；之后由 RxCplt 回调自行续接 */
    (void)HAL_UART_Receive_IT(&huart4, &rx_byte, 1U);
}

bool ec_tof_latest(uint16_t *dist_mm, uint8_t *conf, uint32_t *age_ms, uint32_t now_ms)
{
    uint32_t age;

    if (!s_have_frame) {
        if (dist_mm != NULL) { *dist_mm = 0U; }
        if (conf != NULL)    { *conf = 0U; }
        if (age_ms != NULL)  { *age_ms = 0xFFFFFFFFUL; }
        return false;
    }
    age = now_ms - s_last_ms;
    if (dist_mm != NULL) { *dist_mm = s_dist_mm; }
    if (conf != NULL)    { *conf = s_conf; }
    if (age_ms != NULL)  { *age_ms = age; }
    return age <= EC_TOF_STALE_MS;
}

bool ec_tof_have_frame(void)
{
    return s_have_frame;
}

uint32_t ec_tof_frames(void)
{
    return s_frames;
}

uint32_t ec_tof_errors(void)
{
    return s_errors;
}

uint32_t ec_tof_raw_bytes(void)
{
    return s_raw_bytes;
}

uint32_t ec_tof_uart_errors(void)
{
    return s_uart_errors;
}

void ec_tof_send_test(void)
{
    /* 自环测试用固定图案。不关心内容，只要 PC10→PC11 短接后 raw 能涨就说明链路通。
     * 注意：RX 的单字节中断接收是同时开着的，TX 与 RX 互不影响。 */
    static const uint8_t pattern[8] = {
        (uint8_t)'T', (uint8_t)'O', (uint8_t)'F',
        (uint8_t)'L', (uint8_t)'O', (uint8_t)'O',
        (uint8_t)'P', (uint8_t)'\n'
    };
    (void)HAL_UART_Transmit(&huart4, (uint8_t *)pattern,
                            (uint16_t)sizeof(pattern), 100U);
}

void ec_tof_uart_rx_cplt(UART_HandleTypeDef *huart)
{
    if (huart->Instance != UART4) {
        return;
    }
    s_raw_bytes++;
    tof_feed_byte(rx_byte);
    (void)HAL_UART_Receive_IT(&huart4, &rx_byte, 1U);
}

void ec_tof_uart_error(UART_HandleTypeDef *huart)
{
    if (huart->Instance != UART4) {
        return;
    }
    s_uart_errors++;
    s_errors++;
    /* ORE/FE/NE/PE 之后必须重新武装接收，否则会永久静默 */
    (void)HAL_UART_Receive_IT(&huart4, &rx_byte, 1U);
}
