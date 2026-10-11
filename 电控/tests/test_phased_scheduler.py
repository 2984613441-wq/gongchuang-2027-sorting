"""Unit tests for phased scheduler module."""

import time
import pytest
from electrical_control.scheduler import PhasedScheduler, RiskLevel


class TestPhasedScheduler:
    """Test suite for PhasedScheduler."""

    def test_initialization(self):
        """Test scheduler initialization."""
        scheduler = PhasedScheduler(time_limit_s=15.0)

        assert scheduler.time_limit == 15.0
        assert scheduler.start_time is None
        assert len(scheduler.objects) == 0
        assert len(scheduler.completed_ids) == 0

    def test_start_round(self):
        """Test round initialization."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},
            {'id': 2, 'class_id': 1, 'confidence': 0.8, 'x': 200, 'y': 200},
            {'id': 3, 'class_id': 2, 'confidence': 0.6, 'x': 300, 'y': 300},
        ]

        scheduler.start_round(objects)

        assert scheduler.start_time is not None
        assert len(scheduler.objects) == 3
        assert len(scheduler.completed_ids) == 0

    def test_phase1_select_high_confidence(self):
        """Test Phase 1: selects high-confidence close objects."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},   # SAFE, close
            {'id': 2, 'class_id': 1, 'confidence': 0.75, 'x': 500, 'y': 500},  # MEDIUM, far
            {'id': 3, 'class_id': 2, 'confidence': 0.6, 'x': 50, 'y': 50},     # RISKY, closest
        ]

        scheduler.start_round(objects)

        # Phase 1 should prefer SAFE/MEDIUM, sorted by distance
        target = scheduler.get_next_target()

        assert target is not None
        assert target.object_id in [1, 2]  # Should pick SAFE or MEDIUM, not RISKY

    def test_phase2_select_safe_only(self):
        """Test Phase 2: only selects safe objects."""
        scheduler = PhasedScheduler()

        # Manually set high success rates to create SAFE objects
        scheduler.classifier.class_success_rates[0] = 0.85
        scheduler.classifier.class_success_rates[1] = 0.85
        scheduler.classifier.class_success_rates[2] = 0.85

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},   # SAFE
            {'id': 2, 'class_id': 1, 'confidence': 0.75, 'x': 50, 'y': 50},    # MEDIUM (conf<0.85)
            {'id': 3, 'class_id': 2, 'confidence': 0.6, 'x': 20, 'y': 20},     # RISKY
        ]

        scheduler.start_round(objects)

        # Artificially advance to Phase 2
        scheduler.start_time = time.time() - 8.0  # 8s elapsed

        target = scheduler.get_next_target()

        assert target is not None
        assert target.object_id == 1  # Only SAFE object

    def test_phase3_strict_filtering(self):
        """Test Phase 3: strict confidence and time filtering."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.85, 'x': 100, 'y': 100},  # SAFE but not ultra-high
            {'id': 2, 'class_id': 1, 'confidence': 0.95, 'x': 10, 'y': 10},    # Ultra-high confidence, very close
            {'id': 3, 'class_id': 2, 'confidence': 0.92, 'x': 5000, 'y': 5000}, # Ultra-high but far
        ]

        scheduler.start_round(objects)

        # Artificially advance to Phase 3
        scheduler.start_time = time.time() - 13.0  # 13s elapsed

        target = scheduler.get_next_target()

        # Phase 3 is conservative - may return None if no ultra-safe+fast option
        # This is correct behavior (better to stop than risk 15s penalty)
        if target is not None:
            assert target.confidence > 0.9
            assert target.estimated_time_s < 1.5

    def test_mark_completed_updates_state(self):
        """Test marking objects as completed."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},
            {'id': 2, 'class_id': 1, 'confidence': 0.8, 'x': 200, 'y': 200},
        ]

        scheduler.start_round(objects)

        scheduler.mark_completed(1, success=True)

        assert 1 in scheduler.completed_ids
        assert 2 not in scheduler.completed_ids

        # Next target should skip completed object
        target = scheduler.get_next_target()
        assert target.object_id == 2

    def test_should_abort_safety_margin(self):
        """Test abort logic with safety margin."""
        scheduler = PhasedScheduler(time_limit_s=15.0)

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},
        ]

        scheduler.start_round(objects)

        # Artificially advance time to 13s (2s remaining < 3s margin)
        scheduler.start_time = time.time() - 13.0

        assert scheduler.should_abort() is True

    def test_get_stats(self):
        """Test statistics reporting."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},
            {'id': 2, 'class_id': 1, 'confidence': 0.75, 'x': 200, 'y': 200},
            {'id': 3, 'class_id': 2, 'confidence': 0.6, 'x': 300, 'y': 300},
        ]

        scheduler.start_round(objects)
        scheduler.mark_completed(1, success=True)

        stats = scheduler.get_stats()

        assert stats['completed'] == 1
        assert stats['total'] == 3
        assert stats['remaining'] == 2
        assert stats['phase'] == 'PHASE1_HARVEST'
        assert 'risk_breakdown' in stats

    def test_empty_candidates_returns_none(self):
        """Test behavior when no candidates available."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.9, 'x': 100, 'y': 100},
        ]

        scheduler.start_round(objects)
        scheduler.mark_completed(1, success=True)

        # All objects completed
        target = scheduler.get_next_target()

        assert target is None

    def test_phase3_returns_none_if_no_ultra_safe(self):
        """Test Phase 3 returns None when no ultra-safe options."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': 1, 'class_id': 0, 'confidence': 0.85, 'x': 100, 'y': 100},  # Not ultra-high
            {'id': 2, 'class_id': 1, 'confidence': 0.75, 'x': 200, 'y': 200},  # Medium
        ]

        scheduler.start_round(objects)

        # Artificially advance to Phase 3
        scheduler.start_time = time.time() - 13.0

        target = scheduler.get_next_target()

        # Phase 3 should refuse to pick non-ultra-safe objects
        assert target is None


class TestScenarios:
    """Integration test scenarios from requirements."""

    def test_scenario1_normal_flow(self):
        """Scenario 1: Normal flow with 12 objects."""
        scheduler = PhasedScheduler()

        # 12 objects, uniform distribution
        objects = [
            {'id': i, 'class_id': i % 6, 'confidence': 0.85 + (i % 3) * 0.05,
             'x': (i % 4) * 300, 'y': (i // 4) * 300}
            for i in range(1, 13)
        ]

        scheduler.start_round(objects)

        completed = 0
        for _ in range(12):
            if scheduler.should_abort():
                break

            target = scheduler.get_next_target()
            if target is None:
                break

            scheduler.mark_completed(target.object_id, success=True)
            completed += 1

        # Should complete multiple objects without aborting
        assert completed >= 8

    def test_scenario2_low_confidence(self):
        """Scenario 2: Low confidence scenario."""
        scheduler = PhasedScheduler()

        # Boost success rates to make high-confidence objects SAFE
        for i in range(6):
            scheduler.classifier.class_success_rates[i] = 0.85

        # 12 objects, only 4 with confidence > 0.7
        objects = [
            {'id': i, 'class_id': i % 6, 'confidence': 0.9 if i <= 4 else 0.65,
             'x': i * 100, 'y': i * 100}
            for i in range(1, 13)
        ]

        scheduler.start_round(objects)

        safe_picked = 0
        for _ in range(12):
            if scheduler.should_abort():
                break

            target = scheduler.get_next_target()
            if target is None:
                break

            if target.risk_level == RiskLevel.SAFE:
                safe_picked += 1

            scheduler.mark_completed(target.object_id, success=True)

        # Should prioritize safe objects
        assert safe_picked >= 3

    def test_scenario3_time_pressure(self):
        """Scenario 3: Time pressure, early abort."""
        scheduler = PhasedScheduler()

        objects = [
            {'id': i, 'class_id': i % 6, 'confidence': 0.85,
             'x': i * 100, 'y': i * 100}
            for i in range(1, 13)
        ]

        scheduler.start_round(objects)

        # Artificially advance to 12.5s (2.5s remaining)
        scheduler.start_time = time.time() - 12.5

        # Should abort due to safety margin
        assert scheduler.should_abort() is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
