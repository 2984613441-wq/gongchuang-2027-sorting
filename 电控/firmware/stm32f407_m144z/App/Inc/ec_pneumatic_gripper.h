/* 气动夹爪测试代码 - 头文件
 * 文件位置：电控/firmware/stm32f407_m144z/App/Inc/ec_pneumatic_gripper.h
 */

#ifndef EC_PNEUMATIC_GRIPPER_H
#define EC_PNEUMATIC_GRIPPER_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief 初始化气动夹爪（启动PWM）
 * @note 在main函数中调用，MX_TIM2_Init()之后
 */
void ec_pneumatic_gripper_init(void);

/**
 * @brief 初始化是否成功（PWM 通道已启动）
 * @return true = 可用；false = 初始化失败，所有动作都应被拒绝
 * @note  2026-10-26 新增。仿照 ec_drop_servo 的 fail-closed 设计：
 *        外设可缺席（没接气阀），但缺席时动作必须明确返回失败，
 *        而不是静默下发一个没人执行的 CCR。
 */
bool ec_pneumatic_gripper_is_ready(void);

/**
 * @brief 当前状态
 * @return 1 = 吸附中（阀通电），0 = 释放（阀断电）
 */
uint8_t ec_pneumatic_gripper_state(void);

/**
 * @brief 设置气动夹爪脉宽（微秒）
 * @param pulse_us 脉宽，范围1000-2000us（根据实际调整）
 */
void ec_pneumatic_gripper_set_pulse(uint16_t pulse_us);

/**
 * @brief 气动夹爪张开
 */
void ec_pneumatic_gripper_open(void);

/**
 * @brief 气动夹爪闭合
 */
void ec_pneumatic_gripper_close(void);

/**
 * @brief 气动夹爪中位（如果支持）
 */
void ec_pneumatic_gripper_neutral(void);

/**
 * @brief 获取当前脉宽（微秒）
 * @return 当前PWM脉宽
 */
uint16_t ec_pneumatic_gripper_get_pulse(void);

#endif /* EC_PNEUMATIC_GRIPPER_H */
