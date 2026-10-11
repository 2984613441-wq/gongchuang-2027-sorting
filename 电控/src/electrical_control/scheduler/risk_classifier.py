"""Risk-based object classification for intelligent pick sequencing.

This module classifies detected objects into risk levels (SAFE/MEDIUM/RISKY)
based on vision confidence, historical success rates, and estimated pick time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple

from .motion_config import MotionConfig, DEFAULT_MOTION_CONFIG


class RiskLevel(Enum):
    """Risk classification for detected objects."""

    SAFE = "safe"       # confidence>0.85 & success_rate>0.8
    MEDIUM = "medium"   # confidence>0.7
    RISKY = "risky"     # other cases


@dataclass(frozen=True)
class ObjectRisk:
    """Risk assessment for a single detected object."""

    object_id: int
    class_id: int
    confidence: float
    position: Tuple[int, int]  # (x, y) in 0.1mm units
    estimated_time_s: float
    historical_success_rate: float
    risk_level: RiskLevel
    failure_count: int = 0


class RiskClassifier:
    """Bayesian risk classifier with adaptive success rate tracking."""

    # Initial priors for each class (conservative estimates)
    _DEFAULT_SUCCESS_RATE = 0.7

    # Risk thresholds
    _SAFE_CONFIDENCE_THRESHOLD = 0.85
    _SAFE_SUCCESS_RATE_THRESHOLD = 0.8
    _MEDIUM_CONFIDENCE_THRESHOLD = 0.7

    # Bayesian update parameters
    _SUCCESS_UPDATE_WEIGHT = 0.1   # Conservative boost on success
    _FAILURE_UPDATE_WEIGHT = 0.3   # Stronger penalty on failure

    def __init__(
        self,
        current_position: Tuple[int, int] = (0, 0),
        motion_config: MotionConfig | None = None
    ) -> None:
        """Initialize classifier with optional current position and motion config.

        Args:
            current_position: Current (x, y) position in 0.1mm units
            motion_config: Motion parameters config (uses default if None)
        """
        self.current_position = current_position
        self.motion_config = motion_config or DEFAULT_MOTION_CONFIG
        # Historical success rates: {class_id: success_rate}
        self.class_success_rates: Dict[int, float] = {}

    def classify(self, obj: dict) -> ObjectRisk:
        """Classify a single object and compute its risk profile.

        Args:
            obj: Detection dict with keys: id, class_id, confidence, x, y

        Returns:
            ObjectRisk with full risk assessment
        """
        object_id = obj['id']
        class_id = obj['class_id']
        confidence = obj['confidence']
        position = (obj['x'], obj['y'])

        # Estimate pick time: distance + action
        estimated_time = self._estimate_pick_time(position)

        # Get historical success rate (prior if unknown)
        success_rate = self.class_success_rates.get(
            class_id,
            self._DEFAULT_SUCCESS_RATE
        )

        # Classify risk level
        risk_level = self._classify_risk(confidence, success_rate)

        return ObjectRisk(
            object_id=object_id,
            class_id=class_id,
            confidence=confidence,
            position=position,
            estimated_time_s=estimated_time,
            historical_success_rate=success_rate,
            risk_level=risk_level,
            failure_count=0,
        )

    def update_success_rate(self, class_id: int, success: bool) -> None:
        """Update success rate using Bayesian smoothing.

        Args:
            class_id: Object class to update
            success: Whether the pick succeeded
        """
        current = self.class_success_rates.get(class_id, self._DEFAULT_SUCCESS_RATE)

        if success:
            # Conservative boost: slowly increase confidence
            new_rate = (1 - self._SUCCESS_UPDATE_WEIGHT) * current + self._SUCCESS_UPDATE_WEIGHT
        else:
            # Stronger penalty: quickly reduce confidence
            new_rate = (1 - self._FAILURE_UPDATE_WEIGHT) * current

        # Clamp to reasonable bounds [0.1, 0.99]
        self.class_success_rates[class_id] = max(0.1, min(0.99, new_rate))

    def update_position(self, new_position: Tuple[int, int]) -> None:
        """Update current position for distance calculations.

        Args:
            new_position: New (x, y) position in 0.1mm units
        """
        self.current_position = new_position

    def _estimate_pick_time(self, target_pos: Tuple[int, int]) -> float:
        """Estimate time to reach and pick target.

        Args:
            target_pos: Target (x, y) in 0.1mm units

        Returns:
            Estimated time in seconds
        """
        distance_mm = self._calc_distance(target_pos)
        motion_time = distance_mm / self.motion_config.motion_speed_mm_per_s
        return motion_time + self.motion_config.total_pick_time_s

    def _calc_distance(self, target_pos: Tuple[int, int]) -> float:
        """Calculate Euclidean distance to target in mm.

        Args:
            target_pos: Target (x, y) in 0.1mm units

        Returns:
            Distance in mm
        """
        x_diff = (target_pos[0] - self.current_position[0]) * 0.1
        y_diff = (target_pos[1] - self.current_position[1]) * 0.1
        return (x_diff**2 + y_diff**2)**0.5

    def _classify_risk(self, confidence: float, success_rate: float) -> RiskLevel:
        """Classify risk based on confidence and historical success.

        Args:
            confidence: Vision detection confidence [0, 1]
            success_rate: Historical success rate [0, 1]

        Returns:
            RiskLevel classification
        """
        if (confidence >= self._SAFE_CONFIDENCE_THRESHOLD and
            success_rate >= self._SAFE_SUCCESS_RATE_THRESHOLD):
            return RiskLevel.SAFE
        elif confidence >= self._MEDIUM_CONFIDENCE_THRESHOLD:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.RISKY

    def get_success_rate(self, class_id: int) -> float:
        """Get current success rate for a class.

        Args:
            class_id: Object class

        Returns:
            Current success rate or default prior
        """
        return self.class_success_rates.get(class_id, self._DEFAULT_SUCCESS_RATE)

    def reset_class_rates(self) -> None:
        """Reset all class success rates (e.g., for new round)."""
        self.class_success_rates.clear()
