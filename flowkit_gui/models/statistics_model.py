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
import pandas as pd
import numpy as np

from .workspace_model import WorkspaceModel, Sample, DataSource
from ..utils.mfi_calculations import calculate_mean, calculate_median, calculate_geometric_mean
from ..utils.logging_config import get_logger

logger = get_logger("statistics_model")


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

    def calculate_statistics(
        self,
        gate_ids: List[str],
        channels: List[str],
        metrics: List[MFIMetric],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        sample_ids: Optional[List[str]] = None
    ) -> None:
        """
        Calculate statistics for specified gates and channels.

        Args:
            gate_ids: List of gate IDs to calculate stats for
            channels: List of channel names for MFI calculation
            metrics: List of MFI metrics to calculate
            progress_callback: Optional callback(current, total) for progress
            sample_ids: Optional list of sample IDs to include (None = all samples)
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

        for sample in samples:
            sample_id = sample.sample_id
            self._statistics[sample_id] = {}

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

        logger.info(f"Statistics calculation complete: {successful_calcs} successful, {samples_with_errors} with errors")

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
                            stats.mfi_values[channel] = {}

                            if MFIMetric.MEAN in metrics:
                                stats.mfi_values[channel]['Mean'] = calculate_mean(channel_data)
                            if MFIMetric.MEDIAN in metrics:
                                stats.mfi_values[channel]['Median'] = calculate_median(channel_data)
                            if MFIMetric.GEOMETRIC_MEAN in metrics:
                                stats.mfi_values[channel]['GeoMean'] = calculate_geometric_mean(channel_data)

                            channels_calculated += 1
                        else:
                            logger.debug(f"Channel '{channel}' not in DataFrame columns")

                    logger.debug(f"Calculated MFI for {channels_calculated}/{len(channels)} channels")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"_calculate_gate_stats FAILED for {sample_id}/{gate_id}: {error_msg}")
            stats.error_message = error_msg
            self._warnings.append(f"Sample '{sample_id}', Gate '{gate_id}': {error_msg}")

        return stats

    def get_statistics_dataframe(
        self,
        gate_ids: List[str],
        channels: List[str],
        metrics: List[MFIMetric],
        include_keywords: bool = True,
        include_gate_stats: bool = True
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

            # Add keywords if requested
            if include_keywords:
                custom = sample.get_custom_keywords()
                for kw_name, kw_value in custom.items():
                    row[kw_name] = str(kw_value) if kw_value else ''

            # Add gate statistics
            for gate_id in gate_ids:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    # Count and percent columns (only if include_gate_stats=True)
                    if include_gate_stats:
                        row[f"{gate_id}_count"] = stats.event_count
                        row[f"{gate_id}_%parent"] = stats.percent_of_parent
                        row[f"{gate_id}_%total"] = stats.percent_of_total

                    # MFI columns
                    for channel in channels:
                        if channel in stats.mfi_values:
                            for metric in metrics:
                                metric_key = metric.value
                                if metric_key in stats.mfi_values[channel]:
                                    col_name = f"{gate_id}_{metric_key}_{channel}"
                                    row[col_name] = stats.mfi_values[channel][metric_key]

            rows.append(row)

        return pd.DataFrame(rows)

    def get_statistics_dataframe_sparse(
        self,
        selected_pairs: List[tuple],  # List of (gate_id, channel) tuples
        metrics: List[MFIMetric],
        include_keywords: bool = True,
        include_gate_stats: bool = True,
        all_gate_ids: Optional[List[str]] = None
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

            # Add keywords if requested
            if include_keywords:
                custom = sample.get_custom_keywords()
                for kw_name, kw_value in custom.items():
                    row[kw_name] = str(kw_value) if kw_value else ''

            # Add gate statistics (count, %parent, %total) if enabled
            for gate_id in gate_ids_for_stats:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    # Count and percent columns
                    row[f"{gate_id}_count"] = stats.event_count
                    row[f"{gate_id}_%parent"] = stats.percent_of_parent
                    row[f"{gate_id}_%total"] = stats.percent_of_total

            # Add MFI columns ONLY for selected (gate_id, channel) pairs
            for gate_id, channel in selected_pairs:
                if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
                    stats = self._statistics[sample_id][gate_id]

                    if channel in stats.mfi_values:
                        for metric in metrics:
                            metric_key = metric.value
                            if metric_key in stats.mfi_values[channel]:
                                col_name = f"{gate_id}_{metric_key}_{channel}"
                                row[col_name] = stats.mfi_values[channel][metric_key]

            rows.append(row)

        return pd.DataFrame(rows)

    def get_gate_statistics(self, sample_id: str, gate_id: str) -> Optional[GateStatistics]:
        """Get statistics for a specific sample/gate combination."""
        if sample_id in self._statistics and gate_id in self._statistics[sample_id]:
            return self._statistics[sample_id][gate_id]
        return None

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
        data_type: FrequencyDataType = FrequencyDataType.BOTH
    ) -> pd.DataFrame:
        """
        Calculate frequency (count and/or %parent) data for gates.

        Args:
            gate_ids: List of gate IDs to include
            wide: If True, return wide format (one row per sample, gates as columns).
                  If False, return tidy format (one row per gate per sample).
            include_keywords: Whether to include sample keywords in output
            data_type: What data to include - BOTH, COUNTS only, or PERCENT only

        Returns:
            DataFrame with frequency data in requested format
        """
        samples = self._workspace.samples
        logger.info(f"Calculating frequencies for {len(samples)} samples, {len(gate_ids)} gates, wide={wide}, data_type={data_type.value}")

        if wide:
            return self._calculate_frequencies_wide(gate_ids, include_keywords, data_type)
        else:
            return self._calculate_frequencies_tidy(gate_ids, include_keywords, data_type)

    def _calculate_frequencies_wide(
        self,
        gate_ids: List[str],
        include_keywords: bool,
        data_type: FrequencyDataType = FrequencyDataType.BOTH
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

            # Add keywords if requested
            if include_keywords:
                custom = sample.get_custom_keywords()
                for kw_name, kw_value in custom.items():
                    row[kw_name] = str(kw_value) if kw_value else ''

            # Add frequency data for each gate
            for gate_id in gate_ids:
                try:
                    stats = self._workspace.get_gate_statistics(sample_id, gate_id)
                    gate_path = gate_paths.get(gate_id, gate_id)

                    # Add columns based on data_type
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row[f"{gate_path}_count"] = stats.get('count', 0)
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row[f"{gate_path}_%parent"] = stats.get('percent_parent', 0.0)
                except Exception as e:
                    gate_path = gate_paths.get(gate_id, gate_id)
                    logger.warning(f"Failed to get stats for {sample_id}/{gate_id}: {e}")
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row[f"{gate_path}_count"] = 0
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row[f"{gate_path}_%parent"] = 0.0

            rows.append(row)

        return pd.DataFrame(rows)

    def _calculate_frequencies_tidy(
        self,
        gate_ids: List[str],
        include_keywords: bool,
        data_type: FrequencyDataType = FrequencyDataType.BOTH
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

            # Get keywords once per sample
            keywords = {}
            if include_keywords:
                custom = sample.get_custom_keywords()
                for kw_name, kw_value in custom.items():
                    keywords[kw_name] = str(kw_value) if kw_value else ''

            # Add a row for each gate
            for gate_id in gate_ids:
                try:
                    stats = self._workspace.get_gate_statistics(sample_id, gate_id)
                    gate_path = gate_paths.get(gate_id, gate_id)

                    row = {
                        'sample_id': sample_id,
                        'sample_name': sample_name,
                        'gate_path': gate_path,
                        'gate_name': gate_id,
                    }

                    # Add columns based on data_type
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.COUNTS):
                        row['count'] = stats.get('count', 0)
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row['%parent'] = stats.get('percent_parent', 0.0)

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
                        row['count'] = 0
                    if data_type in (FrequencyDataType.BOTH, FrequencyDataType.PERCENT):
                        row['%parent'] = 0.0
                    row.update(keywords)
                    rows.append(row)

        return pd.DataFrame(rows)

    def calculate_normalized_frequencies(
        self,
        reference_gate_ids: List[str],
        sample_ids: Optional[List[str]] = None,
        max_depth: int = 0,
        include_keywords: bool = True
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

            for sample in samples:
                sample_id = sample.sample_id
                row = {
                    'sample_id': sample_id,
                    'sample_name': sample.name,
                }

                # Add keywords if requested
                if include_keywords:
                    custom = sample.get_custom_keywords()
                    for kw_name, kw_value in custom.items():
                        row[kw_name] = str(kw_value) if kw_value else ''

                # Get reference gate count
                try:
                    ref_stats = self._workspace.get_gate_statistics(sample_id, ref_gate_id)
                    ref_count = ref_stats.get('count', 0)
                except Exception as e:
                    logger.warning(f"Failed to get reference stats for {sample_id}/{ref_gate_id}: {e}")
                    ref_count = 0

                row[f"ref_count"] = ref_count

                # Process each descendant
                for descendant in descendants:
                    desc_gate_id = descendant.gate_id

                    # Compute relative path from reference gate
                    desc_path_parts = desc_gate_id.split('/')
                    relative_path = '/'.join(desc_path_parts[ref_depth:])

                    # Get descendant count
                    try:
                        desc_stats = self._workspace.get_gate_statistics(sample_id, desc_gate_id)
                        desc_count = desc_stats.get('count', 0)
                    except Exception as e:
                        logger.warning(f"Failed to get descendant stats for {sample_id}/{desc_gate_id}: {e}")
                        desc_count = 0

                    # Calculate normalized percentage
                    if ref_count > 0:
                        pct_of_ref = (desc_count / ref_count) * 100.0
                    else:
                        pct_of_ref = 0.0

                    # Add columns for this descendant
                    row[f"{relative_path}_count"] = desc_count
                    row[f"{relative_path}_%of_ref"] = pct_of_ref

                rows.append(row)

            result_dataframes[ref_gate_id] = pd.DataFrame(rows)
            logger.info(f"Created DataFrame for '{ref_gate_id}': {len(rows)} samples, {len(descendants)} descendants")

        return result_dataframes

    def calculate_normalized_frequencies_tidy(
        self,
        reference_gate_ids: List[str],
        sample_ids: Optional[List[str]] = None,
        max_depth: int = 0,
        include_keywords: bool = True
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

                # Get keywords once per sample
                keywords = {}
                if include_keywords:
                    custom = sample.get_custom_keywords()
                    for kw_name, kw_value in custom.items():
                        keywords[kw_name] = str(kw_value) if kw_value else ''

                # Get reference gate count
                try:
                    ref_stats = self._workspace.get_gate_statistics(sample_id, ref_gate_id)
                    ref_count = ref_stats.get('count', 0)
                except Exception as e:
                    logger.warning(f"Failed to get reference stats for {sample_id}/{ref_gate_id}: {e}")
                    ref_count = 0

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
                        desc_stats = self._workspace.get_gate_statistics(sample_id, desc_gate_id)
                        desc_count = desc_stats.get('count', 0)
                    except Exception as e:
                        logger.warning(f"Failed to get descendant stats for {sample_id}/{desc_gate_id}: {e}")
                        desc_count = 0

                    # Calculate normalized percentage
                    if ref_count > 0:
                        pct_of_ref = (desc_count / ref_count) * 100.0
                    else:
                        pct_of_ref = 0.0

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
