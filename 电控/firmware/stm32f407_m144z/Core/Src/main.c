/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "ec_app.h"
#include "ec_board_stm32.h"
#include "ec_pneumatic_gripper.h"  // 气动夹爪测试
#include "ec_tof.h"                // ToF 测距（MINIF/DVP0501C1, UART4）
#include "ec_drop_servo.h"

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
IWDG_HandleTypeDef hiwdg;

TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim4;
TIM_HandleTypeDef htim8;
TIM_HandleTypeDef htim9;
TIM_HandleTypeDef htim10;
TIM_HandleTypeDef htim11;

UART_HandleTypeDef huart2;
UART_HandleTypeDef huart3;
UART_HandleTypeDef huart4;  // ToF测距

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM8_Init(void);
static void MX_TIM9_Init(void);
static void MX_TIM10_Init(void);
static void MX_TIM11_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_USART3_UART_Init(void);
static void MX_UART4_Init(void);  // ToF测距
static void MX_IWDG_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */
  /* 2026-09-18 修复（堵转挂死根因）：
   * 提升 SysTick 优先级至 2，确保 HAL_GetTick() 和主循环喂狗能正常执行。
   * 正确优先级：TIM 步进(1) > SysTick(2) > UART(3)。
   * SysTick 默认优先级 15（最低）会导致主循环被中断风暴完全饿死。 */
  HAL_NVIC_SetPriority(SysTick_IRQn, 2, 0);
  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_TIM4_Init();
  MX_TIM8_Init();
  MX_TIM9_Init();
  /* 2026-10-22 修复：落料舵机初始化失败【绝不能】进 Error_Handler()。
   * 原实现是 `if (!ec_drop_servo_init()) { Error_Handler(); }`，而
   *   Error_Handler() = __disable_irq(); while(1){}
   * 且本调用位于 MX_USART2_UART_Init() 之前 ⇒ 一旦失败，
   * UART 永远起不来，板子**静默死锁**，外部完全无响应（连 PING 都不回）。
   * 而落料舵机型号未定、可能没接，属于"可缺席"外设 —— 缺席不应拖垮整机。
   * 处置：失败只记标志，继续初始化；DROP? 会回 ready=0，
   *       DROP 动作全部返回 ERR DROP_NOT_READY（fail-closed，不会误动）。 */
  (void)ec_drop_servo_init();
  MX_TIM10_Init();
  MX_TIM11_Init();
  MX_USART2_UART_Init();
  MX_USART3_UART_Init();
  MX_UART4_Init();  // ToF测距
  MX_IWDG_Init();
  /* USER CODE BEGIN 2 */
  ec_app_init();
  ec_pneumatic_gripper_init();  // 初始化气动夹爪PWM

  /* 气动夹爪测试：1秒吸附，1秒松开 */
  uint32_t gripper_test_last_toggle = 0;
  uint8_t gripper_test_state = 0;  // 0=松开, 1=吸附

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    uint32_t now = HAL_GetTick();

    /* 气动夹爪测试：每1000ms切换一次 */
    if (now - gripper_test_last_toggle >= 1000) {
      gripper_test_last_toggle = now;
      if (gripper_test_state == 0) {
        ec_pneumatic_gripper_close();  // 吸附
        gripper_test_state = 1;
      } else {
        ec_pneumatic_gripper_open();   // 松开
        gripper_test_state = 0;
      }
    }

    ec_app_poll(HAL_GetTick());
    HAL_IWDG_Refresh(&hiwdg);
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  /* ============================================================================
   * 🔴 2026-09-28 主频提升：HSI 16 MHz（PLL_NONE）  →  HSE 25 MHz + PLL = 168 MHz
   *
   * 【为什么改】
   *   ① 本项目**自己的设计文档**就按 168 MHz 时钟树核算：
   *      `docs/design/stm32f407-pin-timer-allocation.md:90` 原文
   *      "TIM8/TIM4/TIM9 时钟按 STM32F407 时钟树核算（APB2 定时器 168 MHz 或
   *       APB1 定时器 84 MHz，最终以 CubeMX 配置为准）"
   *   ② 运动规划代码的设计假设也是 168 MHz：
   *      `电控/stm32_logic/include/ec_step_profile.h:66-67` 原文
   *      "sqrt is ~1 us on a 168 MHz M4, negligible against the 100 us worst case"
   *      ⇒ 16 MHz 下同一整数开方约 **10.5 us**，占 `EC_STEP_MAX_HZ = 10000`
   *        （100 us 周期）预算的 **~10%**，且**是在步进中断里每拍都算**
   *      ⇒ 这是"提速上限被卡住"的结构性原因。
   *   ③ CubeMX 工程 `diankongv1.0.ioc` 里 PLL **本来就是配好的**：
   *      `RCC.VCOOutputFreq_Value=192000000` / `RCC.PLLCLKFreq_Value=96000000`
   *      / `RCC.HSE_VALUE=25000000`；但生成的代码却是 `PLL_NONE` + `SYSCLKSOURCE_HSI`
   *      ⇒ 高度疑似"某次改动没改回去"的遗留（**现场若要确认，见下方回退说明**）。
   *
   * 【改了什么（算例，全部整除）】
   *   HSE  8 MHz ÷ PLLM( 8) = 1 MHz  × PLLN(336) = 336 MHz(VCO)  ÷ PLLP(2) = 168 MHz
   *   （2026-10-17 修正：原按 25 MHz 晶振配置，但板上实为 8 MHz ⇒ 实际 SYSCLK 只有
   *     53.76 MHz，实测 USART2 波特率 38400、HAL_GetTick 慢 3.125 倍。改 PLLM=8 后
   *     整除关系不变，其余 PLLN/PLLP/PLLQ/APB 分频全部无需改动。）
   *   PLLQ(7) → 48 MHz（本项目未用 USB/SDIO，保守取值）
   *   HCLK  = 168 MHz（AHB DIV1）
   *   PCLK1 =  42 MHz（APB1 DIV4，F407 的 APB1 上限就是 42 MHz）
   *   PCLK2 =  84 MHz（APB2 DIV2）
   *   Flash 延迟 = 5 WS（VOS=1 下 168 MHz 的规范值）
   *
   * ⚠️⚠️ 【必须同步改的 7 个定时器 Prescaler】（否则舵机/步进频率全错）
   *   TIM2  APB1 舵机 50 Hz : 15  → 83   (84 MHz / 84  / 20000 = 50 Hz)
   *   TIM3  APB1 挡板 50 Hz : 15  → 83
   *   TIM4  APB1 STEP_Y     : 159 → 839  (84 MHz / 840 = 100 kHz)
   *   TIM8  APB2 STEP_X     : 159 → 1679 (168 MHz / 1680 = 100 kHz)
   *   TIM9  APB1 预留       : 159 → 839
   *   TIM10 APB2 挡板 50 Hz : 15  → 167  (168 MHz / 168 / 20000 = 50 Hz)
   *   TIM11 APB2 挡板 50 Hz : 15  → 167
   *   ⇒ 改完 TIM4/TIM8 的计数时钟仍是 **100 kHz**，与 `ec_board_stm32.c:28` 的
   *     `#define EC_STEP_TIMER_HZ UINT32_C(100000)` **保持一致**（改一端必须改另一端）。
   *
   * ⚠️ 【F407 绝不能调用 HAL_PWREx_EnableOverDrive()】
   *   `Drivers/CMSIS/.../stm32f407xx.h` 里 **无** `PWR_CR_ODEN/ODRDY` 定义；
   *   而 `Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr_ex.c:404` 的注释原文：
   *   "This function can be used only for STM32F42xx/STM32F43xx/STM32F446xx/
   *    STM32F469xx/STM32F479xx devices."
   *   ⇒ F407 跑 168 MHz **不需要** over-drive；若误调用，会等一个永不置位的
   *     ODRDY 标志 ⇒ 返回 HAL_TIMEOUT ⇒ 若判空则进 Error_Handler **板子不启动**。
   *
   * ⚠️ 【不受主频影响的部分（已核实依据）】
   *   UART 波特率：`stm32f4xx_hal_uart.c:3782` 用 `HAL_RCC_GetPCLK1Freq()` 现算
   *   SysTick 1ms ：`stm32f4xx_hal_rcc.c:719` 会先更新 SystemCoreClock、`:722`
   *                 再 `HAL_InitTick()` 重算
   *   IWDG       ：由 **LSI** 决定（不依赖 SYSCLK）
   *   ⇒ 这三者都**不需要改**。
   *
   * ⚠️ 【回退方法（一键）】
   *   用同目录 `main.c.bak-before-20260928-168mhz` 覆盖本文件，
   *   再用 `Core/Src/system_stm32f4xx.c.bak-before-20260928-168mhz` 覆盖对应文件，
   *   重新编译即可回到 16 MHz。**旧 hex 也请保留**。
   *   ⇒ 若烧录后【板子完全不启动】：说明 HSE 未起振 ⇒ 立刻回退（不会损坏硬件）。
   *   ⇒ 若【舵机乱抖 / 电机频率不对】：说明某个 PSC 算错 ⇒ 按上表逐个核对。
   * ============================================================================ */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE|RCC_OSCILLATORTYPE_LSI;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.LSIState = RCC_LSI_ON;          /* IWDG 仍用 LSI，与主频无关 */
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8U;                  /* 8 MHz / 8 = 1 MHz（2026-10-17 修正，原 25U） */
  RCC_OscInitStruct.PLL.PLLN = 336U;                /* 1 MHz × 336 = 336 MHz (VCO) */
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;       /* 336 / 2 = 168 MHz (SYSCLK) */
  RCC_OscInitStruct.PLL.PLLQ = 7U;                  /* 336 / 7 = 48 MHz（未用） */
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, A HB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;   /* HCLK  = 168 MHz */
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;    /* PCLK1 =  42 MHz */
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;    /* PCLK2 =  84 MHz */

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief IWDG Initialization Function
  * @param None
  * @retval None
  */
static void MX_IWDG_Init(void)
{

  /* USER CODE BEGIN IWDG_Init 0 */

  /* USER CODE END IWDG_Init 0 */

  /* USER CODE BEGIN IWDG_Init 1 */
  /* 2026-09-18 堵转挂死根因修复：原计划缩短 IWDG 超时从 1000ms→500ms，
   * 但实际配置（Prescaler=32, Reload=1000）仍为 **约 1.0s**
   * （LSI 32kHz / 32 / 1000 = 1Hz）。
   * 堵转场景下主循环被中断风暴饿死，1.0s 触发复位仍可加速恢复。
   * ⚠️ 若需真正改成 500ms，应设 Reload=500。 */
  /* USER CODE END IWDG_Init 1 */
  hiwdg.Instance = IWDG;
  hiwdg.Init.Prescaler = IWDG_PRESCALER_32;
  hiwdg.Init.Reload = 1000;
  if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN IWDG_Init 2 */

  /* USER CODE END IWDG_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 83;      /* 2026-09-28: 16MHz→168MHz。APB1定时器钟=84MHz, /84 = 1MHz, Period19999 ⇒ 50Hz */
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 19999;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim2, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */
  HAL_TIM_MspPostInit(&htim2);

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 83;      /* 2026-09-28: 16MHz→168MHz。APB1定时器钟=84MHz, /84 = 1MHz ⇒ 50Hz */
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 19999;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */
  HAL_TIM_MspPostInit(&htim3);

}

/**
  * @brief TIM4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM4_Init(void)
{

  /* USER CODE BEGIN TIM4_Init 0 */

  /* USER CODE END TIM4_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM4_Init 1 */

  /* USER CODE END TIM4_Init 1 */
  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 839;     /* 2026-09-28: 16MHz→168MHz。APB1定时器钟=84MHz, /840 = 100kHz（= EC_STEP_TIMER_HZ）*/
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 9999;
  htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim4) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM4_Init 2 */
  /* 2026-09-18 修复（Y 轴步进计数/加减速中断）：
   * 步进计数递减与梯形加减速的 ARR 更新全部在 TIM 更新中断里
   * （ec_board_stm32.c: ec_step_port_on_timer_period），
   * 而 CubeMX 生成本工程时没有勾选 TIM 全局中断 —— 既没有这两行 NVIC 使能，
   * stm32f4xx_it.c 里也没有 TIM4_IRQHandler 函数体。
   * 后果：counted_steps_remaining 永不被递减 → STEP_REMAIN 冻结、
   * MODE 永不回 IDLE、RESULT 恒为 0，且 HZ 参数被忽略
   * （定时器始终停在 profile 首个 ARR = 200Hz）。
   * 修复必须成对：NVIC 使能 + 中断函数体，缺一不可。 */
  HAL_NVIC_SetPriority(TIM4_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(TIM4_IRQn);
  /* USER CODE END TIM4_Init 2 */
  HAL_TIM_MspPostInit(&htim4);

}

/**
  * @brief TIM8 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM8_Init(void)
{

  /* USER CODE BEGIN TIM8_Init 0 */

  /* USER CODE END TIM8_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};
  TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

  /* USER CODE BEGIN TIM8_Init 1 */

  /* USER CODE END TIM8_Init 1 */
  htim8.Instance = TIM8;
  htim8.Init.Prescaler = 1679;    /* 2026-09-28: 16MHz→168MHz。APB2定时器钟=168MHz, /1680 = 100kHz（= EC_STEP_TIMER_HZ）*/
  htim8.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim8.Init.Period = 9999;
  htim8.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim8.Init.RepetitionCounter = 0;
  htim8.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim8) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim8, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
  sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
  if (HAL_TIM_PWM_ConfigChannel(&htim8, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  sBreakDeadTimeConfig.OffStateRunMode = TIM_OSSR_DISABLE;
  sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
  sBreakDeadTimeConfig.LockLevel = TIM_LOCKLEVEL_OFF;
  sBreakDeadTimeConfig.DeadTime = 0;
  sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
  sBreakDeadTimeConfig.BreakPolarity = TIM_BREAKPOLARITY_HIGH;
  sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
  if (HAL_TIMEx_ConfigBreakDeadTime(&htim8, &sBreakDeadTimeConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM8_Init 2 */
  /* 2026-09-18 修复（X 轴步进计数/加减速中断）：同 TIM4，见上方说明。
   * TIM8 的更新中断在 F407 上复用 TIM8_UP_TIM13_IRQn 这一条 NVIC 线。 */
  HAL_NVIC_SetPriority(TIM8_UP_TIM13_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(TIM8_UP_TIM13_IRQn);
  /* USER CODE END TIM8_Init 2 */
  HAL_TIM_MspPostInit(&htim8);

}

/**
  * @brief TIM9 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM9_Init(void)
{

  /* USER CODE BEGIN TIM9_Init 0 */

  /* USER CODE END TIM9_Init 0 */

  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM9_Init 1 */

  /* USER CODE END TIM9_Init 1 */
  htim9.Instance = TIM9;
  htim9.Init.Prescaler = 167;     /* TIM9/APB2: 168MHz/168 = 1MHz, 1us tick */
  htim9.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim9.Init.Period = 19999;      /* 1MHz/20000 = 50Hz (20ms period) */
  htim9.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim9.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim9) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim9, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM9_Init 2 */

  /* USER CODE END TIM9_Init 2 */
  HAL_TIM_MspPostInit(&htim9);

}

/**
  * @brief TIM10 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM10_Init(void)
{

  /* USER CODE BEGIN TIM10_Init 0 */

  /* USER CODE END TIM10_Init 0 */

  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM10_Init 1 */

  /* USER CODE END TIM10_Init 1 */
  htim10.Instance = TIM10;
  htim10.Init.Prescaler = 167;    /* 2026-09-28: 16MHz→168MHz。APB2定时器钟=168MHz, /168 = 1MHz ⇒ 50Hz */
  htim10.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim10.Init.Period = 19999;
  htim10.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim10.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim10) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim10) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim10, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM10_Init 2 */

  /* USER CODE END TIM10_Init 2 */
  HAL_TIM_MspPostInit(&htim10);

}

/**
  * @brief TIM11 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM11_Init(void)
{

  /* USER CODE BEGIN TIM11_Init 0 */

  /* USER CODE END TIM11_Init 0 */

  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM11_Init 1 */

  /* USER CODE END TIM11_Init 1 */
  htim11.Instance = TIM11;
  htim11.Init.Prescaler = 167;    /* 2026-09-28: 16MHz→168MHz。APB2定时器钟=168MHz, /168 = 1MHz ⇒ 50Hz */
  htim11.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim11.Init.Period = 19999;
  htim11.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim11.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim11) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim11) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim11, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM11_Init 2 */

  /* USER CODE END TIM11_Init 2 */
  HAL_TIM_MspPostInit(&htim11);

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief USART3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART3_UART_Init(void)
{

  /* USER CODE BEGIN USART3_Init 0 */

  /* USER CODE END USART3_Init 0 */

  /* USER CODE BEGIN USART3_Init 1 */

  /* USER CODE END USART3_Init 1 */
  huart3.Instance = USART3;
  huart3.Init.BaudRate = 115200;
  huart3.Init.WordLength = UART_WORDLENGTH_8B;
  huart3.Init.StopBits = UART_STOPBITS_1;
  huart3.Init.Parity = UART_PARITY_NONE;
  huart3.Init.Mode = UART_MODE_TX_RX;
  huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart3.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART3_Init 2 */

  /* USER CODE END USART3_Init 2 */

}

/**
  * @brief UART4 Initialization Function (ToF测距)
  * @param None
  * @retval None
  */
static void MX_UART4_Init(void)
{

  /* USER CODE BEGIN UART4_Init 0 */

  /* USER CODE END UART4_Init 0 */

  /* USER CODE BEGIN UART4_Init 1 */

  /* USER CODE END UART4_Init 1 */
  huart4.Instance = UART4;
  huart4.Init.BaudRate = 115200;
  huart4.Init.WordLength = UART_WORDLENGTH_8B;
  huart4.Init.StopBits = UART_STOPBITS_1;
  huart4.Init.Parity = UART_PARITY_NONE;
  huart4.Init.Mode = UART_MODE_TX_RX;
  huart4.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart4.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN UART4_Init 2 */

  /* USER CODE END UART4_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
/* USER CODE BEGIN MX_GPIO_Init_1 */
/* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(DIR_Z_GPIO_Port, DIR_Z_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOC, LIGHT_EN_Pin|DIR_Y_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(ENABLE_X_GPIO_Port, ENABLE_X_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(DIR_X_GPIO_Port, DIR_X_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(ENABLE_Y_GPIO_Port, ENABLE_Y_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(ENABLE_Z_GPIO_Port, ENABLE_Z_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin : DIR_Z_Pin */
  GPIO_InitStruct.Pin = DIR_Z_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(DIR_Z_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : MANUAL_RESET_SIG_Pin Z_UP_Pin */
  GPIO_InitStruct.Pin = MANUAL_RESET_SIG_Pin|Z_UP_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;   /* 2026-09-18 PAN-FIX: wai bu 10k shang la cong wei an zhuang, gai yong nei bu shang la, fang zhi xuan kong yin jiao bei EMI fan zhuan */
  HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

  /*Configure GPIO pins : LIGHT_EN_Pin DIR_Y_Pin */
  GPIO_InitStruct.Pin = LIGHT_EN_Pin|DIR_Y_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pin : START_SIG_Pin */
  GPIO_InitStruct.Pin = START_SIG_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;   /* 2026-09-18: START xuan kong bei du cheng yi zhi an zhe, shang la jiu zheng */
  HAL_GPIO_Init(START_SIG_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : ENABLE_X_Pin DIR_X_Pin */
  GPIO_InitStruct.Pin = ENABLE_X_Pin|DIR_X_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : X_END_Pin X_HOME_Pin Y_HOME_Pin ESTOP_FB_Pin
                           Z_DOWN_Pin */
  GPIO_InitStruct.Pin = X_END_Pin|X_HOME_Pin|Y_HOME_Pin|ESTOP_FB_Pin
                          |Z_DOWN_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;   /* 2026-09-18 PAN-FIX: wai bu 10k shang la cong wei an zhuang, gai yong nei bu shang la, fang zhi xuan kong yin jiao bei EMI fan zhuan */
  HAL_GPIO_Init(GPIOG, &GPIO_InitStruct);

  /*Configure GPIO pin : Y_END_Pin */
  GPIO_InitStruct.Pin = Y_END_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(Y_END_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : ENABLE_Y_Pin */
  GPIO_InitStruct.Pin = ENABLE_Y_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(ENABLE_Y_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : ENABLE_Z_Pin */
  GPIO_InitStruct.Pin = ENABLE_Z_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(ENABLE_Z_GPIO_Port, &GPIO_InitStruct);

/* USER CODE BEGIN MX_GPIO_Init_2 */
/* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  /* 2026-10-17：UART4 留给 ToF 测距（MINIF/DVP0501C1，ASCII 协议） */
  if (huart->Instance == UART4) {
    ec_tof_uart_rx_cplt(huart);
    return;
  }
  ec_board_uart_rx_callback(huart);
}

/* 2026-09-18 RX-DEAF-FIX: 以前本工程没有定义这个回调，于是 HAL 的弱回调（空函数）
 * 生效：任何一次 ORE/FE/NE/PE 都会走 UART_EndRxTransfer()，把 RxState 置 READY 并
 * 关掉 RXNE 中断，而没有人重新武装 HAL_UART_Receive_IT —— 接收从此永久死亡。
 * 这就是「收到若干帧后完全静默、全程看不到任何 ACK/NACK、按 RESET 键即恢复」的
 * 直接死因。这里只负责把接收重新武装；字节仍由环形缓冲兜住。 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
  /* 2026-10-17：UART4 的 ToF 链路同样需要重新武装，否则 ToF 会永久静默 */
  if (huart->Instance == UART4) {
    ec_tof_uart_error(huart);
    return;
  }
  ec_board_uart_error_callback(huart);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  ec_step_port_on_timer_period(htim);
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
