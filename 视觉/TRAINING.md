# 7 类形状 YOLO 训练与 MaixCAM 迁移指南

> 说明：本文档描述本地 PyCharm 的 YOLO 训练/评估流程，用于数据集准备与精度
> 实验。推荐使用 YOLO11n，因为当前工程已有 `yolo11n.pt`，且 MaixCAM 模型转换
> 与 `MaixPyYoloBackend` 都直接支持 `yolo11`。YOLOv8n、YOLOv5u 可作备选。

## 已准备好的文件

- PyCharm 工程：`D:\AAAdesktop1\shijue\ultralytics-8.3.163`
- Python 解释器：`D:\Anaconda\envs\yolo\python.exe`
- 数据配置：`datasets\block_dataset_v1\data.yaml`
- 预训练权重：`yolo11n.pt`
- 训练脚本：`train_blocks.py`
- 测试集评估脚本：`evaluate_blocks.py`
- VOC 转 YOLO 脚本：`prepare_voc_dataset.py`
- VOC 统计脚本：`voc_stats.py`
- ONNX 导出脚本：`export_onnx.py`

## 本地数据集准备

MaixHub 导出的 Pascal VOC 包结构是 `images/` + `xml/`（部分导出为
`images/` + `annotations/`，脚本两者都接受）。先转成本地 YOLO
数据集，并切出 train/val/test：

```text
python <repo>\视觉\training\prepare_voc_dataset.py ^
  --source-root D:\AAAdesktop1\shijue\voc_export ^
  --output-root D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class ^
  --val-ratio 0.1 --test-ratio 0.1 --seed 42
```

脚本会校验 XML、图像和类别，按类别分层抽样，输出
`images/{train,val,test}`、`labels/{train,val,test}`、`data.yaml`、
`classes.txt` 和 `manifest.json`。若某个类别图片少于 3 张，会直接报错。

训练时把 `--data` 指向生成的 `data.yaml`：

```text
--data D:\AAAdesktop1\shijue\ultralytics-8.3.163\datasets\block_dataset_v1_7class\data.yaml
```

数据集按形状分为 7 类，颜色（蓝/灰）不单独成类：

| class_id | 英文 label | 中文 |
|---|---|---|
| 0 | cube | 正方体 |
| 1 | cuboid | 长方体 |
| 2 | cylinder | 圆柱 |
| 3 | hexagonal_prism | 六棱柱 |
| 4 | pentagonal_prism | 五棱柱 |
| 5 | square_pyramid | 四角锥 |
| 6 | triangular_prism | 三角柱 |

以上顺序以 MaixHub 实际导出顺序为准；本地
`datasets\block_dataset_v1` 的 `data.yaml` / `classes.txt` 必须保持同一顺序，
否则 `class_id` 会在本地与 MaixCAM 之间错位。

## MaixHub 已导出事实（2026-08-25）

- 当前模型包任务 `317458`：YOLOv5s，输入 448×448，`model_type=yolov5`，
  `conf_th=0.5`、`iou_th=0.45`，导出为 `.mud` + `.cvimodel`。
- 100 epoch 最佳 `val_acc=0.4241`。分类别：
  `cube 0.6364`、`cuboid 0.2909`、`cylinder 0.6364`、
  `hexagonal_prism 0.0529`、`pentagonal_prism 0.4545`、
  `square_pyramid 0.5411`、`triangular_prism 0.3566`。
- 结论：输入尺寸和标签顺序已冻结；**精度尚未通过**，`hexagonal_prism`、
  `cuboid`、`triangular_prism` 仍需补数据/修标注后再训练。
- 历史任务 `317442` 的 `val_acc=0.4801` 仅供参考，不作为当前部署模型。

同一形状的不同颜色（蓝/灰）都标为同一 shape label；训练集需覆盖两种颜色，
避免模型按颜色分类。

## PyCharm 配置

1. 使用 PyCharm 打开 `D:\AAAdesktop1\shijue\ultralytics-8.3.163`，不要只打开单个 Python 文件。
2. 在 `File > Settings > Project > Python Interpreter` 中选择 `D:\Anaconda\envs\yolo\python.exe`。
3. 打开工程根目录的 `train_blocks.py`。
4. 进入 `Run > Edit Configurations`，新建 Python 配置。
5. `Script path` 选择 `D:\AAAdesktop1\shijue\ultralytics-8.3.163\train_blocks.py`。
6. `Working directory` 必须是 `D:\AAAdesktop1\shijue\ultralytics-8.3.163`。
7. `Parameters` 填写：

```text
--epochs 30 --batch 16 --imgsz 448 --device 0 --workers 0 --name block_yolo11n_e30
```

8. 点击 Run。日志开头应显示 `CUDA:0 (NVIDIA GeForce RTX 5070 Ti...)`，不能是 CPU。

训练完成后，以控制台最后一行 `TRAINING_OUTPUT` 为准。首次运行的预期权重路径是：

```text
D:\AAAdesktop1\shijue\ultralytics-8.3.163\runs\block_detector\block_yolo11n_e30\weights\best.pt
```

如果同名运行目录已经存在，Ultralytics 可能自动增加数字后缀，因此不要凭猜测复制权重，必须查看 `TRAINING_OUTPUT`。

## 独立测试集评估

30 轮结束后，在 PyCharm 新建第二个 Python 运行配置：

- `Script path`：`D:\AAAdesktop1\shijue\ultralytics-8.3.163\evaluate_blocks.py`
- `Working directory`：`D:\AAAdesktop1\shijue\ultralytics-8.3.163`
- `Parameters`：

```text
--weights runs\block_detector\block_yolo11n_e30\weights\best.pt --device 0 --workers 0
```

如果 `TRAINING_OUTPUT` 给出的目录带数字后缀，此处同步改为真实路径。评估脚本固定使用 `split="test"`，不会用测试集继续训练。

## 导出 ONNX

评估通过后，在工程根目录运行仓库脚本（把权重路径替换成 `TRAINING_OUTPUT` 给出的
真实 `best.pt`）：

```text
--weights runs\block_detector\block_yolo11n_e30\weights\best.pt --imgsz 448
```

导出为静态 `1x3x448x448` RGB ONNX，FP32，供 MaixCAM 模型转换页使用。
官方转换文档建议用 `ultralytics==8.4.104` 导出，`opset=17`、`simplify=True`。
当前本地 `8.3.163 + torch 2.13` 会实际生成 opset 18，与平台旧 onnx 检查器不兼容。
建议优先重建导出环境（另建 `yolo_export` 环境安装 `ultralytics==8.4.104`），
或者直接使用下面的降级脚本。
若转换页报 `Unrecognized attribute: antialias for operator Resize` 或
`ir_version is higher than the checker's`，用 `fix_onnx_for_maixhub.py`
把 ONNX 降到 opset 13 后再传：

```text
--input <best.onnx> --output <best_maixcam_opset13.onnx> --opset 13
```

官方推荐导出命令（在 `ultralytics==8.4.104` 环境中执行）：

```text
yolo export model=<best.pt> format=onnx imgsz=448 opset=17 simplify=True
```

## MaixCAM 模型转换

上传刚才导出的 ONNX，按页面要求填写：

- 模型类型：MaixCAM 转换页支持 **YOLOv5u / YOLOv8 / YOLO11 / YOLO26** 的
  `detect`。推荐选 YOLO11 或 YOLOv8；不要选传统 YOLOv5（`yolov5s.pt`），
  它不属于这里的 YOLOv5u 路径。
- 输入尺寸：静态 `1x3xHxW` RGB，宽高为 32 的倍数；本仓库固定 `448×448`。
- ONNX 大小：不超过 100MB。
- 量化图片：20-100 张有效图片，推荐 50-100 张真实场景图。
- 模型标签：按 MaixHub 导出顺序填写 7 个类别：

  ```text
  cube,cuboid,cylinder,hexagonal_prism,pentagonal_prism,square_pyramid,triangular_prism
  ```

转换完成后下载 `.mud`，按实际模型类型设置 `MaixPyYoloBackend.family`：
`yolo11` / `yolov8`。`yolov5u`、`yolo26` 的 MaixPy 适配需要等转换产物
实测后再补，不提前猜 API。

## 当前边界

1 epoch 冒烟训练只证明数据格式、CUDA、AMP、训练、验证和权重保存链路可运行，不代表模型精度达标。30 epoch 的验证指标也只能代表本次小型伪数据集；树莓派、MaixCAM、真实相机和比赛现场仍需独立测试。
