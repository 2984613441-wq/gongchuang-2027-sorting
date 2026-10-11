# 交付 · DSH · 2026-09-18 · 屏幕两段显示（识别到物体 → 分拣成功）

## 任务

在现有屏幕渲染链上增加两段信息，**目的只是验证 7 寸屏能不能正常用**（用户原话），
不追求完整业务语义：
1. 识别到待分拣物体 → 屏幕上显示该物体信息
2. 成功放进转盘/落料位之后 → 显示「分拣成功」

来源：`docs/决定-2026-09-18-演示与正式分离及新增需求.md` §6；触发点由用户本轮拍板
（以 STM32 报**动作完成** MOTION_DONE 为准，不等转盘真的转到位）。

## 改了什么

| 文件:行号 | 改了什么 |
|---|---|
| `电控/src/electrical_control/rpi/display.py:65-82` | 新增 `split_color_shape()`：本地名称（`"青色正方体"`）拆成 `(颜色, 形状)`。**线格式里没有颜色/形状字段**，树莓派只有本地名称表，所以只能就地拆；拆不出返回 `None`。`__all__` 同步（`:118`） |
| `电控/src/electrical_control/rpi/display_hdmi.py:412-425` | 新增模块级 `load_font(font_path, size, ImageFont=None)`；原 `HdmiDisplayRenderer._font`（`:409`）改为**委托**它（行为不变，避免字体逻辑抄两份） |
| `电控/src/electrical_control/rpi/display_hdmi.py:433-597` | 新增 **`TwoStageInfo`**（:453）与 **`TwoStageDisplay`**（:468）：`show_recognized()`（:493，段1）/ `show_success()`（:497，段2）。两段显示**不参与任何协议**：不产 `DisplayContent`、不返回 `PendingRender`、不进 DISPLAY_ACK 闭环。段1 版面：标题 + 「第 N 件」+ 货格号/名称/颜色/形状 四行；段2 版面：「分拣成功」150px 绿字居中 + 副标题。查不到的字段显示 `—`（`:449`），绝不编值 |
| `电控/src/electrical_control/rpi/display_hdmi.py:26-28` | 模块 docstring 补一句：本模块除协议帧外还有一条**不参与协议**的两段显示路径 |
| `电控/deploy/run_chain.py:80-87` | 导入 `split_color_shape` / `TwoStageDisplay` / `TwoStageInfo` |
| `电控/deploy/run_chain.py:766-806` | 新增 `_two_stage_info()`（:774，ItemTaskContext → 载荷）与 `_show_two_stage()`（:793，**屏幕失败只记 ERROR，绝不停链**） |
| `电控/deploy/run_chain.py:873-875` | `run()` 里构造 `two_stage`（与协议帧共用同一个 `frame_output`），并打印实际使用的字体 |
| `电控/deploy/run_chain.py:943` | `success_info` 变量初始化（段2 待显示载荷） |
| `电控/deploy/run_chain.py:961-962` | 新的一件：清掉上一件遗留的段2 载荷 |
| `电控/deploy/run_chain.py:983-986` | **段1 触发点**：ITEM_TASK 发出之后立刻显示物体信息（放在发令之后，不占用发令时间） |
| `电控/deploy/run_chain.py:1033-1046` | **段2 触发点**：`if event == "MOTION_DONE":` —— 只**记下**载荷不画（原因见下） |
| `电控/deploy/run_chain.py:1076-1086` | 段2 落屏：规则帧（`_render_and_ack`，含 DISPLAY_ACK）出完之后再画，且只在结果码 `SUCCESS` 时画 |
| `电控/tests/rpi/test_two_stage_display.py`（新文件，全程 1-150） | 10 个测试：两段各出 1024x600 RGB 且只推一次、段1 标题/序号/四行都有墨迹、换件像素必须变、字段缺失不崩、段2 绿色大标题、居中、`_success_detail` 文案、尺寸校验、`split_color_shape` 三种情形 |
| `工具/pi_two_stage_demo.py`（新文件） | 探针：走真实渲染路径合成两帧并存 PNG；`--fb0` 时复用已验证的 `FramebufferFrameOutput` 直接写屏。**不碰串口/落点表/run_chain** |
| `工具/screen_samples/two_stage_1_recognized.png`、`two_stage_2_success.png`（新文件，1024x600） | 两段各一张样本图，可直接 `pi_blit_png.py --auto 3` 上屏 |

## 两段显示长什么样

版面锚点（`display_hdmi.py:440-449` 的常量）：左列标签 x=48，右列数值 x=260，四行
起点 y=250、行距 88。

**段1 `two_stage_1_recognized.png`（1024x600）**

| 区域 | 内容 | 字号/颜色 |
|---|---|---|
| y=36 | `识别到待分拣物体` | 44px 强调蓝 (88,166,255) |
| y=100 | 一条强调色分隔线（x=48..976） | — |
| y=120 | `第 3 件` | 88px 白 (240,244,250) |
| y=250/338/426/514 | `货格号 3` / `名称 红色三棱柱` / `颜色 红色` / `形状 三棱柱` | 标签 30px 灰、数值 56px 白 |

**段2 `two_stage_2_success.png`（1024x600）**

| 区域 | 内容 | 字号/颜色 |
|---|---|---|
| y=110 | `分拣成功` | 150px 绿 (96,220,120)，水平居中 |
| y=320 | 绿色分隔线 | — |
| y=368 | `第 3 件 · 货格 3 · 红色 · 三棱柱` | 48px 白，居中 |

**版面已用像素审计逐字验证**（见下方命令）：两帧墨迹均未越界（段1 x48..976/y46..580、
段2 x48..976/y143..425，都在 1024x600 内）、四行之间四道空隙均为纯背景（无重叠）、
每个字符串的墨迹包围盒与墨迹像素数**与"同字体同字号单独渲染该字符串"完全一致**
（即屏上就是那串字，不靠肉眼也不靠 OCR）。

## 「分拣成功」的触发点接在哪

**接在 `电控/deploy/run_chain.py:1033`，即主循环的 `if event == "MOTION_DONE":` 分支**
—— STM32 报动作完成那条帧（`Command.MOTION_DONE = 0x22`，方向 STM32→RASPI，帧带空调
由 gateway 校验 task_id 后才到达这里）。**不新增任何协议**，不改字节布局。

落屏时机与闸门：

1. MOTION_DONE 到达时**只记下**载荷（`success_info`，`:1044`），**不立刻画**。
   原因：MOTION_DONE 与 ITEM_RESULT 在假链路里实测相隔 **0 ms**（同一次 poll 里连着处理，
   见下方运行输出 58,040 两行），立刻画出的「分拣成功」会被紧接着的规则帧
   （`_render_and_ack` 的 DISPLAY_DATA 帧）盖掉 → 肉眼根本看不到，验收等于没验。
2. 在规则帧 + DISPLAY_ACK 出完之后（`run_chain.py:1076-1086`）再画 → 「分拣成功」**留在屏上**，
   直到下一件的段1 覆盖它。视觉上就是"分拣完 → 显示成功 → 下一件"。
3. 额外加了 `result_code == 0`（SUCCESS）这一道：结果码要到 ITEM_RESULT 才知道，动作"完成"
   不等于"成功"，失败件不显示「分拣成功」。这是**收紧了触发条件**，不是改变触发源。

## 怎么验证的

本机通用头部（`docs/交接-入口-所有AI必读.md` §2 四行）：

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH=(Resolve-Path '电控\src').Path
cd 电控 ; py -3 -m pytest tests -q -p no:cacheprovider
```

输出（**287 passed / 59 subtests** = 基线 277 + 新增 10，零回归）：

```
287 passed, 59 subtests passed in 0.93s
```

> ⚠️ 本机沙箱的一个坑（不是代码问题，也不是项目问题）：`tests/rpi/test_framebuffer_pack.py`
> 的两个测试要在临时目录里建目录再删；DSH 的 workspace-write 沙箱拒绝向**子进程新建的
> 目录**写入，会报 `PermissionError: [Errno 13] ... tmpXXXX/fb0`（已用最小探针证实：
> 直接写工作区内文件 OK、写 `tempfile.mkdtemp()` 出来的目录被拒）。所以不提权时是
> `2 failed, 285 passed`，**失败的正是这 2 个**，且与本改动无关（改动前同样失败），
> 提权后即得上面这一行。

新增测试单独跑：

```
py -3 -m pytest tests/rpi/test_two_stage_display.py -q -p no:cacheprovider
..........                                                               [100%]
10 passed in 0.24s
```

样本图生成（两段各一张）：

```
py -3 工具/pi_two_stage_demo.py --out 工具/screen_samples
字体: C:\Windows\Fonts\msyh.ttc
已生成 1024x600 RGB: 工具\screen_samples\two_stage_1_recognized.png
已生成 1024x600 RGB: 工具\screen_samples\two_stage_2_success.png
```

整链冒烟（`--fake-link`，无硬件；一次跑出 2 件 × 2 段 = 4 帧）：

```
py -3 电控\deploy\run_chain.py --fake-link --frame-output file --output-dir <scratch> --font C:\Windows\Fonts\msyh.ttc
两段显示字体: C:\Windows\Fonts\msyh.ttc
ITEM_TASK sent: target_seq=1 class_id=2 image_id=2
两段显示已上屏: 1024x600 target_seq=1 box_id=2      ← 段1
inbound: MOTION_DONE accepted
inbound: ITEM_RESULT accepted
显示完成并确认: target_seq=1 name=红方柱 success=1 → DISPLAY_ACK   ← 规则帧（协议闭环未受影响）
两段显示已上屏: 1024x600 target_seq=1 box_id=2      ← 段2（在规则帧之后落屏）
ITEM_TASK sent: target_seq=2 class_id=4 image_id=4
两段显示已上屏: 1024x600 target_seq=2 box_id=4
…（第 2 件同上）
本轮汇总: 派发 2 件, 成功计数 2     退出码 0
```

版面逐字审计（一次性脚本，跑完已删）：两帧 `未被裁: True`、四道行间空隙 `纯背景 OK`、
6+2 个字符串全部 `✓ 与单独渲染一致`、字形自检 `「五」≠「棱」-> True`（真中文，非方块）、
大标题居中偏差 5.0px（CJK 字形在 em 框内左右留白不等所致，1024px 屏上不可见，已写进
`_center_x` 注释）。

## 我没验证什么

- ❌ **没上真机**。一次都没有上电、没有烧录、没有接屏。上屏路径
  （`FramebufferFrameOutput` 按真实 bpp 打包）本次**只走了代码与主机单测**，
  屏上到底出不出这两张图**未验证**。
- ❌ **树莓派 Python 3.9.2 / Pillow 8.1.2 上没跑过**。新增代码回避了 `dataclass(slots=True)`
  与 `Image.Resampling`，PEP 604 注解都在 `from __future__ import annotations` 之后，
  但**只在本机 Python 3.14.5 / Pillow 12.2.0 上跑过**。
- ❌ **树莓派中文字形未验**——样本图用的是本机微软雅黑；wqy-zenhei 的实际字形仍是
  `2026-09-17-树莓派屏幕点亮-实机结论.md` §6 里那条未验证项。
- ❌ **颜色/形状取自哪里，未与视觉侧对齐**。当前是"从本地名称表就地拆"（`青色正方体`
  → 颜色=青色、形状=正方体）。**线格式里确实没有颜色/形状字段**（每目标 7 字节），
  所以这是唯一不猜的办法；但 `[BoxMap]`（(color_id, shape_id) → box_id）那张表如果
  将来填了，应该改成查表而不是拆字符串——见"我需要改 X"。
- ❌ 帧在屏上停留多久、切换有无撕裂/闪烁**未看**（需要真屏 + 相机或肉眼）。
- ❌ run_chain 的段1/段2 延时只在本机测过（每帧约 60ms 合成）；树莓派上会更慢，
  对**15 秒失活预算**的实际占用**未测**。

## 我需要改 X，请批准

1. **`电控/deploy/sorting_config.ini`（或线格式之外的本地表）加一节 `[BoxLabels]`**，
   形如 `1 = 青色, 正方体`，段1 的「颜色/形状」改为查表。
   为什么：现在靠拆名称字符串（`display.split_color_shape`），名称一旦改成
   `"盒1"` 之类就拆不出来；查表比拆字符串可靠，也能与 `[BoxMap]` 共用同一份现场数据。
   不改线格式（L4 不动），只加本地配置。
2. **`工具/pi_screen_probe.py` 已过期**：它仍按 **32bpp** 直写 fb0（`:235-241`），
   并在文案里说 16bpp 会花屏，而实机 fb 就是 **16bpp**（`2026-09-17` 结论 §2.3），
   且它自己实现了一套打包，没有复用已按真实 bpp 打包的 `FramebufferFrameOutput`。
   要不要我把它改成调用 `FramebufferFrameOutput`（与 `run_chain --frame-output fb0` 同一条路）？
   这次我**没有动它**（`工具/**` 改动需申报）。
3. **`docs/决定-2026-09-18-...md` §6 / §11 第 6 条**的「待确认：第 2 段以什么为触发」
   已被你本轮拍板（STM32 报动作完成）。我建议改成"已拍板"，但那是你的决定记录，
   **请批准我改**（正文第 143-144 行 + 表格第 208 行，共两处）。
