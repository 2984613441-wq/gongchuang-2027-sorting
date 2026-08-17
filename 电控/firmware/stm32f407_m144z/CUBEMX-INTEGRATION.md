# CubeMX/HAL 代码接入说明

> 本目录已纳入当前通过静态验收的 `.ioc`。CubeMX 配置仍由用户维护；本说明规定代码所依赖的符号、安全门禁和重新生成后的复核项。

## 1. CubeMX 标签与句柄契约

GPIO 必须使用交接基线中的标签：

- `ENABLE_X`、`ENABLE_Y`、`ENABLE_Z`，初始化输出高；
- `DIR_X`、`DIR_Y`、`DIR_Z`，初始化输出低；
- `LIGHT_EN`，初始化输出低；
- `X_HOME`、`X_END`、`Y_HOME`、`Y_END`、`Z_UP`、`Z_DOWN`、`ESTOP_FB`、`START_SIG`、`MANUAL_RESET_SIG`，全部 `GPIO_NOPULL`；
- `STEP_X=TIM8_CH1`、`STEP_Y=TIM4_CH1`、`STEP_Z=TIM9_CH1`；
- `BARRIER_PWM_1=TIM3_CH3`、`BARRIER_PWM_2=TIM3_CH4`、`BARRIER_PWM_3=TIM10_CH1`、`BARRIER_PWM_4=TIM11_CH1`；
- `GRIP_PWM=TIM2_CH3`、`WRIST_PWM=TIM2_CH4`；
- `UART_MAIN=USART3 PD8/PD9`、`UART_BACKUP=USART2 PA2/PA3`，均为 115200 8N1。

生成工程必须提供标准句柄 `htim2/3/4/8/9/10/11` 和 `huart3`。首轮 HSI 为 16 MHz，三个 STEP 定时器配置为 10 Hz；代码运行时只把比较值设为周期的一半，不修改 PSC/ARR。

## 2. 加入工程的源码

将 `App/Src` 全部 C 文件加入 Keil 工程，并直接加入以下既有核心源码：

```text
../../../stm32_logic/src/ec_crc32.c
../../../stm32_logic/src/ec_dedup.c
../../../stm32_logic/src/ec_state_machine.c
```

包含目录：

```text
../App/Inc
../../../stm32_logic/include
```

以上路径均以 `MDK-ARM/diankongv1.0.uvprojx` 所在目录为基准。

CubeMX 的 `USER CODE` 保护只覆盖源文件中的标记区域，不保证保留手工加入 Keil 的 App/Logic 工程组、包含路径和诊断宏。每次重新生成后，都必须重新核对 `.uvprojx` 中的九个源文件、两条包含路径及 `EC_DIAGNOSTIC_BUILD=1`。

诊断构建增加宏：

```text
EC_DIAGNOSTIC_BUILD=1
```

## 3. `main.c` 接入点

在 CubeMX 完成 `MX_GPIO_Init()`、全部 `MX_TIM*_Init()` 和 `MX_USART*_UART_Init()` 后调用：

```c
/* USER CODE BEGIN 2 */
ec_app_init();
/* USER CODE END 2 */
```

主循环只增加：

```c
/* USER CODE BEGIN WHILE */
while (1)
{
    ec_app_poll(HAL_GetTick());
/* USER CODE END WHILE */
```

并在 USER CODE 区提供 UART 回调转发：

```c
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    ec_board_uart_rx_callback(huart);
}
```

头文件：

```c
#include "ec_app.h"
#include "ec_board_stm32.h"
```

## 4. 禁止项

- CubeMX 生成代码和 USER CODE 均不得在启动时调用任何 `HAL_TIM_PWM_Start`。
- `ENABLE_X/Y/Z` 不得经历先低后高；CubeMX 必须在切换为输出前预装载高电平。
- `WRIST_PWM` 仅保留，代码启动路径不调用 TIM2_CH4 Start。
- 九路输入不得使用内部 `PULLUP` 或 `PULLDOWN`。
- `ESTOP_FB` 仅是反馈，不能作为危险动力切断实现。
- 未取得具体授权前，不接线、不烧录、不带危险动力上电、不执行真实电机运动。

## 5. 首轮诊断边界

- `STEP X/Y/Z` 只输出对应定时器通道的 10 Hz、50% 占空比脉冲；三个 `ENABLE` 始终保持高电平，因此它不是电机运动测试。
- `SAFE_LOCK=1` 表示生产动作保持锁定；诊断 STEP 脉冲不会解锁状态机，也不会取得驱动使能权。
- 5 秒自动停止和 `STEP STOP` 都依赖主循环继续调用 `ec_app_poll()`；它们不是独立硬件安全边界。实机系统仍须依赖硬件急停和危险动力切断。
- UART 接收使用固定容量环形队列和逐字节中断；队列满时返回 `ERR RX_OVERFLOW`。正式构建不定义 `EC_DIAGNOSTIC_BUILD`，命令解析编译为空实现。
- 用户生成 CubeMX 工程后，必须再核对 `.ioc`、MSP、GPIO 初始输出、定时器 PSC/ARR 和启动路径，并完成 Keil 无警告构建；在此之前不能宣称目标固件已编译或板级安全窗口已验证。
