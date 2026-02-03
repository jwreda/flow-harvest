"""
Tests for Statistics Model - focusing on low event count warnings.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from unittest.mock import Mock, MagicMock, patch

from flowkit_gui.models.statistics_model import (
    StatisticsModel, MFIMetric, GateStatistics,
    LOW_EVENT_WARNING_THRESHOLD, MODERATE_EVENT_WARNING_THRESHOLD
)
from flowkit_gui.models.workspace_model import Sample, GateInfo, DataSource


def create_mock_sample(sample_id, name, event_count=10000):
    """Create a mock sample."""
    return Sample(
        sample_id=sample_id,
        name=name,
        fcs_path=None,
        group="",
        keywords={},
        event_count=event_count
    )


def create_mock_workspace(samples, gate_stats_map=None, events_df=None):
    """
    Create a mock workspace with configurable gate statistics.

    Args:
        samples: List of Sample objects
        gate_stats_map: Dict mapping (sample_id, gate_id) -> {'count': n, 'percent_parent': p}
        events_df: DataFrame to return from get_gated_events (or None)
    """
    mock_workspace = Mock()
    mock_workspace.samples = samples

    def get_gate_statistics(sample_id, gate_id):
        if gate_stats_map and (sample_id, gate_id) in gate_stats_map:
            return gate_stats_map[(sample_id, gate_id)]
        return {'count': 100, 'percent_parent': 50.0, 'percent_total': 10.0}

    mock_workspace.get_gate_statistics = Mock(side_effect=get_gate_statistics)
    mock_workspace.has_fcs_data = Mock(return_value=True)
    mock_workspace.get_gated_events = Mock(return_value=events_df)

    return mock_workspace


class TestLowEventCountWarnings:
    """Tests for low event count warning functionality."""

    def test_low_event_count_warning_threshold(self):
        """Verify the threshold constants are set correctly."""
        assert LOW_EVENT_WARNING_THRESHOLD == 10
        assert MODERATE_EVENT_WARNING_THRESHOLD == 50
        assert LOW_EVENT_WARNING_THRESHOLD < MODERATE_EVENT_WARNING_THRESHOLD

    def test_low_event_count_generates_warning(self):
        """Test that gates with very few events (<10) generate warnings."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with only 5 events
        gate_stats_map = {
            ('S1', 'LowEventGate'): {'count': 5, 'percent_parent': 1.0, 'percent_total': 0.1}
        }

        # Create events DataFrame with data
        events_df = pd.DataFrame({
            'Ki67': [100.0, 200.0, 300.0, 400.0, 500.0]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['LowEventGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Should have a warning about low event count
        assert len(warnings) > 0
        assert any('only 5 events' in w for w in warnings)
        assert any('unreliable' in w for w in warnings)

    def test_moderate_event_count_no_strong_warning(self):
        """Test that gates with 10-49 events don't get 'unreliable' warning."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with 30 events
        gate_stats_map = {
            ('S1', 'ModerateGate'): {'count': 30, 'percent_parent': 5.0, 'percent_total': 1.0}
        }

        events_df = pd.DataFrame({
            'Ki67': [float(i) for i in range(30)]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['ModerateGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Should NOT have "unreliable" warning for moderate counts
        assert not any('unreliable' in w for w in warnings)

    def test_sufficient_events_no_warning(self):
        """Test that gates with >= 50 events don't generate event count warnings."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with 100 events
        gate_stats_map = {
            ('S1', 'NormalGate'): {'count': 100, 'percent_parent': 20.0, 'percent_total': 5.0}
        }

        events_df = pd.DataFrame({
            'Ki67': [float(i) for i in range(100)]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['NormalGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Should not have any event count related warnings
        assert not any('events' in w.lower() and 'unreliable' in w.lower() for w in warnings)

    def test_zero_events_no_low_count_warning(self):
        """Test that zero events don't trigger low count warning (separate error)."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with 0 events
        gate_stats_map = {
            ('S1', 'EmptyGate'): {'count': 0, 'percent_parent': 0.0, 'percent_total': 0.0}
        }

        mock_workspace = create_mock_workspace(samples, gate_stats_map, None)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['EmptyGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Should NOT have "unreliable" warning for 0 events (different handling)
        assert not any('unreliable' in w for w in warnings)

    def test_boundary_at_threshold(self):
        """Test that exactly 10 events doesn't trigger strong warning."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with exactly 10 events (at threshold)
        gate_stats_map = {
            ('S1', 'BoundaryGate'): {'count': 10, 'percent_parent': 2.0, 'percent_total': 0.5}
        }

        events_df = pd.DataFrame({
            'Ki67': [float(i) for i in range(10)]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['BoundaryGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Exactly 10 events should NOT trigger "unreliable" (threshold is <10)
        assert not any('unreliable' in w for w in warnings)

    def test_boundary_at_moderate_threshold(self):
        """Test that exactly 50 events doesn't trigger moderate warning."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        # Create gate stats with exactly 50 events
        gate_stats_map = {
            ('S1', 'ModerateGate'): {'count': 50, 'percent_parent': 10.0, 'percent_total': 2.0}
        }

        events_df = pd.DataFrame({
            'Ki67': [float(i) for i in range(50)]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['ModerateGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.MEDIAN]
        )

        warnings = model.get_warnings()
        # Exactly 50 events is at threshold, no warning should be generated
        # (warnings are for < 50, not <= 50)
        assert len(warnings) == 0 or not any('caution' in w.lower() for w in warnings)


class TestGMFINaNExplanationIntegration:
    """Tests for gMFI NaN explanation integration in StatisticsModel."""

    def test_gmfi_nan_logs_explanation(self):
        """Test that gMFI NaN triggers explanation logging."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        gate_stats_map = {
            ('S1', 'TestGate'): {'count': 100, 'percent_parent': 50.0, 'percent_total': 10.0}
        }

        # Events with negative values - will cause gMFI to be NaN
        events_df = pd.DataFrame({
            'Ki67': [100.0, 200.0, -50.0, 300.0, 400.0]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)

        # Patch the logger to capture log calls
        with patch('flowkit_gui.models.statistics_model.logger') as mock_logger:
            model.calculate_statistics(
                gate_ids=['TestGate'],
                channels=['Ki67'],
                metrics=[MFIMetric.GEOMETRIC_MEAN]
            )

            # Check that logger.info was called with gMFI explanation
            info_calls = [str(call) for call in mock_logger.info.call_args_list]
            # Should have logged explanation about NaN
            assert any('gMFI NaN' in str(call) for call in info_calls) or \
                   any('non-positive' in str(call) for call in info_calls)

    def test_gmfi_valid_no_explanation(self):
        """Test that valid gMFI doesn't trigger explanation logging."""
        samples = [create_mock_sample('S1', 'Sample 1')]

        gate_stats_map = {
            ('S1', 'TestGate'): {'count': 100, 'percent_parent': 50.0, 'percent_total': 10.0}
        }

        # Events with all positive values - gMFI will be valid
        events_df = pd.DataFrame({
            'Ki67': [100.0, 200.0, 300.0, 400.0, 500.0]
        })

        mock_workspace = create_mock_workspace(samples, gate_stats_map, events_df)

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics(
            gate_ids=['TestGate'],
            channels=['Ki67'],
            metrics=[MFIMetric.GEOMETRIC_MEAN]
        )

        # Get the calculated stats
        stats = model.get_gate_statistics('S1', 'TestGate')
        assert stats is not None
        assert 'Ki67' in stats.mfi_values
        # gMFI should be a valid number, not NaN
        gmfi_value = stats.mfi_values['Ki67'].get('GeoMean')
        assert gmfi_value is not None
        assert not np.isnan(gmfi_value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
