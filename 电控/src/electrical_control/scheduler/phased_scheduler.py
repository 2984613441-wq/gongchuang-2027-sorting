"""Three-phase scheduler with time-segmented risk strategies.

Phase 1 (0-7s): Quick harvest - high confidence + close distance
Phase 2 (7-12s): Stable fill - TSP path optimization on safe objects
Phase 3 (12-15s): Conservative finish - ultra-high confidence only
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from .risk_classifier import RiskClassifier, RiskLevel, ObjectRisk
from .tsp_solver import greedy_tsp


class PhasedScheduler:
    """Time-aware scheduler balancing accuracy and speed within 15s limit."""

    # Phase boundaries (seconds from round start)
    PHASE1_END = 7.0   # Quick harvest period
    PHASE2_END = 12.0  # Stable fill period
    # Phase 3: 12-15s conservative finish

    # Phase 3 strict thresholds
    PHASE3_MIN_CONFIDENCE = 0.88  # Relaxed from 0.9 to avoid premature abort
    PHASE3_MAX_TIME = 2.0         # Relaxed from 1.5s to allow more picks

    # Safety margin to avoid 15s penalty
    ABORT_MARGIN_S = 4.0  # Increased from 3.0s for Z-axis safety

    def __init__(self, time_limit_s: float = 15.0):
        """Initialize scheduler with time limit.

        Args:
            time_limit_s: Maximum time per round (default 15s)
        """
        self.time_limit = time_limit_s
        self.start_time: Optional[float] = None
        self.classifier = RiskClassifier()
        self.objects: List[ObjectRisk] = []
        self.completed_ids: set[int] = set()
        self._last_selected_id: Optional[int] = None
        # Recent pick exclusion zone (30mm radius, cleared on next completion)
        self._recent_pick_pos: Optional[Tuple[float, float]] = None
        self._exclusion_radius_mm: float = 30.0

    def start_round(self, objects: List[dict]) -> None:
        """Start new round and classify all objects.

        Args:
            objects: List of detection dicts with keys: id, class_id, confidence, x, y
        """
        self.start_time = time.time()
        self.completed_ids.clear()
        self.objects = [self.classifier.classify(obj) for obj in objects]
        self._last_selected_id = None

    def get_next_target(self) -> Optional[ObjectRisk]:
        """Select next target based on current phase strategy.

        Returns:
            ObjectRisk to pick next, or None if no suitable target
        """
        if self.start_time is None:
            return None

        elapsed = time.time() - self.start_time
        remaining = self.time_limit - elapsed

        # Filter completed objects
        candidates = [
            obj for obj in self.objects
            if obj.object_id not in self.completed_ids
        ]

        # Filter recent pick exclusion zone (prevent re-picking空位)
        if self._recent_pick_pos is not None:
            rx, ry = self._recent_pick_pos
            candidates = [
                obj for obj in candidates
                if ((obj.position[0] - rx)**2 + (obj.position[1] - ry)**2)**0.5
                   > self._exclusion_radius_mm
            ]

        if not candidates:
            return None

        # Route to phase-specific strategy
        if elapsed < self.PHASE1_END:
            target = self._phase1_select(candidates)
        elif elapsed < self.PHASE2_END:
            target = self._phase2_select(candidates, remaining)
        else:
            target = self._phase3_select(candidates, remaining)

        # Record target position as exclusion zone
        if target is not None:
            self._recent_pick_pos = target.position

        return target

    def mark_completed(self, object_id: int, success: bool) -> None:
        """Mark object as completed and update success rates.

        Args:
            object_id: ID of completed object
            success: Whether pick succeeded
        """
        self.completed_ids.add(object_id)

        # Find object and update classifier
        for obj in self.objects:
            if obj.object_id == object_id:
                self.classifier.update_success_rate(obj.class_id, success)
                # Update position for distance calculations
                self.classifier.update_position(obj.position)

                if not success:
                    # Increment failure count for this object
                    # Note: ObjectRisk is frozen, so we track failures externally
                    pass
                break

        # Clear exclusion zone after completing current pick
        self._recent_pick_pos = None

    def should_abort(self) -> bool:
        """Check if round should abort early to avoid 15s penalty.

        Returns:
            True if remaining time < safety margin
        """
        if self.start_time is None:
            return False

        elapsed = time.time() - self.start_time
        remaining = self.time_limit - elapsed

        return remaining < self.ABORT_MARGIN_S

    def get_phase_name(self) -> str:
        """Get current phase name for logging.

        Returns:
            Phase name string
        """
        if self.start_time is None:
            return "NOT_STARTED"

        elapsed = time.time() - self.start_time
        if elapsed < self.PHASE1_END:
            return "PHASE1_HARVEST"
        elif elapsed < self.PHASE2_END:
            return "PHASE2_FILL"
        else:
            return "PHASE3_FINISH"

    def get_elapsed(self) -> float:
        """Get elapsed time since round start.

        Returns:
            Elapsed seconds, or 0 if not started
        """
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def get_remaining(self) -> float:
        """Get remaining time in round.

        Returns:
            Remaining seconds, or time_limit if not started
        """
        if self.start_time is None:
            return self.time_limit
        return self.time_limit - self.get_elapsed()

    # ====== Phase-specific selection strategies ======

    def _phase1_select(self, candidates: List[ObjectRisk]) -> Optional[ObjectRisk]:
        """Phase 1: Quick harvest - prioritize high confidence + close distance.

        Strategy: Grab the low-hanging fruit fast (3-4 items in 7s)
        - Filter: SAFE + MEDIUM risk
        - Sort by: estimated time (distance + pick time)
        - Fallback: If no SAFE/MEDIUM, consider all

        Args:
            candidates: Available objects

        Returns:
            Closest high-confidence object
        """
        # Filter by risk level
        filtered = [
            obj for obj in candidates
            if obj.risk_level in [RiskLevel.SAFE, RiskLevel.MEDIUM]
        ]

        if not filtered:
            # Fallback: no safe options, consider everything
            filtered = candidates

        if not filtered:
            return None

        # Select closest (minimum estimated time)
        return min(filtered, key=lambda obj: obj.estimated_time_s)

    def _phase2_select(
        self,
        candidates: List[ObjectRisk],
        remaining: float
    ) -> Optional[ObjectRisk]:
        """Phase 2: Stable fill - TSP-like path optimization on safe objects.

        Strategy: Maximize safe picks with efficient routing (4-5 items in 5s)
        - Filter: Only SAFE objects
        - Sort by: distance from current position (greedy TSP)
        - Fallback: If no SAFE, consider MEDIUM

        Args:
            candidates: Available objects
            remaining: Remaining time in round

        Returns:
            Next safe object in optimal path
        """
        # Only consider safe objects
        safe_objs = [obj for obj in candidates if obj.risk_level == RiskLevel.SAFE]

        if not safe_objs:
            # Fallback: try MEDIUM risk
            safe_objs = [obj for obj in candidates if obj.risk_level == RiskLevel.MEDIUM]

        if not safe_objs:
            return None

        # Use TSP path planning for optimal routing
        current_pos = self.classifier.current_position
        path = greedy_tsp(safe_objs, current_pos)

        # Return first object in optimal path
        return path[0] if path else None

    def _phase3_select(
        self,
        candidates: List[ObjectRisk],
        remaining: float
    ) -> Optional[ObjectRisk]:
        """Phase 3: Conservative finish - only ultra-high confidence + fast picks.

        Strategy: Avoid 15s penalty, only take sure bets (1-2 items max)
        - Filter: confidence > 0.9 AND estimated_time < 1.5s
        - Sort by: fastest first
        - Safety: Stop if remaining < 3s

        Args:
            candidates: Available objects
            remaining: Remaining time in round

        Returns:
            Ultra-safe fast object, or None if too risky
        """
        # Strict filtering: ultra-high confidence + fast
        ultra_safe = [
            obj for obj in candidates
            if obj.confidence > self.PHASE3_MIN_CONFIDENCE
            and obj.estimated_time_s < self.PHASE3_MAX_TIME
        ]

        if not ultra_safe:
            # No safe options: better to stop than risk penalty
            return None

        # Select fastest
        return min(ultra_safe, key=lambda obj: obj.estimated_time_s)

    # ====== Statistics and diagnostics ======

    def get_stats(self) -> dict:
        """Get current round statistics.

        Returns:
            Dict with completion counts, phase info, timing
        """
        completed_count = len(self.completed_ids)
        total_count = len(self.objects)

        risk_breakdown = {
            "safe": sum(1 for obj in self.objects if obj.risk_level == RiskLevel.SAFE),
            "medium": sum(1 for obj in self.objects if obj.risk_level == RiskLevel.MEDIUM),
            "risky": sum(1 for obj in self.objects if obj.risk_level == RiskLevel.RISKY),
        }

        return {
            "completed": completed_count,
            "total": total_count,
            "remaining": total_count - completed_count,
            "elapsed": self.get_elapsed(),
            "remaining_time": self.get_remaining(),
            "phase": self.get_phase_name(),
            "risk_breakdown": risk_breakdown,
        }
