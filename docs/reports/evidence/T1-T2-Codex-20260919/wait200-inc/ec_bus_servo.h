#ifndef EC_BUS_SERVO_H
#define EC_BUS_SERVO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* 幻尔（Hiwonder）总线舵机协议 —— HX-06L / 自适应夹爪。
 *
 * 帧格式（10 字节）：
 *   [0] 0x55        帧头
 *   [1] 0x55        帧头
 *   [2] ID          舵机 ID（默认 1，0xFE 为广播）
 *   [3] LEN         自 ID 起被校验覆盖的字节数（MOVE_TIME_WRITE 时 = 7）
 *   [4] CMD         命令字（MOVE_TIME_WRITE = 1）
 *   [5] 位置 低字节
 *   [6] 位置 高字节
 *   [7] 时间 低字节
 *   [8] 时间 高字节
 *   [9] 校验 = ~(frame[2..8] 累加) & 0xFF
 *
 * 波特率 115200。物理层为半双工单总线（SIG 单线收发）；
 * 本项目只发不收（不回读），故无需方向控制脚。
 *
 * 参考实现：
 *   幻尔 51 例程   BusServoCtrl.c   （帧构造与校验）
 *   幻尔 树莓派例程 BusServoCmd.py  （命令字全表）
 *   资料包路径：第四期选题咨询会/自适应机械爪/02 程序示例/ */

#define EC_BUS_SERVO_HEADER           UINT8_C(0x55)
#define EC_BUS_SERVO_ID_DEFAULT       UINT8_C(1)
#define EC_BUS_SERVO_ID_BROADCAST     UINT8_C(0xFE)

#define EC_BUS_SERVO_CMD_MOVE_TIME_WRITE  UINT8_C(1)

/* 协议量程：0-1000 对应 0°-240° */
#define EC_BUS_SERVO_POS_MAX          UINT16_C(1000)
#define EC_BUS_SERVO_TIME_MAX_MS      UINT16_C(30000)

/* 自适应夹爪位置（出厂角度限位 96°-156°，换算即 400-650）。
 * 机械语义：开 = 升，闭 = 降，单自由度。 */
#define EC_GRIP_POS_OPEN   UINT16_C(400)  /* 张开最大 = 升（出厂下限，勿小于 400） */
#define EC_GRIP_POS_MID    UINT16_C(500)  /* 中位 */
#define EC_GRIP_POS_CLOSE  UINT16_C(640)  /* 闭合 = 降（可按夹取物大小 ±50 微调） */

/* MOVE_TIME_WRITE 帧总长（= LEN + 3 = 10）。 */
#define EC_BUS_SERVO_MOVE_FRAME_LEN   10U

/* 计算校验：覆盖 frame[2] 至 frame[len-2]。len < 4 时返回 0。 */
uint8_t ec_bus_servo_checksum(const uint8_t *frame, size_t len);

/* 构造一条 MOVE_TIME_WRITE 帧。成功返回写入的字节数（10），
 * 参数越界或缓冲区不足返回 0（不写任何字节）。 */
size_t ec_bus_servo_build_move(uint8_t *out, size_t out_len, uint8_t id,
                               uint16_t position, uint16_t time_ms);

#endif
