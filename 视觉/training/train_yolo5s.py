# -*- coding: utf-8 -*-
"""训练 YOLOv5s 检测 7 类三维几何体（448x448）"""
import os
import sys

# ultralytics 是本地仓库（非 pip 安装），手动加进 sys.path
sys.path.insert(0, r"D:/AAAdesktop1/shijue/ultralytics-8.3.163")

from ultralytics import YOLO


def main():
    data_yaml = r"D:/AAAdesktop1/shijue/yolo_dataset/data.yaml"
    project = r"D:/AAAdesktop1/shijue/runs"
    name = "yolo5s_geom7c"

    model = YOLO("yolov5s.pt")  # 从 COCO 预训练权重微调

    results = model.train(
        data=data_yaml,
        imgsz=448,
        epochs=100,
        batch=16,
        device=0,
        project=project,
        name=name,
        exist_ok=True,
        patience=30,          # 30 epoch 无提升则提前停止
        workers=4,
        seed=42,
        verbose=True,
    )

    best = os.path.join(project, name, "weights", "best.pt")
    print("=== 训练完成 ===")
    print("best.pt:", best)
    print("metrics:", results.metrics if hasattr(results, "metrics") else "n/a")


if __name__ == "__main__":
    main()
