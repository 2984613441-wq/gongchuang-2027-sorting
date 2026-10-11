# 工具 / 电脑端监控 GUI

> **2026-09-15 重写 + 新增总控面板。** 原版（2026-09-09）只文档化了 `monitor_gui.py`，
> 它早于 `monitor_gui_v2.py` 出现，**端口和目标机全是错的**，照它操作会连不上。

---

## 0. 先看这张表：用哪个？

| 程序 | 连谁 | 端口 | 状态 | 能看到什么 |
|---|---|---|---|---|
| **`control_panel.py`** ⭐ | **两个都连** | **9001 + 9002** | ✅ **可用**（2026-09-15 新增） | **总控面板**，4 区：①实时监控（含 9001/9002 两页）②参数 ③**对应表** ④**烧录**。见 §0.1 |
| **`monitor_gui.py`** | **MaixCAM** `172.20.10.2` | **9001** | ✅ **可用**（2026-09-15 起） | MaixCAM **原始**检测结果：类别ID／类别名／**置信度**／**中心像素坐标**；FPS；检测数量。并可**热调参**（改 conf/iou 立即生效）与**按需截图**（存到 MaixCAM 的 `/root/screenshots/`） |
| **`monitor_gui_v2.py`** | **树莓派** `172.20.10.8` | **9002** | ✅ **可用** | **全链路**：①视觉检测结果（经树莓派转发）②树莓派→STM32 的 ITEM_TASK（round_id／task_id／frame_seq／target_seq／class_id／**X·Y 坐标 0.1mm**）③STM32→树莓派的 ITEM_RESULT（结果码／是否成功） |

> **三个的关系**：`control_panel.py` 的监控区**已经包含**上面两个 GUI 的能力
> （9001 页 + 9002 页），另外多了参数、对应表、烧录三区。
> `monitor_gui.py` / `monitor_gui_v2.py` **保留不动**，当作两个更简的单一用途窗口。
>
> `tools/monitor_gui.py` 依赖的 MaixCAM 侧实现是 `视觉/src/maixcam_deploy/main.py`
> 里的 `MonitorServer` 类（2026-09-15 新增，已端到端验证 16/16）。

### 0.1 总控面板 `control_panel.py` 六个区

| 区 | 干什么 | 备注 |
|---|---|---|
| **1 实时监控** | 内分两页：**MaixCAM 原始检测 (9001)** 与 **全链路 (9002)** | 9001 页有**「最后收到帧」与推理停滞告警** —— 「摄像头停了、树莓派还在发指令」这类故障**心跳看不出来**，只能靠这个。9002 页三阶段并排，顺序对不上即可定位断点 |
| **2 参数** | 上：conf/iou 滑块 → **实时下发 MaixCAM，立即生效**（**不改文件**）。下：**配置文件里实际存在的全部条目**，可直接改 | **不写死键名** —— 因为工作区里有**两份键名不同的 `sorting_config.ini`**（见下） |
| **3 对应表** | (颜色, 形状) → 货格，用**中文名**选，不用记数字；六格落点 mm；实时校验 | 颜色词表 11 个、形状词表 7 个，与 `视觉/src/sorting_vision/` 同源 |
| **5 颜色标定** | **本地试算器**：输入 RGB → 立刻显示判成什么颜色 + HSL + 色块；11 项 HSL 阈值可编辑 | ⚠️ 阈值存在 `[ColorThresholds]`，但 `color_quant.py` 目前是**硬编码**的 → **改了线上不生效**，需协作任务 02 接线 |
| **6 屏幕显示** | **用树莓派上的同一个渲染器**（`HdmiDisplayRenderer`）本地出图；**中文字体检测**（能识破"会变方块"的字体）；名称表 7 条可编辑；导出 `--names-file` JSON；一键生成 `run_chain` 启动命令 | 🔴 **字体不对 → 货物名称变方块 → 赛题"信息错误 → 不得分"**。这个区就是用来 10 秒内发现这件事的 |
| **4 烧录** | 顶部有**「上机就绪状态」**一屏概览；① 写本地配置 ② 下发 MaixCAM ③ 生成树莓派 scp/ssh 命令 ④ 导出 `BoxAssignment`+`DropTable` Python 片段 | ①会先备份 `.bak`；校验不过**拒绝写盘** |

**写入策略（重要）**：面板只写 `[BoxMap]` / `[DropPoints]` / `[ColorThresholds]` /
`[DisplayNames]` 这几节，其余内容**逐字节保留**（含注释）—— `configparser` 会吞掉注释，
所以用的是文本级替换。单键修改走 `set_ini_value()`，同样保留行内注释。

**自检与验证**：`py -3 工具/control_panel.py --selftest`（**13 组断言**）；
另有配置读写端到端 17 项、9002 链路 9 项、颜色试算 14 项、**屏幕显示区 16 项**，均通过。

> ⚠️ **⚠️ 工作区里有两份 `sorting_config.ini`，键名不同：**
> - `电控/deploy/sorting_config.ini`（5052B）← **面板默认用这份**，它逐项命中全部冻结参数
> - `电控/deployment/sorting_config.ini`（2393B）← 更早、更薄的一代
>
> 详见 `docs/冲突与决策台账-2026-09-10.md` §7.1（**原判定写反了，已更正**）。

---

## 1. 端口总表（避免再混淆）

| 端口 | 谁在监听 | 用途 | 能不能断 |
|---|---|---|---|
| **8765** | **树莓派** | **生产通道**：MaixCAM → 树莓派 `BATCH_TARGETS` | ❌ **不可中断**，比赛主链路 |
| **9001** | **MaixCAM** | **监控**：原始检测结果 + 调参命令 + 截图命令（`MonitorServer`） | ✅ 可随时断；`ENABLE_MONITOR=0` 可整体关闭 |
| **9002** | **树莓派** | **监控**：全链路广播（JSON，只读旁路） | ✅ 可随时断 |

> ⚠️ 注意 8765 是**树莓派**监听、MaixCAM 连入 —— 不是反过来。
> 旧文档 `工具/README.md:179` 与 `代码包说明.md` 把 8765 说成"MaixCAM 监听端口"，那是错的。
>
> 两条监控都是**只读旁路**，断开或崩溃都不影响比赛主链路。

---

## 2. ⚠️ Python 环境：必须用 `py -3`（本机最容易卡住的地方）

**本机 `python` 指向一个没有 pip 的虚拟环境**：

```
C:\Users\29845\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe   ← 无 pip，装了也没用
```

所以下面这些**一定会失败**：

```powershell
pip install PyQt5            # → failed to locate pyvenv.cfg: ???????????
python -m pip install PyQt5  # → No module named pip
python 工具\monitor_gui_v2.py  # → ModuleNotFoundError: No module named 'PyQt5'
```

**改用 `py -3`（系统 Python 3.14.5，PyQt5 已装好）**：

```powershell
# 1) 装依赖（已确认可用）
py -3 -m pip install -r "C:\Users\29845\Desktop\工创赛\工具\requirements.txt"

# 2) 启动监控 GUI
cd C:\Users\29845\Desktop\工创赛
py -3 工具\monitor_gui_v2.py
```

> 如果 `py` 也不可用，替换为你的系统 Python 全路径，例如 `D:\python.exe -m pip ...`。
> 自检：`py -3 -c "import PyQt5; print('OK')"` 应输出 `OK`。

---

## 3. 怎么用

### 3.0 MaixCAM 侧（原始检测监控，9001）✅ 2026-09-15 新增

**第 1 步：把新的 `main.py` 部署到 MaixCAM**（本仓库里的是最新版）

```powershell
scp C:\Users\29845\Desktop\工创赛\视觉\src\maixcam_deploy\main.py root@172.20.10.2:/root/
```

**第 2 步：在 MaixCAM 上启动**

```bash
ssh root@172.20.10.2
cd /root
python main.py
```

预期输出（多一行 MONITOR）：

```
[MONITOR] 监听端口 9001
```

**第 3 步：电脑端启动 GUI**

```powershell
cd C:\Users\29845\Desktop\工创赛
py -3 工具\monitor_gui.py
```

1. IP = `172.20.10.2`、端口 = `9001`（已是默认值）
2. 点「连接」→ 变绿「已连接」
3. 表格实时显示：类别ID／类别名／置信度／中心X／中心Y
4. 拖滑块 → 点「应用参数」→ MaixCAM 控制台打印 `[MONITOR] 参数已更新: conf=0.50, iou=0.45`
5. 点「保存截图到MaixCAM」→ 图片存到 MaixCAM 的 `/root/screenshots/`，用
   `scp root@172.20.10.2:/root/screenshots/*.jpg ./` 取回

**开关与端口**（环境变量，启动前设）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `ENABLE_MONITOR` | `1` | 设 `0` 完全关闭监控（**比赛时建议关**） |
| `MONITOR_PORT` | `9001` | 监控端口 |
| `SCREENSHOT_DIR` | `/root/screenshots` | 截图目录 |

**性能与安全**：监控是**只读旁路** —— 网络收发全在守护线程，检测主循环每帧只做
一次属性赋值（组 JSON + 交给发送线程），**客户端再慢也不会拖慢检测**；
监控起不来只是打印一行错误，不影响 8765 生产通道。

### 3.1 树莓派侧（全链路监控，9002）

监控由 `电控/deploy/run_chain.py` 启动：

```python
MONITOR_PORT = 9002                       # run_chain.py:101
monitor = MonitorBroadcaster(port=MONITOR_PORT)   # :652
monitor.start(logger)                             # :653
```

启动 `run_chain.py` 后，日志里应出现：

```
[MONITOR] 监控服务已启动: 0.0.0.0:9002
```

### 3.2 电脑侧

```powershell
cd C:\Users\29845\Desktop\工创赛
py -3 工具\monitor_gui_v2.py
```

1. 确认 IP = `172.20.10.8`、端口 = `9002`（已是默认值）
2. 点「连接」→ 状态变绿「已连接」
3. 切到四个标签页查看：
   - **数据流监控**：三个环节（视觉→树莓派、树莓派→STM32、STM32→树莓派）的概览
   - **视觉检测**：Task ID、检测数量、每目标的 序号/类别ID/盒子ID
   - **电控指令**：发给 STM32 的坐标与序号 —— **验坐标传递就看这里**
   - **执行结果**：STM32 回来的成功/失败与结果码

### 3.3 坐标单位

`电控指令` 标签页里的 X/Y 是 **0.1mm 单位**：`x_position=1000` 表示 **100.0 mm**。
坐标系原点 = **装置中心**（2026-09-15 用户裁决：上电位置即原点，上电前人工把机构摆到中心）。

---

## 4. 这个监控能看到什么 / 看不到什么

| 你想要的 | 方案B（当前，9002） | 说明 |
|---|---|---|
| 视觉检测结果（类别、坐标） | ✅ | 经树莓派转发的版本 |
| 树莓派发给 STM32 的指令 | ✅ | 含 X/Y 坐标，可验坐标传递 |
| STM32 的执行结果（成功/失败） | ✅ | 含结果码 |
| **XYZ 实时位置** | ❌ | STM32 目前**不上报**实时位置 |
| **XYZ 电机转速** | ❌ | 同上 |
| 验证「视觉→电控」数据链路 | ✅ | **这正是方案B 的目的** |

> 要看实时位置/转速，需要**改 STM32 固件增加状态上报**（方案A），约需 2 天，涉及
> 通信协议（属项目 L4 红线：改系统间通信协议，需用户批准）。**目前未做。**

---

## 5. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'PyQt5'` | 用了 `python` 而不是 `py -3` | 见 §2 |
| `pip: failed to locate pyvenv.cfg` | 同上，`python` 是坏的 venv | 见 §2 |
| 点连接后一直「未连接」 | ①树莓派没跑 `run_chain.py` ②9002 没监听 ③不在同一网段 | 树莓派上执行 `netstat -an \| grep 9002`，应见 `LISTEN` |
| 连上了但表格没数据 | 正常：只在**有目标/有任务**时才推送 | 放个物块，或看「数据流监控」页状态 |
| 连 MaixCAM 的 9001 连不上 | **该监控未实现**（见 §0） | 用 `monitor_gui_v2.py` |

---

## 6. 安全边界

- 监控是**只读旁路**：`MonitorBroadcaster` 唯一的发送是 `client.sendall(message)`
  （`run_chain.py:189`）**发给监控 GUI**；它**不向 STM32 发任何东西**，不碰 wire 协议。
  断开监控不影响比赛主链路。
- ⚠️ 监控服务绑定 **`0.0.0.0:9002`**（对整个局域网开放，无鉴权）。
  **比赛时建议关掉监控**，或只在调试时启用。
- 监控数据含检测类别与坐标，属项目内部数据；不要连到比赛网络之外的机器。

---

## 7. 文件清单

| 文件 | 说明 |
|---|---|
| `control_panel.py` | ⭐ **总控面板**（PyQt5，4 区）—— 监控(9001+9002)／参数／对应表／烧录。默认指向 `电控/deploy/sorting_config.ini` |
| `monitor_gui.py` | ✅ **MaixCAM 原始检测监控**（PyQt5，连 172.20.10.2:9001）—— 置信度／像素坐标／热调参／截图 |
| `monitor_gui_v2.py` | ✅ **全链路监控**（PyQt5，连 172.20.10.8:9002）—— 视觉 + 指令 + 执行结果 |
| `requirements.txt` | `PyQt5>=5.15.0` |
| `README.md` | 本文件 |

> `control_panel.py` 复用了 `monitor_gui.py` 的 `RecvThread`（同目录 import），
> 所以**两个文件要放在一起**。

---

**最后更新**：2026-09-15（新增总控面板 `control_panel.py`；修正 deploy/deployment 配置判定；接线 `run_chain.py` 读真实落点表）
**相关**：`电控/deploy/run_chain.py`（9002 监控实现 + 落点表接线）、`视觉/src/maixcam_deploy/main.py`（9001 监控实现）、`docs/冲突与决策台账-2026-09-10.md`（冲突登记，见 §7）

---

## 8. 打包 / 交付（修正失败的 zip 命令）

你之前这条命令失败了：

```
zip warning: name not matched: zhandui/
zip error: Nothing to do! (try: zip -r 电控完整交接包_2026-09-15.zip . -i zhandui/)
```

**原因不是 `zip` 不存在**（本机有），而是 **`zhandui/` 这个目录根本不存在** →
`zip` 找不到要包含的东西，于是 "Nothing to do"。

### 正确做法（三种，任选）

**① `tar`（推荐，本机自带，对中文路径最稳）**

```powershell
cd C:\Users\29845\Desktop\工创赛
tar -czf "$env:USERPROFILE\Desktop\电控交接包-2026-09-15.tar.gz" 电控
```

**② `Compress-Archive`（纯 PowerShell）**

```powershell
cd C:\Users\29845\Desktop\工创赛
Compress-Archive -Path 电控 -DestinationPath "$env:USERPROFILE\Desktop\电控交接包-2026-09-15.zip" -Force
```

**③ `zip`（要写对路径）**

```powershell
cd C:\Users\29845\Desktop\工创赛
# 先把要打包的目录写对（用 Get-ChildItem 确认名字），例如：
zip -r "$env:USERPROFILE\Desktop\电控交接包-2026-09-15.zip" 电控
```

### 注意

- **`.tarignore` 已存在**（仓库根），里面列了应排除的目录
  （`历史版本/`、`代码/`、`演示代码/`、`工具/`、`__pycache__/` 等）。
  用 `tar` 时把它当排除清单用即可。
- **别把关整个仓库根打进包**：根目录含 `archive/`（≈4.19 GB，内含 3.31 GB 树莓派系统镜像）。
  只打包你要交付的子目录（如 `电控`、`视觉`）。
- 若确实要打某个目录，先用 `Get-ChildItem -Directory` 确认目录名拼写，
  避免再出现 `name not matched`。
