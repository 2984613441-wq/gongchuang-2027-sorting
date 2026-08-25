from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a trained YOLO11n block detector on the held-out test split.")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("datasets/block_dataset_v1_7class/data.yaml"))
    parser.add_argument("--imgsz", type=int, default=448)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    if not args.weights.is_file():
        raise FileNotFoundError(f"weights not found: {args.weights.resolve()}")
    if not args.data.is_file():
        raise FileNotFoundError(f"dataset YAML not found: {args.data.resolve()}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is unavailable. Run this script from the local Ultralytics project.") from exc

    model = YOLO(str(args.weights))
    metrics = model.val(
        data=str(args.data),
        split="test",
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project="runs/block_detector_eval",
        name="held_out_test",
        plots=True,
        verbose=True,
    )
    print("TEST_METRICS=" + json.dumps(metrics.results_dict, ensure_ascii=False, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
