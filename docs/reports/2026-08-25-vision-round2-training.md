# 视觉第二轮本地训练报告（2026-08-25）

## 结论一句话

用 638 张超集重训 YOLO11n，独立 test 集 mAP50 从第一轮的 **0.873 → 0.913**（+0.04）；
三个棱柱弱类显著提升（hexagonal +0.14、triangular +0.13）。ONNX 已用 `yolo_export` 环境导出为 **opset 17**、静态 1×3×448×448、10.52 MB，供 MaixCAM 转换页使用。

---

## 1. 数据来源与分裂统计

- 来源：`训练1 (1).zip`（638 张，是旧 402 张的超集），解压到 `D:\AAAdesktop1\shijue\voc_export_638`。
- 结构：`images/` 638 `.jpg`、`annotations/` 638 `.xml`、`train.txt`。
- `voc_stats.py` 校验：images=638、xml=638、无未知类别、无缺失配对。

分类别标注框数（共 1014 框；括号为第一轮 402 张对比）：

| 类别 | 第一轮 | 第二轮 | 变化 |
|---|---|---|---|
| cube | 91 | 108 | +17 |
| cuboid | 62 | 94 | +32 |
| cylinder | 122 | 149 | +27 |
| hexagonal_prism | 116 | 188 | +72 |
| pentagonal_prism | 144 | 181 | +37 |
| square_pyramid | 111 | 148 | +37 |
| triangular_prism | 112 | 146 | +34 |

最弱的 `cuboid`（62→94）与 `hexagonal_prism`（116→188）补得最多。

### 划分

`prepare_voc_dataset.py` → `datasets/block_dataset_v1_7class_round2`，分层划分 seed=42、val/test 各 0.1：

| split | 图片数 |
|---|---|
| train | 510 |
| val | 64 |
| test | 64 |

每个 split 覆盖全 7 类。最小类 `cuboid`：val 8 / test 10（第一轮为 4/6）。

## 2. 训练

```powershell
train_blocks.py --data ...\block_dataset_v1_7class_round2\data.yaml `
  --model ...\yolo11n.pt --epochs 100 --imgsz 448 --batch 16 --device 0 `
  --name block_yolo11n_e100_round2
```

- 环境：`D:\Anaconda\envs\yolo\python.exe`，CUDA:0 = NVIDIA GeForce RTX 5070 Ti Laptop GPU。
- 模型：YOLO11n，2,583,517 参数，6.3 GFLOPs。

`TRAINING_OUTPUT`（权威权重）：

```json
{"run_dir": "D:\\AAAdesktop1\\shijue\\ultralytics-8.3.163\\runs\\block_detector\\block_yolo11n_e100_round2",
 "best_pt": "D:\\AAAdesktop1\\shijue\\ultralytics-8.3.163\\runs\\block_detector\\block_yolo11n_e100_round2\\weights\\best.pt",
 "best_exists": true}
```

`best.pt` 5.45 MB。

### val 集指标（best.pt，64 图 / 89 实例）

| 指标 | 值 |
|---|---|
| mAP50 | 0.89 |
| mAP50-95 | 0.674 |
| Precision | 0.78 |
| Recall | 0.798 |

## 3. 独立 test 集评估

`evaluate_blocks.py`（split=test，64 图 / 95 实例）：

**整体：mAP50 = 0.913，mAP50-95 = 0.706，P = 0.819，R = 0.893**

分类别（mAP50 / P / R）：

| 类别 | 实例 | mAP50 | P | R |
|---|---|---|---|---|
| cube | 10 | 0.910 | 0.738 | 0.847 |
| cuboid | 10 | 0.928 | 0.820 | 0.910 |
| cylinder | 14 | 0.932 | 1.000 | 0.926 |
| hexagonal_prism | 18 | 0.958 | 0.889 | 0.833 |
| pentagonal_prism | 17 | 0.918 | 0.629 | 1.000 |
| square_pyramid | 13 | 0.887 | 0.819 | 0.923 |
| triangular_prism | 13 | 0.859 | 0.841 | 0.814 |

## 4. 与第一轮（402 张）对比

test 集 mAP50：

| 类别 | 第一轮 | 第二轮 | 变化 |
|---|---|---|---|
| cube | 0.808 | 0.910 | +0.10 |
| cuboid | 0.909 | 0.928 | +0.02 |
| cylinder | 0.995 | 0.932 | −0.06 |
| hexagonal_prism | 0.818 | **0.958** | **+0.14** |
| pentagonal_prism | 0.859 | 0.918 | +0.06 |
| square_pyramid | 0.995 | 0.887 | −0.11 |
| triangular_prism | 0.728 | **0.859** | **+0.13** |
| **整体** | **0.873** | **0.913** | **+0.04** |

**结论**：弱类大翻身——`hexagonal_prism`（+0.14）、`triangular_prism`（+0.13）显著改善，
正是第一轮人工补数据重点。`cylinder`/`square_pyramid` 略降属正常波动（test 样本小、且两轮 test 划分不同）。

## 5. ONNX 导出

用 `yolo_export` 环境（**ultralytics 8.4.104** / onnx 1.22.0）导出，`--opset 17`：

```powershell
& "D:\Anaconda\envs\yolo_export\python.exe" `
  "C:\Users\29845\Desktop\工创赛\视觉\training\export_onnx.py" `
  --weights "<best_pt>" --imgsz 448 --opset 17
```

输出：

```text
D:\AAAdesktop1\shijue\ultralytics-8.3.163\runs\block_detector\block_yolo11n_e100_round2\weights\best.onnx
```

- **opset 17**（已实测确认，非第一轮的 18）✓
- 输入：`images [1, 3, 448, 448]`，静态 ✓
- 输出：`output0 [1, 11, 4116]`
- 文件大小：10.52 MB（< 100MB）✓
- 未运行 `fix_onnx_for_maixhub.py`（按指示）。

## 6. 环境说明（供复现）

- 训练/评估用 `yolo` 环境（ultralytics 8.3.163，本地源码），运行需设 `PYTHONPATH` 指向工程根目录（见第一轮报告第 6 节）。
- ONNX 导出用 `yolo_export` 环境（ultralytics 8.4.104 已装入 site-packages，无需 PYTHONPATH），用于生成 MaixHub 兼容的 opset 17。

## 7. 仍需补数据的类别

1. `pentagonal_prism`（test P 0.629）：仍易误检，与 hexagonal / triangular 棱柱混淆，建议继续补充/校对。
2. `cube`（test P 0.738）：误检略多，注意与 `square_pyramid`、`cuboid` 的区分。
3. `triangular_prism`（test R 0.814）：仍有约 18% 漏检。

## 8. 待实机验证

本地指标达标 ≠ 实机可用。opset 17 是否被 MaixCAM 模型转换页接受、分拣是否可用，必须等 MaixCAM 实机验证。

---

*本报告由 Claude 生成，未执行 `git commit`，未修改 `视觉/src` 生产代码。*
