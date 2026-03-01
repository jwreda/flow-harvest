"""
Tests for ExportConfig validation.

Ensures that invalid field combinations raise ValueError during construction.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from flowkit_gui.exporters.export_config import ExportConfig


class TestExportConfigValidation:
    """Tests for ExportConfig __post_init__ validation."""

    def test_bead_normalize_without_gate_raises(self):
        """bead_normalize=True without bead_gate_id should raise ValueError."""
        with pytest.raises(ValueError, match="bead_normalize=True requires bead_gate_id"):
            ExportConfig(bead_normalize=True, bead_gate_id=None)

    def test_bead_normalize_with_empty_string_gate_raises(self):
        """bead_normalize=True with empty string bead_gate_id should raise ValueError."""
        with pytest.raises(ValueError, match="bead_normalize=True requires bead_gate_id"):
            ExportConfig(bead_normalize=True, bead_gate_id="")

    def test_bead_normalize_with_gate_passes(self):
        """bead_normalize=True with a valid bead_gate_id should not raise."""
        config = ExportConfig(bead_normalize=True, bead_gate_id="Beads")
        assert config.bead_normalize is True
        assert config.bead_gate_id == "Beads"

    def test_volume_normalize_zero_denominator_raises(self):
        """volume_normalize=True with zero denominator should raise ValueError."""
        with pytest.raises(ValueError, match="volume_denominator must be positive"):
            ExportConfig(volume_normalize=True, volume_denominator=0.0)

    def test_volume_normalize_negative_denominator_raises(self):
        """volume_normalize=True with negative denominator should raise ValueError."""
        with pytest.raises(ValueError, match="volume_denominator must be positive"):
            ExportConfig(volume_normalize=True, volume_denominator=-10.0)

    def test_volume_normalize_positive_denominator_passes(self):
        """volume_normalize=True with positive denominator should not raise."""
        config = ExportConfig(volume_normalize=True, volume_denominator=100.0)
        assert config.volume_normalize is True
        assert config.volume_denominator == 100.0

    def test_bead_normalize_zero_user_number_raises(self):
        """bead_normalize=True with zero bead_user_number should raise ValueError."""
        with pytest.raises(ValueError, match="bead_user_number must be positive"):
            ExportConfig(bead_normalize=True, bead_gate_id="Beads", bead_user_number=0.0)

    def test_bead_normalize_negative_user_number_raises(self):
        """bead_normalize=True with negative bead_user_number should raise ValueError."""
        with pytest.raises(ValueError, match="bead_user_number must be positive"):
            ExportConfig(bead_normalize=True, bead_gate_id="Beads", bead_user_number=-500.0)

    def test_bead_normalize_positive_user_number_passes(self):
        """bead_normalize=True with positive bead_user_number should not raise."""
        config = ExportConfig(bead_normalize=True, bead_gate_id="Beads", bead_user_number=1000.0)
        assert config.bead_user_number == 1000.0

    def test_defaults_pass_validation(self):
        """Default ExportConfig should pass all validation (no normalization enabled)."""
        config = ExportConfig()
        assert config.bead_normalize is False
        assert config.volume_normalize is False

    def test_volume_not_normalized_ignores_denominator(self):
        """When volume_normalize=False, denominator value is not validated."""
        config = ExportConfig(volume_normalize=False, volume_denominator=-999.0)
        assert config.volume_denominator == -999.0

    def test_bead_not_normalized_ignores_gate(self):
        """When bead_normalize=False, bead_gate_id None is fine."""
        config = ExportConfig(bead_normalize=False, bead_gate_id=None)
        assert config.bead_gate_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
