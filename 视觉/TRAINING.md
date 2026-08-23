# 绿色/蓝色方块 YOLO11n 训练指南

> 说明：本文档描述本地 PyCharm 的 YOLO11n 训练/评估流程，用于数据集准备与精度
> 实验。最终部署模型的训练与导出走 MaixHub（云端）；导出物决定
> `MaixPyYoloBackend` 的模型家族与输入尺寸。

## 已准备好的文件

- PyCharm 工程：`D:\AAAdesktop1\shijue\ultralytics-8.3.163`
- Python 解释器：`D:\Anaconda\envs\yolo\python.exe`
- 数据配置：`datasets\block_dataset_v1\data.yaml`
- 预训练权重：`yolo11n.pt`
- 训练脚本：`train_blocks.py`
- 测试集评估脚本：`evaluate_blocks.py`

数据集按源视频隔离，不能重新随机划分：

| 集合 | 图片 | green_block 框 | blue_block 框 |
|---|---:|---:|---:|
| train | 60 | 177 | 145 |
| val | 17 | 24 | 25 |
| test | 13 | 25 | 52 |
| 合计 | 90 | 226 | 222 |

橙色方块是非目标干扰物，不标注、不增加类别。

## PyCharm 配置

1. 使用 PyCharm 打开 `D:\AAAdesktop1\shijue\ultralytics-8.3.163`，不要只打开单个 Python 文件。
2. 在 `File > Settings > Project > Python Interpreter` 中选择 `D:\Anaconda\envs\yolo\python.exe`。
3. 打开工程根目录的 `train_blocks.py`。
4. 进入 `Run > Edit Configurations`，新建 Python 配置。
5. `Script path` 选择 `D:\AAAdesktop1\shijue\ultralytics-8.3.163\train_blocks.py`。
6. `Working directory` 必须是 `D:\AAAdesktop1\shijue\ultralytics-8.3.163`。
7. `Parameters` 填写：

```text
--epochs 30 --batch 16 --device 0 --workers 0 --name block_yolo11n_e30
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

## 当前边界

1 epoch 冒烟训练只证明数据格式、CUDA、AMP、训练、验证和权重保存链路可运行，不代表模型精度达标。30 epoch 的验证指标也只能代表本次小型伪数据集；树莓派、MaixCAM、真实相机和比赛现场仍需独立测试。
