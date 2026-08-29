from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from sorting_vision.drop_table import (
    DropPoint,
    DropTable,
    DropTableError,
    ITEM_TASK_COORD_LIMIT,
)


class DropTableTests(unittest.TestCase):
    def test_point_accepts_boundary_coordinate(self) -> None:
        point = DropPoint(ITEM_TASK_COORD_LIMIT, -ITEM_TASK_COORD_LIMIT)
        self.assertEqual(ITEM_TASK_COORD_LIMIT, point.x_0_1mm)
        self.assertEqual(-ITEM_TASK_COORD_LIMIT, point.y_0_1mm)

    def test_point_rejects_out_of_range_coordinate(self) -> None:
        with self.assertRaises(DropTableError):
            DropPoint(ITEM_TASK_COORD_LIMIT + 1, 0)
        with self.assertRaises(DropTableError):
            DropPoint(0, -ITEM_TASK_COORD_LIMIT - 1)

    def test_point_rejects_non_integer(self) -> None:
        with self.assertRaises(DropTableError):
            DropPoint(True, 0)
        with self.assertRaises(DropTableError):
            DropPoint(0, 1.5)

    def test_table_rejects_empty(self) -> None:
        with self.assertRaises(DropTableError):
            DropTable({})

    def test_table_rejects_out_of_range_box_id(self) -> None:
        with self.assertRaises(DropTableError):
            DropTable({0: DropPoint(0, 0)})
        with self.assertRaises(DropTableError):
            DropTable({7: DropPoint(0, 0)})

    def test_point_for_known_box_id(self) -> None:
        point = DropPoint(1200, -860)
        table = DropTable({1: point})
        self.assertEqual(point, table.point_for(1))

    def test_point_for_unknown_box_id_fails_closed(self) -> None:
        table = DropTable({1: DropPoint(0, 0)})
        with self.assertRaises(DropTableError):
            table.point_for(2)

    def test_point_for_rejects_bool_alias_for_box_one(self) -> None:
        table = DropTable({1: DropPoint(0, 0)})
        with self.assertRaises(DropTableError):
            table.point_for(True)


if __name__ == "__main__":
    unittest.main()
