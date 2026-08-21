# 2026-08-20 电控新对话交接提示词

> 用途：用户在新对话粘贴此提示词，由 Codex 接手 2026-08-20 的电控工作。
> 依赖文件：以交接单和验证记录为准，不依赖本提示词之外的历史对话记忆。

```text
你是接手 2026-08-20 工创赛电控工作的 Codex。当前目标：三天内把校赛电控做成可实操闭环，重点是串口通信与运动指令链路可靠；视觉由另一路推进，你不负责视觉训练，但必须保持视觉侧可对照的指令接口。

先完整读取以下文件，再决定下一步：
1. AGENTS.md 与 CLAUDE.md
2. docs/reports/2026-08-20-codex-handoff-current-progress.md
3. docs/design/2026-08-20-motion-command-list-v1.md
4. docs/reports/2026-08-20-barrier-command-v1-verification.md
5. docs/reports/2026-08-20-xy-step-motion-v1-verification.md
6. docs/prompts/claude-review-20260820-barrier-command-v1-readonly-review-prompt.md
7. 电控/firmware/stm32f407_m144z/MDK-ARM/xy-step-motion-v1-build.log

当前已确认事实：
- 主机测试 2/2 通过：ec_firmware_host_tests、ec_diag_disabled_tests。
- 固件已实现：PING、STATUS、INPUTS、STOP ALL、MOTION ARM、MOVE 定时版、MOVE STEPS 目标步数版、SERVO、GROUP、BARRIER。
- XY/Z 目标步数命令：MOVE X DIR0 STEPS 2000 HZ 500；步数 1～1,000,000，频率 10～10,000 Hz，发完自动停止。
- 四路挡板：PB0/PB1/PF6/PF7，命令 BARRIER ARM、BARRIER P<us>、BARRIER 1..4 P<us>、BARRIER COLLECT/AVOID P<us>、BARRIER STOP。
- 最新 Keil 构建 0 Error(s), 0 Warning(s)；最新 HEX SHA256：1277F2472A2E3CE7068317B1246BEBEEB36F941AC87939A03F0459FAD188D03D。
- 尚未实机烧录、串口实测或运动验证；挡板角度、XY 每毫米步数、正方向、最大安全频率均未标定。

下一步顺序（硬件动作必须先取得用户对具体动作的授权）：
1. 确认用户已烧录最新 HEX，串口为 115200 8N1。
2. 串口实测：PING -> OK PONG；STATUS；INPUTS 应 ACTIVE=0000。
3. 低风险单轴：MOTION ARM；MOVE X DIR0 STEPS 500 HZ 200；等待自动停止；记录方向、实际距离和 STATUS 的 STEP_TARGET/STEP_REMAIN。
4. 标定 X/Y 每毫米步数与正方向，把结果写入上层配置和验证记录。
5. 四路挡板逐通道 BARRIER 1..4 P<us> 标定 COLLECT/AVOID 脉宽，更新指令清单。
6. 每个 L2+ 步骤完成后更新交接单、验证记录和 Claude 审核词；Claude 发现项必须由你逐项对照证据处理。

约束：
- 不得把 Keil 构建或主机测试写成实机通过。
- 不得猜写未冻结的正式二进制帧、CRC16、超时、电机、限位、挡板角度和电源参数。
- 接线、上电、烧录、采购、实机运动必须等待用户对具体动作授权。
- 工作树包含大量未提交和未跟踪文件；git 提交必须精确选择本次电控文件，不得一把提交。
- 经验沉淀：完成 L2+ 任务后在 .claude/experiences/ 写候选经验，采用五字段格式，标注来源、证据强度、适用条件、反例、验证时间、状态与版本；未经验证不得升格为长期经验。
- 视觉若索要接口，指向 docs/design/2026-08-20-motion-command-list-v1.md，不另造协议。

第一个动作：读完文件后向用户确认串口端口、烧录状态和可上电时间，然后给出 10 分钟内可执行的实测清单；在取得授权前不要先改代码。
```
