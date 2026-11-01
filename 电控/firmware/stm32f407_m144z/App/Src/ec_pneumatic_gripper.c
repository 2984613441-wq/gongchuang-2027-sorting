/* 气动夹爪控制代码 - STM32侧
 * 文件位置：电控/firmware/stm32f407_m144z/App/Src/ec_pneumatic_gripper.c
 *
 * 功能：控制PB11 (TIM2_CH4) 驱动气动电磁阀（开关控制）
 * 日期：2026-10-11
 * 逻辑来源：朋友的f407测试气泵代码
 */

#include "ec_pneumatic_gripper.h"
#include "stm32f4xx_hal.h"

/* 外部定时器句柄（在main.c或tim.c中定义） */
extern TIM_HandleTypeDef htim2;

/* 气动电磁阀：开关控制（不是舵机）
 * 占空比 100% = 吸附（电磁阀通电）
 * 占空比 0%   = 释放（电磁阀断电）
 *
 * 我们的TIM2配置：
 * PSC = 83, ARR = 19999 (20000-1)
 * 频率 = 84MHz / 84 / 20000 = 50Hz
 * CCR范围：0~20000
 */
#define PNEUMATIC_DUTY_OFF   0U      /* 释放：0%占空比 */
#define PNEUMATIC_DUTY_ON    20000U  /* 吸附：100%占空比 */

/* 2026-10-26 新增：就绪标志 + 语义状态。
 * 仿照 ec_drop_servo 的 fail-closed 设计 —— 气阀属于"可缺席"外设，
 * 缺席不应拖垮整机，但动作必须明确返回失败，而不是静默写一个没人执行的 CCR。 */
static bool    s_ready = false;
static uint8_t s_state = 0U;   /* 1 = 吸附中，0 = 释放 */

/**
 * @brief 初始化气动夹爪（启动PWM通道）
 * @note  TIM2已在main.c中初始化，这里只启动CH4通道并设为释放状态
 */
void ec_pneumatic_gripper_init(void)
{
    /* 初始状态：释放（0%占空比） */
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, PNEUMATIC_DUTY_OFF);

    /* 启动PWM输出；失败则保持 not ready，后续动作全部拒绝 */
    if (HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_4) != HAL_OK) {
        s_ready = false;
        s_state = 0U;
        return;
    }
    s_ready = true;
    s_state = 0U;
}

/**
 * @brief 初始化是否成功
 */
bool ec_pneumatic_gripper_is_ready(void)
{
    return s_ready;
}

/**
 * @brief 当前状态：1 = 吸附中，0 = 释放
 */
uint8_t ec_pneumatic_gripper_state(void)
{
    return s_state;
}

/**
 * @brief 气动夹爪张开（释放）
 */
void ec_pneumatic_gripper_open(void)
{
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, PNEUMATIC_DUTY_OFF);
    s_state = 0U;
}

/**
 * @brief 气动夹爪闭合（吸附）
 */
void ec_pneumatic_gripper_close(void)
{
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, PNEUMATIC_DUTY_ON);
    s_state = 1U;
}

/**
 * @brief 气动夹爪中位（气动阀不支持，调用open）
 */
void ec_pneumatic_gripper_neutral(void)
{
    ec_pneumatic_gripper_open();
}

/**
 * @brief 设置气动夹爪占空比
 * @param pulse_us 占空比值（0~2000，兼容旧接口）
 */
void ec_pneumatic_gripper_set_pulse(uint16_t pulse_us)
{
    __HAL_TIM_SET_COMPARE(&htim2, TIM_CHANNEL_4, (uint32_t)pulse_us);
}

/**
 * @brief 获取当前占空比值
 * @return 当前CCR值（0=释放, 2000=吸附）
 */
uint16_t ec_pneumatic_gripper_get_pulse(void)
{
    uint32_t ccr = __HAL_TIM_GET_COMPARE(&htim2, TIM_CHANNEL_4);
    return (uint16_t)ccr;
}
