#!/usr/bin/env python3
"""Interactive HSV color sampling tool for on-site calibration.

Usage:
    python color_calibration.py --camera 0 --output calibration_samples.json

On-site workflow:
    1. Place a physical item of known color under actual lighting
    2. Press SPACE to capture sample (10 samples per color recommended)
    3. Press 'n' to move to next color
    4. Press 'q' to finish and save

The tool outputs a JSON file with HSV statistics per color, which can be
fed into color_boundary_analysis.py to compute optimal thresholds.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


@dataclass
class ColorSample:
    """Single HSV sample for a color."""
    color_name: str
    h_mean: float  # 0-360 degrees
    s_mean: float  # 0-1
    v_mean: float  # 0-1
    roi_pixels: int  # number of pixels sampled


@dataclass
class CalibrationSession:
    """Complete calibration session with all color samples."""
    timestamp: str
    lighting_notes: str
    samples: list[ColorSample]


def sample_roi_hsv(frame: np.ndarray, x: int, y: int, size: int = 50) -> tuple[float, float, float]:
    """Sample average HSV from a square ROI centered at (x, y).

    Args:
        frame: BGR image from camera.
        x, y: Center coordinates of sampling region.
        size: Side length of square ROI in pixels.

    Returns:
        (h_mean, s_mean, v_mean): Average HSV values.
            h_mean in [0, 360] degrees
            s_mean, v_mean in [0, 1]
    """
    h, w = frame.shape[:2]
    x1 = max(0, x - size // 2)
    y1 = max(0, y - size // 2)
    x2 = min(w, x + size // 2)
    y2 = min(h, y + size // 2)

    roi = frame[y1:y2, x1:x2]
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Convert to float and normalize
    h_mean = float(np.mean(hsv_roi[:, :, 0])) * 2  # OpenCV H is 0-179, convert to 0-358
    s_mean = float(np.mean(hsv_roi[:, :, 1])) / 255.0
    v_mean = float(np.mean(hsv_roi[:, :, 2])) / 255.0

    pixels = (x2 - x1) * (y2 - y1)
    return h_mean, s_mean, v_mean, pixels


def run_interactive_sampling(camera_index: int = 0, roi_size: int = 50) -> CalibrationSession:
    """Run interactive color sampling loop.

    Args:
        camera_index: Camera device index.
        roi_size: ROI square size in pixels.

    Returns:
        CalibrationSession with all captured samples.
    """
    if not CV2_AVAILABLE:
        raise RuntimeError("OpenCV (cv2) is required for interactive sampling")

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera {camera_index}")

    samples: list[ColorSample] = []
    current_color = input("Enter color name for first sample (e.g., 'red'): ").strip()
    lighting_notes = input("Lighting notes (e.g., '补光灯开启, 白底'): ").strip()

    print("\n=== Instructions ===")
    print("SPACE: Capture sample at center crosshair")
    print("'n': Move to next color")
    print("'q': Finish and save")
    print("=====================\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Draw crosshair at center
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (0, 255, 0), 2)
        cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (0, 255, 0), 2)

        # Draw ROI box
        half = roi_size // 2
        cv2.rectangle(frame, (cx - half, cy - half), (cx + half, cy + half), (255, 0, 0), 2)

        # Display info
        cv2.putText(frame, f"Color: {current_color} | Samples: {len(samples)}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, "SPACE=Capture | n=Next color | q=Quit",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow('Color Calibration', frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(' '):  # Capture sample
            h_mean, s_mean, v_mean, pixels = sample_roi_hsv(frame, cx, cy, roi_size)
            sample = ColorSample(
                color_name=current_color,
                h_mean=h_mean,
                s_mean=s_mean,
                v_mean=v_mean,
                roi_pixels=pixels
            )
            samples.append(sample)
            print(f"✓ Captured {current_color}: H={h_mean:.1f}° S={s_mean:.3f} V={v_mean:.3f}")

        elif key == ord('n'):  # Next color
            new_color = input("\nEnter next color name (or press Enter to finish): ").strip()
            if not new_color:
                break
            current_color = new_color
            print(f"Switched to: {current_color}")

        elif key == ord('q'):  # Quit
            break

    cap.release()
    cv2.destroyAllWindows()

    from datetime import datetime
    session = CalibrationSession(
        timestamp=datetime.now().isoformat(),
        lighting_notes=lighting_notes,
        samples=samples
    )

    return session


def save_session(session: CalibrationSession, output_path: Path) -> None:
    """Save calibration session to JSON."""
    data = {
        "timestamp": session.timestamp,
        "lighting_notes": session.lighting_notes,
        "samples": [asdict(s) for s in session.samples]
    }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Saved {len(session.samples)} samples to: {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive HSV color calibration tool")
    parser.add_argument("--camera", type=int, default=0, help="Camera device index")
    parser.add_argument("--roi-size", type=int, default=50, help="ROI square size in pixels")
    parser.add_argument("--output", type=Path, default="calibration_samples.json",
                        help="Output JSON file path")

    args = parser.parse_args(argv)

    if not CV2_AVAILABLE:
        print("ERROR: OpenCV (cv2) is required for this tool", file=sys.stderr)
        print("Install: pip install opencv-python", file=sys.stderr)
        return 1

    print("=== Color Calibration Tool ===")
    print(f"Camera: {args.camera}")
    print(f"ROI size: {args.roi_size}px")
    print(f"Output: {args.output}\n")

    try:
        session = run_interactive_sampling(args.camera, args.roi_size)
        save_session(session, args.output)

        # Print summary
        print("\n=== Summary ===")
        colors = {}
        for sample in session.samples:
            colors.setdefault(sample.color_name, []).append(sample)

        for color, color_samples in colors.items():
            print(f"{color}: {len(color_samples)} samples")

        print(f"\nNext step: Run color_boundary_analysis.py on {args.output}")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
