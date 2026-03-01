"""
XLSX Exporter - Generate Excel workbooks with flow cytometry analysis results.

This module provides:
- Multi-sheet workbook generation
- Gating strategy sheet (with full paths)
- Keywords sheets (tidy and wide formats)
- Statistics sheets (selected and all markers)
- Warnings sheet for calculation errors
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.table import Table, TableStyleInfo

from ..models.workspace_model import WorkspaceModel, DataSource
from ..models.keywords_model import KeywordsModel
from ..models.statistics_model import StatisticsModel, MFIMetric, FrequencyDataType
from ..config import defaults as config_defaults
from ..utils.logging_config import get_logger
from ..utils.cancellation import CancellationToken, CancellationError
from ..utils.timing import PipelineTimer
from .export_config import ExportConfig

logger = get_logger("xlsx_exporter")


@dataclass
class CompensationSummary:
    """Compensation application details for export summary."""
    mode: DataSource  # AUTO, RAW, or COMP
    total_samples: int
    matrices_used: Dict[str, int]  # {matrix_name: sample_count}
    failed_samples: int
    spectral_samples: int  # Count using spectral/OLS compensation


@dataclass
class StatisticsSummary:
    """Statistics generation details for export summary."""
    gates_exported: int
    channels_analyzed: int  # Unique channels with MFI
    mfi_metrics: List[str]  # e.g., ["Mean", "Median", "GeoMean"]
    total_mfi_calculations: int  # gates x channels x metrics x samples
    frequency_calculations: int  # gate count statistics


@dataclass
class ExportSummary:
    """Complete export operation summary."""
    # Success/failure status
    success: bool
    filepath: str

    # Sample/gate counts
    samples_processed: int
    gates_exported: int
    keywords_exported: int

    # Detailed breakdowns
    compensation: CompensationSummary
    statistics: StatisticsSummary

    # Sheets created
    sheets_created: List[str]

    # Issues
    warnings: List[str]
    errors: List[str]


class XLSXExporter:
    """
    Export flow cytometry analysis results to Excel workbook.

    Generates sheets:
    1. Gating_Strategy - Hierarchical gate structure with full paths
    2. Keywords - Tidy format (one row per keyword per sample)
    3. Keywords_Wide (optional) - Wide format pivoted by Mouse/Organ
    4. Statistics_Selected - MFI for user-selected markers only
    5. Statistics_All - MFI for all markers
    6. Warnings (if any) - List of calculation errors/warnings
    """

    def __init__(
        self,
        workspace: WorkspaceModel,
        keywords_model: KeywordsModel,
        config: Optional[ExportConfig] = None,
        gate_ids: Optional[List[str]] = None,
        selected_markers: Optional[List[str]] = None,
        all_markers: Optional[List[str]] = None,
        mfi_metrics: Optional[List[MFIMetric]] = None,
        include_wide_keywords: bool = False,
        include_tidy_frequencies: bool = False,
        include_all_sheets: bool = False,
        data_source: DataSource = DataSource.AUTO,
        index_columns: Optional[List[str]] = None,
        selected_keywords: Optional[List[str]] = None,
        selected_sample_ids: Optional[List[str]] = None,
        matrix_selections: Optional[List[tuple]] = None,
        reference_gate_ids: Optional[List[str]] = None,
        descendant_depth: int = 0,
        volume_normalize: bool = False,
        volume_denominator: float = 100.0,
        bead_normalize: bool = False,
        bead_gate_id: Optional[str] = None,
        bead_user_number: float = 1000.0,
        bead_mode: str = "per_n_beads",
        scale_factors: Optional[Dict[str, float]] = None
    ):
        """
        Initialize exporter.

        Args:
            workspace: Loaded WorkspaceModel
            keywords_model: KeywordsModel with sample data
            config: Optional ExportConfig object containing all export parameters.
                   If provided, overrides all other keyword arguments.
            gate_ids: List of gate IDs to include (ignored if config provided)
            selected_markers: User-selected marker channels (ignored if config provided)
            all_markers: All available marker channels (ignored if config provided)
            mfi_metrics: List of MFI metrics to calculate (ignored if config provided)
            include_wide_keywords: Whether to include Keywords_Wide sheet (ignored if config provided)
            include_tidy_frequencies: Whether to include tidy frequency sheets (ignored if config provided)
            include_all_sheets: Whether to include _All sheets (Counts_All, Frequencies_All, MFI_All, Concatenated_All) (ignored if config provided)
            data_source: Event data source (AUTO, RAW, or COMP) (ignored if config provided)
            index_columns: Keywords to use as index columns in Keywords_Wide sheet (ignored if config provided)
            selected_keywords: Keywords to include in export (None = all keywords) (ignored if config provided)
            selected_sample_ids: List of sample IDs to export (None = all samples) (ignored if config provided)
            matrix_selections: List of (gate_id, channel) tuples for sparse MFI selection (ignored if config provided)
            reference_gate_ids: Gates to use as normalization references for frequency sheets (ignored if config provided)
            descendant_depth: Max depth for descendant gates (0 = unlimited) (ignored if config provided)
            volume_normalize: Whether to calculate volume-normalized counts (ignored if config provided)
            volume_denominator: Denominator for normalization (e.g., 100 for per 100 μL) (ignored if config provided)
            bead_normalize: Whether to calculate bead-normalized counts (ignored if config provided)
            bead_gate_id: Gate ID for counting beads population (ignored if config provided)
            bead_user_number: Denominator for "per N beads" or beads per well (ignored if config provided)
            bead_mode: "per_n_beads" or "per_well" (ignored if config provided)
            scale_factors: Optional dict of sample_id -> scale factor for scaling event counts (ignored if config provided)
        """
        # If config provided, unpack all parameters from it
        if config is not None:
            gate_ids = config.gate_ids
            selected_markers = config.selected_markers
            all_markers = config.all_markers
            mfi_metrics = config.mfi_metrics
            include_wide_keywords = config.include_wide_keywords
            include_tidy_frequencies = config.include_tidy_frequencies
            include_all_sheets = config.include_all_sheets
            data_source = config.data_source
            index_columns = config.index_columns
            selected_keywords = config.selected_keywords
            selected_sample_ids = config.selected_sample_ids
            matrix_selections = config.matrix_selections
            reference_gate_ids = config.reference_gate_ids
            descendant_depth = config.descendant_depth
            volume_normalize = config.volume_normalize
            volume_denominator = config.volume_denominator
            bead_normalize = config.bead_normalize
            bead_gate_id = config.bead_gate_id
            bead_user_number = config.bead_user_number
            bead_mode = config.bead_mode
            scale_factors = config.scale_factors

        self._workspace = workspace
        self._keywords_model = keywords_model
        self._gate_ids = gate_ids
        self._selected_markers = selected_markers
        self._all_markers = all_markers
        self._mfi_metrics = mfi_metrics
        self._include_wide_keywords = include_wide_keywords
        self._include_tidy_frequencies = include_tidy_frequencies
        self._include_all_sheets = include_all_sheets
        self._data_source = data_source
        self._index_columns = index_columns
        self._selected_keywords = selected_keywords
        self._selected_sample_ids = selected_sample_ids
        self._matrix_selections = matrix_selections
        self._reference_gate_ids = reference_gate_ids or []
        self._descendant_depth = descendant_depth
        self._volume_normalize = volume_normalize
        self._volume_denominator = volume_denominator
        self._bead_normalize = bead_normalize
        self._bead_gate_id = bead_gate_id
        self._bead_user_number = bead_user_number
        self._bead_mode = bead_mode
        self._scale_factors = scale_factors
        self._warnings: List[str] = []

        # Build matrix selections lookup for efficient checking
        self._matrix_selection_set = set(matrix_selections) if matrix_selections else None

    def export(
        self,
        filepath: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> ExportSummary:
        """
        Export data to Excel workbook.

        Args:
            filepath: Path to save the Excel file
            progress_callback: Optional callback(current, total) for progress
            status_callback: Optional callback(message) for detailed status updates
            cancellation_token: Optional token to support cancellation

        Raises:
            CancellationError: If cancellation_token is cancelled
        """
        self._warnings.clear()
        wb = Workbook()
        try:
            return self._export_workbook(wb, filepath, progress_callback, status_callback, cancellation_token)
        finally:
            wb.close()

    def _export_workbook(
        self,
        wb: Workbook,
        filepath: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> ExportSummary:
        """Internal export implementation that writes to the given workbook."""

        # Initialize pipeline timer for performance monitoring
        timer = PipelineTimer("Excel Export")
        timer.start()

        logger.info(f"Starting export to {filepath}")
        logger.debug(f"Data source: {self._data_source.value}")

        # Initialize sheets created tracking for export summary
        sheets_created = []

        # Determine which samples we're processing for summary
        processing_sample_ids = (
            self._selected_sample_ids if self._selected_sample_ids
            else [s.sample_id for s in self._workspace.samples]
        )

        # Collect compensation summary for export report
        comp_info = self._workspace.get_workspace_compensation_info()
        comp_assignments = comp_info.get('sample_assignments', {})
        matrices_used: Dict[str, int] = {}  # {matrix_name: count}
        spectral_count = 0

        # Count matrix usage across selected samples
        for sample_id in processing_sample_ids:
            if sample_id in comp_assignments:
                assignment = comp_assignments[sample_id]
                matrix_name = assignment.matrix_name
                matrices_used[matrix_name] = matrices_used.get(matrix_name, 0) + 1
                if assignment.spectral:
                    spectral_count += 1

        # Determine whether to include "_Selected" sheets
        # When no markers are selected, _Selected sheets are redundant with _All sheets
        has_selected_markers = bool(self._selected_markers)
        logger.debug(f"Include _Selected sheets: {has_selected_markers}")

        # Check for gates that don't exist in all samples and add informational warnings
        missing_gates_info = self._workspace.get_missing_gates_info(self._gate_ids)
        for gate_id, missing_samples in missing_gates_info.items():
            if len(missing_samples) <= 5:
                sample_list = ", ".join(missing_samples)
            else:
                sample_list = f"{', '.join(missing_samples[:5])} and {len(missing_samples) - 5} more"
            self._warnings.append(
                f"Gate '{gate_id}' not present in samples: {sample_list} "
                f"(statistics will show zeros for these samples)"
            )
            logger.info(f"Gate '{gate_id}' missing from {len(missing_samples)} samples")

        # Calculate total steps for progress
        # Base: Gating_Strategy, Keywords = 2
        # _All sheets (optional): Counts_All, Frequencies_All, MFI_All, Concatenated_All = 4
        # Count/Freq sheets always written; MFI/Concatenated only if markers selected
        # Optional: Keywords_Wide (+1), Tidy _All (+2), Tidy count/freq (+2), Tidy MFI if markers
        all_sheet_count = 4 if self._include_all_sheets else 0
        # Counts_Selected + Frequencies_Selected always; MFI + Concatenated only if markers
        selected_sheet_count = 2 + (2 if has_selected_markers else 0)
        tidy_all_count = 2 if self._include_tidy_frequencies and self._include_all_sheets else 0
        # Tidy count/freq always when tidy enabled; no tidy MFI sheets exist
        tidy_selected_count = 2 if self._include_tidy_frequencies else 0
        # +1 for Compensation sheet
        total_steps = 3 + all_sheet_count + selected_sheet_count + (1 if self._include_wide_keywords else 0) + tidy_all_count + tidy_selected_count

        # Add volume normalization sheets
        if self._volume_normalize:
            total_steps += 1  # Selected volume-normalized sheet
            if self._include_all_sheets:
                total_steps += 1  # All volume-normalized sheet

        # Add bead normalization sheet
        if self._bead_normalize and self._bead_gate_id:
            total_steps += 1

        current_step = 0

        # Sheet 1: Gating Strategy
        if status_callback:
            status_callback("Writing Gating_Strategy sheet...")
        with timer.step("Write gating strategy"):
            ws_gates = wb.active
            ws_gates.title = "Gating_Strategy"
            self._write_gating_strategy(ws_gates)
            sheets_created.append("Gating_Strategy")
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Sheet 2: Keywords (Tidy)
        if status_callback:
            status_callback("Writing Keywords sheet...")
        with timer.step("Write keywords sheet"):
            ws_keywords = wb.create_sheet("Keywords")
            self._write_keywords_tidy(ws_keywords)
            sheets_created.append("Keywords")
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Sheet 3 (optional): Keywords Wide
        if self._include_wide_keywords:
            if status_callback:
                status_callback("Writing Keywords_Wide sheet...")
            ws_keywords_wide = wb.create_sheet("Keywords_Wide")
            self._write_keywords_wide(ws_keywords_wide)
            sheets_created.append("Keywords_Wide")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Compensation
        if status_callback:
            status_callback("Writing Compensation sheet...")
        ws_compensation = wb.create_sheet("Compensation")
        self._write_compensation_sheet(ws_compensation, comp_info, processing_sample_ids)
        sheets_created.append("Compensation")
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Pre-calculate statistics ONCE with all markers (optimization)
        # This avoids calculating the same gate statistics twice
        all_markers_set = set(self._all_markers)
        if self._selected_markers:
            all_markers_set.update(self._selected_markers)
        all_markers_combined = list(all_markers_set)

        # Log sample filtering if active
        if self._selected_sample_ids:
            logger.info(f"Filtering to {len(self._selected_sample_ids)} selected samples")

        # Check for cancellation before heavy computation
        if cancellation_token:
            cancellation_token.check_cancelled()

        logger.info(f"Pre-calculating statistics for {len(all_markers_combined)} markers...")
        if status_callback:
            status_callback("Calculating statistics...")
        stats_model = StatisticsModel(self._workspace, data_source=self._data_source)
        if all_markers_combined:
            # Use parallel statistics when multiple workers configured
            max_workers = config_defaults.MAX_PARALLEL_WORKERS
            with timer.step("Calculate statistics"):
                if max_workers is None or max_workers > 1:
                    stats_model.calculate_statistics_parallel(
                        self._gate_ids,
                        all_markers_combined,
                        self._mfi_metrics,
                        max_workers=max_workers,
                        sample_ids=self._selected_sample_ids,
                        status_callback=status_callback,
                        cancellation_token=cancellation_token,
                        gc_interval=config_defaults.GC_COLLECT_INTERVAL
                    )
                else:
                    stats_model.calculate_statistics(
                        self._gate_ids,
                        all_markers_combined,
                        self._mfi_metrics,
                        sample_ids=self._selected_sample_ids,
                        status_callback=status_callback,
                        cancellation_token=cancellation_token
                    )
            calc_warnings = stats_model.get_warnings()
            if calc_warnings:
                self._warnings.extend(calc_warnings)
                logger.debug(f"Collected {len(calc_warnings)} warnings from statistics calculation")

        # Check for cancellation after statistics calculation
        if cancellation_token:
            cancellation_token.check_cancelled()

        # Calculate volume-normalized counts if enabled
        normalized_counts_df = None
        if self._volume_normalize:
            if status_callback:
                status_callback("Calculating volume-normalized counts...")
            with timer.step("Calculate normalized counts"):
                try:
                    volume_warnings = stats_model.calculate_normalized_counts(
                        denominator=self._volume_denominator,
                        gate_ids=self._gate_ids,
                        sample_ids=self._selected_sample_ids
                    )
                    normalized_counts_df = stats_model.normalized_counts_df
                    if volume_warnings:
                        self._warnings.extend(volume_warnings)
                        logger.info(f"Volume normalization: {len(volume_warnings)} samples missing $VOL")
                except Exception as e:
                    logger.error(f"Volume normalization failed: {e}")
                    self._warnings.append(f"Volume normalization failed: {e}")

        # Calculate bead-normalized counts if enabled
        bead_normalized_df = None
        if self._bead_normalize and self._bead_gate_id:
            if status_callback:
                status_callback("Calculating bead-normalized counts...")
            with timer.step("Calculate bead-normalized counts"):
                try:
                    bead_df, bead_warnings = stats_model.calculate_bead_normalized_counts(
                        bead_gate_id=self._bead_gate_id,
                        user_number=self._bead_user_number,
                        mode=self._bead_mode,
                        gate_ids=self._gate_ids,
                        sample_ids=self._selected_sample_ids
                    )
                    bead_normalized_df = bead_df
                    if bead_warnings:
                        self._warnings.extend(bead_warnings)
                        logger.info(f"Bead normalization: {len(bead_warnings)} warnings")
                except Exception as e:
                    logger.error(f"Bead normalization failed: {e}")
                    self._warnings.append(f"Bead normalization failed: {e}")

        # Sheet: Counts_All (wide format, counts only)
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing Counts_All sheet...")
            ws_counts_all = wb.create_sheet("Counts_All")
            self._write_frequencies_wide_sheet(
                ws_counts_all, stats_model, self._gate_ids, "All Gates Counts",
                data_type=FrequencyDataType.COUNTS
            )
            sheets_created.append("Counts_All")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Counts_Selected (always written — counts are gate-level, not marker-dependent)
        if status_callback:
            status_callback("Writing Counts_Selected sheet...")
        ws_counts_selected = wb.create_sheet("Counts_Selected")
        self._write_frequencies_wide_sheet(
            ws_counts_selected, stats_model, self._gate_ids, "Selected Gates Counts",
            data_type=FrequencyDataType.COUNTS
        )
        sheets_created.append("Counts_Selected")
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Sheet: Volume-normalized counts (if enabled)
        if self._volume_normalize and normalized_counts_df is not None:
            sheet_name = self._sanitize_sheet_name(self._get_volume_sheet_name(include_all=False))
            if status_callback:
                status_callback(f"Writing {sheet_name} sheet...")
            ws_vol_norm = wb.create_sheet(sheet_name)
            self._write_normalized_counts_sheet(ws_vol_norm, normalized_counts_df, sheet_name)
            sheets_created.append(sheet_name)
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

            # Also create _All version if include_all_sheets is enabled
            if self._include_all_sheets:
                sheet_name_all = self._sanitize_sheet_name(self._get_volume_sheet_name(include_all=True))
                if status_callback:
                    status_callback(f"Writing {sheet_name_all} sheet...")
                ws_vol_norm_all = wb.create_sheet(sheet_name_all)
                self._write_normalized_counts_sheet(ws_vol_norm_all, normalized_counts_df, sheet_name_all)
                sheets_created.append(sheet_name_all)
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

        # Sheet: Bead-normalized counts (if enabled)
        if self._bead_normalize and bead_normalized_df is not None:
            bead_sheet_name = self._sanitize_sheet_name(
                stats_model.get_bead_sheet_name(self._bead_user_number, self._bead_mode)
            )
            if status_callback:
                status_callback(f"Writing {bead_sheet_name} sheet...")
            ws_bead_norm = wb.create_sheet(bead_sheet_name)
            self._write_bead_normalized_counts_sheet(ws_bead_norm, bead_normalized_df, bead_sheet_name)
            sheets_created.append(bead_sheet_name)
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Frequencies_All (wide format, percentages only)
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing Frequencies_All sheet...")
            ws_freq_all = wb.create_sheet("Frequencies_All")
            self._write_frequencies_wide_sheet(
                ws_freq_all, stats_model, self._gate_ids, "All Gates Frequencies",
                data_type=FrequencyDataType.PERCENT
            )
            sheets_created.append("Frequencies_All")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Frequencies_Selected (always written — frequencies are gate-level, not marker-dependent)
        if status_callback:
            status_callback("Writing Frequencies_Selected sheet...")
        ws_freq_selected = wb.create_sheet("Frequencies_Selected")
        self._write_frequencies_wide_sheet(
            ws_freq_selected, stats_model, self._gate_ids, "Selected Gates Frequencies",
            data_type=FrequencyDataType.PERCENT
        )
        sheets_created.append("Frequencies_Selected")
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Optional: Tidy format sheets (counts and frequencies separate)
        if self._include_tidy_frequencies:
            # Tidy _All sheets (only if include_all_sheets is enabled)
            if self._include_all_sheets:
                if status_callback:
                    status_callback("Writing Counts_All_Tidy sheet...")
                ws_counts_all_tidy = wb.create_sheet("Counts_All_Tidy")
                self._write_frequencies_tidy_sheet(
                    ws_counts_all_tidy, stats_model, self._gate_ids, "All Gates Counts Tidy",
                    data_type=FrequencyDataType.COUNTS
                )
                sheets_created.append("Counts_All_Tidy")
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

            # Counts_Selected_Tidy (always written — counts are gate-level, not marker-dependent)
            if status_callback:
                status_callback("Writing Counts_Selected_Tidy sheet...")
            ws_counts_selected_tidy = wb.create_sheet("Counts_Selected_Tidy")
            self._write_frequencies_tidy_sheet(
                ws_counts_selected_tidy, stats_model, self._gate_ids, "Selected Gates Counts Tidy",
                data_type=FrequencyDataType.COUNTS
            )
            sheets_created.append("Counts_Selected_Tidy")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

            # Frequencies_All_Tidy (only if include_all_sheets is enabled)
            if self._include_all_sheets:
                if status_callback:
                    status_callback("Writing Frequencies_All_Tidy sheet...")
                ws_freq_all_tidy = wb.create_sheet("Frequencies_All_Tidy")
                self._write_frequencies_tidy_sheet(
                    ws_freq_all_tidy, stats_model, self._gate_ids, "All Gates Frequencies Tidy",
                    data_type=FrequencyDataType.PERCENT
                )
                sheets_created.append("Frequencies_All_Tidy")
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

            # Frequencies_Selected_Tidy (always written — frequencies are gate-level, not marker-dependent)
            if status_callback:
                status_callback("Writing Frequencies_Selected_Tidy sheet...")
            ws_freq_selected_tidy = wb.create_sheet("Frequencies_Selected_Tidy")
            self._write_frequencies_tidy_sheet(
                ws_freq_selected_tidy, stats_model, self._gate_ids, "Selected Gates Frequencies Tidy",
                data_type=FrequencyDataType.PERCENT
            )
            sheets_created.append("Frequencies_Selected_Tidy")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: MFI_Selected - Pure MFI only (no gate stats)
        if has_selected_markers:
            if status_callback:
                status_callback("Writing MFI_Selected sheet...")
            ws_mfi_selected = wb.create_sheet("MFI_Selected")
            if self._matrix_selections:
                self._write_statistics_sheet_sparse(
                    ws_mfi_selected,
                    stats_model,
                    self._matrix_selections,
                    "MFI Selected (sparse)",
                    include_gate_stats=False
                )
            else:
                self._write_statistics_sheet(
                    ws_mfi_selected,
                    stats_model,
                    self._selected_markers,
                    "MFI Selected",
                    include_gate_stats=False
                )
            sheets_created.append("MFI_Selected")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: MFI_All - Pure MFI only (no gate stats)
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing MFI_All sheet...")
            ws_mfi_all = wb.create_sheet("MFI_All")
            self._write_statistics_sheet(
                ws_mfi_all,
                stats_model,
                self._all_markers,
                "MFI All",
                include_gate_stats=False
            )
            sheets_created.append("MFI_All")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Concatenated_Selected - Gate stats + sparse MFI
        # Columns reordered by measurement type: counts → normalized counts → %parent → MFI
        if has_selected_markers:
            if status_callback:
                status_callback("Writing Concatenated_Selected sheet...")
            ws_concat_selected = wb.create_sheet("Concatenated_Selected")
            if self._matrix_selections:
                self._write_statistics_sheet_sparse(
                    ws_concat_selected,
                    stats_model,
                    self._matrix_selections,
                    "Concatenated Selected (sparse)",
                    include_gate_stats=True,
                    normalized_counts_df=normalized_counts_df if self._volume_normalize else None,
                    reorder_columns=True
                )
            else:
                self._write_statistics_sheet(
                    ws_concat_selected,
                    stats_model,
                    self._selected_markers,
                    "Concatenated Selected",
                    include_gate_stats=True,
                    normalized_counts_df=normalized_counts_df if self._volume_normalize else None,
                    reorder_columns=True
                )
            sheets_created.append("Concatenated_Selected")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Concatenated_All - All gate stats + all MFI
        # Columns reordered by measurement type: counts → normalized counts → %parent → MFI
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing Concatenated_All sheet...")
            ws_concat_all = wb.create_sheet("Concatenated_All")
            self._write_statistics_sheet(
                ws_concat_all,
                stats_model,
                self._all_markers,
                "Concatenated All",
                include_gate_stats=True,
                normalized_counts_df=normalized_counts_df if self._volume_normalize else None,
                reorder_columns=True
            )
            sheets_created.append("Concatenated_All")
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Write normalized frequency sheets if reference gates are selected
        if self._reference_gate_ids:
            logger.info(f"Generating normalized frequency sheets for {len(self._reference_gate_ids)} reference gates")
            if status_callback:
                status_callback("Calculating normalized frequencies...")

            # Wide format: one sheet per reference gate
            normalized_wide = stats_model.calculate_normalized_frequencies(
                reference_gate_ids=self._reference_gate_ids,
                sample_ids=self._selected_sample_ids,
                max_depth=self._descendant_depth,
                include_keywords=True
            )

            # Track existing sheet names for collision handling (case-insensitive)
            existing_sheet_names = {ws.title.lower() for ws in wb.worksheets}

            for ref_gate_id, df in normalized_wide.items():
                if not df.empty:
                    if status_callback:
                        status_callback(f"Writing normalized frequency sheet for {ref_gate_id}...")
                    sheet_name = self._write_normalized_frequency_sheet(
                        wb, ref_gate_id, df, existing_sheet_names
                    )
                    sheets_created.append(sheet_name)
                    logger.debug(f"Created sheet '{sheet_name}' for reference gate '{ref_gate_id}'")

            # Tidy format: combined sheet
            if status_callback:
                status_callback("Writing normalized frequencies tidy sheet...")
            normalized_tidy = stats_model.calculate_normalized_frequencies_tidy(
                reference_gate_ids=self._reference_gate_ids,
                sample_ids=self._selected_sample_ids,
                max_depth=self._descendant_depth,
                include_keywords=True
            )

            if not normalized_tidy.empty:
                self._write_normalized_frequencies_tidy_sheet(wb, normalized_tidy)
                sheets_created.append("Normalized_Freq_Tidy")

        # Sheet (if warnings): Warnings
        if self._warnings:
            if status_callback:
                status_callback("Writing Warnings sheet...")
            ws_warnings = wb.create_sheet("Warnings")
            self._write_warnings(ws_warnings)
            sheets_created.append("Warnings")
            logger.warning(f"Export completed with {len(self._warnings)} warnings")

        # Final cancellation check before saving
        if cancellation_token:
            cancellation_token.check_cancelled()

        # Save workbook
        if status_callback:
            status_callback("Saving Excel file...")
        with timer.step("Save workbook"):
            wb.save(filepath)

        # Log timing summary with cache stats
        cache_stats = self._workspace.get_cache_stats() if hasattr(self._workspace, 'get_cache_stats') else None
        timer.summary(cache_stats=cache_stats)

        logger.info(f"Export saved to {filepath}")

        # Build export summary
        unique_channels = set(self._all_markers)
        if self._selected_markers:
            unique_channels.update(self._selected_markers)
        samples_count = len(processing_sample_ids)
        mfi_metric_names = [m.value for m in self._mfi_metrics]

        # Calculate total MFI calculations
        # If using sparse matrix selections, count actual selections
        if self._matrix_selections:
            total_mfi = len(self._matrix_selections) * len(self._mfi_metrics) * samples_count
        else:
            total_mfi = len(self._gate_ids) * len(unique_channels) * len(self._mfi_metrics) * samples_count

        frequency_calcs = len(self._gate_ids) * samples_count

        # Count keywords
        if self._selected_keywords:
            keywords_count = len(self._selected_keywords)
        else:
            all_keywords = self._keywords_model.get_available_keywords()
            keywords_count = len(all_keywords)

        # Count compensation failures from warnings
        comp_failed_count = sum(
            1 for w in self._warnings
            if "compensation" in w.lower() and "failed" in w.lower()
        )

        summary = ExportSummary(
            success=True,
            filepath=filepath,
            samples_processed=samples_count,
            gates_exported=len(self._gate_ids),
            keywords_exported=keywords_count,
            compensation=CompensationSummary(
                mode=self._data_source,
                total_samples=samples_count,
                matrices_used=matrices_used,
                failed_samples=comp_failed_count,
                spectral_samples=spectral_count
            ),
            statistics=StatisticsSummary(
                gates_exported=len(self._gate_ids),
                channels_analyzed=len(unique_channels),
                mfi_metrics=mfi_metric_names,
                total_mfi_calculations=total_mfi,
                frequency_calculations=frequency_calcs
            ),
            sheets_created=sheets_created,
            warnings=self._warnings.copy(),
            errors=[]
        )

        return summary

    def get_warnings(self) -> List[str]:
        """Get list of warnings/errors from the export."""
        return self._warnings.copy()

    def has_warnings(self) -> bool:
        """Check if there were any warnings during export."""
        return len(self._warnings) > 0

    def _write_gating_strategy(self, ws) -> None:
        """Write gating strategy sheet with full paths."""
        headers = ["Gate Path", "Gate Name", "Depth", "Gate Type", "Parameters"]
        ws.append(headers)

        # Style header row
        self._style_header_row(ws, 1)

        # Write gates with full paths
        for gate_info in self._workspace.gates:
            if gate_info.gate_id in self._gate_ids:
                ws.append([
                    gate_info.full_path_string,
                    gate_info.name,
                    gate_info.depth,
                    gate_info.gate_type,
                    ", ".join(gate_info.parameters) if gate_info.parameters else ""
                ])

        # Auto-fit columns
        self._autofit_columns(ws)

        # Freeze header row
        ws.freeze_panes = "A2"

    def _write_keywords_tidy(self, ws) -> None:
        """Write keywords in tidy format."""
        df = self._keywords_model.get_tidy_dataframe(selected_keywords=self._selected_keywords)

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance)
        self._write_dataframe_rows(ws, df)

        # Auto-fit and freeze
        self._autofit_columns(ws)
        ws.freeze_panes = "A2"

    def _write_keywords_wide(self, ws) -> None:
        """Write keywords in wide format."""
        df = self._keywords_model.get_wide_dataframe(
            index_columns=self._index_columns,
            selected_keywords=self._selected_keywords
        )

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance)
        self._write_dataframe_rows(ws, df)

        # Auto-fit and freeze
        self._autofit_columns(ws)
        ws.freeze_panes = "A2"

    def _write_statistics_sheet(
        self,
        ws,
        stats_model: StatisticsModel,
        markers: List[str],
        description: str,
        include_gate_stats: bool = True,
        normalized_counts_df: Optional[pd.DataFrame] = None,
        reorder_columns: bool = False
    ) -> None:
        """
        Write statistics sheet using pre-calculated StatisticsModel.

        Args:
            ws: Worksheet to write to
            stats_model: Pre-calculated StatisticsModel with all needed data
            markers: List of markers to include in this sheet
            description: Description for logging
            include_gate_stats: If True, include count/%parent columns.
                               If False, only include MFI columns (for MFI-only sheets).
            normalized_counts_df: Optional DataFrame with volume-normalized counts
                                 to merge into the sheet (for Concatenated sheets).
            reorder_columns: If True, reorder columns by measurement type
                            (for Concatenated sheets).
        """
        logger.debug(f"Writing statistics sheet: {description}")

        # Get DataFrame (stats already calculated, just filters to requested markers)
        df = stats_model.get_statistics_dataframe(
            self._gate_ids,
            markers,
            self._mfi_metrics,
            include_keywords=True,
            include_gate_stats=include_gate_stats,
            scale_factors=self._scale_factors
        )

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Reorder columns for Concatenated sheets
        if reorder_columns and include_gate_stats:
            df = self._reorder_concatenated_columns(df, normalized_counts_df)

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 4 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=4)

        # Auto-fit and freeze
        self._autofit_columns(ws, max_width=30)

        # Freeze first few columns (sample info + keywords)
        # Find where gate columns start
        freeze_col = 'F'  # Default
        for i, col in enumerate(df.columns):
            if '_count' in col or '_Mean_' in col or '_Median_' in col:
                freeze_col = get_column_letter(i + 1)
                break

        ws.freeze_panes = f"{freeze_col}2"

    def _write_statistics_sheet_sparse(
        self,
        ws,
        stats_model: StatisticsModel,
        matrix_selections: List[tuple],
        description: str,
        include_gate_stats: bool = True,
        normalized_counts_df: Optional[pd.DataFrame] = None,
        reorder_columns: bool = False
    ) -> None:
        """
        Write statistics sheet with sparse MFI columns.

        Only generates MFI columns for the exact (gate_id, channel) pairs specified
        in matrix_selections, rather than the full cartesian product.

        Args:
            ws: Worksheet to write to
            stats_model: Pre-calculated StatisticsModel with all needed data
            matrix_selections: List of (gate_id, channel) tuples for MFI columns
            description: Description for logging
            include_gate_stats: If True, include count/%parent for all tree-selected gates.
                               If False, only include MFI columns (for MFI-only sheets).
            normalized_counts_df: Optional DataFrame with volume-normalized counts
                                 to merge into the sheet (for Concatenated sheets).
            reorder_columns: If True, reorder columns by measurement type
                            (for Concatenated sheets).
        """
        logger.debug(f"Writing sparse statistics sheet: {description}")
        logger.info(f"Sparse export: {len(matrix_selections)} specific gate/marker combinations")

        # Get DataFrame using sparse method
        df = stats_model.get_statistics_dataframe_sparse(
            selected_pairs=matrix_selections,
            metrics=self._mfi_metrics,
            include_keywords=True,
            include_gate_stats=include_gate_stats,
            all_gate_ids=self._gate_ids if include_gate_stats else None,
            scale_factors=self._scale_factors
        )

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Reorder columns for Concatenated sheets
        if reorder_columns and include_gate_stats:
            df = self._reorder_concatenated_columns(df, normalized_counts_df)

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 4 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=4)

        # Auto-fit and freeze
        self._autofit_columns(ws, max_width=30)

        # Freeze first few columns (sample info + keywords)
        # Find where gate columns start
        freeze_col = 'F'  # Default
        for i, col in enumerate(df.columns):
            if '_count' in col or '_Mean_' in col or '_Median_' in col:
                freeze_col = get_column_letter(i + 1)
                break

        ws.freeze_panes = f"{freeze_col}2"

    def _write_frequencies_wide_sheet(
        self,
        ws,
        stats_model: StatisticsModel,
        gate_ids: List[str],
        description: str,
        data_type: FrequencyDataType = FrequencyDataType.BOTH
    ) -> None:
        """
        Write frequencies sheet in wide format (one row per sample).

        Args:
            ws: Worksheet to write to
            stats_model: StatisticsModel for frequency calculation
            gate_ids: List of gate IDs to include
            description: Description for logging
            data_type: What data to include - BOTH, COUNTS only, or PERCENT only
        """
        logger.debug(f"Writing frequencies wide sheet: {description}")

        # Get frequency DataFrame (wide format)
        df = stats_model.calculate_frequencies(gate_ids, wide=True, include_keywords=True, data_type=data_type)

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 2 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=2)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=40)

        # Freeze first columns (sample info + keywords)
        freeze_col = 'D'  # Default: after sample_id, sample_name, and some keywords
        for i, col in enumerate(df.columns):
            if '_count' in col or '_%parent' in col:
                freeze_col = get_column_letter(i + 1)
                break

        ws.freeze_panes = f"{freeze_col}2"

    def _write_frequencies_tidy_sheet(
        self,
        ws,
        stats_model: StatisticsModel,
        gate_ids: List[str],
        description: str,
        data_type: FrequencyDataType = FrequencyDataType.BOTH
    ) -> None:
        """
        Write frequencies sheet in tidy format (one row per gate per sample).

        Args:
            ws: Worksheet to write to
            stats_model: StatisticsModel for frequency calculation
            gate_ids: List of gate IDs to include
            description: Description for logging
            data_type: What data to include - BOTH, COUNTS only, or PERCENT only
        """
        logger.debug(f"Writing frequencies tidy sheet: {description}")

        # Get frequency DataFrame (tidy format)
        df = stats_model.calculate_frequencies(gate_ids, wide=False, include_keywords=True, data_type=data_type)

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 2 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=2)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=50)

        # Freeze header row
        ws.freeze_panes = "A2"

    def _write_warnings(self, ws) -> None:
        """Write warnings sheet with all calculation errors."""
        headers = ["Warning"]
        ws.append(headers)
        self._style_header_row(ws, 1)

        for warning in self._warnings:
            ws.append([warning])

        self._autofit_columns(ws, max_width=100)
        ws.freeze_panes = "A2"

    def _write_compensation_sheet(
        self,
        ws,
        comp_info: Dict[str, Any],
        processing_sample_ids: List[str]
    ) -> None:
        """
        Write compensation information sheet.

        Creates two sections:
        1. Global Matrices - all compensation matrices defined in workspace
        2. Sample Assignments - per-sample compensation matrix assignments

        Args:
            ws: Worksheet to write to
            comp_info: Result from workspace.get_workspace_compensation_info()
            processing_sample_ids: List of sample IDs being exported
        """
        global_matrices = comp_info.get('global_matrices', [])
        sample_assignments = comp_info.get('sample_assignments', {})

        # Section 1: Global Matrices
        ws.append(["=== Global Compensation Matrices ==="])
        ws.append([])  # blank row

        headers_matrices = ["Matrix Name", "Matrix ID", "Type", "Color", "Status", "Detector Count"]
        ws.append(headers_matrices)
        self._style_header_row(ws, ws.max_row)

        if global_matrices:
            for matrix in global_matrices:
                matrix_type = "Spectral" if matrix.spectral else "Conventional"
                ws.append([
                    matrix.name,
                    matrix.matrix_id,
                    matrix_type,
                    matrix.color or "",
                    getattr(matrix, 'status', "") or "",
                    len(matrix.detectors) if matrix.detectors else 0
                ])
        else:
            ws.append(["No compensation matrices defined in workspace"])

        # Blank separator rows
        ws.append([])
        ws.append([])

        # Section 2: Sample Assignments
        ws.append(["=== Per-Sample Compensation Assignments ==="])
        ws.append([])  # blank row

        headers_samples = ["sample_id", "sample_name", "Compensation Matrix", "Matrix Type", "Color"]
        ws.append(headers_samples)
        self._style_header_row(ws, ws.max_row)

        for sample_id in processing_sample_ids:
            sample = self._workspace.get_sample_by_id(sample_id)
            sample_name = sample.name if sample else sample_id

            assignment = sample_assignments.get(sample_id)
            if assignment and assignment.matrix_name:
                matrix_name = assignment.matrix_name
                matrix_type = "Spectral" if assignment.spectral else "Conventional"
                color = assignment.color or ""
            else:
                matrix_name = "None"
                matrix_type = "N/A"
                color = ""

            ws.append([sample_id, sample_name, matrix_name, matrix_type, color])

        self._autofit_columns(ws, max_width=50)
        ws.freeze_panes = "A2"

    def _write_normalized_frequency_sheet(
        self,
        workbook,
        ref_gate_id: str,
        df: pd.DataFrame,
        existing_sheet_names: set
    ) -> str:
        """
        Write a single reference gate's normalized frequencies.

        Note: Count columns are removed per user feedback - counts are available
        in the Counts_* and Concatenated_* sheets.

        Args:
            workbook: The openpyxl Workbook
            ref_gate_id: The reference gate ID (full path)
            df: DataFrame with normalized frequency data
            existing_sheet_names: Set of sheet names already used (for collision handling)

        Returns:
            The sheet name that was created
        """
        # Create sheet name from gate name (last path component)
        gate_name = ref_gate_id.split('/')[-1]
        base_sheet_name = self._sanitize_sheet_name(f"Freq_of_{gate_name}")

        # Handle sheet name collisions
        sheet_name = base_sheet_name
        suffix = 1
        while sheet_name.lower() in existing_sheet_names:
            # Need to add suffix, but keep total length <= 31
            suffix_str = f"_{suffix}"
            max_base_len = 31 - len(suffix_str)
            sheet_name = f"{base_sheet_name[:max_base_len]}{suffix_str}"
            suffix += 1

        existing_sheet_names.add(sheet_name.lower())
        ws = workbook.create_sheet(sheet_name)

        logger.debug(f"Writing normalized frequency sheet: {sheet_name} for {ref_gate_id}")

        if df.empty:
            ws.append([f"No data available for reference gate: {ref_gate_id}"])
            return sheet_name

        # Remove count columns - keep only percentage and metadata columns
        # Count data is available in Counts_* sheets and Concatenated sheets
        cols_to_keep = [col for col in df.columns
                        if not col.endswith('_count') or col == 'ref_count']
        # Actually remove ref_count too - only keep sample info, keywords, and percentages
        cols_to_keep = [col for col in cols_to_keep if col != 'ref_count']
        df = df[cols_to_keep]

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 2 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=2)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=40)

        # Freeze first columns (sample info + keywords) and header row
        freeze_col = 'D'  # Default: after sample_id, sample_name, and some keywords
        for i, col in enumerate(df.columns):
            if '_%of_' in col:
                freeze_col = get_column_letter(i + 1)
                break

        ws.freeze_panes = f"{freeze_col}2"

        return sheet_name

    def _write_normalized_frequencies_tidy_sheet(
        self,
        workbook,
        df: pd.DataFrame
    ) -> None:
        """
        Write combined tidy format for all reference gates.

        Args:
            workbook: The openpyxl Workbook
            df: DataFrame with tidy normalized frequency data
        """
        ws = workbook.create_sheet("Normalized_Freq_Tidy")

        logger.debug(f"Writing normalized frequencies tidy sheet: {len(df)} rows")

        if df.empty:
            ws.append(["No normalized frequency data available"])
            return

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (vectorized for performance, 2 decimal places)
        self._write_dataframe_rows(ws, df, decimal_places=2)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=50)

        # Freeze header row
        ws.freeze_panes = "A2"

    def _style_header_row(self, ws, row_num: int) -> None:
        """Apply styling to header row."""
        header_font = Font(bold=True)
        header_fill = PatternFill(
            start_color="DDDDDD",
            end_color="DDDDDD",
            fill_type="solid"
        )
        header_alignment = Alignment(horizontal="center", vertical="center")

        for cell in ws[row_num]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

    def _autofit_columns(self, ws, max_width: int = 50, max_sample_rows: int = 100) -> None:
        """
        Auto-fit column widths based on sampled content.

        Instead of iterating all cells (O(rows x columns)), samples up to
        max_sample_rows evenly distributed throughout the data to estimate
        column widths efficiently.

        Args:
            ws: Worksheet to auto-fit
            max_width: Maximum column width
            max_sample_rows: Maximum number of rows to sample for width estimation
        """
        for column_cells in ws.columns:
            max_length = 0
            column = column_cells[0].column_letter
            total_rows = len(column_cells)

            # Determine which rows to sample
            if total_rows <= max_sample_rows:
                # Small dataset - check all rows
                sample_indices = range(total_rows)
            else:
                # Large dataset - sample evenly distributed rows
                # Always include header (index 0) and last row
                step = total_rows / max_sample_rows
                sample_indices = [int(i * step) for i in range(max_sample_rows)]
                # Ensure we include the header row
                if 0 not in sample_indices:
                    sample_indices[0] = 0

            for idx in sample_indices:
                try:
                    cell = column_cells[idx]
                    cell_length = len(str(cell.value)) if cell.value else 0
                    max_length = max(max_length, cell_length)
                except (IndexError, Exception):
                    pass

            # Add padding and cap at max_width
            adjusted_width = min(max_length + 2, max_width)
            ws.column_dimensions[column].width = adjusted_width

    @staticmethod
    def _sanitize_value(val):
        """Sanitize a cell value for safe openpyxl serialization."""
        if pd.isna(val):
            return ""
        if isinstance(val, (float, np.floating)) and np.isinf(val):
            return ""
        if isinstance(val, np.integer):
            return int(val)
        if isinstance(val, np.floating):
            return float(val)
        if isinstance(val, str) and len(val) > 32767:
            return val[:32767]
        return val

    @staticmethod
    def _sanitize_sheet_name(name: str) -> str:
        """
        Sanitize a string for use as an Excel sheet name.

        Excel forbids these characters in sheet names: : \\ / ? * [ ]
        Sheet names also cannot start or end with an apostrophe.
        Maximum length is 31 characters.
        """
        # Replace Excel-forbidden characters with underscore
        name = re.sub(r'[:\\/?\*\[\]]', '_', name)
        # Strip leading/trailing apostrophes (Excel rejects these)
        name = name.strip("'")
        # Strip leading/trailing whitespace
        name = name.strip()
        # Truncate to 31 characters (Excel limit)
        name = name[:31]
        # Final strip in case truncation left trailing whitespace
        name = name.strip()
        return name

    def _write_dataframe_rows(
        self,
        ws,
        df: pd.DataFrame,
        decimal_places: Optional[int] = None
    ) -> None:
        """
        Write DataFrame rows to worksheet efficiently.

        This method streams rows one at a time to avoid memory spikes from
        creating full copies of the data (e.g., via df.values.tolist()).

        All values are sanitized to ensure valid OOXML output (no NaN, inf,
        or raw numpy types that would corrupt the xlsx file).

        Args:
            ws: Worksheet to write to
            df: DataFrame containing the data
            decimal_places: If provided, round float values to this many places
        """
        for row in df.itertuples(index=False, name=None):
            if decimal_places is not None:
                ws.append([
                    round(v, decimal_places) if isinstance(v := self._sanitize_value(cell), float) else v
                    for cell in row
                ])
            else:
                ws.append([self._sanitize_value(v) for v in row])

    def _remove_percent_total_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove all %total columns from DataFrame.

        Args:
            df: DataFrame with columns that may include %total

        Returns:
            DataFrame with %total columns removed
        """
        cols_to_keep = [col for col in df.columns if '%total' not in col.lower()]
        return df[cols_to_keep]

    def _reorder_concatenated_columns(
        self,
        df: pd.DataFrame,
        normalized_counts_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        Reorder columns by measurement type for Concatenated sheets.

        Order: sample info → counts → normalized counts (if any) → %parent → MFI

        Args:
            df: DataFrame with mixed columns
            normalized_counts_df: Optional DataFrame with volume-normalized counts

        Returns:
            DataFrame with reordered columns
        """
        cols = list(df.columns)

        # Categorize columns
        sample_cols = []  # sample_id, sample_name, scale_factor
        keyword_cols = []  # User keywords
        count_cols = []  # Raw counts
        scaled_count_cols = []  # Scaled counts (scale factor applied)
        parent_cols = []  # %parent
        mfi_cols = []  # MFI values

        for col in cols:
            if col in ('sample_id', 'sample_name', 'scale_factor'):
                sample_cols.append(col)
            elif '_scaled_count' in col:
                scaled_count_cols.append(col)
            elif '_count' in col and '%' not in col:
                count_cols.append(col)
            elif '%parent' in col.lower():
                parent_cols.append(col)
            elif any(metric in col for metric in ('_Mean_', '_Median_', '_GeoMean_')):
                mfi_cols.append(col)
            else:
                # Must be a keyword column
                keyword_cols.append(col)

        # Sort each group alphabetically for consistency
        count_cols.sort()
        scaled_count_cols.sort()
        parent_cols.sort()
        mfi_cols.sort()
        keyword_cols.sort()

        # Build new column order
        new_order = sample_cols + keyword_cols + count_cols + scaled_count_cols

        # Add normalized counts if available
        if normalized_counts_df is not None and not normalized_counts_df.empty:
            # Merge normalized counts into df
            # Rename columns to include denominator suffix
            norm_df = normalized_counts_df.copy()
            denom = int(self._volume_denominator)
            if denom == 1000:
                suffix = '_per_mL'
            else:
                suffix = f'_per_{denom}uL'

            # Rename count columns to normalized format
            new_names = {}
            for col in norm_df.columns:
                if col == 'sample_id':
                    continue
                # Replace _count with normalized suffix
                if col.endswith('_count'):
                    new_col = col.replace('_count', f'_count{suffix}')
                    new_names[col] = new_col

            norm_df = norm_df.rename(columns=new_names)

            # Merge into main df
            df = df.merge(norm_df, on='sample_id', how='left')

            # Add normalized columns to order
            norm_cols = sorted([col for col in norm_df.columns if col != 'sample_id'])
            new_order.extend(norm_cols)

        new_order.extend(parent_cols)
        new_order.extend(mfi_cols)

        # Return reordered DataFrame
        final_cols = [c for c in new_order if c in df.columns]
        return df[final_cols]

    def _get_volume_sheet_name(self, include_all: bool = False) -> str:
        """
        Generate descriptive sheet name for volume-normalized counts.

        Returns:
            Sheet name like "Counts_per_100uL" or "Counts_per_mL"
        """
        denom = int(self._volume_denominator)
        if denom == 1000:
            base = "Counts_per_mL"
        else:
            base = f"Counts_per_{denom}uL"

        return f"{base}_All" if include_all else base

    def _write_normalized_counts_sheet(
        self,
        ws,
        df: pd.DataFrame,
        description: str
    ) -> None:
        """
        Write volume-normalized counts to a worksheet.

        Args:
            ws: Worksheet to write to
            df: DataFrame with normalized counts (from StatisticsModel)
            description: Description for logging
        """
        logger.debug(f"Writing normalized counts sheet: {description}")

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Rename columns to include unit suffix
        denom = int(self._volume_denominator)
        if denom == 1000:
            suffix = '_per_mL'
        else:
            suffix = f'_per_{denom}uL'

        # Create new column names
        new_columns = []
        for col in df.columns:
            if col == 'sample_id':
                new_columns.append(col)
            elif col.endswith('_count'):
                # Replace _count with the volume suffix
                new_col = col.replace('_count', f'_count{suffix}')
                new_columns.append(new_col)
            else:
                new_columns.append(col)

        df = df.copy()
        df.columns = new_columns

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (4 decimal places for normalized counts)
        self._write_dataframe_rows(ws, df, decimal_places=4)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=40)

        # Freeze header row
        ws.freeze_panes = "B2"

    def _write_bead_normalized_counts_sheet(
        self,
        ws,
        df: pd.DataFrame,
        description: str
    ) -> None:
        """
        Write bead-normalized counts to a worksheet.

        Args:
            ws: Worksheet to write to
            df: DataFrame with bead-normalized counts (from StatisticsModel)
            description: Description for logging
        """
        logger.debug(f"Writing bead-normalized counts sheet: {description}")

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

        # Write header
        headers = list(df.columns)
        ws.append(headers)
        self._style_header_row(ws, 1)

        # Write data (4 decimal places for normalized counts)
        self._write_dataframe_rows(ws, df, decimal_places=4)

        # Auto-fit columns
        self._autofit_columns(ws, max_width=40)

        # Freeze header row and sample columns
        ws.freeze_panes = "C2"
