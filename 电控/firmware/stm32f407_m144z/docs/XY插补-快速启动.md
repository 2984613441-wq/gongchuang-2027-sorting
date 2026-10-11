# XY插补 - 5分钟快速启动

## 🎯 目标
用最快速度验证插补算法正确性，然后决定是否继续硬件集成。

---

## ⚡ Step 1：算法测试（2分钟）

在Linux/Mac/Windows任意环境：

```bash
cd 电控/firmware/stm32f407_m144z/tests

# 编译
gcc -Wall -I../App/Inc \
    test_ec_interp.c \
    ../App/Src/ec_interp.c \
    -o test_interp

# 运行
./test_interp
```

**预期输出**：
```
=== XY Interpolation Algorithm Tests ===

Test: 45° diagonal (0,0) -> (10,10)
Test: Shallow angle (0,0) -> (100,20)
Test: Steep angle (0,0) -> (20,100)
Test: Negative X (0,0) -> (-50,30)
Test: Negative Y (0,0) -> (30,-50)
Test: Both negative (10,10) -> (-20,-30)
Test: X-only (0,0) -> (50,0)
Test: Y-only (0,0) -> (0,50)
Test: Zero distance (5,5) -> (5,5)

=== Test Summary ===
Passed: 9/9
```

✅ 如果全部通过 → 继续  
❌ 如果有失败 → 报告问题

---

## 📝 Step 2：参数标定（1小时）

见`docs/XY插补参数标定指南.md`

**最低要求**：
1. 实测X/Y的steps_per_mm
2. 测试最高稳定频率

**输出**：
```c
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(105)  // 你的实测值
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(205)  // 你的实测值
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(1600)  // 你的实测值
```

---

## 🔧 Step 3：集成到固件（10分钟）

### 3.1 添加源文件到编译

编辑`CMakeLists.txt`或`Makefile`：

```cmake
set(APP_SOURCES
    App/Src/ec_app.c
    App/Src/ec_axis_driver.c
    App/Src/ec_interp.c              # 新增
    App/Src/ec_motion_plan.c
    App/Src/ec_motion_plan_interp.c  # 新增
    # ... 其他文件
)
```

### 3.2 修改调用代码

找到调用`ec_motion_plan_build()`的地方，改为：

```c
// 旧代码
ec_axis_pick_place_t program;
if (!ec_motion_plan_build(&program, place_x_mm10, place_y_mm10)) {
    return false;
}

// 新代码（插补模式）
ec_axis_pick_place_t program;
if (!ec_motion_plan_build_interp(&program, place_x_mm10, place_y_mm10)) {
    return false;
}
```

### 3.3 编译烧录

```bash
mkdir build && cd build
cmake ..
make
# 烧录...
```

---

## ✅ Step 4：验证（15分钟）

### 最小验证清单

- [ ] X轴单独移动100mm，实际位移=100mm ± 2mm
- [ ] Y轴单独移动100mm，实际位移=100mm ± 2mm
- [ ] XY同时移动对角线(100,100)，终点误差<3mm
- [ ] 触发X限位，Y同步停止
- [ ] 触发Y限位，X同步停止
- [ ] 按下急停，XY同步停止

### 性能对比测试

```c
// 在main或test函数中
void benchmark(void) {
    // 串行模式
    ec_axis_pick_place_t serial_prog;
    ec_motion_plan_build(&serial_prog, 1000, 800);
    
    uint32_t start = HAL_GetTick();
    ec_axis_driver_start_pick_place(&serial_prog);
    while (ec_axis_driver_state() != EC_AXIS_STATE_DONE) {
        ec_axis_driver_poll(HAL_GetTick(), get_inputs());
    }
    uint32_t serial_time = HAL_GetTick() - start;
    
    // 插补模式
    ec_axis_pick_place_t interp_prog;
    ec_motion_plan_build_interp(&interp_prog, 1000, 800);
    
    start = HAL_GetTick();
    ec_axis_driver_start_pick_place(&interp_prog);
    while (ec_axis_driver_state() != EC_AXIS_STATE_DONE) {
        ec_axis_driver_poll(HAL_GetTick(), get_inputs());
    }
    uint32_t interp_time = HAL_GetTick() - start;
    
    printf("Serial: %lu ms\n", serial_time);
    printf("Interp: %lu ms\n", interp_time);
    printf("Saved:  %lu ms (%.1f%%)\n", 
           serial_time - interp_time,
           100.0f * (serial_time - interp_time) / serial_time);
}
```

---

## 🚨 常见问题

### Q1：编译错误 `undefined reference to interp_init`

**原因**：`ec_interp.c`未加入编译  
**解决**：检查CMakeLists.txt或Makefile

### Q2：运行时卡死在插补状态

**原因**：`interp_step()`未被正确调用  
**解决**：检查`ec_axis_driver_poll()`中`EC_AXIS_STATE_XY_INTERP`分支

### Q3：轨迹不是直线，而是折线

**原因**：插补频率太低，或poll调用间隔太长  
**解决**：提高`EC_AXIS_INTERP_FREQUENCY_HZ`或缩短poll周期

### Q4：对角线终点偏差很大（>5mm）

**原因**：`EC_AXIS_STEPS_PER_MM_X/Y`未标定  
**解决**：重新标定steps_per_mm

### Q5：插补比串行还慢

**原因**：单步开销大（每步调用`start_counted(axis, freq, 1)`）  
**解决**：需要port层提供`pulse_once()`专用API（待优化）

---

## 📊 决策树：要不要继续？

```
算法测试通过？
├─ YES → 参数标定
│         ├─ 标定后<15秒？
│         │   ├─ YES → 🎉 不需要插补，结束
│         │   └─ NO  → 继续集成插补
│         └─ 插补后<15秒？
│               ├─ YES → ✅ 启用插补
│               └─ NO  → ⚠️ 需要其他优化（路径规划/硬件升级）
└─ NO  → 🐛 修复算法BUG
```

---

## 📞 需要帮助？

**文档索引**：
- 详细实施总结：`docs/XY插补实施总结.md`
- 参数标定指南：`docs/XY插补参数标定指南.md`
- 算法测试代码：`tests/test_ec_interp.c`

**关键代码位置**：
- 算法：`App/Src/ec_interp.c:interp_step()`
- 状态机：`App/Src/ec_axis_driver.c:ec_axis_driver_poll()` 第156-182行
- 生成器：`App/Src/ec_motion_plan_interp.c`

启动愉快！🚀
