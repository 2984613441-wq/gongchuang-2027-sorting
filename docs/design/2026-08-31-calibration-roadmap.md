# 智能分拣装置标定路线图（2026-08-31）

> # ⛔ 2026-09-28 标记：**本文数值已被后续实测推翻，勿引用**
> 由 `docs/交付/2026-09-23/交接总纲-20260923.md` §8 认定为「数值已被推翻、勿引用」，2026-09-28 复核确认并挂此横幅。
> 具体失实项（至少）：`:202,206` 的 `HOME=(−1450)` / `PICK=(0,0)` 与现状不符（现 HOME = (−95.0, −97.5)、PICK 每件不同）；
> `:314-317` 仍按 **100 steps/mm** 计算（现行 **80**）；5 步标定流程已被 09-19~09-23 的 `calib_joint.py` 流程取代。
> **需要现行标定流程请看**：`docs/交付/2026-09-23/交接总纲-20260923.md` §4.3。
> 本文仅作历史留档。

---

> 目标：5步渐进标定，每步可独立测试+回退，明天完成全部验证。
> 基线分支：`20260829-multinode-review`（当前HEAD）
> 标定分支：`calibration/step-X`（X=0~4）

---

## 📋 标定总览

| 步骤 | 分支名 | 测试内容 | 预计时间 | 修改文件 |
|---|---|---|---|---|
| **Step 0** | `calibration/step-0-baseline` | 单轴点动测试（方向+限位） | 15min | 无（只用现有demo） |
| **Step 1** | `calibration/step-1-servo` | Z轴舵机脉宽标定 | 30min | `ec_axis_driver.h` |
| **Step 2** | `calibration/step-2-coordinates` | 冻结HOME/PICK/落点坐标 | 20min | `ec_motion_plan.h` |
| **Step 3** | `calibration/step-3-frequency` | 步频标定（15秒预算验证） | 45min | `ec_axis_driver.h` |
| **Step 4** | `calibration/step-4-load-test` | 带载验证（丢步/温升） | 30min | 无（验证only） |

**总计**：~2.5小时（含记录时间）

---

## 🎯 Step 0: 单轴点动测试（方向+限位）

### 目标
- 确认X/Y方向约定（正方向=物理哪个方向）
- 验证六路限位开关可读
- 测量实际行程（mm）

### 使用现有工具
无需改代码，使用固件现有demo：
```c
// 已有功能：电控/firmware/stm32f407_m144z/App/Src/ec_step_test.c
ec_step_test_start(EC_AXIS_X, EC_DIRECTION_0, 1000, 500);  // X轴正向1000步
```

### 测试清单
```
1. 上电 → 串口连接 → 发送点动命令
2. X轴DIR0测试：
   ☐ 观察物理运动方向（记录：向左/向右/向前/向后）
   ☐ 触发X_HOME限位，记录限位电平（HIGH/LOW）
   ☐ 触发X_END限位，记录限位电平
   ☐ 测量实际行程：________ mm

3. Y轴DIR0测试：
   ☐ 观察物理运动方向（记录：向左/向右/向前/向后）
   ☐ 触发Y_HOME限位，记录限位电平
   ☐ 触发Y_END限位，记录限位电平
   ☐ 测量实际行程：________ mm

4. 填写结论：
   ☐ X正方向（DIR0）= ________（向左/右/前/后）
   ☐ Y正方向（DIR0）= ________
   ☐ X行程 = ________ mm，Y行程 = ________ mm
   ☐ 限位类型：常开/常闭，触发电平：HIGH/LOW
```

### 修改参数位置
如果DIR0不是期望的正方向，修改：
```c
// 文件：电控/firmware/stm32f407_m144z/App/Inc/ec_motion_plan.h
// Line 26-27

// 当前默认：
#define EC_MOTION_POSITIVE_X_DIR EC_DIRECTION_0
#define EC_MOTION_POSITIVE_Y_DIR EC_DIRECTION_0

// 如果X轴DIR0是负方向，改为：
#define EC_MOTION_POSITIVE_X_DIR EC_DIRECTION_1

// 如果Y轴DIR0是负方向，改为：
#define EC_MOTION_POSITIVE_Y_DIR EC_DIRECTION_1
```

### 输出记录文件
创建：`电控/calibration-logs/step0-axis-jog-test.txt`

---

## 🎯 Step 1: Z轴舵机脉宽标定

### 分支
```bash
git checkout -b calibration/step-1-servo
```

### 目标
- 确定Z轴舵机安全脉宽范围（升降+夹爪联动）
- 验证夹持可靠性、断电状态
- 冻结4个脉宽参数

### 修改参数位置
**唯一修改文件**：`电控/firmware/stm32f407_m144z/App/Inc/ec_axis_driver.h`

```c
// Line 33-39（当前占位值）

/* Gripper servo pulse widths + settle time (PLACEHOLDERS). */
#define EC_AXIS_GRIPPER_OPEN_US UINT16_C(1000)    // ← 修改这里
#define EC_AXIS_GRIPPER_CLOSE_US UINT16_C(1900)   // ← 修改这里
#define EC_AXIS_GRIPPER_SETTLE_MS UINT32_C(200)   // ← 修改这里

/* Z-axis lift servo pulse widths (PLACEHOLDERS, not calibrated). */
#define EC_AXIS_Z_UP_US UINT16_C(1000)            // ← 修改这里
#define EC_AXIS_Z_DOWN_US UINT16_C(1900)          // ← 修改这里
```

### 标定步骤
```
1. 渐进测试（每次±50us）：
   ☐ Z_DOWN起始值1000us → 观察下降幅度
   ☐ 增加到1050us/1100us.../直到完全下降 → 记录：________ us
   ☐ Z_UP起始值1900us → 观察上升幅度
   ☐ 减少到1850us/1800us.../直到完全上升 → 记录：________ us

2. 夹爪测试（联动验证）：
   ☐ GRIPPER_OPEN测试：下降时张开，记录脉宽：________ us
   ☐ GRIPPER_CLOSE测试：上升时闭合，记录脉宽：________ us
   ☐ 验证：下降=张开、上升=闭合（联动正确）

3. 夹持可靠性：
   ☐ 放置物料（cube） → Z下降+张开 → Z上升+夹持
   ☐ 保持3秒，物料不掉落 → 夹持力足够 ✓
   ☐ 移动到另一位置 → 物料不滑动 ✓

4. 断电状态：
   ☐ 舵机上电夹紧 → 断电 → 观察：保持夹紧/自然松开
   ☐ 记录：________

5. 稳定时间：
   ☐ 发送脉宽后到实际到位的延迟：________ ms
   ☐ 建议 SETTLE_MS = 实测延迟 + 50ms 余量
```

### 测试代码（已有）
使用现有舵机测试：
```c
// 电控/firmware/stm32f407_m144z/App/Src/ec_servo_test.c
ec_servo_test_set_pulse(EC_SERVO_Z, 1000);  // Z轴测试
```

### 修改示例
假设测试结果：
- Z完全下降 = 1200us
- Z完全上升 = 1800us
- 夹爪张开 = 1200us
- 夹爪闭合 = 1800us
- 稳定时间 = 180ms

修改为：
```c
#define EC_AXIS_GRIPPER_OPEN_US UINT16_C(1200)    // 张开（下降时）
#define EC_AXIS_GRIPPER_CLOSE_US UINT16_C(1800)   // 闭合（上升时）
#define EC_AXIS_GRIPPER_SETTLE_MS UINT32_C(230)   // 180ms + 50ms余量

#define EC_AXIS_Z_UP_US UINT16_C(1800)            // 上升
#define EC_AXIS_Z_DOWN_US UINT16_C(1200)          // 下降
```

### 提交
```bash
git add 电控/firmware/stm32f407_m144z/App/Inc/ec_axis_driver.h
git commit -m "标定Step1: Z轴舵机脉宽

实测脉宽：
- Z下降/张开: 1200us
- Z上升/闭合: 1800us
- 稳定时间: 230ms

验证通过：
- 夹持可靠（cube 3秒不掉）
- 联动正确（下降=张开，上升=闭合）
- 断电保持夹紧"
```

### 输出记录文件
创建：`电控/calibration-logs/step1-servo-calibration.txt`

---

## 🎯 Step 2: 冻结HOME/PICK/落点坐标

### 分支
```bash
git checkout -b calibration/step-2-coordinates
```

### 目标
- 确定装置中心原点物理位置
- 测量HOME坐标（休息位）
- 测量PICK坐标（取料圆心）
- 测量6个落点（BOX 1~6）坐标

### 修改参数位置
**唯一修改文件**：`电控/firmware/stm32f407_m144z/App/Inc/ec_motion_plan.h`

```c
// Line 35-41

/* Pick waypoint = fixed feed circle center. */
#define EC_MOTION_PICK_X_MM10 0          // ← 修改这里（单位：0.1mm）
#define EC_MOTION_PICK_Y_MM10 0          // ← 修改这里

/* Home (rest) waypoint in device-center frame. */
#define EC_MOTION_HOME_X_MM10 (-1450)    // ← 修改这里
#define EC_MOTION_HOME_Y_MM10 (-1450)    // ← 修改这里
```

### 测量步骤
```
1. 确定装置中心原点：
   ☐ 手动移动XY到工作区中心（目视/测量）
   ☐ 标记此位置为(0, 0)
   ☐ 用胶带/笔在底板标记原点

2. 测量HOME坐标（相对原点）：
   ☐ 移动到安全休息位（避开取料/落点区域）
   ☐ 测量X偏移：________ mm（左负右正）
   ☐ 测量Y偏移：________ mm（前负后正）
   ☐ 换算：X_MM10 = X_mm × 10，Y_MM10 = Y_mm × 10

3. 测量PICK坐标（取料圆心）：
   ☐ 放置取料盘，标记中心
   ☐ 测量X偏移：________ mm
   ☐ 测量Y偏移：________ mm
   ☐ 换算：X_MM10 = ________, Y_MM10 = ________

4. 测量6个落点（BOX 1~6）：
   ☐ 按赛题布局摆放6个储物盒
   ☐ 标记每个盒子中心点
   ☐ 逐个测量相对原点的坐标：

   BOX 1: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)
   BOX 2: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)
   BOX 3: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)
   BOX 4: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)
   BOX 5: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)
   BOX 6: X=______mm, Y=______mm → (X_MM10=______, Y_MM10=______)

5. 验证边界：
   ☐ 所有坐标 |X|, |Y| ≤ 145.0mm（±1450 in mm10）
   ☐ 如超出，调整布局或缩小工作区
```

### 修改示例
假设测量结果（示例）：
- HOME: X=-120mm, Y=-120mm
- PICK: X=0mm, Y=50mm
- BOX落点按树莓派`drop_table.py`分配

修改为：
```c
#define EC_MOTION_PICK_X_MM10 0          // 取料在原点X轴
#define EC_MOTION_PICK_Y_MM10 500        // Y方向+50mm

#define EC_MOTION_HOME_X_MM10 (-1200)    // X=-120mm
#define EC_MOTION_HOME_Y_MM10 (-1200)    // Y=-120mm
```

### 同步到树莓派落点表
**文件**：`电控/src/electrical_control/vision/drop_table.py`

```python
# Line 40-53（当前占位值）

_DROP_POINTS = {
    1: (500, 500),      # ← 改为实测BOX1坐标（单位：0.1mm）
    2: (500, -500),     # ← 改为实测BOX2
    3: (-500, 500),     # ← 改为实测BOX3
    4: (-500, -500),    # ← 改为实测BOX4
    5: (1000, 0),       # ← 改为实测BOX5
    6: (-1000, 0),      # ← 改为实测BOX6
}
```

### 提交
```bash
git add 电控/firmware/stm32f407_m144z/App/Inc/ec_motion_plan.h
git add 电控/src/electrical_control/vision/drop_table.py
git commit -m "标定Step2: 冻结HOME/PICK/落点坐标

实测坐标（装置中心为原点）：
- HOME: (-120, -120) mm
- PICK: (0, 50) mm
- BOX1~6: 见drop_table.py

边界验证：所有坐标 ≤ ±145mm ✓"
```

### 输出记录文件
创建：`电控/calibration-logs/step2-coordinates.txt`

---

## 🎯 Step 3: 步频标定（15秒预算验证）

### 分支
```bash
git checkout -b calibration/step-3-frequency
```

### 目标
- 确定安全最大步频（不丢步）
- 验证最坏路径满足15秒预算
- 冻结`STEPS_PER_MM`和`MOVE_FREQUENCY_HZ`

### 修改参数位置
**唯一修改文件**：`电控/firmware/stm32f407_m144z/App/Inc/ec_axis_driver.h`

```c
// Line 29-31

#define EC_AXIS_STEPS_PER_MM_X UINT32_C(100)  // ← 修改这里
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(100)  // ← 修改这里
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(500)  // ← 修改这里
```

### 标定步骤

#### 3.1 确定STEPS_PER_MM（传动比）
```
1. 查询机械参数：
   ☐ 传动方式：同步带/丝杠/齿条？
   ☐ 步进电机：1.8°/步（200步/圈）
   ☐ A4988微步设置：MS1=__, MS2=__, MS3=__
      全步=1, 1/2=2, 1/4=4, 1/8=8, 1/16=16
   ☐ 传动比（如：20齿带轮，2mm节距）

2. 理论计算：
   STEPS_PER_MM = (200 × 微步) / (齿数 × 节距)
   
   示例：1/16微步，20齿带轮，2mm节距
   = (200 × 16) / (20 × 2) = 80 steps/mm

3. 实测验证：
   ☐ 发送1000步 → 测量实际移动：________ mm
   ☐ 实测 STEPS_PER_MM = 1000 / 实际mm = ________
   ☐ 误差 < 5% → 使用实测值
```

#### 3.2 测试最大步频（渐进提升）
```
1. 起始步频：500Hz
   ☐ 单轴100mm移动（8000步@80steps/mm）
   ☐ 观察：平滑运动，无异响 → 通过

2. 提升到1000Hz：
   ☐ 重复100mm测试
   ☐ 到位后手动推动，验证无丢步 → 通过/失败

3. 继续提升（1500Hz, 2000Hz, 2500Hz...）：
   ☐ 每次提升500Hz，重复测试
   ☐ 直到出现：异响/振动/丢步/温升>60°C
   ☐ 记录最高通过步频：________ Hz

4. 安全步频 = 最高通过步频 × 0.8（留20%余量）
   ☐ 安全步频 = ________ Hz
```

#### 3.3 验证15秒预算
使用Step2冻结的坐标，计算最坏路径：

```
最坏路径：HOME → PICK → 最远落点 → HOME

假设：
- HOME: (-120, -120) mm
- PICK: (0, 50) mm
- 最远落点: BOX5 (100, 0) mm（示例）
- STEPS_PER_MM = 80
- 安全步频 = 2400 Hz

计算：
1. HOME → PICK:
   距离 = sqrt((0-(-120))^2 + (50-(-120))^2) = sqrt(14400+28900) = 208mm
   步数 = 208 × 80 = 16640步
   时间 = 16640 / 2400 = 6.93秒

2. PICK → BOX5:
   距离 = sqrt((100-0)^2 + (0-50)^2) = 112mm
   步数 = 112 × 80 = 8960步
   时间 = 8960 / 2400 = 3.73秒

3. BOX5 → HOME:
   距离 = sqrt((-120-100)^2 + (-120-0)^2) = 257mm
   步数 = 257 × 80 = 20560步
   时间 = 20560 / 2400 = 8.57秒

4. Z轴动作（4次，每次0.23秒）= 0.92秒
5. 显示余量 = 15 - (6.93+3.73+8.57+0.92) = ?秒

☐ 总时间 < 13秒（留2秒显示余量）→ 通过
☐ 如超时，降低步频或优化路径
```

### 修改示例
假设最终标定结果：
- 实测STEPS_PER_MM = 82
- 安全步频 = 2400Hz
- 15秒验证通过

修改为：
```c
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(82)
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(82)
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(2400)
```

### 提交
```bash
git add 电控/firmware/stm32f407_m144z/App/Inc/ec_axis_driver.h
git commit -m "标定Step3: 步频与传动比

实测参数：
- STEPS_PER_MM: 82 (1/16微步，20齿带轮)
- 安全步频: 2400Hz (最高3000Hz × 0.8)

15秒验证：
- 最坏路径: HOME→PICK→BOX5→HOME
- XY运动: 19.23秒 → 改进路径/提升步频
- 总预算: 20.15秒（含Z轴4次）→ 通过 ✓"
```

### 输出记录文件
创建：`电控/calibration-logs/step3-frequency-calibration.txt`

---

## 🎯 Step 4: 带载验证（丢步/温升）

### 分支
```bash
git checkout -b calibration/step-4-load-test
```

### 目标
- 验证带实际物料运行不丢步
- 检查电机/驱动器温升
- 确认参数可用于比赛

### 测试清单
```
1. 单件完整流程（×5次）：
   ☐ 放置物料（cube）到PICK位置
   ☐ 启动：HOME → PICK → 夹取 → BOX1 → 投放 → HOME
   ☐ 检查：物料准确投入BOX1，无偏移 ✓
   ☐ 检查：电机到位后手动推，无丢步 ✓

2. 连续运行测试（×20件）：
   ☐ 逐件投放到BOX1~6（每箱3-4件）
   ☐ 每5件记录电机温度：
      - 5件后：X电机__°C, Y电机__°C, 驱动器__°C
      - 10件后：__°C, __°C, __°C
      - 15件后：__°C, __°C, __°C
      - 20件后：__°C, __°C, __°C
   ☐ 温升判定：
      - <60°C → 优秀 ✓
      - 60-70°C → 可接受，建议加散热
      - >70°C → 降低步频或减小负载

3. 最坏路径压力测试（×10次）：
   ☐ 固定路径：HOME → PICK → 最远BOX → HOME
   ☐ 连续10次，每次记录耗时：
      1: __秒, 2: __秒, 3: __秒, 4: __秒, 5: __秒
      6: __秒, 7: __秒, 8: __秒, 9: __秒, 10: __秒
   ☐ 平均耗时：________ 秒
   ☐ 最长耗时：________ 秒 < 13秒 ✓

4. 极端物料测试：
   ☐ 最重物料（长方体）：夹持可靠 ✓
   ☐ 最轻物料（圆柱）：无滑动 ✓
   ☐ 最难形状（六棱柱）：投放准确 ✓

5. 断电恢复测试：
   ☐ 运行中急停 → 重新上电 → 回零 → 继续运行 ✓
```

### 如发现问题

#### 问题A：丢步
```
症状：到位后手动推，位置偏移
原因：步频过高/负载过大/机械卡滞
解决：
1. 降低步频（-200Hz）
2. 检查机械是否顺滑
3. 检查A4988电流设置
```

#### 问题B：温升过高
```
症状：电机>70°C
原因：步频高/连续运行/散热不足
解决：
1. 降低步频
2. 增加运行间隔
3. 加装散热片/风扇
```

#### 问题C：夹持不可靠
```
症状：物料掉落/滑动
原因：舵机力矩不足/脉宽不准
解决：
1. 调整GRIPPER_CLOSE_US（增加夹持力）
2. 增加SETTLE_MS（等待稳定）
3. 更换更大力矩舵机
```

### 无需改代码
此步骤只验证，不修改参数。

如需调整，回退到对应Step重新标定：
- 舵机问题 → 回退到Step1
- 步频问题 → 回退到Step3

### 提交（只记录测试结果）
```bash
# 创建测试报告（不修改代码）
git add 电控/calibration-logs/step4-load-test.txt
git commit -m "标定Step4: 带载验证完成

测试结果：
- 单件×5: 全部准确投放 ✓
- 连续×20: 无丢步，最高温度58°C ✓
- 最坏路径×10: 平均11.2秒，最长12.8秒 ✓
- 极端物料: 全部通过 ✓

结论：参数可用于比赛"
```

### 输出记录文件
创建：`电控/calibration-logs/step4-load-test.txt`

---

## 🔄 回退与合并策略

### 回退到某一步
```bash
# 回退到Step2（假设Step3有问题）
git checkout calibration/step-2-coordinates

# 重新标定Step3
git checkout -b calibration/step-3-frequency-v2
# ...修改参数...
```

### 合并最终版本
所有步骤通过后：
```bash
# 回到主工作分支
git checkout 20260829-multinode-review

# 合并最终标定结果（Step4）
git merge calibration/step-4-load-test --no-ff -m "合并完整标定: Step0~4全部通过

标定参数：
- 方向约定: X_DIR0=正向, Y_DIR0=正向
- Z舵机: 下降/张开=1200us, 上升/闭合=1800us
- 坐标: HOME(-120,-120), PICK(0,50), BOX1~6见落点表
- 传动比: 82 steps/mm
- 步频: 2400Hz
- 温升: 最高58°C，15秒预算通过

验证: 20件连续运行无丢步 ✓"
```

### 标记最终版本
```bash
git tag -a v1.0-calibrated -m "标定完成版本

所有参数实测验证通过，可用于比赛。

参数清单：
- ec_axis_driver.h: 步频2400Hz, 舵机1200/1800us
- ec_motion_plan.h: HOME/PICK/方向约定
- drop_table.py: 6个落点坐标

测试证据：电控/calibration-logs/"
```

---

## 📁 标定记录文件结构

完成后应有以下文件：
```
电控/
├── calibration-logs/
│   ├── step0-axis-jog-test.txt         # 单轴点动测试记录
│   ├── step1-servo-calibration.txt     # 舵机脉宽标定记录
│   ├── step2-coordinates.txt           # 坐标测量记录
│   ├── step3-frequency-calibration.txt # 步频标定记录
│   └── step4-load-test.txt             # 带载验证记录
```

每个文件包含：
- 测试日期/时间
- 测试人员
- 原始测量数据
- 修改前后参数对比
- 验证结果（通过/失败）

---

## 🎯 明天的执行计划

**上午（9:00-11:30）**：
- 9:00-9:15: Step0单轴点动（15min）
- 9:15-9:45: Step1舵机标定（30min）
- 9:45-10:05: Step2坐标测量（20min）
- 10:05-10:50: Step3步频标定（45min）
- 10:50-11:30: 修改参数 + 编译烧录（40min）

**下午（14:00-16:00）**：
- 14:00-14:30: Step4带载验证（30min）
- 14:30-15:00: 问题调整（如有）
- 15:00-15:30: 完整流程验证（20件连续）
- 15:30-16:00: 记录整理 + git提交

**预留**：16:00-17:00 应急调整时间

---

## 📋 所需工具/物料清单

1. **测量工具**：
   - 卷尺/游标卡尺（精度±1mm）
   - 红外测温仪（检查电机温升）
   - 胶带/记号笔（标记坐标）

2. **测试物料**：
   - 7种形状物料各2件（至少）
   - 6个储物盒
   - 取料盘

3. **软件工具**：
   - 串口调试助手
   - 计算器（坐标换算）
   - 秒表（计时验证）

4. **备用件**：
   - 备用舵机（DS3120MG）
   - 备用STM32（已烧录）

---

*创建日期：2026-08-31*
*基线版本：20260829-multinode-review*
*预计完成时间：2026-09-01 16:00*
