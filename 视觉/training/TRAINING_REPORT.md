# 训练报告 —— 工创赛 7 类三维几何体检测

## 基本信息
- 模型：YOLOv5s（ultralytics 改进版 `yolov5su.pt` 预训练权重微调）
- 框架：ultralytics 8.3.163 · torch 2.13.0+cu132 · CUDA RTX 5070 Ti Laptop（12GB）
- 输入尺寸：448×448
- Epoch：100（实际 100 轮跑完，best = epoch 95）
- 训练耗时：约 0.46 小时
- 数据集：`voc_export_638` → `yolo_dataset`（train 511 / val 127，7 类共 1014 框）

## 总体指标（best.pt @ val）
| 指标 | 值 |
|---|---:|
| mAP50 | **0.865** |
| mAP50-95 | **0.642** |
| Precision | 0.829 |
| Recall | 0.767 |

## 每类指标
| 类别 | 框数 | P | R | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|---:|
| cube | 108 | 0.858 | 0.714 | 0.896 | 0.655 |
| cuboid | 94 | 0.849 | 0.650 | **0.778** | **0.589** |
| cylinder | 149 | 0.965 | 0.938 | **0.946** | 0.709 |
| hexagonal_prism | 188 | 0.804 | 0.846 | 0.918 | 0.738 |
| pentagonal_prism | 181 | 0.725 | 0.792 | 0.841 | 0.590 |
| square_pyramid | 148 | 0.947 | **0.545** | 0.830 | **0.565** |
| triangular_prism | 146 | **0.655** | 0.885 | 0.846 | 0.646 |

## 关键结论
1. **整体可用**：mAP50 = 0.865，7 类平均都 ≥ 0.78，达到竞赛/演示可用水平。
2. **最强类**：cylinder（0.946）、hexagonal_prism（0.918）—— 注意 hexagonal_prism 并非弱类（纠正了之前的预判）。
3. **真正的弱类**：
   - `cuboid`：整体最弱（mAP50 0.778，召回 0.65），且样本最少（94 框）。
   - `square_pyramid`：召回最低（0.545），高精度低召回 = 大量漏检，容易和其它棱锥/棱柱混淆。
   - `triangular_prism`：精度最低（0.655），高召回低精度 = 误检偏多。
4. **一句话评估**：模型可直接上 K230 使用；若追求更稳，优先给 `cuboid` 和 `square_pyramid` 补采样本，或对这两类适当调低检测阈值。

## 产物位置
- 权重：`D:\AAAdesktop1\shijue\runs\yolo5s_geom7c\weights\best.pt`（18.5MB）
- 图表：`D:\AAAdesktop1\shijue\runs\yolo5s_geom7c\`（results.png、confusion_matrix.png、PR/F1 曲线、val 预测图）
- 每轮指标：`results.csv`

## 下一步（部署 K230）
best.pt 需要转成 K230 用的 `.kmodel`（走 MaixPy / nncase 或 MaixVision 的模型转换），再烧进板子。
