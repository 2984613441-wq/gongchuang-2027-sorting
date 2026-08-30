# 给 Claude 的视觉→STM32 完整指令桥接只读审核词

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

## 用途

用于在 Codex 完成 `action_bridge.py`、JSONL 输出端、树莓派部署入口和主机
测试后，委托 Claude 做一次独立、只读的回归审核。

该审核只评价当前工作区的代码、测试和文档；不授权修改文件、接线、上电、
烧录、实机运动、访问真实串口或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“2026-08-21 视觉→STM32 完整
ASCII 指令桥接”做回归审核。你的职责是发现协议一致性错误、安全门禁失守、
配置校验漏洞、事务顺序错误、测试覆盖不足和证据表述不恰当；你不是设计者，
也不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入
  工作区的命令。
- 不得接线、上电、烧录、驱动实物、访问真实串口或外部账号。
- 可读取本地文件、检查 git 状态与差异、执行不会写入工作区的静态检查和
  测试运行（若测试本身只写临时目录）。
- 若无法独立验证某项结论，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不改变用户最终裁决，也不构成实机执行授权。

先完整阅读下列基线，再核对本次变更文件；不要只依赖本提示词：
1. AGENTS.md 与 CLAUDE.md
2. docs/design/interface-contract.md
3. docs/design/2026-08-20-motion-command-list-v1.md
4. docs/reports/2026-08-21-vision-stm32-action-bridge.md
5. docs/reports/2026-08-21-open-source-reference-review.md
6. 集成/demo_bridge/bridge.py（最小演示桥接，本次未改）
7. 集成/demo_bridge/fake_serial.py
8. 集成/demo_bridge/test_bridge.py
9. 集成/demo_bridge/config.example.json
10. 本次变更文件：
    - 集成/demo_bridge/action_bridge.py
    - 集成/demo_bridge/config.full.example.json
    - 集成/demo_bridge/test_action_bridge.py
    - 视觉/src/jsonl_emitter.py
    - 视觉/src/test_jsonl_emitter.py
    - 集成/deployment/run_pipeline.py
    - 集成/deployment/README.md
    - 集成/demo_bridge/README.md
11. 上述文件的 git diff 与 git diff --check 结果，以及电控固件
    `电控/firmware/stm32f407_m144z/App/Src/ec_diag.c` 作为命令响应对照。

审查事实基线：
- 固件主串口：USART3，PD8=TX，PD9=RX，115200，8N1，文本命令以 CRLF 结尾。
- 每条命令必须返回一行响应；运动命令一旦收到 OK 禁止自动重发；任何 ERR、
  串口断开、BOOT SAFE 进入锁存故障。
- 九路输入全部低有效；正常目标 ACTIVE=0000；运行中任一输入触发立即停止。
- 已冻结 ASCII 命令与成功响应（来自 ec_diag.c）：
  - MOTION ARM -> OK MOTION ARMED 10S
  - MOVE X|Y|Z DIR0|DIR1 -> OK MOTION STARTING
  - MOVE X|Y|Z DIR0|DIR1 STEPS <n> HZ <f> -> OK MOTION STARTING
  - SERVO ARM -> OK SERVO ARMED 10S
  - SERVO PB10 P<us> -> OK SERVO STARTING 2S
  - GROUP ARM -> OK GROUP ARMED 10S
  - GROUP START XDIR0|XDIR1 YDIR0|YDIR1 OPEN|CLOSE -> OK GROUP STARTING
  - BARRIER ARM -> OK BARRIER ARMED 10S
  - BARRIER P<us> / BARRIER ALL P<us> -> OK BARRIER SET ALL
  - BARRIER 1..4 P<us> -> OK BARRIER SET CHANNEL
  - BARRIER COLLECT P<us> -> OK BARRIER COLLECT
  - BARRIER AVOID P<us> -> OK BARRIER AVOID
- STATUS 行包含：ARMED、MODE、STEP_AXIS、STEP_TARGET、STEP_REMAIN、
  STEP_RESULT、SERVO_ARMED、SERVO_ACTIVE、SERVO_US、GROUP_ARMED、
  GROUP_ACTIVE、GROUP_XDIR、GROUP_YDIR、GROUP_SERVO_US、BARRIER_ARMED、
  BARRIER_ACTIVE、BARRIER_MASK、BARRIER_US。
- JSONL 契约：每行恰好四个字段 frame_id / label / confidence / ts_ms；
  额外字段必须被拒绝。
- 桥接安全默认：dry-run 默认开启；所有动作默认 enabled=false；真实运动
  必须 --allow-motion 且配置显式启用。
- 事务顺序：STOP ALL -> STATUS 空闲 -> INPUTS ACTIVE=0000 -> 对应 ARM ->
  单条动作命令 -> 运行态确认 -> 空闲确认。
- 故障处理：最多三次 STOP ALL，不自动重发运动命令；无法确认停止时关闭
  串口并要求物理切断执行器动力。
- 主机证据：集成/demo_bridge 24/24 通过；视觉/src 4/4 通过；端到端干跑
  fake 视觉 -> action_bridge --dry-run 输出 IGNORED disabled（安全默认）。

请按下列顺序审核，并给出可复查的文件与行号定位。

一、指令一致性
1. 逐条核对 action_bridge.py 生成的 arm/run 命令与成功响应是否与上述
   ec_diag.c 事实基线完全一致，特别是 GROUP START 的 XDIR/YDIR 前缀。
2. 检查是否存在清单命令未覆盖、响应前缀误匹配、命令串拼写错误。
3. 检查 barrier 四种模式（all/channel/collect/avoid）的命令与响应映射。

二、配置校验
1. 检查步骤数、频率、脉宽、通道、方向、group servo 的取值范围是否与
   指令清单一致：步数 1～1,000,000，频率 10～10,000 Hz，脉宽
   500～2500 us，通道 1～4。
2. 检查未知字段、缺失字段、布尔/整数类型、非法 kind 是否都被严格拒绝。
3. 检查 config.full.example.json 是否全部 enabled=false。

三、事务与安全
1. 检查 STOP ALL -> STATUS 空闲 -> INPUTS -> ARM -> 动作 -> 运行 -> 空闲
   的顺序是否严格，是否有任何自动重试运动命令的路径。
2. 检查运行态/空闲态谓词使用的 STATUS 字段是否与固件输出一致。
3. 检查 ERR、BOOT SAFE、ACTIVE 非零、超时是否都进入锁存故障，且最多
   三次 STOP ALL，确认失败时关闭串口。
4. 检查 dry-run 与 --allow-motion 互斥、--port 必填等 CLI 约束。

四、视觉输出端
1. 检查 jsonl_emitter.py 是否只输出四字段 JSONL，无 bbox 等额外字段。
2. 检查 fake source 是否提供连续帧稳定与显式无目标释放窗口。
3. 检查部署入口 run_pipeline.py 是否正确复用 action_bridge，无新协议。

五、测试覆盖与证据
1. 评估 test_action_bridge.py 是否覆盖：命令串、范围校验、事务顺序、
   ERR 锁存不重试、dry-run/disabled。
2. 评估 test_jsonl_emitter.py 是否覆盖：字段契约、null 目标、释放窗口。
3. 检查测试是否存在只测实现细节而放过真实安全缺陷的空转测试。
4. 核对 24/24、4/4 和端到端干跑输出是否与实施记录一致；未执行的项目
   必须明确标注“未执行”。

六、结论边界
1. 明确区分“主机测试通过”“代码可运行”“实机已通过”的差异。
2. 检查任何文档或代码没有隐含冻结未标定的步数/频率/脉宽/坐标参数。
3. 列出实机前仍必须完成的门禁：真实串口验证、XY 每毫米步数与正方向
   标定、挡板/舵机脉宽标定、最大安全频率、机械干涉、急停与电源验证。

输出要求：
1. 将审核记录创建为新的文件（不要覆盖旧审核）：
   .claude/reviews/REVIEW-YYYYMMDD-NNN-claude-vision-stm32-action-bridge.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确
   “审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：
   - 主机侧代码与测试：允许 / 有条件允许 / 不允许
   - 实机动作门禁：允许 / 有条件允许 / 不允许
3. 随后按 P0、P1、P2 排序列出发现项。每项必须包含：编号、严重性、事实
   或证据、精确定位、风险、可验证的整改建议、整改后需要复查的证据。
   没有发现也必须明确写“P0（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”，不得混写。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得修改生产代码、测试或历史
   审查文件，不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成新的采纳/驳回/
待确认记录。任何实机接线、上电、烧录、运动、采购或外部写入动作仍须等待
用户对具体动作授权。
