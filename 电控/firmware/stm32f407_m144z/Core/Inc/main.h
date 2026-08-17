/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
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

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim);

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define DIR_Z_Pin GPIO_PIN_6
#define DIR_Z_GPIO_Port GPIOE
#define MANUAL_RESET_SIG_Pin GPIO_PIN_8
#define MANUAL_RESET_SIG_GPIO_Port GPIOF
#define LIGHT_EN_Pin GPIO_PIN_0
#define LIGHT_EN_GPIO_Port GPIOC
#define START_SIG_Pin GPIO_PIN_4
#define START_SIG_GPIO_Port GPIOA
#define ENABLE_X_Pin GPIO_PIN_5
#define ENABLE_X_GPIO_Port GPIOA
#define DIR_X_Pin GPIO_PIN_7
#define DIR_X_GPIO_Port GPIOA
#define Z_UP_Pin GPIO_PIN_11
#define Z_UP_GPIO_Port GPIOF
#define X_END_Pin GPIO_PIN_6
#define X_END_GPIO_Port GPIOG
#define X_HOME_Pin GPIO_PIN_7
#define X_HOME_GPIO_Port GPIOG
#define DIR_Y_Pin GPIO_PIN_7
#define DIR_Y_GPIO_Port GPIOC
#define Y_END_Pin GPIO_PIN_5
#define Y_END_GPIO_Port GPIOD
#define ENABLE_Y_Pin GPIO_PIN_7
#define ENABLE_Y_GPIO_Port GPIOD
#define Y_HOME_Pin GPIO_PIN_9
#define Y_HOME_GPIO_Port GPIOG
#define ESTOP_FB_Pin GPIO_PIN_13
#define ESTOP_FB_GPIO_Port GPIOG
#define Z_DOWN_Pin GPIO_PIN_14
#define Z_DOWN_GPIO_Port GPIOG
#define ENABLE_Z_Pin GPIO_PIN_15
#define ENABLE_Z_GPIO_Port GPIOG

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
