# -*- coding: utf-8 -*-
"""导出 YOLOv5s(u) best.pt → ONNX，供 MaixHub 网页模型转换（yolov5u profile）。

与官方文档对齐：
  - opset=17（不是 13）
  - simplify=True（onnxslim）
  - dynamic=False（静态输入 448×448）
  - dynamo=False（已在 ultralytics/utils/export.py 强制，保留 /model.24/dfl/conv/Conv 节点名）

输出：与 best.pt 同目录的 best.onnx。
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
        simplify=True,   # onnxslim；缺依赖时 ultralytics 会跳过并告警，不影响导出
        opset=17,        # MaixHub 网页转换要求 17
        half=False,      # FP32，量化交给 MaixHub/nncase
    )
    print("EXPORT_DONE:", exported)


if __name__ == "__main__":
    main()
