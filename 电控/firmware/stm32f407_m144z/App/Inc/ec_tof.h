/**
 * @file    ec_tof.h
 * @brief   TinyF / MINIF(DVP0501C1) 激光测距模组驱动（STM32 UART4）
 *
 * 硬件
 * ----
 *   ToF VCC(5V) ── 5V
 *   ToF RXD     ── STM32 PC10 (UART4_TX)
 *   ToF TXD     ── STM32 PC11 (UART4_RX)
 *   ToF GND     ── GND
 *   串口：115200 8N1
 *
 * 协议（2026-10-17 查官方手册确认，**ASCII 文本，不是二进制帧**）
 * ----------------------------------------------------------------
 *   帧结构： 0x20(空格) + 距离(1~5位ASCII数字) + 0x2C 0x20(", ") + 置信度(1~2位) + 0x0A('\n')
 *   示例：   20 33 32 37 2C 20 36 31 0A   ==  " 327, 61\n"
 *            ⇒ 距离 327 mm，置信度 61
 *
 *   距离有效范围：20 ~ 4500 mm
 *   置信度：      0 ~ 62（越大越可信）
 *   默认输出帧率：30 Hz
 *
 * ⚠️ 曾经的 `docs/树莓派ToF转盘接线指南-20261011.md` 写的是
 *    `AA 55 <距离高> <距离低> <校验>` 二进制帧 —— **那是错的**，按此实现收不到数据。
 */

#ifndef EC_TOF_H
#define EC_TOF_H

#include <stdbool.h>
#include <stdint.h>

/* 只有真机构建才需要 HAL 类型（UART_HandleTypeDef）。
 * 主机测试（tests/ 下的 CMake 目标）不定义 USE_HAL_DRIVER，也不链接 HAL，
 * 且 tests/host_stubs/stm32f4xx_hal.h 只提供 HAL_GetTick()
 * ⇒ 在这里按 USE_HAL_DRIVER 分流，保证同一份头文件两边都能编。 */
#if defined(USE_HAL_DRIVER)
#include "stm32f4xx_hal.h"
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define EC_TOF_DIST_MIN_MM   20U     /**< 有效距离下限 */
#define EC_TOF_DIST_MAX_MM   4500U   /**< 有效距离上限 */
/* 置信度上限。
 * 🔴 2026-10-18 实测更正：原值 62 是照早期读数（conf 33~50）定的，
 *    但当天 TOFRAW 抓到原始帧为 " 188, 100\n" —— **置信度实际输出 0~100**，
 *    于是每一帧都被 "conf > 62" 的范围校验拒绝，表现为
 *      errors 狂涨 / frames 不动 / age_ms 一直增大（看着像没数据）。
 *    改为 100 后可接受全量程。若日后 ToF 换型，先发 TOFRAW 确认量程。 */
#define EC_TOF_CONF_MAX      100U    /**< 置信度上限（0~100 百分比量程） */
#define EC_TOF_STALE_MS      500U    /**< 超过此时长没新帧则视为失效 */

/* 单行解析缓冲长度。最长正常帧 " 4500, 62\n" ≈ 11 字符，留余量给异常长帧。
 * 2026-10-18：从 ec_tof.c 上移到本头文件，因为 ec_diag.c 的 TOFRAW 命令
 * 需要一个与 ec_tof.c 内部缓冲同长的临时数组来接收「最近被拒行」。 */
#define EC_TOF_LINE_MAX      16U

/** 初始化：清状态并启动 UART4 单字节中断接收。须在 MX_UART4_Init() 之后调用。 */
void ec_tof_init(void);

/** 查询最新一帧。返回 true 表示数据新鲜（age <= EC_TOF_STALE_MS）。
 *  任一输出指针可为 NULL。 */
bool ec_tof_latest(uint16_t *dist_mm, uint8_t *conf, uint32_t *age_ms, uint32_t now_ms);

/** 是否曾经收到过有效帧。 */
bool ec_tof_have_frame(void);

/** 累计有效帧数 / 累计错误（校验失败、超范围、溢出）。 */
uint32_t ec_tof_frames(void);
uint32_t ec_tof_errors(void);

/** 诊断用：中断里累计收到的**原始字节数**（不做任何解析）。
 *  若 raw_bytes > 0 但 frames = 0 ⇒ 字节到了但协议/波特率不对。
 *  若 raw_bytes = 0 ⇒ 物理层真的一个电平跳变都没有。 */
uint32_t ec_tof_raw_bytes(void);

/** 诊断用：UART4 的 HAL 错误回调次数（ORE/FE/NE/PE）。 */
uint32_t ec_tof_uart_errors(void);

/* 2026-10-18 新增：原始字节环形缓冲（看 ToF 到底在发什么）。
 * 起因：现场出现 errors 狂涨、frames 不动、age_ms 一直增大 ⇒ 每一帧都被
 *       范围校验或格式校验丢弃，而旧代码丢弃时不保留现场，无法定案。
 *       本缓冲把最近收到的原始字节原样留存，供 TOFRAW 命令以 hex 打印。 */
#define EC_TOF_RAW_RING 64U
/** 取出最近收到的原始字节（按时间顺序，末尾是最新的）。返回实际写出字节数，
 *  不会超过 min(max, EC_TOF_RAW_RING)。 */
uint8_t ec_tof_raw_ring(uint8_t *out, uint8_t max);

/** 诊断用：最近一条被拒绝的行及其拒绝原因码。
 *  原因码：1=找不到逗号 2=距离解析失败 3=置信度解析失败
 *          4=超出范围 5=行超长
 *  line 为被拒的原始行（以 '\0' 结尾，最多 EC_TOF_LINE_MAX-1 字节）。 */
uint8_t ec_tof_last_reject(char *line, uint8_t max);

/** 诊断用：在 UART4 上发送一段固定测试数据（"TOFLOOP\n"）。
 *  用法：把 PC10 与 PC11 用杜邦线短接后执行，再读 TOF：
 *    raw 增加  ⇒ PC10/PC11 引脚与 UART4 收发链路都正常，问题在 ToF 一侧
 *    raw 不变  ⇒ 引脚没引出/接错/PC11 断路，属板级问题
 *  ⚠️ 短接测试时请先断开 ToF，否则两个 TX 会对推。 */
void ec_tof_send_test(void);

/** 以下两个由 main.c 的 HAL UART 回调转发（仅 UART4 时生效）。
 *  主机测试不编译 ec_tof.c，也不链接 HAL ⇒ 只在真机构建里声明。 */
#if defined(USE_HAL_DRIVER)
void ec_tof_uart_rx_cplt(UART_HandleTypeDef *huart);
void ec_tof_uart_error(UART_HandleTypeDef *huart);
#endif

#ifdef __cplusplus
}
#endif

#endif /* EC_TOF_H */
