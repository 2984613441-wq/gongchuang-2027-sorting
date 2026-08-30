# 硬件事实收敛清单（2026-08-30）— USART 主备 + 执行器口径

> 背景：外部审查指出 USART2 只同步了一份文档、且执行器口径存在冲突。在批量同步/分配引脚前，先盘点全部冲突，**确认唯一物理事实后再动手**。
> 状态：只读盘点，未改任何硬件相关文档（除 interface-contract.md §2.1 已同步）。

---

## 1. USART 主备：全库残留盘点（USART3 vs USART2）

### 1.1 事实源（互相矛盾）

| 来源 | 结论 | 证据 |
|---|---|---|
| **固件实现** | **USART2**：PA2=TX/PA3=RX，115200 8N1 | `main.c` huart2、`stm32f4xx_hal_msp.c` PA2/PA3 AF7、`ec_board_stm32.c` 收发全走 huart2；USART3 已从代码删除。**Git 历史：固件自 8-17 首次集成即用 USART2** |
| **冻结记录 analysis.md D-011** | **USART3 主**（"正式 STM32 通信物理层 USART3 PD8/PD9 已冻结 2026-08-25"） | Line 100 |
| **硬件映射待确认表**（资料/） | USART3 主、USART2 备 | Line 17-18 |
| interface-contract.md | ⚠️ **2026-08-30 曾误改为 USART2 主，已按复核恢复 USART3 主基线**（见 §1.2） | §2.1 |
| **上电调试速查**（用户上电操作参考） | USART3 PD8/PD9 | 2026-08-26-上电调试速查.md |
| m144z-m4-tested-pin-pcb-map / pin-timer-allocation / 实测确认引脚表 | USART3 主 | 多行 |
| 载板原理图 wiring-spec / candidate-sketch | USART3 主（J_UART_MAIN=USART3） | 多行 |
| M144Z 引脚总图 / PCB 清单 / Excel | USART3 主 | 审查确认（非 md） |
| SAFETY_FIXES_v2/v3 | 自述"USART3→USART2 文档同步未做 ❌"（**把方向搞反了**：不是"文档没跟上固件"，而是"固件没跟上 8-25 冻结决定"） | v2:159-163, v3:202 |

### 1.2 结论（2026-08-30 用户拍板后更新）

- **用户拍板：USART2 为最终物理事实（实物接 PA2/PA3）**。历史过程：固件自 8-17 即用 USART2；8-25 冻结记录曾定 USART3 主（固件未跟随，形成漂移）；2026-08-30 用户确认实物接线 PA2/PA3 并拍板变更冻结接口。
- 执行中：`interface-contract.md` 已升级 **V0.8**（USART2 主 + 变更记录）；A/B 类文档批量同步进行中；C 类历史文档加废弃标注。

### 1.3 待办（按实物确认结果二选一，先不批量改）

**前置**：检查真实接线——设备接在 PD8/PD9 还是 PA2/PA3？

- **若实物接 PD8/PD9（与冻结基线一致）**：修改固件回 USART3（`main.c`/`hal_msp`/`ec_board_stm32` 换回 huart3，删除 huart2 主），恢复与冻结基线一致；施工资料无需改。
- **仅当实物接 PA2/PA3 且明确决定变更冻结接口**：升级 interface-contract V0.7 + 变更记录，再批量同步 A/B 类清单：
  - A 类（冻结/基线记录）：`docs/requirements/analysis.md`（D-011）、`电控/资料/硬件映射待确认表.md`、`interface-contract.md`（V0.7）
  - B 类（操作/施工资料）：`2026-08-26-上电调试速查.md`、`2026-08-20-motion-command-list-v1.md`、`2026-08-26-实机标定测试清单.md`、`电控供电接线参考-2026-08-23.md`、`carrier-schematic-wiring-spec.md`、`carrier-schematic-candidate-sketch.md`、`m144z-m4-tested-pin-pcb-map.md`、`stm32f407-pin-timer-allocation.md`、`stm32f407-实测确认引脚表-2026-08-14.md`、`M144Z-M4_CARRIER_IMPORT_README.md`、载板施工单 Word、载板 Excel、M144Z 引脚总图、PCB 清单、`集成/deployment/README.md`
  - C 类（历史文档，加"已废弃"标注即可）：`docs/reports/*`、`docs/prompts/*`

---

## 2. 执行器口径冲突盘点（决定引脚分配前必须先收敛）

| 维度 | 设计基线（2026-08-30 用户拍板） | 当前固件 | 旧原理图/Excel | 冲突 |
|---|---|---|---|---|
| X/Y | 17HS4401 步进 ×2，80 steps/mm（暂定） | STEP/DIR/EN 三线（PC6/PA7/PA5、PB6/PC7/PD7） | 同左 | 无 |
| Z 升降+夹爪 | **单只 DS3120MG 舵机联动**（升降+夹爪一个舵机，用户 2026-08-30 拍板） | 单个 Z 舵机同时实现升降+夹爪联动（一致 ✅） | 三轴步进（Z 也是步进）+独立夹爪 PWM+腕部 PWM | 旧图口径废弃（以用户拍板为准） |
| 限位 | 回零/限位 STM32 负责；无独立 X/Y 限位 | 六路：X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN | 六路限位 | 口径待收敛 |
| 挡板 | MG996R ×4，4 路 PWM，需 BARRIER_READY 反馈 | 4 路 PWM（PB0/PB1/PF6/PF7），**无位置反馈输入** | — | 反馈缺失（已知） |
| 失电许可 | 需安全回路 | POWER_PERMISSION 位（GPIO 未接） | — | 待接线 |
| 串口 | **USART2 主（用户 2026-08-30 拍板）、USART3 备用** | USART2（一致 ✅） | USART3 主（废弃） | 已拍板收敛 |

### 2.1 结论（2026-08-30 用户拍板后更新）

- **执行器口径已收敛**：Z 升降 + 夹爪 = **单只 DS3120MG 舵机联动**（用户拍板；原"双舵机独立"基线废弃）。固件单舵机联动实现与拍板一致。机械组仍需提供：联动结构、完整行程、夹持可靠性、断电状态验证（标定/安全前置）。
- **串口已收敛**：USART2 主、USART3 备（用户拍板），全库批量同步进行中（`interface-contract.md` V0.8 已完成）。
- **剩余待收敛**：限位实存口径（六路 vs 无独立限位）、挡板反馈引脚、失电许可 GPIO——在唯一硬件真值表完成前，挡板反馈/失电许可 GPIO 分配仍暂缓（I/O 映射红线）。

---

## 3. 拍板结果与剩余项（2026-08-30 用户拍板后）

| 项 | 结果 |
|---|---|
| 1. USART 主链路 | ✅ **已拍板：USART2 主、USART3 备**（实物 PA2/PA3）；契约 V0.8 + 全库同步进行中 |
| 2. 执行器口径 | ✅ **已拍板：Z 升降+夹爪 = 单只 DS3120MG 舵机联动**；机械组待提供联动结构/行程/夹持/断电验证 |
| 3. 15 秒监控 | ✅ 滚动失动监控已落地（`700c508f`，进展源 fail-closed） |
| 4. 运动标定顺序 | ✅ 批准：冻结 HOME/PICK/六落点/路线 → 逐箱算步数 → 加减速策略 → 带载测丢步/温升 → 冻结参数（**待机械组**） |

**剩余待收敛**：限位实存口径、挡板反馈引脚、失电许可 GPIO——唯一硬件真值表完成前，GPIO 分配仍暂缓（I/O 映射红线）。
