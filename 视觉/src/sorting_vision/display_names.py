"""Display name mapping and formatting for the vision subsystem.

Provides Chinese translations and human-readable formatting for shape/color
labels, required by competition rules where display errors = 0 points for
that item.
"""

from __future__ import annotations

from typing import Mapping

# Shape class names (English) to Chinese display names
# Matches the 7-class YOLO model vocabulary (models/labels_yolo5s_geom7c.txt)
SHAPE_NAMES_ZH: Mapping[str, str] = {
    "cube": "正方体",
    "cuboid": "长方体",
    "cylinder": "圆柱",
    "hexagonal_prism": "六棱柱",
    "pentagonal_prism": "五棱柱",
    "square_pyramid": "四棱锥",
    "triangular_prism": "三棱柱",
}

# Color vocabulary (Chinese)
# Matches sorting_vision/sort_plan.py DEFAULT_COLOR_VOCABULARY
COLOR_NAMES_ZH: Mapping[str, str] = {
    "red": "红",
    "orange": "橙",
    "yellow": "黄",
    "green": "绿",
    "cyan": "青",
    "blue": "蓝",
    "purple": "紫",
    "pink": "粉",
    "black": "黑",
    "white": "白",
    "gray": "灰",
}


def format_item_name(color: str, shape: str, *, separator: str = "") -> str:
    """Format a human-readable item name from color and shape labels.

    Args:
        color: Color label (English, from color_quant module).
        shape: Shape label (English, from YOLO class_id or shape_features).
        separator: Optional separator between color and shape (default: "").

    Returns:
        Formatted Chinese name, e.g. "红正方体" or "青圆柱".
        If color/shape not in vocabulary, returns English fallback.

    Examples:
        >>> format_item_name("red", "cube")
        '红正方体'
        >>> format_item_name("cyan", "cylinder")
        '青圆柱'
        >>> format_item_name("green", "cuboid", separator=" ")
        '绿 长方体'
    """
    color_zh = COLOR_NAMES_ZH.get(color, color)
    shape_zh = SHAPE_NAMES_ZH.get(shape, shape)
    return f"{color_zh}{separator}{shape_zh}"


def get_shape_display_name(shape: str) -> str:
    """Get Chinese display name for a shape label.

    Args:
        shape: English shape label (from YOLO or shape_features).

    Returns:
        Chinese name, or original English if not in vocabulary.
    """
    return SHAPE_NAMES_ZH.get(shape, shape)


def get_color_display_name(color: str) -> str:
    """Get Chinese display name for a color label.

    Args:
        color: English color label (from color_quant).

    Returns:
        Chinese name, or original English if not in vocabulary.
    """
    return COLOR_NAMES_ZH.get(color, color)
