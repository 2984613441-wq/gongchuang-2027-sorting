# XY联动插补 - 参数标定指南

## 目标
将PLACEHOLDER参数替换为实测值，确保插补功能安全可靠运行。

---

## 📋 待标定参数清单

| 参数 | 当前值 | 位置 | 优先级 |
|------|--------|------|--------|
| `EC_AXIS_STEPS_PER_MM_X` | 100 | `ec_axis_driver.h:29` | P0 |
| `EC_AXIS_STEPS_PER_MM_Y` | 100 | `ec_axis_driver.h:30` | P0 |
| `EC_AXIS_MOVE_FREQUENCY_HZ` | 500 | `ec_axis_driver.h:49` | P0 |
| `EC_AXIS_INTERP_FREQUENCY_HZ` | 500 | `ec_axis_driver.h:58` | P1 |

---

## 🔧 P0参数标定（必须完成）

### 1. Steps_per_mm（步距比）

**标定方法**：
```c
// 准备：
// 1. 在X/Y轴上贴一张纸，标记起点
// 2. 编写测试程序，移动100mm
// 3. 用卷尺测量实际位移

// 示例测试代码：
void calibrate_steps_per_mm(void) {
    // 移动X轴100mm（理论值：100mm × 100 steps/mm = 10000步）
    ec_step_port_start_counted(EC_AXIS_X, 500, 10000);
    
    // 等待完成后，用卷尺测量实际移动距离
    // 假设实际移动了95mm
    
    // 计算：实际steps_per_mm = 10000步 / 95mm ≈ 105.3
    // 取整：EC_AXIS_STEPS_PER_MM_X = 105
}
```

**计算公式**：
```
steps_per_mm = (发送步数) / (实际位移mm)
```

**注意事项**：
- 测量3次取平均值
- 检查X/Y两轴是否相同（如果传动比不同需分别标定）
- 检查A4988的MS1-MS2-MS3微步设置（1/16细分 vs 全步）

---

### 2. Move_frequency_hz（最大频率）

**标定方法**：
```c
// 逐步提升频率测试
void calibrate_max_frequency(void) {
    uint32_t test_frequencies[] = {500, 1000, 1500, 2000, 2500, 3000};
    
    for (int i = 0; i < 6; i++) {
        uint32_t freq = test_frequencies[i];
        
        // 移动100mm
        uint32_t steps = 100 * EC_AXIS_STEPS_PER_MM_X;
        ec_step_port_start_counted(EC_AXIS_X, freq, steps);
        
        // 等待完成后检查：
        // 1. 实际位移是否=100mm（丢步检测）
        // 2. 噪音/共振是否异常
        // 3. 电机/驱动温度是否<60°C
        
        // 如果出现丢步或过热，停止测试
        // 最高稳定频率 × 0.8 = 工作频率
    }
}
```

**判定标准**：
- ✅ 无丢步：实际位移 ≥ 理论位移 × 99%
- ✅ 无共振：噪音正常，无异常抖动
- ✅ 温度正常：电机/驱动 < 60°C

**推荐值**：
- NEMA17步进电机：通常支持2000-3000Hz
- 如果使用1/16微步：建议不超过2000Hz
- 工作频率 = 最高稳定频率 × 0.8

---

## 🎯 P1参数标定（插补专用）

### 3. Interp_frequency_hz（插补频率）

**标定原则**：
```c
// 如果X/Y传动比相同：
EC_AXIS_INTERP_FREQUENCY_HZ = EC_AXIS_MOVE_FREQUENCY_HZ;

// 如果X/Y传动比不同（例如X是皮带，Y是丝杠）：
EC_AXIS_INTERP_FREQUENCY_HZ = min(X最高频率, Y最高频率) × 0.8;
```

**测试代码**：
```c
void test_interp_diagonal(void) {
    // 从(0,0)移动到(100,100)，对角线
    ec_axis_pick_place_t program;
    ec_motion_plan_build_interp(&program, 1000, 1000);  // 100.0mm
    
    ec_axis_driver_start_pick_place(&program);
    
    // 完成后检查：
    // 1. 终点坐标误差 < 2mm
    // 2. 轨迹是直线（不是折线）
    // 3. 时间 ≈ √(100²+100²) / 速度
}
```

---

## 📊 性能对比测试

**测试场景**：HOME(-145,-145) → PICK(0,0) → PLACE(100,80)

```c
void benchmark_serial_vs_interp(void) {
    uint32_t serial_time, interp_time;
    
    // 串行模式
    ec_axis_pick_place_t serial_program;
    ec_motion_plan_build(&serial_program, 1000, 800);
    
    uint32_t start = HAL_GetTick();
    ec_axis_driver_start_pick_place(&serial_program);
    // 等待完成...
    serial_time = HAL_GetTick() - start;
    
    // 插补模式
    ec_axis_pick_place_t interp_program;
    ec_motion_plan_build_interp(&interp_program, 1000, 800);
    
    start = HAL_GetTick();
    ec_axis_driver_start_pick_place(&interp_program);
    // 等待完成...
    interp_time = HAL_GetTick() - start;
    
    // 报告
    printf("Serial: %lu ms\n", serial_time);
    printf("Interp: %lu ms\n", interp_time);
    printf("Saved:  %lu ms (%.0f%%)\n", 
           serial_time - interp_time,
           (float)(serial_time - interp_time) / serial_time * 100);
}
```

---

## ⚠️ 安全检查清单

在启用插补功能前，必须完成以下测试：

- [ ] **限位保护**：插补过程中触发X限位，Y轴也立即停止
- [ ] **限位保护**：插补过程中触发Y限位，X轴也立即停止
- [ ] **急停保护**：插补过程中按下急停，两轴立即停止
- [ ] **轨迹精度**：对角线终点误差 < 2mm
- [ ] **无丢步**：重复100次，每次终点位置一致
- [ ] **温度正常**：连续运行10分钟，电机温度 < 60°C
- [ ] **时间验证**：单件时间 < 15秒（含显示）

---

## 📝 标定记录模板

```markdown
## 标定记录 - 2026-XX-XX

### 硬件信息
- 电机型号：17HS4401
- 驱动器：A4988
- 微步设置：MS1=H, MS2=H, MS3=L (1/16细分)
- 传动方式：X轴皮带，Y轴丝杠

### 标定结果
| 参数 | 测试值1 | 测试值2 | 测试值3 | 平均值 | 最终值 |
|------|---------|---------|---------|--------|--------|
| X步距比 | 105 | 106 | 105 | 105.3 | 105 |
| Y步距比 | 205 | 204 | 205 | 204.7 | 205 |
| X最高频率 | 2000Hz OK | 2500Hz 丢步 | - | - | 1600Hz |
| Y最高频率 | 1500Hz OK | 2000Hz 共振 | - | - | 1200Hz |

### 插补频率
- 取min(1600, 1200) = 1200Hz

### 性能测试
- 串行模式：8.5秒/件
- 插补模式：6.2秒/件
- 节省时间：2.3秒 (27%)

### 备注
- Y轴丝杠传动比更大，频率较低
- 1200Hz工作稳定，无丢步
```

---

## 🚀 启用插补

标定完成后，修改代码：

```c
// ec_axis_driver.h
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(105)  // 实测值
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(205)  // 实测值
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(1600)  // 实测值
#define EC_AXIS_INTERP_FREQUENCY_HZ UINT32_C(1200)  // min(X,Y)

// ec_app.c或调用处
// 改用插补版本：
ec_motion_plan_build_interp(&program, place_x, place_y);
// 替代原来的：
// ec_motion_plan_build(&program, place_x, place_y);
```

编译、烧录、验证！
