"""Test recent pick exclusion zone to prevent re-picking same position."""

import pytest
from electrical_control.scheduler import PhasedScheduler, RiskLevel


@pytest.fixture
def scheduler():
    """Create scheduler instance."""
    return PhasedScheduler(time_limit_s=15.0)


@pytest.fixture
def mock_objects():
    """Create mock objects at different positions."""
    return [
        {
            "id": 1,
            "class_id": 0,
            "confidence": 0.85,
            "x": 100.0,
            "y": 100.0,
        },
        {
            "id": 2,
            "class_id": 0,
            "confidence": 0.80,
            "x": 105.0,  # 5mm away (within 30mm exclusion)
            "y": 100.0,
        },
        {
            "id": 3,
            "class_id": 1,
            "confidence": 0.75,
            "x": 150.0,  # 50mm away (outside exclusion)
            "y": 100.0,
        },
    ]


def test_no_exclusion_on_first_pick(scheduler, mock_objects):
    """First pick should not be filtered."""
    scheduler.start_round(mock_objects)

    target = scheduler.get_next_target()
    assert target is not None
    assert target.object_id == 1  # Highest confidence


def test_exclusion_zone_filters_nearby(scheduler, mock_objects):
    """Nearby objects within 30mm should be filtered after a pick."""
    scheduler.start_round(mock_objects)

    # First pick: obj 1 at (100, 100)
    target1 = scheduler.get_next_target()
    assert target1.object_id == 1

    # Simulate completion (but obj 1 still in frame with same position)
    # Before mark_completed, exclusion zone is active
    # Obj 2 at (105, 100) is 5mm away → should be filtered

    # Second call without mark_completed → exclusion active
    candidates = [
        obj for obj in scheduler.objects
        if obj.object_id not in scheduler.completed_ids
    ]

    # Manual exclusion check
    if scheduler._recent_pick_pos is not None:
        rx, ry = scheduler._recent_pick_pos
        filtered = [
            obj for obj in candidates
            if ((obj.position[0] - rx)**2 + (obj.position[1] - ry)**2)**0.5
               > scheduler._exclusion_radius_mm
        ]
        # Candidates = obj 1, 2, 3 (obj 1 not yet in completed_ids)
        # After exclusion: obj 1 (0mm) and obj 2 (5mm) filtered, only obj 3 left
        assert len(filtered) == 1  # Only obj 3 (50mm away)
        assert all(obj.object_id != 2 for obj in filtered)


def test_exclusion_cleared_after_completion(scheduler, mock_objects):
    """Exclusion zone should clear after mark_completed."""
    scheduler.start_round(mock_objects)

    # First pick
    target1 = scheduler.get_next_target()
    assert target1.object_id == 1

    # Mark completed → clears exclusion zone
    scheduler.mark_completed(1, success=True)

    # Now obj 2 should be selectable again
    target2 = scheduler.get_next_target()
    assert target2 is not None
    # Should pick obj 2 (closer than obj 3)
    assert target2.object_id == 2


def test_consecutive_frames_different_positions(scheduler):
    """Simulate bug scenario: same object detected in two frames.

    Frame 1: obj at (100, 100) → selected
    Frame 2: same obj at (100, 100) → should be filtered
    """
    # Frame 1
    frame1 = [
        {"id": 1, "class_id": 0, "confidence": 0.85, "x": 100.0, "y": 100.0},
        {"id": 2, "class_id": 1, "confidence": 0.75, "x": 150.0, "y": 100.0},
    ]
    scheduler.start_round(frame1)
    target1 = scheduler.get_next_target()
    assert target1.position == (100.0, 100.0)

    # Frame 2: same object still visible (execution not completed yet)
    # ID changes (detection re-generates IDs), but position same
    frame2 = [
        {"id": 10, "class_id": 0, "confidence": 0.83, "x": 100.0, "y": 100.0},  # Same物理位置
        {"id": 11, "class_id": 1, "confidence": 0.76, "x": 150.0, "y": 100.0},
    ]

    # Update objects without clearing exclusion
    scheduler.objects = [scheduler.classifier.classify(obj) for obj in frame2]
    # Don't clear completed_ids or _recent_pick_pos

    # Second get_next_target should filter obj 10 (at exclusion zone)
    target2 = scheduler.get_next_target()
    assert target2 is not None
    assert target2.position != (100.0, 100.0)  # Should pick obj 11 instead
    assert target2.position == (150.0, 100.0)


def test_exclusion_radius_boundary(scheduler):
    """Test objects exactly at 30mm boundary."""
    objects = [
        {"id": 1, "class_id": 0, "confidence": 0.85, "x": 0.0, "y": 0.0},
        {"id": 2, "class_id": 0, "confidence": 0.80, "x": 30.0, "y": 0.0},  # Exactly 30mm
        {"id": 3, "class_id": 0, "confidence": 0.75, "x": 31.0, "y": 0.0},  # 31mm (outside)
    ]
    scheduler.start_round(objects)

    target1 = scheduler.get_next_target()
    assert target1.object_id == 1

    # Check boundary: 30mm should be filtered, 31mm should pass
    candidates = [
        obj for obj in scheduler.objects
        if obj.object_id not in scheduler.completed_ids
    ]

    rx, ry = scheduler._recent_pick_pos
    filtered = [
        obj for obj in candidates
        if ((obj.position[0] - rx)**2 + (obj.position[1] - ry)**2)**0.5
           > scheduler._exclusion_radius_mm
    ]

    # Only obj 3 should pass (31mm > 30mm)
    assert len(filtered) == 1
    assert filtered[0].object_id == 3
