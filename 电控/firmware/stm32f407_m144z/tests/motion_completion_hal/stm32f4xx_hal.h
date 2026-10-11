#ifndef MOTION_COMPLETION_HOST_HAL_H
#define MOTION_COMPLETION_HOST_HAL_H
/* Host model only. Not a hardware, interrupt-latency or electrical test. */
#include <stdint.h>
typedef enum { HAL_OK = 0, HAL_ERROR = 1 } HAL_StatusTypeDef;
typedef enum { GPIO_PIN_RESET = 0, GPIO_PIN_SET = 1 } GPIO_PinState;
typedef struct { uint16_t input, output; } GPIO_TypeDef;
typedef struct { uint32_t Pin, Mode, Pull, Speed, Alternate; } GPIO_InitTypeDef;
typedef struct {
    unsigned Instance;
    struct { uint32_t Period; } Init;
    uint32_t arr, counter, compare[4], interrupts, running;
    uint64_t next_us;
} TIM_HandleTypeDef;
typedef struct { unsigned Instance; } UART_HandleTypeDef;
extern GPIO_TypeDef host_gpio[7];
#define GPIOA (&host_gpio[0])
#define GPIOB (&host_gpio[1])
#define GPIOC (&host_gpio[2])
#define GPIOD (&host_gpio[3])
#define GPIOE (&host_gpio[4])
#define GPIOF (&host_gpio[5])
#define GPIOG (&host_gpio[6])
#define GPIO_PIN_0 (1U << 0)
#define GPIO_PIN_4 (1U << 4)
#define GPIO_PIN_5 (1U << 5)
#define GPIO_PIN_6 (1U << 6)
#define GPIO_PIN_7 (1U << 7)
#define GPIO_PIN_8 (1U << 8)
#define GPIO_PIN_9 (1U << 9)
#define GPIO_PIN_10 (1U << 10)
#define GPIO_PIN_11 (1U << 11)
#define GPIO_PIN_13 (1U << 13)
#define GPIO_PIN_14 (1U << 14)
#define GPIO_PIN_15 (1U << 15)
#define GPIO_MODE_AF_PP 2U
#define GPIO_NOPULL 0U
#define GPIO_SPEED_FREQ_LOW 0U
#define GPIO_SPEED_FREQ_VERY_HIGH 3U
#define GPIO_AF1_TIM2 1U
#define GPIO_AF7_USART3 7U
#define USART2 2U
#define TIM_CHANNEL_1 0U
#define TIM_CHANNEL_3 2U
#define TIM_CHANNEL_4 3U
#define TIM_IT_UPDATE 1U
#define TIM_IT_CC1 2U
#define TIM_FLAG_UPDATE 1U
#define __HAL_TIM_SET_AUTORELOAD(t, v) ((t)->arr = (v))
#define __HAL_TIM_SET_COUNTER(t, v) ((t)->counter = (v))
#define __HAL_TIM_SET_COMPARE(t, c, v) ((t)->compare[(c)] = (v))
#define __HAL_TIM_CLEAR_FLAG(t, f) ((void)(t), (void)(f))
#define __HAL_TIM_ENABLE_IT(t, f) ((t)->interrupts |= (f))
#define __HAL_TIM_DISABLE_IT(t, f) ((t)->interrupts &= ~(f))
#define __HAL_UART_CLEAR_OREFLAG(u) ((void)(u))
#define __HAL_RCC_GPIOB_CLK_ENABLE() ((void)0)
uint32_t HAL_GetTick(void);
uint32_t __get_PRIMASK(void);
void __disable_irq(void);
void __enable_irq(void);
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *p, uint16_t pin);
void HAL_GPIO_WritePin(GPIO_TypeDef *p, uint16_t pin, GPIO_PinState state);
void HAL_GPIO_Init(GPIO_TypeDef *p, GPIO_InitTypeDef *config);
HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *t, uint32_t channel);
HAL_StatusTypeDef HAL_TIM_PWM_Stop(TIM_HandleTypeDef *t, uint32_t channel);
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *u, uint8_t *data,
                                   uint16_t length, uint32_t timeout);
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *u, uint8_t *data,
                                     uint16_t length);
#endif
