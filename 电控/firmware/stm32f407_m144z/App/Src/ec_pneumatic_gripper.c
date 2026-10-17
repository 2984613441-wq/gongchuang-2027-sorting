/* 气动夹爪测试代码 - STM32侧
 * 文件位置：电控/firmware/stm32f407_m144z/App/Src/ec_pneumatic_gripper.c
 *
 * 功能：控制PB11 (TIM2_CH4) 输出50Hz PWM，驱动气动电磁阀
 * 日期：2026-10-11
 */

#include "ec_pneumatic_gripper.h"
#include "stm32f4xx_hal.h"

/* 外部定时器句柄（在main.c或tim.c中定义） */
extern TIM_HandleTypeDef htim2;

/* PWM频率：50Hz（与舵机共享TIM2） */
#define PNEUMATIC_PWM_FREQ_HZ  50U

/* 脉宽范围（微秒），待实测调整 */
#define PNEUMATIC_PULSE_OPEN_US   1000U  /* 张开 */
#define PNEUMATIC_PULSE_CLOSE_US  2000U  /* 闭合 */
#define PNEUMATIC_PULSE_NEUTRAL_US 1500U /* 中位（如果支持） */

/* TIM2工作频率（168MHz主频下，PSC=83，计数钟=1MHz）
 * ARR = 20000 - 1 → 周期20ms = 50Hz
 * CCR单位：1us
 */
#define TIM2_COUNTER_FREQ_HZ  1000000U  /* 1MHz计数钟 */

/**
 * @brief 初始化气动夹爪（启动PWM通道）
 * @note  TIM2已在main.c中初始化，这里只启动CH4通道
 */
void ec_pneumatic_gripper_init(void)
{
    /* 启动TIM2_CH4 PWM输出（PB11引脚） */
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_4);

    /* 初始状态：中位或张开 */
    ec_pneumatic_gripper_set_pulse(PNEUMATIC_PULSE_NEUTRAL_US);
}

/**
 * @brief 设置气动夹爪脉宽（微秒）
 * @param pulse_us 脉宽，范围1000-2000us（根据实际气动阀调整）
 */
void ec_pneumatic_gripper_set_pulse(uint16_t pulse_us)
{
    /* 限幅保护 */
    if (pulse_us < 500U) {
        pulse_us = 500U;
    }
    if (pulse_us > 2500U) {
        pulse_us = 2500U;
    }

    /* 计算CCR值：pulse_us * (计数钟频率 / 1,000,000)
     * TIM2计数钟=1MHz，所以CCR=pulse_us
     */
    uint32_t compare_value = (uint32_t)pulse_us;

    /* 设置TIM2_CH4比较值 */
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, compare_value);
}

/**
 * @brief 气动夹爪张开
 */
void ec_pneumatic_gripper_open(void)
{
    ec_pneumatic_gripper_set_pulse(PNEUMATIC_PULSE_OPEN_US);
}

/**
 * @brief 气动夹爪闭合
 */
void ec_pneumatic_gripper_close(void)
{
    ec_pneumatic_gripper_set_pulse(PNEUMATIC_PULSE_CLOSE_US);
}

/**
 * @brief 气动夹爪中位（如果支持）
 */
void ec_pneumatic_gripper_neutral(void)
{
    ec_pneumatic_gripper_set_pulse(PNEUMATIC_PULSE_NEUTRAL_US);
}

/**
 * @brief 获取当前脉宽（微秒）
 * @return 当前PWM脉宽
 */
uint16_t ec_pneumatic_gripper_get_pulse(void)
{
    uint32_t ccr = __HAL_TIM_GET_COMPARE(&htim2, TIM_CHANNEL_4);
    return (uint16_t)ccr;
}
