#!/usr/bin/env python3
"""ToF depth sensor integration test.

Tests the complete depth fusion pipeline with real ToF hardware:
1. ToF sensor connection and reading
2. YOLO bbox → ToF depth → shape disambiguation
3. End-to-end validation with physical objects

Hardware requirements:
- ToF sensor (VL53L1X, TF-Luna, or PMOD_TOF100)
- Connected via I2C or UART to Raspberry Pi
- Physical test objects (cylinder, sphere, cube, pyramid, etc.)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sorting_vision.depth_fusion import (
    DepthReading,
    depth_disambiguate,
    requires_depth_disambiguation,
)


class ToFSensor:
    """Abstract ToF sensor interface."""

    def read_height_mm(self) -> tuple[float, float]:
        """Read object height from ToF sensor.

        Returns:
            (height_mm, confidence): Height in mm and confidence [0, 1].
        """
        raise NotImplementedError

    def close(self) -> None:
        """Close sensor connection."""
        pass


class VL53L1XSensor(ToFSensor):
    """VL53L1X I2C ToF sensor."""

    def __init__(self, i2c_bus: int = 1, i2c_addr: int = 0x29):
        try:
            import board
            import adafruit_vl53l1x
            i2c = board.I2C()
            self.sensor = adafruit_vl53l1x.VL53L1X(i2c)
            self.sensor.start_ranging()
            print(f"✓ VL53L1X initialized on I2C bus {i2c_bus}")
        except Exception as e:
            raise RuntimeError(f"VL53L1X init failed: {e}")

    def read_height_mm(self) -> tuple[float, float]:
        if self.sensor.data_ready:
            distance = self.sensor.distance
            if distance is not None and 30 <= distance <= 300:
                # VL53L1X returns distance in cm, convert to mm
                height_mm = distance * 10.0
                confidence = 0.95  # VL53L1X is high-confidence
                return height_mm, confidence
        return 0.0, 0.0

    def close(self) -> None:
        self.sensor.stop_ranging()


class TFLunaSensor(ToFSensor):
    """TF-Luna UART ToF sensor."""

    def __init__(self, port: str = "/dev/ttyAMA0", baudrate: int = 115200):
        try:
            import serial
            self.ser = serial.Serial(port, baudrate, timeout=0.1)
            print(f"✓ TF-Luna initialized on {port}")
        except Exception as e:
            raise RuntimeError(f"TF-Luna init failed: {e}")

    def read_height_mm(self) -> tuple[float, float]:
        # TF-Luna protocol: 9-byte frame
        # 0x59 0x59 Dist_L Dist_H Strength_L Strength_H Temp_L Temp_H Checksum
        if self.ser.in_waiting >= 9:
            data = self.ser.read(9)
            if data[0] == 0x59 and data[1] == 0x59:
                distance_cm = data[2] + (data[3] << 8)
                strength = data[4] + (data[5] << 8)

                if 20 <= distance_cm <= 3000 and strength > 100:
                    height_mm = distance_cm * 10.0
                    confidence = min(strength / 1000.0, 1.0)
                    return height_mm, confidence
        return 0.0, 0.0

    def close(self) -> None:
        self.ser.close()


class MockToFSensor(ToFSensor):
    """Mock ToF sensor for testing without hardware."""

    def __init__(self):
        self.height_mm = 50.0
        print("⚠️ Using MOCK ToF sensor (no real hardware)")

    def read_height_mm(self) -> tuple[float, float]:
        return self.height_mm, 0.95

    def set_height(self, height_mm: float) -> None:
        """Manually set mock height for testing."""
        self.height_mm = height_mm


def create_tof_sensor(sensor_type: str) -> ToFSensor:
    """Factory function to create ToF sensor instance."""
    if sensor_type == "vl53l1x":
        return VL53L1XSensor()
    elif sensor_type == "tfluna":
        return TFLunaSensor()
    elif sensor_type == "mock":
        return MockToFSensor()
    else:
        raise ValueError(f"Unknown sensor type: {sensor_type}")


def test_tof_reading(sensor: ToFSensor, num_samples: int = 10) -> None:
    """Test basic ToF sensor readings."""
    print("\n=== ToF Sensor Reading Test ===")
    print(f"Taking {num_samples} samples...\n")

    heights = []
    confidences = []

    for i in range(num_samples):
        height_mm, confidence = sensor.read_height_mm()
        heights.append(height_mm)
        confidences.append(confidence)
        print(f"Sample {i+1:2d}: {height_mm:6.1f}mm (conf={confidence:.2f})")
        time.sleep(0.1)

    if heights:
        avg_height = sum(heights) / len(heights)
        std_height = (sum((h - avg_height)**2 for h in heights) / len(heights)) ** 0.5
        avg_conf = sum(confidences) / len(confidences)

        print(f"\nStatistics:")
        print(f"  Height: {avg_height:.1f} ± {std_height:.1f} mm")
        print(f"  Confidence: {avg_conf:.2f}")

        if std_height > 5.0:
            print("⚠️ High standard deviation - check sensor stability")
        if avg_conf < 0.7:
            print("⚠️ Low confidence - check sensor placement/lighting")


def test_depth_disambiguation(sensor: ToFSensor) -> None:
    """Test depth-based shape disambiguation."""
    print("\n=== Depth Disambiguation Test ===")
    print("Place test objects and press Enter to measure...")

    test_cases = [
        ("cylinder", "Tall cylinder (H>1.2*W)", "cylinder"),
        ("cylinder", "Sphere (H<0.8*W)", "sphere"),
        ("triangular_prism", "Triangular prism (H>0.8*W)", "triangular_prism"),
        ("triangular_prism", "Tetrahedron (H<0.6*W)", "regular_tetrahedron"),
        ("cube", "Cube (H≈W)", "cube"),
        ("cube", "Square pyramid (H<0.6*W)", "square_pyramid"),
    ]

    results = []

    for yolo_shape, description, expected in test_cases:
        input(f"\n{description} → ")

        # Take 3 readings and average
        heights = []
        for _ in range(3):
            h, c = sensor.read_height_mm()
            if c > 0.7:
                heights.append(h)
            time.sleep(0.05)

        if not heights:
            print("  ❌ No valid reading (confidence too low)")
            results.append((description, "ERROR", expected, False))
            continue

        avg_height = sum(heights) / len(heights)

        # Assume bbox_width=50px, px_to_mm=1.0 for testing
        bbox_width_px = 50.0
        px_to_mm = 1.0

        depth_reading = DepthReading(height_mm=avg_height, confidence=0.95)
        result = depth_disambiguate(yolo_shape, bbox_width_px, depth_reading, px_to_mm)

        correct = result == expected
        status = "✓" if correct else "✗"

        print(f"  Height: {avg_height:.1f}mm")
        print(f"  YOLO: {yolo_shape} → Depth: {result}")
        print(f"  Expected: {expected} → {status}")

        results.append((description, result, expected, correct))

    # Summary
    print("\n=== Test Summary ===")
    correct_count = sum(1 for _, _, _, ok in results if ok)
    total = len(results)

    for desc, result, expected, ok in results:
        status = "✓" if ok else "✗"
        print(f"{status} {desc}: {result} (expected {expected})")

    print(f"\nAccuracy: {correct_count}/{total} ({100*correct_count/total:.0f}%)")

    if correct_count == total:
        print("🎉 All tests passed!")
    elif correct_count >= total * 0.8:
        print("⚠️ Most tests passed, but review failures")
    else:
        print("❌ Many tests failed - check thresholds or sensor calibration")


def interactive_mode(sensor: ToFSensor) -> None:
    """Interactive testing mode with live readings."""
    print("\n=== Interactive Mode ===")
    print("Commands:")
    print("  r - Take reading")
    print("  t - Test disambiguation (cylinder/cube/prism)")
    print("  q - Quit")

    while True:
        cmd = input("\n> ").strip().lower()

        if cmd == 'q':
            break
        elif cmd == 'r':
            height_mm, confidence = sensor.read_height_mm()
            print(f"Height: {height_mm:.1f}mm (confidence: {confidence:.2f})")
        elif cmd == 't':
            yolo_shape = input("YOLO shape (cylinder/cube/triangular_prism): ").strip()
            bbox_width = float(input("Bbox width (px): ") or "50")

            height_mm, confidence = sensor.read_height_mm()
            if confidence < 0.7:
                print("⚠️ Low confidence reading")

            depth_reading = DepthReading(height_mm=height_mm, confidence=confidence)
            result = depth_disambiguate(yolo_shape, bbox_width, depth_reading, px_to_mm=1.0)

            print(f"Result: {yolo_shape} → {result}")
            print(f"Height/Width ratio: {height_mm/bbox_width:.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ToF depth sensor integration test")
    parser.add_argument("--sensor", choices=["vl53l1x", "tfluna", "mock"],
                        default="mock", help="ToF sensor type")
    parser.add_argument("--mode", choices=["reading", "disambiguation", "interactive"],
                        default="reading", help="Test mode")
    parser.add_argument("--samples", type=int, default=10, help="Number of samples for reading test")

    args = parser.parse_args(argv)

    print("=== ToF Depth Sensor Integration Test ===\n")

    try:
        sensor = create_tof_sensor(args.sensor)

        if args.mode == "reading":
            test_tof_reading(sensor, args.samples)
        elif args.mode == "disambiguation":
            test_depth_disambiguation(sensor)
        elif args.mode == "interactive":
            interactive_mode(sensor)

        sensor.close()
        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
