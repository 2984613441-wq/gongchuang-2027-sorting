# 给 Claude 的 2026-08-22 电控 P0/P2 整改只读审核词

## 用途

委托 Claude 对 Codex 已实施的 P0 计数运动 update 中断修复、P2-1/P2-3/P2-4
整改、P1 掩码文档澄清做一次独立、只读回归审核。

该审核只评价当前工作区代码、测试和文档；不授权修改文件、接线、上电、烧录、
实机运动、访问真实串口或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“2026-08-22 电控 P0/P2 整改批次”
做回归审核。你只负责发现事实错误、安全缺口、协议不一致、测试盲区和证据表述
问题；你不是设计者，也不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入
  工作区的命令。
- 不得接线、上电、烧录、驱动实物、访问真实串口或外部账号。
- 可读取本地文件、检查 git status/diff；可执行不会写入工作区的静态检查，
  若测试只写临时目录也可运行。
- 若无法独立验证，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不改变用户最终裁决，也不构成实机执行授权。

先完整阅读下列基线，再核对本次变更文件；不要只依赖本提示词：
1. AGENTS.md 与 CLAUDE.md
2. docs/prompts/codex-handoff-20260822-next-conversation-prompt.md
3. .claude/reviews/REVIEW-20260822-001-claude-ec-motion-test-firmware.md
4. .claude/reviews/REVIEW-20260822-002-codex-ec-motion-test-reconciliation.md
5. .claude/reviews/REVIEW-20260822-003-codex-p0-p2-ec-fixes.md
6. docs/design/2026-08-20-motion-command-list-v1.md
7. 本次变更文件：
   - 电控/firmware/stm32f407_m144z/App/Src/ec_board_stm32.c
   - 电控/firmware/stm32f407_m144z/App/Inc/ec_step_test.h
   - 电控/firmware/stm32f407_m144z/App/Src/ec_step_test.c
   - 电控/firmware/stm32f407_m144z/App/Src/ec_diag.c
   - 电控/firmware/stm32f407_m144z/tests/test_step_test.c
   - 电控/firmware/stm32f407_m144z/tests/test_diag.c
   - 电控/firmware/stm32f407_m144z/MDK-ARM/ec-p0-fix-20260822-build.log
8. 上述文件的 git diff 与 git diff --check 结果

审查事实基线（Codex 已实测或静态核对）：
- 主机测试：在 %TEMP% 纯英文目录全新 MinGW 构建，ctest 2/2 通过
  （ec_firmware_host_tests、ec_diag_disabled_tests）。
- Keil：UV4 命令行重建 0 Error(s), 0 Warning(s)；日志
  MDK-ARM/ec-p0-fix-20260822-build.log。
- 新 HEX SHA256：1A565E56B11B2D564798D96D15295AD204820EA58A439AF3833A4E83FA8D8196。
- P0 修复位置：ec_board_stm32.c 启动路径为 PWM_Start + 清 TIM_FLAG_UPDATE +
  使能 TIM_IT_UPDATE（约 157/164/171 行）；停止路径补关 CC1/UPDATE
  （约 77/78 行）。
- NVIC：stm32f4xx_hal_msp.c 已使能 TIM4_IRQn、TIM8_UP_TIM13_IRQn、
  TIM1_BRK_TIM9_IRQn；TIM8_CC_IRQn 未使能。
- P2-1：ec_step_test.h 新增 EC_STEP_MAX_STEPS=1,000,000；ec_step_test.c
  函数层与 ec_diag.c 解析层同时校验。
- P1 文档：指令清单第 3 节按动作类别限定抑制掩码，保留单轴 7 路 /
  组合 9 路；START/MANUAL_RESET 当前仅参与组合动作抑制。
- 实机门禁：未烧录、未串口实测、未运动验证；STEP_RESULT=DONE 实机复核
  未授权。

请按下列顺序审核。

一、P0 修复正确性
1. 确认 HAL_TIM_PWM_Start + __HAL_TIM_ENABLE_IT(TIM_IT_UPDATE) 是否真正
   解决“计数运动永远超时、STEP_RESULT 恒为 TIMEOUT”。
2. 检查启动前清除 TIM_FLAG_UPDATE、停止时关闭 CC1/UPDATE 是否存在遗漏或
   副作用；特别检查重复 start/stop、旧版 Start_IT 残留、主循环 stop、
   安全输入触发 stop 的路径。
3. 核对 HAL_TIM_IRQHandler 中 update 事件到 HAL_TIM_PeriodElapsedCallback
   的调用条件，以及 main.c 的 PeriodElapsedCallback 到
   ec_step_port_on_timer_period 的接线。
4. 检查 NVIC 与 IRQHandler 是否覆盖 TIM4/TIM8/TIM9 全部三轴，TIM8_CC 是否
   存在默认 handler 落地风险。
5. 明确主机测试为何不能覆盖 ec_board_stm32.c，并评估整改后仍缺的验证。

二、P2-1 一致性
1. 检查 EC_STEP_MAX_STEPS 是否同时在函数契约与诊断解析层生效，无其它
   硬编码残留。
2. 检查新增测试是否真正覆盖 1,000,001 拒绝与 1,000,000 接受。

三、P1 文档与代码一致性
1. 检查指令清单第 3 节新措辞是否消除“任一输入”歧义，且与四模块实际掩码一致。
2. 评估保留 7/9 是否安全，START/MANUAL_RESET 生产语义缺口是否已如实记录。

四、P2-3/P2-4/P2-2 文档
1. 检查 BARRIER ALL/COLLECT/AVOID 当前同行为说明是否准确。
2. 检查 TIM9 注释与极端参数超时边界记录是否准确。

五、测试与证据
1. 核对主机测试 2/2、Keil 0 Error(s)/0 Warning(s)、HEX SHA256、日志路径
   是否与记录一致。
2. 评估是否存在只测实现细节而放过真实中断接线的空转测试。

六、结论边界
1. 明确区分“主机测试通过”“Keil 构建通过”“实机已通过”。
2. 列出实机前仍必须完成的门禁：真实定时器中断复核
   MOVE X DIR0 STEPS 100 HZ 100 报 STEP_RESULT=DONE、STEP_REMAIN=0；
   XY/挡板/舵机标定；急停与电源验证。

输出要求：
1. 将审核记录创建为新的文件（不要覆盖旧审核）：
   .claude/reviews/REVIEW-YYYYMMDD-NNN-claude-ec-p0-p2-fixes.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确
   “审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：
   - 电控固件 P0/P2 整改：通过 / 有条件通过 / 不通过
   - 实机动作门禁：允许 / 有条件允许 / 不允许
3. 随后按 P0、P1、P2 排序列出发现项。每项必须包含：编号、严重性、事实或
   证据、精确定位、风险、可验证的整改建议、整改后需要复查的证据。
   没有发现也必须明确写“P0（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”，不得混写。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得修改生产代码、测试或历史审查
   文件，不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成新的采纳/驳回/待确认
记录。任何接线、上电、烧录、实机运动、push、git 改写或 .git 清理仍须用户对
具体动作授权。
