# P8-A · 协议一致性清理（⭐ 主设计）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md`、
> `../协作-2026-09-15/04-架构与安全审查.md`、
> **`docs/design/interface-contract.md`**（V0.8，命令字权威）、
> `docs/冲突与决策台账-2026-09-10.md` 的 **E-10 / E-11 / E-12 / V-07**
>
> 你是本问题的**主设计者**。对方出实现草案。你出**设计与裁决**。

---

## 要清的四处协议不一致

### ① E-10：命令字撞号（台账标为"最严重"）

**冻结契约**：`0x10`=BATCH_TARGETS、`0x20`=BARRIER_READY、`0x21`=ITEM_TASK、
`0x22`=MOTION_DONE、`0x25`=DISPLAY_ACK…

而调参方案用 **`0x20`** 发参数 → **与 `BARRIER_READY` 撞号**。

**本节点已初步查明**：撞号的两侧（`电控/deploy/sync_params.py` 与
`App/Src/ec_config_handler.c`）**都没有在跑**（后者是死代码，只 include 自己）。

**你要做的**：
1. **独立核实**这个结论（别信我）
2. 裁决：**整条废弃** 还是 **重新分配命令字**？
3. ⚠️ 注意：**挡板已取消**（用户 2026-09-15 裁决），`BARRIER_READY` 这个命令字**还有存在意义吗**？

### ② E-11：帧格式绕过 CRC16

调参帧用 `[0xA5][cmd][len][payload][和校验]`，**绕过了冻结契约的 CRC16**。

**你要做的**：核实 → 裁决（修正 / 随①一并废弃）。

### ③ E-12：协议版本不一致

代码里同时存在 **V0.4**（`protocol/__init__.py:1`、`codec.py:10`、`ec_protocol.h:8`）
与 **V0.5**，而契约是 **V0.8**。

**你要做的**：给统一方案（谁改谁、或者版本号本来就不是这个含义 —— **先核实语义**）。

### ④ V-07：`MODEL_PATH` 三方不一致

| 出处 | 值 |
|---|---|
| `视觉/src/maixcam_deploy/main.py:26` | `model_8766.mud` |
| `视觉/src/maixcam_deploy/capture.py:31` | `model_8629.mud` |
| `maixcam_deploy/README.md:15` | `model_8629.mud` |

🔴 **已知关键事实（2026-09-15 实测）**：
- **`model_8766.mud` 的 `model_type = yolov8`**，在 MaixCAM 上**加载成功**，
  `input 448x448`、`labels num=7` → **与 `main.py:375` 的 `nn.YOLOv8` 匹配**
- **`model_8629.mud` 的 `model_type = yolo11`**，来源是 `block_yolo11n` 训练线 → **不匹配**

**你要做的**：给出统一方案 + 依据。**capture.py 和 README 该改成什么？**

---

## 你要产出的一张表（后续协议变更都要用它）

**全部已用命令字表**：命令字 / 含义 / 定义位置 / 是否在用 / 是否可回收。

自己跑：
```powershell
Select-String -Path "docs\design\interface-contract.md" -Pattern '0x[0-9A-Fa-f]{2}'
Select-String -Path "电控\stm32_logic\src\*.c","电控\src\electrical_control\protocol\*.py" -Pattern '0x[0-9A-Fa-f]{2}'
```

**这张表是 P3（协议方案 B + request_id）选命令字的前提** —— **做完交叉给 P3**。

---

## 交付格式

```
## ① E-10 撞号 —— 独立核实结论 + 裁决（废弃 / 重分配）
## ② E-11 CRC 绕过 —— 核实 + 裁决
## ③ E-12 版本号 —— 先核实语义，再给统一方案
## ④ V-07 MODEL_PATH —— 统一方案 + 依据
## 全部已用命令字表（含空闲值）
## 给 P3 的交叉输入（哪些命令字可用）
## 🔴 需要用户批准的 L4 动作清单
## 我明确无法判断的
```

## 红线

- 🔴 **只出裁决与提案，不改协议文件**（`interface-contract.md` 是 L4 的产物）
- ❌ 不上电、不烧录
- ❌ 不要越界去改固件实现（P1/P2/P7）或视觉（P6）
