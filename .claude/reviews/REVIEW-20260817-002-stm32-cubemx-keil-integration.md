# REVIEW-20260817-002：STM32 CubeMX/Keil 接入复审

> 日期：2026-08-17
> 范围：静态配置、源码接入、主机回归、Keil 只编译验证
> 独立性：弱独立性；主实施与三个审查角色均属于同一 Codex 环境，不替代另一模型或实机审核。

## 总体裁决

**主机侧回归与 Keil 目标编译通过，可以提交代码；仍禁止把结果表述为烧录、串口、电机、限位或实机通过。**

## 已实施内容

- 将用户在 D 盘生成并经三轮静态验收的 `Core`、`Drivers`、`MDK-ARM`、`.ioc` 和 `.mxproject` 复制到 Git 工作区。
- 在 `main.c` 的 CubeMX `USER CODE` 区加入：
  - `ec_app.h`、`ec_board_stm32.h`；
  - 外设初始化后的 `ec_app_init()`；
  - 主循环中的 `ec_app_poll(HAL_GetTick())`；
  - USART 接收完成回调转发。
- Keil 工程加入 `App/Src` 六个源文件及 `stm32_logic/src` 三个源文件。
- Keil 包含路径加入 `../App/Inc`、`../../../stm32_logic/include`，并定义 `EC_DIAGNOSTIC_BUILD=1`。
- 忽略 Keil 目标构建输出目录，保留工程源文件与配置。
- CubeMX 本地副本包含完整 CMSIS/DSP/NN 与未使用 HAL 实现；Git 只纳入当前 Keil 工程依赖的 CMSIS/设备头文件、HAL 头文件和实际参与编译的 HAL 源文件，避免提交无关示例库。

## 静态复核

- 16 个 GPIO 标签宏完整，映射与交接契约一致。
- 三路 `ENABLE` 在输出模式初始化前预装高电平；三路 `DIR` 和 `LIGHT_EN` 预装低电平。
- 九路输入均为 `GPIO_NOPULL`。
- TIM4/8/9 为 `PSC=159, ARR=9999`；TIM2/3/10/11 为 `PSC=15, ARR=19999`；所有初始 Pulse 为 0。
- USART3 NVIC、IRQ Handler 与 HAL 转发存在。
- Keil 工程中所有列出的源文件实际路径均存在，缺失数为 0。
- CubeMX 生成启动路径不存在自动 `HAL_TIM_PWM_Start` 或 `HAL_TIM_Base_Start`。

## 实际验证结果

### 主机纯逻辑

- 新建全英文临时路径入口后，以 GCC 16.1.0、`-Wall -Wextra -Wpedantic -Werror` 构建成功。
- CTest：`1/1` 通过，`0` 失败。

### 固件适配层主机测试

- 诊断构建与关闭诊断两种目标均严格编译成功。
- CTest：`2/2` 通过，`0` 失败。

### Keil 目标编译

- 工具：Keil ARMCC `V5.06 update 7 (build 960)`。
- 结果：`0 Error(s), 0 Warning(s)`。
- 尺寸：`Code=11762, RO-data=506, RW-data=52, ZI-data=2580`。
- 从 Git 暂存索引导出的干净快照再次构建，30 个工程文件缺失数为 0，结果仍为 `0 Error(s), 0 Warning(s)`，证明精简后的提交内容可独立构建。
- 已生成 HEX 仅作为编译产物；未执行下载、烧录、接线、上电或运动。

## 发现与处理

- 旧主机构建缓存引用不存在的 `S:\`，没有进入代码编译；保留旧目录不删除，改用新临时构建目录。
- MinGW 不能正确处理当前中文路径；通过临时 ASCII 目录联接执行测试，未复制或移动源码。
- Keil 同样经临时 ASCII 目录入口执行构建；该入口只用于兼容工具链，Git 工作区始终是唯一源码权威，禁止在临时目录直接维护第二份代码。
- 接入说明原先少算了从 `MDK-ARM` 到 `电控/stm32_logic` 的一层目录，已按实际解析结果改为 `../../../stm32_logic/...`。

## 剩余门禁

- 真实运动频率、速度、加速度、行程、回零时序和多级动作仍未冻结。
- 实验室阶段开始前仍需单独审核烧录版本、硬件急停、危险动力切断、驱动使能逻辑和限位电气状态。
- 本报告不授权烧录、接线、带危险动力上电或实机运动。
