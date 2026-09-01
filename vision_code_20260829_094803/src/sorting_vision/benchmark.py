"""Comparable deployment benchmark records for future Pi/MaixCAM decisions."""

from __future__ import annotations

import json
import math
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .pipeline import VisionPipeline
from .types import ImageLike, ResultStatus


@dataclass(frozen=True)
class BenchmarkRecord:
    target: str
    model_format: str
    model_version: str
    validation_set_id: str
    sample_count: int
    successful_samples: int
    mean_latency_ms: float
    p95_latency_ms: float
    fps: float
    peak_memory_mb: float
    model_size_mb: float | None
    accuracy_metric_name: str | None
    accuracy_metric_value: float | None
    peak_temperature_c: float | None
    stability_duration_s: float
    notes: str = ""
    schema_version: str = "vision-deployment-benchmark-v0.1"

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent, sort_keys=True)


AccuracyEvaluator = Callable[[tuple[object, ...]], tuple[str, float]]
TemperatureReader = Callable[[], float]


def benchmark_pipeline(
    pipeline: VisionPipeline,
    samples: Iterable[ImageLike],
    *,
    target: str,
    model_format: str,
    model_version: str,
    validation_set_id: str,
    model_path: str | Path | None = None,
    accuracy_evaluator: AccuracyEvaluator | None = None,
    temperature_reader: TemperatureReader | None = None,
    notes: str = "",
) -> BenchmarkRecord:
    sample_list = tuple(samples)
    if not sample_list:
        raise ValueError("benchmark requires at least one validation sample")
    latencies: list[float] = []
    results: list[object] = []
    temperatures: list[float] = []
    tracemalloc.start()
    benchmark_start = time.perf_counter()
    try:
        for task_id, sample in enumerate(sample_list, start=1):
            started = time.perf_counter()
            result = pipeline.infer_batch(task_id, sample)
            latencies.append((time.perf_counter() - started) * 1000.0)
            results.append(result)
            if temperature_reader is not None:
                temperatures.append(float(temperature_reader()))
        duration = time.perf_counter() - benchmark_start
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    successful = sum(result.status is ResultStatus.OK for result in results)
    accuracy_name: str | None = None
    accuracy_value: float | None = None
    if accuracy_evaluator is not None:
        accuracy_name, accuracy_value = accuracy_evaluator(tuple(results))
    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
    resolved_model = Path(model_path).expanduser().resolve() if model_path else None
    model_size_mb = (
        resolved_model.stat().st_size / (1024.0 * 1024.0)
        if resolved_model is not None and resolved_model.is_file()
        else None
    )
    mean_latency = statistics.fmean(latencies)
    return BenchmarkRecord(
        target=target,
        model_format=model_format,
        model_version=model_version,
        validation_set_id=validation_set_id,
        sample_count=len(sample_list),
        successful_samples=successful,
        mean_latency_ms=mean_latency,
        p95_latency_ms=sorted_latencies[p95_index],
        fps=1000.0 / mean_latency if mean_latency > 0 else 0.0,
        peak_memory_mb=peak_bytes / (1024.0 * 1024.0),
        model_size_mb=model_size_mb,
        accuracy_metric_name=accuracy_name,
        accuracy_metric_value=accuracy_value,
        peak_temperature_c=max(temperatures) if temperatures else None,
        stability_duration_s=duration,
        notes=notes,
    )
