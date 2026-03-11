"""
Statistics Model - Calculate and aggregate gate statistics and MFI values.

This module provides:
- Gate statistics calculation (count, percent)
- MFI calculations (mean, median, geometric mean)
- Statistics aggregation across samples and gates
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import multiprocessing
import threading
import gc
import pandas as pd
import numpy as np

from .workspace_model import WorkspaceModel, Sample, DataSource
from ..utils.mfi_calculations import (
    calculate_mean, calculate_median, calculate_geometric_mean,
    calculate_all_mfi_optimized, explain_geometric_mean_result
)
from ..utils.logging_config import get_logger
from ..utils.cancellation import CancellationToken, CancellationError
from ..utils.timing import timed_operation
from ..config import defaults as config_defaults

logger = get_logger("statistics_model")

# Event count thresholds for warnings
LOW_EVENT_WARNING_THRESHOLD = 10
MODERATE_EVENT_WARNING_THRESHOLD = 50


class MFIMetric(Enum):
    """MFI metric types."""
    MEAN = "Mean"
    MEDIAN = "Median"
    GEOMETRIC_MEAN = "GeoMean"


class FrequencyDataType(Enum):
    """Frequency data output types."""
    BOTH = "both"       # Both count and percent (original behavior)
    COUNTS = "counts"   # Raw event counts only
    PERCENT = "percent" # Percentage data only


@dataclass
class GateStatistics:
    """Statistics for a single gate on a single sample."""
    sample_id: str
    gate_id: str
    gate_path: str

    # Core statistics
    event_count: int = 0
    percent_of_parent: float = 0.0
    percent_of_total: float = 0.0

    # MFI values keyed by channel name
    mfi_values: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Structure: {"channel_name": {"Mean": value, "Median": value, "GeoMean": value}}

    # Error tracking
    error_message: Optional[str] = None


class StatisticsModel:
    """
    Model for calculating and aggregating statistics.

    Handles:
    - Per-gate, per-sample statistics
    - MFI calculations for selected channels
    - Aggregation into exportable DataFrames
    """

    def __init__(self, workspace: WorkspaceModel, data_source: DataSource = DataSource.AUTO):
        self._workspace = workspace
        self._data_source = data_source
        self._statistics: Dict[str, Dict[str, GateStatistics]] = {}
        # Structure: {sample_id: {gate_id: GateStatistics}}
        self._warnings: List[str] = []  # Collect warnings during calculation
        self._warnings_lock = threading.Lock()  # Protects _warnings in parallel mode
        self._normalized_counts_df: Optional[pd.DataFrame] = None  # Volume-normalized counts
        self._bead_normalized_df: Optional[pd.DataFrame] = None  # Bead-normalized counts

    def calculate_statistics(
        self,
        gate_ids: List[str],
        channels: List[str],
        metrics: List[MFIMetric],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        sample_ids: Optional[List[str]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> None:
        """
        Calculate statistics for specified gates and channels.

        Args:
            gate_ids: List of gate IDs to calculate stats for
            channels: List of channel names for MFI calculation
            metrics: List of MFI metrics to calculate
            progress_callback: Optional callback(current, total) for progress
            sample_ids: Optional list of sample IDs to include (None = all samples)
            status_callback: Optional callback(message) for status updates
            cancellation_token: Optional token to support cancellation

        Raises:
            CancellationError: If cancellation_token is cancelled
        """
        self._statistics.clear()
        self._warnings.clear()

        # Filter samples if sample_ids provided
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in self._workspace.samples if s.sample_id in sample_id_set]
        else:
            samples = self._workspace.samples

        # Store which samples we're processing for later use
        self._included_samples = samples
        total_work = len(samples) * len(gate_ids)
        current = 0

        logger.info(f"Calculating statistics for {len(samples)} samples, {len(gate_ids)} gates, {len(channels)} channels")
        logger.debug(f"Data source: {self._data_source.value}")

        samples_with_errors = 0
        successful_calcs = 0

        # Context for timing
        context = f"{len(samples)} samples, {len(gate_ids)} gates, {len(channels)} channels"

        with timed_operation("Statistics calculation", context):
            for sample_idx, sample in enumerate(samples):
                # Check for cancellation at each sample boundary
                if cancellation_token:
                    cancellation_token.check_cancelled()

                sample_id = sample.sample_id
                self._statistics[sample_id] = {}

                # Report sample progress
                if status_callback:
                    status_callback(f"Processing sample {sample_idx + 1}/{len(samples)}: {sample.name}")

                # Check if sample has FCS data
                if not self._workspace.has_fcs_data(sample_id):
                    logger.warning(f"Sample '{sample_id}' has no FCS data - skipping MFI calculations")
                    self._warnings.append(f"Sample '{sample.name}': No FCS data available")

                for gate_id in gate_ids:
                    # Get gate statistics
                    stats = self._calculate_gate_stats(sample_id, gate_id, channels, metrics)
                    self._statistics[sample_id][gate_id] = stats

                    if stats.error_message:
                        samples_with_errors += 1
                    elif stats.mfi_values:
                        successful_calcs += 1

                    current += 1
                    if progress_callback:
                        progress_callback(current, total_work)

                # Periodic garbage collection and progress logging
                # DataFrames created for each sample/gate combo can accumulate without cleanup
                gc_interval = getattr(config_defaults, 'GC_COLLECT_INTERVAL', 5)
                if (sample_idx + 1) % gc_interval == 0:
                    gc.collect()
                    logger.info(f"  Processed {sample_idx + 1}/{len(samples)} samples")

        logger.info(f"Statistics calculation complete: {successful_calcs} successful, {samples_with_errors} with errors")

    def calculate_statistics_parallel(
        self,
        gate_ids: List[str],
        channels: List[str],
        metrics: List[MFIMetric],
        max_workers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        sample_ids: Optional[List[str]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None,
        gc_interval: int = 10
    ) -> None:
        """
        Calculate statistics for specified gates and channels using parallel workers.

        This is the parallel equivalent of calculate_statistics(). Each sample is
        processed by a separate worker thread. NumPy releases the GIL during MFI
        calculations (mean, median, gmean), enabling true parallelism across cores.

        Args:
            gate_ids: List of gate IDs to calculate stats for
            channels: List of channel names for MFI calculation
            metrics: List of MFI metrics to calculate
            max_workers: Number of worker threads (None = min(4, cpu_count))
            progress_callback: Optional callback(current, total) for progress
            sample_ids: Optional list of sample IDs to include (None = all samples)
            status_callback: Optional callback(message) for status updates
            cancellation_token: Optional token to support cancellation
            gc_interval: Run gc.collect() every N completed samples (default 10)

        Raises:
            CancellationError: If cancellation_token is cancelled
        """
        # --- Same setup as sequential method ---
        self._statistics.clear()
        self._warnings.clear()

        # Filter samples if sample_ids provided
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in self._workspace.samples if s.sample_id in sample_id_set]
        else:
            samples = self._workspace.samples

        # Store which samples we're processing for later use
        self._included_samples = samples
        total_work = len(samples) * len(gate_ids)

        # Determine worker count
        if max_workers is None:
            max_workers = min(4, multiprocessing.cpu_count())

        logger.info(
            f"Calculating statistics (parallel, {max_workers} workers) for "
            f"{len(samples)} samples, {len(gate_ids)} gates, {len(channels)} channels"
        )
        logger.debug(f"Data source: {self._data_source.value}")

        # Lock for defensive safety when merging results into shared state
        results_lock = threading.Lock()

        # --- Worker function ---
        def process_sample(sample):
            """Process all gates for a single sample. Returns collected results."""
            sample_id = sample.sample_id
            sample_stats = {}
            sample_warnings = []
            successful_count = 0
            error_count = 0

            # Check if sample has FCS data
            if not self._workspace.has_fcs_data(sample_id):
                logger.warning(f"Sample '{sample_id}' has no FCS data - skipping MFI calculations")
                sample_warnings.append(f"Sample '{sample.name}': No FCS data available")

            for gate_id in gate_ids:
                # Reuse the existing per-gate calculation method
                stats = self._calculate_gate_stats(sample_id, gate_id, channels, metrics)
                sample_stats[gate_id] = stats

                if stats.error_message:
                    error_count += 1
                elif stats.mfi_values:
                    successful_count += 1

            return (sample_id, sample_stats, sample_warnings, successful_count, error_count)

        # --- Tracking variables ---
        samples_with_errors = 0
        successful_calcs = 0
        completed_count = 0

        context = f"{len(samples)} samples, {len(gate_ids)} gates, {len(channels)} channels, {max_workers} workers"

        with timed_operation("Statistics calculation (parallel)", context):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit one future per sample
                future_to_sample = {
                    executor.submit(process_sample, sample): sample
                    for sample in samples
                }

                # Process results as they complete
                for future in as_completed(future_to_sample):
                    # Check for cancellation at each sample completion
                    if cancellation_token:
                        if cancellation_token.is_cancelled:
                            # Cancel remaining futures
                            for pending_future in future_to_sample:
                                pending_future.cancel()
                            cancellation_token.check_cancelled()  # Raises CancellationError

                    sample = future_to_sample[future]

                    try:
                        sample_id, sample_stats, sample_warnings, s_success, s_errors = future.result()
                    except CancellationError:
                        raise  # Re-raise cancellation
                    except Exception as e:
                        # Worker raised an unexpected exception
                        sample_id = sample.sample_id
                        logger.error(f"Worker failed for sample '{sample_id}': {type(e).__name__}: {e}")
                        samples_with_errors += 1
                        completed_count += 1
                        # Still update progress
                        if progress_callback:
                            progress_callback(completed_count * len(gate_ids), total_work)
                        continue

                    # Merge results under lock for defensive safety
                    with results_lock:
                        self._statistics[sample_id] = sample_stats
                        self._warnings.extend(sample_warnings)

                    successful_calcs += s_success
                    samples_with_errors += s_errors
                    completed_count += 1

                    # Progress callback — increment by number of gates per sample
                    if progress_callback:
                        progress_callback(completed_count * len(gate_ids), total_work)

                    # Status callback with sample progress
                    if status_callback:
                        status_callback(
                            f"Processed sample {completed_count}/{len(samples)}: {sample.name}"
                        )

                    # Periodic garbage collection
                    if completed_count % gc_interval == 0:
                        gc.collect()
                        logger.info(f"  Processed {completed_count}/{len(samples)} samples")

        logger.info(
            f"Statistics calculation (parallel) complete: "
            f"{successful_calcs} successful, {samples_with_errors} with errors"
        )

    def _calculate_gate_stats(
        self,
        sample_id: str,
        gate_id: str,
        channels: List[str],
        metrics: List[MFIMetric]
    ) -> GateStatistics:
        """Calculate statistics for a single gate on a single sample."""
        stats = GateStatistics(
            sample_id=sample_id,
            gate_id=gate_id,
            gate_path=gate_id  # Will be replaced with full path
        )

        try:
            # Get basic gate statistics from workspace
            gate_stats = self._workspace.get_gate_statistics(sample_id, gate_id)
            stats.event_count = gate_stats.get('count', 0)
            stats.percent_of_parent = gate_stats.get('percent_parent', 0.0)
            stats.percent_of_total = gate_stats.get('percent_total', 0.0)

            logger.debug(f"Gate stats for {sample_id}/{gate_id}: count={stats.event_count}")

            # Add warnings for low event counts
            if stats.event_count > 0 and stats.event_count < LOW_EVENT_WARNING_THRESHOLD:
                warning_msg = f"Gate '{gate_id}' has only {stats.event_count} events - statistics are unreliable"
                logger.warning(warning_msg)
                with self._warnings_lock:
                    self._warnings.append(f"Sample '{sample_id}', {warning_msg}")
            elif stats.event_count > 0 and stats.event_count < MODERATE_EVENT_WARNING_THRESHOLD:
                logger.info(f"Gate '{gate_id}' has {stats.event_count} events - interpret statistics with caution")

            # Calculate MFI if we have events and channels
            if stats.event_count == 0:
                logger.debug(f"Skipping MFI calculation: event_count=0 for {sample_id}/{gate_id}")
                stats.error_message = "No events in gate"
            elif not channels:
                logger.debug(f"Skipping MFI calculation: no channels specified")
            else:
                # Get gated events with specified data source
                events_df = self._workspace.get_gated_events(
                    sample_id, gate_id, channels, data_source=self._data_source
                )

                if events_df is None:
                    logger.warning(f"get_gated_events returned None for {sample_id}/{gate_id}")
                    stats.error_message = "Failed to retrieve gated events"
                elif events_df.empty:
                    logger.warning(f"get_gated_events returned empty DataFrame for {sample_id}/{gate_id}")
                    stats.error_message = "Empty event data"
                else:
                    logger.debug(f"Got events DataFrame: shape={events_df.shape}, columns={list(events_df.columns)}")

                    channels_calculated = 0
                    for channel in channels:
                        if channel in events_df.columns:
                            channel_data = events_df[channel].values

                            # Use optimized single-pass calculation
                            stats.mfi_values[channel] = calculate_all_mfi_optimized(
                                channel_data,
                                include_mean=MFIMetric.MEAN in metrics,
                                include_median=MFIMetric.MEDIAN in metrics,
                                include_geomean=MFIMetric.GEOMETRIC_MEAN in metrics
                            )

                            # Log explanation when gMFI is NaN
                            if MFIMetric.GEOMETRIC_MEAN in metrics:
                                gmfi_value = stats.mfi_values[channel].get('GeoMean')
                                if gmfi_value is not None and np.isnan(gmfi_value):
                                    explanation = explain_geometric_mean_result(channel_data)
                                    if explanation:
                                        logger.info(f"gMFI NaN for {sample_id}/{gate_id}/{channel}: {explanation}")

                            channels_calculated += 1
                        else:
                            logger.debug(f"Channel '{channel}' not in DataFrame columns")

                    logger.debug(f"Calculated MFI for {channels_calculated}/{len(channels)} channels")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"_calculate_gate_stats FAILED for {sample_id}/{gate_id}: {error_msg}")
            stats.error_message = error_msg
            with self._warnings_lock:
                self._warnings.append(f"Sample '{sample_id}', Gate '{gate_id}': {error_msg}")

        return stats

    def get_statistics_dataframe(
        self,
        gate_ids: List[str],
        channels: List[str],
        metrics: List[MFIMetric],
        include_keywords: bool = True,
        include_gate_stats: bool = True,
        scale_factors: Optional[Dict[str, float]] = None,
        selected_keywords: Optional[List[str]] = None,
        channel_display_names: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """
        Generate statistics DataFrame in wide format.

        Args:
            gate_ids: Gates to include
            channels: Channels for MFI columns
            metrics: MFI metrics to include
            include_keywords: Whether to include sample keywords
            include_gate_stats: If True, include count/%parent/%total columns.
                               If False, only include MFI columns (for MFI-only sheets).
            scale_factors: Optional dict of sample_id -> scale factor. When provided,
                          adds a scale_factor column and scaled_count columns for each gate.

        Returns:
            DataFrame with one row per sample, columns for each gate/metric combination
        """
        rows = []

        # Use included samples if available (from calculate_statistics), else all samples
        samples = getattr(self, '_included_samples', self._workspace.samples)

        for sample in samples:
            sample_id = sample.sample_id
            row = {
                'sample_id': sample_id,
                'sample_name': sample.name,
            }

            # Add scale factor column if provided
            if scale_factors:
                row['scale_factor'] = scale_factors.get(sample_id, 1.0)

            # Add keywords if requested (sorted alphabetically for consistent column order)
            if include_keywords:
                custom = sample.get_custom_keywords()
                keys = sorted(custom.keys())
                if selected_keywords is not None:
                    keys = [k for k in keys if k in selected_keywords]
                for kw_name in keys:
                    row[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

            # Add gate statistics
            for gate_id in gate_ids:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    # Count and percent columns (only if include_gate_stats=True)
                    # Note: %total is excluded per user feedback - not commonly used
                    if include_gate_stats:
                        row[f"{gate_id}_count"] = stats.event_count
                        # Add scaled count if scale factors provided
                        if scale_factors:
                            factor = scale_factors.get(sample_id, 1.0)
                            row[f"{gate_id}_scaled_count"] = stats.event_count * factor
                        row[f"{gate_id}_%parent"] = stats.percent_of_parent

                    # MFI columns
                    for channel in channels:
                        if channel in stats.mfi_values:
                            for metric in metrics:
                                metric_key = metric.value
                                if metric_key in stats.mfi_values[channel]:
                                    display = channel_display_names.get(channel, channel) if channel_display_names else channel
                                    col_name = f"{gate_id}_{metric_key}_{display}"
                                    row[col_name] = stats.mfi_values[channel][metric_key]

            rows.append(row)

        return pd.DataFrame(rows)

    def get_statistics_dataframe_sparse(
        self,
        selected_pairs: List[tuple],  # List of (gate_id, channel) tuples
        metrics: List[MFIMetric],
        include_keywords: bool = True,
        include_gate_stats: bool = True,
        all_gate_ids: Optional[List[str]] = None,
        scale_factors: Optional[Dict[str, float]] = None,
        selected_keywords: Optional[List[str]] = None,
        channel_display_names: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """
        Generate statistics DataFrame with sparse MFI columns.

        Only generates MFI columns for the exact (gate_id, channel) pairs specified,
        rather than the full cartesian product of gates × channels.

        Args:
            selected_pairs: List of (gate_id, channel) tuples for MFI columns
            metrics: MFI metrics to include
            include_keywords: Whether to include sample keywords
            include_gate_stats: If True, include count/%parent/%total columns.
                               If False, only include MFI columns (for MFI-only sheets).
            all_gate_ids: List of all gate IDs for gate stats. If provided and include_gate_stats=True,
                         gate stats are included for ALL these gates. If None, only gates in selected_pairs.
            scale_factors: Optional dict of sample_id -> scale factor. When provided,
                          adds a scale_factor column and scaled_count columns for each gate.

        Returns:
            DataFrame with one row per sample, sparse MFI columns for selected pairs only
        """
        rows = []

        # Determine which gates get stats columns (only matters if include_gate_stats=True)
        if include_gate_stats:
            if all_gate_ids:
                gate_ids_for_stats = all_gate_ids
            else:
                # Only gates that appear in selected_pairs
                gate_ids_for_stats = list(set(gate_id for gate_id, _ in selected_pairs))
        else:
            gate_ids_for_stats = []

        # Use included samples if available (from calculate_statistics), else all samples
        samples = getattr(self, '_included_samples', self._workspace.samples)

        for sample in samples:
            sample_id = sample.sample_id
            row = {
                'sample_id': sample_id,
                'sample_name': sample.name,
            }

            # Add scale factor column if provided
            if scale_factors:
                row['scale_factor'] = scale_factors.get(sample_id, 1.0)

            # Add keywords if requested (sorted alphabetically for consistent column order)
            if include_keywords:
                custom = sample.get_custom_keywords()
                keys = sorted(custom.keys())
                if selected_keywords is not None:
                    keys = [k for k in keys if k in selected_keywords]
                for kw_name in keys:
                    row[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

            # Add gate statistics (count, %parent) if enabled
            # Note: %total is excluded per user feedback - not commonly used
            for gate_id in gate_ids_for_stats:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    # Count and percent columns
                    row[f"{gate_id}_count"] = stats.event_count
                    # Add scaled count if scale factors provided
                    if scale_factors:
                        factor = scale_factors.get(sample_id, 1.0)
                        row[f"{gate_id}_scaled_count"] = stats.event_count * factor
                    row[f"{gate_id}_%parent"] = stats.percent_of_parent

            # Add MFI columns ONLY for selected (gate_id, channel) pairs
            for gate_id, channel in selected_pairs:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    if channel in stats.mfi_values:
                        for metric in metrics:
                            metric_key = metric.value
                            if metric_key in stats.mfi_values[channel]:
                                display = channel_display_names.get(channel, channel) if channel_display_names else channel
                                col_name = f"{gate_id}_{metric_key}_{display}"
                                row[col_name] = stats.mfi_values[channel][metric_key]

            rows.append(row)

        return pd.DataFrame(rows)

    def get_gate_statistics(self, sample_id: str, gate_id: str) -> Optional[GateStatistics]:
        """Get statistics for a specific sample/gate combination."""
        if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
            return self._statistics[sample_id][gate_id]
        return None

    def _resolve_gate_stats(self, sample_id: str, gate_id: str) -> Tuple[int, float, float]:
        """
        Resolve gate stats from precomputed cache when available, else workspace.

        Returns:
            Tuple of (count, percent_parent, percent_total)
        """
        cached = self.get_gate_statistics(sample_id, gate_id)
        if cached is not None:
            return cached.event_count, cached.percent_of_parent, cached.percent_of_total

        stats = self._workspace.get_gate_statistics(sample_id, gate_id)
        count = int(stats.get('count', 0) or 0)
        percent_parent = float(stats.get('percent_parent', 0.0) or 0.0)
        percent_total = float(stats.get('percent_total', 0.0) or 0.0)
        return count, percent_parent, percent_total

    def get_warnings(self) -> List[str]:
        """Get list of warnings/errors from calculation."""
        return self._warnings.copy()

    def has_warnings(self) -> bool:
        """Check if there were any warnings during calculation."""
        return len(self._warnings) > 0

    def calculate_frequencies(
        self,
        gate_ids: List[str],
        wide: bool = True,
        include_keywords: bool = True,
        data_type: FrequencyDataType = FrequencyDataType.BOTH,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Calculate frequency (count and/or %parent) data for gates.

        Args:
            gate_ids: List of gate IDs to include
            wide: If True, return wide format (one row per sample, gates as columns).
                  If False, return tidy format (one row per gate per sample).
            include_keywords: Whether to include sample keywords in output
            data_type: What data to include - BOTH, COUNTS only, or PERCENT only
            selected_keywords: Optional list of keyword names to include (None = all)

        Returns:
            DataFrame with frequency data in requested format
        """
        samples = self._workspace.samples
        logger.info(f"Calculating frequencies for {len(samples)} samples, {len(gate_ids)} gates, wide={wide}, data_type={data_type.value}")

        if wide:
            return self._calculate_frequencies_wide(gate_ids, include_keywords, data_type, selected_keywords)
        else:
            return self._calculate_frequencies_tidy(gate_ids, include_keywords, data_type, selected_keywords)

    def _calculate_frequencies_wide(
        self,
        gate_ids: List[str],
        include_keywords: bool,
        data_type: FrequencyDataType = FrequencyDataType.BOTH,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Generate wide format frequency DataFrame (one row per sample)."""
        rows = []

        # Build gate path lookup for column naming (using clean path format for Excel)
        gate_paths = {}
        for gate_info in self._workspace.gates:
            gate_paths[gate_info.gate_id] = gate_info.full_path_string

        # Use included samples if available, else all samples
        samples = getattr(self, '_included_samples', self._workspace.samples)

        for sample in samples:
            sample_id = sample.sample_id
            row = {
                'sample_id': sample_id,
                'sample_name': sample.name,
            }

            # Add keywords if requested (sorted alphabetically for consistent column order)
            if include_keywords:
                custom = sample.get_custom_keywords()
                keys = sorted(custom.keys())
                if selected_keywords is not None:
                    keys = [k for k in keys if k in selected_keywords]
                for kw_name in keys:
                    row[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

            # Add frequency data for each gate
            for gate_id in gate_ids:
                try:
                    count, percent_parent, _ = self._resolve_gate_stats(sample_id, gate_id)
                    gate_path = gate_paths.get(gate_id, gate_id)

                    # Add columns based on data_type
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row[f"{gate_path}_count"] = count
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row[f"{gate_path}_%parent"] = percent_parent
                except Exception as e:
                    gate_path = gate_paths.get(gate_id, gate_id)
                    logger.warning(f"Failed to get stats for {sample_id}/{gate_id}: {e}")
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row[f"{gate_path}_count"] = float('nan')
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row[f"{gate_path}_%parent"] = float('nan')

            rows.append(row)

        return pd.DataFrame(rows)

    def _calculate_frequencies_tidy(
        self,
        gate_ids: List[str],
        include_keywords: bool,
        data_type: FrequencyDataType = FrequencyDataType.BOTH,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Generate tidy format frequency DataFrame (one row per gate per sample)."""
        rows = []

        # Build gate path lookup (using clean path format for Excel)
        gate_paths = {}
        for gate_info in self._workspace.gates:
            gate_paths[gate_info.gate_id] = gate_info.full_path_string

        # Use included samples if available, else all samples
        samples = getattr(self, '_included_samples', self._workspace.samples)

        for sample in samples:
            sample_id = sample.sample_id
            sample_name = sample.name

            # Get keywords once per sample (sorted alphabetically for consistent order)
            keywords = {}
            if include_keywords:
                custom = sample.get_custom_keywords()
                keys = sorted(custom.keys())
                if selected_keywords is not None:
                    keys = [k for k in keys if k in selected_keywords]
                for kw_name in keys:
                    keywords[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

            # Add a row for each gate
            for gate_id in gate_ids:
                try:
                    count, percent_parent, _ = self._resolve_gate_stats(sample_id, gate_id)
                    gate_path = gate_paths.get(gate_id, gate_id)

                    row = {
                        'sample_id': sample_id,
                        'sample_name': sample_name,
                        'gate_path': gate_path,
                        'gate_name': gate_id,
                    }

                    # Add columns based on data_type
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row['count'] = count
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row['%parent'] = percent_parent

                    # Add keywords
                    row.update(keywords)

                    rows.append(row)
                except Exception as e:
                    gate_path = gate_paths.get(gate_id, gate_id)
                    logger.warning(f"Failed to get stats for {sample_id}/{gate_id}: {e}")
                    row = {
                        'sample_id': sample_id,
                        'sample_name': sample_name,
                        'gate_path': gate_path,
                        'gate_name': gate_id,
                    }
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row['count'] = float('nan')
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row['%parent'] = float('nan')
                    row.update(keywords)
                    rows.append(row)

        return pd.DataFrame(rows)

    def calculate_normalized_frequencies(
        self,
        reference_gate_ids: List[str],
        sample_ids: Optional[List[str]] = None,
        max_depth: int = 0,
        include_keywords: bool = True,
        selected_keywords: Optional[List[str]] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Calculate frequencies of descendants as % of reference gates (wide format).

        This method calculates how much of each reference gate population is
        accounted for by its descendant gates. For example, if CD8+ is the
        reference gate and CD8+/PD1+ is a descendant, this calculates what
        percentage of CD8+ cells are PD1+.

        Args:
            reference_gate_ids: List of gate IDs to use as normalization references
                               (e.g., ["Cells/Live/CD8+", "Cells/Live/CD4+"])
            sample_ids: Optional list of sample IDs to include (None = all samples)
            max_depth: Maximum descendant depth (0 = unlimited, 1 = direct children only)
            include_keywords: Include sample keywords in output DataFrames

        Returns:
            Dict mapping reference_gate_id to DataFrame with columns:
            - sample_id, sample_name, [keywords...],
              {descendant_relative_path}_count, {descendant_relative_path}_%of_ref
        """
        logger.info(f"Calculating normalized frequencies for {len(reference_gate_ids)} reference gates")

        # Filter samples if sample_ids provided
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in self._workspace.samples if s.sample_id in sample_id_set]
        else:
            samples = self._workspace.samples

        result_dataframes = {}

        for ref_gate_id in reference_gate_ids:
            logger.debug(f"Processing reference gate: {ref_gate_id}")

            # Get descendants for this reference gate
            descendants = self._workspace.get_descendant_gates(ref_gate_id, max_depth)
            logger.debug(f"Found {len(descendants)} descendant gates for {ref_gate_id}")

            if not descendants:
                logger.warning(f"No descendants found for reference gate '{ref_gate_id}'")
                # Create empty DataFrame with basic columns
                result_dataframes[ref_gate_id] = pd.DataFrame(columns=['sample_id', 'sample_name'])
                continue

            # Build rows for this reference gate
            rows = []

            # Get reference gate path for computing relative paths
            ref_path_parts = ref_gate_id.split('/')
            ref_depth = len(ref_path_parts)
            ref_gate_name = ref_path_parts[-1] if ref_path_parts else ref_gate_id

            for sample in samples:
                sample_id = sample.sample_id
                row = {
                    'sample_id': sample_id,
                    'sample_name': sample.name,
                }

                # Add keywords if requested (sorted alphabetically for consistent column order)
                if include_keywords:
                    custom = sample.get_custom_keywords()
                    keys = sorted(custom.keys())
                    if selected_keywords is not None:
                        keys = [k for k in keys if k in selected_keywords]
                    for kw_name in keys:
                        row[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

                # Get reference gate count
                try:
                    ref_count, _, _ = self._resolve_gate_stats(sample_id, ref_gate_id)
                except Exception as e:
                    logger.warning(f"Failed to get reference stats for {sample_id}/{ref_gate_id}: {e}")
                    ref_count = float('nan')

                row[f"ref_count"] = ref_count

                # Process each descendant
                for descendant in descendants:
                    desc_gate_id = descendant.gate_id

                    # Compute relative path from reference gate
                    desc_path_parts = desc_gate_id.split('/')
                    relative_path = '/'.join(desc_path_parts[ref_depth:])

                    # Get descendant count
                    try:
                        desc_count, _, _ = self._resolve_gate_stats(sample_id, desc_gate_id)
                    except Exception as e:
                        logger.warning(f"Failed to get descendant stats for {sample_id}/{desc_gate_id}: {e}")
                        desc_count = float('nan')

                    # Calculate normalized percentage
                    if isinstance(ref_count, float) and math.isnan(ref_count):
                        pct_of_ref = float('nan')
                    elif isinstance(desc_count, float) and math.isnan(desc_count):
                        pct_of_ref = float('nan')
                    elif ref_count > 0:
                        pct_of_ref = (desc_count / ref_count) * 100.0
                    else:
                        pct_of_ref = float('nan')

                    # Add columns for this descendant
                    row[f"{relative_path}_count"] = desc_count
                    row[f"{relative_path}_%of_{ref_gate_name}"] = pct_of_ref

                rows.append(row)

            result_dataframes[ref_gate_id] = pd.DataFrame(rows)
            logger.info(f"Created DataFrame for '{ref_gate_id}': {len(rows)} samples, {len(descendants)} descendants")

        return result_dataframes

    def calculate_normalized_frequencies_tidy(
        self,
        reference_gate_ids: List[str],
        sample_ids: Optional[List[str]] = None,
        max_depth: int = 0,
        include_keywords: bool = True,
        selected_keywords: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Calculate normalized frequencies in tidy format (one row per sample/gate/reference).

        This method provides the same calculation as calculate_normalized_frequencies
        but in a tidy (long) format that is easier to use for programmatic analysis,
        filtering, and plotting with tools like seaborn or ggplot.

        Args:
            reference_gate_ids: List of gate IDs to use as normalization references
            sample_ids: Optional list of sample IDs to include (None = all samples)
            max_depth: Maximum descendant depth (0 = unlimited, 1 = direct children only)
            include_keywords: Include sample keywords in output

        Returns:
            DataFrame with columns:
            - sample_id: Sample identifier
            - sample_name: Human-readable sample name
            - reference_gate: Full path of reference gate (e.g., "Cells/Live/CD8+")
            - reference_gate_name: Just the name of reference gate (e.g., "CD8+")
            - descendant_gate: Full path of descendant gate
            - descendant_gate_name: Just the name of descendant gate
            - relative_path: Path from reference to descendant (e.g., "PD1+/Tim3+")
            - relative_depth: How many levels below reference (1 = direct child)
            - count: Event count in descendant gate
            - reference_count: Event count in reference gate
            - %of_reference: (count / reference_count) * 100
            - [keywords...]: Sample keywords if include_keywords=True
        """
        logger.info(f"Calculating normalized frequencies (tidy) for {len(reference_gate_ids)} reference gates")

        # Filter samples if sample_ids provided
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in self._workspace.samples if s.sample_id in sample_id_set]
        else:
            samples = self._workspace.samples

        rows = []

        for ref_gate_id in reference_gate_ids:
            logger.debug(f"Processing reference gate: {ref_gate_id}")

            # Get descendants for this reference gate
            descendants = self._workspace.get_descendant_gates(ref_gate_id, max_depth)
            logger.debug(f"Found {len(descendants)} descendant gates for {ref_gate_id}")

            if not descendants:
                logger.warning(f"No descendants found for reference gate '{ref_gate_id}'")
                continue

            # Get reference gate name (last part of path)
            ref_path_parts = ref_gate_id.split('/')
            ref_gate_name = ref_path_parts[-1] if ref_path_parts else ref_gate_id
            ref_depth = len(ref_path_parts)

            for sample in samples:
                sample_id = sample.sample_id
                sample_name = sample.name

                # Get keywords once per sample (sorted alphabetically for consistent order)
                keywords = {}
                if include_keywords:
                    custom = sample.get_custom_keywords()
                    keys = sorted(custom.keys())
                    if selected_keywords is not None:
                        keys = [k for k in keys if k in selected_keywords]
                    for kw_name in keys:
                        keywords[kw_name] = str(custom[kw_name]) if custom[kw_name] else ''

                # Get reference gate count
                try:
                    ref_count, _, _ = self._resolve_gate_stats(sample_id, ref_gate_id)
                except Exception as e:
                    logger.warning(f"Failed to get reference stats for {sample_id}/{ref_gate_id}: {e}")
                    ref_count = float('nan')

                # Process each descendant
                for descendant in descendants:
                    desc_gate_id = descendant.gate_id
                    desc_gate_name = descendant.name

                    # Compute relative path and depth
                    desc_path_parts = desc_gate_id.split('/')
                    relative_path = '/'.join(desc_path_parts[ref_depth:])
                    relative_depth = len(desc_path_parts) - ref_depth

                    # Get descendant count
                    try:
                        desc_count, _, _ = self._resolve_gate_stats(sample_id, desc_gate_id)
                    except Exception as e:
                        logger.warning(f"Failed to get descendant stats for {sample_id}/{desc_gate_id}: {e}")
                        desc_count = float('nan')

                    # Calculate normalized percentage
                    if isinstance(ref_count, float) and math.isnan(ref_count):
                        pct_of_ref = float('nan')
                    elif isinstance(desc_count, float) and math.isnan(desc_count):
                        pct_of_ref = float('nan')
                    elif ref_count > 0:
                        pct_of_ref = (desc_count / ref_count) * 100.0
                    else:
                        pct_of_ref = float('nan')

                    # Build the row
                    row = {
                        'sample_id': sample_id,
                        'sample_name': sample_name,
                        'reference_gate': ref_gate_id,
                        'reference_gate_name': ref_gate_name,
                        'descendant_gate': desc_gate_id,
                        'descendant_gate_name': desc_gate_name,
                        'relative_path': relative_path,
                        'relative_depth': relative_depth,
                        'count': desc_count,
                        'reference_count': ref_count,
                        '%of_reference': pct_of_ref,
                    }

                    # Add keywords
                    row.update(keywords)

                    rows.append(row)

        result_df = pd.DataFrame(rows)
        logger.info(f"Created tidy DataFrame: {len(rows)} rows")

        return result_df

    def get_volume_keyword(self, sample_id: str) -> Optional[float]:
        """
        Extract $VOL keyword from sample.

        Args:
            sample_id: The sample ID to get volume for

        Returns:
            Volume in microliters (μL), or None if not available
        """
        sample = self._workspace.get_sample_by_id(sample_id)
        if sample is None:
            logger.debug(f"Sample '{sample_id}' not found for volume lookup")
            return None

        # $VOL is stored in the sample keywords
        vol_str = sample.keywords.get('$VOL')
        if not vol_str:
            logger.debug(f"Sample '{sample_id}' has no $VOL keyword")
            return None

        try:
            vol = float(vol_str)
            if vol <= 0:
                logger.warning(f"Sample '{sample_id}' has invalid $VOL value: {vol}")
                return None
            return vol
        except ValueError:
            logger.warning(f"Sample '{sample_id}' has non-numeric $VOL: '{vol_str}'")
            return None

    def calculate_normalized_counts(
        self,
        denominator: float,
        gate_ids: Optional[List[str]] = None,
        sample_ids: Optional[List[str]] = None
    ) -> List[str]:
        """
        Calculate volume-normalized counts.

        Normalized count = (raw_count / $VOL) * denominator

        For example, if $VOL is 50 μL and denominator is 100, the result
        represents "cells per 100 μL".

        Args:
            denominator: Target volume for normalization (e.g., 100 for per 100 μL)
            gate_ids: List of gate IDs to include. If None, uses all gates
                     with calculated statistics.
            sample_ids: List of sample IDs to include. If None, uses all samples
                       from _included_samples.

        Returns:
            List of warning messages for samples with missing/invalid $VOL

        Raises:
            ValueError: If calculate_statistics() was not called first
        """
        if not self._statistics:
            raise ValueError("Must call calculate_statistics() before calculate_normalized_counts()")

        warnings = []

        # Determine which samples to process
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in getattr(self, '_included_samples', self._workspace.samples)
                       if s.sample_id in sample_id_set]
        else:
            samples = getattr(self, '_included_samples', self._workspace.samples)

        # Determine which gates to include
        if gate_ids is None:
            # Get all unique gate_ids from statistics
            gate_ids = set()
            for sample_stats in self._statistics.values():
                gate_ids.update(sample_stats.keys())
            gate_ids = sorted(gate_ids)

        logger.info(f"Calculating normalized counts for {len(samples)} samples, "
                    f"{len(gate_ids)} gates, denominator={denominator}")

        rows = []

        for sample in samples:
            sample_id = sample.sample_id
            vol = self.get_volume_keyword(sample_id)

            row = {'sample_id': sample_id}

            if vol is None or vol <= 0:
                warning = f"Sample '{sample.name}' ({sample_id}): missing or invalid $VOL keyword"
                warnings.append(warning)
                logger.warning(warning)

                # Fill with NaN for this sample
                for gate_id in gate_ids:
                    row[f"{gate_id}_count"] = float('nan')
                rows.append(row)
                continue

            # Get statistics for each gate and calculate normalized count
            if sample_id in self._statistics:
                for gate_id in gate_ids:
                    if gate_id in self._statistics[sample_id]:
                        stats = self._statistics[sample_id][gate_id]
                        raw_count = stats.event_count
                        normalized = (raw_count / vol) * denominator
                        row[f"{gate_id}_count"] = normalized
                    else:
                        row[f"{gate_id}_count"] = float('nan')
            else:
                # Sample has no statistics, fill with NaN
                for gate_id in gate_ids:
                    row[f"{gate_id}_count"] = float('nan')

            rows.append(row)

        self._normalized_counts_df = pd.DataFrame(rows)
        logger.info(f"Created normalized counts DataFrame: {len(rows)} samples, "
                    f"{len(warnings)} warnings")

        # Add warnings to the model's warning list
        self._warnings.extend(warnings)

        return warnings

    @property
    def normalized_counts_df(self) -> Optional[pd.DataFrame]:
        """Returns the calculated volume-normalized counts DataFrame."""
        return self._normalized_counts_df

    def get_volume_sheet_name(self, denominator: float, include_all: bool = False) -> str:
        """
        Generate descriptive sheet name for volume-normalized counts.

        Args:
            denominator: The volume denominator used
            include_all: If True, adds "_All" suffix

        Returns:
            Sheet name like "Counts_per_100uL" or "Counts_per_mL"
        """
        if denominator == 1000:
            base = "Counts_per_mL"
        else:
            base = f"Counts_per_{int(denominator)}uL"

        return f"{base}_All" if include_all else base

    # --- Bead Normalization ---

    # Threshold below which bead counts are considered statistically unreliable
    LOW_BEAD_COUNT_THRESHOLD = 50

    def calculate_bead_normalized_counts(
        self,
        bead_gate_id: str,
        user_number: float,
        mode: str = "per_n_beads",
        gate_ids: Optional[List[str]] = None,
        sample_ids: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Calculate bead-normalized counts.

        Formula: normalized = (cell_count_in_gate / bead_count) * user_number

        For "per_n_beads" mode (Mode A):
            e.g., CD4+ T cells per 1000 beads

        For "per_well" mode (Mode B):
            e.g., CD4+ T cells per well (user_number = beads added per well)

        Args:
            bead_gate_id: Gate ID for the counting beads population
            user_number: Denominator for "per N beads" or beads per well
            mode: "per_n_beads" or "per_well"
            gate_ids: Gates to normalize. None = all gates from statistics.
            sample_ids: Samples to include. None = all from _included_samples.

        Returns:
            Tuple of (DataFrame with normalized counts, list of warnings)

        Raises:
            ValueError: If calculate_statistics() was not called first
        """
        if not self._statistics:
            raise ValueError("Must call calculate_statistics() before calculate_bead_normalized_counts()")

        warnings = []

        # Determine which samples to process
        if sample_ids is not None:
            sample_id_set = set(sample_ids)
            samples = [s for s in getattr(self, '_included_samples', self._workspace.samples)
                       if s.sample_id in sample_id_set]
        else:
            samples = getattr(self, '_included_samples', self._workspace.samples)

        # Determine which gates to include
        if gate_ids is None:
            gate_ids_set = set()
            for sample_stats in self._statistics.values():
                gate_ids_set.update(sample_stats.keys())
            gate_ids = sorted(gate_ids_set)

        logger.info(
            f"Calculating bead-normalized counts: {len(samples)} samples, "
            f"{len(gate_ids)} gates, bead_gate={bead_gate_id}, "
            f"user_number={user_number}, mode={mode}"
        )

        rows = []

        for sample in samples:
            sample_id = sample.sample_id

            row = {
                'sample_id': sample_id,
                'sample_name': sample.name,
            }

            # Get bead count for this sample
            bead_count = None
            if sample_id in self._statistics and bead_gate_id in self._statistics[sample_id]:
                bead_stats = self._statistics[sample_id][bead_gate_id]
                bead_count = bead_stats.event_count
            else:
                warning = (
                    f"Sample '{sample.name}' ({sample_id}): "
                    f"bead gate '{bead_gate_id}' not found in statistics"
                )
                warnings.append(warning)
                logger.warning(warning)

            row['bead_count'] = bead_count if bead_count is not None else float('nan')

            # Handle missing or zero bead count
            if bead_count is None:
                # Already warned above; fill with NaN
                for gate_id in gate_ids:
                    row[f"{gate_id}_bead_norm"] = float('nan')
                rows.append(row)
                continue

            if bead_count == 0:
                warning = (
                    f"Sample '{sample.name}' ({sample_id}): "
                    f"bead count is 0 - cannot normalize (division by zero)"
                )
                warnings.append(warning)
                logger.warning(warning)
                for gate_id in gate_ids:
                    row[f"{gate_id}_bead_norm"] = float('nan')
                rows.append(row)
                continue

            if bead_count < self.LOW_BEAD_COUNT_THRESHOLD:
                warning = (
                    f"Sample '{sample.name}' ({sample_id}): "
                    f"low bead count ({bead_count}) - results may be statistically unreliable"
                )
                warnings.append(warning)
                logger.warning(warning)

            # Calculate normalized count for each gate
            if sample_id in self._statistics:
                for gate_id in gate_ids:
                    if gate_id in self._statistics[sample_id]:
                        stats = self._statistics[sample_id][gate_id]
                        raw_count = stats.event_count
                        normalized = (raw_count / bead_count) * user_number
                        row[f"{gate_id}_bead_norm"] = normalized
                    else:
                        row[f"{gate_id}_bead_norm"] = float('nan')
            else:
                # Sample has no statistics, fill with NaN
                for gate_id in gate_ids:
                    row[f"{gate_id}_bead_norm"] = float('nan')

            rows.append(row)

        self._bead_normalized_df = pd.DataFrame(rows)
        logger.info(
            f"Created bead-normalized counts DataFrame: {len(rows)} samples, "
            f"{len(warnings)} warnings"
        )

        # Add warnings to the model's warning list
        self._warnings.extend(warnings)

        return self._bead_normalized_df, warnings

    @property
    def bead_normalized_df(self) -> Optional[pd.DataFrame]:
        """Returns the calculated bead-normalized counts DataFrame."""
        return self._bead_normalized_df

    @staticmethod
    def get_bead_sheet_name(user_number: float, mode: str = "per_n_beads") -> str:
        """
        Generate descriptive sheet name for bead-normalized counts.

        Excel sheet names have a 31-character limit.

        Args:
            user_number: The user-provided number
            mode: "per_n_beads" or "per_well"

        Returns:
            Sheet name like "Bead_Norm (per 1000 beads)" or
            "Bead_Norm (50000 beads/well)", truncated to 31 chars
        """
        n = int(user_number)
        if mode == "per_well":
            name = f"Bead_Norm ({n} beads/well)"
        else:
            name = f"Bead_Norm (per {n} beads)"

        # Excel sheet name limit is 31 characters
        if len(name) > 31:
            name = name[:31]

        return name
