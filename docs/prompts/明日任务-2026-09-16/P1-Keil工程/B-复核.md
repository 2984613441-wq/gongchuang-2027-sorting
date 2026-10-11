# P1-B · Keil 工程修复（🔍 独立复核者）

> **先读** `../协作-2026-09-15/00-总览与交接规则.md`。
>
> 你是 **P1 的复核者**，对方是执行者。**不要相信对方的清单** ——
> **你必须自己从源码重新推一遍**，然后和它的产出比对。
> **只复核，不修改**。

---

## 0. 背景（一句话）

`ec_app.c`（在 Keil 工程里）调用的多个函数定义在**没被加进工程**的文件里 →
**undefined reference → 链接失败 → 烧不进板子**。

执行者（A 份）被要求补 **6 个**文件进 `.uvprojx`。

---

## 1. 🔍 你要独立验证的第一件事：**清单对不对**

**不要**直接读 对方的清单然后点头。**自己跑**：

```powershell
# 工程里到底列了哪些文件
$uv = "电控\firmware\stm32f407_m144z\MDK-ARM\diankongv1.0.uvprojx"
(Select-String -Path $uv -Pattern '<FileName>([^<]+)</FileName>' -AllMatches).Matches |
  ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique

# 磁盘上实际有哪些
Get-ChildItem "电控\firmware\stm32f407_m144z\App\Src" -Filter *.c
Get-ChildItem "电控\stm32_logic\src" -Filter *.c
```

然后自己回答：

| 问题 | 你要给的答案 |
|---|---|
| 工程内条目数是多少？ | ______（执行前应为 **35**，执行后应为 **41**） |
| 磁盘上有、工程里没有的 `.c` 有几个？分别是哪些？ | ______ |
| **执行者加的 6 个对不对？有没有漏、有没有多？** | ______ |
| **是否存在执行者没发现、但同样会造成 undefined reference 的文件？** | ______ |

---

## 2. 🔍 独立验证第二件事：**真的一定链接失败吗**

执行者的核心论据是"`ec_app.c` 调用了这些函数"。**你要自己核实**：

1. 在 `App/Src/ec_app.c` 里 grep 所有这些符号，**逐条列出 `文件:行号`**：
   - `ec_motion_plan_build`
   - `ec_axis_driver_*`
   - `ec_startup_sequence_*`
   - `ec_demo_*`
   - `ec_gateway_*` / `ec_proto_*`
2. **对每个符号确认：它的定义确实在"没进工程"的文件里**，
   而**不是**在某个已进工程的文件里（防止执行者搞错）。
3. **特别检查 `ec_app.c:539` 的 `ec_demo_poll`** ——
   这是**无条件调用**（不在任何 `#if` 里），是最硬的证据。

**如果发现执行者的清单**：
- **少了** → 你补出来，这会让 Rebuild 再失败一次
- **多了** → 说明有冗余，指出是哪个

---

## 3. 🔍 独立验证第三件事：**4 个台架模块与 5 个开关**

1. 自己确认 `ec_servo_test.c` / `ec_group_test.c` / `ec_barrier_test.c` / `ec_step_test.c`
   **里面到底有没有 `#if`**（执行者说"一个都没有"）。
   ```powershell
   foreach($f in @('ec_servo_test.c','ec_group_test.c','ec_barrier_test.c','ec_step_test.c','ec_diag.c')){
     $t = Get-Content "电控\firmware\stm32f407_m144z\App\Src\$f" -Raw
     "$f : " + ([regex]::Matches($t,'(?m)^\s*#\s*(if|ifdef|ifndef)')).Count
   }
   ```
2. 确认 `ec_diag.c` 的 `#else` 分支（约 `L603-609`）**是否真的给了
   `ec_diag_init` / `_process_line` / `_on_rx_byte` / `_poll` / `_tick` 五个空实现**
   —— 少一个，置 0 就会链接失败。
3. 确认 `ec_diag_port_write` 的定义位置，以及它的**外部调用点是否都在 `#if` 里**。

**这三条合起来决定"置 0 到底安不安全"** —— 这是执行者最容易想当然的地方。

---

## 4. 🔍 你要给出的判断

```
## 清单核对
执行者的 6 个：✅ 对 / ❌ 有问题（说明）
漏掉的：______
多出的：______

## undefined reference 是否成立
结论：______
关键证据（文件:行号）：______

## 置 0 是否安全
结论：______
三个空壳齐全吗：______
ec_diag_port_write 的位置与调用点：______

## 我认为 Rebuild 还会失败的地方（如果有）
______

## 我明确无法判断的
______
```

---

## 5. 红线

- ❌ **只复核，不改任何文件**（包括 `.uvprojx`）
- ❌ 不上电、不烧录
- ❌ 不要顺手去改 `ec_motion_plan.c` / `ec_app.c` —— 那是 **P2** 的范围
- ❌ 不要动那 4 个台架模块（用户明确说先别删）
