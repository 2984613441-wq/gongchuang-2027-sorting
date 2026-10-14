"""Tests for depth-based shape disambiguation."""

import pytest

from sorting_vision.depth_fusion import (
    CUBE_RATIO,
    CYLINDER_HEIGHT_RATIO,
    PYRAMID_RATIO,
    SPHERE_HEIGHT_RATIO,
    TETRAHEDRON_RATIO,
    TRIANGULAR_PRISM_RATIO,
    DepthReading,
    depth_disambiguate,
    get_ambiguity_group,
    requires_depth_disambiguation,
)


class TestDepthReading:
    def test_create_depth_reading(self):
        reading = DepthReading(height_mm=50.0, confidence=0.95)
        assert reading.height_mm == 50.0
        assert reading.confidence == 0.95

    def test_depth_reading_frozen(self):
        reading = DepthReading(height_mm=50.0, confidence=0.95)
        with pytest.raises(AttributeError):
            reading.height_mm = 60.0  # type: ignore


class TestAmbiguityGroups:
    def test_cylinder_sphere_group(self):
        assert get_ambiguity_group("cylinder") == "cylinder_or_sphere"
        assert get_ambiguity_group("sphere") == "cylinder_or_sphere"

    def test_prism_tetrahedron_group(self):
        assert get_ambiguity_group("triangular_prism") == "triangular_prism_or_tetrahedron"
        assert get_ambiguity_group("regular_tetrahedron") == "triangular_prism_or_tetrahedron"

    def test_cube_pyramid_group(self):
        assert get_ambiguity_group("cube") == "cube_or_pyramid"
        assert get_ambiguity_group("square_pyramid") == "cube_or_pyramid"

    def test_unambiguous_shapes(self):
        assert get_ambiguity_group("cuboid") is None
        assert get_ambiguity_group("hexagonal_prism") is None
        assert get_ambiguity_group("pentagonal_prism") is None

    def test_requires_depth(self):
        assert requires_depth_disambiguation("cylinder")
        assert requires_depth_disambiguation("cube")
        assert requires_depth_disambiguation("triangular_prism")
        assert not requires_depth_disambiguation("cuboid")
        assert not requires_depth_disambiguation("hexagonal_prism")


class TestCylinderVsSphere:
    """Ambiguity group 1: Cylinder vs Sphere."""

    def test_tall_object_is_cylinder(self):
        """Height > 1.2 * width → cylinder."""
        depth = DepthReading(height_mm=65.0, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cylinder"

    def test_short_object_is_sphere(self):
        """Height < 0.8 * width → sphere."""
        depth = DepthReading(height_mm=35.0, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "sphere"

    def test_ambiguous_range_defaults_cylinder(self):
        """0.8 * width < height < 1.2 * width → default to YOLO (cylinder)."""
        depth = DepthReading(height_mm=50.0, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cylinder"

    def test_low_confidence_fallback(self):
        """Low ToF confidence → return YOLO shape."""
        depth = DepthReading(height_mm=35.0, confidence=0.5)  # < 0.7
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cylinder"  # Fallback, not "sphere"


class TestTriangularPrismVsTetrahedron:
    """Ambiguity group 2: Triangular prism vs Regular tetrahedron."""

    def test_tall_is_prism(self):
        """Height > 0.8 * width → triangular_prism."""
        depth = DepthReading(height_mm=45.0, confidence=0.95)
        result = depth_disambiguate("triangular_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "triangular_prism"

    def test_short_is_tetrahedron(self):
        """Height < 0.6 * width → regular_tetrahedron."""
        depth = DepthReading(height_mm=25.0, confidence=0.95)
        result = depth_disambiguate("triangular_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "regular_tetrahedron"

    def test_ambiguous_defaults_prism(self):
        depth = DepthReading(height_mm=35.0, confidence=0.95)
        result = depth_disambiguate("triangular_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "triangular_prism"


class TestCubeVsPyramid:
    """Ambiguity group 3: Cube vs Square pyramid."""

    def test_height_equals_width_is_cube(self):
        """Height ≈ width (within ±10%) → cube."""
        depth = DepthReading(height_mm=50.0, confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cube"

    def test_short_is_pyramid(self):
        """Height < 0.6 * width → square_pyramid."""
        depth = DepthReading(height_mm=25.0, confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "square_pyramid"

    def test_tall_defaults_cube(self):
        """Height > 1.1 * width → default to cube."""
        depth = DepthReading(height_mm=60.0, confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cube"


class TestUnambiguousShapes:
    def test_cuboid_unchanged(self):
        depth = DepthReading(height_mm=50.0, confidence=0.95)
        result = depth_disambiguate("cuboid", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cuboid"

    def test_hexagonal_prism_unchanged(self):
        depth = DepthReading(height_mm=50.0, confidence=0.95)
        result = depth_disambiguate("hexagonal_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "hexagonal_prism"


class TestPixelToMmConversion:
    def test_px_to_mm_scaling(self):
        """Verify pixel-to-mm conversion is applied."""
        depth = DepthReading(height_mm=60.0, confidence=0.95)
        # bbox_width=50px * 2.0 = 100mm base → 60/100=0.6 ratio → sphere
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=2.0)
        assert result == "sphere"

    def test_zero_width_fallback(self):
        """Zero bbox width → return YOLO shape."""
        depth = DepthReading(height_mm=50.0, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=0, depth_reading=depth, px_to_mm=1.0)
        assert result == "cylinder"


class TestThresholdBoundaries:
    """Test exact threshold boundaries (critical for correctness)."""

    def test_cylinder_threshold_exact(self):
        """Height = CYLINDER_HEIGHT_RATIO * width → still cylinder (>= check)."""
        depth = DepthReading(height_mm=50 * CYLINDER_HEIGHT_RATIO, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cylinder"

    def test_sphere_threshold_exact(self):
        """Height = SPHERE_HEIGHT_RATIO * width → still sphere (<= check)."""
        depth = DepthReading(height_mm=50 * SPHERE_HEIGHT_RATIO, confidence=0.95)
        result = depth_disambiguate("cylinder", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "sphere"

    def test_tetrahedron_threshold_exact(self):
        depth = DepthReading(height_mm=50 * TETRAHEDRON_RATIO, confidence=0.95)
        result = depth_disambiguate("triangular_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "regular_tetrahedron"

    def test_prism_threshold_exact(self):
        depth = DepthReading(height_mm=50 * TRIANGULAR_PRISM_RATIO, confidence=0.95)
        result = depth_disambiguate("triangular_prism", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "triangular_prism"

    def test_pyramid_threshold_exact(self):
        depth = DepthReading(height_mm=50 * PYRAMID_RATIO, confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "square_pyramid"

    def test_cube_lower_bound_exact(self):
        """Height = (1 - CUBE_RATIO) * width → still cube."""
        depth = DepthReading(height_mm=50 * (1.0 - CUBE_RATIO), confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cube"

    def test_cube_upper_bound_exact(self):
        """Height = (1 + CUBE_RATIO) * width → still cube."""
        depth = DepthReading(height_mm=50 * (1.0 + CUBE_RATIO), confidence=0.95)
        result = depth_disambiguate("cube", bbox_width_px=50, depth_reading=depth, px_to_mm=1.0)
        assert result == "cube"
