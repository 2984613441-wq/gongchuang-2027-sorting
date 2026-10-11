# 交付 · 配置文件收口（三份 ini 并存 + 硬编码超时）· 2026-09-18

## 任务
收口三份并存 ini：deploy/sorting_config.ini（权威）、deployment/sorting_config.ini（废弃）、calibration_config.ini（标定链）。让 [Timeout] 不再"写了不读"、统一 conf_threshold 键名、核实 [Safety] 限位警告是否仍成立。**行为必须可证明不变**（fake-link 基线：派发 2 件 / 成功计数 2 / exit=0）。

## 改了什么

### 1. 电控/deploy/sorting_config.ini（权威版）
- `:45-58` —— **[Timeout] 节整体删除**，替换为注释块。原因：`single_item_timeout_s=13` / `total_round_timeout_s=180` 在电控全部 `.py` 中**零引用**（台账 E-31，2026-09-18 复核 grep 仍 0 命中），属"改了不生效"的假配置。超时真实权威：赛规 15s 失活监控 = 固件 `ec_app.c`（台账 E-09）；ITEM_TASK 重传超时 5s = `run_chain.py:893 task_timeout_s=5.0`。**run_chain.py 未改**（二选一选了"删节+注释"，理由见下）。
- `:62-70` —— **[Safety] limit_switch_check 注释更新**（只读复核结论），**值 `false` 未动（L4）**。原警告"固件 POST/HOMING 仍依赖 6 个限位输入（:124-126、:158-171）"经源码复核**已过时**：`ec_startup_sequence.c`（2026-09-16 17:04 修改）文件头 `:12` 明写"不再检查任何限位输入"；POST 仅查 ESTOP + 电源许可（`:123-135`）；HOMING 改为"上电位置即原点"（`:159-168`）。即：**毛病 3 的"上电即炸的雷"已被固件侧 2026-09-16 的同步修改拆除，当前 `limit_switch_check=false` 与固件一致，无冲突**。

### 2. 电控/deployment/sorting_config.ini（废弃版）
- `:12-18` —— 顶部横幅更新：标记已按方案 (a)（台账 E-26 待裁决项）执行——apply_config.py 已改读 confidence_threshold，本文件键名已同步统一；仍属废弃，保留作 apply_config.py 调参链路格式参考。
- `:34` —— `conf_threshold` → `confidence_threshold`（键名统一为 deploy 权威版）。

### 3. 电控/deployment/apply_config.py
- `:64` —— `config.getfloat('Vision', 'conf_threshold')` → `confidence_threshold`
- `:66` / `:68` —— 错误消息文本 `conf_threshold` → `confidence_threshold`
- `:104` —— `config.get('Vision', 'conf_threshold')` → `confidence_threshold`
- `:208` —— 打印文本 `conf_threshold` → `confidence_threshold`

### 未改（明确）
- `run_chain.py` 一行未动（含 :893 task_timeout_s=5.0）。理由：`[Timeout]` 的 13s/180s 语义是"单件/整轮时限"，而 `task_timeout_s=5.0` 是"无应答重传间隔"，两者不同；把重传间隔改成读 13s 会改变真实链路重传行为（违背"行为不变"硬约束）。故选"删 [Timeout] 节 + 注释说明"，消除假配置且行为零变化。
- `calibration_config.ini` 未合并、未改动（归标定链，pixel_to_device.py 专用）。`[WorkspaceLimits]` 保持 2026-09-18 的 X ±105.0 / Y ±95.0（已用 configparser 回读确认）。
- `deployment/apply_config.py` 的 `CONFIG_FILE="/home/pi/sorting_config.ini"` 硬编码未改（树莓派部署路径，主机上不存在属预期）。

## 怎么验证的（原始粘贴）

### 1. pytest（通用头部命令，基线 277 passed）
```
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:PYTHONPATH=(Resolve-Path '电控\src').Path
cd 电控 ; py -3 -m pytest tests -q -p no:cacheprovider
```
输出（改后）：
```
........................................................................................... [ 44%]
.................................................. [ 62%]
........................................................ [ 82%]
................................................                         [100%]
277 passed, 59 subtests passed in 0.95s
```
改前基线：`277 passed, 59 subtests passed in 1.65s` —— **一致**。

### 2. fake-link（基线：派发 2 件 / 成功计数 2 / exit=0）
```
cd 电控 ; py -3 deploy/run_chain.py --fake-link
```
输出（改后，关键行）：
```
INFO ec-chain: ITEM_TASK sent: target_seq=1 class_id=2 image_id=2
INFO ec-chain: inbound: MOTION_DONE accepted
INFO ec-chain: inbound: ITEM_RESULT accepted
INFO ec-chain: 显示完成并确认: target_seq=1 name=红方柱 success=1 → DISPLAY_ACK
INFO ec-chain: ITEM_TASK sent: target_seq=2 class_id=4 image_id=4
INFO ec-chain: inbound: MOTION_DONE accepted
INFO ec-chain: inbound: ITEM_RESULT accepted
INFO ec-chain: 显示完成并确认: target_seq=2 name=蓝圆柱 success=2 → DISPLAY_ACK
INFO ec-chain: 任务源已耗尽（demo 队列），本轮结束
INFO ec-chain: 本轮汇总: 派发 2 件, 成功计数 2
EXITCODE=0
```
改前基线：同样 `派发 2 件, 成功计数 2`，EXITCODE=0 —— **一致**。

### 3. apply_config.py 实际用法（--verify-only）
```
cd 电控 ; py -3 deployment/apply_config.py --verify-only
```
输出（改后）：
```
[INFO] ==================================================
[INFO] 智能分拣装置 - 配置应用工具
[INFO] ==================================================
[INFO] 加载配置文件: /home/pi/sorting_config.ini
[ERROR] 配置文件不存在: /home/pi/sorting_config.ini
EXITCODE=1
```
说明：CONFIG_FILE 硬编码树莓派路径 `/home/pi/sorting_config.ini`，主机（Windows）上不存在属预期，改前改后行为一致（load_config 逻辑未动）。键名改动的有效性另用 configparser 直读验证（见下）。

### 4. 键名统一与文件状态（configparser 直读）
```
deploy [Vision].confidence_threshold = 0.5
deploy has [Timeout] = False
deployment [Vision].confidence_threshold = 0.5
deployment has conf_threshold = False
calib [WorkspaceLimits] = -105.0 105.0 -95.0 95.0
OK
```
- deploy 权威版 `confidence_threshold` 可读、[Timeout] 已删
- deployment 版键名已统一、无 `conf_threshold` 残留
- calibration_config.ini 未动、[WorkspaceLimits] 保持 ±105/±95

### 5. 残留检查
`conf_threshold` 在 `电控/deploy/`、`电控/deployment/` 全部 `.py/.ini` 中：**0 命中**。

## 我没验证什么
- 未在真实树莓派上运行 `apply_config.py`（无 /home/pi 环境、无 systemd）；主机侧仅验证到"配置文件不存在"分支与 configparser 键名读取。
- 未编译/烧录固件；`ec_startup_sequence.c` 结论为**主机侧只读源码复核**（2026-09-16 17:04 版本），不代表 Keil 目标机实构建验证。
- 未跑 `sync_params.py`（UART 调参已放弃，需串口硬件）；其读取点按源码列于对照表。
- pytest 运行会刷新 `tests/` 下既有 `__pycache__`（历史已有，非新增构建产物）；无新文件留在仓库。

## 需要改 X，请批准
1. **遗留（台账 E-26 的另一半）**：`apply_config.py` 仍读 `[Scheduler] task_retry_limit / motion_timeout_scale` 与 `[Network] gateway_host / gateway_port`，这些键只在废弃的 deployment 版存在，**deploy 权威版没有**。若树莓派 `/home/pi/sorting_config.ini` 部署的是 deploy 版（面板 scp），`apply_config.py` 校验会失败。建议下一步二选一：(a) 把 apply_config.py 所需键补进 deploy 权威版（并删 [Debug] 等死键）；或 (b) 明确 apply_config.py 专用 deployment 版、部署流改回 deployment 版。需批准后再动。
2. `sync_params.py`（已放弃 UART 调参，deploy/ 下）读 `[Motion]/[Vision]/[Network]`，键名与 deploy 版一致、不受本次影响；建议后续随 0x20 撞号（E-10）一并归档。

## 对照表（三份 ini 每键 → 读取点）

### A. 电控/deploy/sorting_config.ini —— 权威版（本次后 5 节）
| 节 | 键 | 值 | 被谁读 / 用在哪一行 |
|---|---|---|---|
| [Vision] | confidence_threshold | 0.5 | deploy/sync_params.py:140；MaixCAM main.py 经 env CONF_TH（deployment/apply_config.py:104 生成 environment.conf） |
| [Vision] | iou_threshold | 0.45 | sync_params.py:141；env IOU_TH（apply_config.py:105） |
| [Vision] | model_path | /root/my_models/model_8766.mud | 无 Python 读取（MaixCAM main.py env MODEL_PATH） |
| [Motion] | x_speed_multiplier | 1.0 | sync_params.py:74（已放弃 UART 调参） |
| [Motion] | y_speed_multiplier | 1.0 | sync_params.py:75 |
| [Motion] | acceleration_factor | 1.0 | sync_params.py:76 |
| [Motion] | max_speed_limit | 5000 | sync_params.py:77 |
| ~~[Timeout]~~ | ~~single_item_timeout_s / total_round_timeout_s~~ | 已删除 | 原零引用（台账 E-31）→ 本次删除 |
| [Safety] | emergency_stop_enabled | true | 零读取（记录；固件控制） |
| [Safety] | limit_switch_check | false | 零读取（记录；固件 2026-09-16 已移除限位检查，警告解除） |
| [Safety] | workspace_limit_x_mm / workspace_limit_y_mm | 145 | 零读取（记录；wire 域实际为 ec_motion_plan.h EC_MOTION_WORKSPACE_LIMIT_MM10=1450） |
| [Safety] | reach_limit_mm | 82.5 | 零读取（记录） |
| [Calibration] | steps_per_mm_x / steps_per_mm_y | 80 | 零读取（记录；固件 ec_axis_driver.h EC_AXIS_STEPS_PER_MM_X/Y） |
| [Calibration] | travel_per_leg_mm | 165 | 零读取（记录） |
| [Calibration] | last_calibration_date | 2026-09-15 | 零读取（记录） |
| [Network] | maixcam_host | 172.20.10.2 | sync_params.py:127 |
| [Network] | maixcam_port | 8765 | sync_params.py:128 |
| [Network] | stm32_port | /dev/ttyUSB0 | sync_params.py:212 |
| [Network] | stm32_baudrate | 115200 | sync_params.py:213 |
| （部署副本由面板补写） | [DropPoints] / [BoxMap] | 现场标定 | deploy/run_chain.py:282-306（load_drop_points，[DropPoints]）、:308-330（load_box_map，[BoxMap]）、:799-800（调用）；--config 参数 :418-419 |

### B. 电控/deployment/sorting_config.ini —— 废弃版（4 节，键名已统一）
| 节 | 键 | 值 | 被谁读 / 用在哪一行 |
|---|---|---|---|
| [Vision] | confidence_threshold（原 conf_threshold，本次统一） | 0.5 | deployment/apply_config.py:64（validate）、:104（env 生成）、:208（打印） |
| [Vision] | iou_threshold | 0.45 | apply_config.py:71、:105、:209 |
| [Vision] | model_path | /root/my_models/model_8766.mud | apply_config.py:106 |
| [Scheduler] | motion_timeout_scale | 1.0 | apply_config.py:86、:211 |
| [Scheduler] | task_retry_limit | 2 | apply_config.py:79、:210 |
| [Scheduler] | queue_reorder | false | 零读取 |
| [Scheduler] | display_ack_timeout | 2.0 | 零读取 |
| [Network] | gateway_host | 172.20.10.8 | apply_config.py:107 |
| [Network] | gateway_port | 8765 | apply_config.py:108 |
| [Network] | heartbeat_interval_ms | 500 | 零读取 |
| [Debug] | verbose_logging / save_frames / report_comm | false | 零读取 |

### C. 电控/calibration_config.ini —— 标定链（3 节，不合并）
| 节 | 键 | 值 | 被谁读 / 用在哪一行 |
|---|---|---|---|
| [CameraCalibration] | a11 / a12 / tx / a21 / a22 / ty | 0.0 | src/electrical_control/rpi/pixel_to_device.py:90-91 |
| [CameraCalibration] | camera_height | 262.0 | pixel_to_device.py:95 |
| [CameraCalibration] | calibration_date / calibrated_by | 未标定 / 待填 | 零读取（记录） |
| [ObjectHeights] | 1=40.0 … 6=30.0 | 高度 mm | pixel_to_device.py:98-99 |
| [WorkspaceLimits] | x_min / x_max | -105.0 / 105.0 | pixel_to_device.py:113（2026-09-18 已改，本次未动） |
| [WorkspaceLimits] | y_min / y_max | -95.0 / 95.0 | pixel_to_device.py:114 |

> 默认路径：pixel_to_device.py:47-49 按本文件位置推算 repo_root/电控/calibration_config.ini。
