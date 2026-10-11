# T2 · 固件/时序：`NACK_SINGLE_TASK_ONLY` 根因 + 派发时序

> **整份复制给 AI 即可。**
> **你是只读分析者：不要创建/修改/删除任何文件，不要执行 git，不要连硬件、不要上电、不要烧录。**
> 代码/方案写在回复里，**不要落盘**。

---

## 0. 你的角色

你是**嵌入式固件 + 主机侧时序**方向的分析者。工作区：`C:\Users\29845\Desktop\工创赛`。

## 1. 现象（今晚实测，2026-09-21 凌晨，两轮都复现）

树莓派侧的链在**收到 `DISPLAY_ACK` 之后立刻派发下一件 `ITEM_TASK`**，板子随即回：

```
20:03:08.559  第1件成功 (显示完成并确认 → DISPLAY_ACK)
20:03:09.564  ITEM_TASK sent（第2件）
20:03:10.572  inbound NACK_ACK_NOT_APPLICABLE
20:03:10.623  inbound NACK_SINGLE_TASK_ONLY      ← 「一次只能一个任务」
20:03:31.327  第2件才成功（耗时 21.8 s）
```

**后果**：旧代码把 `NACK_*` 落到主循环最后的 `else` 分支，**只打日志、不做任何重试**
⇒ 只能干等满 `task_timeout_s` 才重传 ⇒ **每件白拖 ~8 秒，实测 21~22 秒/件**（正常应约 13 秒）。

**已经做的临时修**（今晚，已有备份）：
在 `电控/deploy/run_chain.py` 主循环里加了一个 `elif event.startswith("NACK")` 分支，
**收到 NACK 就等 0.3 s 立即重发**。**这只是缓兵之计，根因还没查。**

## 2. 你要回答的问题

1. **板子为什么回 `NACK_SINGLE_TASK_ONLY`？** 它内部的状态机在收到新 `ITEM_TASK` 时，
   判断"已有任务在飞"的依据是什么？**写完一件之后它什么时候才算"空闲"？**
2. **`NACK_ACK_NOT_APPLICABLE` 又是什么条件触发的？** 两个 NACK 为什么**成对出现**？
3. **有没有一个"板子准备好了"的正向信号？** 我们观察到板子**每完成一件会再报一次
   `BARRIER_READY`**。它是否等价于"我已进入 WAIT_TASK、可以接下一件"？
4. **正确的派发时序应该是什么？** 给出：链应该在什么条件下才允许派下一件
   （等 `BARRIER_READY`？等某个 ACK？还是保持现在的"先发、被拒再退避重试"更好？）。
   要给出两种方案的**取舍**（延迟、鲁棒性、误判风险）。
5. **0.3 s 退避够不够？** 依据是什么？（可以从板子完成一件后到发出 `BARRIER_READY` 的实测间隔推断）

## 3. 必读文件

- `电控/deploy/run_chain.py`
  （主循环入站事件处理；搜 `event ==` / `startswith("NACK")` / `BARRIER_READY` / `resend_item_task`）
- `电控/src/electrical_control/rpi/gateway.py`（`:198-228` 把板子应答解析成事件名）
- `电控/src/electrical_control/protocol/types.py`（`:20` `ACK=0x05`）、`protocol/ack_nack.py`（`:16-19` reason 码）
- `电控/stm32_logic/src/ec_state_machine.c`（**重点**；搜 `SINGLE_TASK`、`NACK`、`WAIT_TASK`、`BARRIER_READY`）
- `电控/stm32_logic/src/ec_protocol_gateway.c`（`:66-110` 入站分发）
- `电控/firmware/stm32f407_m144z/App/Src/ec_app.c`（任务受理路径）
- `docs/design/interface-contract.md`（V0.8 命令字权威）

## 4. 已核实的前提

* 板子**每完成一件会再报一次 `BARRIER_READY`**（`ec_state_machine.c` 的 `PREPARE_BARRIER` 路径）。
* **建轮次**那一发 `ITEM_TASK` 会被启动序列**吞掉**（**一个字节都不回**），
  链的补偿逻辑是在收到 `BARRIER_READY` 时**立刻原样重发**同一帧
  （`run_chain.py` 里搜 `_should_resend_on_barrier_ready`）。
* 板子开机处于 `FAULT_LOCK`，`round_id=0`；**收到第一发 `ITEM_TASK` 才开始建轮次**。
* **FAULT_LOCK 会自愈**：`ec_state_machine.c` 里"FAULT_LOCK 下再收到一帧就重建轮次继续"，
  注释原文"一次故障之后链路能自愈，不必人工按 RESET"。
  ⚠️ 这条有个危险推论：**超窗后主机每几秒一次的在飞重传，会让机器从「错误原点」重跑同一件。**
  也请一并确认这条推论是否成立。
* 单件程序 **10 步**；程序跑完才发**一次** `MOTION_DONE`。
* 15 秒失活窗：**只有 `DISPLAY_ACK` 能关窗**，运动进度不算（`App/Inc/ec_app.h:16-17` 进度源编译期关闭）。

## 5. 产出要求

1. **根因结论**（带 `文件:行号`）。
2. **推荐的派发时序**（写成可落地的伪代码/diff 片段；说明改哪几行）。
3. **是否建议回退今晚那个 0.3 s 退避补丁**（如果正向信号方案更好）。
4. **是否需要改协议**（如需要，明确标 L4 并说明为什么无法用现有命令字解决）。
5. **验收判据**：能一条命令/一段日志判定的那种。建议判据示例：
   「连跑 ≥6 件，`NACK_*` 计数 = 0，且每件 `ITEM_TASK → DISPLAY_ACK` ≤ 14.0 s」。

## 6. 硬性要求

- 每条结论带 `文件:行号`；无法证实的写「未验证」，**不要猜**。
- 证据分三档：**【实测】/【代码推断】/【未验证】**。
- 结尾给：

```
[落点] 目标文件：<路径> ｜ 方式：新建/修改 ｜ 语言：<语言>
[建议执行] <可执行命令清单>
```
