"""
Tests for LSTM anomaly detection — rule-based checks, model loading, and detection accuracy.
"""
import pytest
import numpy as np
from app.ml.anomaly_detector import AnomalyDetector
from app.ml.lstm_model import VitalsNormalizer
from app.simulator.vitals_simulator import generate_vitals


# ── Vitals Normalizer ─────────────────────────────────────────────────────────

class TestVitalsNormalizer:
    def test_normal_vitals_normalize_to_0_1(self):
        normalizer = VitalsNormalizer()
        vitals = np.array([[75, 98, 120, 80, 36.8, 16]], dtype=np.float32)
        normalized = normalizer.normalize(vitals)
        assert normalized.shape == vitals.shape
        assert np.all(normalized >= 0)
        assert np.all(normalized <= 1)

    def test_boundary_values_clip_correctly(self):
        normalizer = VitalsNormalizer()
        # Values at clinical extremes
        extreme = np.array([[30, 70, 60, 40, 34.0, 6]], dtype=np.float32)
        normalized = normalizer.normalize(extreme)
        assert np.all(normalized >= 0)
        assert np.all(normalized <= 1)

    def test_denormalize_reverses_normalize(self):
        normalizer = VitalsNormalizer()
        original = np.array([[75, 98, 120, 80, 36.8, 16]], dtype=np.float32)
        normalized = normalizer.normalize(original)
        recovered = normalizer.denormalize(normalized)
        np.testing.assert_allclose(recovered, original, rtol=0.01)


# ── Rule-Based Detection ──────────────────────────────────────────────────────

class TestRuleBasedDetection:
    """
    Rule-based checks always run regardless of model availability.
    These are the clinical safety net.
    """

    def setup_method(self):
        self.detector = AnomalyDetector()

    def _make_vitals(self, **overrides):
        base = {
            "heart_rate": 75.0,
            "spo2": 98.0,
            "blood_pressure_sys": 120.0,
            "blood_pressure_dia": 80.0,
            "temperature": 36.8,
            "respiratory_rate": 16.0,
        }
        base.update(overrides)
        return base

    def test_normal_vitals_not_flagged(self):
        vitals = self._make_vitals()
        result = self.detector._rule_based_check(vitals)
        assert result is None

    def test_tachycardia_detected(self):
        vitals = self._make_vitals(heart_rate=145.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        anomaly_type, score = result
        assert anomaly_type == "tachycardia"
        assert 0 < score <= 1.0

    def test_bradycardia_detected(self):
        vitals = self._make_vitals(heart_rate=38.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "bradycardia"

    def test_hypoxia_detected(self):
        vitals = self._make_vitals(spo2=85.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "hypoxia"

    def test_hypertensive_crisis_detected(self):
        vitals = self._make_vitals(blood_pressure_sys=195.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "hypertensive_crisis"

    def test_hypotension_detected(self):
        vitals = self._make_vitals(blood_pressure_sys=78.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "hypotension"

    def test_fever_detected(self):
        vitals = self._make_vitals(temperature=39.2)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "fever"

    def test_hypothermia_detected(self):
        vitals = self._make_vitals(temperature=34.5)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "hypothermia"

    def test_tachypnea_detected(self):
        vitals = self._make_vitals(respiratory_rate=28.0)
        result = self.detector._rule_based_check(vitals)
        assert result is not None
        assert result[0] == "tachypnea"

    def test_severity_score_proportional_to_deviation(self):
        mild = self.detector._rule_based_check(self._make_vitals(heart_rate=132.0))
        severe = self.detector._rule_based_check(self._make_vitals(heart_rate=180.0))
        assert mild is not None and severe is not None
        assert mild[1] < severe[1]

    def test_severity_score_capped_at_1(self):
        extreme = self._make_vitals(heart_rate=250.0)
        result = self.detector._rule_based_check(extreme)
        assert result is not None
        assert result[1] <= 1.0


# ── Full Detection Pipeline ───────────────────────────────────────────────────

class TestDetectionPipeline:
    def setup_method(self):
        self.detector = AnomalyDetector()
        self.detector.load()

    def _make_vitals(self, **overrides):
        base = {
            "heart_rate": 75.0,
            "spo2": 98.0,
            "blood_pressure_sys": 120.0,
            "blood_pressure_dia": 80.0,
            "temperature": 36.8,
            "respiratory_rate": 16.0,
        }
        base.update(overrides)
        return base

    def test_detect_returns_three_values(self):
        vitals = self._make_vitals()
        result = self.detector.detect("test-patient-1", vitals)
        assert len(result) == 3
        is_anomaly, score, anomaly_type = result
        assert isinstance(is_anomaly, bool)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_normal_vitals_not_anomaly(self):
        for i in range(12):  # fill sliding window
            is_anomaly, score, _ = self.detector.detect("test-p-normal", self._make_vitals())
        assert not is_anomaly

    def test_tachycardia_always_detected(self):
        """Rule-based check catches this regardless of model."""
        vitals = self._make_vitals(heart_rate=155.0)
        is_anomaly, score, anomaly_type = self.detector.detect("test-p-tachy", vitals)
        assert is_anomaly is True
        assert anomaly_type == "tachycardia"
        assert score > 0

    def test_hypoxia_always_detected(self):
        vitals = self._make_vitals(spo2=85.0)
        is_anomaly, score, anomaly_type = self.detector.detect("test-p-hypoxia", vitals)
        assert is_anomaly is True
        assert anomaly_type == "hypoxia"

    def test_sliding_window_per_patient(self):
        """Each patient has an independent sliding window."""
        vitals = self._make_vitals()
        for _ in range(5):
            self.detector.detect("patient-a", vitals)
            self.detector.detect("patient-b", vitals)

        assert len(self.detector._windows["patient-a"]) == 5
        assert len(self.detector._windows["patient-b"]) == 5

    def test_window_max_length_is_10(self):
        vitals = self._make_vitals()
        for _ in range(15):
            self.detector.detect("test-p-window", vitals)
        assert len(self.detector._windows["test-p-window"]) == 10

    def test_anomaly_score_higher_for_worse_anomaly(self):
        mild_result = self.detector.detect("test-p-m", self._make_vitals(heart_rate=132.0))
        severe_result = self.detector.detect("test-p-s", self._make_vitals(heart_rate=180.0))
        assert severe_result[1] > mild_result[1]


# ── Simulator Data Quality ────────────────────────────────────────────────────

class TestSimulatorDataQuality:
    def test_normal_vitals_in_clinical_range(self):
        for _ in range(100):
            vitals = generate_vitals("test", time_offset=0, force_anomaly=None)
            assert 55 <= vitals["heart_rate"] <= 105
            assert 94 <= vitals["spo2"] <= 100
            assert 85 <= vitals["blood_pressure_sys"] <= 145
            assert 55 <= vitals["blood_pressure_dia"] <= 95
            assert 35.5 <= vitals["temperature"] <= 37.8
            assert 10 <= vitals["respiratory_rate"] <= 22

    def test_forced_tachycardia_in_range(self):
        for _ in range(20):
            vitals = generate_vitals("test", force_anomaly="tachycardia")
            assert vitals["heart_rate"] > 120

    def test_forced_hypoxia_in_range(self):
        for _ in range(20):
            vitals = generate_vitals("test", force_anomaly="hypoxia")
            assert vitals["spo2"] < 93

    def test_forced_fever_in_range(self):
        for _ in range(20):
            vitals = generate_vitals("test", force_anomaly="fever")
            assert vitals["temperature"] > 38.0

    def test_vitals_have_all_required_fields(self):
        vitals = generate_vitals("test")
        required = ["heart_rate", "spo2", "blood_pressure_sys",
                    "blood_pressure_dia", "temperature", "respiratory_rate",
                    "patient_id", "timestamp"]
        for field in required:
            assert field in vitals, f"Missing field: {field}"

    def test_anomaly_probability_is_realistic(self):
        """Less than 20% of readings should be anomalies in normal operation."""
        anomaly_count = sum(
            1 for _ in range(200)
            if generate_vitals("test")["simulated_anomaly"] is not None
        )
        anomaly_rate = anomaly_count / 200
        assert anomaly_rate < 0.20, f"Anomaly rate too high: {anomaly_rate:.1%}"