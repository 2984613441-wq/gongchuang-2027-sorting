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

## 仍未冻结（阻塞 runner/decoder 落地）

1. MaixHub 导出的模型格式：`.mud` 包 vs 裸 `.kmodel` + labels 文件。
2. 模型家族：YOLOv5 / YOLOv8 / YOLO11 / 其他，决定用 MaixPy 内置 `nn.YOLO*`
   解码器还是手动张量 decoder。
3. 模型输入尺寸：当前 `InferenceConfig` 默认 640×640，需与导出模型一致。
4. 类别表与顺序：当前伪数据集为 `0=green_block`、`1=blue_block`。
5. 相机标定矩阵：未注入则 `motion_ready=false`，动作链走不通。

## 待用户裁决

- 本地 PC 训练路径（`视觉/TRAINING.md` 的 YOLO11n CUDA/AMP 冒烟）与 MaixHub 云端
  训练谁是最终权威路径，需要统一口径；目前看是本地备数据集、MaixHub 训练。
