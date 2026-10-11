# App 状态可观测与串口无应答证据边界

- 结论：给现有 ASCII STATUS 末尾追加真实状态枚举名，可以区分状态机锁定与帧校验调查方向。无解析后 inbound 日志不代表无字节；轮次不匹配的 NACK 路径不能替代 FAULT_LOCK 静默路径的现场证据。ISR 自己更新的时间戳测的是 ISR 间隔，不是主循环活性。
- 来源：用户 2026-09-18 任务、当前状态机/网关/诊断/板级源码，以及 `docs/reports/2026-09-18-App状态可观测与ITEM_TASK无应答排查.md`。Keil 0/0；主机测试通过。首次隔离测试因新增 App 依赖链接失败，补测试桩后通过。现场状态未取得，不能断言根因。
- 适用条件：当前 STM32 App 的 STATUS 与现有协议。仅用于源码审查及主机验证；禁止据此宣称烧录、串口或运动通过。FAULT_LOCK 的来源、实际 round_id、现场 Python/固件版本仍需现场证据；不能推广成所有 task_id 错误都静默丢弃。
- 最后验证时间：2026-09-18。源码清单与产物哈希见报告；共享工作区再次修改后，需重新核对适用版本。资源为 Codex、PowerShell、ARMCC/Keil、CMake/CTest、Python pytest；未用子 Agent、未做跨 Provider 复用验证。
- 状态：证据状态 OBSERVED（构建/主机验证有实证；现场根因 INSUFFICIENT_EVIDENCE）；治理状态 DRAFT。旧文档若说未找到 NVIC_SystemReset，与本轮源码冲突；以带行号及哈希的当前证据为准。源码机制变化时重审或废止本经验，不自动升级为安全策略。
