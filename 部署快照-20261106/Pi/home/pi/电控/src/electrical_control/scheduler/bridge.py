"""Scheduler integration wrapper for vision batch processing.

This module bridges vision detection results and the phased scheduler,
converting VisionTarget objects to scheduler-compatible format.
"""

from __future__ import annotations

from typing import List, Optional

from electrical_control.protocol import ItemTaskPayload
from electrical_control.rpi.vision_ingest import BatchTargets, VisionTarget

from .phased_scheduler import PhasedScheduler


def vision_target_to_scheduler_object(
    target: VisionTarget,
    *,
    x_position: int = 0,
    y_position: int = 0,
) -> dict:
    """Convert VisionTarget to scheduler-compatible object dict.

    Args:
        target: VisionTarget from vision system
        x_position: Calibrated X position in 0.1mm units (default 0)
        y_position: Calibrated Y position in 0.1mm units (default 0)

    Returns:
        Dict with keys: id, class_id, confidence, x, y
    """
    return {
        "id": target.target_seq,
        "class_id": target.class_id,
        "confidence": target.confidence / 100.0,  # Convert 0-100 to 0.0-1.0
        "x": x_position,
        "y": y_position,
        # Additional metadata for debugging
        "_color_id": target.color_id,
        "_pixel_x": target.pixel_x,
        "_pixel_y": target.pixel_y,
    }


class SchedulerBridge:
    """Bridge between vision batches and intelligent scheduling.

    This class orchestrates:
    1. Vision batch reception
    2. Scheduler prioritization
    3. Ordered task queue generation
    """

    def __init__(self, scheduler: PhasedScheduler):
        """Initialize bridge with scheduler instance.

        Args:
            scheduler: PhasedScheduler instance
        """
        self.scheduler = scheduler
        self._current_batch: Optional[BatchTargets] = None
        self._task_queue: List[ItemTaskPayload] = []
        self._target_lookup: dict[int, VisionTarget] = {}
        # P3: VisionTarget -> (grasp_x, grasp_y) in 0.1mm, or None when unknown.
        # Unset until the pixel->mm calibration is injected, so payloads stay
        # non-serializable rather than silently grasping at the device centre.
        self._calibrate_grasp: Optional[callable] = None

    def process_batch(
        self,
        batch: BatchTargets,
        *,
        calibrate_position: callable = None,
        calibrate_grasp: callable = None,
    ) -> None:
        """Process vision batch and initialize scheduler.

        Args:
            batch: BatchTargets from vision system
            calibrate_position: Optional function (VisionTarget) -> (x, y) in 0.1mm
                                If None, uses placeholder (0, 0)
            calibrate_grasp: Optional function (VisionTarget) -> (x, y) in 0.1mm.
                                The GRASP point (P3). If None, payloads carry no
                                grasp point and cannot be serialized - there is
                                deliberately no (0, 0) fallback.
        """
        self._current_batch = batch
        self._target_lookup.clear()
        self._calibrate_grasp = calibrate_grasp

        # Build scheduler-compatible object list
        objects = []
        for target in batch.targets:
            self._target_lookup[target.target_seq] = target

            # Get calibrated position if available
            if calibrate_position is not None:
                x_pos, y_pos = calibrate_position(target)
            else:
                x_pos, y_pos = 0, 0

            obj = vision_target_to_scheduler_object(
                target,
                x_position=x_pos,
                y_position=y_pos,
            )
            objects.append(obj)

        # Initialize scheduler with all objects
        self.scheduler.start_round(objects)

    def get_next_task(self) -> Optional[ItemTaskPayload]:
        """Get next task from scheduler-prioritized queue.

        Returns:
            ItemTaskPayload for next object to pick, or None if no targets
        """
        if self.scheduler.should_abort():
            return None

        target_obj = self.scheduler.get_next_target()
        if target_obj is None:
            return None

        # Map back to VisionTarget
        target_seq = target_obj.object_id
        vision_target = self._target_lookup.get(target_seq)
        if vision_target is None:
            return None

        # Build ItemTaskPayload
        # Note: This assumes drop table is not yet integrated
        # When drop table lands, replace (0, 0, 0) with real coordinates
        grasp = self._calibrate_grasp(vision_target) if self._calibrate_grasp else None
        return ItemTaskPayload(
            target_seq=vision_target.target_seq,
            class_id=vision_target.class_id,
            image_id=vision_target.class_id,  # Frozen 1:1 mapping
            x_position=target_obj.position[0],
            y_position=target_obj.position[1],
            grip_angle=0xFF,  # Frozen "no rotation"
            # P3: None until calibrate_grasp is injected; encode then refuses
            # (fail-closed) instead of commanding a grasp at the centre (E-18).
            pick_x_position=grasp[0] if grasp else None,
            pick_y_position=grasp[1] if grasp else None,
        )

    def mark_task_completed(self, target_seq: int, success: bool) -> None:
        """Mark task as completed and update scheduler.

        Args:
            target_seq: Target sequence number
            success: Whether pick succeeded
        """
        self.scheduler.mark_completed(target_seq, success)

    def get_scheduler_stats(self) -> dict:
        """Get current scheduler statistics.

        Returns:
            Stats dict from scheduler
        """
        return self.scheduler.get_stats()

    def should_abort_round(self) -> bool:
        """Check if scheduler recommends aborting round.

        Returns:
            True if should abort to avoid 15s penalty
        """
        return self.scheduler.should_abort()


__all__ = [
    "SchedulerBridge",
    "vision_target_to_scheduler_object",
]
