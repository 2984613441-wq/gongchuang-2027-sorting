# 像素到毫米标定接入与主机验证

日期：2026-09-18。范围：L2，树莓派主机纯逻辑。任务书：`.claude/tasks/task-20260918-pixel-calibration.md`。

## 结论与边界

正式组装路径 `run_chain.build_socket_source` 已注入 `PixelToDeviceConverter` 适配器。已标定目标产生毫米抓取点，经现有调度器、出站网关进入 FakeSerialLink，ITEM_TASK 仍为既有 12 字节。未标定、全零或非法配置、未知高度、缺失 box_id、非法像素、补偿后越界均 fail-closed；不猜 (0,0)，不猜 h=0。

这是主机合成参数的验证结果。现有真实 INI 的六个仿射参数仍为占位零值，未伪造实测标定；现场抓取精度、固件、串口、屏幕、电机及运动未验证。用户要求的协议、GPIO、运动计划、速度、Home 和 15 秒监控不在本轮修改范围。

工作树有并行编辑：本轮编写测试期间，另一处工作更新了转换器、主链路组装和部分测试。本记录描述当前合并工作树的可复核结果，不把并行更新冒认为本 Agent 独立完成；保留其修改。本轮补充了 40 个回归用例、语义与类型注解、INI 注释、NumPy 运行依赖及审查证据。近奇异矩阵、无穷帧尺寸、非法工作区在新增测试中出现过红灯，随后在并行更新中修复。

## 字段裁决

`[ObjectHeights]` 的键是 **box_id**，适配器传 `target.box_id`。依据：配置第 50 行、VisionTarget 的 box_id 定义，以及既有 `test_socket_vision_source.py` 中 class_id=2 而 box_id=1/2 的样例。当前校赛解析器确实将同一 id 字节赋给 class_id 与 box_id；这只是该解析分支的数值相等，不能替代逻辑字段语义。

`pixel_to_device(u,v,class_id)` 保留历史关键字兼容，参数文档明确其实际含义为高度表 box_id。新增测试故意设 class_id=2、box_id=3，两类高度分别 0 和 40，锁定查询不能串用。

## 改动行号对照

旧行号来自任务开始时的源文件快照 `.claude/tasks/pixel-calibration-before-20260918.json`，不是混有其他历史修改的 Git HEAD；新行号为本次验证时的工作树。

| 文件 | 原位置 | 当前位置 | 内容 |
|---|---|---|---|
| `电控/src/electrical_control/rpi/socket_vision_source.py` | 92、104、162 | 38、93、104、162 | 可选参数与透传原本已存在；改用现有 GraspPointForTarget 类型，缺省 None 行为不变 |
| `电控/src/electrical_control/rpi/pixel_to_device.py` | 50 | 133 | 默认配置路径去掉重复的“电控”目录 |
| 同上 | 78、89、116 | 41、168、181、229 | INI 行尾注释解析；仿射校验通过后才置已标定 |
| 同上 | 95、109 | 98、195、221 | 相机高度、帧尺寸为有限正值；工作区有限、有序且位于既有协议范围 |
| 同上 | 125、152 | 264、273、298 | 历史 class_id 参数实际使用 box_id；非法像素和缺失/非法高度拒识 |
| 同上 | 155、156 | 238、323、327 | nadir 为图像中心的仿射像，以 nadir 为中心补偿 |
| 同上 | 无 | 344 | 类型明确的 VisionTarget -> mm10 或 None 工厂 |
| 同上 | 177 起 | 371 起 | 自检加入假标定与偏心 nadir，原 640×480 合成样例显式指定帧尺寸 |
| `电控/deploy/run_chain.py` | 100、633、649、901 | 102、387、634、662、686、931 | 导入转换器；CLI/环境配置；正式工厂创建并注入适配器；真实分支传参 |
| `电控/calibration_config.ini` | 55 | 55 | 文档说明缺失高度拒识，以及高度键为 box_id；数值未改 |
| `电控/deploy/requirements.txt` | 22 | 24 | NumPy 从调试可选依赖变为正式链路依赖，最低 1.19.5 |
| `电控/tests/rpi/test_pixel_to_device.py` | 无 | 1、70、113、136、144、177、196、217、249 | 新增 40 个参数化主机用例，覆盖用户 a-d 及正式工厂到出站编码 |

仿射合理性采用明确的粗筛：六参数有限；非全零；相对行列式下限为行向量长度积的 1e-9；每轴行向量长度 0.02 到 20 mm/px；平移绝对值不超过 10000 mm。此范围只拒绝明显异常，不代表现场精度合格。反射、旋转和负行列式均可合法。

## Nadir 手算与配置

按用户要求沿用主点在图像中心的假设。默认帧 320×320，nadir=A(160,160,1)。无主点偏移的实测依据，不另猜一个主点。可选 frame_width/frame_height 仅描述实际标定图像尺寸，不能拿来补偿主点偏移。

合成 A=[[0.5,0,-50],[0,0.5,-100]]，H=200，box_id=3 的 h=40：
- nadir=(30,-20)mm；像素 (180,120) 的仿射像=(40,-40)mm。
- scale=1.25；结果=(30+(40-30)*1.25, -20+(-40+20)*1.25)=(42.5,-45)mm。
- 输出=(425,-450)mm10；旧公式为 (500,-500)。图像中心补偿后保持 (300,-200)mm10。

主链路默认加载 `电控/calibration_config.ini`，亦可通过 `--calibration-config <path>` 或 `CALIBRATION_CONFIG` 指定。改变配置后重启进程重新加载；本次没有运行真实链路入口或部署。

## 实际验证

初次沙箱基线：`2 failed, 297 passed, 2 skipped, 59 subtests passed in 1.36s`。两项失败是 test_framebuffer_pack 的 TemporaryDirectory 读写 PermissionError。改 TEMP 到工作区仍复现；沙箱外自动审批放行后原命令基线为 `301 passed, 59 subtests passed in 1.19s`。没有修改或跳过既有测试。

新增测试首次运行时，工作树已被并行更新：`2 failed, 33 passed in 0.60s`，失败为近奇异矩阵误放行与当时尚未落地的 CLI 参数。补充配置边界测试后：`5 failed, 35 passed in 0.59s`，分别为无穷帧宽/高及三组非法工作区。

最终完整命令，在 `C:\Users\29845\Desktop\工创赛\电控` 目录、沙箱外执行：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
py -3 -m pytest tests -q -p no:cacheprovider
```

等价于用户要求的 `PYTHONPATH=src py -3 -m pytest tests -q -p no:cacheprovider`。实际 stdout：

```text
........................................................................................................................... [ 36%]
.................................................. [ 50%]
...................................................................... [ 71%]
.......................................................... [ 88%]
........................................                                 [100%]
341 passed, 59 subtests passed in 1.41s
```

退出码 0。另在隔离工作目录执行 `py -3 ../src/electrical_control/rpi/pixel_to_device.py`，8 项自检通过，输出 `[PASS] All tests passed`，退出码 0。这是合成数据自检，不是对真实 INI 的标定精度证明。

`git diff --check -- 电控/src/electrical_control/rpi/socket_vision_source.py 电控/deploy/run_chain.py 电控/deploy/requirements.txt` 退出码 0，仅有仓库行尾 LF/CRLF 提示。

## 角色复核

【核心角色】主机工厂、队列拒识、毫米单位、nadir 手算与既有出站编码均有实际测试支持；新增 40 项，完整 341 项通过。

【辅助角色】SocketVisionSource 缺省回调仍为 None，旧路径保留不可序列化行为；注入后 None 表示跳过该件；依赖声明与标定参数文档已对齐。

【监察角色】与任务开始 SHA256 对照，`stm32f4xx_hal_msp.c`、`main.c`、`ec_board_stm32.c`、`vision_ingest.py`、`protocol/item_context.py` 均未改变。配置数值不替换。内部复核置信度 4/5；主机交付证据缺失 0 项，实机验证不在本次范围；逻辑跳跃 0 项。未声称单 Agent 为独立模型审核。

另外用 ConfigParser 结构化比较快照与当前 INI 全部节和值：`PASS: calibration INI data unchanged (comments only).`，退出码 0。

【调度协议】用户授权的本地主机修改与证据交付完成；无外部写入、发布、烧录、上电或实机运动。
