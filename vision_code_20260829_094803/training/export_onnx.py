from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a trained YOLO weight to static ONNX for MaixCAM conversion."
    )
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=448)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--simplify", action="store_true", default=True)
    parser.add_argument("--no-simplify", dest="simplify", action="store_false")
    parser.add_argument("--dynamic", action="store_true", default=False)
    args = parser.parse_args()

    if not args.weights.is_file():
        raise FileNotFoundError(f"weights not found: {args.weights.resolve()}")
    if args.imgsz < 32 or args.imgsz % 32 != 0:
        raise ValueError("imgsz must be a multiple of 32 and at least 32")
    if args.opset < 11:
        raise ValueError("opset must be 11 or newer")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is unavailable. Run this script from the local Ultralytics project."
        ) from exc

    model = YOLO(str(args.weights))
    exported = model.export(
        format="onnx",
        imgsz=args.imgsz,
        dynamic=args.dynamic,
        simplify=args.simplify,
        opset=args.opset,
        half=False,
    )
    output_path = Path(str(exported)).resolve()
    print(f"ONNX_OUTPUT={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
