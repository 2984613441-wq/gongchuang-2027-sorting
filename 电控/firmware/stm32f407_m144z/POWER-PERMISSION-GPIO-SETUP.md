# 电源许可 GPIO 接入指南

## 当前状态
**临时方案**：电源许可信号被强制假定为"存在"，以允许系统启动。  
**位置**：`App/Src/ec_board_stm32.c:80`

```c
/* No GPIO mapping: the fail-closed input blocks startup. */
```

---

## 硬件接线要求

### 信号定义
- **信号名称**：POWER_PERMISSION
- **电气特性**：**主动高电平**（HIGH = 有电源许可，LOW = 失电）
- **输入位**：`EC_INPUT_POWER_PERMISSION` (bit 9)
- **推荐GPIO**：任意可用数字输入（建议与其他安全信号同组）

### 推荐硬件配置
- **上拉电阻**：10kΩ（确保断线时默认为高电平）
- **滤波电容**：0.1µF（抑制干扰）
- **输入保护**：TVS二极管或限流电阻

---

## 启用真实GPIO采样（3步）

### 第1步：在 CubeMX 中配置 GPIO

1. 打开 `diankongv1.0.ioc`
2. 选择一个可用GPIO引脚（例如 `PE0`）
3. 配置为：
   - **Mode**: GPIO_Input
   - **GPIO Pull-up/Pull-down**: Pull-up
   - **User Label**: `POWER_PERMISSION`
4. 保存并重新生成代码

### 第2步：修改 `ec_board_stm32.c`

找到 `read_raw_inputs()` 函数（约第77行），**替换临时代码**：

```c
// ❌ 删除临时代码：
// raw |= EC_INPUT_POWER_PERMISSION;  /* Assume power present */

// ✅ 启用真实GPIO读取：
EC_READ_HIGH(EC_INPUT_POWER_PERMISSION, POWER_PERMISSION);
```

### 第3步：验证编译

```bash
# Keil 中 Rebuild
# 预期：0 Error, 0 Warning
```

---

## 失效保护逻辑

### 检测逻辑（已实现）

**位置**：`App/Src/ec_app.c:179-195`

```c
static bool power_permission_check_lost(uint16_t active_inputs)
{
    /* active_inputs中bit置位 = 低电平触发 = 许可丢失 */
    return (active_inputs & EC_INPUT_POWER_PERMISSION) != 0U;
}
```

### 触发行为

当电源许可信号变为 LOW 时：
1. **立即触发** `EC_EVENT_POWER_PERMISSION_LOST`
2. **停止所有运动**（调用 `ec_safety_port_stop_all()`）
3. **进入故障锁定状态** `EC_STATE_FAULT_LOCK`
4. **需要手动复位**（按START按钮重新启动）

### 输入滤波

- **去抖时间**：50ms（10位输入共用，配置在 `ec_inputs.c:53`）
- **目的**：防止电源毛刺误触发
- **代价**：检测延迟最多50ms

---

## 测试验证

### 单元测试（可在接线前验证逻辑）

```python
# 模拟电源许可丢失
inputs = 0x0000  # 所有输入为0，包括POWER_PERMISSION
active_mask = filter_inputs(inputs)
assert (active_mask & EC_INPUT_POWER_PERMISSION) != 0  # 应判定为失电
```

### 硬件测试（接线后）

1. **正常供电**：POWER_PERMISSION引脚接高电平 → 系统正常启动
2. **模拟断电**：运行中断开POWER_PERMISSION → 立即停止并锁定
3. **恢复测试**：重新接高电平并按START → 系统重新启动

---

## 常见问题

### Q: 接线后立即锁定怎么办？
**A**: 检查：
1. GPIO配置是否为Pull-up？
2. 信号源是否真的输出高电平（用万用表测量）？
3. 接线是否正确（信号线、地线）？

### Q: 能否改为低电平有效？
**A**: 可以，但需要修改两处：
1. `ec_board_stm32.c`: 改用 `EC_READ_LOW` 宏（需自行定义）
2. `ec_app.c:195`: 改为 `== 0U`（bit清零=失电）

### Q: 去抖时间50ms太长/太短？
**A**: 修改 `ec_inputs.c:53` 的 `EC_INPUT_DEBOUNCE_MS` 常量

---

## 相关文件

- `App/Inc/ec_inputs.h:15` - 信号位定义
- `App/Src/ec_board_stm32.c:77` - GPIO采样
- `App/Src/ec_inputs.c:53` - 去抖滤波器
- `App/Src/ec_app.c:179` - 失电检测逻辑
- `App/Src/ec_app.c:334` - 失电事件触发

---

**最后更新**：2026-01-XX  
**状态**：临时方案运行中，等待硬件接线
