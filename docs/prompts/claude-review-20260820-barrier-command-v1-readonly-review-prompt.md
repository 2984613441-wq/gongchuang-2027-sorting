# 给 Claude 的挡板模块、XY 目标步数与指令清单只读审核词

## 用途

用于在 Codex 完成四路挡板固件、XY 目标步数运动、`PING`/挡板指令解析、主机测试同步和指令清单编写后，委托 Claude 做一次独立、只读的回归审核。

该审核只评价当前工作区的代码、测试、构建证据和文档；不授权修改文件、采购、投板、接线、上电、烧录、实机运动或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“2026-08-20 四路挡板模块、XY 目标步数运动与校赛主控指令清单 V1”做回归审核。你的职责是发现事实错误、安全边界失守、引脚/定时器冲突、中断接线错误、命令解析不一致、测试覆盖不足和证据表述不恰当；你不是设计者，也不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入工作区的命令。
- 不得采购、投板、接线、上电、烧录、驱动实物、访问真实串口或外部账号。
- 可读取本地文件、检查 git 状态与差异、执行不会写入工作区的文本搜索和静态一致性检查。
- 若无法独立验证某项结论，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不改变用户最终裁决，也不构成实机执行授权。

先完整阅读下列基线，再核对本次变更文件；不要只依赖本提示词：
1. AGENTS.md 与 CLAUDE.md
2. docs/requirements/analysis.md
3. 电控/资料/要求汇总.md
4. 电控/资料/硬件映射待确认表.md
5. docs/design/interface-contract.md
6. docs/design/2026-08-20-motion-command-list-v1.md
7. docs/reports/2026-08-20-barrier-command-v1-verification.md
8. docs/reports/2026-08-20-xy-step-motion-v1-verification.md
9. docs/reports/2026-08-20-codex-handoff-current-progress.md
10. 本次变更文件：
   - 电控/firmware/stm32f407_m144z/App/Inc/ec_barrier_test.h
   - 电控/firmware/stm32f407_m144z/App/Src/ec_barrier_test.c
   - 电控/firmware/stm32f407_m144z/App/Inc/ec_step_test.h
   - 电控/firmware/stm32f407_m144z/App/Src/ec_step_test.c
   - 电控/firmware/stm32f407_m144z/App/Src/ec_board_stm32.c
   - 电控/firmware/stm32f407_m144z/App/Src/ec_app.c
   - 电控/firmware/stm32f407_m144z/App/Src/ec_diag.c
   - 电控/firmware/stm32f407_m144z/Core/Src/main.c
   - 电控/firmware/stm32f407_m144z/Core/Src/stm32f4xx_it.c
   - 电控/firmware/stm32f407_m144z/Core/Src/stm32f4xx_hal_msp.c
   - 电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1.0.uvprojx
   - 电控/firmware/stm32f407_m144z/tests/CMakeLists.txt
   - 电控/firmware/stm32f407_m144z/tests/test_barrier_test.c
   - 电控/firmware/stm32f407_m144z/tests/test_diag.c
   - 电控/firmware/stm32f407_m144z/tests/test_main.c
   - 电控/firmware/stm32f407_m144z/tests/test_support.h
   - 电控/firmware/stm32f407_m144z/tests/test_step_test.c
   - 电控/firmware/stm32f407_m144z/tests/test_group_test.c
11. 上述文件的 git diff 与 git diff --check 结果，以及电控/firmware/stm32f407_m144z/App/Src/ 现有代码作为对照。

审查事实基线：
- 四路挡板通道固定为 PB0/TIM3_CH3、PB1/TIM3_CH4、PF6/TIM10_CH1、PF7/TIM11_CH1；这是既有硬件映射基线的功能映射。
- 挡板脉宽允许范围 500～2500 us；归集/避让角度尚未实机标定，代码不得写死 COLLECT/AVOID 默认角度。
- 新增命令：PING、BARRIER ARM、BARRIER P<us>、BARRIER 1..4 P<us>、BARRIER ALL P<us>、BARRIER COLLECT P<us>、BARRIER AVOID P<us>、BARRIER STOP；STATUS 增加 BARRIER_TEST/BARRIER_ARMED/BARRIER_ACTIVE/BARRIER_MASK/BARRIER_US 字段。
- XY/Z 新增目标步数命令：MOVE <axis> DIR<0|1> STEPS <n> HZ <f>；步数 1～1,000,000，频率 10～10,000 Hz；STM32 用 TIM4/TIM8/TIM9 更新中断计数，发完自动停止；STATUS 增加 STEP_TARGET/STEP_REMAIN。
- 授权规则：MOVE/GROUP START/SERVO START/BARRIER SET 前必须对应 ARM，授权窗口 10 秒且一次性使用；九路输入任一 ACTIVE 非零时拒绝授权或立即停止。
- 主机侧证据：在 %TEMP% 纯英文目录全新配置构建，ec_firmware_host_tests 与 ec_diag_disabled_tests 2/2 通过；本机中文路径下 MinGW 编译存在路径编码问题，因此未在原目录直接构建。
- Keil 证据：用户本机 Keil V5.06 分别重建挡板版与 XY 步数版，均 0 Error(s), 0 Warning(s)；最新 XY 版 HEX SHA256 为 `1277F2472A2E3CE7068317B1246BEBEEB36F941AC87939A03F0459FAD188D03D`，构建日志为 `MDK-ARM/xy-step-motion-v1-build.log`。
- 实机门禁不变：不得把 Keil 构建或主机测试写成实机通过；挡板到位判据、四路实际脉宽、XY 每毫米步数与正方向、最大安全频率、机械干涉、电源和急停仍需实机验证。

请按下列顺序审核，并给出可复查的文件与行号定位。

一、变更范围与基线一致性
1. 核对挡板引脚/定时器是否与硬件映射表一致，是否存在与 STEP、舵机、补光、UART 的复用冲突。
2. 检查是否把未冻结的挡板角度、驱动器参数、机械参数写成事实。
3. 检查指令清单是否与固件实际解析完全一致，是否存在清单有而固件没有、或固件有而清单没有的命令。

二、挡板状态机与安全
1. 检查 ARM 是否为一次性授权、10 秒窗口是否严格、过期与输入门禁是否在 poll 中清除。
2. 检查 BARRIER RUNNING 期间输入触发、3 秒保持到期、端口启动失败是否都能停止 PWM 并回到 IDLE。
3. 检查 BARRIER 与 STEP、SERVO、GROUP 的互斥是否双向成立，且挡板自身 ARM/START 不会被自己的 busy 状态误拒绝。
4. 检查 STOP ALL、STEP STOP、RX_OVERFLOW、LINE_TOO_LONG 是否都会停止挡板。
5. 检查上电安全态是否包含四路挡板 PWM 停止，以及 ESTOP 相关路径是否同样停止挡板。

三、命令解析与响应
1. 逐条核对 PING、BARRIER P、BARRIER ALL P、BARRIER 1..4 P、BARRIER COLLECT P、BARRIER AVOID P、BARRIER STOP 的前缀长度与脉宽指针偏移是否正确。
2. 检查脉宽解析是否严格拒绝非数字、越界、超长行，是否允许前导零但拒绝非法值。
3. 检查 STATUS 输出缓冲区是否足够、字段数量与格式串是否匹配，HELP 是否包含新增命令。
4. 检查 EC_BARRIER_TEST_BUILD=0 的编译路径是否仍然可链接（ec_diag_disabled_tests 已作为证据）。

四、测试覆盖与证据
1. 评估 test_barrier_test.c 是否覆盖：未授权启动、非法 mask、非法脉宽、输入门禁、busy 互斥、一次性授权、运行停止、端口失败、9 路输入逐一触发。
2. 评估 test_step_test.c 是否覆盖：未授权启动、非法步数/频率、输入门禁、完成回调复位、目标/剩余步数查询。
3. 评估 test_diag.c 是否覆盖：命令解析、错误响应、STATUS 字段、与 STEP/SERVO/GROUP 的互斥。
4. 检查测试是否存在只测实现细节而放过真实安全缺陷的空转测试。
5. 核对 %TEMP% 构建命令、2/2 通过输出、Keil 构建日志和 HEX SHA256 是否与验证记录一致；未执行的项目必须明确标注“未执行”。

五、结论边界
1. 明确区分“主机测试通过”“Keil 构建通过”“HEX 已生成”“实机已通过”的差异。
2. 检查任何文档或代码没有隐含冻结挡板实际角度、到位判据、XY 标定参数、电源或机械参数。
3. 列出实机前仍必须完成的门禁：串口 PING/STATUS/BARRIER/MOVE STEPS 实机验证、四路挡板逐通道脉宽标定、COLLECT/AVOID 角度确认、XY 每毫米步数与正方向标定、最大安全频率、机械干涉检查、急停与电源验证。

六、XY 目标步数中断接线
1. 核对 TIM4/TIM8/TIM9 的 IRQ 名称、NVIC 使能位置与 stm32f4xx_it.c 处理函数是否匹配目标芯片启动文件。
2. 核对 HAL_TIM_PWM_Start_IT 使能更新中断后，HAL_TIM_PeriodElapsedCallback 是否只处理当前 counted 轴，发完步数是否停止 PWM、关闭更新中断、禁能驱动并复位状态。
3. 检查 STOP ALL、输入触发、60 秒超时、端口启动失败是否都能关闭 counted 状态，是否存在中断中重复进入或递归停止。
4. 检查 MOVE STEPS 命令是否与旧版 MOVE 互斥、与 GROUP/SERVO/BARRIER 互斥，STATUS 的目标/剩余步数是否来自当前 counted 上下文而不是陈旧值。

输出要求：
1. 将审核记录创建为新的文件（不要覆盖旧审核）：
   .claude/reviews/REVIEW-YYYYMMDD-NNN-claude-barrier-command-v1.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确“审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：
   - 主机侧代码与测试：允许 / 有条件允许 / 不允许
   - 实机动作门禁：允许 / 有条件允许 / 不允许
3. 随后按 P0、P1、P2 排序列出发现项。每项必须包含：编号、严重性、事实或证据、精确定位、风险、可验证的整改建议、整改后需要复查的证据。没有发现也必须明确写“P0（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”，不得混写。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得修改生产代码、测试或历史审查文件，不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成新的采纳/驳回/待确认记录。任何实机接线、上电、烧录、挡板动作、采购或外部写入动作仍须等待用户对具体动作授权。
