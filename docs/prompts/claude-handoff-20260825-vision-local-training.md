# Claude 操作手册：视觉本地训练与 MaixCAM 迁移准备（2026-08-25）

## 目标

在本地 Ultralytics 工程中完成 7 类形状检测模型的：

1. VOC 数据集校验与 YOLO 格式转换；
2. 本地训练 YOLO11n；
3. 独立 test 集评估；
4. 导出静态 448×448 ONNX，供 MaixCAM 模型转换页使用。

只做主机侧代码、数据、训练和评估。不要连接、上电或操作 MaixCAM、STM32、
电机、串口等真实硬件。

## 背景事实

- 仓库路径：`C:\Users\29845\Desktop\工创赛`
- 训练工程：`D:\AAAdesktop1\shijue\ultralytics-8.3.163`
- Python 解释器：`D:\Anaconda\envs\yolo\python.exe`
- 训练权重：工程内已有 `yolo11n.pt`
- 目标输入：448×448，RGB，`mean=0`，`std=255`
- 7 个类别顺序固定为：

  ```text
  cube, cuboid, cylinder, hexagonal_prism,
  pentagonal_prism, square_pyramid, triangular_prism
  ```

- 数据要求见 `视觉/DATASET_REQUIREMENTS.md`。
- 仓库脚本：
  - `视觉/training/voc_stats.py`
  - `视觉/training/prepare_voc_dataset.py`
  - `视觉/training/train_blocks.py`
  - `视觉/training/evaluate_blocks.py`
  - `视觉/training/export_onnx.py`

## 输入准备（由用户完成，不在你的任务内）

用户需要从 MaixHub 导出 Pascal VOC 已标注数据集，并解压成：

```text
D:\AAAdesktop1\shijue\voc_export
├── images
│   └── *.jpg
└── xml  （或 annotations，两个目录名都接受）
    └── *.xml
```

如果该目录不存在或缺少 `images` 与 `xml`/`annotations`，停止执行并报告用户，不要自行
下载、标注或编造数据。

## 执行步骤

### 1. 检查环境

```powershell
& "D:\Anaconda\envs\yolo\python.exe" -c "import ultralytics, PIL; print(ultralytics.__version__, PIL.__version__)"
```

如果导入失败，停止并报告具体错误。

### 2. 检查数据目录

```powershell
Test-Path "D:\AAAdesktop1\shijue\voc_export\images"
Test-Path "D:\AAAdesktop1\shijue\voc_export\xml"
Test-Path "D:\AAAdesktop1\shijue\voc_export\annotations"
```

第一个必须是 `True`，后面两个至少有一个是 `True` 才能继续。

### 3. 转换 VOC 为 YOLO 数据集

先统计当前标注，确认类别和缺失情况：

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\voc_stats.py" `
  --source-root "D:\AAAdesktop1\shijue\voc_export"
```

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\prepare_voc_dataset.py" `
  --source-root "D:\AAAdesktop1\shijue\voc_export" `
  --output-root "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class" `
  --val-ratio 0.1 --test-ratio 0.1 --seed 42
```

输出必须是 `data.yaml`、`classes.txt`、`manifest.json` 和
`images/{train,val,test}`、`labels/{train,val,test}`。

### 4. 训练

```powershell
Set-Location "D:\AAAdesktop1\shijue\ultralytics-8.3.163"

& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\train_blocks.py" `
  --data "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class\data.yaml" `
  --model "D:\AAAdesktop1\shijue\ultralytics-8.3.163\yolo11n.pt" `
  --epochs 100 --imgsz 448 --batch 16 --device 0
```

记录控制台最后的 `TRAINING_OUTPUT`，其中 `best_pt` 是权威权重路径。

### 5. 评估

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\evaluate_blocks.py" `
  --weights "<best_pt>" `
  --data "D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class\data.yaml" `
  --imgsz 448
```

把 `<best_pt>` 替换为 `TRAINING_OUTPUT` 给出的真实路径。

### 6. 导出 ONNX

```powershell
& "D:\Anaconda\envs\yolo\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\export_onnx.py" `
  --weights "<best_pt>" --imgsz 448
```

确认输出的 ONNX 是静态 `1x3x448x448`，文件小于 100MB。

## 结果记录

把以下内容写入 `docs/reports/2026-08-25-vision-local-training.md`：

- 数据来源目录和样本量；
- train/val/test 划分；
- 训练命令和 `TRAINING_OUTPUT`；
- test 集 mAP 与分类别指标；
- ONNX 输出路径和文件大小；
- 未完成的项和需要用户补数据的类别。

不要用“训练通过”代替“实机通过”。模型是否可用于分拣，必须等待 MaixCAM
实机验证。

## 边界

- 不修改 `视觉/src` 生产代码，除非脚本运行报错且必须修复；若修改，写清原因。
- 不执行 `git commit`，除非用户明确授权。
- 不下载未在背景事实中列出的权重或包。
- 不猜测 MaixPy API、串口协议、CRC、电机参数或未冻结的硬件接线。
- 遇到数据不足、类别缺失或标注可疑，先报告，不自行用脚本“补数据”。
