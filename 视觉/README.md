# 视觉子系统 V0.1

本目录现提供一个**平台无关、关闭失败**的 YOLO 类推理核心。当前只完成主机侧纯逻辑骨架和 Fake 后端；没有训练模型、连接相机，也没有证明树莓派或 MaixCAM 能运行真实模型。

## 当前部署裁决

训练与部署分为四层：

1. **PC 训练层**：整理数据集、训练模型并导出候选格式。
2. **通用推理契约**：配置、检测对象、过滤/NMS、坐标转换、整批识别、单目标复核和诊断 JSON，位于 `src/sorting_vision/`。
3. **Raspberry Pi 适配层**：可使用 Ultralytics、ONNX Runtime 或以后验证过的其他运行时；V0.1 提供可选 Ultralytics 适配边界。
4. **MaixCAM 适配层**：预留 kmodel runner 与张量 decoder 注入边界，不猜测尚未冻结的 MaixPy API 或输出张量布局。

现有正式架构仍以“MaixCAM 推理、树莓派调度/显示”为旧基线；用户最新意图是不预先冻结部署端。最终在树莓派与 MaixCAM 之间的选择，必须使用同一验证集对模型格式兼容性、精度、延迟/FPS、峰值内存、模型大小、温度和稳定性进行实测。本轮不改写冻结架构或通信协议。

## V0.1 模块

| 模块 | 职责 |
|---|---|
| `config.py` | 模型路径、类别表、阈值、输入尺寸、设备与最大检测数的显式配置和校验 |
| `types.py` | 原始框、内部检测结果、整批结果、单目标复核结果和错误对象 |
| `backends/` | Fake、可选 Ultralytics、ONNX Runtime、MaixCAM/kmodel runner/decoder 适配边界 |
| `postprocess.py` | 置信度过滤、类别感知 NMS 和重复目标关闭失败 |
| `coordinates.py` | 像素诊断坐标与显式注入的仿射标定接口 |
| `pipeline.py` | 整批识别和单目标复核 |
| `single_target.py` | 单目标推理循环：接入桌面模板循环结构，强制恰好一个目标并失败关闭 |
| `export.py` | 可读 JSON 诊断导出；明确不是正式 wire codec |
| `benchmark.py` | 两个候选部署端使用同一验证集的可比较基准记录 |

## 单目标推理循环

`single_target.py` 提供 `SingleTargetLoopConfig`、`SingleTargetResult`、
`process_single_target_frame` 和 `run_vision_loop`，用于固定单相机、单目标场景。
`labels` 按 tuple 索引映射 `class_id`（`labels[class_id]`）；未配置类别表时任何检测都
失败关闭。`hmirror`/`vflip`/`rotation`/`source`/`camera_index` 本轮仅校验、保留，
待真实相机/图像适配器冻结后再接线。`run_vision_loop` 支持注入 `coordinate_transform`
标定；未标定时成功检测仍 `motion_ready=false`。`min_confirm_frames=1` 默认单帧即上报；
设为 N 时要求连续 N 帧检测到同一 `class_id` 才上报。达到 N 后，后续同类帧继续逐帧
上报，由下游按需去重；失败帧仍会上报并重置计数。若 `max_frames` 在凑满 N 帧前耗尽，
未确认目标不会上报。
成功行文本格式与桌面模板一致，失败行带错误码
（`frame_id:none:<error_code>:<elapsed_ms>ms`），JSON 继续带
`diagnostic_only=true`、`wire_codec_frozen=false`、`motion_ready` 和
`confidence_percent`。该模块不生成 wire 帧，也不输出运动指令。

## 关闭失败规则

以下情况返回 `status="failed"`、空检测列表和明确错误码，且 `motion_ready=false`：

- 模型文件或可选运行时缺失；
- 输入缺失、损坏或尺寸非法；
- 类别不在数据集类别表中；
- 置信度不是有限数或超出 `[0, 1]`；
- 检测框超出输入图像；
- 同类别高重叠重复目标（默认由 NMS 识别后拒绝，而不是静默选一个）；
- 过滤后无检测；
- 一帧出现多个互不重叠目标（违反单目标约束）；
- 未配置类别表且出现任何检测；
- 坐标变换结果超出显式配置的标定边界；
- 单目标复核找到零个或多个期望类别候选。
- 后端未知异常映射 `UNEXPECTED_BACKEND_FAILURE`，核心处理段未知异常映射 `INTERNAL_CORE_ERROR`。

未注入经验证标定时，成功检测只输出 `image_pixel` 中心点，仍然 `motion_ready=false`。V0.1 没有任何机械中心点、类别、工作区坐标、相机参数或标定矩阵默认值。

## 内部结果与现有字段语义

整批结果保留原视觉说明所需语义：任务号、目标数量、类别 ID、置信度、坐标以及可扩展的角度语义。当前内部对象使用 `0..1` 浮点置信度，诊断 JSON 额外给出 `confidence_percent`；是否量化为 `uint8 (0-100)` 属于未来 wire codec 的职责。

坐标对象始终携带 `frame`、`unit`、`calibrated` 和可选 `calibration_id`。物理单位、端序、角度编码和 `BATCH_TARGETS` / `TARGET_REACQUIRE_RSP` 正式载荷尚未冻结，因此 V0.1 不编码串口帧、不定义 CRC/外层帧/波特率、不把 JSON 当作正式协议，也不控制执行器。

每个诊断 JSON 都明确包含：

```json
{
  "schema_version": "vision-diagnostic-v0.1",
  "diagnostic_only": true,
  "wire_codec_frozen": false,
  "motion_ready": false
}
```

## 运行纯逻辑测试和示例

在仓库根目录执行：

```powershell
python -m unittest discover -s 视觉/tests -v
python 视觉/examples/fake_demo.py
```

两者只使用 Python 标准库，不下载模型、不联网、不访问相机或硬件。示例没有物理标定，因此识别状态可为成功，但 `motion_ready` 必须为 `false`。

## 参考环境核验（2026-08-21）

`智能分类垃圾桶全套文件.zip` 与拆分后的 `开源参考/` 位于桌面仓库根目录
（`C:\Users\29845\Desktop\工创赛\`），未纳入当前 worktree；若在别处运行，需另行
提供这些产物。原包自带 `venv` 为 Python 3.10.8（约 1.35 GB / 27,220 个文件），含
torch、torchvision、opencv-python、numpy、pandas、matplotlib、scipy、
tensorboard 等，但未发现 `pyserial` 与 `PyQt5`，而参考 GUI/串口脚本会 import
这两个包，因此原 `venv` 不能直接作为完整运行环境。

建议运行参考代码时按桌面仓库根目录的 `开源参考/视觉/requirements.txt` 新建环境，并
补装 `pyserial` 与 `PyQt5`；不要依赖原包 `venv`。本项目 `sorting_vision` 核心只依赖
Python 标准库，上述核验仅约束参考代码运行环境。

## 今晚数据集接入清单

当前伪数据集已经完成90张有效图片标注和来源隔离划分，类别固定为 `0=green_block`、`1=blue_block`。train/val/test 分别为60/17/13张，同一视频来源不跨集合。新增照片中的橙色方块由用户明确裁决为非目标干扰物，不新增类别、不画框。1 epoch YOLO11n CUDA/AMP 冒烟训练已经通过；PyCharm 30 epoch 操作见 `TRAINING.md`，完整证据见 `docs/reports/2026-08-18-vision-dataset-training-prep-validation.md`。

当前仍需在训练前确认或生成：

- `dataset.yaml`（或实际等价配置文件）及它引用的路径；
- 类别表在所有标签和 `data.yaml` 中保持 `0=green_block`、`1=blue_block`；
- 标注格式和版本（实际工具导出的格式，而不是仅写“YOLO”）；
- 至少数张原始样例图及对应标注，用于解析与坐标边界检查；
- 训练/验证/测试集划分方式和数据集版本标识；
- 训练使用的模型家族、仓库/包版本、预训练权重来源；
- 训练输入尺寸、颜色通道顺序、归一化与 letterbox 规则；
- 训练产物及候选导出格式（具体权重、ONNX、kmodel 或其他；不限于其中任一种）；
- 后处理参数：置信度阈值、NMS IoU、最大检测数；
- 目标部署候选的系统版本、运行时版本、可用内存和加速能力；
- 用于部署对比的固定验证集及精度指标定义。

所有外部 YAML、标注、图片和模型都按不可信输入处理：先在隔离目录检查文件类型、路径引用、类别表和样例解析，不执行数据集或模型附带的未知脚本。

## 部署评估表

`benchmark.py` 提供统一记录对象。树莓派和 MaixCAM 必须使用相同的 `validation_set_id`、样本顺序和精度指标定义。

| 指标 | Raspberry Pi | MaixCAM | 判定要求 |
|---|---:|---:|---|
| 模型格式与运行时版本 | 待实测 | 待实测 | 能加载且输出能被同一契约解析 |
| mAP/准确性指标 | 待实测 | 待实测 | 指标名称、IoU/阈值和数据集版本一致 |
| 平均/P95 单帧延迟、FPS | 待实测 | 待实测 | 同批次、预热和计时边界 |
| 峰值内存、模型大小 | 待实测 | 待实测 | 同一口径并记录实际部署文件 |
| 峰值温度 | 待实测 | 待实测 | 记录环境和散热条件 |
| 稳定性时长/失败数 | 待实测 | 待实测 | 连续运行且记录失败样本 |

V0.1 的主机 Fake 基准只能验证字段与流程，不可作为树莓派或 MaixCAM 性能结论。

## 仍未验证

- “Unal”数据集内容与格式；
- 任何真实模型的精度；
- Ultralytics、ONNX、kmodel 或其他格式在目标设备上的兼容性；
- Raspberry Pi 或 MaixCAM 的真实延迟、内存、温度与稳定性；
- 相机采集、曝光、补光、畸变与物理标定；
- 串口、屏幕、STM32、电机和整机闭环。
