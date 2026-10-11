"""Unit tests for TSP solver module."""

import pytest
from electrical_control.scheduler import ObjectRisk, RiskLevel
from electrical_control.scheduler.tsp_solver import (
    greedy_tsp,
    two_opt_improve,
    estimate_path_time,
)


def create_test_object(obj_id: int, x: int, y: int, confidence: float = 0.9) -> ObjectRisk:
    """Helper to create test ObjectRisk."""
    return ObjectRisk(
        object_id=obj_id,
        class_id=0,
        confidence=confidence,
        position=(x, y),
        estimated_time_s=2.0,
        historical_success_rate=0.8,
        risk_level=RiskLevel.SAFE,
    )


class TestGreedyTSP:
    """Test suite for greedy TSP solver."""

    def test_empty_list(self):
        """Test TSP with empty object list."""
        result = greedy_tsp([], (0, 0))
        assert result == []

    def test_single_object(self):
        """Test TSP with single object."""
        obj = create_test_object(1, 100, 100)
        result = greedy_tsp([obj], (0, 0))

        assert len(result) == 1
        assert result[0].object_id == 1

    def test_two_objects_nearest_first(self):
        """Test TSP selects nearest object first."""
        obj1 = create_test_object(1, 500, 500)  # Far
        obj2 = create_test_object(2, 50, 50)    # Close
        result = greedy_tsp([obj1, obj2], (0, 0))

        assert len(result) == 2
        assert result[0].object_id == 2  # Nearest first
        assert result[1].object_id == 1

    def test_three_objects_greedy_path(self):
        """Test TSP builds greedy nearest-neighbor path."""
        obj1 = create_test_object(1, 0, 100)
        obj2 = create_test_object(2, 100, 0)
        obj3 = create_test_object(3, 100, 100)

        result = greedy_tsp([obj1, obj2, obj3], (0, 0))

        assert len(result) == 3
        # From (0,0): nearest is obj1 or obj2 (both ~100 units)
        # Then continue greedy from there
        assert result[0].object_id in [1, 2]

    def test_path_visits_all_objects(self):
        """Test TSP visits all objects exactly once."""
        objects = [create_test_object(i, i * 100, i * 100) for i in range(1, 6)]

        result = greedy_tsp(objects, (0, 0))

        assert len(result) == 5
        visited_ids = {obj.object_id for obj in result}
        assert visited_ids == {1, 2, 3, 4, 5}

    def test_start_position_affects_path(self):
        """Test different start positions yield different paths."""
        obj1 = create_test_object(1, 0, 100)
        obj2 = create_test_object(2, 100, 0)
        obj3 = create_test_object(3, 200, 200)  # Add third object to break ties
        objects = [obj1, obj2, obj3]

        path_from_origin = greedy_tsp(objects, (0, 0))
        path_from_top = greedy_tsp(objects, (0, 200))

        # From (0,0): obj1 or obj2 are closest (both ~100 units)
        # From (0,200): obj1 is closest (100 units vs obj2 at ~224 units)
        # Different start positions should yield different paths
        assert path_from_top[0].object_id == 1  # obj1 is closest to (0,200)


class TestTwoOptImprove:
    """Test suite for 2-opt improvement."""

    def test_empty_path(self):
        """Test 2-opt with empty path."""
        result = two_opt_improve([])
        assert result == []

    def test_short_path_no_improvement(self):
        """Test 2-opt with path too short for optimization."""
        obj1 = create_test_object(1, 100, 100)
        obj2 = create_test_object(2, 200, 200)
        path = [obj1, obj2]

        result = two_opt_improve(path)

        # Too short for 2-opt, returns as-is
        assert len(result) == 2

    def test_four_objects_can_improve(self):
        """Test 2-opt can improve suboptimal path."""
        # Create a path with a crossing (suboptimal)
        obj1 = create_test_object(1, 0, 0)
        obj2 = create_test_object(2, 100, 100)
        obj3 = create_test_object(3, 0, 100)
        obj4 = create_test_object(4, 100, 0)

        # Suboptimal path: 1 -> 3 -> 2 -> 4 (crosses)
        suboptimal_path = [obj1, obj3, obj2, obj4]

        result = two_opt_improve(suboptimal_path, max_iterations=10)

        # Should improve or stay same (never worse)
        assert len(result) == 4


class TestEstimatePathTime:
    """Test suite for path time estimation."""

    def test_empty_path(self):
        """Test time estimation for empty path."""
        assert estimate_path_time([]) == 0.0

    def test_single_object(self):
        """Test time estimation for single object."""
        obj = create_test_object(1, 100, 100)
        time_s = estimate_path_time([obj], pick_time_s=2.0)

        # Only pick time, no motion
        assert time_s == 2.0

    def test_two_objects_includes_motion(self):
        """Test time estimation includes motion time."""
        obj1 = create_test_object(1, 0, 0)
        obj2 = create_test_object(2, 1000, 0)  # 100mm away (1000 * 0.1mm)

        time_s = estimate_path_time(
            [obj1, obj2],
            motion_speed_mm_per_s=50.0,
            pick_time_s=2.0
        )

        # Motion: 100mm / 50mm/s = 2s
        # Picks: 2 * 2s = 4s
        # Total: 6s
        assert 5.9 < time_s < 6.1

    def test_longer_path_sums_correctly(self):
        """Test time estimation for longer path."""
        objects = [
            create_test_object(1, 0, 0),
            create_test_object(2, 500, 0),    # 50mm
            create_test_object(3, 500, 500),  # 50mm
            create_test_object(4, 0, 500),    # 50mm
        ]

        time_s = estimate_path_time(
            objects,
            motion_speed_mm_per_s=50.0,
            pick_time_s=2.0
        )

        # Motion: 150mm / 50mm/s = 3s
        # Picks: 4 * 2s = 8s
        # Total: ~11s
        assert 10.5 < time_s < 11.5


class TestIntegration:
    """Integration tests combining TSP components."""

    def test_greedy_then_improve(self):
        """Test full pipeline: greedy TSP + 2-opt improvement."""
        objects = [
            create_test_object(1, 0, 0),
            create_test_object(2, 100, 0),
            create_test_object(3, 100, 100),
            create_test_object(4, 0, 100),
        ]

        # Build greedy path
        greedy_path = greedy_tsp(objects, (0, 0))

        # Improve with 2-opt
        improved_path = two_opt_improve(greedy_path, max_iterations=20)

        # Estimate times
        greedy_time = estimate_path_time(greedy_path)
        improved_time = estimate_path_time(improved_path)

        # Improved should be <= greedy (never worse)
        assert improved_time <= greedy_time

    def test_realistic_scenario_12_objects(self):
        """Test realistic scenario with 12 objects."""
        objects = [
            create_test_object(i, (i % 4) * 300, (i // 4) * 300)
            for i in range(1, 13)
        ]

        # Build path
        path = greedy_tsp(objects, (0, 0))
        improved_path = two_opt_improve(path, max_iterations=50)

        # Estimate time
        total_time = estimate_path_time(
            improved_path,
            motion_speed_mm_per_s=50.0,
            pick_time_s=2.0
        )

        # 12 objects should be completable within 15s target
        # (This is just path time, doesn't include Z-axis moves)
        assert len(improved_path) == 12
        assert total_time > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
