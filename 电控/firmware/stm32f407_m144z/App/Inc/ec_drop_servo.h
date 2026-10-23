#ifndef EC_DROP_SERVO_H
#define EC_DROP_SERVO_H

#include <stdbool.h>
#include <stdint.h>

/* ============================================================================
 * 落料门舵机 —— PE5 / TIM9_CH1 / 50 Hz
 *
 * 【型号已确定】MG996R（用户 2026-10-22 确认：就是原来挡板用的那款）
 *
 * 脉宽实测依据（docs/省赛-待办-20260928.md:95 原文）：
 *   "MG996R 位置舵机，量程 ≈270°（实测：线0=1500µs、线1=845µs、90°≈655µs）"
 *   ⇒ 中位 1500µs，每 90° = 655µs，故 ±90° = 845µs / 2155µs
 *
 * ⚠️ 方向未验证：845 与 2155 哪个是"放行"、哪个是"挡住"，
 *    取决于舵机摇臂的机械安装方向。**接线后必须用 DROP POS 实测确认**：
 *      DROP POS 845   → 看门往哪边摆
 *      DROP POS 2155  → 看门往哪边摆
 *    若实测相反，只需交换下面 OPEN_US 与 CLOSE_US 两个值（各一行）。
 *
 * ⚠️ 上电默认 MID(1500µs)：两个极限之间的中位，不偏向任何一侧，
 *    避免未知安装方向下上电即把门顶到机械端点。接线后应改成实测确认的
 *    "安全侧"（通常是 CLOSE，即物块掉不下去那一侧）。
 * ========================================================================== */

#define EC_DROP_SERVO_MID_US      UINT16_C(1500)  /* 中位 / 上电默认 */

/* ±90° 摆动（MG996R: 1500 ∓ 655）。
 * TODO(接线后实测): 若安装方向相反，交换这两行即可。 */
#define EC_DROP_SERVO_OPEN_US     UINT16_C(845)   /* 待实测确认：放行（物块可落入转盘） */
#define EC_DROP_SERVO_CLOSE_US    UINT16_C(2155)  /* 待实测确认：挡住（物块停在门上） */

/* 安全范围：留出 MG996R 量程余量，避免发到机械端点导致持续堵转烧舵机 */
#define EC_DROP_SERVO_MIN_US      UINT16_C(700)
#define EC_DROP_SERVO_MAX_US      UINT16_C(2300)

/* 动作后等待到位：MG996R 空载 90° 约 0.20~0.26s（@5~6V），400ms 约 1.5~2 倍余量 */
#define EC_DROP_SERVO_SETTLE_MS   UINT32_C(400)

bool ec_drop_servo_init(void);
bool ec_drop_servo_set_us(uint16_t pulse_us);
bool ec_drop_servo_open(void);
bool ec_drop_servo_close(void);
bool ec_drop_servo_mid(void);
bool ec_drop_servo_is_ready(void);
uint16_t ec_drop_servo_current_us(void);
void ec_drop_servo_stop(void);

#endif
