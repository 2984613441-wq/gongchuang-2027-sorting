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

#define WS_HIGH() (LIGHT_EN_GPIO_Port->BSRR = (uint32_t)LIGHT_EN_Pin)
#define WS_LOW() (LIGHT_EN_GPIO_Port->BSRR = ((uint32_t)LIGHT_EN_Pin) << 16U)

static uint8_t s_grb[EC_WS2812_BYTES];
static uint8_t s_level = EC_WS2812_DEFAULT_LEVEL;
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

static void ws_send_byte(uint8_t value)
{
    int8_t i;
    for (i = 7; i >= 0; i--) {
        uint32_t start = DWT->CYCCNT;
        uint32_t high_cycles;

        WS_HIGH();
        high_cycles = ((value >> (uint8_t)i) & 0x01U) ? WS_T1H_CYCLES : WS_T0H_CYCLES;
        while ((DWT->CYCCNT - start) < high_cycles) {
            /* busy wait */
        }
        WS_LOW();
        while ((DWT->CYCCNT - start) < WS_PERIOD_CYCLES) {
            /* busy wait */
        }
    }
}

void ec_ws2812_init(void)
{
    uint16_t i;

    ws_dwt_enable();
    WS_LOW();
    for (i = 0U; i < EC_WS2812_BYTES; i++) {
        s_grb[i] = 0U;
    }
    s_level = EC_WS2812_DEFAULT_LEVEL;
    s_inited = true;
}

void ec_ws2812_send_grb(const uint8_t *grb, uint16_t len)
{
    uint16_t i;
    uint32_t primask;

    if (!s_inited) {
        ec_ws2812_init();
    }
    if (grb == NULL) {
        return;
    }
    if (len > EC_WS2812_BYTES) {
        len = EC_WS2812_BYTES;
    }

    /* 帧前复位：低电平保持 >50us。此段中断仍开着，无副作用。 */
    WS_LOW();
    ws_delay_us(WS_RESET_US);

    primask = __get_PRIMASK();
    __disable_irq();
    for (i = 0U; i < len; i++) {
        ws_send_byte(grb[i]);
    }
    __set_PRIMASK(primask);

    /* 帧后复位：锁存。 */
    WS_LOW();
    ws_delay_us(WS_RESET_US);
}

void ec_ws2812_fill(uint8_t r, uint8_t g, uint8_t b)
{
    uint16_t i;

    for (i = 0U; i < EC_WS2812_LED_COUNT; i++) {
        /* WS2812 的线上顺序是 G-R-B */
        s_grb[i * 3U + 0U] = g;
        s_grb[i * 3U + 1U] = r;
        s_grb[i * 3U + 2U] = b;
    }
    ec_ws2812_send_grb(s_grb, EC_WS2812_BYTES);
}

void ec_ws2812_off(void)
{
    ec_ws2812_fill(0U, 0U, 0U);
}

void ec_ws2812_white_on(void)
{
    /* 亮度 255 时就是标定过的中性白 (255,200,90)，不是 (255,255,255) */
    (void)ec_ws2812_set_white_level(s_level);
}

bool ec_ws2812_set_white_level(uint8_t level)
{
    uint16_t lv = level;

    s_level = level;
    /* 按标定比例缩放：level=255 → (255,200,90)；level=128 → (128,100,45)。
     * 用 uint16 乘再除，避免 8 位溢出。 */
    ec_ws2812_fill((uint8_t)((EC_WS2812_WHITE_R * lv) / EC_WS2812_LEVEL_MAX),
                   (uint8_t)((EC_WS2812_WHITE_G * lv) / EC_WS2812_LEVEL_MAX),
                   (uint8_t)((EC_WS2812_WHITE_B * lv) / EC_WS2812_LEVEL_MAX));
    return true;
}

uint8_t ec_ws2812_white_level(void)
{
    return s_level;
}
