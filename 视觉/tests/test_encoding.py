"""Tests for color and shape encoding."""

from __future__ import annotations

import pytest

from sorting_vision.encoding import (
    CODE_TO_COLOR,
    CODE_TO_SHAPE,
    COLOR_TO_CODE,
    SHAPE_TO_CODE,
    decode_color_shape,
    encode_color_shape,
    validate_encoding,
)


class TestColorShapeEncoding:
    """Test color and shape encoding/decoding."""

    def test_encode_red_cube(self):
        """Red cube should encode to 0."""
        assert encode_color_shape("red", "cube") == 0  # (0 << 4) | 0

    def test_encode_blue_cylinder(self):
        """Blue cylinder should encode to 82."""
        assert encode_color_shape("blue", "cylinder") == 82  # (5 << 4) | 2

    def test_encode_unknown_color(self):
        """Unknown color should encode to 15."""
        encoded = encode_color_shape("unknown", "cube")
        assert (encoded >> 4) == 15

    def test_encode_unknown_shape(self):
        """Unknown shape should encode to 15."""
        encoded = encode_color_shape("red", "unknown")
        assert (encoded & 0x0F) == 15

    def test_decode_zero(self):
        """Decoding 0 should give red cube."""
        assert decode_color_shape(0) == ("red", "cube")

    def test_decode_82(self):
        """Decoding 82 should give blue cylinder."""
        assert decode_color_shape(82) == ("blue", "cylinder")

    def test_round_trip_all_colors(self):
        """All colors should round-trip correctly."""
        for color in COLOR_TO_CODE:
            encoded = encode_color_shape(color, "cube")
            decoded_color, _ = decode_color_shape(encoded)
            assert decoded_color == color

    def test_round_trip_all_shapes(self):
        """All shapes should round-trip correctly."""
        for shape in SHAPE_TO_CODE:
            encoded = encode_color_shape("red", shape)
            _, decoded_shape = decode_color_shape(encoded)
            assert decoded_shape == shape

    def test_validate_encoding(self):
        """All combinations should validate."""
        assert validate_encoding() is True

    def test_color_code_range(self):
        """Color codes should be 0-15."""
        for code in COLOR_TO_CODE.values():
            assert 0 <= code <= 15

    def test_shape_code_range(self):
        """Shape codes should be 0-15."""
        for code in SHAPE_TO_CODE.values():
            assert 0 <= code <= 15

    def test_no_color_code_collision(self):
        """No two colors should have the same code."""
        codes = list(COLOR_TO_CODE.values())
        assert len(codes) == len(set(codes))

    def test_no_shape_code_collision(self):
        """No two shapes should have the same code."""
        codes = list(SHAPE_TO_CODE.values())
        assert len(codes) == len(set(codes))

    def test_reverse_mapping_completeness(self):
        """Reverse mappings should cover all codes."""
        for code in COLOR_TO_CODE.values():
            assert code in CODE_TO_COLOR

        for code in SHAPE_TO_CODE.values():
            assert code in CODE_TO_SHAPE

    def test_regular_tetrahedron_support(self):
        """Regular tetrahedron should be supported."""
        assert "regular_tetrahedron" in SHAPE_TO_CODE
        encoded = encode_color_shape("red", "regular_tetrahedron")
        _, shape = decode_color_shape(encoded)
        assert shape == "regular_tetrahedron"

    def test_encoded_value_range(self):
        """Encoded values should be 0-255."""
        for color in COLOR_TO_CODE:
            for shape in SHAPE_TO_CODE:
                encoded = encode_color_shape(color, shape)
                assert 0 <= encoded <= 255

    def test_invalid_color_defaults_to_unknown(self):
        """Invalid color should default to code 15."""
        encoded = encode_color_shape("invalid_color", "cube")
        color_code = (encoded >> 4) & 0x0F
        assert color_code == 15

    def test_invalid_shape_defaults_to_unknown(self):
        """Invalid shape should default to code 15."""
        encoded = encode_color_shape("red", "invalid_shape")
        shape_code = encoded & 0x0F
        assert shape_code == 15
