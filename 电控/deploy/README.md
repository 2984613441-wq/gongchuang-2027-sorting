# 树莓派端部署包（`电控/deploy/`）

> 状态：主机侧闭环模块已就绪（`电控/src/electrical_control/rpi/`），本目录为树莓派端
> **真实链路组装 + 启动配置**。视觉侧 MaixCAM 线格式**未冻结**，部署包把视觉数据源做成
> 注入式/占位，**不写死视觉线格式**。
>
> 依据：`docs/design/2026-08-29-host-side-chain-interfaces.md`（接口契约）、
> `docs/design/2026-08-29-hdmi-screen-arrival-verification.md`（屏规格 §1/§3）。

## 0. 文件清单

| 文件 | 用途 |
|---|---|
| `requirements.txt` | 运行依赖：pyserial / pillow（opencv 等联调项注释为可选） |
| `run_chain.py` | 真实链路组装示例 + 可直接运行的入口骨架（见 §3 组装结构） |
| `install.sh` | 树莓派安装脚本：字体 + venv + pip + config.txt（备份后追加） |
| `ec-chain.service` | systemd 开机自启示例（PORT/IMAGE_DIR/FONT 等占位） |
| `README.md` | 本说明 |

---

## 1. 硬件接线

### 1.1 树莓派 ↔ STM32（USART2）

固件事实：STM32 用 **USART2，PA2=TX / PA3=RX，115200 8N1**（`firmware/main.c huart2`）。

| 树莓派（GPIO 排针） | 方向 | STM32（USART2） |
|---|---|---|
| TXD（如 ttyAMA0 = GPIO14） | → | **PA3（RX）** |
| RXD（如 ttyAMA0 = GPIO15） | ← | **PA2（TX）** |
| GND | ⇄ | GND（**必须共地**） |

要点：

- **交叉接线**：Pi TX → STM32 RX、Pi RX ← STM32 TX，不可直连同名端；
- **共地**：两端 GND 必须连在一起，否则电平参考不一致会收乱码；
- **电平**：树莓派与 STM32 均为 3.3V 逻辑，可直接互连；**严禁**接入 5V 电平；
- **端口名是部署配置**：取决于树莓派型号/overlay（`/dev/ttyAMA0`、`/dev/serial0`、
  `/dev/ttyS0`），用 `--port` / 环境变量 `PORT` 注入，**不写死**。若用 PL011，
  config.txt 需 `enable_uart=1`（本项目 install.sh 不自动改，按需手动加）。

### 1.2 树莓派 ↔ HDMI 屏（1024×600）

按 `docs/design/2026-08-29-hdmi-screen-arrival-verification.md` §2：

- micro-HDMI 转接线插树莓派 4B 的 **HDMI0** 口 → 屏 HDMI 口；
- 屏 **CTouch** 口（兼具供电）接树莓派 USB 口；供电不足时用独立 **5V/2A** 接 POWER 口；
- 树莓派用足 **5V/3A** 适配器（供电不足会闪屏）。

---

## 2. config.txt（1024×600）

install.sh 会**备份原文件后追加**以下配置块（幂等，带 `EC-CHAIN HDMI 1024x600` 标记），
内容与屏验证文档 §3 逐行一致：

```ini
max_usb_current=1
hdmi_force_hotplug=1
config_hdmi_boost=7
hdmi_group=2
hdmi_mode=1
hdmi_mode=87
hdmi_drive=1
display_rotate=0
hdmi_cvt 1024 600 60 6 0 0 0
```

修改 config.txt 后需重启生效。备份文件为 `config.txt.bak.<时间戳>`。

---

## 3. run_chain.py：组装结构与主循环

### 3.1 组装结构（真实链路）

```
PySerialLink(port, baud=115200)          # 真实 UART（pyserial；STM32 USART2 冻结 115200 8N1）
  ├─ 入站：link.receive() 整帧 → PiProtocolGateway.feed_frame → Scheduler 门禁
  └─ 出站：OutboundGateway.send_item_task / send_display_ack → link.send()
Scheduler(FakeTaskSource)                # 视觉数据源占位（MaixCAM 线格式未冻结，注入式替换）
  └─ 显示：HdmiDisplayRenderer(image_loader, frame_output, font_path, task)
```

- 所有 import 均为 `electrical_control.rpi.*`；部署时把 `电控/src` 加入 PYTHONPATH
  （install.sh 会写入 venv 的 `.pth`，无需手动设置）；
- 波特率 115200 已冻结（STM32 USART2），仅作默认值（`--baud` 可改）；
- 图片目录 / 中文字体 / 名称映射 / 帧输出 / 轮次参数全部参数注入，**不写死**。

### 3.2 主循环（每件物料）

```
scheduler.next_task()
  → outbound.send_item_task(task)                      # ITEM_TASK 出站（→ WAIT_MOTION_DONE）
  → 轮询 link.receive() → gateway.feed_frame(frame)
      MOTION_DONE → gateway 已调用 accept_motion_done（→ WAIT_ITEM_RESULT）
      ITEM_RESULT → gateway 已调用 accept_item_result（→ WAIT_RENDER）
      ACK / NACK → 当前 gateway 未建模，事件为 IGNORED，记录后继续
  → build_display_view(content, names)                 # class_id → 本地名称
  → renderer.present(view).complete()                  # RenderReceipt（含 content_crc32）
  → scheduler.accept_render_receipt(receipt)           # WAIT_RENDER → READY
  → outbound.send_display_ack(intent)                  # DISPLAY_ACK 出站
  → 下一件（赛题 R-D04：显示完成后才能分拣下一件）
```

- 入站采用 **select 轮询**（`link.receive()` 自带帧边界解析，返回整帧）；也可改造成
  独立入站线程 + `gateway.feed_byte()` 逐字节喂入（代码注释已标注）；
- 视觉源占位见 `build_placeholder_source()`：线格式冻结后替换为注入式视觉源
  （`FakeVisionSource`/解析出的 `BatchTargets` → `build_item_task_queue` →
  `FakeTaskSource`），调度器只认 `set_permitted()/next_if_permitted()` 接口，无需改调度器。

### 3.3 运行参数

| 参数 / 环境变量 | 说明 | 默认 |
|---|---|---|
| `--port` / `PORT` | 串口设备（真实模式必填） | — |
| `--baud` / `BAUD` | 波特率（STM32 USART2 冻结值） | `115200` |
| `--image-dir` / `IMAGE_DIR` | TF 卡图片目录，`<image_id>.png/.jpg`（真实模式必填） | — |
| `--font` / `FONT` | 中文字体路径；缺省提示安装 `fonts-wqy-zenhei` | 自动探测 |
| `--names-file` / `NAMES_FILE` | `class_id → 名称` JSON（真实模式必填） | — |
| `--round-id` / `ROUND_ID` | 本轮 ID（真实模式必填） | — |
| `--round-task-id` / `ROUND_TASK_ID` | 本轮任务号 u16（真实模式必填） | — |
| `--start-round` | 真实模式先要求输入 `HOME`，确认滑台在负向最里角后才开始 verified round；无交互终端会拒绝 | 关 |
| `--frame-output` / `FRAME_OUTPUT` | `auto` / `fb0` / `file` / `none` | `auto` |
| `--output-dir` / `OUTPUT_DIR` | `file` 模式的 PNG 保存目录 | `frames` |
| `--fake-link` | 开发/冒烟：FakeSerialLink + 模拟 STM32，无需硬件 | 关 |

### 3.4 运行示例

```bash
# 主机冒烟（无硬件，跑通整条闭环）：
PYTHONPATH=电控/src python 电控/deploy/run_chain.py --fake-link --frame-output none

# 树莓派真实运行（install.sh 装好后，venv 已带 .pth）：
电控/deploy/.venv/bin/python 电控/deploy/run_chain.py \
  --port /dev/ttyAMA0 \
  --image-dir /opt/ec-chain/images \
  --names-file /opt/ec-chain/names.json \
  --round-id round-1 --round-task-id 7 \
  --start-round --frame-output fb0
```

`names.json` 示例：`{"2": "红方柱", "4": "蓝圆柱"}`。

---

## 4. 安装

```bash
sudo bash install.sh          # 需 root；会装字体/venv/pip 依赖，并备份后追加 config.txt
```

脚本动作（`set -euo pipefail`）：

1. `apt install fonts-wqy-zenhei python3-venv python3-pip`；
2. 建 `.venv` 并 `pip install -r requirements.txt`；
3. 把 `电控/src` 写入 venv `site-packages/ec-chain.pth`（`electrical_control.rpi.*` 免 PYTHONPATH）；
4. `/boot/config.txt`（或 `/boot/firmware/config.txt`）：**备份后**追加 1024×600 屏配置块。

> 上电 / 接线 / 烧录 / 实机运动属于项目 L4 授权操作，执行前需用户明确批准；本包只提供
> 脚本与文档，不代行授权。

---

## 5. 开机自启（systemd）

```bash
sudo cp ec-chain.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ec-chain
journalctl -u ec-chain -f    # 查看日志
```

单元要点：

- `WorkingDirectory` / `Environment`（PORT / IMAGE_DIR / FONT / NAMES_FILE / ROUND_ID /
  ROUND_TASK_ID）均为**占位**，按实际路径/参数修改；
- systemd 没有现场交互终端，`ExecStart` **不得**带 `--start-round`；服务保持
  `RECOVERY_LOCK` 待命，必须由操作员在现场终端确认 HOME 后以前台命令开始；
- `User=pi` 需在 `dialout` 组（默认）以访问串口。

---

## 6. 当前限制（诚实清单）

1. **视觉数据源占位**：`run_chain.py` 用 `FakeTaskSource` 占位，MaixCAM 的
   `BATCH_TARGETS` 线格式**未冻结**，未写死任何视觉线格式；冻结后替换为注入式视觉源
   （见 `build_placeholder_source()` 注释）。真实模式当前为空源：一轮开始后无任务可派发，
   链路即报告"任务源已耗尽"退出——接入视觉源后可持续供任务。
2. **落料点表未注入**：`drop_point_for_box` 需实测后注入（注入后 ITEM_TASK payload 才
   可序列化，`grip_angle=0xFF`）；DEMO 用占位坐标。
3. **`--start-round` 已有最低限度人工 HOME 门禁**：真实模式在打开串口和视觉线程前
   要求输入精确的 `HOME`。但板子无绝对位置，该输入只能确认操作员已检查，不能自动证明
   机构确实在 HOME；STM32 就绪 / 双节点初始化仍需后续接真实上报，当前仍直接置 True。
4. **ACK/NACK 入站未建模**：当前 gateway 对 ACK/NACK（Command 0x05/0x06）返回
   `IGNORED`，链路以 MOTION_DONE / ITEM_RESULT 驱动；STM32 级 ACK/NACK 建模属未来步骤。
5. **`--frame-output fb0` 已按 fb 真实 bpp 打包（2026-09-17 改）**：写屏前读
   `/sys/class/graphics/fb0/bits_per_pixel` 与 `virtual_size`，16bpp 走 RGB565 小端、
   24/32bpp 走 fbdev 的 `B,G,R[,X]` 内存序，并按 `line_length` 处理行填充；
   **读不到 bpp 就拒绝启动**（以前按 32bpp 直写，在 16bpp 的屏上实测
   `[Errno 28] No space left on device`）。实现见 `src/electrical_control/rpi/display_hdmi.py`，
   实机自检 `python3 -m electrical_control.rpi.display_hdmi --info` / `--bars`。
   **仍未在真机验证**：见 `docs/staging/2026-09-17-屏幕bpp适配-逐文件diff.md`。
6. **UART 使能未自动配置**：`enable_uart=1` 等按树莓派型号/overlay 手动配置（§1.1）。

---

## 7. 参考

- 接口契约：`docs/design/2026-08-29-host-side-chain-interfaces.md`
- 屏规格与 config.txt：`docs/design/2026-08-29-hdmi-screen-arrival-verification.md`
- 集成测试（同构组装参考）：`电控/tests/integration/test_host_side_chain.py`
