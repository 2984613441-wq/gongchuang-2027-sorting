# ToF深度融合设计文档

**文档版本**：v1.0  
**日期**：2026-10-11  
**状态**：设计完成，待ToF模块到货验证  
**负责人**：视觉子系统团队

---

## 1. 背景与问题

### 1.1 俯视歧义问题

YOLO模型基于俯视图像识别形状，存在**三组无法区分的形状对**：

| 歧义组 | 俯视特征 | 问题 |
|--------|---------|------|
| **圆柱 vs 球** | 都是圆形 | 无法区分 |
| **三棱柱 vs 正四面体** | 都是三角形 | 无法区分 |
| **正方体 vs 四棱锥** | 都是正方形 | 无法区分 |

### 1.2 省赛影响

- 省赛24件**必然包含上述歧义组**
- 纯YOLO识别会**误判** → 分错盒 → 0分
- 需要**深度信息**解决歧义

---

## 2. 解决方案：ToF深度融合

### 2.1 核心思路

**利用高度/宽度比值区分形状**：
- 圆柱高，球矮（圆柱高度 > 1.2倍直径）
- 三棱柱高，正四面体矮（棱柱高度 > 0.8倍底边）
- 正方体高宽相等，四棱锥矮（锥高度 < 0.6倍底边）

### 2.2 技术路线

```
YOLO检测 → 提取bbox宽度(px)
    ↓
ToF测量 → 物体高度(mm)
    ↓
计算高宽比 = 高度 / (宽度 × px_to_mm)
    ↓
应用判据阈值 → 输出精确形状
```

---

## 3. 接口设计

### 3.1 核心函数

```python
def depth_disambiguate(
    yolo_shape: str,              # YOLO预测的形状
    bbox_width_px: float,         # 检测框宽度（像素）
    depth_reading: DepthReading,  # ToF深度测量
    px_to_mm: float = 1.0,        # 像素到毫米转换系数
) -> str:
    """使用ToF深度消除YOLO形状歧义。
    
    Returns:
        精确形状标签，例如 "sphere", "cylinder"
    """
```

### 3.2 数据结构

```python
@dataclass(frozen=True)
class DepthReading:
    height_mm: float      # 物体高度（毫米）
    confidence: float     # 传感器置信度 [0, 1]
```

---

## 4. 判据阈值

### 4.1 初始值（基于标准几何）

| 歧义组 | 判据 | 阈值 | 依据 |
|--------|------|------|------|
| **圆柱 vs 球** | 高/宽 > 1.2 | 圆柱 | 标准圆柱高宽比 |
|  | 高/宽 < 0.8 | 球 | 球直径≈高度 |
| **三棱柱 vs 正四面体** | 高/宽 > 0.8 | 三棱柱 | 棱柱通常较高 |
|  | 高/宽 < 0.6 | 正四面体 | 四面体高≈0.58×边长 |
| **正方体 vs 四棱锥** | 0.9 < 高/宽 < 1.1 | 正方体 | 正方体高=宽 |
|  | 高/宽 < 0.6 | 四棱锥 | 锥高≈0.5-0.7×底边 |

### 4.2 校准要求

⚠️ **上述阈值为初始值，必须现场标定**

**标定方法**：
1. 准备6类实物（圆柱/球/三棱柱/正四面体/正方体/四棱锥）
2. 在实际光照+ToF高度下测量10次
3. 计算高宽比统计值（均值±标准差）
4. 调整阈值确保分类边界清晰

---

## 5. 集成方案

### 5.1 主链集成位置

```python
# 视觉/src/sorting_vision/pipeline.py

from .depth_fusion import depth_disambiguate, requires_depth_disambiguation

def infer_batch(..., tof_readings: list[DepthReading] | None = None):
    # ... YOLO推理 ...
    
    # 深度融合（如果ToF可用）
    if tof_readings:
        for detection, tof_reading in zip(detections, tof_readings):
            if requires_depth_disambiguation(detection.class_name):
                refined_shape = depth_disambiguate(
                    yolo_shape=detection.class_name,
                    bbox_width_px=detection.bbox.width,
                    depth_reading=tof_reading,
                    px_to_mm=self.px_to_mm_calibration
                )
                detection.class_name = refined_shape  # 覆盖YOLO预测
```

### 5.2 降级策略

**ToF不可用时的处理**：
- `tof_readings=None` → 跳过深度融合，使用YOLO原始预测
- `depth_reading.confidence < 0.7` → 置信度低，返回YOLO预测
- `bbox_width_px == 0` → 检测框异常，返回YOLO预测

---

## 6. ToF硬件要求

### 6.1 传感器选型

| 参数 | 要求 | 备注 |
|------|------|------|
| 测量范围 | 30-300mm | 覆盖物料高度 |
| 分辨率 | ≤1mm | 区分5mm高度差 |
| 响应时间 | <100ms | 匹配YOLO帧率 |
| 接口 | I2C/UART | 树莓派兼容 |

### 6.2 推荐型号

- **VL53L1X**（STMicroelectronics）：I2C接口，测量范围4-4000mm
- **TF-Luna**（Benewake）：UART接口，测量范围0.2-8m

### 6.3 安装位置

```
相机（俯视）
    ↓
转盘表面
    ↑
ToF传感器（侧面45°）
```

**要求**：
- ToF与相机视野重叠
- 避免遮挡物料
- 固定支架防抖动

---

## 7. 测试计划

### 7.1 单元测试（已完成）

- ✅ 三组歧义的判据边界测试
- ✅ 像素到毫米转换
- ✅ 低置信度降级
- ✅ 异常输入处理

**测试覆盖**：48项测试，全部通过

### 7.2 集成测试（ToF到货后）

| 测试场景 | 输入 | 预期输出 |
|---------|------|----------|
| 高圆柱 | YOLO=cylinder, H=70mm, W=50mm | cylinder |
| 球 | YOLO=cylinder, H=40mm, W=50mm | sphere |
| 三棱柱 | YOLO=triangular_prism, H=50mm, W=50mm | triangular_prism |
| 正四面体 | YOLO=triangular_prism, H=30mm, W=50mm | regular_tetrahedron |
| 正方体 | YOLO=cube, H=50mm, W=50mm | cube |
| 四棱锥 | YOLO=cube, H=25mm, W=50mm | square_pyramid |

### 7.3 现场验证（省赛前）

- [ ] 24件混放场景
- [ ] ToF置信度统计
- [ ] 误判率<5%
- [ ] 延迟增量<2秒

---

## 8. 性能指标

### 8.1 精度目标

| 指标 | 目标值 | 验收标准 |
|------|--------|----------|
| 圆柱vs球 正确率 | ≥95% | 10次测试≥9次正确 |
| 三棱柱vs四面体 正确率 | ≥90% | 实物标准件测试 |
| 正方体vs四棱锥 正确率 | ≥95% | 实物标准件测试 |
| ToF响应延迟 | <100ms | 单次测量时间 |
| 整体延迟增量 | <2秒 | 相比无ToF场景 |

### 8.2 鲁棒性

- ToF不可用时自动降级（不中断识别）
- 低置信度时返回YOLO预测（不强制深度）
- 异常数据（宽度=0, 高度负数）安全处理

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| ToF模块延迟到货 | 中 | 高 | 备选方案：问裁判确认件范围 |
| 现场光照干扰ToF | 中 | 中 | 选择抗干扰型号（VL53L1X） |
| 阈值现场标定困难 | 低 | 中 | 预留3天标定时间 |
| 深度融合误判率高 | 低 | 高 | 降级策略：关闭深度融合 |

---

## 10. 时间计划

| 里程碑 | 时间 | 依赖 |
|--------|------|------|
| ✅ 设计完成 | Week 1 | 无 |
| ✅ 单元测试通过 | Week 1 | 无 |
| ToF模块到货 | Week 3 | 下单（立即） |
| 集成到主链 | Week 4 | ToF到货 |
| 现场标定阈值 | Week 6 | 到实验室 |
| 省赛前验证 | Week 7 | 完整系统 |

---

## 11. 参考资料

### 11.1 相关文档

- `视觉/src/sorting_vision/depth_fusion.py`：核心实现
- `视觉/tests/test_depth_fusion.py`：单元测试
- `docs/交接总纲-20261002.md§7.2-7`：三组歧义描述

### 11.2 外部资源

- VL53L1X数据手册：https://www.st.com/resource/en/datasheet/vl53l1x.pdf
- ToF原理：Time-of-Flight测距技术

---

## 12. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2026-10-11 | 初始设计 | 视觉团队 |

---

**审批**：待ToF模块到货后进入实施阶段
