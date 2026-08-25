# MaixCAM 部署事实与集成缺口 — 2026-08-23

> 来源：用户现场提供（2026-08-23）。本文件只记录事实与缺口，不猜测 MaixPy API、
> 张量布局、串口帧、CRC 或波特率。

## 已确认事实

- 设备：MaixCAM（主机名 `maxicam-544c.local`，SG2002 系列）
- 系统版本：`maxicam-2026-01-24-maxipy-v4.12.5`
- MaixPy：`4.12.5`（v4，不是 K210/v0.6）
- 摄像头：GC4653，无 IMU
- 存储：28.78 GiB；CPU 850 MHz；NPU 700 MHz
- 训练路径：MaixHub 云端训练，届时导出模型

## 由此确定

- runner 必须走 MaixPy v4 的 `maix.nn` API；`视觉/src/vision_loop_template.py` 里
  的 K210 `kpu` 模板作废。
- 视觉推理端固定为 MaixCAM；树莓派保持调度/显示职责。

## MaixHub 首次导出事实（2026-08-25，task 317442）

- 模型格式：导出 `.mud` 与 `cvimodel`。
- 模型家族：经典 YOLOv5s；MaixPy 端应使用 `nn.YOLOv5` 解码器。这是本次
  MaixHub 在线训练产物，不代表最终模型路径。
- 模型输入尺寸：448×448；`InferenceConfig` 和
  `MaixPyYoloBackend` 默认值已同步为 448。
- 类别表与顺序（以此为准）：
  `0=cube`、`1=cuboid`、`2=cylinder`、`3=hexagonal_prism`、
  `4=pentagonal_prism`、`5=square_pyramid`、`6=triangular_prism`。
- 训练结果：100 epoch 最佳 `val_acc=0.4801`，验证集 35 张。
  `cuboid=0.0`、`triangular_prism=0.2424`，精度尚未通过实机门槛。

## 当前模型包（2026-08-25，task 317458）

- 本地压缩包：`C:\Users\29845\Downloads\model-317458.maixcam.zip`
- zip SHA256：`C81B1CAA4D9831AA149014B02C8D3A0B7A657660C86E75F319FEBF3EDCC68319`
- 包内文件：`model_317458.mud`、`model_317458.cvimodel`、`main.py`、
  `app.yaml`、`report.json`。
- `model_317458.mud` 明确 `model_type = yolov5`、输入 `rgb`、`mean=0`、
  `scale=1/255`，`labels` 顺序为 `cube, cuboid, cylinder, hexagonal_prism,
  pentagonal_prism, square_pyramid, triangular_prism`。
- `report.json` 输入尺寸：`448×448`；输出三支为 YOLOv5 标准特征图。
- `main.py` 参考加载方式为 `nn.YOLOv5(model=model_path)`，检测参数
  `conf_th=0.5`、`iou_th=0.45`。
- 训练结果：100 epoch 最佳 `val_acc=0.4241`。分类别：
  `cube 0.6364`、`cuboid 0.2909`、`cylinder 0.6364`、
  `hexagonal_prism 0.0529`、`pentagonal_prism 0.4545`、
  `square_pyramid 0.5411`、`triangular_prism 0.3566`。
- 结论：这是当前可上机联调的模型，但 `hexagonal_prism`、`cuboid`、
  `triangular_prism` 仍明显偏弱，不能作为最终分拣模型。

## 本地训练与 MaixCAM 转换路径（2026-08-25 补充）

- MaixCAM 模型转换页支持 `yolov5u`、`yolov8`、`yolo11`、`yolo26` 的
  `detect` 模型。
- 本地训练推荐 `yolo11n.pt`，因为现有工程已具备 YOLO11 权重，且
  `MaixPyYoloBackend` 直接支持 `yolo11`。
- YOLOv8n、YOLOv5u 可作备选；`yolov5u` 与 `yolo26` 的 MaixPy 适配需等
  转换产物实测后再补，不提前猜测 API。

## 本地 YOLO11n 首次训练产物（2026-08-25）

- 权重：`D:\AAAdesktop1\shijue\ultralytics-8.3.163\runs\block_detector\block_yolo11n_e100\weights\best.pt`
- ONNX：`D:\AAAdesktop1\shijue\ultralytics-8.3.163\runs\block_detector\block_yolo11n_e100\weights\best.onnx`
- ONNX 输入 `[1, 3, 448, 448]`，输出 `[1, 11, 4116]`，opset 18。
- 数据集：train/val/test = 320/41/41，类别顺序与 MaixHub 一致。
- 独立 test 集：mAP50 0.873，mAP50-95 0.656；`hexagonal_prism`、
  `triangular_prism`、`pentagonal_prism` 仍偏弱。
- 下一步需在 MaixCAM 转换页验证 YOLO11 + opset 18 是否可接受。

## MaixCAM 转换成功产物（2026-08-25，task 8622）

- 压缩包：`C:\Users\29845\Downloads\maixhub-model-convert-maixcam-8622.zip`
- 包内文件：`model_8622.mud`、`model_8622.cvimodel`。
- `model_8622.mud`：`model_type = yolo11`、`type=detector`、`input_type=rgb`、
  `mean=0`、`scale=1/255`，labels 顺序正确。
- 部署代码应使用 `nn.YOLO11`，对应 `MaixPyYoloBackend(family="yolo11")`。
- 当前仍未在 MaixCAM 真机验证，模型弱类仍需补数据后再冻结正式版本。

## 视觉第二轮本地训练（2026-08-25，638 张）

- 数据：`训练1 (1).zip`，638 张，是旧 402 张超集。
- 数据集：`block_dataset_v1_7class_round2`，train/val/test = 510/64/64。
- 权重：`block_yolo11n_e100_round2\weights\best.pt`。
- ONNX：`block_yolo11n_e100_round2\weights\best.onnx`，opset 17、
  静态 `[1,3,448,448]`、10.52 MB。
- 独立 test 集：mAP50 0.913 / mAP50-95 0.706，优于第一轮 0.873。
- 仍偏弱：`pentagonal_prism` P 0.629、`cube` P 0.738、
  `triangular_prism` R 0.814。
- 下一步：用该 round2 ONNX 重新走 MaixCAM 转换，替换 task 8622。

## MaixCAM 转换成功产物（round2，2026-08-25，task 8629）

- 压缩包：`C:\Users\29845\Downloads\maixhub-model-convert-maixcam-8629.zip`
- zip SHA256：`30814C82BA4CFFE6B630F726E8A52B7A591A7121B6CEC5C38229D8B1881C5F9B`
- 包内文件：`model_8629.mud`（300 B）、`model_8629.cvimodel`（2,994,312 B）。
- `model_8629.mud`：`model_type = yolo11`、`type=detector`、`input_type=rgb`、
  `mean=0,0,0`、`scale=0.00392156862745098`（即 1/255），labels 顺序正确：
  `cube, cuboid, cylinder, hexagonal_prism, pentagonal_prism, square_pyramid,
  triangular_prism`。
- 部署代码默认 `MODEL_PATH` 已同步为 `/root/my_models/model_8629.mud`。
- 这是当前可上机联调的 round2 版本；弱类仍为 `pentagonal_prism` P 0.629、
  `cube` P 0.738、`triangular_prism` R 0.814，正式版本需达标后再冻结。

## 仍未冻结

1. 相机标定矩阵：未注入则 `motion_ready=false`，动作链走不通。
2. MaixPy v4 对 `.mud` / `cvimodel` 的实际加载与 `nn.YOLO11.detect` 解码
   未在真机验证，仍是文档化脚手架。
3. 最终可上机的模型版本：当前 448 模型仅用于接口联调，正式模型需在
   `cuboid`、`triangular_prism` 达标后再冻结。

## 待用户裁决

- 本地 PC 训练路径（`视觉/TRAINING.md` 的 YOLO11n CUDA/AMP 流程）与 MaixHub
  云端训练谁是最终权威路径，需要统一口径；目前倾向本地备数据、本地 YOLO11n
  训练，再走 MaixCAM 模型转换。
