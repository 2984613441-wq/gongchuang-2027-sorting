# ToF集成实测指南

**文档版本**：v1.0  
**日期**：2026-10-11  
**状态**：硬件到货，准备实测  
**预计耗时**：2-3小时（含标定）

---

## 1. 硬件准备检查清单

### 1.1 ToF模块信息

- [ ] ToF型号：____________（VL53L1X / TF-Luna / PMOD_TOF100）
- [ ] 接口类型：□ I2C  □ UART
- [ ] 供电电压：____________V
- [ ] 测量范围：____________mm

### 1.2 连接检查

**I2C连接（VL53L1X）**：
```
VL53L1X → 树莓派
VCC     → 3.3V (Pin 1)
GND     → GND (Pin 6)
SDA     → GPIO2/SDA (Pin 3)
SCL     → GPIO3/SCL (Pin 5)
```

**UART连接（TF-Luna）**：
```
TF-Luna → 树莓派
VCC     → 5V (Pin 2)
GND     → GND (Pin 6)
TX      → RXD (Pin 10, GPIO15)
RX      → TXD (Pin 8, GPIO14)
```

- [ ] 连接已完成
- [ ] 电源指示灯亮
- [ ] I2C地址检测通过（`i2cdetect -y 1`）或UART设备存在（`ls /dev/ttyAMA0`）

---

## 2. 软件环境准备

### 2.1 安装依赖（树莓派）

**VL53L1X (I2C)**：
```bash
sudo apt-get update
sudo apt-get install -y python3-pip
pip3 install adafruit-circuitpython-vl53l1x
```

**TF-Luna (UART)**：
```bash
pip3 install pyserial
```

### 2.2 启用I2C/UART

```bash
# 启用I2C
sudo raspi-config
# Interface Options → I2C → Yes

# 启用UART（禁用串口控制台）
sudo raspi-config
# Interface Options → Serial Port → 
#   "Would you like a login shell accessible over serial?" → No
#   "Would you like the serial port hardware enabled?" → Yes
```

**重启生效**：
```bash
sudo reboot
```

### 2.3 验证连接

**I2C**：
```bash
i2cdetect -y 1
# 应显示 0x29 地址（VL53L1X默认）
```

**UART**：
```bash
ls -l /dev/ttyAMA0
# 应存在设备文件
```

---

## 3. 测试步骤

### 3.1 基础读数测试（10分钟）

```bash
cd 视觉/tests
python3 test_tof_integration.py --sensor vl53l1x --mode reading --samples 20
# 或
python3 test_tof_integration.py --sensor tfluna --mode reading --samples 20
```

**检查输出**：
- [ ] 读数稳定（标准差<5mm）
- [ ] 置信度>0.8
- [ ] 响应时间<100ms

**问题排查**：
| 现象 | 可能原因 | 解决 |
|------|---------|------|
| 全部0.0mm | 传感器未初始化 | 检查I2C/UART连接 |
| 高标准差(>10mm) | 环境干扰 | 遮挡强光、固定支架 |
| 低置信度(<0.5) | 超出量程 | 调整物体距离 |

---

### 3.2 消歧测试（30分钟）

**准备6个测试物体**：
1. 高圆柱（高>1.2×直径）
2. 球（直径≈高度）
3. 三棱柱立放（高>0.8×底边）
4. 正四面体（高≈0.58×底边）
5. 正方体（高=边长）
6. 四棱锥底朝下（高<0.6×底边）

**执行测试**：
```bash
python3 test_tof_integration.py --sensor vl53l1x --mode disambiguation
```

**按提示放置物体并按Enter**

**记录结果**：
| 物体 | 测得高度(mm) | YOLO输入 | 输出结果 | 预期结果 | 正确 |
|------|-------------|----------|---------|---------|------|
| 高圆柱 |  | cylinder |  | cylinder | □ |
| 球 |  | cylinder |  | sphere | □ |
| 三棱柱 |  | triangular_prism |  | triangular_prism | □ |
| 正四面体 |  | triangular_prism |  | regular_tetrahedron | □ |
| 正方体 |  | cube |  | cube | □ |
| 四棱锥 |  | cube |  | square_pyramid | □ |

**正确率目标**：≥5/6 (83%)

---

### 3.3 阈值标定（60分钟）

**如果消歧测试正确率<83%，需重新标定阈值**

#### 步骤1：收集标准件数据

**准备标准几何体**（实物或3D打印）：
- 圆柱：直径50mm，高度70mm
- 球：直径50mm
- 三棱柱：底边50mm，高50mm
- 正四面体：底边50mm
- 正方体：边长50mm
- 四棱锥：底边50mm，高30mm

**测量每个物体10次**：
```bash
python3 test_tof_integration.py --sensor vl53l1x --mode interactive
```

在交互模式中：
```
> r   # 读取高度
Height: 68.5mm (confidence: 0.95)
> r   # 再读9次，记录所有值
...
```

**记录到Excel**：
| 物体 | 真实高度 | 真实宽度 | 测量1 | 测量2 | ... | 测量10 | 均值 | 标准差 | 高宽比 |
|------|---------|---------|-------|-------|-----|--------|------|--------|--------|
| 圆柱 | 70mm | 50mm |  |  |  |  |  |  | 1.40 |
| 球 | 50mm | 50mm |  |  |  |  |  |  | 1.00 |
| ... |  |  |  |  |  |  |  |  |  |

#### 步骤2：计算新阈值

**公式**：
```
CYLINDER_RATIO = (圆柱高宽比 + 球高宽比) / 2 + 1个标准差
SPHERE_RATIO = (圆柱高宽比 + 球高宽比) / 2 - 1个标准差
```

**示例**：
- 圆柱高宽比：1.40 ± 0.05
- 球高宽比：1.00 ± 0.03
- 边界 = (1.40 + 1.00)/2 = 1.20
- `CYLINDER_HEIGHT_RATIO = 1.20 + 0.05 = 1.25`
- `SPHERE_HEIGHT_RATIO = 1.20 - 0.05 = 1.15`

#### 步骤3：更新代码

```bash
cd 视觉/src/sorting_vision
nano depth_fusion.py
```

修改常量：
```python
CYLINDER_HEIGHT_RATIO = 1.25  # 更新为标定值
SPHERE_HEIGHT_RATIO = 1.15    # 更新为标定值
TRIANGULAR_PRISM_RATIO = 0.XX  # 同样方法标定
TETRAHEDRON_RATIO = 0.XX
CUBE_RATIO = 0.XX
PYRAMID_RATIO = 0.XX
```

#### 步骤4：重新测试

```bash
cd 视觉/tests
python3 test_tof_integration.py --sensor vl53l1x --mode disambiguation
```

**验收标准**：正确率≥95% (≥6/6或5/6)

---

## 4. px_to_mm标定（30分钟）

**像素到毫米转换系数标定**

### 步骤1：拍摄标定板

- 打印A4纸棋盘格标定板（10×7，格子30mm）
- 放在转盘位置
- 拍摄一张图像

### 步骤2：计算转换系数

```python
import cv2
import numpy as np

# 读取标定图像
img = cv2.imread("calibration.jpg")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# 检测棋盘角点
ret, corners = cv2.findChessboardCorners(gray, (9, 6), None)

if ret:
    # 计算相邻角点距离（像素）
    distances_px = []
    for i in range(len(corners) - 1):
        dist = np.linalg.norm(corners[i] - corners[i+1])
        distances_px.append(dist)
    
    avg_dist_px = np.mean(distances_px)
    real_dist_mm = 30.0  # 实际格子尺寸
    
    px_to_mm = real_dist_mm / avg_dist_px
    print(f"px_to_mm = {px_to_mm:.4f}")
```

### 步骤3：验证

```python
# 放置已知尺寸物体
bbox_width_px = 120  # 从YOLO检测
real_width_mm = 50   # 卡尺测量

calculated_width = bbox_width_px * px_to_mm
error = abs(calculated_width - real_width_mm)
print(f"计算宽度: {calculated_width:.1f}mm")
print(f"误差: {error:.1f}mm ({100*error/real_width_mm:.1f}%)")
```

**目标**：误差<5%

---

## 5. 集成到主链（30分钟）

### 5.1 修改pipeline.py

```python
# 视觉/src/sorting_vision/pipeline.py

from .depth_fusion import DepthReading, depth_disambiguate, requires_depth_disambiguation

class VisionPipeline:
    def __init__(self, ..., tof_sensor=None, px_to_mm=1.0):
        # ...
        self.tof_sensor = tof_sensor
        self.px_to_mm = px_to_mm
    
    def infer_batch(self, images, ...):
        # ... YOLO推理 ...
        
        # ToF深度融合
        if self.tof_sensor:
            for detection in detections:
                if requires_depth_disambiguation(detection.class_name):
                    # 读取ToF深度
                    height_mm, confidence = self.tof_sensor.read_height_mm()
                    depth_reading = DepthReading(height_mm, confidence)
                    
                    # 消歧
                    refined_shape = depth_disambiguate(
                        yolo_shape=detection.class_name,
                        bbox_width_px=detection.bbox.width,
                        depth_reading=depth_reading,
                        px_to_mm=self.px_to_mm
                    )
                    
                    detection.class_name = refined_shape
        
        return detections
```

### 5.2 端到端测试

```bash
cd 视觉
python3 -c "
from sorting_vision.pipeline import VisionPipeline
from tests.test_tof_integration import create_tof_sensor

tof = create_tof_sensor('vl53l1x')
pipeline = VisionPipeline(..., tof_sensor=tof, px_to_mm=0.25)

# 放置圆柱
result = pipeline.infer_batch([image])
print(result[0].class_name)  # 应输出 'cylinder' 或 'sphere'
"
```

---

## 6. 性能评估

### 6.1 延迟测试

```python
import time

start = time.time()
height_mm, conf = tof_sensor.read_height_mm()
tof_latency = (time.time() - start) * 1000

print(f"ToF延迟: {tof_latency:.1f}ms")
```

**目标**：<100ms

### 6.2 整体延迟

```python
# 无ToF
start = time.time()
result_no_tof = pipeline_no_tof.infer_batch([image])
time_no_tof = time.time() - start

# 有ToF
start = time.time()
result_with_tof = pipeline_with_tof.infer_batch([image])
time_with_tof = time.time() - start

overhead = time_with_tof - time_no_tof
print(f"ToF开销: {overhead*1000:.0f}ms")
```

**目标**：<2秒增量

---

## 7. 验收清单

- [ ] ToF读数稳定（标准差<5mm）
- [ ] 消歧测试正确率≥95%
- [ ] px_to_mm标定误差<5%
- [ ] 集成到pipeline.py成功
- [ ] ToF延迟<100ms
- [ ] 整体延迟增量<2秒
- [ ] 阈值已根据实测标定
- [ ] 代码已提交Git

---

## 8. 问题排查

| 问题 | 诊断 | 解决 |
|------|------|------|
| ToF无读数 | `i2cdetect -y 1` 看不到0x29 | 检查接线、重新插拔 |
| 读数跳动大 | 标准差>10mm | 遮挡强光、加固支架 |
| 消歧错误率高 | 某组歧义全错 | 重新标定该组阈值 |
| px_to_mm误差大 | 误差>10% | 重拍标定板、检查畸变 |
| 延迟过高 | >200ms | 降低ToF采样率、异步读取 |

---

## 9. 降级预案

**如果ToF集成失败（时间不足/硬件故障）**：

1. **关闭深度融合**：
```python
pipeline = VisionPipeline(..., tof_sensor=None)  # 禁用ToF
```

2. **备选方案**：
- 问裁判确认省赛物料范围（是否包含歧义组）
- 使用形状特征降级预案（`shape_features.py`）
- 纯YOLO + 人工分拣歧义件

3. **记录决策**：
```
原因：[ToF硬件故障 / 标定失败 / 时间不足]
影响：三组歧义无法自动区分，预计失分____分
```

---

## 10. 完成标志

**ToF集成实测报告**（填写`docs/ToF集成实测报告-YYYYMMDD.md`）：
- [ ] 硬件型号与连接
- [ ] 基础读数测试结果（标准差、置信度）
- [ ] 消歧测试6/6结果表
- [ ] 阈值标定数据（如有）
- [ ] px_to_mm标定值
- [ ] 性能指标（延迟）
- [ ] 遇到的问题与解决
- [ ] 签字确认

---

**预计总时间**：2-3小时  
**建议时段**：下午连续时间块（避免中断）  
**人员**：2人（1人操作、1人记录）
