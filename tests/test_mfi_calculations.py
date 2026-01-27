"""
Tests for MFI calculations.
"""

import pytest
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from flowkit_gui.utils.mfi_calculations import (
    calculate_mean, calculate_median, calculate_geometric_mean, calculate_all_mfi
)


class TestCalculateMean:
    """Tests for calculate_mean function."""

    def test_basic_mean(self):
        """Test basic mean calculation."""
        values = [1, 2, 3, 4, 5]
        result = calculate_mean(values)
        assert result == 3.0

    def test_mean_with_numpy_array(self):
        """Test mean with numpy array input."""
        values = np.array([10, 20, 30])
        result = calculate_mean(values)
        assert result == 20.0

    def test_mean_with_floats(self):
        """Test mean with float values."""
        values = [1.5, 2.5, 3.5]
        result = calculate_mean(values)
        assert result == 2.5

    def test_mean_empty_array(self):
        """Test mean of empty array returns NaN."""
        result = calculate_mean([])
        assert np.isnan(result)

    def test_mean_single_value(self):
        """Test mean of single value."""
        result = calculate_mean([42])
        assert result == 42.0

    def test_mean_with_negative_values(self):
        """Test mean with negative values."""
        values = [-10, 0, 10]
        result = calculate_mean(values)
        assert result == 0.0


class TestCalculateMedian:
    """Tests for calculate_median function."""

    def test_basic_median_odd(self):
        """Test median with odd number of values."""
        values = [1, 3, 5, 7, 9]
        result = calculate_median(values)
        assert result == 5.0

    def test_basic_median_even(self):
        """Test median with even number of values."""
        values = [1, 2, 3, 4]
        result = calculate_median(values)
        assert result == 2.5

    def test_median_empty_array(self):
        """Test median of empty array returns NaN."""
        result = calculate_median([])
        assert np.isnan(result)

    def test_median_single_value(self):
        """Test median of single value."""
        result = calculate_median([42])
        assert result == 42.0

    def test_median_unsorted(self):
        """Test median with unsorted input."""
        values = [5, 1, 4, 2, 3]
        result = calculate_median(values)
        assert result == 3.0


class TestCalculateGeometricMean:
    """Tests for calculate_geometric_mean function."""

    def test_basic_geomean(self):
        """Test basic geometric mean calculation."""
        values = [1, 2, 4, 8]
        result = calculate_geometric_mean(values)
        # Geometric mean of [1, 2, 4, 8] = (1*2*4*8)^(1/4) = 64^0.25 = 2.83...
        assert abs(result - 2.8284271247) < 0.0001

    def test_geomean_equal_values(self):
        """Test geometric mean with equal values."""
        values = [5, 5, 5, 5]
        result = calculate_geometric_mean(values)
        assert abs(result - 5.0) < 0.0001

    def test_geomean_empty_array(self):
        """Test geometric mean of empty array returns NaN."""
        result = calculate_geometric_mean([])
        assert np.isnan(result)

    def test_geomean_with_zeros(self):
        """Test geometric mean returns NaN when zeros present."""
        values = [0, 1, 2, 4]
        result = calculate_geometric_mean(values)
        assert np.isnan(result)

    def test_geomean_with_negatives(self):
        """Test geometric mean returns NaN when negative values present."""
        values = [-5, -3, 1, 2, 4]
        result = calculate_geometric_mean(values)
        assert np.isnan(result)

    def test_geomean_all_negative(self):
        """Test geometric mean returns NaN when all values are non-positive."""
        values = [-5, -3, 0]
        result = calculate_geometric_mean(values)
        assert np.isnan(result)

    def test_geomean_single_positive(self):
        """Test geometric mean with single positive value."""
        result = calculate_geometric_mean([42])
        assert abs(result - 42.0) < 0.0001


class TestCalculateAllMFI:
    """Tests for calculate_all_mfi function."""

    def test_all_metrics(self):
        """Test calculating all metrics at once."""
        values = [1, 2, 3, 4, 5]
        result = calculate_all_mfi(values)

        assert 'Mean' in result
        assert 'Median' in result
        assert 'GeoMean' in result

        assert result['Mean'] == 3.0
        assert result['Median'] == 3.0

    def test_selective_metrics(self):
        """Test calculating selective metrics."""
        values = [1, 2, 3, 4, 5]
        result = calculate_all_mfi(values, include_mean=True, include_median=False, include_geomean=False)

        assert 'Mean' in result
        assert 'Median' not in result
        assert 'GeoMean' not in result

    def test_no_metrics_selected(self):
        """Test with no metrics selected returns empty dict."""
        values = [1, 2, 3]
        result = calculate_all_mfi(values, include_mean=False, include_median=False, include_geomean=False)

        assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
