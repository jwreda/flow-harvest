"""
MFI Calculations - Mean Fluorescence Intensity calculations.

This module provides functions for calculating:
- Arithmetic mean
- Median
- Geometric mean (with handling for negative/zero values)
"""

import numpy as np
from scipy import stats
from typing import Union

ArrayLike = Union[np.ndarray, list]


def calculate_mean(values: ArrayLike) -> float:
    """
    Calculate arithmetic mean of values.

    Args:
        values: Array-like of numeric values

    Returns:
        Arithmetic mean, or NaN if empty
    """
    arr = np.asarray(values, dtype=np.float64)

    if len(arr) == 0:
        return np.nan

    return float(np.mean(arr))


def calculate_median(values: ArrayLike) -> float:
    """
    Calculate median of values.

    Args:
        values: Array-like of numeric values

    Returns:
        Median value, or NaN if empty
    """
    arr = np.asarray(values, dtype=np.float64)

    if len(arr) == 0:
        return np.nan

    return float(np.median(arr))


def calculate_geometric_mean(values: ArrayLike) -> float:
    """
    Calculate geometric mean of values.

    Handles negative and zero values by:
    - Filtering to positive values only
    - Returning NaN if no positive values exist

    Note: Geometric mean is commonly used in flow cytometry because
    fluorescence intensity data is typically log-normally distributed.

    Args:
        values: Array-like of numeric values

    Returns:
        Geometric mean of positive values, or NaN if no positive values
    """
    arr = np.asarray(values, dtype=np.float64)

    if len(arr) == 0:
        return np.nan

    # Filter to positive values (geometric mean undefined for <= 0)
    positive_values = arr[arr > 0]

    if len(positive_values) == 0:
        return np.nan

    # Use scipy's gmean for numerical stability
    return float(stats.gmean(positive_values))


def calculate_all_mfi(
    values: ArrayLike,
    include_mean: bool = True,
    include_median: bool = True,
    include_geomean: bool = True
) -> dict:
    """
    Calculate all MFI metrics at once.

    Args:
        values: Array-like of numeric values
        include_mean: Include arithmetic mean
        include_median: Include median
        include_geomean: Include geometric mean

    Returns:
        Dict with keys 'Mean', 'Median', 'GeoMean' as applicable
    """
    result = {}

    if include_mean:
        result['Mean'] = calculate_mean(values)

    if include_median:
        result['Median'] = calculate_median(values)

    if include_geomean:
        result['GeoMean'] = calculate_geometric_mean(values)

    return result
