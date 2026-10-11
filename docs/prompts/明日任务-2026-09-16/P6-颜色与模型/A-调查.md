# P6-A · 颜色数据通路 + 模型族/`.mud`（🔨 调查取证）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md`、
> `../协作-2026-09-15/02-视觉.md`、
> `../协作-2026-09-15/04-架构与安全审查.md` 的 §1（E-17）
>
> ⚠️ **本问题的"裁决"由 对方做**（`B-裁决.md`）。
> **你出的是证据**，给裁定者用。**不要自己拍板。**

---

## 0. 两个待查的事

| # | 事 | 已知 |
|---|---|---|
| **①** | **颜色算法跑在哪台机器上？数据怎么过去？** | 疑似**通路根本不存在** |
| **②** | **模型族 + `.mud` 编号** | 三方冲突，配置指向不存在的文件 |

---

## 1. ① 颜色数据通路 —— 你要证的与要查的

### 已知事实（先用，别重查）

- **MaixCAM 上根本没有颜色代码**：`视觉/src/maixcam_deploy/main.py`（476 行）
  全文只有 YOLO 检测 + 画框。grep `HSV|hsv|color` 只命中画框用的 `image.COLOR_RED`
- **颜色的真身**：`视觉/src/sorting_vision/color_quant.py:354-385` 的 `color_name()`
  （HSL 硬编码阈值）
- **那条纯逻辑包目前没有任何生产消费方**（`BoxAssignment`/`DropTable` 只在测试里被构造）
- **`main.py:339-365` 的 `encode_batch_targets`**：每个目标只有 **7 字节**
  ```
  target_count(1) + task_id(2,BE) + 每目标[ class_id(1) + confidence(1) + X(2,BE) + Y(2,BE) + angle(1,0xFF) ]
  ```
  **没有颜色、没有 RGB、没有任何像素**。它自己的 docstring 写 "never for motion"

### 你要证的

**"树莓派算不出颜色"** —— 把这条**从证据上钉死**：

1. `main.py` 到底发什么？**逐字段列表 + 行号**
2. **树莓派收到的数据里，有没有任何东西能推出颜色？**（逐一排查）
3. `SocketVisionSource` / `scheduler` / `sort_plan` **有没有任何地方在等一个颜色字段**？
4. **全仓 grep `color_id`、`classify_roi_color`、`build_sort_plan`** ——
   有没有任何生产代码调用它们？（若无，说"无消费方"）

### 你要给的三个方案的**代价评估**（不是选择）

| 方案 | 做法 | 你要评估 |
|---|---|---|
| **A** | MaixCAM 算每框主色，`BATCH_TARGETS` 加 1 字节 `color_id` | ① `color_quant.py` 移植到 MaixCAM 要改多少？它依赖什么（PIL？纯 Python？）② MaixCam 的算力够吗（要读那几帧的推理耗时）③ 协议改动面 |
| **B** | MaixCAM 把图像/ROI 传给树莓派 | 带宽、延迟、协议改动面 |
| **C** | 其他（你有更好的就说） | |

**⚠️ 所有方案都会改协议 → 都是 L4。评估代价就好，别动手。**

---

## 2. ② 模型族 + `.mud`

### 已知事实

- `视觉/models/` 有 3 个 `.onnx`：
  | 文件 | 大小 | 时间 |
  |---|---|---|
  | `best_maixcam_opset13.onnx` | 10,447,760 | 2026-08-25 |
  | `yolo5s_geom7c_opset13.onnx` | 36,556,987 | 2026-09-03 |
  | `yolo5s_geom7c_opset17.onnx` | 36,622,719 | 2026-09-03 |
- `main.py` 用的是 **`nn.YOLOv8`**（`main.py:375`）
- **工作区内 0 个 `.mud`**
- **但** `C:\Users\29845\Downloads\maixhub-model-convert-maixcam-*` 里有 **11 个包**，
  含 `model_8622.mud`(300B) + `model_8622.cvimodel`(2.99MB)、`model_8629.*`
- 两份配置写的是 `model_path = /root/my_models/model_8766.mud` → **8766 不存在**

### ✅ 已更正：`8766` **是存在的**（2026-09-15 晚复核）

`C:\Users\29845\Downloads\maixhub-model-convert-maixcam-8766.zip`
→ **`model_8766.mud` + `model_8766.cvimodel`**

**所以两份配置里的 `model_path = /root/my_models/model_8766.mud` 是【对的】**
—— 缺的只是"把这两个文件推到 MaixCAM 的该路径下"。

**Downloads 里的全部唯一组合**：

| 包 | 内容 |
|---|---|
| `maixhub-model-convert-maixcam-8766.zip` | `model_8766.mud` + `model_8766.cvimodel` ← **配置要的就是这个** |
| `maixhub-model-convert-maixcam-8622.zip` | `model_8622.mud` + `model_8622.cvimodel` |
| `maixhub-model-convert-maixcam-8629*.zip`（重复 6+ 份） | `model_8629.mud` + `model_8629.cvimodel` |

### 🔴 但真问题没解决：**工作区里没有 `.mud`，只有 onnx**

`视觉/models/` 里是 3 个 `.onnx`：

| 文件 | 大小 | 时间 |
|---|---|---|
| `best_maixcam_opset13.onnx` | 10,447,760 | 2026-08-25 |
| `yolo5s_geom7c_opset13.onnx` | 36,556,987 | 2026-09-03 |
| `yolo5s_geom7c_opset17.onnx` | 36,622,719 | 2026-09-03 |

而 `main.py` 用的是 **`nn.YOLOv8`**（`main.py:375`）。

### 你要查的

1. **`Downloads` 里那些包到底有几个不同版本？** 列出所有唯一的 `(mud, cvimodel)` 组合
2. **`.mud` 只有 300 字节 —— 它是什么？** 打开看内容（文本？JSON？）
   它和 `.cvimodel` 什么关系？
3. **`nn.YOLOv8` vs `yolo5s_*` 的 onnx：到底哪个对？**
   - 查 MaixPy 官方文档：`nn.YOLOv8` 支持哪些输入？（给链接）
   - 读 onnx 的 metadata / `graph.input`，判断这三个文件各是什么族、什么输入尺寸
   - **不要靠文件名猜**
4. **`model_8622` 和 `model_8629` 有什么区别？** 大小一样（2,994,312 B）——
   是同一个模型不同编号，还是不同模型？
5. **8766 是哪里来的？** 追一下这个数字的出处
   （提示：`archive/packages/latest-code/代码包说明.md` 被台账标为"型号/目录/端口多处失实"）

### ⚠️ 你可以做的一件真事（用户已认可）

用户说：**"这个不是可以在电脑上用 maixvision 跑代码吗"** —— 对，这是**验证模型的正确工具**
（MaixVision 连接 MaixCAM，代码跑在**设备上**，电脑上看实时画面）。

**MaixVision 安装包在 `C:\Users\29845\Downloads\MaixVision-1.2.2-setup.exe`。**
**但装不装、推哪个模型到设备上 —— 都要用户批准**（改目标机环境）。
**你出步骤，不要自己装。**

---

## 3. 交付格式

```
## ① 颜色通路
"树莓派算不出颜色" 的证据链（每条带 文件:行号）
全仓消费方排查结果
三方案代价评估表（A/B/C）

## ② 模型与 .mud
Downloads 里所有唯一 (mud, cvimodel) 组合表
.mud 的内容与作用
nn.YOLOv8 vs yolo5s 的判定（附 onnx 元数据证据）
8622 vs 8629 的区别
8766 的来源追溯

## 🔴 我发现的、裁定者必须知道的事
## 我明确无法判断的
```

## 4. 红线

- ❌ **不要删/覆盖任何 `.onnx`**（L4：删模型权重）
- ❌ **不要训练新模型**（可以给方案）
- ❌ **不要自己装 MaixVision、不要往设备推文件**（L4）
- ❌ 不改协议、不改 `color_quant.py`（那是接线，属裁定后的实施）
