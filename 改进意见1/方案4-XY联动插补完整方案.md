# 问题4：XY轴联动插补 - 完整实施方案

## 📋 问题本质

将X→Y的串行运动改为XY同时运动的斜线轨迹，通过插补算法缩短路径时间。

## 🎯 核心收益

- **运动时间缩短30-50%**
- 从"X先动→Y再动"改为"XY同时斜线运动"
- 关键提升：单件时间从6-8s降至4-5s

---

## 🔧 推荐方案：Bresenham直线插补

### 核心思路

采用Bresenham算法实现直线插补：
- 输入：起点(x0, y0)、终点(x1, y1)
- 输出：步进序列，每步决定X轴或Y轴动还是XY同时动
- 特点：整数运算，无浮点误差，适合单片机

### 算法示例

```
起点(0,0) → 终点(10,6)

串行方案（原有）：
  X: 0→10（10步）
  Y: 0→6（6步）
  总时间：16步

插补方案（新）：
  步进序列：XY XY XY XY XY XY X X X X
  总时间：10步（X的最大行程）
  时间缩短：37.5%
```

---

## 🏗️ 实施步骤

### Step 1: STM32底层插补模块（8h）

**文件位置**：`电控/firmware/stm32f407_m144z/src/interpolation.c`

```c
#ifndef INTERPOLATION_H
#define INTERPOLATION_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    INTERP_AXIS_NONE = 0,
    INTERP_AXIS_X = 1,
    INTERP_AXIS_Y = 2,
    INTERP_AXIS_BOTH = 3
} interp_axis_t;

typedef struct {
    int32_t x0, y0;        // 起点
    int32_t x1, y1;        // 终点
    int32_t x_current;     // 当前X位置
    int32_t y_current;     // 当前Y位置
    int32_t dx, dy;        // 总位移
    int32_t sx, sy;        // 方向（±1）
    int32_t error;         // Bresenham误差累积
    bool finished;         // 是否完成
} interp_state_t;

// 初始化插补状态
void interp_init(interp_state_t *state, 
                 int32_t x0, int32_t y0, 
                 int32_t x1, int32_t y1);

// 单步插补（返回本步应动的轴）
interp_axis_t interp_step(interp_state_t *state);

// 检查是否完成
bool interp_is_finished(const interp_state_t *state);

#endif // INTERPOLATION_H
```

**实现文件**：

```c
#include "interpolation.h"
#include <stdlib.h>

void interp_init(interp_state_t *state, 
                 int32_t x0, int32_t y0, 
                 int32_t x1, int32_t y1) {
    state->x0 = x0;
    state->y0 = y0;
    state->x1 = x1;
    state->y1 = y1;
    state->x_current = x0;
    state->y_current = y0;
    
    state->dx = abs(x1 - x0);
    state->dy = abs(y1 - y0);
    
    state->sx = (x0 < x1) ? 1 : -1;
    state->sy = (y0 < y1) ? 1 : -1;
    
    state->error = state->dx - state->dy;
    state->finished = false;
}

interp_axis_t interp_step(interp_state_t *state) {
    if (state->finished) {
        return INTERP_AXIS_NONE;
    }
    
    // 检查是否到达目标
    if (state->x_current == state->x1 && state->y_current == state->y1) {
        state->finished = true;
        return INTERP_AXIS_NONE;
    }
    
    // Bresenham算法
    int32_t e2 = 2 * state->error;
    interp_axis_t axis_to_move = INTERP_AXIS_NONE;
    
    if (e2 > -state->dy && state->x_current != state->x1) {
        state->error -= state->dy;
        state->x_current += state->sx;
        axis_to_move |= INTERP_AXIS_X;
    }
    
    if (e2 < state->dx && state->y_current != state->y1) {
        state->error += state->dx;
        state->y_current += state->sy;
        axis_to_move |= INTERP_AXIS_Y;
    }
    
    return axis_to_move;
}

bool interp_is_finished(const interp_state_t *state) {
    return state->finished;
}
```

### Step 2: 运动状态机改造（6h）

**文件位置**：`电控/firmware/stm32f407_m144z/src/motion_controller.c`

**原有状态机**：
```c
typedef enum {
    MOTION_STATE_IDLE,
    MOTION_STATE_X_MOVING,
    MOTION_STATE_Y_MOVING,
    MOTION_STATE_Z_MOVING,
    MOTION_STATE_DONE
} motion_state_t;
```

**新状态机**：
```c
typedef enum {
    MOTION_STATE_IDLE,
    MOTION_STATE_XY_INTERP,    // 新增：XY插补状态
    MOTION_STATE_Z_MOVING,
    MOTION_STATE_DONE
} motion_state_t;

typedef struct {
    motion_state_t state;
    interp_state_t interp;     // 插补状态
    uint32_t step_timer_hz;    // 步进频率
    uint32_t next_step_tick;   // 下一步时间戳
} motion_controller_t;
```

**状态机逻辑**：

```c
void motion_start_xy(int32_t target_x, int32_t target_y) {
    // 获取当前位置
    int32_t current_x = axis_get_position(AXIS_X);
    int32_t current_y = axis_get_position(AXIS_Y);
    
    // 初始化插补
    interp_init(&g_motion.interp, current_x, current_y, target_x, target_y);
    
    // 设置步进频率（取两轴中较快的）
    g_motion.step_timer_hz = 1000;  // 1kHz基准
    g_motion.next_step_tick = HAL_GetTick();
    
    // 进入插补状态
    g_motion.state = MOTION_STATE_XY_INTERP;
    
    // 使能两轴
    axis_enable(AXIS_X);
    axis_enable(AXIS_Y);
}

void motion_poll(void) {
    if (g_motion.state != MOTION_STATE_XY_INTERP) {
        return;
    }
    
    uint32_t now = HAL_GetTick();
    
    // 检查是否到达步进时间
    if (now < g_motion.next_step_tick) {
        return;
    }
    
    // 执行一步插补
    interp_axis_t axis = interp_step(&g_motion.interp);
    
    if (axis == INTERP_AXIS_NONE) {
        // 插补完成
        g_motion.state = MOTION_STATE_DONE;
        return;
    }
    
    // 根据插补结果驱动电机
    if (axis & INTERP_AXIS_X) {
        axis_step_once(AXIS_X);
    }
    
    if (axis & INTERP_AXIS_Y) {
        axis_step_once(AXIS_Y);
    }
    
    // 计算下一步时间
    g_motion.next_step_tick = now + (1000 / g_motion.step_timer_hz);
}
```

### Step 3: 限位保护升级（2h）

**文件位置**：`电控/firmware/stm32f407_m144z/src/limit_check.c`

**原有逻辑**：单轴限位检查

**新逻辑**：XY同时运动时，两轴都需检查

```c
bool motion_check_limit_xy(void) {
    // 检查X轴限位
    if (axis_limit_triggered(AXIS_X)) {
        // X轴触发限位，停止XY
        axis_stop(AXIS_X);
        axis_stop(AXIS_Y);
        return false;
    }
    
    // 检查Y轴限位
    if (axis_limit_triggered(AXIS_Y)) {
        // Y轴触发限位，停止XY
        axis_stop(AXIS_X);
        axis_stop(AXIS_Y);
        return false;
    }
    
    return true;
}

// 在motion_poll中调用
void motion_poll(void) {
    if (g_motion.state != MOTION_STATE_XY_INTERP) {
        return;
    }
    
    // 限位检查
    if (!motion_check_limit_xy()) {
        g_motion.state = MOTION_STATE_ERROR;
        return;
    }
    
    // ... 后续插补逻辑
}
```

### Step 4: 速度协调（4h）

**问题**：XY轴速度不同时，如何协调？

**方案**：归一化速度

```c
void motion_start_xy_with_speed(int32_t target_x, int32_t target_y, 
                                uint32_t speed_mm_s) {
    // 计算路径长度
    int32_t dx = target_x - current_x;
    int32_t dy = target_y - current_y;
    float path_length = sqrtf(dx*dx + dy*dy);  // mm
    
    // 计算总时间
    float total_time_s = path_length / speed_mm_s;
    
    // 计算步进频率（假设1步=0.1mm）
    uint32_t total_steps = (uint32_t)(path_length / 0.1f);
    uint32_t step_hz = (uint32_t)(total_steps / total_time_s);
    
    g_motion.step_timer_hz = step_hz;
    
    // 初始化插补
    interp_init(&g_motion.interp, current_x, current_y, target_x, target_y);
    g_motion.state = MOTION_STATE_XY_INTERP;
}
```

### Step 5: 测试验证（6h）

#### 测试1：直线精度测试
```c
// 测试用例1：45度斜线
motion_start_xy(0, 0, 100, 100);
// 期望：X和Y同时到达，误差<1mm

// 测试用例2：浅角度斜线
motion_start_xy(0, 0, 100, 20);
// 期望：X动5步，Y动1步

// 测试用例3：陡角度斜线
motion_start_xy(0, 0, 20, 100);
// 期望：Y动5步，X动1步
```

#### 测试2：限位响应测试
```c
// X轴触发限位
motion_start_xy(0, 0, 200, 100);  // X超限
// 期望：X触限时，XY都停止
```

#### 测试3：速度一致性测试
```c
// 不同路径，相同速度
motion_start_xy_with_speed(0, 0, 100, 0, 50);    // 100mm, 50mm/s
motion_start_xy_with_speed(0, 0, 70, 70, 50);    // 99mm, 50mm/s
// 期望：两次运动时间接近（误差<5%）
```

---

## 📊 性能对比

| 场景 | 串行时间 | 插补时间 | 提升 |
|------|---------|---------|------|
| (0,0)→(100,100) | 20s | 10s | 50% |
| (0,0)→(100,50) | 15s | 10s | 33% |
| (0,0)→(50,100) | 15s | 10s | 33% |
| **平均提升** | - | - | **40%** |

---

## ⏱️ 实施时间估算

| 任务 | 时间 | 优先级 |
|------|------|--------|
| STM32插补模块 | 8h | 高 ⭐⭐⭐ |
| 运动状态机改造 | 6h | 高 ⭐⭐⭐ |
| 限位保护升级 | 2h | 高 ⭐⭐⭐ |
| 速度协调 | 4h | 中 ⭐⭐ |
| 测试验证 | 6h | 高 ⭐⭐⭐ |
| **总计** | **26小时** | |

**建议实施顺序**：
1. Day 1-2：插补模块 + 状态机改造
2. Day 3：限位保护 + 基础测试
3. Day 4：速度协调 + 完整验证
4. Day 5：稳定性测试 + Bug修复

---

## 🚨 风险与缓解

**风险1**：插补算法BUG导致路径偏差
- 缓解：单元测试覆盖所有角度（0°/45°/90°）

**风险2**：XY同时动时，限位响应不及时
- 缓解：高优先级中断，1ms内响应

**风险3**：速度协调不当导致抖动
- 缓解：步进频率平滑过渡，避免突变

**风险4**：重复定位精度下降
- 缓解：插补后回原点校准，验证误差<0.5mm

---

## 📁 相关文件清单

**需要创建**：
- `电控/firmware/stm32f407_m144z/src/interpolation.c`
- `电控/firmware/stm32f407_m144z/src/interpolation.h`

**需要修改**：
- `电控/firmware/stm32f407_m144z/src/motion_controller.c`
- `电控/firmware/stm32f407_m144z/src/limit_check.c`

**需要测试**：
- 直线精度测试（10个不同角度）
- 限位响应测试（XY各方向）
- 速度一致性测试
- 重复定位精度测试（100次循环）
- 连续运动稳定性测试（1小时）

---

## 🔄 与树莓派集成

**树莓派端不需要改动**，因为：
- 树莓派发送的是目标坐标 `(x_target, y_target)`
- STM32内部决定用串行还是插补
- 对上层透明

**可选优化**：树莓派增加"运动模式"参数
```python
# 树莓派端
task = {
    'x_target': 100,
    'y_target': 50,
    'motion_mode': 'INTERPOLATION'  # or 'SEQUENTIAL'
}
```

---

## 📈 后续优化方向

1. **圆弧插补**：支持圆弧路径（更平滑）
2. **S曲线加减速**：避免急停急起
3. **路径预规划**：批量路径一次规划
4. **动态速度调整**：根据角度自适应速度
