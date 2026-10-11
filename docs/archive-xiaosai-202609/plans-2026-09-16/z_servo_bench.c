/* =========================================================================
 * z_servo_bench.c —— Z 舵机脉宽重测 · 独立裸机最小台架（方案 C，备选）
 * =========================================================================
 * 适用：现有台架命令(SERVO PB10)与 Z 舵机实际接线不一致、且不想改
 *       ec_servo_test.c / ec_diag.c 时，用本文件做最小台架。
 *       新建最小 Keil 工程（仅本文件 + STM32F407 启动文件 + CMSIS
 *       stm32f4xx.h），编译烧录，与生产工程完全隔离；用完烧回生产固件。
 *
 * 前提（与生产固件一致）：
 *   - 系统时钟 = HSI 16 MHz（复位默认；若板子启用了 PLL，需按实际
 *     TIM2 时钟重算 PSC，见文件尾注）
 *   - TIM2 输出 50 Hz 伺服 PWM（PSC=15, ARR=19999 → 20 ms 周期）
 *
 * 行为：
 *   - 串口 USART2（PA2=TX, PA3=RX）115200 8N1，ASCII 命令（CR/LF 结尾）：
 *       P<脉宽>   例 P1100 → 所选通道输出 1100 us，2 秒后自动停止
 *       Q         立即停止 PWM
 *   - 编译期宏 Z_SERVO_CH：3 = PB10/TIM2_CH3，4 = PB11/TIM2_CH4
 *     （按实测接线改这一行）
 *
 * 红线：本程序只解决"怎么发脉冲"，执行上电/烧录仍需用户 L4 授权。
 * ========================================================================= */
#include "stm32f4xx.h"

#ifndef Z_SERVO_CH
#define Z_SERVO_CH 4            /* 3=PB10(TIM2_CH3)  4=PB11(TIM2_CH4) */
#endif

#define PULSE_ON_MS   2000U
#define PULSE_MAX_US  2500U     /* MG996R 脉宽上限 */

static void delay_1ms(uint32_t ms)          /* HSI 16MHz: 16000 tick/ms */
{
    SysTick->LOAD = 15999U;
    SysTick->VAL  = 0U;
    SysTick->CTRL = 5U;                     /* CLKSOURCE=HCLK, ENABLE, 不中断 */
    while (ms--) {
        while ((SysTick->CTRL & (1UL << 16)) == 0U) { }
    }
    SysTick->CTRL = 0U;
}

static void uart_put(const char *s)
{
    while (*s) {
        while ((USART2->SR & USART_SR_TXE) == 0U) { }
        USART2->DR = (uint8_t)*s++;
    }
}

static int uart_get(uint8_t *c)             /* 非阻塞读: 1=读到, 0=无 */
{
    if ((USART2->SR & USART_SR_RXNE) != 0U) {
        *c = (uint8_t)USART2->DR;
        return 1;
    }
    return 0;
}

static void pwm_start(uint16_t pulse_us)
{
#if Z_SERVO_CH == 3
    TIM2->CCR3 = pulse_us;
    TIM2->CCER |= TIM_CCER_CC3E;            /* CH3 = PB10 */
#else
    TIM2->CCR4 = pulse_us;
    TIM2->CCER |= TIM_CCER_CC4E;            /* CH4 = PB11 */
#endif
}

static void pwm_stop(void)
{
#if Z_SERVO_CH == 3
    TIM2->CCER &= ~TIM_CCER_CC3E;
    TIM2->CCR3 = 0U;
#else
    TIM2->CCER &= ~TIM_CCER_CC4E;
    TIM2->CCR4 = 0U;
#endif
}

static void gpio_tim2_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
#if Z_SERVO_CH == 3
    GPIOB->MODER  = (GPIOB->MODER & ~(3UL << (10 * 2))) | (2UL << (10 * 2));   /* PB10 AF */
    GPIOB->AFR[1] = (GPIOB->AFR[1] & ~(0xFUL << ((10 - 8) * 4)))
                  | (1UL << ((10 - 8) * 4));                                   /* AF1=TIM2 */
#else
    GPIOB->MODER  = (GPIOB->MODER & ~(3UL << (11 * 2))) | (2UL << (11 * 2));   /* PB11 AF */
    GPIOB->AFR[1] = (GPIOB->AFR[1] & ~(0xFUL << ((11 - 8) * 4)))
                  | (1UL << ((11 - 8) * 4));                                   /* AF1=TIM2 */
#endif
}

static void tim2_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;
    TIM2->PSC    = 15U;                     /* 16MHz/16 = 1MHz */
    TIM2->ARR    = 19999U;                  /* 20 ms -> 50 Hz */
    TIM2->CCMR1  = TIM_CCMR1_OC3M_1 | TIM_CCMR1_OC3M_2;   /* CH3: PWM1(110) */
    TIM2->CCMR2  = TIM_CCMR2_OC4M_1 | TIM_CCMR2_OC4M_2;   /* CH4: PWM1(110) */
    TIM2->CCER   = 0U;                      /* 输出先不使能 */
    TIM2->CR1   |= TIM_CR1_CEN;
}

static void uart2_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    RCC->APB1ENR |= RCC_APB1ENR_USART2EN;
    GPIOA->MODER  = (GPIOA->MODER & ~((3UL << (2 * 2)) | (3UL << (3 * 2))))
                  | ((2UL << (2 * 2)) | (2UL << (3 * 2)));   /* PA2/PA3 AF */
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~((0xFUL << (2 * 4)) | (0xFUL << (3 * 4))))
                  | ((7UL << (2 * 4)) | (7UL << (3 * 4)));   /* AF7=USART2 */
    USART2->BRR   = 16U * 1000000U / 115200U;               /* ~115200 @16MHz */
    USART2->CR1   = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

/* 2 秒输出窗口内轮询串口：'Q' 可提前停止 */
static void wait_pulse_window(void)
{
    uint32_t ms = PULSE_ON_MS;
    uint8_t c;
    while (ms--) {
        if (uart_get(&c) && (c == 'Q')) break;
        delay_1ms(1U);
    }
    pwm_stop();
}

int main(void)
{
    uint16_t pulse = 0U;
    int have_value = 0;
    uint8_t c;

    gpio_tim2_init();
    tim2_init();
    uart2_init();
    uart_put("Z SERVO BENCH READY CH=");
#if Z_SERVO_CH == 3
    uart_put("PB10\r\n");
#else
    uart_put("PB11\r\n");
#endif

    for (;;) {
        if (uart_get(&c)) {
            if ((c >= '0') && (c <= '9')) {
                pulse = (uint16_t)(pulse * 10U + (uint16_t)(c - '0'));
                have_value = 1;
            } else if ((c == '\r') || (c == '\n')) {
                if (have_value) {
                    if ((pulse >= 500U) && (pulse <= PULSE_MAX_US)) {
                        pwm_start(pulse);
                        wait_pulse_window();
                    } else {
                        uart_put("ERR RANGE 500-2500\r\n");
                    }
                    pulse = 0U;
                    have_value = 0;
                }
            } else if (c == 'Q') {
                pwm_stop();
            } else if (c == 'P') {
                pulse = 0U;
                have_value = 0;
            }
        }
    }
}
/* 尾注：若板子上电后被 PLL 提频（如 SYSCLK=168MHz、APB1=42MHz、
 * TIM2CLK=84MHz），必须把 PSC 改为 83（84MHz/84=1MHz），ARR 保持 19999，
 * 否则脉宽会按比例缩小。以生产 main.c 的实际时钟配置为准。 */
