"""`sorting_vision.depth_fusion` 的单元测试。

覆盖 2026-10-26 重写后的表1 六类版本：
- PointCloudProfile 的构造校验与派生指标
- disambiguate_round()：圆柱 / 圆锥 / 中间地带 / 点太少
- requires_depth_disambiguation() / ambiguity_group_of()：只有圆柱与圆锥需要 ToF
- profile_from_raw_depths()：从 64 点原始距离算统计

⚠️ 阈值是理论值（未经实测）。这些测试锁的是**行为契约**，不是标定值：
   改阈值时这些测试仍然应该过（除了显式测边界的那几条）。
"""

import pytest

from sorting_vision.depth_fusion import (
    CONE_FLATNESS_MIN,
    CYLINDER_FLATNESS_MAX,
    MIN_POINTS,
    OBJECT_DEPTH_MARGIN_MM,
    ROUND_AMBIGUOUS_GROUP,
    PointCloudProfile,
    ambiguity_group_of,
    disambiguate_round,
    profile_from_raw_depths,
    requires_depth_disambiguation,
)


# ─────────────────────────────────────────────────────────────────────────────
# PointCloudProfile
# ─────────────────────────────────────────────────────────────────────────────


class TestPointCloudProfile:
    def test_construct_basic(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=0.4, diameter_mm=40.0)
        assert p.point_count == 6
        assert p.std_mm == pytest.approx(0.4)

    def test_diameter_optional(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=0.4)
        assert p.diameter_mm is None

    def test_negative_point_count_rejected(self):
        with pytest.raises(ValueError, match="point_count"):
            PointCloudProfile(
                point_count=-1, min_mm=250.0, max_mm=251.0,
                mean_mm=250.5, std_mm=0.4)

    def test_nan_rejected(self):
        with pytest.raises(ValueError, match="有限数"):
            PointCloudProfile(
                point_count=6, min_mm=float("nan"), max_mm=251.0,
                mean_mm=250.5, std_mm=0.4)

    def test_inf_rejected(self):
        with pytest.raises(ValueError, match="有限数"):
            PointCloudProfile(
                point_count=6, min_mm=250.0, max_mm=float("inf"),
                mean_mm=250.5, std_mm=0.4)

    def test_negative_std_rejected(self):
        with pytest.raises(ValueError, match="std_mm"):
            PointCloudProfile(
                point_count=6, min_mm=250.0, max_mm=251.0,
                mean_mm=250.5, std_mm=-0.1)

    def test_min_greater_than_max_rejected(self):
        with pytest.raises(ValueError, match="min_mm"):
            PointCloudProfile(
                point_count=6, min_mm=252.0, max_mm=251.0,
                mean_mm=251.5, std_mm=0.4)

    def test_nonpositive_diameter_rejected(self):
        with pytest.raises(ValueError, match="diameter_mm"):
            PointCloudProfile(
                point_count=6, min_mm=250.0, max_mm=251.0,
                mean_mm=250.5, std_mm=0.4, diameter_mm=0.0)

    def test_frozen(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=0.4, diameter_mm=40.0)
        with pytest.raises(Exception):
            p.std_mm = 1.0  # type: ignore[misc]


class TestDerivedMetrics:
    def test_flatness_with_diameter(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=2.0, diameter_mm=40.0)
        assert p.flatness() == pytest.approx(2.0 / 40.0)

    def test_flatness_without_diameter(self):
        """无直径时退化成裸 std。"""
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=2.0)
        assert p.flatness() == pytest.approx(2.0)

    def test_peak_to_peak(self):
        p = PointCloudProfile(
            point_count=6, min_mm=245.0, max_mm=262.0,
            mean_mm=253.0, std_mm=6.5, diameter_mm=40.0)
        assert p.peak_to_peak_mm() == pytest.approx(17.0)

    def test_peak_to_peak_zero_for_flat(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=250.0,
            mean_mm=250.0, std_mm=0.0, diameter_mm=40.0)
        assert p.peak_to_peak_mm() == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# disambiguate_round — 核心消歧
# ─────────────────────────────────────────────────────────────────────────────


class TestDisambiguateRound:
    def test_flat_top_is_cylinder(self):
        """顶面平坦（std/dia = 0.01）⇒ 圆柱。"""
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=0.4, diameter_mm=40.0)
        assert disambiguate_round(p) == "cylinder"

    def test_conical_gradient_is_cone(self):
        """锥形梯度（std/dia ≈ 0.16）⇒ 圆锥。"""
        p = PointCloudProfile(
            point_count=6, min_mm=245.0, max_mm=262.0,
            mean_mm=253.0, std_mm=6.5, diameter_mm=40.0)
        assert disambiguate_round(p) == "cone"

    def test_middle_band_returns_none(self):
        """中间地带（0.05 < flat < 0.12）⇒ 不下结论，调用方保留原判断。"""
        # std/dia = 3.2/40 = 0.08
        p = PointCloudProfile(
            point_count=6, min_mm=247.0, max_mm=257.0,
            mean_mm=252.0, std_mm=3.2, diameter_mm=40.0)
        flat = p.flatness()
        assert CYLINDER_FLATNESS_MAX < flat < CONE_FLATNESS_MIN
        assert disambiguate_round(p) is None

    def test_too_few_points_returns_none(self):
        """点数少于 MIN_POINTS ⇒ 不下结论。"""
        p = PointCloudProfile(
            point_count=MIN_POINTS - 1, min_mm=245.0, max_mm=262.0,
            mean_mm=253.0, std_mm=6.5, diameter_mm=40.0)
        assert disambiguate_round(p) is None

    def test_exactly_min_points_allowed(self):
        """恰好 MIN_POINTS 个点 ⇒ 允许下结论。"""
        p = PointCloudProfile(
            point_count=MIN_POINTS, min_mm=245.0, max_mm=262.0,
            mean_mm=253.0, std_mm=6.5, diameter_mm=40.0)
        assert disambiguate_round(p) == "cone"

    def test_zero_points_returns_none(self):
        p = PointCloudProfile(
            point_count=0, min_mm=0.0, max_mm=0.0,
            mean_mm=0.0, std_mm=0.0, diameter_mm=40.0)
        assert disambiguate_round(p) is None

    def test_flatness_exactly_at_cylinder_threshold(self):
        """flatness == CYLINDER_FLATNESS_MAX ⇒ 不满足 `< 阈值`，落到中间地带。"""
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=CYLINDER_FLATNESS_MAX * 40.0,
            diameter_mm=40.0)
        assert p.flatness() == pytest.approx(CYLINDER_FLATNESS_MAX)
        assert disambiguate_round(p) is None

    def test_flatness_exactly_at_cone_threshold(self):
        """flatness == CONE_FLATNESS_MIN ⇒ 不满足 `> 阈值`，落到中间地带。"""
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=CONE_FLATNESS_MIN * 40.0,
            diameter_mm=40.0)
        assert p.flatness() == pytest.approx(CONE_FLATNESS_MIN)
        assert disambiguate_round(p) is None

    def test_just_above_cone_threshold(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=CONE_FLATNESS_MIN * 40.0 + 0.5,
            diameter_mm=40.0)
        assert disambiguate_round(p) == "cone"

    def test_just_below_cylinder_threshold(self):
        p = PointCloudProfile(
            point_count=6, min_mm=250.0, max_mm=251.0,
            mean_mm=250.5, std_mm=CYLINDER_FLATNESS_MAX * 40.0 - 0.1,
            diameter_mm=40.0)
        assert disambiguate_round(p) == "cylinder"


# ─────────────────────────────────────────────────────────────────────────────
# 歧义组判定
# ─────────────────────────────────────────────────────────────────────────────


class TestAmbiguityGroup:
    @pytest.mark.parametrize("shape", ["cylinder", "cone"])
    def test_round_shapes_need_tof(self, shape):
        assert requires_depth_disambiguation(shape) is True
        assert ambiguity_group_of(shape) == ROUND_AMBIGUOUS_GROUP

    @pytest.mark.parametrize(
        "shape", ["cube", "cuboid", "pentagonal_prism", "tetrahedron"])
    def test_other_shapes_do_not_need_tof(self, shape):
        """表1 其余 4 类俯视轮廓唯一，不需要 ToF。"""
        assert requires_depth_disambiguation(shape) is False
        assert ambiguity_group_of(shape) is None

    def test_unknown_shape_not_ambiguous(self):
        assert requires_depth_disambiguation("banana") is False
        assert ambiguity_group_of("banana") is None

    def test_old_7class_shapes_no_longer_grouped(self):
        """旧 7 类的形状名在表1 里不存在，不应被判为歧义组。

        `triangular_prism` 用户已裁决删除；`square_pyramid` 已改名
        `tetrahedron`；`sphere` 表1 没有。
        """
        for legacy in ("triangular_prism", "square_pyramid", "sphere",
                       "hexagonal_prism"):
            assert requires_depth_disambiguation(legacy) is False


# ─────────────────────────────────────────────────────────────────────────────
# profile_from_raw_depths
# ─────────────────────────────────────────────────────────────────────────────


class TestProfileFromRawDepths:
    def test_all_points_object(self):
        """不给背景 ⇒ 所有有限正数都算物体点。"""
        depths = [250.0] * 64
        p = profile_from_raw_depths(depths, diameter_mm=40.0)
        assert p.point_count == 64
        assert p.std_mm == pytest.approx(0.0)
        assert p.flatness() == pytest.approx(0.0)

    def test_flat_cylinder_scenario(self):
        """圆柱：64 点都在 250±0.2 ⇒ flatness 极小 ⇒ 判圆柱。"""
        depths = []
        for i in range(64):
            depths.append(250.0 + (0.2 if i % 2 else -0.2))
        p = profile_from_raw_depths(depths, diameter_mm=40.0)
        assert p.point_count == 64
        assert disambiguate_round(p) == "cylinder"

    def test_cone_scenario(self):
        """圆锥：中心近边缘远 ⇒ std 大 ⇒ 判圆锥。

        构造：距离从 245（中心）到 262（边缘）均匀分布。
        """
        depths = [245.0 + (262.0 - 245.0) * i / 63.0 for i in range(64)]
        p = profile_from_raw_depths(depths, diameter_mm=40.0)
        flat = p.flatness()
        assert flat > CONE_FLATNESS_MIN
        assert disambiguate_round(p) == "cone"

    def test_nan_and_negative_ignored(self):
        depths = [250.0, 250.0, 250.0, float("nan"), -1.0, 0.0, None]
        p = profile_from_raw_depths(depths, diameter_mm=40.0)
        assert p.point_count == 3

    def test_empty_returns_zero_profile(self):
        p = profile_from_raw_depths([], diameter_mm=40.0)
        assert p.point_count == 0
        assert p.std_mm == pytest.approx(0.0)
        assert disambiguate_round(p) is None

    def test_background_filtering(self):
        """给背景距离 ⇒ 只保留显著更近的点（物体）。"""
        # 60 个背景点（300mm）+ 4 个物体点（250mm）
        depths = [300.0] * 60 + [250.0] * 4
        p = profile_from_raw_depths(
            depths, diameter_mm=40.0, background_mm=300.0)
        assert p.point_count == 4
        assert p.mean_mm == pytest.approx(250.0)

    def test_background_nothing_close_enough(self):
        """所有点都接近背景 ⇒ 没有物体点。"""
        depths = [300.0, 299.0, 298.0]
        p = profile_from_raw_depths(
            depths, diameter_mm=40.0, background_mm=300.0,
            margin_mm=OBJECT_DEPTH_MARGIN_MM)
        assert p.point_count == 0

    def test_negative_margin_rejected(self):
        with pytest.raises(ValueError, match="margin_mm"):
            profile_from_raw_depths([250.0], margin_mm=-1.0)

    def test_single_point_std_zero(self):
        p = profile_from_raw_depths([250.0], diameter_mm=40.0)
        assert p.point_count == 1
        assert p.std_mm == pytest.approx(0.0)

    def test_std_is_sample_std(self):
        """确认用的是样本标准差（n-1），不是总体标准差（n）。"""
        depths = [10.0, 20.0, 30.0]
        p = profile_from_raw_depths(depths)
        # 均值 20；样本方差 = (100+0+100)/2 = 100 ⇒ std = 10
        assert p.mean_mm == pytest.approx(20.0)
        assert p.std_mm == pytest.approx(10.0)
