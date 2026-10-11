# -*- coding: utf-8 -*-
"""导出 YOLOv5s best.pt → ONNX，供 MaixHub 模型转换页使用。

与 train_yolo5s.py 一致：ultralytics 用本地仓库（非 pip 安装）。
输出：与 best.pt 同目录的 best.onnx（opset 13 / 448×448 / 静态 / FP32）。
"""
import sys

sys.path.insert(0, r"D:/AAAdesktop1/shijue/ultralytics-8.3.163")

from ultralytics import YOLO

WEIGHTS = r"D:/AAAdesktop1/shijue/runs/yolo5s_geom7c/weights/best.pt"


def main() -> None:
    model = YOLO(WEIGHTS)
    exported = model.export(
        format="onnx",
        imgsz=448,
        dynamic=False,
        simplify=True,   # 若环境缺 onnxsim，ultralytics 会跳过并告警，不影响导出
        opset=13,        # MaixHub 转换器更稳的 opset 目标
        half=False,      # FP32，量化交给 MaixHub/nncase
    )
    print("EXPORT_DONE:", exported)


if __name__ == "__main__":
    main()
