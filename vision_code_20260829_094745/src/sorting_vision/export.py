"""Human-readable diagnostic JSON. This is deliberately not a wire codec."""

from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from typing import Any

from .types import BatchResult, ReacquireResult


def normalize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [normalize_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(item) for key, item in value.items()}
    return value


def to_diagnostic_dict(result: BatchResult | ReacquireResult) -> dict[str, Any]:
    payload = normalize_value(asdict(result))
    payload["motion_ready"] = result.motion_ready
    payload["wire_codec_frozen"] = False
    payload["diagnostic_only"] = True
    if isinstance(result, BatchResult):
        payload["target_count"] = len(result.detections)
        payload["confidence_percent"] = [
            round(detection.confidence * 100.0, 3) for detection in result.detections
        ]
    elif result.detection is not None:
        payload["confidence_percent"] = round(result.detection.confidence * 100.0, 3)
    return payload


def to_diagnostic_json(result: BatchResult | ReacquireResult, *, indent: int = 2) -> str:
    return json.dumps(to_diagnostic_dict(result), ensure_ascii=False, indent=indent, sort_keys=True)
