# REVIEW-20260812-008：状态机与驱动骨架弱独立性审查对账

> 日期：2026-08-12  
> 性质：Codex内部只读审查后的技术对账，弱独立性；不是Claude审查  
> 裁决：主机骨架可交Claude只读审查，不代表实机安全已验证

## 采纳并关闭

- 错误轮次任务可运动：加入`task_id == round_id`门和旧轮反例。
- 接件绕过验证态：加入匹配身份的`TaskSafetyValidated`，未验证不发运动，无效则锁定。
- ACK接口断裂：删除本地`DisplayAckAccepted`，直接消费协议`DisplayAckReceived`。
- STM32本地累计数越权：删除累计`success_count`，仅记录当前件成功语义并发`ITEM_RESULT`意图。
- 旧/乱序frame可接件：加入当前轮frame_seq水位。
- MOTION_DONE/ITEM_RESULT不可观察：加入两个分离的fake HAL动作意图。
- 急停覆盖不足：除`FAULT_LOCK`外所有状态均锁定。
- 端口故障后可继续STEP：STOP、disable、DIR、ENABLE、STEP故障路径均先建立保守本地状态，异常原样传播并锁存，无自动重试。

上述处置均有追加RED→GREEN；详细数量见TASK-003第12节。最终新鲜结果为协议14、状态机19、驱动12，共45项通过。

## 待确认与阻塞

- `DISPLAY_ACK`期望内容中`image_id/success_count`来源继续按Claude REVIEW-005 P0-001阻塞。
- `accepted_tasks`在主机骨架中仍无界；正式固件前需冻结容量、淘汰和跨轮策略。
- `TaskSafetyValidated`只表达已验证结论，不定义真实工作区、限位、挡板或动力回路判据。
- 电机参数、A4988适配、第三通道、重力轴防坠、急停回路及完整外层帧均未冻结。

## TDD诚实性

挡板门修复最初未先观察RED；后续仅完成错误路径回归验证。不得将其描述为原始测试先行。其余首批包缺失RED及审查修复RED均有真实测试入口和退出状态。
