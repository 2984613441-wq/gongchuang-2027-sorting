#ifndef EC_Z_SERVO_H
#define EC_Z_SERVO_H

#include <stdbool.h>
#include <stdint.h>

/* ============================================================================
 * Z 轴舵机 —— PB0 / TIM3_CH3 / 50 Hz（2026-11-01 改造新增）
 *
 * 背景：原来 Z 与夹爪是**同一个舵机**（LDX-335MG，PB10/TIM2_CH3）机械联动。
 *       用户 2026-11-01 改硬件：Z 单独用一个舵机（原来挡板舵机那款），
 *       只负责**夹爪升降**；夹爪仍是原来的夹爪舵机；托盘落料槽仍用
 *       PE5/TIM9_CH1（见 ec_drop_servo.h）。
 *
 * 通道选择：用户明确"Z 轴舵机不用管是哪个挡板口，直接选一个"⇒ 选
 *           **PB0 / TIM3_CH3**（TIM3 已按 50 Hz、1 µs 分辨率初始化，
 *           MSP 里 PB0->TIM3_CH3 的 AF2 也已配好，见 stm32f4xx_hal_msp.c:212-220）。
 *
 * ⚠️ 脉宽上下限**目前是占位值**：MG996R 标称 1500 中位、±90°≈845/2155 µs，
 *    但 Z 实际需要多少行程取决于机械安装。接线后必须用台架命令实测：
 *        ZPOS 845 / ZPOS 1500 / ZPOS 2155      （看杆往哪边走、行程够不够）
 *    实测确认后，把下面 UP/DOWN 两个值改成实测值即可，其它代码不用动。
 *
 * ⚠️ 上电默认 MID(1500)：不偏向任何一侧，避免未知安装方向下上电即顶到机械端点。
 *    接线验证后建议改成"安全侧"（通常是 UP，夹爪停在高位不压台面）。
 * ========================================================================== */

#define EC_Z_SERVO_MID_US      UINT16_C(1500)  /* 中位 / 上电默认 */

/* 待实测：抬起 / 下降（现在都填中位，等于"不动"，避免未标定就乱走） */
#define EC_Z_SERVO_UP_US       UINT16_C(1500)  /* TODO(接线后实测) */
#define EC_Z_SERVO_DOWN_US     UINT16_C(1500)  /* TODO(接线后实测) */

/* 安全范围：留舵机量程余量，避免发到机械端点持续堵转烧舵机 */
#define EC_Z_SERVO_MIN_US      UINT16_C(700)
#define EC_Z_SERVO_MAX_US      UINT16_C(2300)

/* 动作后等待到位：MG996R 空载 90° 约 0.20~0.26s，取 400ms 作 1.5~2 倍余量 */
#define EC_Z_SERVO_SETTLE_MS   UINT32_C(400)

bool ec_z_servo_init(void);
bool ec_z_servo_set_us(uint16_t pulse_us);
bool ec_z_servo_up(void);
bool ec_z_servo_down(void);
bool ec_z_servo_mid(void);
bool ec_z_servo_is_ready(void);
uint16_t ec_z_servo_current_us(void);
void ec_z_servo_stop(void);

#endif
