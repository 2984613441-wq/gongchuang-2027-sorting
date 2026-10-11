# P10-B · 数据集与训练（🔍 独立复核）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md`、
> **`视觉/training/README-视觉资产来源-2026-09-15.md`**、`docs/冲突与决策台账-2026-09-10.md` 的 **V-13 / V-15**
>
> 你是 **P10 的复核者**，对方出方案与核实。**只复核，不改文件。**

---

## 1. 🔍 最高价值的一条：**数据泄漏判定**

训练报告的 mAP50 = **0.865** 是当前唯一的模型质量依据。
**但如果 train/val 划分有泄漏，这个数字就是虚的。**

**你要独立判断**（这是本任务最重要的一问）：

1. D 盘 `yolo_dataset` 的 **train 511 / val 127** 是怎么分的？
   去看 `voc2yolo.py` / `prepare_voc_dataset.py` / `make_dataset` 的划分逻辑。
2. ⚠️ **关键**：同一个物体 / 同一个拍摄批次的**相邻帧**有没有跨集合？
   - 数据集图片名形如 `0824171735_device_1.jpg`、`0824171743_device_2.jpg` ——
     **时间戳连号**！如果连号的图被随机分到 train 和 val 两侧 → **严重泄漏**
3. **去实际检查**（不要只看代码）：
   ```powershell
   # 列出 val 集合里的文件名，看时间戳分布是否与 train 交错
   Get-ChildItem "D:\AAAdesktop1\shijue\yolo_dataset\images\val" | Select-Object -ExpandProperty Name | Sort-Object | Select-Object -First 30
   Get-ChildItem "D:\AAAdesktop1\shijue\yolo_dataset\images\train" | Select-Object -ExpandProperty Name | Sort-Object | Select-Object -First 30
   ```
4. **给结论**：mAP50 = 0.865 是**可信**还是**虚高**？
   如果是虚高，**实机表现会比报告差多少**？（给区间估计 + 依据）

> ⚠️ 这一条直接影响"模型到底够不够用"的判断（P6 会用到）—— **做完交叉给 P6**。

---

## 2. 🔍 核实 V-19：到底用哪个预训练权重

对方会给核实结论。你要**自己再核一遍**：

```powershell
Get-ChildItem "D:\AAAdesktop1\shijue" -Filter 'yolov5*' -Recurse -Depth 1 |
  Select-Object Name, Length, FullName
```

**判断**：
1. `yolov5su.pt` 存在吗？`yolov5s.pt` 存在吗？两个都在吗？
2. `args.yaml` 记的 `model: yolov5s.pt` —— ultralytics 会**把实际文件名写进 args**，
   所以这条**比报告的正文更可信**。对方同意吗？
3. **报告里那句 `yolov5su.pt` 是错的吗？** 给结论。

---

## 3. 🔍 审查 V-15 防错方案

对方会给一个"零拷贝防错"方案。审：

1. **它有没有先 grep 谁引用 `视觉/datasets/preliminary`？**
   你**自己再 grep 一遍**，看它漏了哪些引用点。
   ```powershell
   Get-ChildItem "C:\Users\29845\Desktop\工创赛" -Recurse -Include '*.py','*.md','*.yaml','*.ini' |
     Select-String -Pattern 'datasets/preliminary|datasets\\\\preliminary' | Select-Object -First 30
   ```
2. **方案会不会破坏现有测试或工具？**（比如 `视觉/tests/` 已归档，但别的脚本可能引用）
3. **"加 README 警告"够不够？** 还是应该更硬（改名 / 删 / 加机器可读的标记）？
   **给判断** —— 你的强项是边界与失效模式。

---

## 4. 🔍 弱类对策的时间估算可信吗

对方会给"补采 vs 不改模型"两条路 + 时间估算。审：

1. **时间估算有依据吗**，还是拍脑袋？
2. **"不改模型"那条路**：靠降阈值改善召回，但**精度会更差** ——
   误检变多会不会导致**分错盒**（比漏检更糟）？给判断。
3. **哪条路在校赛前更现实？** 给结论。

---

## 5. 交付格式

```
## 🔴 数据泄漏判定 —— 结论 + 证据 + 对 mAP 0.865 的影响
## V-19 核实结论（用哪个 .pt）
## V-15 防错方案审查（漏的引用点 / 够不够硬）
## 弱类对策审查（时间估算可信度 / 误检 vs 漏检的取舍）
## 我明确无法判断的
```

## 6. 红线

- ❌ **只复核，不改任何文件**
- ❌ **不动 D 盘任何东西**（用户裁决：原封不动）
- ❌ 不要删工作区那份 386 图数据集
- ❌ 不训练模型
