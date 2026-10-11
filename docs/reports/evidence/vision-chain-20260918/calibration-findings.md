# 视觉现场标定与现行入口证据核对（2026-09-18）

本文件是视觉链路核对的只读证据分项。仅搜索本地主机文档、源码、配置和历史输出；未运行相机程序、未连接设备、未上电、未运动、未执行任何 git 操作。文件行号来自本次读取。最小验证：逐项对应清单要求与现有记录，实际读取 ini，区分代码、交接陈述、原始日志和离线结果。

## 1. 清单逐项结论

`视觉/现场标定清单.md:3-4` 是 2026-08-30 待定项记录，不能当已完成标定表。其三个条目只有待做步骤，无执行人、原始样本、验收结果。

| 清单项 | 本次结论 | 可复核证据 |
|---|---|---|
| 实际光照和白平衡下逐色 RGB 采样、重定分桶、冻结阈值 | **完整完成证据不足；有局部试调交接陈述，不能记为已完成。** | 要求是 `视觉/现场标定清单.md:28-33`；`视觉/src/sorting_vision/color_quant.py:357-359` 仍声明 starter / 待现场白平衡标定，`:362` 实际调用 `rgb_to_hsl`，清单的“HSV”标题不应误读成当前 V6 阈值已经冻结。 |
| V3 旧路线红橙阈值局部实测 | **有用户截图/实测值的交接陈述，非本次独立实机验证。** | `视觉/整合包-2026-09-16/智能分拣-代码整合包-2026-09-16/00_先看这里.md:53-55`：橙圆柱通过、青方体/蓝三棱柱仍 CHECK，红橙边界依据橙 H=4～5、红 H≈177 试调；同处仍要求固定灯光/高度验证。不能扩展为六色准确率或现行 V6 的现场验收。 |
| V6 颜色识别与传输 | **有实机通过的交接陈述；本地未找到对应 153 帧原始接收日志。仅能记录陈述的范围。** | `交付-给朋友/给朋友的任务-2026-09-18.md:4-6` 自述 MaixCAM→Pi 153 帧全部解析、橙圆柱 box6→绿方体 box2；同文件 `:53-61` 仍要求黑色现场调参步骤，`:66-79` 仍要求六色 HSV、ROI、面积/纯度、稳定参数的现场清单。`视觉/src/maixcam_deploy/stage1_color_v6_send.py:182-191` 明示 HSV 是初始阈值、仍需现场核对。不能将“153 帧可解析”推成所有类别/光照/遮挡均验收。 |
| 六盒实际位置与 `(color_id,shape_id)→box_id` 现场冻结、注入 BoxAssignment | **未完成现场闭环。逻辑色→货格表已存在，物理位置/现场校验没有冻结证据。** | 要求是 `视觉/现场标定清单.md:37-46`；V6 逻辑映射在 `视觉/src/maixcam_deploy/stage1_color_v6_send.py:193-196`，六色按青1/绿2/红3/蓝4/黑5/橙6。`docs/交付/2026-09-18/分工提示词-七点拆解.md:208` 明示没有现场冻结对应关系；现读 `电控/deploy/sorting_config.ini:127-149` 六落点全部临时 `(5,5)`，文件中根本没有 `[BoxMap]` 节。`电控/calibration-logs/step2-coordinates.txt:90-118` 六盒测量仍为空格模板。 |
| 置信度两处统一 | **清单列举的两处现已同为 0.50，但完成的是主机配置状态；无现场置信度分布验收证据。** | 清单 `视觉/现场标定清单.md:50-56` 声称 config=0.50、template=0.35；实读 `视觉/src/sorting_vision/config.py:17` 与 `视觉/src/vision_loop_template.py:47` 都是 0.50。0.35 实际仍在 `视觉/src/sorting_vision/single_target.py:53`；采集预标注入口 `视觉/src/maixcam_deploy/capture.py:29` 是 0.30。现 V6 的 wire confidence 是 `color_fraction×100` 合成整数，见 `stage1_color_v6_send.py:59-62`，不是 YOLO 分数，不能直接拿旧 YOLO 阈值宣称校准。 |

上述清单没有一项具备本地原始记录足以证明“现场完整冻结并验收通过”。这不否认已有用户/交接实测陈述，只限定本地主机可以复核到的证据范围。

## 2. 不在旧清单中的坐标标定现状

| 项目 | 状态与来源 |
|---|---|
| 320×320、保持相机位置/高度、托盘负 Y 半轴 | 是本任务冻结边界，`docs/交付/2026-09-18/分工提示词-七点拆解.md:87,97-99`。端点 X57–232px↔−95…+95mm、Y142–232px↔−97.5…0mm 来自现场基线陈述；本次不改动或重做。 |
| 端点粗标 | `电控/calibration_config.ini:29-38` 记录由 `工具/pi_fov_probe.py` 监听、手推物块到底获得两轴端点，误差约 ±5mm，并要求正式九点替代。本地记录属于测量陈述，未找到对应逐帧采样日志或原始尺测记录。`:35`“两轴比例相近→镜无畸变”的推断不构成畸变验收证据。 |
| 相机高度 262mm | `电控/calibration_config.ini:51-54` 写镜头离地475mm−托盘面离地213mm=262mm；是既有测量记录，本次没有独立硬件复核，不建议移动相机。 |
| 正式九点 / 反向 RMS | **明确未做**，`docs/交付/2026-09-18/分工提示词-七点拆解.md:51`；`电控/calibration_config.ini:57,60` 仍是“未标定”“待填”。`:12` RMS≤2mm 是目标，不是结果。 |
| Y 正方向 | **独立实测未确认**，`电控/calibration_config.ini:40-43`；点2任务 `docs/交付/2026-09-18/分工提示词-七点拆解.md:115` 同样要求确认。 |
| 六类真实高度 / 视差补偿 | **当前故意关闭，不是高度已测为零。** `电控/calibration_config.ini:74-88` 说明粗标时置零并在正式九点后恢复真实高度；六类数值均0。配置中的物理解释是现有注释，本次未验证其精度。 |
| 抓取/完成/屏幕全链闭环 | 不是视觉标定已通过的证据。基线 `docs/交付/2026-09-18/分工提示词-七点拆解.md:45,48,50` 仍记录无 MOTION_DONE、抓取点可信度未验证、显示闭环未端到端跑过。 |

`电控/deploy/sorting_config.ini:106` 的 `last_calibration_date=2026-09-15` 是记录字段，且 `:89,105` 明写占位/待实测；它不能替代实测记录。`docs/reports/标定准备完成-最终交付清单.md:277-284,301-317` 的完成度是“准备”，而 `:217-229` 的实机验收仍是空复选框。

## 3. 当前入口：能确认到哪一层

1. **旧 `main.py` 不宜再称当前现场识别入口。** `交付-给朋友/给朋友的任务-2026-09-18.md:116` 明写它是已废弃的老 YOLO 入口。旧目录 README `视觉/src/maixcam_deploy/README.md:3-10,25-28` 仍教运行 `main.py` 并描述 `APP_CMD_DETECT_RES`，与现行 V6 交接不一致，只能作为历史说明。
2. **现行交接路线是 V6 颜色法。** `_incoming/视觉包V6/智能分拣-视觉完整交接包-V6-2026-09-17/00_交接说明_先看这里.md:11-13,28-34` 指向 `stage1_color_v6_stable.py`，颜色映射得到形状/货格、不依赖 YOLO；这个原版只显示/写日志。
3. **本地完整联网单文件是 `stage1_color_v6_send.py`。** `视觉/src/maixcam_deploy/stage1_color_v6_send.py:1-25` 解释其在 V6 上加发送桥；`:166-167` 帧320、内部检测224。独立 `v6_bridge.py:8-13` 是粘贴到 V6 的桥代码说明，不应误写成必须另开一个进程。其 `:30` 仍留有“标定按448”的旧注释，与当前320冻结基线冲突，不予采用。
4. **设备此刻具体进程/脚本哈希仍【证据不足】。** 09-18 的153帧陈述没有本地原始日志、启动命令、板端进程或已部署文件哈希，不能由“本地有发送版”推出“设备此刻正运行该文件”。这不需要连接板子才能完成主机审查：本报告明确保留验证边界。

## 4. 原始输出的分级

能在本地找到的实机原始日志片段是 `docs/交付/2026-09-18/实机定位-链路零入站真因.md:13-18`：

```text
2026-09-18 04:13:12,847 INFO    ec-chain: inbound: BARRIER_READY（STM32 就绪上报，记录即可）
2026-09-18 04:13:16,816 WARNING ec-chain: inbound ACK_ACCEPTED:
2026-09-18 04:13:21,836 INFO    ec-chain: inbound: DUPLICATE（重放/重传帧，已用缓存应答）
```

这是 Pi↔STM32 入站解码证据，不能证明颜色阈值/仓位/坐标精度。V6 包的 `01_当前运行_V6/第一赛段-V6稳定版使用说明.md:50-54` 则清楚说82项是离线检查、包含用户截图回放、**本次未连接摄像头**；截图含旧框文字，不能用于精确轮廓或实时稳定性验收。`05_交接校验/本次校验说明.md:3-10` 也分开了“用户反馈稳定”与“未连接设备复测”。

## 5. 本次实际命令与原始输出

工作目录：`C:\Users\29845\Desktop\工创赛`。以下为本次执行的只读 Python 检查，退出码0；读取历史离线结果不等于重新跑82项。

```powershell
@'
from pathlib import Path
from configparser import ConfigParser
import json
root=Path.cwd()
config=ConfigParser(inline_comment_prefixes=('#',';'))
config.read(root/'电控/deploy/sorting_config.ini',encoding='utf-8-sig')
cal=ConfigParser(inline_comment_prefixes=('#',';'))
cal.read(root/'电控/calibration_config.ini',encoding='utf-8-sig')
print('DropPoints='+json.dumps(dict(config.items('DropPoints')),ensure_ascii=False,sort_keys=True))
print('BoxMap_present='+str(config.has_section('BoxMap')))
print('ObjectHeights='+json.dumps(dict(cal.items('ObjectHeights')),ensure_ascii=False,sort_keys=True))
print('calibration_date='+cal.get('CameraCalibration','calibration_date'))
print('calibrated_by='+cal.get('CameraCalibration','calibrated_by'))
print('camera_height='+cal.get('CameraCalibration','camera_height'))
for folder in ['docs/交付/2026-09-18','工具','交付-给朋友','电控/calibration-logs']:
    found=[p.relative_to(root).as_posix() for p in (root/folder).rglob('*') if p.is_file() and p.suffix.lower() in {'.log','.jsonl','.csv','.out'}]
    print('raw_log_candidates '+folder+'='+json.dumps(found,ensure_ascii=False))
res=root/'_incoming/视觉包V6/智能分拣-视觉完整交接包-V6-2026-09-17/01_当前运行_V6/stage1_color_v6_test_results.json'
data=json.loads(res.read_text(encoding='utf-8-sig'))
print('historical_offline_result_tests_run='+str(data['tests_run']))
print('historical_offline_result_passed_cases='+str(len(data['passed_cases'])))
print('NOTE: read-only inventory; no hardware, no test rerun')
'@ | py -3 -X utf8 -
```

```text
DropPoints={"1": "5.0, 5.0", "2": "5.0, 5.0", "3": "5.0, 5.0", "4": "5.0, 5.0", "5": "5.0, 5.0", "6": "5.0, 5.0"}
BoxMap_present=False
ObjectHeights={"1": "0.0", "2": "0.0", "3": "0.0", "4": "0.0", "5": "0.0", "6": "0.0"}
calibration_date=未标定
calibrated_by=待填
camera_height=262.0
raw_log_candidates docs/交付/2026-09-18=[]
raw_log_candidates 工具=[]
raw_log_candidates 交付-给朋友=[]
raw_log_candidates 电控/calibration-logs=[]
historical_offline_result_tests_run=82
historical_offline_result_passed_cases=82
NOTE: read-only inventory; no hardware, no test rerun
```

扫描范围说明：上述日志后缀检查只覆盖列明目录，不代表全磁盘没有日志；另外对本工作区文档/日志搜索153帧和V6运行记录，只找到本节引用的交接陈述。初次广域 `rg` 搜索报 `电控\_pt: 拒绝访问。(os error 5)`，因此没有宣称“全工作区全部文件已穷尽”。对已找到文件均使用显式路径读取，证据不依赖该不可读目录。

## 6. 自查结论

本分项没有把历史82项离线检查写成实机通过，没有把153帧交接陈述写成完整视觉验收，没有把逻辑货格表写成物理仓位已标定，也没有把配置日期或“准备100%”写成执行完成。所有未找到原始现场记录的事项保留为证据不足。
