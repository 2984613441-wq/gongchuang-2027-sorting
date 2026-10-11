# 数据集与 ONNX 独立审查（2026-09-18）

本附件只核对本地现存文件；没有训练、推理、运行重映射脚本、连接设备或修改任何生产文件。下文 `E` 指本目录 `dataset-models-output.txt`；二进制模型的行号引用指直接读取后产生的证据行，不伪造二进制文件行号。

## 执行与证据

工作目录：`C:\Users\29845\Desktop\工创赛`。最终实际执行命令：

```powershell
py -3 -X utf8 'docs/reports/evidence/vision-chain-20260918/dataset_models.py' | Tee-Object -FilePath 'docs/reports/evidence/vision-chain-20260918/dataset-models-output.txt' | Select-Object -Last 10
```

退出码 **0**。`Tee-Object` 在尾部筛选之前保存了完整标准输出，共 307 行。Python 3.14.5 / `D:\python.exe`；`onnx` 未安装，已有 `onnxruntime 1.26.0`，未安装新依赖（E:1、302）。模型 I/O 与 metadata 由 CPU session 加载读取，**未调用 `session.run()`**；真实 opset/IR 由现存 ONNX 的 protobuf 字段直接读取（`dataset_models.py:112` 起、E:302）。

## B-07：闭案结论不受现状支持

1. **脚本实际作用对象是根目录 `workspace_label`，不是 `视觉/datasets/preliminary`。** `视觉/training/remap_labels.py:31` 硬编码根工作区，`:38` 仅遍历 `img_*.txt`，`:55` 无条件施加 `REMAP`，`:57` 原地写回。映射是 `0→3,1→6,2→4,3→2,4→5,5→1,6→0`（`:21`）；变换前后编号集合均为 0–6，因此只数取值范围不能证明类义正确（E:3）。脚本也没有“已转换”标记，重复运行不会保持原值；本次未运行它。

2. **目前可复核的变换版本是 `workspace_label` 的 64 文件 / 87 框，并已传播到 D 盘 round3 的 `ws_` 训练样本。** 386 张 preliminary 图片中有 64 张与 workspace 的图片 SHA256 完全相同；这 64 对的全部框坐标、框数相同，类别全部严格满足上述 REMAP，没有一对同号（E:140、141、147）。round3 的 64 张 `ws_` 图片与 workspace 同 hash，标签全部同号同框（E:298）；`视觉/training/merge_workspace_dataset.py:21`、`:22`、`:58`、`:63`、`:64` 显示源、目标与复制方式，D 盘 manifest 原文也记载 `workspace_added: 64`（E:159–175）。这证明了编号变换和传播现状，**不能代替 64 张图片逐框形状真值验收，也不能证明某日脚本执行的历史记录**。

3. **preliminary 的旧标签没有同步这次变换。** 抽样两张图片 hash 均为 `dc32a6fafc3f39ed62d23c8c5b30f780a1b0c6209f9b9ae2c55b2dc0352ac4a7`（E:154–155），标签为：

   ```text
   视觉/datasets/preliminary/labels/session_1787758510_img_00019.txt:1
   4 0.496652 0.352679 0.354911 0.348214
   workspace_label/img_00004.txt:1
   5 0.496652 0.352679 0.354911 0.348214
   archive/datasets/raw-capture-2026-08-27/session_1787758510/img_00019.txt:1
   4 0.496652 0.352679 0.354911 0.348214
   ```

   不是只凭 mtime 猜测两批：以保留的 `unannotated.txt` 清单分组，386 文件 = **211 份原有标注 + 175 份后来自动标注**。211 份的标注逐框全部与原始采集归档一致；175 份在归档中为 57 份空标签、118 份无标签（E:299）。自动标注脚本读取 round2 权重，从 `b.cls` 直接写 id，没有旧→新 REMAP（`视觉/datasets/preliminary/auto_label.py:12`、`:16`、`:47`、`:50`、`:60`）。现存审核稿也把 175 份列为待核对自动标注（`视觉/datasets/preliminary/审核稿.md:5`、`:158`）。**全体 211 份旧标注的形状真值没有逐图验收；可严格证实的是 211 份保持归档编号，其中可与 workspace 匹配的 64 份仍保留变换前编号。**

4. **`_unused` 存在也不能证明 preliminary 重映射已做。** preliminary `_unused/labels` 有 148 个空文件（E:142），但其本目录另有仅按空标签移动文件的脚本（`视觉/datasets/preliminary/move_unused.py:6`、`:14`、`:17`、`:22`）。workspace `_unused` 是 124 个空标签（另有对应图片），并非“248 个标签”（E:143）。

5. 因此，台账 `docs/冲突与决策台账-2026-09-10.md:103`、`:461`、`:539` 的“B-07 已消解、preliminary 与类表完全对上”依据不充分，且与同图同框不同号的现存证据直接冲突。本次**不更改裁决台账、不重写标签**；应在主报告登记“B-07 关闭结论需重开复核”，不能继续据此宣称 preliminary 可直接重训。

## 当前训练配置与推理类别来源

| 范围 | 可证实现状 | 证据 |
|---|---|---|
| 台账裁决的现行训练集 | `D:\AAAdesktop1\shijue\yolo_dataset`，638 图，train 511 / val 127 | 台账:480、487；E:146 |
| YOLOv5s 训练配置 | 指向该 D 盘 data.yaml；七类顺序如下 | `视觉/training/train_yolo5s.py:13`；`视觉/training/runs/yolo5s_geom7c/args.yaml:4`；`视觉/training/data.yaml:2`、`:8` |
| 638 图标签对原始 VOC | 638/638 文件、共 1014 框，类名映射与六位小数归一化坐标逐框一致；无 mismatch | E:156–158；转换依据 `视觉/training/voc2yolo.py:15`、`:20`、`:26`、`:36` |
| 另有 round3 训练线 | D 盘 `block_dataset_v1_7class_round3`，574 / 64 / 64 标签；其 64 个 `ws_` 样本等于重映射版 workspace；训练 args 指向 round3 且模型为 yolo11n.pt | E:190–193、295–298；不能用此替换台账“现行数据集”裁决 |
| MaixCAM 推理入口 | 使用 `MODEL_PATH`（默认 `/root/my_models/model_8766.mud`）创建 `nn.YOLOv8`；显示名称来自 `detector.labels[obj.class_id]`，不从训练 data.yaml 或旁车 txt 动态读取；active 排除原始形状 id 1 | `视觉/src/maixcam_deploy/main.py:29`、`:378`、`:472`、`:47`、`:444` |

638 图原始 VOC 的类名逐框一致只证明转换和编号一致，**不等于实物识别准确率验收**。preliminary/workspace 与现行 yolo_dataset 没有字节相同的图片，不能据此把 yolo_dataset 的正确编号外推到 preliminary（E:148–149）。

统一**预期形状 id**顺序为 `0 cube / 1 cuboid / 2 cylinder / 3 hexagonal_prism / 4 pentagonal_prism / 5 square_pyramid / 6 triangular_prism`（`视觉/training/data.yaml:8`–`:14`；`workspace_label/classes.txt:1`–`:7`）。它不是校赛货格 id 顺序，后者请用主报告的逐跳链路证据。

## 三个 ONNX 的直接读取结果

三个文件均 CPU session 加载成功；共同输入 **`images`, `tensor(float)`, `[1,3,448,448]`**，共同输出 **`output0`, `tensor(float)`, `[1,11,4116]`**；均在模型自身 `metadata.names` 内带上述 0–6 七类顺序，类别数为 **7**，不是根据输出的 11 猜“11 类”（E:303–305）。

**这里的 448 是既有导出资产的实际静态张量尺寸，不是现场帧设置建议。本轮没有把 MaixCAM 320×320 改成 448，也没有向模型送入任何图像。** 三个本地 ONNX 不能单凭名称或旁车表被认作现场 `model_8766`；现场转换模型与原始 ONNX 的版本对应、转换后的实际输入、部署 hash 均【证据不足】。models 目录目前没有任何 `.mud`（E:306），`main.py` 的默认路径是设备绝对路径（`:29`），其存在及内容不在本机三 ONNX 的证明范围内。

| 本地文件 | 模型内自述训练来源 | 真实 opset / IR | 大小（字节） | 证据 |
|---|---|---|---:|---|
| `视觉/models/best_maixcam_opset13.onnx` | `Ultralytics YOLO11n`，`block_dataset_v1_7class/data.yaml` | 13 / 7 | 10447760 | E:303 |
| `视觉/models/yolo5s_geom7c_opset13.onnx` | `Ultralytics YOLOv5s`，`yolo_dataset/data.yaml` | 13 / 7 | 36556987 | E:304 |
| `视觉/models/yolo5s_geom7c_opset17.onnx` | `Ultralytics YOLOv5s`，`yolo_dataset/data.yaml` | 17 / 8 | 36622719 | E:305 |

`best_maixcam_opset13` 的 metadata `args` 仍写原导出 `opset:12`，真实模型 `opset_import` 已是 13；这说明 **metadata 的历史导出参数不能代替实际图结构**（E:303）。模型名字与来源根据二进制内 `description` 报告，不升级为对训练过程的独立认证。

完整 SHA256：

```text
best_maixcam_opset13.onnx  da15c580fb0c8d6324f117eb12ab00494eba136b66c5970400996ef5145ad758
yolo5s_geom7c_opset13.onnx 3685a194a4b768b2b5d068efe7a181a448ff4aa7d83b128b294c0ea47c273b66
yolo5s_geom7c_opset17.onnx 2cfb159f262abf94033a0e0e6878c727749f565f165951909cd59db617088214
```

Hash、输入输出、固有类表、日期与其他元数据的完整原始输出见 E:303–305。主机加载成功不代表 MaixCAM 推理、模型识别精度或实机链路通过。
