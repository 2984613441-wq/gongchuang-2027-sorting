"""Motion parameters configuration for scheduler.

These parameters MUST be calibrated with actual hardware testing.
DO NOT use default values in competition without calibration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MotionConfig:
    """Motion parameters for time estimation.

    All parameters should be calibrated from real hardware measurements.
    """

    # Linear motion speed in XY plane (mm/s)
    # Calibration method: Measure 100mm movement × 10 times, take average
    # Current value: CONSERVATIVE ESTIMATE - NEEDS CALIBRATION
    motion_speed_mm_per_s: float = 50.0

    # Complete pick action time including Z-axis movement (seconds)
    # Calibration method: Measure full pick cycle × 10 times, take average
    # Must include: Z-down + grip + Z-up + verification
    # Current value: ESTIMATE WITHOUT Z-AXIS - NEEDS CALIBRATION
    pick_action_time_s: float = 2.0

    # Z-axis movement time estimate (seconds)
    # Calibration method: Measure Z-down + Z-up × 10 times, take average
    # Current value: PLACEHOLDER - NEEDS CALIBRATION
    z_axis_time_s: float = 0.5

    def __post_init__(self) -> None:
        """Validate parameters are positive."""
        if self.motion_speed_mm_per_s <= 0:
            raise ValueError("motion_speed_mm_per_s must be positive")
        if self.pick_action_time_s <= 0:
            raise ValueError("pick_action_time_s must be positive")
        if self.z_axis_time_s < 0:
            raise ValueError("z_axis_time_s must be non-negative")

    @property
    def total_pick_time_s(self) -> float:
        """Total time for one complete pick including Z-axis."""
        return self.pick_action_time_s + self.z_axis_time_s


# Default configuration (MUST BE CALIBRATED)
DEFAULT_MOTION_CONFIG = MotionConfig()


def load_motion_config(filepath: str | None = None) -> MotionConfig:
    """Load motion config from file or return default.

    Args:
        filepath: Optional path to JSON config file

    Returns:
        MotionConfig instance
    """
    if filepath is None:
        return DEFAULT_MOTION_CONFIG

    import json
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        return DEFAULT_MOTION_CONFIG

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 文件里的 _note / _calibration_* 是元数据键，不是 dataclass 字段；
    # 直接 MotionConfig(**data) 会抛
    #   TypeError: MotionConfig.__init__() got an unexpected keyword argument '_note'
    # （台账 E-14）。只过滤 '_' 前缀：真正写错的参数名（如 motion_speed_mm_s）
    # 仍然会响亮地报错，而不是静默退回未标定的默认值。
    known = {k: v for k, v in data.items() if not k.startswith('_')}
    return MotionConfig(**known)


def save_motion_config(config: MotionConfig, filepath: str) -> None:
    """Save motion config to JSON file.

    Args:
        config: MotionConfig to save
        filepath: Path to save JSON file
    """
    import json
    from pathlib import Path

    data = {
        'motion_speed_mm_per_s': config.motion_speed_mm_per_s,
        'pick_action_time_s': config.pick_action_time_s,
        'z_axis_time_s': config.z_axis_time_s,
    }

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


__all__ = [
    'MotionConfig',
    'DEFAULT_MOTION_CONFIG',
    'load_motion_config',
    'save_motion_config',
]
