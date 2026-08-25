# REVIEW-20260823-007 · 帝国机制四官审核：电控固件（存档）

> 审核方：帝国机制四官（御史 / 监察官 / 求是官 / 复盘官）
> 审核对象：电控固件 P0/P2 整改后的当前代码（含 volatile 整改）
> 审核等级：L3（模型分离：御史 sonnet / 监察 sonnet；求是 opus / 复盘 opus）
> 审核日期：2026-08-23
> 关联：REVIEW-001 / 001a / 002 / 003 / 004
> 说明：本记录为 2026-08-23 帝国四官审核的正式存档。原结论此前散落在交接稿，未落 REVIEW 编号；005 / 006 已被视觉侧占用，故本档取 007。

---

## 0. 总体裁决

- 电控固件：**有条件通过（静态层面）**
- 实机动作：**不允许**（运行时正确性未经真实定时器中断验证；`STEP_RESULT=DONE` 实机复核未授权）

---

## 1. 四官结论

### 【御史】（sonnet，模型分离）
- 结论：**有条件通过**
- 新发现 P1：ISR / 主循环共享状态缺 `volatile` → **已修**（9 个共享变量，见证据）
- 新发现 P2 ×7：均不阻塞上机，择机修（明细见 §2）

### 【监察官】（sonnet）
- 结论：**Level 3 红线冻结**
- 冻结理由（三项）：
  1. 动力走杜邦（0.2~0.5mm² 连接线承载电机电流，长跑发热风险）
  2. 硬件急停未落地（`ESTOP_FB` 只是辅助反馈，不物理切断动力）
  3. 保险丝规格冲突（采购清单 5~10A vs 接线参考 2~3A）
- 注：用户已明知风险仍拍板「动力线 / 保险丝不改」，红线冻结为**留痕**，不改变用户决策。

### 【求是官】（opus）
- 代码静态正确：事实占比 **~85%**
- 「实机可用」：猜测占比 **近 100%**（无任何运行时证据）

### 【复盘官】（opus）
- 5 条经验：P0 中断坑 / 板级测试盲区 / 杜邦 vs 动力 / 降压共地 / Z=舵机

---

## 2. 御史 7 项 P2（均不阻塞上机）

| 编号 | 问题 | 精确定位 | 影响 |
|---|---|---|---|
| P2-1 | DONE→TIMEOUT 覆盖竞争 | `ec_step_test.c:161-167`（ISR 设 DONE）vs `:206-210`（poll 设 TIMEOUT） | 窗口极小 |
| P2-2 | 诊断 UART 20ms 超时截断 | `ec_board_stm32.c:407`（`HAL_UART_Transmit(..., 20U)`） | STATUS/HELP 后半段被截；STEP_RESULT 在截断区前，P0 复核不受影响 |
| P2-3 | 安全抑制主循环轮询 | `ec_step_test.c:185-192` | 最坏 ~50ms 停止延迟 |
| P2-4 | 安全中止无 ABORTED 观测 | `stop_active_test` 无结果状态 | 无法区分「正常停」vs「安全中止」 |
| P2-5 | `start_counted` 无重入保护 | `ec_board_stm32.c:138-176` | 极端并发下状态可被覆盖 |
| P2-6 | STEP 无 arm 门禁 | `ec_diag.c:378-386`（`STEP X/Y/Z` 直接启动，不检查 `motion_armed`） | 绕过 MOTION ARM 授权 |
| P2-7 | 100kHz 魔数 | `ec_board_stm32.c:131,156`（`period = (100000 / hz) - 1`） | 与 PSC=159 硬耦合 |

---

## 3. 证据核对

- volatile 整改：`ec_step_test.c` 5 个（`active_axis`/`started_at_ms`/`counted_steps`/`mode`/`counted_result`）+ `ec_board_stm32.c` 4 个（`counted_axis`/`counted_steps_remaining`/`counted_steps_total`/`counted_active`）= 9 个。
- Keil 构建日志：`0 Error(s), 0 Warning(s)`，编译含 `ec_board_stm32.c`。
- 新 HEX SHA256：`1a565e56b11b2d564798d96d15295ad204820ea58a439af3833a4e83fa8d8196`。

---

## 4. 独立性限制（如实声明）

- 御史 / 监察用 sonnet（与执行方 opus 模型分离）。
- 求是 / 复盘用 opus，与御史结论存在同会话先验一致性风险。
- 主机测试未独立重跑，仅静态确认用例有效与证据文件存在。

---

## 5. 复审触发条件

- 实机授权并复核 `MOVE X DIR0 STEPS 100 HZ 100 → STEP_RESULT=DONE` 后复审 P0。
- 若主机测试增加板级接线覆盖，复审测试有效性。
- 若掩码 / 文档基线变更，复审 P1。
