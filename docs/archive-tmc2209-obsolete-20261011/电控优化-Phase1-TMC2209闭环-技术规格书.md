# Phase 1：TMC2209 闭环基础设施 —— 技术规格书 v1.0

> **目标**：解决"丢步无人知道" —— 实现堵转检测、丢步告警、无传感器回零
> **风险等级**：L4（硬件改造 + 固件新增 UART）
> **前置条件**：Phase 0 完成（168 MHz 已烧录验证）
> **预计工时**：硬件 0.5 天 + 固件开发 3 天 + 调试 2 天 = **5.5 天**

---

## 1. 技术对比（A4988 vs TMC2209）

| 维度 | A4988 | TMC2209 | 备注 |
|---|---|---|---|
| **接口兼容性** | STEP/DIR/EN | ✅ **完全一样** | 直接插上，无需改线 |
| **驱动电流** | 最大 2A/相 | 最大 2.8A/相（峰值） | TMC2209 更强 |
| **微步** | 1/16 | 1/256（插值） | TMC2209 更细腻 |
| **堵转检测** | ❌ 无 | ✅ **StallGuard** | 实时检测 |
| **丢步检测** | ❌ 无 | ✅ 通过堵转间接 | — |
| **无传感器回零** | ❌ 无 | ✅ 支持 | 撞端点时堵转 |
| **串口诊断** | ❌ 无 | ✅ UART | 读写寄存器 |
| **静音** | 噪音大 | ✅ StealthChop2 | 低速几乎无声 |
| **价格** | ~¥8 | ~¥15 | 价差可接受 |
| **Vref 设置** | 电位器 | UART 写寄存器 | TMC2209 可软件调 |

---

## 2. 硬件改造清单

### 2.1 器件采购

| 项 | 型号 | 数量 | 单价 | 小计 | 备注 |
|---|---|---|---|---|---|
| **TMC2209 驱动板** | 带散热片版本 | **2** | ¥15 | ¥30 | X/Y 各一个 |
| **杜邦线** | 母对母 2.54mm | 若干 | — | — | UART 接线用 |

### 2.2 引脚分配（STM32 侧）

| 信号 | STM32 引脚 | 复用功能 | 当前状态 | 说明 |
|---|---|---|---|---|
| **STEP_X** | PC6 | TIM8_CH1 | ✅ 已用 | **不动** |
| **DIR_X** | PA7 | GPIO | ✅ 已用 | **不动** |
| **ENABLE_X** | PA5 | GPIO | ✅ 已用 | **不动**（低有效） |
| **STEP_Y** | PB6 | TIM4_CH1 | ✅ 已用 | **不动** |
| **DIR_Y** | PC7 | GPIO | ✅ 已用 | **不动** |
| **ENABLE_Y** | PD7 | GPIO | ✅ 已用 | **不动** |
| **UART_TX** | **PA9** | USART1_TX | ✅ **空闲** | ⭐ 新增（发送配置） |
| **UART_RX** | **PA10** | USART1_RX | ✅ **空闲** | ⭐ 新增（读取状态） |

### 2.3 TMC2209 侧引脚

| 引脚 | 功能 | 接到 |
|---|---|---|
| **STEP** | 步进脉冲输入 | STM32 PC6（X）/ PB6（Y）|
| **DIR** | 方向输入 | STM32 PA7（X）/ PC7（Y）|
| **EN** | 使能输入（低有效）| STM32 PA5（X）/ PD7（Y）|
| **UART** | 单线半双工 | STM32 PA9/PA10（USART1）|
| **VIO** | 逻辑电源 | 3.3V |
| **GND** | 地 | GND |
| **VM** | 电机电源 | 12V（与电池共用）|

### 2.4 地址设置（UART 多设备）

TMC2209 通过 **MS1/MS2** 引脚设置 UART 地址（0~3）：

| 驱动 | MS1 | MS2 | 地址 |
|---|---|---|---|
| **X 轴** | GND | GND | **0** |
| **Y 轴** | VIO | GND | **1** |

---

## 3. 固件架构设计

### 3.1 模块职责

```
ec_tmc2209.c/.h (新增)
    ├── UART 初始化（USART1，115200，单线半双工）
    ├── 寄存器读写（WriteRegister / ReadRegister）
    ├── 初始化配置（电流、微步、StealthChop）
    ├── StallGuard 查询（SGTHRS、SG_RESULT）
    └── 诊断接口（读 GSTAT、DRV_STATUS）
         ↓
ec_board_stm32.c (修改)
    ├── 初始化时调用 `tmc2209_init()`
    ├── `ec_step_port_start_counted()` 前查询 StallGuard
    └── 堵转时停止运动 + 上报
         ↓
ec_app.c (修改)
    ├── 新增响应字 `STALL_DETECTED <axis> <sg_value>`
    └── 堵转后进入安全态
```

### 3.2 关键寄存器（TMC2209）

| 寄存器 | 地址 | 功能 | 初始值 |
|---|---|---|---|
| **GCONF** | 0x00 | 全局配置 | 使能 StealthChop + UART |
| **IHOLD_IRUN** | 0x10 | 电流设置 | IRUN=20（1.4A RMS） |
| **TPOWERDOWN** | 0x11 | 待机延时 | 20（2s 后进待机） |
| **CHOPCONF** | 0x6C | 斩波配置 | 默认 |
| **COOLCONF** | 0x6D | CoolStep 配置 | 关闭（静态电流） |
| **SGTHRS** | 0x40 | StallGuard 阈值 | **64**（初始，需调优） |
| **SG_RESULT** | 0x41 | StallGuard 结果（只读）| 读取判断堵转 |
| **DRV_STATUS** | 0x6F | 驱动状态（只读）| 错误标志 |

### 3.3 UART 协议（TMC2209）

**帧格式**（8 字节）：
```
[Sync(0x05)] [Slave Addr] [Register Addr] [Data 32bit MSB first] [CRC8]
```

**CRC8 多项式**：`0x07`（x^8 + x^2 + x + 1）

**示例**：写 IHOLD_IRUN = 0x00140A14（IHOLD=10, IRUN=20）
```
05 00 90 00 14 0A 14 [CRC]
```

---

## 4. 实现清单（文件级）

### 4.1 新增文件

| 文件 | 行数估算 | 职责 |
|---|---|---|
| `App/Inc/ec_tmc2209.h` | 80 | 数据结构、寄存器定义、函数声明 |
| `App/Src/ec_tmc2209.c` | 250 | UART 读写、StallGuard 查询、初始化 |

### 4.2 修改文件

| 文件 | 改动行数 | 改动点 |
|---|---|---|
| `Core/Src/main.c` | +15 | USART1 初始化（PA9/PA10） |
| `App/Src/ec_board_stm32.c` | +30 | 集成 StallGuard 查询 |
| `App/Src/ec_app.c` | +20 | 新增 `STALL_DETECTED` 响应字 |

---

## 5. 代码框架（伪代码）

### 5.1 `ec_tmc2209.h`

```c
#ifndef EC_TMC2209_H
#define EC_TMC2209_H

#include <stdint.h>
#include <stdbool.h>

// TMC2209 寄存器地址
#define TMC2209_REG_GCONF       0x00
#define TMC2209_REG_IHOLD_IRUN  0x10
#define TMC2209_REG_SGTHRS      0x40
#define TMC2209_REG_SG_RESULT   0x41
#define TMC2209_REG_DRV_STATUS  0x6F

// 驱动地址（对应 X/Y 轴）
typedef enum {
    TMC2209_ADDR_X = 0,
    TMC2209_ADDR_Y = 1
} tmc2209_addr_t;

// 初始化（在 main() 中调用）
void tmc2209_init(void);

// 写寄存器
bool tmc2209_write_reg(tmc2209_addr_t addr, uint8_t reg, uint32_t value);

// 读寄存器
bool tmc2209_read_reg(tmc2209_addr_t addr, uint8_t reg, uint32_t *value);

// 设置电流（RMS，单位：mA）
bool tmc2209_set_current(tmc2209_addr_t addr, uint16_t irun_ma, uint16_t ihold_ma);

// 设置 StallGuard 阈值（0~255，值越大越灵敏）
bool tmc2209_set_sg_threshold(tmc2209_addr_t addr, uint8_t threshold);

// 读取 StallGuard 结果（0~1023，值越小越接近堵转）
bool tmc2209_read_sg_result(tmc2209_addr_t addr, uint16_t *sg_result);

// 检测堵转（返回 true = 堵转）
bool tmc2209_is_stalled(tmc2209_addr_t addr);

#endif
```

### 5.2 `ec_tmc2209.c`（核心函数）

```c
#include "ec_tmc2209.h"
#include "main.h"  // UART 句柄

extern UART_HandleTypeDef huart1;

// CRC8 计算
static uint8_t calc_crc8(uint8_t *data, uint8_t len) {
    uint8_t crc = 0;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x80) crc = (crc << 1) ^ 0x07;
            else crc <<= 1;
        }
    }
    return crc;
}

// 写寄存器
bool tmc2209_write_reg(tmc2209_addr_t addr, uint8_t reg, uint32_t value) {
    uint8_t frame[8];
    frame[0] = 0x05;              // Sync
    frame[1] = addr;              // Slave address
    frame[2] = 0x80 | reg;        // Write flag + register
    frame[3] = (value >> 24) & 0xFF;
    frame[4] = (value >> 16) & 0xFF;
    frame[5] = (value >> 8) & 0xFF;
    frame[6] = value & 0xFF;
    frame[7] = calc_crc8(frame, 7);
    
    HAL_StatusTypeDef status = HAL_UART_Transmit(&huart1, frame, 8, 100);
    return (status == HAL_OK);
}

// 读寄存器
bool tmc2209_read_reg(tmc2209_addr_t addr, uint8_t reg, uint32_t *value) {
    uint8_t tx_frame[4], rx_frame[8];
    tx_frame[0] = 0x05;
    tx_frame[1] = addr;
    tx_frame[2] = reg;  // Read flag = 0
    tx_frame[3] = calc_crc8(tx_frame, 3);
    
    // 发送读请求
    if (HAL_UART_Transmit(&huart1, tx_frame, 4, 100) != HAL_OK)
        return false;
    
    // 接收 8 字节响应
    if (HAL_UART_Receive(&huart1, rx_frame, 8, 100) != HAL_OK)
        return false;
    
    // 校验 CRC
    if (rx_frame[7] != calc_crc8(rx_frame, 7))
        return false;
    
    *value = ((uint32_t)rx_frame[3] << 24) |
             ((uint32_t)rx_frame[4] << 16) |
             ((uint32_t)rx_frame[5] << 8) |
             rx_frame[6];
    return true;
}

// 初始化
void tmc2209_init(void) {
    // X 轴（地址 0）
    tmc2209_write_reg(TMC2209_ADDR_X, TMC2209_REG_GCONF, 0x00000001);  // Enable UART
    tmc2209_set_current(TMC2209_ADDR_X, 1400, 500);  // IRUN=1.4A, IHOLD=0.5A
    tmc2209_set_sg_threshold(TMC2209_ADDR_X, 64);    // 初始阈值
    
    // Y 轴（地址 1）
    tmc2209_write_reg(TMC2209_ADDR_Y, TMC2209_REG_GCONF, 0x00000001);
    tmc2209_set_current(TMC2209_ADDR_Y, 1400, 500);
    tmc2209_set_sg_threshold(TMC2209_ADDR_Y, 64);
}

// 检测堵转
bool tmc2209_is_stalled(tmc2209_addr_t addr) {
    uint16_t sg_result;
    if (!tmc2209_read_sg_result(addr, &sg_result))
        return false;
    
    // SG_RESULT < 阈值 = 堵转（阈值需调优）
    return (sg_result < 50);
}
```

### 5.3 集成到 `ec_board_stm32.c`

```c
#include "ec_tmc2209.h"

// 在运动开始前检查
TIM_HandleTypeDef *ec_step_port_start_counted(/* ... */) {
    // 检查堵转
    if (axis == EC_AXIS_X && tmc2209_is_stalled(TMC2209_ADDR_X)) {
        // 上报堵转（通过 ec_app）
        return NULL;
    }
    if (axis == EC_AXIS_Y && tmc2209_is_stalled(TMC2209_ADDR_Y)) {
        return NULL;
    }
    
    // 原有逻辑...
}
```

---

## 6. 调试与调优

### 6.1 StallGuard 阈值调优

| 阈值 | 效果 | 适用场景 |
|---|---|---|
| **0~30** | 不敏感，只在明显堵转时触发 | 误报多时降低 |
| **50~80** | 中等敏感（推荐起点）| 初始值 |
| **100~150** | 高敏感，轻微阻力也触发 | 精确检测 |
| **>200** | 极敏感，可能误报 | 调试用 |

**调优流程**：
1. 从 **64** 开始
2. 空载运行 10 次 `pi_square.py`，记录误报次数
3. 人为堵转（手抓滑台），记录检测延迟
4. 调整阈值，重复 2-3

### 6.2 电流设置

**公式**：`I_RMS = (CS + 1) / 32 * V_FS / (R_sense + 0.02Ω) * 1/√2`

**简化**（假设 R_sense = 0.11Ω）：
- **IRUN = 20** → 约 1.4A RMS（2.0A 峰值）
- **IHOLD = 10** → 约 0.7A RMS（待机）

### 6.3 诊断命令（新增）

| 命令 | 功能 | 响应 |
|---|---|---|
| `TMC_READ X SG_RESULT` | 读 X 轴 StallGuard 值 | `SG_RESULT 512` |
| `TMC_READ Y DRV_STATUS` | 读 Y 轴驱动状态 | `DRV_STATUS 0x00000000` |
| `TMC_SET X SGTHRS 80` | 设置 X 轴阈值 | `OK` |

---

## 7. 验证矩阵

| # | 测试 | 判据 | 工具 |
|---|---|---|---|
| 1 | **UART 通信** | 能读写寄存器，CRC 无错 | `TMC_READ` 命令 |
| 2 | **电流设置** | 电机运行平稳，不过热 | 温度枪测量 |
| 3 | **空载无误报** | `pi_square.py` × 10，零堵转告警 | 日志 |
| 4 | **人为堵转检测** | 手抓滑台，≤200ms 内检测到 | 秒表 |
| 5 | **负载堵转检测** | 顶到机械端点，检测到 | 实机 |
| 6 | **无传感器回零** | X/Y 撞端点后回退 5mm | `pi_home.py` |
| 7 | **24 件热浸** | 零误报，零漏报 | 实机 |

---

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| UART 调试困难（CRC 错误）| 中 | 高 | 用示波器验证波形 |
| StallGuard 误报多 | 中 | 中 | 调低阈值（如 30）|
| 电流设置不当（过热/扭矩不足）| 中 | 高 | 从保守值（1.0A）开始 |
| 与 USART2 冲突 | 低 | 高 | ✅ PA9/PA10 已确认空闲 |
| 硬件兼容性（板子不同）| 低 | 高 | 买带散热片的正规板 |

---

## 9. 成本与时间

| 项 | 成本 | 时间 |
|---|---|---|
| **硬件采购** | ¥30 | 3 天到货 |
| **硬件焊接/接线** | — | 0.5 天 |
| **固件开发** | — | 3 天 |
| **调试调优** | — | 2 天 |
| **验证测试** | — | 1 天 |
| **总计** | **¥30** | **6.5 天** |

---

## 10. Phase 1 完成标志

- ✅ TMC2209 UART 通信正常（能读写寄存器）
- ✅ 空载运行 `pi_square.py` × 10，零堵转误报
- ✅ 人为堵转检测延迟 ≤200ms
- ✅ 实机一轮（5 件），零漏报
- ✅ 电机温度 ≤50°C
- ✅ 无传感器回零成功率 ≥95%

**达成后进入 Phase 2**（性能提升）。

---

**制定人**：Claude（电控优化）｜ **日期**：2026-10-11 ｜ **版本**：v1.0 ｜ **依据**：TMC2209 数据手册 + STM32 引脚空闲确认
