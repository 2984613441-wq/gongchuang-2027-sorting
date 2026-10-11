# P2-A · 抓取点语义修正（🔨 实现者）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md` +
> **`docs/design/抓取时序-2026-09-15.md`**（本文的设计依据，**必读**）
>
> 你只做 **P2**。协议改动（`ITEM_TASK` 加字段）是 **P3** 的范围，**你不要动协议**。

---

## 问题（一句话）

固件把**抓取点写死成装置中心 (0,0)**，把**落料点做成参数** —— **反了**。
赛题要求**货物位置随机、不可触碰** → **抓取点必须每件不同，落料点固定**。

**照现状跑**：机构跑到装置中心空夹一次 → **抓空却计成功数 → 分拣数量全错**。

---

## 现状（实测，你自己再核一遍）

```c
/* App/Src/ec_motion_plan.c:65-91 —— 现在的 7 步 */
0: MOVE_XY HOME  -> PICK        PICK 来自常量
1: Z down（张开）
2: Z up（闭合＝夹住）            都在 PICK
3: MOVE_XY PICK  -> PLACE       PLACE = 传入的 (x, y)
4: Z down（张开＝放料）
5: Z up（闭合＝复位）            都在 PLACE
6: MOVE_XY PLACE -> HOME
```

```c
/* App/Inc/ec_motion_plan.h:51-54 */
#define EC_MOTION_PICK_X_MM10 0     /* ← 写死 */
#define EC_MOTION_PICK_Y_MM10 0
```

```c
/* App/Src/ec_app.c:150-162 */
ec_gateway_item_target(&gateway, &x_mm10, &y_mm10);
ec_motion_plan_build(&program, x_mm10, y_mm10);   /* 只有一组坐标 */
```

---

## 好消息：**动作序列本身不用改**

现在的 7 步 **顺序是对的**（HOME→PICK→夹→PLACE→放→HOME）。

**唯一要改的是：PICK 从常量变成参数。**

> **不要**去加"视觉确认"那一步 —— 那是 **组织层**的事（树莓派侧请求新图），
> **不属运动程序**。面板里那 9 步是"含组织动作的完整时序"，
> 而**运动程序只需要这 7 步**。别搞混。

---

## 你要做的

### 1. 改 `App/Inc/ec_motion_plan.h`

```c
/* 删掉 */
#define EC_MOTION_PICK_X_MM10 0
#define EC_MOTION_PICK_Y_MM10 0
```

**改签名**（两个函数都要改，否则头文件自相矛盾）：

```c
bool ec_motion_plan_build(ec_axis_pick_place_t *out,
                          int16_t pick_x_mm10,  int16_t pick_y_mm10,
                          int16_t place_x_mm10, int16_t place_y_mm10);
```

`ec_motion_plan_build_interp()` 同样加两个参数（它没被调用，但签名要保持一致）。

**`EC_MOTION_HOME_X/Y_MM10 = (-800)` 保持不变**（-80.0mm 角落）。

> ⚠️ **顺带修一处过期注释**：`ec_motion_plan.h:8-12` 还写着
> *"the mm->steps ratio (80 steps/mm) is theoretically derived, not measured"*
> —— **已过期**。用户已实测 50 次（台账 **E-07 已消解**）。请把注释改成实测。

### 2. 改 `App/Src/ec_motion_plan.c`

- `step[0]` 的起点从 `EC_MOTION_HOME_*` → **`pick_x_mm10, pick_y_mm10`**
- `step[3]` 的起点从 `EC_MOTION_PICK_*` → **`pick_x_mm10, pick_y_mm10`**
- **双重域检查（1450 ∩ 825）要对【两组坐标都做】**，不能只查落料点
- 更新文件顶部注释（现在写的是 "maps one ITEM_TASK drop coordinate"）

### 3. 改 `App/Src/ec_app.c`

**关键：抓取点的数据来源还不存在**（P3 才会把字段加到协议里）。

**你要做的**是让它**能编译、且在新数据到来前 fail-closed**：

1. 在头文件里声明一个新访问器（**并由你实现一个"取不到"的桩**）：
   ```c
   /* ec_gateway.h 或 ec_app 内部 */
   bool ec_gateway_item_pick(int16_t *out_x_mm10, int16_t *out_y_mm10);
   ```
2. 桩的行为：**返回 false**（表示"还没有抓取点"）
3. `ec_app_start_motion()` 里：
   ```c
   if (!ec_gateway_item_target(&gateway, &place_x, &place_y) ||
       !ec_gateway_item_pick(&pick_x, &pick_y) ||          /* 桩：现在恒 false */
       !ec_motion_plan_build(&program, pick_x, pick_y, place_x, place_y)) {
       ec_app_inject_item_result(EC_RESULT_POSITION_UNREACHABLE);
       return;
   }
   ```

**这样做的结果**：`P3` 没做完之前，固件**不会乱动** —— 拿不到抓取点就报"位置不可达"，
**fail-closed，安全**。这正是我们要的。

4. 把 `ec_app_start_motion()` 的注释从 "drop coordinate" 改成
   "pick + drop coordinates"（现在只提了 drop）。

### 4. 同步测试期望（**注意：测试已归档**）

`电控/firmware/stm32f407_m144z/tests/` 已于 2026-09-15 归档到
`archive/tests-2026-09-15/firmware-tests/`。
`test_motion_plan.c` 与 `test_app.c` 里会有 `ec_motion_plan_build(&p, x, y)` 的调用。

- **若你只是改代码、不跑测试** → 在交付里写明"测试文件已归档，未同步"
- **若你要跑测试** → 从 `archive/` 搬回，改完再跑，**并说明你搬动了哪些文件**

**不要自己决定搬不搬** —— 写清楚你选了哪种，让用户知道。

---

## 验收

- [ ] `ec_motion_plan_build` 与 `..._interp` 签名都改成 5 参
- [ ] `EC_MOTION_PICK_*` 常量已删除，且**全仓 grep 不到遗留引用**
  ```powershell
  Select-String -Path "电控\firmware\stm32f407_m144z\App\*.c","电控\firmware\stm32f407_m144z\App\Inc\*.h" `
    -Pattern 'EC_MOTION_PICK' 
  ```
- [ ] 双重域检查覆盖**两组**坐标
- [ ] `ec_gateway_item_pick` 桩返回 false → 运动被 fail-closed 拦住
- [ ] 编译通过（**这一步要等 P1 修好 Keil 工程**；若 P1 未完成，说明"未编译验证"）

## 交付格式

```
## 改了哪些文件（路径:行号）
## 动作序列有没有变（应该没有）
## 域检查现在覆盖哪些坐标
## ec_gateway_item_pick 桩的行为
## 测试文件：搬回了 / 没搬（选哪个，为什么）
## 编译验证：通过 / 未验证（说明原因）
## 我认为 P3 需要注意的接口点
```

## 红线

- ❌ **不改协议**（`ITEM_TASK` 加字段是 P3 的事）
- ❌ **不加"视觉确认"那一步到运动程序里**（那是组织层）
- ❌ 不上电、不烧录
- ❌ 不动 `ec_*_test.c` 那 4 个台架模块
- ❌ 不改 I/O 映射
