# 视觉本地训练报告（2026-08-25）

## 结论一句话

7 类形状检测 YOLO11n 已在本地跑通 VOC→YOLO 转换、100 轮训练、独立 test 集评估与静态 ONNX 导出（1×3×448×448，10.45MB）。
弱类（棱柱类）仍需人工补数据/校对；ONNX 的 opset 18 兼容性需在 MaixCAM 实机核验。

---

## 1. 数据来源与样本量

- 来源：`训练1.zip`（MaixHub 导出 Pascal VOC），解压到 `D:\AAAdesktop1\shijue\voc_export`。
- 结构：`images/` 402 张 `.jpg`（416×416），`annotations/` 402 个 `.xml`（注意是 `annotations/` 不是 `xml/`），另有 `train.txt` 清单。
- 图片 ↔ XML 一一对应，无未知类别名。

类别标注框数（共 758 框）：

| 类别 | 框数 |
|---|---|
| cube | 91 |
| cuboid | 62 |
| cylinder | 122 |
| hexagonal_prism | 116 |
| pentagonal_prism | 144 |
| square_pyramid | 111 |
| triangular_prism | 112 |

## 2. 数据集划分

`prepare_voc_dataset.py` → `datasets/block_dataset_v1_7class`，按「图片主类」分层划分，seed=42，val/test 各 0.1：

| split | 图片数 |
|---|---|
| train | 320 |
| val | 41 |
| test | 41 |

每个 split 均覆盖全部 7 类。最小类 `cuboid`：val 4 张、test 6 张（偏薄）。

## 3. 训练

```powershell
train_blocks.py --data ...\block_dataset_v1_7class\data.yaml `
  --model ...\yolo11n.pt --epochs 100 --imgsz 448 --batch 16 --device 0
```

- 环境：`D:\Anaconda\envs\yolo\python.exe`，CUDA:0 = NVIDIA GeForce RTX 5070 Ti Laptop GPU（12227 MiB）。
- 模型：YOLO11n，100 层，2,583,517 参数，6.3 GFLOPs。
- 时长：100 epochs / 0.119 h（约 7 分钟）。

`TRAINING_OUTPUT`（权威权重）：

```json
{"run_dir": "D:\\AAAdesktop1\\shijue\\ultralytics-8.3.163\\runs\\block_detector\\block_yolo11n_e100",
 "best_pt": "D:\\AAAdesktop1\\shijue\\ultralytics-8.3.163\\runs\\block_detector\\block_yolo11n_e100\\weights\\best.pt",
 "best_exists": true}
```

`best.pt` 5.5MB（已剥离优化器）。

### val 集指标（best.pt，41 图 / 71 实例）

| 指标 | 值 |
|---|---|
| mAP50 | 0.934 |
| mAP50-95 | 0.689 |
| Precision | 0.82 |
| Recall | 0.886 |

## 4. 独立 test 集评估

`evaluate_blocks.py`（split=test，41 图 / 66 实例）：

**整体：mAP50 = 0.873，mAP50-95 = 0.656，P = 0.888，R = 0.786**

分类别（mAP50 / P / R）：

| 类别 | mAP50 | P | R | 备注 |
|---|---|---|---|---|
| cube | 0.808 | 0.972 | 0.75 | 召回偏低 |
| cuboid | 0.909 | 0.90 | 0.833 | |
| cylinder | 0.995 | 0.983 | 1.0 | |
| hexagonal_prism | **0.818** | 0.725 | **0.60** | 漏检 40% |
| pentagonal_prism | 0.859 | **0.639** | 0.692 | 误检多 |
| square_pyramid | 0.995 | 0.999 | 1.0 | |
| triangular_prism | **0.728** | 1.0 | **0.629** | 漏检 37% |

**弱类结论**：三个棱柱类（hexagonal / triangular / pentagonal）在独立 test 集上仍明显偏弱，
与人工校对重点（`pentagonal_prism vs hexagonal_prism vs triangular_prism` 混淆组）一致。
样本量小（每类 test 仅 8–13 例），指标有噪声，但趋势稳定：棱柱类易漏检/误检。

## 5. ONNX 导出（完成）

`export_onnx.py` 成功，输出：

```text
D:\AAAdesktop1\shijue\ultralytics-8.3.163\runs\block_detector\block_yolo11n_e100\weights\best.onnx
```

- 文件大小：**10.45 MB**（< 100MB ✓）
- 输入张量：`images [1, 3, 448, 448]`，**静态**（非动态）✓
- 输出张量：`output0 [1, 11, 4116]`（11 = 4 bbox + 7 类；4116 = 56²+28²+14² 三个尺度锚点）
- 算子集：Add / Concat / Conv / Div / MatMul / MaxPool / Mul / Reshape / Resize / Sigmoid / Softmax / Split / Sub / Transpose（均为常见算子）

### 依赖修复记录（本次导出新增安装的包）

初始环境缺 `onnx`，ultralytics 自动安装失败（其内部 `uv pip install --index-strategy=unsafe-best-match --prerelease=allow`
绕过 pip 配置的清华镜像、倾向选 sdist 源码包导致本地 C++ 编译失败）。经用户授权后，用 pip 直装（走清华镜像）：

```powershell
"D:/Anaconda/envs/yolo/python.exe" -m pip install "onnx>=1.16,<1.18" onnxruntime onnxslim
"D:/Anaconda/envs/yolo/python.exe" -m pip install onnxscript
```

实际安装：onnx 1.17.0、onnxruntime 1.29.0、onnxslim 0.1.96、onnxscript 0.7.1（+ protobuf 7.36.0、onnx_ir 1.0.0、flatbuffers、ml_dtypes 等依赖）。

### ⚠️ 待实机核验：opset 版本

`export_onnx.py` 默认请求 **opset 12**，但 torch 2.13 的新 ONNX 导出器最低只能导出 **opset 18**；
自动降级到 12 失败（onnx 版本转换器对 `Resize` 算子无 18→12 适配器），因此实际模型停留在 **opset 18**。

- 手册显式验收标准（静态 1×3×448×448 + <100MB）**均已满足**；
- 但 opset 18 ≠ 脚本原意的 12，MaixCAM/nncase 是否接受 opset 18 需在模型转换页实机验证，本地无法确认。

## 6. 环境问题与修复记录（重要，供复现）

`ultralytics` **未装进** `yolo` 环境的 site-packages，只是工程根目录下的源码包
`ultralytics-8.3.163\ultralytics\`。因此运行脚本时需显式设置 `PYTHONPATH` 指向工程根目录：

```powershell
$env:PYTHONPATH = "D:\AAAdesktop1\shijue\ultralytics-8.3.163"
```

否则 `python train_blocks.py` 只把脚本目录（`视觉\training\`）加入 `sys.path`，`import ultralytics` 失败。
**未修改任何 `视觉/training` 脚本代码**，仅运行时加环境变量。

## 7. 未完成项 / 需要用户跟进

1. **弱类人工校对/补数据**（正式模型前必须做）：
   - `cuboid` 仅 62 框、val/test 各 4/6 张，样本不足；
   - `hexagonal_prism`（test R 0.60）、`triangular_prism`（test R 0.629）、`pentagonal_prism`（test P 0.639）需重点核对混淆标注。
   - 重点核对组：`cube vs square_pyramid`、`cuboid vs cube`、`pentagonal_prism vs hexagonal_prism vs triangular_prism`。
2. **实机验证**：本地指标 ≠ 实机可用性。模型是否可用于分拣，必须等 MaixCAM 实机验证，不能用「训练通过」代替「实机通过」。
   - 特别注意：导出 ONNX 为 **opset 18**（非脚本原意的 12），需在 MaixCAM 模型转换页确认 nncase 是否接受该版本（见第 5 节）。

---

*本报告由 Claude 生成，未执行 `git commit`。*
