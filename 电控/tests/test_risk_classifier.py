"""Unit tests for risk classifier module."""

import pytest
from electrical_control.scheduler import RiskClassifier, RiskLevel, ObjectRisk


class TestRiskClassifier:
    """Test suite for RiskClassifier."""

    def test_classify_safe_object(self):
        """Test classification of high-confidence object with good history."""
        classifier = RiskClassifier()

        # First, build up success history for class 0
        classifier.class_success_rates[0] = 0.85  # Manually set high success rate

        obj = {
            'id': 1,
            'class_id': 0,
            'confidence': 0.90,
            'x': 100,
            'y': 100,
        }

        result = classifier.classify(obj)

        assert result.object_id == 1
        assert result.class_id == 0
        assert result.confidence == 0.90
        assert result.risk_level == RiskLevel.SAFE
        assert result.historical_success_rate == 0.85

    def test_classify_medium_object(self):
        """Test classification of medium-confidence object."""
        classifier = RiskClassifier()

        obj = {
            'id': 2,
            'class_id': 1,
            'confidence': 0.75,
            'x': 200,
            'y': 200,
        }

        result = classifier.classify(obj)

        assert result.risk_level == RiskLevel.MEDIUM

    def test_classify_risky_object(self):
        """Test classification of low-confidence object."""
        classifier = RiskClassifier()

        obj = {
            'id': 3,
            'class_id': 2,
            'confidence': 0.60,
            'x': 300,
            'y': 300,
        }

        result = classifier.classify(obj)

        assert result.risk_level == RiskLevel.RISKY

    def test_update_success_rate_on_success(self):
        """Test Bayesian update on successful pick."""
        classifier = RiskClassifier()
        class_id = 0

        initial_rate = classifier.get_success_rate(class_id)
        classifier.update_success_rate(class_id, success=True)
        updated_rate = classifier.get_success_rate(class_id)

        assert updated_rate > initial_rate
        assert 0.1 <= updated_rate <= 0.99

    def test_update_success_rate_on_failure(self):
        """Test Bayesian update on failed pick."""
        classifier = RiskClassifier()
        class_id = 0

        initial_rate = classifier.get_success_rate(class_id)
        classifier.update_success_rate(class_id, success=False)
        updated_rate = classifier.get_success_rate(class_id)

        assert updated_rate < initial_rate
        assert 0.1 <= updated_rate <= 0.99

    def test_distance_calculation(self):
        """Test distance estimation."""
        classifier = RiskClassifier(current_position=(0, 0))

        obj = {
            'id': 1,
            'class_id': 0,
            'confidence': 0.85,
            'x': 100,  # 10mm
            'y': 100,  # 10mm
        }

        result = classifier.classify(obj)

        # Distance should be sqrt(10^2 + 10^2) = 14.14mm
        # Time = 14.14/50 + 2.0 + 0.5 = 2.78s (with Z-axis time)
        assert 2.7 < result.estimated_time_s < 2.9

    def test_update_position(self):
        """Test position update for distance calculations."""
        classifier = RiskClassifier(current_position=(0, 0))

        classifier.update_position((100, 100))

        assert classifier.current_position == (100, 100)

    def test_reset_class_rates(self):
        """Test resetting all class success rates."""
        classifier = RiskClassifier()

        classifier.update_success_rate(0, True)
        classifier.update_success_rate(1, False)

        assert len(classifier.class_success_rates) == 2

        classifier.reset_class_rates()

        assert len(classifier.class_success_rates) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
