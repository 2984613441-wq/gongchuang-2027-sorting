from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Train YOLO11n for green/blue block detection.")
    parser.add_argument("--data", type=Path, default=Path("datasets/block_dataset_v1/data.yaml"))
    parser.add_argument("--model", type=Path, default=Path("yolo11n.pt"))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--project", type=Path, default=Path("runs/block_detector"))
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    if args.epochs <= 0 or args.imgsz <= 0 or args.batch <= 0 or args.workers < 0:
        raise ValueError("epochs, imgsz and batch must be positive; workers must be non-negative")
    if not args.data.is_file():
        raise FileNotFoundError(f"dataset YAML not found: {args.data.resolve()}")
    if not args.model.is_file():
        raise FileNotFoundError(f"model weights not found: {args.model.resolve()}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Ultralytics is unavailable. Run this script from the local Ultralytics project.") from exc

    run_name = args.name or f"block_yolo11n_e{args.epochs}"
    model = YOLO(str(args.model))
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(args.project),
        name=run_name,
        seed=42,
        deterministic=True,
        cache=False,
        pretrained=True,
        amp=True,
        plots=True,
        val=True,
        save=True,
        verbose=True,
    )
    save_dir = Path(model.trainer.save_dir).resolve()
    best_path = save_dir / "weights" / "best.pt"
    last_path = save_dir / "weights" / "last.pt"
    summary = {
        "run_dir": str(save_dir),
        "best_pt": str(best_path),
        "best_exists": best_path.is_file(),
        "last_pt": str(last_path),
        "last_exists": last_path.is_file(),
    }
    print("TRAINING_OUTPUT=" + json.dumps(summary, ensure_ascii=False))
    if not best_path.is_file():
        raise RuntimeError(f"training finished but best.pt was not found: {best_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
