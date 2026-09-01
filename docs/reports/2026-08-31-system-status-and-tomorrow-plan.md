# 智能分拣装置完整状态报告（2026-08-31 22:00）

---

## 📊 系统状态总览

### ✅ 已完成模块（可运行/测试通过）

| 模块 | 状态 | 测试覆盖 | 备注 |
|------|------|---------|------|
| **三设备通信协议** | ✅ 冻结 | 210+58测试通过 | USART2主，ACK/NACK完整 |
| **树莓派调度链** | ✅ 完成 | Fake串口闭环通过 | 部署包ready |
| **STM32状态机** | ✅ 完成 | C逻辑85/85通过 | 15秒监控+门禁完整 |
| **固件Host测试** | ✅ 全绿 | 5套件0警告 | gcc -Werror通过 |
| **视觉推理核心** | ✅ 完成 | 75测试通过 | YOLO11n适配完成 |
| **固件烧录** | ✅ 验证 | 0错0警 | 用户实机确认 |

### ⚠️ 待标定/完善模块

| 模块 | 状态 | 阻塞原因 | 解决方案 |
|------|------|---------|---------|
| **运动参数** | ⚠️ 占位值 | 80steps/mm@500Hz会撞15秒超时 | 明天Step3标定 |
| **Z轴舵机** | ⚠️ 占位值 | 1000us/1900us未实测 | 明天Step1标定 |
| **坐标系统** | ⚠️ 占位值 | HOME/PICK/BOX1~6未测量 | 明天Step2标定 |
| **视觉模型** | 🟡 精度低 | val_acc=0.424，弱类<0.3 | 补数据+重训练 |
| **MaixCAM部署** | 🟡 未验证 | 无真机测试 | 待模型改进后验证 |

---

## 🎯 明天标定任务（2026-09-01）

### 上午：参数标定（9:00-11:30）

#### 9:00-9:15 | Step 0: 单轴点动测试
**目标**：确认X/Y方向、限位可读、行程测量

**操作**：
1. 上电，串口连接
2. X轴DIR0点动1000步，观察物理方向
3. Y轴DIR0点动1000步，观察物理方向
4. 触发6路限位，记录电平
5. 测量X/Y实际行程

**输出**：
- 填写：`电控/calibration-logs/step0-axis-jog-test.txt`
- 如需修改方向：编辑`ec_motion_plan.h` Line 26-27

---

#### 9:15-9:45 | Step 1: Z轴舵机标定
**目标**：确定4个舵机脉宽参数

**操作**：
1. 从1000us开始，每次+50us测试Z下降
2. 从1900us开始，每次-50us测试Z上升
3. 同步测试夹爪张开/闭合
4. 验证夹持可靠性（cube保持3秒）
5. 测量稳定时间（发送→到位延迟）

**输出**：
- 填写：`电控/calibration-logs/step1-servo-calibration.txt`
- 修改：`ec_axis_driver.h` Line 33-39
- 提交：git commit "Step1: 舵机脉宽 张开=___us 闭合=___us"

---

#### 9:45-10:05 | Step 2: 坐标测量
**目标**：冻结HOME/PICK/BOX1~6坐标

**操作**：
1. 确定装置中心原点（标记）
2. 测量HOME休息位（相对原点，单位mm）
3. 测量PICK取料圆心
4. 测量6个BOX中心点
5. 换算为0.1mm单位（×10）

**输出**：
- 填写：`电控/calibration-logs/step2-coordinates.txt`
- 修改：`ec_motion_plan.h` Line 35-41
- 修改：`drop_table.py` Line 40-53
- 提交：git commit "Step2: HOME/PICK/BOX坐标冻结"

---

#### 10:05-10:50 | Step 3: 步频标定
**目标**：确定传动比和安全步频

**操作**：
1. 查询机械参数（微步、齿数、节距）
2. 理论计算STEPS_PER_MM
3. 实测验证：1000步→实际mm
4. 渐进提升步频（500→1000→1500...）
5. 记录最高通过步频，取×0.8
6. 计算15秒预算（最坏路径）
7. 实测验证一次完整流程

**输出**：
- 填写：`电控/calibration-logs/step3-frequency-calibration.txt`
- 修改：`ec_axis_driver.h` Line 29-31
- 提交：git commit "Step3: 传动比=___steps/mm 步频=___Hz"

---

#### 10:50-11:30 | 编译烧录
**操作**：
1. MDK-ARM编译固件（0错0警）
2. 烧录到STM32
3. 快速验证：回零→单次运动

---

### 下午：带载验证（14:00-16:00）

#### 14:00-14:30 | Step 4: 单件+连续测试
**操作**：
1. 单件×5次（不同物料）
2. 连续×20件（6个BOX均匀分布）
3. 每5件记录温度

**输出**：
- 填写：`电控/calibration-logs/step4-load-test.txt`

---

#### 14:30-15:00 | 最坏路径压力测试
**操作**：
1. 固定路径×10次
2. 记录每次耗时
3. 验证无丢步

---

#### 15:00-15:30 | 极端物料+断电恢复
**操作**：
1. 最重/最轻/最难形状各测试
2. 急停→重启→回零→继续

---

#### 15:30-16:00 | 整理提交
**操作**：
1. 完善4个测试记录文件
2. git commit "Step4: 带载验证通过"
3. 合并到主分支
4. 打tag: v1.0-calibrated

---

## 📂 需要修改的文件清单

### 固件文件（C代码）

#### 文件1: `电控/firmware/stm32f407_m144z/App/Inc/ec_axis_driver.h`
```c
// Step 1修改（Line 33-39）
#define EC_AXIS_GRIPPER_OPEN_US UINT16_C(______)    // ← 填实测值
#define EC_AXIS_GRIPPER_CLOSE_US UINT16_C(______)   // ← 填实测值
#define EC_AXIS_GRIPPER_SETTLE_MS UINT32_C(______)  // ← 填实测值+50
#define EC_AXIS_Z_UP_US UINT16_C(______)            // ← 填实测值
#define EC_AXIS_Z_DOWN_US UINT16_C(______)          // ← 填实测值

// Step 3修改（Line 29-31）
#define EC_AXIS_STEPS_PER_MM_X UINT32_C(______)     // ← 填实测值
#define EC_AXIS_STEPS_PER_MM_Y UINT32_C(______)     // ← 填实测值
#define EC_AXIS_MOVE_FREQUENCY_HZ UINT32_C(______)  // ← 填安全步频
```

#### 文件2: `电控/firmware/stm32f407_m144z/App/Inc/ec_motion_plan.h`
```c
// Step 0修改（Line 26-27，如需要）
#define EC_MOTION_POSITIVE_X_DIR EC_DIRECTION_____  // 0 or 1
#define EC_MOTION_POSITIVE_Y_DIR EC_DIRECTION_____  // 0 or 1

// Step 2修改（Line 35-41）
#define EC_MOTION_PICK_X_MM10 ______    // 实测×10
#define EC_MOTION_PICK_Y_MM10 ______    // 实测×10
#define EC_MOTION_HOME_X_MM10 ______    // 实测×10
#define EC_MOTION_HOME_Y_MM10 ______    // 实测×10
```

### Python文件

#### 文件3: `电控/src/electrical_control/vision/drop_table.py`
```python
# Step 2修改（Line 40-53）
_DROP_POINTS = {
    1: (______, ______),  # BOX1实测×10
    2: (______, ______),
    3: (______, ______),
    4: (______, ______),
    5: (______, ______),
    6: (______, ______),
}
```

---

## 🛠️ 所需工具/物料

### 测量工具
- ✅ 卷尺/游标卡尺
- ✅ 红外测温仪
- ✅ 胶带/记号笔
- ✅ 秒表

### 测试物料
- ✅ 7种形状物料各2件
- ✅ 6个储物盒
- ✅ 取料盘

### 软件工具
- ✅ 串口调试助手
- ✅ MDK-ARM（编译固件）
- ✅ ST-Link（烧录）

### 备用件
- ✅ 备用舵机DS3120MG
- ✅ 备用STM32板

---

## 📋 Git分支策略

```
20260829-multinode-review (当前主分支)
    ↓
calibration/step-0-baseline (无代码修改)
    ↓
calibration/step-1-servo (修改ec_axis_driver.h舵机参数)
    ↓
calibration/step-2-coordinates (修改ec_motion_plan.h+drop_table.py)
    ↓
calibration/step-3-frequency (修改ec_axis_driver.h步频参数)
    ↓
calibration/step-4-load-test (只记录测试结果)
    ↓
合并回20260829-multinode-review
    ↓
打tag: v1.0-calibrated
```

### 回退策略
如Step3有问题：
```bash
git checkout calibration/step-2-coordinates
git checkout -b calibration/step-3-frequency-v2
# 重新标定...
```

---

## ⚠️ 预计风险与应对

### 风险1: 丢步（概率30%）
**症状**：到位后手动推，位置偏移
**应对**：降低步频200Hz → 重新Step3

### 风险2: 温升过高（概率20%）
**症状**：电机>70°C
**应对**：加散热片 或 降低步频

### 风险3: 夹持不稳（概率15%）
**症状**：物料掉落
**应对**：增加GRIPPER_CLOSE_US +50us → 重新Step1

### 风险4: 15秒超时（概率25%）
**症状**：计算耗时>13秒
**应对**：提高步频 或 优化布局（调整HOME位置）

### 风险5: 机械参数不明（概率10%）
**症状**：机械组无法提供齿数/节距
**应对**：直接实测（1000步→测量实际mm）

---

## ✅ 验收标准（明天16:00前达成）

### 必须达成（P0）
- ☐ 3个文件参数全部填写（共9个参数）
- ☐ 固件编译0错0警
- ☐ 单件×5次全部通过
- ☐ 15秒预算验证通过（最坏路径<13秒）
- ☐ 温升<70°C
- ☐ 4个标定记录文件完整
- ☐ git tag v1.0-calibrated

### 期望达成（P1）
- ☐ 连续×20件成功率≥95%
- ☐ 最坏路径×10次无丢步
- ☐ 极端物料全部通过
- ☐ 断电恢复测试通过

### 可选达成（P2）
- ☐ 温升<60°C（优秀）
- ☐ 连续×20件成功率=100%
- ☐ 标定经验写入`.claude/experiences/`

---

## 📞 现场联系人

### 如遇技术问题
- 机械组：________（提供传动参数）
- 电控组长：________
- 视觉组：________（后续MaixCAM部署）

### 如遇设备故障
- 实验室管理员：________
- 备用STM32位置：________
- 备用舵机位置：________

---

## 📌 明天早上第一件事

1. **检查设备**：
   - STM32通电正常
   - 6路限位接线完成
   - A4988驱动器MS1-3设置确认
   - 舵机供电6V稳定

2. **准备工具**：
   - 打印`QUICK-REFERENCE.txt`
   - 打印4个step测试记录模板
   - 准备卷尺、测温仪、秒表

3. **启动测试**：
   - 9:00准时开始Step0
   - 每步完成立即git commit
   - 遇阻立即记录+联系

---

## 🎯 预期成果（明天16:00）

### 代码层面
- ✅ 3个文件参数冻结
- ✅ 固件可烧录运行
- ✅ git tag v1.0-calibrated

### 硬件层面
- ✅ 单件投放准确（偏差<10mm）
- ✅ 连续运行稳定（无丢步）
- ✅ 温升可控（<70°C）

### 文档层面
- ✅ 4个标定记录文件完整
- ✅ 参数修改前后对比清晰
- ✅ 问题记录+解决方案

---

**当前时间**: 2026-08-31 22:00  
**当前分支**: 20260829-multinode-review  
**最新提交**: 7dd82566 标定方案完整交付  
**准备状态**: ✅ 文档ready，明天9:00开始执行

---

*祝明天标定顺利！* 🚀
