/* 气动夹爪测试代码 - 头文件
 * 文件位置：电控/firmware/stm32f407_m144z/App/Inc/ec_pneumatic_gripper.h
 */

#ifndef EC_PNEUMATIC_GRIPPER_H
#define EC_PNEUMATIC_GRIPPER_H

#include <stdint.h>

/**
 * @brief 初始化气动夹爪（启动PWM）
 * @note 在main函数中调用，MX_TIM2_Init()之后
 */
void ec_pneumatic_gripper_init(void);

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
