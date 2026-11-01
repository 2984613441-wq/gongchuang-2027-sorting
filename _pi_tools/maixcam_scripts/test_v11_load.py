#!/usr/bin/env python3
"""在 MaixCAM 上验证 v11 模型能正常加载（不打开摄像头，最省内存）。"""
from maix import nn, err

MODEL = "/root/my_models/yolo11n_6c_v11_448_cv181x.mud"

print("=" * 50)
print("  v11 模型加载测试")
print("=" * 50)
print("  模型: %s" % MODEL)

try:
    m = nn.YOLO11(model=MODEL, dual_buff=False)
except Exception as e:
    print("  ❌ 加载失败: %s" % e)
    raise SystemExit(1)

print("  ✅ 加载成功")
try:
    print("  输入尺寸: %s" % str(m.input_width()) + "x" + str(m.input_height()))
except Exception:
    pass
try:
    labels = m.labels
    print("  标签数: %d" % len(labels))
    print("  标签: %s" % labels)
except Exception as e:
    print("  标签读取失败: %s" % e)

print("=" * 50)
print("  ✅ v11 模型可用")
