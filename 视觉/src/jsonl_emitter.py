"""Bridge-compatible JSONL output for the vision side.

The action bridge consumes exactly one JSON object per line:

    {"frame_id": int, "label": str|null, "confidence": 0..1, "ts_ms": int}

Extra fields are rejected by the bridge, so this module never emits bbox or
diagnostic fields. The fake source lets the full chain be exercised on a host
without a camera or model; replace it with the real detector on Raspberry Pi.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from typing import Iterable, Mapping, Optional, TextIO


def detection_line(frame_id: int, label: Optional[str], confidence: float,
                   ts_ms: int) -> str:
    if not isinstance(frame_id, int) or isinstance(frame_id, bool) or frame_id < 0:
        raise ValueError("frame_id must be a non-negative integer")
    if label is not None and (not isinstance(label, str) or not label):
        raise ValueError("label must be a non-empty string or None")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
    ):
        raise ValueError("confidence must be a finite number within [0, 1]")
    if not isinstance(ts_ms, int) or isinstance(ts_ms, bool) or ts_ms < 0:
        raise ValueError("ts_ms must be a non-negative integer")
    payload = {
        "frame_id": frame_id,
        "label": label,
        "confidence": confidence,
        "ts_ms": ts_ms,
    }
    return json.dumps(payload, ensure_ascii=False)


def fake_detection_lines(label: str, confidence: float,
                         frames: int) -> Iterable[str]:
    """Emit a stable detection then an explicit no-target release window."""
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise ValueError("frames must be a positive integer")
    base_ms = int(time.monotonic() * 1000)
    for index in range(frames):
        yield detection_line(index, label, confidence, base_ms + index * 100)
    for index in range(frames):
        yield detection_line(index + frames, None, 0.0,
                             base_ms + (index + frames) * 100)


def stream_lines(stream: Iterable[str], output: TextIO) -> int:
    for line in stream:
        output.write(line + "\n")
        output.flush()
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("fake", "stdin"), default="fake")
    parser.add_argument("--label", default="class_a",
                        help="label used by the fake source")
    parser.add_argument("--confidence", type=float, default=1.0,
                        help="confidence used by the fake source")
    parser.add_argument("--frames", type=int, default=8,
                        help="stable frames and release frames")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.source == "fake":
        if not (0.0 <= args.confidence <= 1.0):
            raise SystemExit("--confidence must be between 0 and 1")
        if args.frames < 1:
            raise SystemExit("--frames must be at least 1")
        lines = fake_detection_lines(args.label, args.confidence, args.frames)
    else:
        lines = (line.rstrip("\r\n") for line in sys.stdin)
    return stream_lines(lines, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
