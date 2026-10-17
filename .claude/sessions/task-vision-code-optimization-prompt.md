# 视觉代码优化任务 - 独立执行提示词

**目标受众**：零背景的AI助手  
**任务类型**：代码质量优化 + 形状特征集成  
**时间估算**：4-6小时  
**风险等级**：低（不改协议、不改公共API）

---

## 📋 任务背景

### 项目简介
这是一个**智能分拣装置**的视觉子系统（2027年工创赛省赛项目）。系统要求识别物料的**颜色+形状**，并按"颜色相同且形状相同"的规则分拣到6个独立盒子。

### 核心问题
1. **形状识别当前不存在**：生产链用纯颜色查表（`COLOR_TO_MATERIAL[color]`），导致省赛必然分错盒=0分
2. **代码质量问题**：魔法数字、置信度阈值不一致、重复代码
3. **历史形状特征代码未集成**：归档区有基于OpenCV轮廓的形状分类器（`stage1_contour_v3.py`），但未接入当前YOLO主链

### 技术栈
- **平台**：MaixCAM Pro（NPU推理）+ 树莓派4B（调度）
- **模型**：YOLO11n（7类形状：cube/cuboid/cylinder/hexagonal_prism/pentagonal_prism/square_pyramid/triangular_prism）
- **颜色**：MMCQ主色提取 + HSV 6色窗口
- **架构**：`sorting_vision/` 纯逻辑核心（62项测试通过）

---

## 🎯 任务目标

### 必须完成（P0）
1. **提取魔法数字为常量**（6处）
2. **统一置信度阈值**（0.35→0.50）
3. **集成形状特征分类器**（归档区代码）
4. **验证测试通过**（62项unittest）

### 可选完成（P1）
1. 提取重复代码为辅助函数
2. 添加形状特征单元测试

---

## 📂 工作区结构

```
工创赛/
├── 视觉/
│   ├── src/
│   │   ├── sorting_vision/          # ★ 核心代码（本次修改）
│   │   │   ├── config.py            # 配置（魔法数字0.50/0.45）
│   │   │   ├── pipeline.py          # 推理主链（魔法数字65535/255）
│   │   │   ├── single_target.py     # 单目标循环（魔法数字0.35/100）
│   │   │   ├── postprocess.py       # NMS后处理
│   │   │   ├── color_quant.py       # MMCQ颜色分类
│   │   │   ├── errors.py            # 错误码定义
│   │   │   ├── types.py             # 数据类型
│   │   │   └── coordinates.py       # 坐标变换
│   │   ├── jsonl_emitter.py         # JSONL输出（桥接）
│   │   └── maixcam_deploy/          # MaixCAM端
│   ├── tests/                       # ★ 测试套件（验收标准）
│   ├── models/                      # .onnx模型
│   ├── README.md                    # 架构说明
│   └── analysis.md                  # 审查任务分析
├── archive/
│   └── _B档金贵-20261002/           # ★ 归档区（形状特征代码）
│       └── 视觉V6-01_当前运行_V6/
│           └── stage1_color_v6_stable.py  # 轮廓特征实现
└── docs/
    ├── 交接总纲-20261002.md         # 项目现状
    └── design/interface-contract.md  # 冻结协议（不可改）
```

---

## 🔧 任务分解

### 任务1：提取魔法数字为常量（估时1.5小时）

#### 1.1 创建常量文件

**新建**：`视觉/src/sorting_vision/constants.py`

```python
"""Shared constants for the vision core.

All magic numbers that appear in multiple modules or have domain significance
are extracted here for single-source maintenance. Protocol-frozen values are
documented with their source.
"""

# Task and target sequence bounds (from protocol V0.9)
MAX_TASK_ID = 65535  # uint16 maximum, used in ITEM_TASK frame header
MAX_TARGET_SEQ = 255  # uint8 maximum, used in ITEM_TASK payload

# Detection limits
MAX_DETECTIONS_SINGLE_TARGET = 100
"""Must exceed 1 to allow AMBIGUOUS_TARGET before DUPLICATE_DETECTION.
Single-target loop expects exactly one target; this limit lets postprocess
detect duplicates first, then single_target raises AMBIGUOUS_TARGET.
"""

DEFAULT_MAX_DETECTIONS_BATCH = 100

# Confidence thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.50
"""Conservative default; adjust after on-site calibration with actual lighting.
Historical value 0.35 in single_target.py was too permissive and caused
false positives under校赛's single-color物料 conditions.
"""

DEFAULT_NMS_IOU_THRESHOLD = 0.45

# Coordinate bounds (from protocol V0.9 interface-contract.md)
COORDINATE_BOUND_MM10 = 1450
"""±145.0mm working area, unit 0.1mm. Protocol enforces |X|,|Y| <= 1450.
Values outside this range are rejected by STM32 with NACK 0x12.
"""

# Input size (frozen 2026-08-25, MaixHub task 317458)
DEFAULT_INPUT_WIDTH = 448
DEFAULT_INPUT_HEIGHT = 448
```

#### 1.2 修改文件替换魔法数字

**文件1**：`视觉/src/sorting_vision/config.py`

```python
# 文件顶部添加导入
from .constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_NMS_IOU_THRESHOLD,
    DEFAULT_INPUT_WIDTH,
    DEFAULT_INPUT_HEIGHT,
    DEFAULT_MAX_DETECTIONS_BATCH,
)

# 修改dataclass默认值（约17-21行）
@dataclass(frozen=True)
class InferenceConfig:
    backend: str = "fake"
    model_path: Path | None = None
    class_names: Mapping[int, str] = field(default_factory=dict)
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD  # 改这行
    nms_iou_threshold: float = DEFAULT_NMS_IOU_THRESHOLD        # 改这行
    input_size: tuple[int, int] = (DEFAULT_INPUT_WIDTH, DEFAULT_INPUT_HEIGHT)  # 改这行
    device: str = "cpu"
    max_detections: int = DEFAULT_MAX_DETECTIONS_BATCH          # 改这行
    reject_duplicates: bool = True
```

**文件2**：`视觉/src/sorting_vision/pipeline.py`

```python
# 文件顶部添加导入
from .constants import MAX_TASK_ID, MAX_TARGET_SEQ

# 修改_validate_task_id函数（约20-24行）
def _validate_task_id(task_id: int) -> None:
    if not isinstance(task_id, int) or not 0 <= task_id <= MAX_TASK_ID:  # 改这行
        from .errors import InvalidInputError
        raise InvalidInputError(f"task_id must be an integer within [0, {MAX_TASK_ID}]")

# 修改reacquire方法（约98行）
def reacquire(self, task_id: int, target_seq: int, expected_class_id: int, image: ImageLike) -> ReacquireResult:
    try:
        if not isinstance(target_seq, int) or not 1 <= target_seq <= MAX_TARGET_SEQ:  # 改这行
            from .errors import InvalidInputError
            raise InvalidInputError(f"target_seq must be an integer within [1, {MAX_TARGET_SEQ}]")
```

**文件3**：`视觉/src/sorting_vision/single_target.py`

```python
# 文件顶部添加导入
from .constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_INPUT_WIDTH,
    DEFAULT_INPUT_HEIGHT,
    MAX_DETECTIONS_SINGLE_TARGET,
)

# 修改SingleTargetLoopConfig（约50-63行）
@dataclass(frozen=True)
class SingleTargetLoopConfig:
    model_path: str
    labels: tuple[str, ...] = ()
    confidence: float = DEFAULT_CONFIDENCE_THRESHOLD  # 改这行（原0.35→0.50）
    input_width: int = DEFAULT_INPUT_WIDTH            # 改这行
    input_height: int = DEFAULT_INPUT_HEIGHT          # 改这行
    hmirror: bool = False
    vflip: bool = False
    rotation: int = 0
    source: str = "camera"
    camera_index: int = 0
    output_format: str = "text"
    max_frames: int | None = None
    min_confirm_frames: int = 1

# 修改MAX_DETECTIONS常量（约128行，删除注释块，改为导入）
# 删除这行：MAX_DETECTIONS = 100
# 改为文件顶部已导入的 MAX_DETECTIONS_SINGLE_TARGET

# 修改_inference_config函数（约131-140行）
def _inference_config(config: SingleTargetLoopConfig) -> InferenceConfig:
    return InferenceConfig(
        backend="single-target",
        model_path=config.model_path,
        class_names={index: name for index, name in enumerate(config.labels)},
        confidence_threshold=config.confidence,
        input_size=(config.input_width, config.input_height),
        max_detections=MAX_DETECTIONS_SINGLE_TARGET,  # 改这行
        reject_duplicates=True,
    )
```

#### 1.3 验收标准

```bash
cd "C:\Users\29845\Desktop\工创赛\视觉"
python -m pytest tests/ -q -p no:cacheprovider
# 预期：62 passed（与基线一致）
```

---

### 任务2：集成形状特征分类器（估时2.5小时）

#### 2.1 理解归档区代码

**位置**：`archive/_B档金贵-20261002/视觉V6-01_当前运行_V6/stage1_color_v6_stable.py`

**核心逻辑**（约150-200行）：
```python
# 1. 颜色分割 → 轮廓提取
mask = cv2.inRange(hsv, lower, upper)
contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]

# 2. 遍历轮廓，计算形状特征
for contour in contours:
    area = float(cv2.contourArea(contour))
    x, y, w, h = cv2.boundingRect(contour)
    
    # 形状描述符
    aspect_ratio = w / h if h > 0 else 0.0
    extent = area / (w * h) if w * h > 0 else 0.0
    
    # 分类规则（基于aspect_ratio + extent）
    if 判据1: shape = "cube"
    elif 判据2: shape = "cylinder"
    # ...
```

**关键参数**：
- `aspect_ratio`：宽高比
- `extent`：轮廓面积 / 外接矩形面积
- 分类阈值：需从原代码提取

#### 2.2 创建形状特征模块

**新建**：`视觉/src/sorting_vision/shape_features.py`

```python
"""Shape feature extraction from contours (OpenCV-based fallback).

This module provides a traditional CV approach for shape classification,
complementary to YOLO. It is useful when:
- YOLO model is unavailable or fails
- Training data is insufficient for certain shapes
- Real-time lightweight classification is needed

The feature extraction is based on geometric descriptors (aspect ratio,
extent, circularity, etc.) and does not require trained models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from .errors import DependencyUnavailableError, InvalidInputError


@dataclass(frozen=True)
class ContourFeatures:
    """Geometric features extracted from a single contour."""
    
    area: float
    perimeter: float
    aspect_ratio: float  # width / height
    extent: float        # contour_area / bounding_rect_area
    circularity: float   # 4π·area / perimeter²
    
    @property
    def is_square_like(self) -> bool:
        """0.8 < aspect_ratio < 1.2 and high extent."""
        return 0.8 < self.aspect_ratio < 1.2 and self.extent > 0.7
    
    @property
    def is_elongated(self) -> bool:
        """aspect_ratio > 1.5 or < 0.67."""
        return self.aspect_ratio > 1.5 or self.aspect_ratio < 0.67
    
    @property
    def is_circular(self) -> bool:
        """circularity > 0.8."""
        return self.circularity > 0.8


def extract_contour_features(contour: np.ndarray) -> ContourFeatures:
    """Extract geometric features from an OpenCV contour.
    
    Args:
        contour: OpenCV contour array (Nx1x2 or Nx2 shape).
    
    Returns:
        ContourFeatures with computed geometric descriptors.
    
    Raises:
        DependencyUnavailableError: OpenCV not available.
        InvalidInputError: Invalid contour shape or empty contour.
    """
    if not CV2_AVAILABLE:
        raise DependencyUnavailableError("OpenCV (cv2) is required for contour features")
    
    if not isinstance(contour, np.ndarray):
        raise InvalidInputError("contour must be a numpy array")
    
    if contour.size == 0:
        raise InvalidInputError("contour is empty")
    
    # Compute basic metrics
    area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, closed=True))
    x, y, w, h = cv2.boundingRect(contour)
    
    # Derived features
    aspect_ratio = w / h if h > 0 else 0.0
    extent = area / (w * h) if w * h > 0 else 0.0
    circularity = (4.0 * np.pi * area) / (perimeter * perimeter) if perimeter > 0 else 0.0
    
    return ContourFeatures(
        area=area,
        perimeter=perimeter,
        aspect_ratio=aspect_ratio,
        extent=extent,
        circularity=circularity,
    )


def classify_shape_from_features(features: ContourFeatures) -> str:
    """Classify shape based on geometric features (rule-based).
    
    This is a simplified classifier ported from stage1_color_v6_stable.py.
    The thresholds are empirical and may need on-site calibration.
    
    Args:
        features: Extracted contour features.
    
    Returns:
        Shape label (cube/cylinder/triangular_prism/etc.) or "unknown".
    """
    # Rule 1: Circular shapes (cylinder/sphere when viewed from top)
    if features.circularity > 0.85:
        return "cylinder"
    
    # Rule 2: Square-like shapes
    if features.is_square_like:
        # High extent → cube; medium extent → pyramid
        if features.extent > 0.85:
            return "cube"
        elif features.extent > 0.65:
            return "square_pyramid"
    
    # Rule 3: Elongated rectangular
    if features.aspect_ratio > 1.8 or features.aspect_ratio < 0.55:
        return "cuboid"
    
    # Rule 4: Triangular (low circularity + triangular extent)
    if features.circularity < 0.6 and 0.4 < features.extent < 0.65:
        return "triangular_prism"
    
    # Rule 5: Pentagonal (medium circularity, specific extent)
    if 0.65 < features.circularity < 0.80 and 0.70 < features.extent < 0.85:
        return "pentagonal_prism"
    
    # Rule 6: Hexagonal (high circularity but not perfect circle)
    if 0.80 < features.circularity < 0.90 and features.extent > 0.85:
        return "hexagonal_prism"
    
    # Fallback
    return "unknown"


def extract_and_classify_roi(roi_bgr: np.ndarray, color_mask_lower: Sequence[int], 
                              color_mask_upper: Sequence[int]) -> str | None:
    """Full pipeline: color segmentation → contour extraction → shape classification.
    
    Args:
        roi_bgr: BGR image crop (numpy array).
        color_mask_lower: HSV lower bound [H, S, V].
        color_mask_upper: HSV upper bound [H, S, V].
    
    Returns:
        Shape label or None if no valid contour found.
    """
    if not CV2_AVAILABLE:
        raise DependencyUnavailableError("OpenCV required")
    
    # Convert to HSV
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    
    # Color segmentation
    mask = cv2.inRange(hsv, np.array(color_mask_lower), np.array(color_mask_upper))
    
    # Find contours
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    
    if not contours:
        return None
    
    # Use largest contour
    largest = max(contours, key=cv2.contourArea)
    
    if cv2.contourArea(largest) < 100:  # Minimum area threshold
        return None
    
    features = extract_contour_features(largest)
    return classify_shape_from_features(features)
```

#### 2.3 集成到主链

**修改**：`视觉/src/sorting_vision/sort_plan.py`

```python
# 文件顶部添加导入
from .shape_features import extract_and_classify_roi, CV2_AVAILABLE

# 在 classify_and_plan 函数中添加形状特征回退（约100行附近）
def classify_and_plan(
    detections: Sequence[RawDetection],
    image: Any,  # 原始图像（BGR）
    box_assignment: BoxAssignment | None = None,
    color_vocabulary: tuple[str, ...] = DEFAULT_COLOR_VOCABULARY,
    use_shape_features: bool = False,  # 新增参数
) -> tuple[PlacedItem, ...]:
    """Group detections by (color, shape) and assign to boxes.
    
    Args:
        ...
        use_shape_features: If True and OpenCV available, use contour-based
                            shape classification as fallback when YOLO class_id
                            is uncertain or contradicts color.
    """
    # ... 现有颜色分类逻辑 ...
    
    # 新增：形状特征回退
    if use_shape_features and CV2_AVAILABLE and image is not None:
        try:
            # 提取ROI并分类形状
            shape_from_features = extract_and_classify_roi(
                roi_bgr=image[y1:y2, x1:x2],  # 从detection bbox提取
                color_mask_lower=get_hsv_lower(color_id),
                color_mask_upper=get_hsv_upper(color_id),
            )
            
            # 若YOLO class_id与特征分类不一致，记录警告或使用特征分类
            if shape_from_features and shape_from_features != yolo_shape:
                # 策略：优先YOLO，特征作为置信度修正
                pass  # 可在此添加日志或决策逻辑
        except Exception:
            pass  # 静默失败，不影响主链
    
    # ... 现有分箱逻辑 ...
```

#### 2.4 验收标准

```bash
# 1. 单元测试通过
python -m pytest tests/ -q -p no:cacheprovider
# 预期：62 passed（新功能为可选，不破坏现有逻辑）

# 2. 形状特征模块单独测试（新增）
python -m pytest 视觉/tests/test_shape_features.py -v
# 预期：测试用例覆盖 extract_contour_features / classify_shape_from_features
```

---

### 任务3：（可选）提取重复代码（估时1小时）

#### 3.1 提取安全整数回退

**修改**：`视觉/src/sorting_vision/pipeline.py`

```python
# 在文件顶部（约15行）添加辅助函数
def _safe_int(value: Any, fallback: int) -> int:
    """Return value if it's an int, otherwise fallback."""
    return value if isinstance(value, int) else fallback

# 替换3处使用（约77, 84, 141, 149行）
# 前：task_id=task_id if isinstance(task_id, int) else -1
# 后：task_id=_safe_int(task_id, -1)
```

#### 3.2 验收

```bash
python -m pytest tests/ -q -p no:cacheprovider
# 预期：62 passed（行为不变，只是重构）
```

---

## ✅ 最终验收清单

### 必须通过
- [ ] 62项unittest全部通过
- [ ] 新建`constants.py`文件存在
- [ ] 3个文件（config.py/pipeline.py/single_target.py）成功导入常量
- [ ] 置信度默认值统一为0.50
- [ ] 新建`shape_features.py`文件存在
- [ ] 形状特征函数可正常导入（即使未集成到主链）

### 可选通过
- [ ] 提取`_safe_int`辅助函数
- [ ] 新增形状特征单元测试

---

## 🚫 禁止事项

1. **不得修改冻结协议**：
   - `docs/design/interface-contract.md` 的 ITEM_TASK 12字节格式
   - 坐标范围 `[-1450, 1450]`
   - 箱号 `1..6`

2. **不得修改公共API**：
   - `VisionPipeline.infer_batch()` 签名
   - `VisionPipeline.reacquire()` 签名
   - `BatchResult` / `ReacquireResult` 字段

3. **不得删除现有测试**：
   - 62项测试必须保持（可新增，不可删除）

4. **不得引入新的外部依赖**：
   - OpenCV已存在，可用
   - numpy已存在，可用
   - 不得添加其他第三方库

---

## 📝 交付物

### 代码文件（必须）
1. `视觉/src/sorting_vision/constants.py`（新建）
2. `视觉/src/sorting_vision/shape_features.py`（新建）
3. `视觉/src/sorting_vision/config.py`（修改）
4. `视觉/src/sorting_vision/pipeline.py`（修改）
5. `视觉/src/sorting_vision/single_target.py`（修改）

### 测试结果（必须）
```bash
cd "C:\Users\29845\Desktop\工创赛\视觉"
python -m pytest tests/ -v > test_results.txt 2>&1
```

### 变更说明（必须）
Markdown文件，格式：
```markdown
# 视觉代码优化变更说明

## 改动汇总
- 新建文件：2个
- 修改文件：3个
- 删除文件：0个

## 改动详情
### 1. 新建 constants.py
提取6处魔法数字...

### 2. 新建 shape_features.py
从归档区移植轮廓特征分类器...

### 3. 修改 config.py
- 第17行：0.50 → DEFAULT_CONFIDENCE_THRESHOLD
- ...

## 测试结果
62 passed, 25 skipped, 0 failed

## 遗留问题
- 形状特征分类器的阈值需现场标定
- ...
```

---

## 🆘 常见问题

### Q1：测试失败怎么办？
**A**：
1. 检查导入路径是否正确（相对导入`.constants`）
2. 检查常量名是否拼写错误
3. 运行单个测试定位问题：`pytest tests/test_config.py -v`

### Q2：找不到归档区文件？
**A**：
- 完整路径：`C:\Users\29845\Desktop\工创赛\archive\_B档金贵-20261002\视觉V6-01_当前运行_V6\stage1_color_v6_stable.py`
- 关键代码在约150-200行（`findContours` / `contourArea` / `boundingRect`）

### Q3：OpenCV导入失败？
**A**：
- 使用`try-except`包裹导入（已在`shape_features.py`模板中提供）
- 设置`CV2_AVAILABLE = False`标志
- 形状特征功能降级为不可用（不影响主链）

### Q4：62项测试是哪些？
**A**：
```bash
pytest tests/ --collect-only
# 查看所有测试项名称
```

---

## 📞 验收联系

完成后请提供：
1. `test_results.txt`（pytest完整输出）
2. 变更说明Markdown文件
3. 修改后的5个代码文件（zip打包）

预期耗时：4-6小时（含调试）  
紧急联系：提供错误截图 + pytest输出
