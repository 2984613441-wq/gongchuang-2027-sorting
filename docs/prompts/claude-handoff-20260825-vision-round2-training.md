# Claude 提示词：视觉第二轮本地训练（2026-08-25）

## 目标

用更新后的 638 张训练集，重新训练 YOLO11n 模型，独立 test 集评估后导出
静态 448×448 ONNX，供 MaixCAM 模型转换页使用。

只做主机侧代码、数据、训练、评估和 ONNX 导出。不要连接、上电或操作
MaixCAM、STM32、电机、串口等真实硬件。

## 背景事实

- 仓库路径：`C:\Users\29845\Desktop\工创赛`
- 训练工程：`D:\AAAdesktop1\shijue\ultralytics-8.3.163`
- 训练解释器：`D:\Anaconda\envs\yolo\python.exe`
- ONNX 导出解释器：`D:\Anaconda\envs\yolo_export\python.exe`
  （该环境已安装 `ultralytics==8.4.104`，用于生成 MaixHub 兼容的 opset17 ONNX）
- 数据集 zip：`C:\Users\29845\Downloads\训练1 (1).zip`
- 数据量：638 张图片，638 个 XML，是旧 402 张的超集
- 7 个类别顺序固定为：

  ```text
  cube, cuboid, cylinder, hexagonal_prism,
  pentagonal_prism, square_pyramid, triangular_prism
  ```

- 仓库脚本：
  - `视觉/training/voc_stats.py`
  - `视觉/training/prepare_voc_dataset.py`
  - `视觉/training/train_blocks.py`
  - `视觉/training/evaluate_blocks.py`
  - `视觉/training/export_onnx.py`

## 输入准备

用户已经提供了新数据 zip，不需要你下载或标注。解压后结构应是：

```text
images/
annotations/   （脚本也接受 xml/ 目录）
train.txt
```

## 执行步骤

### 1. 解压新数据集

```powershell
Expand-Archive -LiteralPath "C:\Users\29845\Downloads\训练1 (1).zip" `
  -DestinationPath "D:\AAAdesktop1\shijue\voc_export_638"
```

### 2. 统计并校验数据

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\voc_stats.py" `
  --source-root "D:\AAAdesktop1\shijue\voc_export_638"
```

确认 `images=638`、`xml_files=638`、无未知类别、无缺失配对。

### 3. 转换 VOC 为 YOLO

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\prepare_voc_dataset.py" `
  --source-root "D:\AAAdesktop1\shijue\voc_export_638" `
  --output-root "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class_round2" `
  --val-ratio 0.1 --test-ratio 0.1 --seed 42
```

### 4. 训练 YOLO11n

```powershell
Set-Location "D:\AAAdesktop1\shijue\ultralytics-8.3.163"

& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\train_blocks.py" `
  --data "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class_round2\data.yaml" `
  --model "D:\AAAdesktop1\shijue\ultralytics-8.3.163\yolo11n.pt" `
  --epochs 100 --imgsz 448 --batch 16 --device 0 `
  --name block_yolo11n_e100_round2
```

记录最后的 `TRAINING_OUTPUT`，其中 `best_pt` 是权威权重路径。

### 5. 独立 test 集评估

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\evaluate_blocks.py" `
  --weights "<best_pt>" `
  --data "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class_round2\data.yaml" `
  --imgsz 448
```

### 6. 导出 ONNX

必须用 `yolo_export` 环境，不要用 `yolo` 环境：

```powershell
& "D:\Anaconda\envs\yolo_export\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\export_onnx.py" `
  --weights "<best_pt>" --imgsz 448 --opset 17
```

不要运行 `fix_onnx_for_maixhub.py`；`yolo_export` 环境导出的是 MaixHub
兼容的 opset17 ONNX。

## 结果记录

把以下内容写入 `docs/reports/2026-08-25-vision-round2-training.md`：

- 数据集来源和 638 张的分裂统计；
- 训练命令和 `TRAINING_OUTPUT`；
- test 集 mAP50、mAP50-95、P、R；
- 分类别 mAP50 / P / R；
- 与第一轮 402 张训练结果的对比；
- ONNX 输出路径、opset、输入尺寸和文件大小；
- 仍需补数据的类别。

## 边界

- 不修改 `视觉/src` 生产代码，除非脚本报错且必须修复；若修改，写清原因。
- 不执行 `git commit`。
- 不下载额外权重或包。
- 不猜测 MaixPy API、串口协议、CRC、电机参数或未冻结的硬件接线。
- 不自行补数据、不修改 XML 标注；数据问题只报告，由用户处理。
- 主机测试通过不等于 MaixCAM 实机通过。
