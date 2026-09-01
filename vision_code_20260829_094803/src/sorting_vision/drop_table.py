"""Drop-point table mapping visual box ids to physical coordinates.

The coordinates are mechanical facts that must be measured on site and
injected here; this module never invents them. Protocol V0.6 limits the
ITEM_TASK X/Y coordinate to +-145.0 mm (origin = device center), which is
+-1450 in 0.1 mm units.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


ITEM_TASK_COORD_LIMIT = 1450
MIN_BOX_ID = 1
MAX_BOX_ID = 6


class DropTableError(Exception):
    code = "DROP_TABLE_ERROR"


@dataclass(frozen=True, slots=True)
class DropPoint:
    x_0_1mm: int
    y_0_1mm: int

    def __post_init__(self) -> None:
        for name in ("x_0_1mm", "y_0_1mm"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise DropTableError(f"{name} must be a signed integer")
            if not -ITEM_TASK_COORD_LIMIT <= value <= ITEM_TASK_COORD_LIMIT:
                raise DropTableError(
                    f"{name} out of range (+-{ITEM_TASK_COORD_LIMIT})"
                )


class DropTable:
    """Maps box_id (1..6) to its measured physical drop coordinates."""

    def __init__(self, points: Mapping[int, DropPoint]) -> None:
        if not points:
            raise DropTableError("drop table must not be empty")
        normalized: dict[int, DropPoint] = {}
        for box_id, point in points.items():
            if not isinstance(box_id, int) or isinstance(box_id, bool):
                raise DropTableError("box_id must be an integer")
            if not MIN_BOX_ID <= box_id <= MAX_BOX_ID:
                raise DropTableError(f"box_id must be in [{MIN_BOX_ID}, {MAX_BOX_ID}]")
            if not isinstance(point, DropPoint):
                raise DropTableError("point must be a DropPoint")
            normalized[box_id] = point
        self._points = normalized

    def point_for(self, box_id: int) -> DropPoint:
        point = self._points.get(box_id)
        if point is None:
            raise DropTableError(f"no drop point configured for box_id {box_id}")
        return point
