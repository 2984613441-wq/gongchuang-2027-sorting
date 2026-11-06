"""TSP (Traveling Salesman Problem) solver for path optimization.

Implements greedy nearest-neighbor approximation for efficient pick sequencing.
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .risk_classifier import ObjectRisk


def greedy_tsp(
    objects: List[ObjectRisk],
    start_pos: Tuple[int, int],
    *,
    position: Callable[[object], Tuple[int, int]] | None = None,
) -> List[ObjectRisk]:
    """Greedy nearest-neighbor TSP approximation.

    Builds a path by repeatedly selecting the closest unvisited object.
    Time complexity: O(n²)
    Approximation ratio: ~1.5x optimal on average

    Args:
        objects: List of objects to visit
        start_pos: Starting position (x, y) in 0.1mm units
        position: Optional accessor mapping one object to its (x, y) in the SAME
            units as start_pos. Defaults to obj.position (ObjectRisk). The
            Pi-side ITEM_TASK payload carries the same 0.1mm point under
            pick_x_position/pick_y_position, so the caller passes an accessor
            instead of fabricating ObjectRisk objects.

    Returns:
        Ordered list of objects following greedy path
    """
    if not objects:
        return []

    pos_of = position or (lambda obj: obj.position)
    result: List[ObjectRisk] = []
    remaining = objects.copy()
    current_pos = start_pos

    while remaining:
        # Find nearest object to current position
        nearest = min(
            remaining,
            key=lambda obj: _euclidean_distance(current_pos, pos_of(obj))
        )

        result.append(nearest)
        remaining.remove(nearest)
        current_pos = pos_of(nearest)

    return result


def _euclidean_distance(pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
    """Calculate Euclidean distance between two positions.

    Args:
        pos1: First position (x, y) in 0.1mm units
        pos2: Second position (x, y) in 0.1mm units

    Returns:
        Distance in 0.1mm units
    """
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]
    return (dx * dx + dy * dy) ** 0.5


def two_opt_improve(path: List[ObjectRisk], max_iterations: int = 100) -> List[ObjectRisk]:
    """2-opt local search improvement (optional enhancement).

    Repeatedly swaps edges to reduce total path length.
    Time complexity: O(n² × iterations)

    Args:
        path: Initial path from greedy_tsp
        max_iterations: Maximum optimization iterations

    Returns:
        Improved path
    """
    if len(path) < 4:
        return path  # 2-opt needs at least 4 nodes

    improved = path.copy()
    best_length = _path_length(improved)

    for _ in range(max_iterations):
        improved_this_round = False

        for i in range(1, len(improved) - 2):
            for j in range(i + 1, len(improved)):
                if j - i == 1:
                    continue  # Adjacent edges, skip

                # Try reversing segment [i, j]
                new_path = improved[:i] + improved[i:j][::-1] + improved[j:]
                new_length = _path_length(new_path)

                if new_length < best_length:
                    improved = new_path
                    best_length = new_length
                    improved_this_round = True
                    break

            if improved_this_round:
                break

        if not improved_this_round:
            break  # Local optimum reached

    return improved


def _path_length(path: List[ObjectRisk]) -> float:
    """Calculate total path length.

    Args:
        path: Ordered list of objects

    Returns:
        Total distance in 0.1mm units
    """
    if len(path) < 2:
        return 0.0

    total = 0.0
    for i in range(len(path) - 1):
        total += _euclidean_distance(path[i].position, path[i + 1].position)

    return total


def estimate_path_time(
    path: List[ObjectRisk],
    *,
    motion_speed_mm_per_s: float = 50.0,
    pick_time_s: float = 2.0
) -> float:
    """Estimate total time for a pick sequence.

    Args:
        path: Ordered list of objects
        motion_speed_mm_per_s: Linear motion speed
        pick_time_s: Time per pick action

    Returns:
        Estimated total time in seconds
    """
    if not path:
        return 0.0

    # Convert path length from 0.1mm units to mm
    path_length_mm = _path_length(path) * 0.1
    motion_time = path_length_mm / motion_speed_mm_per_s
    pick_time_total = len(path) * pick_time_s

    return motion_time + pick_time_total


__all__ = [
    "greedy_tsp",
    "two_opt_improve",
    "estimate_path_time",
]
