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

    Returns NaN if any value is non-positive (≤ 0), since geometric mean
    is mathematically undefined for such values.

    Note: Geometric mean is commonly used in flow cytometry because
    fluorescence intensity data is typically log-normally distributed.

    Args:
        values: Array-like of numeric values

    Returns:
        Geometric mean, or NaN if empty or any value is non-positive
    """
    arr = np.asarray(values, dtype=np.float64)

    if len(arr) == 0:
        return np.nan

    # Return NaN if any non-positive values (geometric mean undefined for <= 0)
    if np.any(arr <= 0):
        return np.nan

    # Use scipy's gmean for numerical stability
    return float(stats.gmean(arr))


def explain_geometric_mean_result(values: ArrayLike) -> str:
    """
    Explain why geometric mean might return NaN.

    This function analyzes an array of values and returns an explanation
    for why calculate_geometric_mean would return NaN (if it would).

    Args:
        values: Array-like of numeric values

    Returns:
        Explanation string, or empty string if gMFI is valid
    """
    arr = np.asarray(values, dtype=np.float64)

    if len(arr) == 0:
        return "Geometric mean is undefined for empty data"

    n_negative = int(np.sum(arr < 0))
    n_zero = int(np.sum(arr == 0))
    n_nonpositive = n_negative + n_zero

    if n_nonpositive > 0:
        pct_nonpositive = (n_nonpositive / len(arr)) * 100
        return (
            f"Geometric mean is undefined for non-positive values. "
            f"Data contains {n_nonpositive} non-positive values ({pct_nonpositive:.1f}%): "
            f"{n_negative} negative, {n_zero} zero. "
            f"Consider using Median instead."
        )

    return ""


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


def calculate_all_mfi_optimized(
    values: ArrayLike,
    include_mean: bool = True,
    include_median: bool = True,
    include_geomean: bool = True
) -> dict:
    """
    Calculate all MFI metrics with minimized array operations.

    This optimized version:
    - Converts to numpy array only once
    - Filters positive values only once (for geomean)
    - Avoids redundant array copies

    Args:
        values: Array-like of numeric values
        include_mean: Include arithmetic mean
        include_median: Include median
        include_geomean: Include geometric mean

    Returns:
        Dict with keys 'Mean', 'Median', 'GeoMean' as applicable
    """
    # Single array conversion
    arr = np.asarray(values, dtype=np.float64)

    result = {}

    if len(arr) == 0:
        if include_mean:
            result['Mean'] = np.nan
        if include_median:
            result['Median'] = np.nan
        if include_geomean:
            result['GeoMean'] = np.nan
        return result

    # Calculate mean and median on full array
    if include_mean:
        result['Mean'] = float(np.mean(arr))

    if include_median:
        result['Median'] = float(np.median(arr))

    # Geometric mean requires all positive values
    if include_geomean:
        if np.any(arr <= 0):
            result['GeoMean'] = np.nan
        else:
            result['GeoMean'] = float(stats.gmean(arr))

    return result
