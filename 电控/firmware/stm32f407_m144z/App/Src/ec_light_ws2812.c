#include "ec_light_ws2812.h"

#include "main.h"
#include "stm32f4xx_hal.h"

#include <stddef.h>

/* 位时序用 DWT->CYCCNT 自校正：
 * 每个位记下起点周期，等到目标周期数再翻转/结束，
 * 这样 GPIO 写入和循环开销都被吸收，不依赖编译器优化等级与 -O0/-O3 差异。
 *   168MHz 下：1us = 168 周期
 *     T0H 0.35us ≈ 58 周期
 *     T1H 0.75us ≈ 126 周期
 *     位周期 1.25us ≈ 210 周期
 * WS2812B 容差很宽（T0H/T1H ±150ns，周期 1.25us±600ns），上述取值居中且安全。 */
#define WS_CYCLES_PER_US (SystemCoreClock / UINT32_C(1000000))
#define WS_T0H_CYCLES ((WS_CYCLES_PER_US * UINT32_C(35)) / UINT32_C(100))
#define WS_T1H_CYCLES ((WS_CYCLES_PER_US * UINT32_C(75)) / UINT32_C(100))
#define WS_PERIOD_CYCLES ((WS_CYCLES_PER_US * UINT32_C(125)) / UINT32_C(100))
#define WS_RESET_US UINT32_C(320) /* 规范要求 >50us，取 320us 兼容各版本 */

/* 🔴 2026-10-30：支持**两路独立** WS2812 灯带（用户确认：同款灯珠，但分别控制、不级联）
 *   路 0：PC0 = LIGHT_EN   （原灯带，16 颗）
 *   路 1：PE3 = LIGHT2_EN  （新增灯带，16 颗）
 * 数据线各自独立，不能用同一条线（否则就成了级联，只能同时同色）。
 *
 * 为什么把 port/pin 提到 ws_send_byte 里做成局部量：
 *   位时序对"高电平开始时刻"敏感；如果在位循环里调用函数取 port/pin，
 *   函数调用开销会吃掉高电平时间（T0H 只有 0.35us）。提到循环外后，
 *   每个位仍然只有一次 BSRR 写，与旧实现指令数完全一致。 */
static inline GPIO_TypeDef *ws_port_of(ec_ws2812_ch ch)
{
    return (ch == EC_WS2812_CH1) ? LIGHT2_EN_GPIO_Port : LIGHT_EN_GPIO_Port;
}

static inline uint16_t ws_pin_of(ec_ws2812_ch ch)
{
    return (ch == EC_WS2812_CH1) ? (uint16_t)LIGHT2_EN_Pin : (uint16_t)LIGHT_EN_Pin;
}

static uint8_t s_grb[EC_WS2812_BYTES];
static uint8_t s_level[EC_WS2812_CH_NUM];
static bool s_inited;

static void ws_dwt_enable(void)
{
    /* TRCENA 必须在写 CYCCNT 之前置位，否则计数器不跑 */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0U;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static inline void ws_delay_cycles(uint32_t cycles)
{
    uint32_t start = DWT->CYCCNT;
    while ((DWT->CYCCNT - start) < cycles) {
        /* busy wait */
    }
}

static inline void ws_delay_us(uint32_t us)
{
    ws_delay_cycles(us * WS_CYCLES_PER_US);
}

static void ws_low(ec_ws2812_ch ch)
{
    GPIO_TypeDef *port = ws_port_of(ch);
    port->BSRR = ((uint32_t)ws_pin_of(ch)) << 16U;
}

static void ws_send_byte(ec_ws2812_ch ch, uint8_t value)
{
    GPIO_TypeDef *port = ws_port_of(ch);
    const uint32_t pin = (uint32_t)ws_pin_of(ch);
    const uint32_t pin_reset = pin << 16U;
    int8_t i;

    for (i = 7; i >= 0; i--) {
        uint32_t start = DWT->CYCCNT;
        uint32_t high_cycles;

        port->BSRR = pin;
        high_cycles = ((value >> (uint8_t)i) & 0x01U) ? WS_T1H_CYCLES : WS_T0H_CYCLES;
        while ((DWT->CYCCNT - start) < high_cycles) {
            /* busy wait */
        }
        port->BSRR = pin_reset;
        while ((DWT->CYCCNT - start) < WS_PERIOD_CYCLES) {
            /* busy wait */
        }
    }
}

void ec_ws2812_init(void)
{
    uint16_t i;
    uint8_t ch;

    ws_dwt_enable();

    /* 两路都先拉低（上电安全态 = 全灭）*/
    ws_low(EC_WS2812_CH0);
    ws_low(EC_WS2812_CH1);

    for (i = 0U; i < EC_WS2812_BYTES; i++) {
        s_grb[i] = 0U;
    }
    for (ch = 0U; ch < (uint8_t)EC_WS2812_CH_NUM; ch++) {
        s_level[ch] = EC_WS2812_DEFAULT_LEVEL;
    }
    s_inited = true;
}

void ec_ws2812_send_grb_ch(ec_ws2812_ch ch, const uint8_t *grb, uint16_t len)
{
    uint16_t i;
    uint32_t primask;

    if (!s_inited) {
        ec_ws2812_init();
    }
    if ((grb == NULL) || (ch >= EC_WS2812_CH_NUM)) {
        return;
    }
    if (len > EC_WS2812_BYTES) {
        len = EC_WS2812_BYTES;
    }

    /* 帧前复位：低电平保持 >50us。此段中断仍开着，无副作用。 */
    ws_low(ch);
    ws_delay_us(WS_RESET_US);

    primask = __get_PRIMASK();
    __disable_irq();
    for (i = 0U; i < len; i++) {
        ws_send_byte(ch, grb[i]);
    }
    __set_PRIMASK(primask);

    /* 帧后复位：锁存。 */
    ws_low(ch);
    ws_delay_us(WS_RESET_US);
}

void ec_ws2812_send_grb(const uint8_t *grb, uint16_t len)
{
    ec_ws2812_send_grb_ch(EC_WS2812_CH0, grb, len);
}

void ec_ws2812_fill_ch(ec_ws2812_ch ch, uint8_t r, uint8_t g, uint8_t b)
{
    uint16_t i;

    for (i = 0U; i < EC_WS2812_LED_COUNT; i++) {
        /* WS2812 的线上顺序是 G-R-B */
        s_grb[i * 3U + 0U] = g;
        s_grb[i * 3U + 1U] = r;
        s_grb[i * 3U + 2U] = b;
    }
    ec_ws2812_send_grb_ch(ch, s_grb, EC_WS2812_BYTES);
}

void ec_ws2812_fill(uint8_t r, uint8_t g, uint8_t b)
{
    ec_ws2812_fill_ch(EC_WS2812_CH0, r, g, b);
}

void ec_ws2812_off_ch(ec_ws2812_ch ch)
{
    ec_ws2812_fill_ch(ch, 0U, 0U, 0U);
}

void ec_ws2812_off(void)
{
    ec_ws2812_off_ch(EC_WS2812_CH0);
}

void ec_ws2812_off_all(void)
{
    uint8_t ch;

    for (ch = 0U; ch < (uint8_t)EC_WS2812_CH_NUM; ch++) {
        ec_ws2812_off_ch((ec_ws2812_ch)ch);
    }
}

void ec_ws2812_white_on_ch(ec_ws2812_ch ch)
{
    /* 亮度以该路自己的记录为准，默认 255 ⇒ 标定过的中性白 (255,200,90) */
    if (ch >= EC_WS2812_CH_NUM) {
        return;
    }
    (void)ec_ws2812_set_white_level_ch(ch, s_level[ch]);
}

void ec_ws2812_white_on(void)
{
    ec_ws2812_white_on_ch(EC_WS2812_CH0);
}

bool ec_ws2812_set_white_level_ch(ec_ws2812_ch ch, uint8_t level)
{
    uint16_t lv = level;

    if (ch >= EC_WS2812_CH_NUM) {
        return false;
    }
    s_level[ch] = level;
    /* 按标定比例缩放：level=255 → (255,200,90)；level=128 → (128,100,45)。
     * 用 uint16 乘再除，避免 8 位溢出。 */
    ec_ws2812_fill_ch(ch,
                      (uint8_t)((EC_WS2812_WHITE_R * lv) / EC_WS2812_LEVEL_MAX),
                      (uint8_t)((EC_WS2812_WHITE_G * lv) / EC_WS2812_LEVEL_MAX),
                      (uint8_t)((EC_WS2812_WHITE_B * lv) / EC_WS2812_LEVEL_MAX));
    return true;
}

bool ec_ws2812_set_white_level(uint8_t level)
{
    return ec_ws2812_set_white_level_ch(EC_WS2812_CH0, level);
}

uint8_t ec_ws2812_white_level_ch(ec_ws2812_ch ch)
{
    if (ch >= EC_WS2812_CH_NUM) {
        return 0U;
    }
    return s_level[ch];
}

uint8_t ec_ws2812_white_level(void)
{
    return ec_ws2812_white_level_ch(EC_WS2812_CH0);
}
