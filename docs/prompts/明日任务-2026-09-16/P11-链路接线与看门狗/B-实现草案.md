# P11-B · 运行链路接线与看门狗（🔨 实现草案）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md`、
> `../协作-2026-09-15/03-树莓派链路.md`
>
> ⚠️ **本问题的设计由 对方主做**（`A-设计.md`）。
> **你出"改动清单 + 现状核实"**，供设计落地。**不要抢设计。**

---

## 1. 你要核实的现状（**先取证，再给清单**）

### ① `run_chain.py` 的落点/对应表接线（2026-09-15 刚接的）

去读并回答：

1. `load_drop_points()` / `load_box_map()` 的**完整实现**（贴代码 + 行号）
2. `build_socket_source(drop_point_for_box=drop_points.__getitem__)` 里
   **未知 `box_id` 抛的 `KeyError` 会被谁接住？**
   一路追到调用点，判断会不会：
   - 崩掉整个进程？
   - **让某个线程静默死掉**（比赛时无提示停止工作）？
   - **被吞掉后继续用错误坐标发指令**（如果会，**标为最高优先级**）
3. **fail-closed 的时机**：是在读串口**之前**就失败吗？（先开串口再退出会留下已打开的设备）
4. `--config` 默认值硬编码 `/home/pi/sorting_config.ini`，Windows 开发环境读不到 —— 给改进建议

### ② `BoxAssignment` / `DropTable` 的真实消费方

```powershell
Get-ChildItem "C:\Users\29845\Desktop\工创赛" -Recurse -Include '*.py' |
  Select-String -Pattern 'BoxAssignment|DropTable|build_sort_plan|classify_roi_color'
```

**逐条列出**：哪些是**测试**，哪些是**生产代码**。
**本节点已知**：构造点全在测试里 —— **自己去证实或推翻**。

### ③ 15 秒看门狗

```powershell
Get-ChildItem "电控\firmware\stm32f407_m144z" -Recurse -Include '*.c','*.h' |
  Select-String -Pattern '15000|15秒|watchdog|last_observable_ms|no_motion'
```

**回答**：实现了没有？在哪？覆盖哪些状态？`ec_app.c` 里那个 `>= 15000` 的判据管什么？

### ④ 23.2 秒那条"既存风险"

`docs/plans-2026-09-16/02-机构方案A-vs-B.md` 声称"台账 E-20 算出的 **23.2 s 超时**已是既存风险"。
**去台账找 E-20**，看这个数字怎么来的。**如果台账里没有，说明那是它自己算的 → 指出。**

### ⑤ 显示门禁

读 `PendingRender` / `RenderReceipt` / `scheduler` 的代码，回答：

- `DISPLAY_ACK` **谁发谁收**？是树莓派自问自答，还是等 STM32？
- `success_count` **在哪累加**？抓空 / 未到位 / 落料异常时会不会虚增？
- `ITEM_RESULT` 是**真实传感器反馈**还是"流程走完就算成功"？

---

## 2. 你要产出的：改动清单

| 层 | 文件 | 现在 | 要改成 | 行号 | 工作量 |
|---|---|---|---|---|---|
| 树莓派运行时 | `电控/deploy/run_chain.py` | | | | |
| 调度器 | `电控/src/electrical_control/scheduler/` | | | | |
| 显示 | `电控/src/electrical_control/rpi/display*.py` | | | | |
| 固件 | `App/Src/ec_app.c` | | | | （如是 L4，标注） |

---

## 3. 交付格式

```
## ① run_chain 接线现状（含 KeyError 会怎样 —— 最重要）
## ② BoxAssignment/DropTable 消费方全表（测试 vs 生产）
## ③ 15 秒看门狗现状核实
## ④ 23.2s 数字来源核实
## ⑤ 显示门禁：真/假 + success_count 会不会虚增
## 改动清单（表格 + 文件:行号）
## 🔴 我认为必须马上处理的（排序）
## 分歧声明（若与对方的设计冲突）
```

## 4. 红线

- ❌ **不要真的改代码** —— 出清单，等设计定
- ❌ 不上电、不烧录
- ❌ 不碰固件实现（P1/P2/P7）、协议（P3/P8）、配置（P9）、数据集（P10）
