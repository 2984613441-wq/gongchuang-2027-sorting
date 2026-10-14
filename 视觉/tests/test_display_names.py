"""Tests for display name mapping and formatting."""

from sorting_vision.display_names import (
    COLOR_NAMES_ZH,
    SHAPE_NAMES_ZH,
    format_item_name,
    get_color_display_name,
    get_shape_display_name,
)


class TestShapeNames:
    def test_all_seven_classes_covered(self):
        """All 7 YOLO classes have Chinese translations."""
        expected = {
            "cube",
            "cuboid",
            "cylinder",
            "hexagonal_prism",
            "pentagonal_prism",
            "square_pyramid",
            "triangular_prism",
        }
        assert set(SHAPE_NAMES_ZH.keys()) == expected

    def test_no_empty_translations(self):
        """No empty Chinese strings."""
        for zh in SHAPE_NAMES_ZH.values():
            assert zh.strip(), "Empty translation found"

    def test_get_shape_display_name(self):
        assert get_shape_display_name("cube") == "正方体"
        assert get_shape_display_name("cylinder") == "圆柱"
        assert get_shape_display_name("triangular_prism") == "三棱柱"

    def test_unknown_shape_returns_english(self):
        """Unknown shapes fall back to English."""
        assert get_shape_display_name("unknown") == "unknown"
        assert get_shape_display_name("sphere") == "sphere"


class TestColorNames:
    def test_eleven_colors_covered(self):
        """All 11 color vocabulary entries have translations."""
        expected = {
            "red",
            "orange",
            "yellow",
            "green",
            "cyan",
            "blue",
            "purple",
            "pink",
            "black",
            "white",
            "gray",
        }
        assert set(COLOR_NAMES_ZH.keys()) == expected

    def test_no_empty_translations(self):
        for zh in COLOR_NAMES_ZH.values():
            assert zh.strip()

    def test_get_color_display_name(self):
        assert get_color_display_name("red") == "红"
        assert get_color_display_name("cyan") == "青"
        assert get_color_display_name("black") == "黑"

    def test_unknown_color_returns_english(self):
        assert get_color_display_name("unknown") == "unknown"
        assert get_color_display_name("magenta") == "magenta"


class TestFormatItemName:
    def test_basic_formatting(self):
        """Standard color+shape combinations."""
        assert format_item_name("red", "cube") == "红正方体"
        assert format_item_name("cyan", "cylinder") == "青圆柱"
        assert format_item_name("green", "cuboid") == "绿长方体"

    def test_with_separator(self):
        """Custom separator between color and shape."""
        assert format_item_name("red", "cube", separator=" ") == "红 正方体"
        assert format_item_name("blue", "cylinder", separator="-") == "蓝-圆柱"

    def test_unknown_color_fallback(self):
        """Unknown color uses English."""
        assert format_item_name("magenta", "cube") == "magenta正方体"

    def test_unknown_shape_fallback(self):
        """Unknown shape uses English."""
        assert format_item_name("red", "sphere") == "红sphere"

    def test_both_unknown_fallback(self):
        """Both unknown uses full English."""
        assert format_item_name("unknown", "unknown") == "unknownunknown"

    def test_empty_separator(self):
        """Default separator is empty string."""
        result = format_item_name("red", "cube")
        assert " " not in result
        assert result == "红正方体"
