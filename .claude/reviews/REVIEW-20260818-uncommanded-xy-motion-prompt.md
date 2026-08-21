# Claude只读安全审核任务：未授权时X/Y实体运动

## 审核方式

只读审核，不得修改、格式化、生成或删除任何项目文件，不得烧录、接线或上电。所有结论必须给出文件路径、行号和证据强度；无法由代码确认的内容必须标为“物理待验证”。

## 项目与目标

- 仓库：`C:\Users\29845\Desktop\工创赛`
- STM32工程：`电控/firmware/stm32f407_m144z`
- 芯片：STM32F407ZGTx，当前演示固件包含X/Y/Z步进测试和PB10舵机测试。
- 真正目标：解释并封堵“没有X/Y运动授权、状态机显示空闲，但X/Y实体发生运动”的风险；在原因未确认前，不批准视觉自动联动或多执行器同时上电。

## 已知事实

1. X、Y分别曾在正常`MOTION ARM → MOVE`流程中被用户确认能够实体动作。
2. 随后用户烧录舵机v3并执行：
   - `SERVO ARM`
   - `SERVO PB10 P1300`
3. 串口在舵机运行期间持续显示：

   ```text
   ARMED=0 MODE=0 STEP_AXIS=0
   SERVO_ARMED=0 SERVO_ACTIVE=1 SERVO_US=1300
   ```

4. 用户明确报告：此时X、Y实体发生运动。
5. 日志随后出现不完整且乱码的启动文本：

   ```text
   BOOT SAFE HSI=16000000 驜OOT SAFE HSI=160000?
   ```

6. 因此当前只能确认：正常状态机没有命令X/Y；无法仅凭日志确认运动发生在烧录复位窗口、舵机供电瞬态、STM32复位窗口、驱动输入悬空还是接线串扰期间。
7. 现场驱动模块仅见`HW-134A`标记，可能是A4988兼容载板，但具体版型、VDD、采样电阻、保护与针位尚未由照片或数据手册冻结。

## 冻结的应用映射

- X：STEP=PC6/TIM8_CH1，DIR=PA7，ENABLE=PA5（低有效）。
- Y：STEP=PB6/TIM4_CH1，DIR=PC7，ENABLE=PD7（低有效）。
- 舵机：PB10/TIM2_CH3，50 Hz。
- 启动目标安全态：STEP PWM停止；DIR低；ENABLE高（禁用）。

## 必读文件

- `电控/firmware/stm32f407_m144z/Core/Src/main.c`
- `电控/firmware/stm32f407_m144z/Core/Inc/main.h`
- `电控/firmware/stm32f407_m144z/Core/Src/stm32f4xx_hal_msp.c`
- `电控/firmware/stm32f407_m144z/diankongv1.0.ioc`
- `电控/firmware/stm32f407_m144z/App/Src/ec_board_stm32.c`
- `电控/firmware/stm32f407_m144z/App/Src/ec_step_test.c`
- `电控/firmware/stm32f407_m144z/App/Src/ec_servo_test.c`
- `电控/firmware/stm32f407_m144z/App/Src/ec_diag.c`
- `电控/firmware/stm32f407_m144z/App/Src/ec_app.c`
- `docs/design/m144z-m4-tested-pin-pcb-map.md`
- `docs/design/carrier-schematic-wiring-spec.md`
- `docs/reports/2026-08-18-stm32-servo-demo-v3.md`
- `电控/firmware/stm32f407_m144z/MDK-ARM/servo-v3-build.log`

## 必须回答的问题

1. 在正常运行路径中，是否存在任何代码能在`MODE=0 STEP_AXIS=0`时启动TIM4/TIM8、拉低PA5/PD7或产生X/Y STEP边沿？
2. 从上电/复位开始，到`MX_GPIO_Init()`完成之间，PA5、PD7、PC6、PB6分别处于什么模式和默认电平？是否存在驱动器ENABLE或STEP输入悬空窗口？
3. `MX_GPIO_Init()`是否在切换GPIO输出模式前预装载ENABLE高电平？这只能覆盖软件初始化后，还是也能覆盖复位早期和烧录期间？
4. `HAL_TIM_PWM_Stop()`后PC6/PB6的实际输出状态能否由代码保证为稳定低电平？计时器停止、复位或GPIO切换过程中是否可能形成边沿？
5. 舵机启动是否可能改写TIM4/TIM8、PC6/PB6、PA5/PD7，或通过复用冲突直接影响X/Y？必须全仓搜索证明。
6. 日志中的重复/乱码`BOOT SAFE`是否与欠压复位、看门狗复位、串口干扰等多个原因相容？当前代码是否记录了复位原因寄存器；若没有，下一版最小诊断应记录什么？
7. 如果外部驱动器没有硬件偏置，建议的ENABLE上拉、STEP下拉、DIR默认态应如何设计？必须明确：
   - 不得把任何GPIO上拉到12V/VMOT；
   - 未确认驱动VDD与STM32耐压前，不得直接给出上拉电压；
   - 区分临时台架措施与正式载板措施。
8. 是否应禁止在X/Y动力开启时烧录或复位STM32？在增加硬件失效安全默认态之前，是否应禁止舵机与X/Y同时上动力？
9. 给出能区分以下原因的最小实验矩阵：
   - 复位窗口输入悬空；
   - 舵机导致电源掉压/EMI复位；
   - STEP/EN接线交叉；
   - 驱动模块自身输入悬空；
   - 正常应用代码错误。

## 审核输出格式

1. **结论等级**：`BLOCK / NEEDS WORK / PASS FOR CONTROLLED RETEST`。
2. **确认事实**：只列代码或日志可证明的内容。
3. **最可能因果链**：每条标明事实、推断或未知。
4. **阻断项**：继续多执行器上电或视觉联动前必须解决的问题。
5. **代码修正候选**：只给建议和具体位置，不修改文件。
6. **硬件修正候选**：区分临时台架与正式载板。
7. **最小复测顺序**：必须从动力断开、单驱动、单轴开始，包含停止条件。
8. **证据缺口**：列出仍需用户提供的电源标签、驱动正反面、接线照片或测量结果。

## 审核红线

- 不得因主机测试、Keil构建或串口状态正常而宣称实机安全通过。
- 不得仅凭`HW-134A`猜测载板朝向、针位、VDD或电流限制。
- 不得把`STOP ALL`当作物理急停。
- 不得建议带电插拔电机或驱动模块。
- 在未解释未授权运动前，不得批准视觉自动触发动作。
