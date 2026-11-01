# interface-contract V1.0（草案，2026-11-01）

> **状态：草案，等用户最终确认后才替换 `interface-contract.md` V0.9 的权威地位。**
> 依据：`docs/协议影响分析-20261101.md` + 2026-11-01 用户三项决策
> （①颜色进链路，主相机判色、副相机复核 ②`class_id` 冻结为 code(1..30) ③逐件参数走固件查表）。
> 外层帧**完全不变**：帧头 `0xA5 0x5A`、`version = 0x01`、CRC-16/MODBUS、大端。

---

## 一、本次冻结的三条口径（与 V0.9 的差异）

| # | 项 | V0.9 | **V1.0（本草案）** |
|---|---|---|---|
| 1 | `BATCH_TARGETS` id 字节 | 未写死；生产实现当 `box_id(1..6)` | **`code(1..30)`**；`0` = 判不出（该件拒识）；`31..255` 非法 |
| 2 | `ITEM_TASK.class_id` | 只写 `class_id(1)`，未规定域 | **`code(1..30)`**（形状×颜色联合） |
| 3 | 逐件运动参数（Z 取/放、夹爪闭合）| 无（旧设计夹爪与 Z 同一舵机）| **固件按 shape 查表**，12 字节 `ITEM_TASK` **不变** |

**颜色来源**：主相机（MaixCAM）本地判定 —— YOLO 给 shape、同框 HSV 给 color，直接算 `code` 发出。
副相机（DF200）只做复核：存在性 + 颜色/形状相容 ⇒ `CONFIRMED / CONTRADICTED / UNPROVEN`。

---

## 二、编码定义（唯一权威，别处不得另立）

```
code = (shape - 1) * COLOR_COUNT + color        # COLOR_COUNT = 5
shape ∈ 1..6 : 1=cube 2=cuboid 3=cylinder 4=pentagonal_prism 5=cone 6=tetrahedron
color ∈ 1..5 : 1=red  2=yellow 3=green    4=blue             5=white
code  ∈ 1..30
```

| code | 形状 | 颜色 | code | 形状 | 颜色 | code | 形状 | 颜色 |
|---|---|---|---|---|---|---|---|---|
| 1–5 | cube | red→white | 11–15 | cylinder | red→white | 21–25 | cone | red→white |
| 6–10 | cuboid | red→white | 16–20 | pentagonal_prism | red→white | 26–30 | tetrahedron | red→white |

**完整表**：`code = (shape-1)*5 + color`。例：`11 = 圆柱+红`、`14 = 圆柱+蓝`、`30 = 四面体+白`。

**边界**：
- `code = 0` ⇒ 形状或颜色判不出 ⇒ **只拒识该件**，不得整帧丢弃，不得猜。
- `code ∈ 31..255` ⇒ 非法 ⇒ 拒识该件。
- 解析实现：`电控/src/electrical_control/rpi/vision_ingest.py`
  `code_to_shape_color()` / `shape_color_to_code()`。

---

## 三、三条报文的具体口径

### 3.1 `BATCH_TARGETS`（MaixCAM → 树莓派，7 字节/目标，**长度不变**）

```
data = count(1) + task_id(2, BE) + N × [ id_byte(1)=code + conf(1) + X(2,BE) + Y(2,BE) + angle(1)=0xFF ]
```

- `X/Y`：**像素坐标**（1280×720 域），2 字节大端，与 V0.9 相同。
- `angle`：恒 `0xFF`。
- `id_byte`：**code(1..30)**（V1.0 起）。
- 发送端开关：`--id-mode shape|code`（默认 `shape` = 现状；**切 `code` 才是 V1.0 行为**）。
- 接收端开关：环境变量 `BATCH_ID_BYTE_MODE`，默认 `box_id`（现状），切 `code` 才走 V1.0 解析。

### 3.2 `ITEM_TASK`（树莓派 → STM32，12 字节，**长度不变**）

```
target_seq(1) + class_id(1)=code + image_id(1) + 落料X(2,BE) + 落料Y(2,BE) + angle(1)=0xFF + 抓取点X(2) + 抓取点Y(2)
```

- `class_id`：**code(1..30)**（V1.0 冻结）。
- 落点 X/Y、抓取点 X/Y：0.1mm、有符号 16 位、大端，语义不变。
- `image_id == class_id` 的旧冻结关系**保留**（即 `image_id = code`）。

### 3.3 逐件运动参数（**不上 wire**）

固件按 `shape = (code-1)//5 + 1` 查表：

```c
/* 6 行 × 3 列；数值全部【待实测】 */
static const uint16_t k_motion_by_shape[6][3] = {
  /* shape 1 cube */            { z_pick, z_place, grip_close },
  /* shape 2 cuboid */          { ... },
  /* shape 3 cylinder */        { ... },
  /* shape 4 pentagonal_prism */{ ... },
  /* shape 5 cone */            { ... },
  /* shape 6 tetrahedron */     { ... },
};
```

- 颜色**不影响**该表（同形状件高/尺寸相同）。
- 槽门开合时序由固件 15 步程序负责，不在协议里。

---

## 四、升级清单（两端**不必同时**升级，靠开关灰度）

| 顺序 | 组件 | 改什么 | 切换开关 |
|---|---|---|---|
| 1 | MaixCAM 发送脚本 | `--id-mode code`（判色 + 算 code）| 启动参数 |
| 2 | 树莓派 | `BATCH_ID_BYTE_MODE=code` | 环境变量 |
| 3 | 树莓派 `[BoxMap]` | 键从 `(color,shape)` 改为 `code`（30 项）| 配置文件 |
| 4 | STM32 固件 | 参数表按 shape 查表；`class_id` 直接透传不解释 | 编译烧录 |
| 5 | 显示/日志 | 打印 `code` 时同时打印 `(shape,color)` 便于排查 | 无 |

**回滚**：①发送端 `--id-mode shape` + 接收端 `BATCH_ID_BYTE_MODE=box_id` 一起回；
②固件参数表保留"按旧单值"的兼容分支（若已烧新固件则不用回）。

---

## 五、未闭合项（V1.0 生效前必须完成）

| # | 项 | 阻塞什么 |
|---|---|---|
| 1 | HSV 5 色阈值现场标定（固定补光灯 + 锁曝光/AWB）| `--id-mode code` 的判色准确率 |
| 2 | 6 类 × 3 个 µs 实测（z_pick / z_place / grip_close）| 固件参数表真值 |
| 3 | 副相机覆盖托盘四角验证（H 映射后四角在画面内）| 复核率 |
| 4 | `[BoxMap]` 30 项重新对应（旧表是 3 形状×2，口径已变）| 落点正确性 |

---

## 六、变更记录

| 日期 | 版本 | 变更 | 依据 |
|---|---|---|---|
| 2026-11-01 | V1.0 草案 | id 字节与 `class_id` 冻结为 `code(1..30)`；逐件参数走固件查表；外层帧不变 | 用户三决策 + `docs/协议影响分析-20261101.md` |

---

## 七、实现期发现（2026-11-01，必须记）

**转盘预置原来把 `ITEM_TASK.payload.class_id` 直接当货格号用**：

```python
# deploy/run_chain.py（改动前）
turn_guard.before_dispatch(task.payload.class_id)   # 注释原文：payload.class_id 就是货格号
```

V1.0 把 `class_id` 冻结成 `code(1..30)` 之后，**这条会转错角度**（把 11 当成"11 号格"）。
已修：派件前先用分配器把 `code → box_id(1..6)` 再下发：

```python
tt_box = int(task.payload.class_id)
if slot_allocator is not None:
    tt_box = int(slot_allocator.box_for(tt_box))
turn_guard.before_dispatch(tt_box)
```

默认 `static` + `box_id` 模式下 `tt_box == payload.class_id`，与改动前逐字节一致。
