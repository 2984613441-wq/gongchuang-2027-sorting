# 硬件事实收敛清单（2026-08-30）— USART 主备 + 执行器口径

> 背景：外部审查指出 USART2 只同步了一份文档、且执行器口径存在冲突。在批量同步/分配引脚前，先盘点全部冲突，**确认唯一物理事实后再动手**。
> 状态：只读盘点，未改任何硬件相关文档（除 interface-contract.md §2.1 已同步）。

---

## 1. USART 主备：全库残留盘点（USART3 vs USART2）

### 1.1 事实源（互相矛盾）

| 来源 | 结论 | 证据 |
|---|---|---|
| **固件代码**（事实权威） | **USART2 主**：PA2=TX/PA3=RX，115200 8N1 | `main.c` huart2（"Control communication uses USART2 exclusively"）、`stm32f4xx_hal_msp.c` PA2/PA3 AF7、`ec_board_stm32.c` 收发全走 huart2；USART3 已从代码删除 |
| interface-contract.md | ✅ 已同步为 USART2 主（2026-08-30）；但**版本号未升**（仍 V0.6） | §2.1、版本历史 Line 303 |
| CUBEMX-INTEGRATION.md | ✅ USART2 主（与固件一致） | Line 16 |
| **冻结记录 analysis.md D-011** | **USART3 主**（"正式 STM32 通信物理层 USART3 PD8/PD9 已冻结 2026-08-25"） | Line 100 |
| **硬件映射待确认表**（资料/） | USART3 主、USART2 备 | Line 17-18 |
| **上电调试速查**（用户上电操作参考） | USART3 PD8/PD9（**按它接线会接错**） | 2026-08-26-上电调试速查.md |
| m144z-m4-tested-pin-pcb-map / pin-timer-allocation / 实测确认引脚表 | USART3 主 | 多行 |
| 载板原理图 wiring-spec / candidate-sketch | USART3 主（J_UART_MAIN=USART3） | 多行 |
| M144Z 引脚总图 / PCB 清单 / Excel | USART3 主 | 审查确认（非 md） |
| SAFETY_FIXES_v2/v3 | **自述"USART3→USART2 文档同步未做 ❌"** | v2:159-163, v3:202 |

### 1.2 结论

- **固件已事实切换 USART2 主**（代码是权威）；但**冻结记录（D-011）、硬件映射表、施工资料、PCB 输入仍指向 USART3**。
- 这是 2026-08-28 就发现、一直未执行的文档同步欠账。
- **必须由用户确认"USART2 为最终物理事实"后**，才能批量同步全部正式材料（涉及"正式通信物理层"的冻结记录变更，属 L4 决策）。

### 1.3 待同步清单（拍板后批量执行）

**A 类 - 冻结/基线记录（改需走变更记录）**：
- `docs/requirements/analysis.md`（D-011 冻结记录 → 更新为 USART2 主 + 变更说明）
- `电控/资料/硬件映射待确认表.md`（主/备 UART 行）
- `docs/design/interface-contract.md`（已同步 §2.1，补版本号 V0.6→V0.7 + 变更记录）

**B 类 - 操作/施工资料（直接影响接线，优先）**：
- `docs/design/2026-08-26-上电调试速查.md`（串口调试整节 → USART2 PA2/PA3）
- `docs/design/2026-08-20-motion-command-list-v1.md`、`2026-08-26-实机标定测试清单.md`
- `docs/design/电控供电接线参考-2026-08-23.md`
- 载板原理图：`carrier-schematic-wiring-spec.md`、`carrier-schematic-candidate-sketch.md`
- 引脚表：`m144z-m4-tested-pin-pcb-map.md`、`stm32f407-pin-timer-allocation.md`、`stm32f407-实测确认引脚表-2026-08-14.md`、`M144Z-M4_CARRIER_IMPORT_README.md`
- 非 md：载板施工单 Word、多份载板 Excel、M144Z 引脚总图、PCB 候选清单（需人工/工具改）
- `集成/deployment/README.md`

**C 类 - 历史文档（保留历史，加"已废弃"标注即可，不批量改写）**：
- `docs/reports/*`（08-14~08-27 的实测/交接报告）、`docs/prompts/*`（交接提示词）

---

## 2. 执行器口径冲突盘点（决定引脚分配前必须先收敛）

| 维度 | 要求汇总（2026-08-26） | 当前固件 | 旧原理图/Excel | 冲突 |
|---|---|---|---|---|
| X/Y | 17HS4401 步进 ×2，80 steps/mm（暂定） | STEP/DIR/EN 三线（PC6/PA7/PA5、PB6/PC7/PD7） | 同左 | 无 |
| Z 升降 | **DS3120MG 舵机**（独立） | **单个 Z 舵机同时实现升降+夹爪联动**（ec_axis_driver.h 注释） | 三轴步进（Z 也是步进） | **严重：舵机 vs 步进、独立 vs 联动** |
| 夹爪 | DS3120MG 舵机（独立） | 并入 Z 舵机联动 | 独立夹爪 PWM + 腕部 PWM | **严重** |
| 限位 | 无独立限位（X/Y 不设）；回零/限位 STM32 负责 | 六路：X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN | 六路限位 | 口径不一 |
| 挡板 | MG996R ×4，4 路 PWM，需 BARRIER_READY 反馈 | 4 路 PWM（PB0/PB1/PF6/PF7），**无位置反馈输入** | — | 反馈缺失（已知） |
| 失电许可 | 需安全回路 | POWER_PERMISSION 位（GPIO 未接） | — | 待接线 |
| 串口 | USART3 主（旧） | USART2 主 | USART3 主 | §1 |

### 2.1 结论

**在形成唯一硬件真值表前，挡板反馈/失电许可的 GPIO 分配一律暂缓**（I/O 映射红线 + 口径未收敛）。真值表至少冻结：执行器数量与联动方式（XY 步进 + 单 Z 舵机联动 or 双舵机独立）、限位实存清单、串口主备、GPIO 占用/废弃/可分配、失电信号源与默认态。

---

## 3. 建议拍板项

1. **USART2 确认为最终物理事实**（是/否）→ 批准后按 §1.3 批量同步 + 冻结记录变更。
2. **执行器口径**：单 Z 舵机联动（固件现状，需机械组确认夹爪能否由 Z 舵机联动驱动）or 双舵机独立（要求汇总）→ 收敛后出唯一硬件真值表。
3. **15 秒监控**：批准滚动 `lastObservableAt` 重构（§3.3 修正版）。
4. **运动标定**：先冻结落点/HOME/PICK/路径（机械组），再测丢步定步频（不批准 3kHz）。
