# PyCharm YOLO 标注指南

## 数据集位置
```
视觉/datasets/preliminary/
├── images/          # 534 张图片
├── labels/          # 211 个已有标注
├── class.txt        # 类别文件（3 类：cube, cuboid, cylinder）
└── unannotated.txt  # 323 张待标注清单
```

## PyCharm 标注插件推荐

### 方案 1: LabelImg（推荐，最简单）
1. **安装**: `pip install labelImg`
2. **启动**: 在 Terminal 运行 `labelImg`
3. **配置**:
   - Open Dir → 选择 `视觉/datasets/preliminary/images`
   - Change Save Dir → 选择 `视觉/datasets/preliminary/labels`
   - 点击 "PascalVOC" 按钮切换到 "YOLO"
   - Load → 选择 `视觉/datasets/preliminary/class.txt`

### 方案 2: CVAT（功能强大，需要本地部署）
```bash
docker run -d -p 8080:8080 cvat/cvat:latest
# 浏览器打开 http://localhost:8080
```

### 方案 3: PyCharm + YOLO Annotator 插件（无需额外安装）
1. Settings → Plugins → 搜索 "Image Labeling" 或 "YOLO Annotator"
2. 安装后右键图片 → Annotate with YOLO

## 标注流程

### 快速标注（按 unannotated.txt 清单）
1. 打开 `unannotated.txt`
2. 点击第一个图片路径 `images/session_xxx_img_yyy.jpg`
3. 框选物体，选择类别（0=cube, 1=cuboid, 2=cylinder）
4. 保存后自动跳到下一个

### 复核已标注数据（重点！）
1. 打开 `labels/` 目录
2. 随机抽查 20-30 个 `.txt` 文件
3. 检查常见错误：
   - **类别错了**（立方体标成圆柱）
   - **框太大/太小**（背景占一半 / 物体被裁掉）
   - **多标/漏标**（一个物体标了两次 / 有物体没标）
   - **坐标越界**（x/y/w/h 不在 [0, 1] 范围内）

## 标注质量标准

### ✅ 好的标注
```
# 文件: session_xxx_img_001.txt
0 0.512 0.345 0.123 0.234  # 立方体，框紧贴物体边缘，坐标在 [0,1] 内
2 0.789 0.567 0.098 0.156  # 圆柱，边界框刚好覆盖整个物体
```

### ❌ 坏的标注
```
# 类别错误
1 0.512 0.345 0.123 0.234  # 明明是 cube(0) 却标成 cuboid(1)

# 框太松
0 0.512 0.345 0.500 0.600  # 背景占了一半

# 框太紧
2 0.789 0.567 0.050 0.080  # 物体边缘被裁掉

# 坐标越界
0 1.200 0.345 0.123 0.234  # x_center = 1.2 > 1.0（越界！）
```

## 类别 ID 对照表

| class_id | 类别名称 | 英文 | 形状特征 |
|---------|---------|------|---------|
| 0 | 立方体 | cube | 正方体，六面相等 |
| 1 | 长方体 | cuboid | 长方体，三边不等 |
| 2 | 圆柱 | cylinder | 圆形截面 + 直边 |

## YOLO 标注格式说明

每个 `.txt` 文件对应一张图片，每行一个物体：
```
<class_id> <x_center> <y_center> <width> <height>
```

- **归一化坐标**：所有数值在 [0, 1] 范围内
- **x_center, y_center**：物体中心点相对图片的位置
- **width, height**：边界框相对图片的宽高比例

示例（假设图片 640x480）：
```
0 0.5 0.5 0.2 0.3
```
- class_id = 0（立方体）
- 中心点 = (640*0.5, 480*0.5) = (320, 240)
- 宽高 = (640*0.2, 480*0.3) = (128, 144)
- 实际像素框 = (256, 168, 384, 312)

## 标注进度跟踪

```bash
# 查看当前进度
cd 视觉/datasets/preliminary
echo "已标注: $(ls labels/*.txt | wc -l) / 534"
echo "剩余: $((534 - $(ls labels/*.txt | wc -l)))"

# 重新生成未标注清单
cd ../../..
python generate_checklist.py
```

## 常见问题

### Q1: PyCharm 打不开图片？
**A**: 确保图片路径正确，中文路径用 PowerShell 而非 Git Bash

### Q2: 保存的 `.txt` 文件是空的？
**A**: 检查是否切换到了 YOLO 格式（不是 PascalVOC）

### Q3: 标注坐标超出 [0,1] 范围？
**A**: 手动编辑 `.txt` 文件，把越界值钳位到 [0, 1]

### Q4: 一张图片有多个物体怎么办？
**A**: 在 `.txt` 文件里写多行，每行一个物体

## 下一步：训练前检查

标注完成后，运行：
```bash
cd 视觉
python -m sorting_vision.validate_dataset datasets/preliminary
```

验证通过后才能开始训练！
