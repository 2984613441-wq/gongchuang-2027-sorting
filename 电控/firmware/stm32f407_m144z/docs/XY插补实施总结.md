# XY轴联动插补 - 实施总结

**实施日期**：2026-09-09  
**状态**：代码完成，待参数标定和硬件验证

---

## 📦 交付物清单

### 核心模块（4个）

| 文件 | 行数 | 作用 | 状态 |
|------|------|------|------|
| `App/Src/ec_interp.c` | 63 | Bresenham插补算法 | ✅ 完成 |
| `App/Inc/ec_interp.h` | 67 | 插补接口定义 | ✅ 完成 |
| `App/Src/ec_axis_driver.c` | +80 | 状态机扩展（新增XY_INTERP状态） | ✅ 完成 |
| `App/Inc/ec_axis_driver.h` | +40 | 新增状态/枚举/参数注释 | ✅ 完成 |
| `App/Src/ec_motion_plan_interp.c` | 108 | 插补版8步程序生成器 | ✅ 完成 |
| `App/Inc/ec_motion_plan.h` | +15 | 新增build_interp接口 | ✅ 完成 |

### 测试与文档

| 文件 | 作用 | 状态 |
|------|------|------|
| `tests/test_ec_interp.c` | 单元测试（9个测试用例） | ✅ 完成 |
| `tests/Makefile_interp_test` | Host编译脚本 | ✅ 完成 |
| `docs/XY插补参数标定指南.md` | 参数标定SOP | ✅ 完成 |
| `docs/XY插补实施总结.md` | 本文件 | ✅ 完成 |

---

## 🎯 核心设计决策

### 1. 架构选择：最小侵入式

**决策**：在现有axis_driver基础上新增`EC_AXIS_STATE_XY_INTERP`状态，不破坏原有串行逻辑。

**理由**：
- ✅ 向后兼容：保留`ec_motion_plan_build()`串行模式
- ✅ 风险隔离：插补失败可快速回退到串行模式
- ✅ 测试独立：新增测试用例不影响现有功能

**实现**：
```c
// 状态机扩展
typedef enum {
    EC_AXIS_STATE_IDLE,
    EC_AXIS_STATE_MOVING,       // 原有单轴串行
    EC_AXIS_STATE_XY_INTERP,    // 新增联动插补
    EC_AXIS_STATE_GRIPPING,
    ...
} ec_axis_state_t;
```

---

### 2. 参数化设计：所有硬编码改为宏

**位置**：`ec_axis_driver.h:25-58`

**改动**：
```c
// 旧版（硬编码）
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(100)
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(500)

// 新版（参数化+标定指南）
/* [PLACEHOLDER - 待实测标定]
 *   实测方法：移动100mm，记录实际步数，steps_per_mm = 实际步数 / 100
 *   当前100是理论值，未经过实物验证
 */
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(100)

/* [PLACEHOLDER - 待实测标定]
 *   实测方法：逐步提升频率（500Hz → 1000Hz → 2000Hz），观察丢步/共振/温度
 *   取最高稳定频率的80%作为工作频率
 *   当前500Hz极度保守，NEMA17通常可达2000Hz+
 */
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(500)

/* XY interpolation frequency (Hz). 
 * [PLACEHOLDER - 待实测标定]
 *   建议值：min(X轴最高频率, Y轴最高频率) × 0.8
 */
#define EC_AXIS_INTERP_FREQUENCY_HZ EC_AXIS_MOVE_FREQUENCY_HZ
```

---

### 3. 算法选择：Bresenham直线插补

**理由**：
- ✅ 纯整数运算，无浮点开销
- ✅ 实时性好，每步决策<10条指令
- ✅ 精度足够：误差≤1步（对于mm级运动可忽略）

**时间复杂度**：O(max(dx, dy))

**空间复杂度**：O(1)

---

### 4. 接口设计：双模式并存

**用户选择**：
```c
// 串行模式（原有，兼容）
ec_motion_plan_build(&program, place_x_mm10, place_y_mm10);

// 插补模式（新增）
ec_motion_plan_build_interp(&program, place_x_mm10, place_y_mm10);
```

**优势**：
- 开发阶段可A/B对比测试
- 标定阶段可快速切换验证
- 生产版本可根据实测结果选择最优模式

---

## ⚠️ 已知限制与待办事项

### 当前限制

1. **坐标系假设**：插补起点固定为(0,0)相对坐标
   - 原因：`start_step()`中硬编码`interp_init(&state, 0, 0, ...)`
   - 影响：只能用于完整轨迹，不能中途插补
   - 解决：需要从port层获取当前绝对位置（待port API扩展）

2. **单步脉冲开销**：插补poll中调用`ec_step_port_start_counted(axis, freq, 1)`
   - 原因：复用现有counted API，每步都重新配置PWM
   - 影响：实际频率可能低于`EC_AXIS_INTERP_FREQUENCY_HZ`
   - 解决：需要port层提供`ec_step_port_pulse_once(axis)`专用API

3. **参数未标定**：当前所有参数为PLACEHOLDER
   - 100 steps/mm：理论值
   - 500 Hz：极度保守值
   - 影响：无法评估实际性能收益

### 待办事项（按优先级）

| 优先级 | 任务 | 负责人 | 预计时间 |
|--------|------|--------|----------|
| P0 | 标定steps_per_mm（X/Y） | 机械组 | 1h |
| P0 | 标定max_frequency_hz | 电控组 | 2h |
| P0 | 单元测试（host） | 电控组 | 0.5h |
| P1 | 集成测试（STM32实机） | 电控组 | 2h |
| P1 | 限位保护测试 | 电控组 | 1h |
| P1 | 性能对比测试（串行 vs 插补） | 电控组 | 1h |
| P2 | Port层优化（单步API） | 电控组 | 3h |
| P2 | 坐标系改进（支持绝对坐标） | 电控组 | 2h |

---

## 📊 预期收益分析

### 理论收益（基于当前PLACEHOLDER参数）

**假设**：
- Steps_per_mm = 100（未标定）
- Frequency = 500 Hz（保守）
- 典型轨迹：HOME(-145,-145) → PICK(0,0) → PLACE(100,80)

**时间对比**：
```
串行模式：
  HOME→PICK: (145+145)×100÷500 = 58秒
  PICK→PLACE: (100+80)×100÷500 = 36秒
  PLACE→HOME: (45+65)×100÷500 = 22秒
  总计：116秒

插补模式：
  HOME→PICK: √(145²+145²)×100÷500 = 41秒
  PICK→PLACE: √(100²+80²)×100÷500 = 26秒
  PLACE→HOME: √(45²+65²)×100÷500 = 16秒
  总计：83秒

节省：33秒（28%）
```

### 🚨 关键发现

**赛规红线**：15秒/件（含运动+显示+通信）

**当前状态**：
- 串行模式：116秒 ❌ **超标8倍**
- 插补模式：83秒 ❌ **仍超标5倍**

**结论**：**插补不是当务之急，参数标定才是！**

### 真正的优化路径

1. **P0：参数标定**（预期10倍提升）
   - 实测steps_per_mm（可能只有20-40，不是100）
   - 提升频率到2000Hz（4倍提升）
   - **预期：116秒 → 11.6秒**

2. **P1：路径优化**（预期20%提升）
   - 储物盒布局优化，减少运动距离
   - 就近投放算法

3. **P2：插补优化**（额外28%提升）
   - 在P0/P1基础上，从11.6秒 → 8.4秒
   - 此时才有意义！

---

## 🔍 验证计划

### 阶段1：算法验证（Host测试）

```bash
cd tests
make -f Makefile_interp_test
./test_ec_interp
```

**预期输出**：
```
=== XY Interpolation Algorithm Tests ===

Test: 45° diagonal (0,0) -> (10,10)
Test: Shallow angle (0,0) -> (100,20)
...

=== Test Summary ===
Passed: 9/9
```

### 阶段2：参数标定（实机）

见`docs/XY插补参数标定指南.md`

### 阶段3：集成测试（STM32）

1. 编译固件（添加`ec_interp.c`到CMakeLists.txt）
2. 烧录
3. 串口监控
4. 执行benchmark测试

### 阶段4：安全验证

- [ ] X限位触发，Y同步停止
- [ ] Y限位触发，X同步停止
- [ ] 急停触发，XY同步停止
- [ ] 对角线精度 < 2mm
- [ ] 重复性测试100次

---

## 📝 使用指南

### 启用插补（标定完成后）

**Step 1**：修改`ec_axis_driver.h`参数

```c
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(105)  // 实测值
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(205)  // 实测值
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(1600)
#define EC_AXIS_INTERP_FREQUENCY_HZ UINT32_C(1200)
```

**Step 2**：修改调用代码

```c
// 旧代码（串行）
ec_axis_pick_place_t program;
ec_motion_plan_build(&program, place_x_mm10, place_y_mm10);

// 新代码（插补）
ec_axis_pick_place_t program;
ec_motion_plan_build_interp(&program, place_x_mm10, place_y_mm10);

// 其余代码不变
ec_axis_driver_start_pick_place(&program);
```

**Step 3**：编译测试

```bash
# 添加到CMakeLists.txt
set(APP_SOURCES
    App/Src/ec_interp.c
    App/Src/ec_motion_plan_interp.c
    # ... 其他文件
)

# 编译
mkdir build && cd build
cmake ..
make
```

### 回退串行模式

只需将`ec_motion_plan_build_interp()`改回`ec_motion_plan_build()`即可。

---

## 🎓 经验总结

### 做对了的事情

1. ✅ **先分析必要性**：发现参数未标定才是真正瓶颈
2. ✅ **参数化设计**：留空位置，等待实测
3. ✅ **最小侵入**：不破坏现有架构
4. ✅ **向后兼容**：保留串行模式作为fallback
5. ✅ **文档先行**：标定指南写在代码之前

### 避免的陷阱

1. ❌ **盲目优化**：如果直接实施插补，节省33秒但总时间仍83秒，收益为负
2. ❌ **硬编码参数**：如果把100/500写死，后期标定需要大量改动
3. ❌ **推倒重来**：如果删除串行模式，测试/回退成本巨大

### 对未来的建议

**给你们团队**：
1. 立即标定steps_per_mm和max_frequency（2-3小时）
2. 如果标定后仍慢，再考虑启用插补
3. 如果标定后已经满足15秒红线，插补可以不做

**给下一届**：
1. 硬件参数永远先实测，再写代码
2. 预留参数位置，不要硬编码
3. 复杂优化前，先做收益分析

---

## 📞 联系与支持

**代码位置**：`电控/firmware/stm32f407_m144z/`

**关键文件**：
- 算法核心：`App/Src/ec_interp.c`
- 状态机：`App/Src/ec_axis_driver.c:poll()`
- 测试：`tests/test_ec_interp.c`
- 标定指南：`docs/XY插补参数标定指南.md`

**问题反馈**：见项目README

---

**实施完成日期**：2026-09-09  
**下一步行动**：参数标定（见标定指南）
