"""
XLSX Exporter - Generate Excel workbooks with flow cytometry analysis results.

This module provides:
- Multi-sheet workbook generation
- Gating strategy sheet (with full paths)
- Keywords sheets (tidy and wide formats)
- Statistics sheets (selected and all markers)
- Warnings sheet for calculation errors
"""

from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.table import Table, TableStyleInfo

from ..models.workspace_model import WorkspaceModel, DataSource
from ..models.keywords_model import KeywordsModel
from ..models.statistics_model import StatisticsModel, MFIMetric, FrequencyDataType
from ..utils.logging_config import get_logger
from ..utils.cancellation import CancellationToken, CancellationError

logger = get_logger("xlsx_exporter")


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
        gate_ids: List[str],
        selected_markers: List[str],
        all_markers: List[str],
        mfi_metrics: List[MFIMetric],
        include_wide_keywords: bool = False,
        include_tidy_frequencies: bool = False,
        include_all_sheets: bool = False,
        data_source: DataSource = DataSource.AUTO,
        index_columns: Optional[List[str]] = None,
        selected_keywords: Optional[List[str]] = None,
        selected_sample_ids: Optional[List[str]] = None,
        matrix_selections: Optional[List[tuple]] = None,
        reference_gate_ids: Optional[List[str]] = None,
        descendant_depth: int = 0
    ):
        """
        Initialize exporter.

        Args:
            workspace: Loaded WorkspaceModel
            keywords_model: KeywordsModel with sample data
            gate_ids: List of gate IDs to include
            selected_markers: User-selected marker channels
            all_markers: All available marker channels
            mfi_metrics: List of MFI metrics to calculate
            include_wide_keywords: Whether to include Keywords_Wide sheet
            include_tidy_frequencies: Whether to include tidy frequency sheets
            include_all_sheets: Whether to include _All sheets (Counts_All, Frequencies_All, MFI_All, Concatenated_All)
            data_source: Event data source (AUTO, RAW, or COMP)
            index_columns: Keywords to use as index columns in Keywords_Wide sheet
            selected_keywords: Keywords to include in export (None = all keywords)
            selected_sample_ids: List of sample IDs to export (None = all samples)
            matrix_selections: List of (gate_id, channel) tuples for sparse MFI selection
            reference_gate_ids: Gates to use as normalization references for frequency sheets
            descendant_depth: Max depth for descendant gates (0 = unlimited)
        """
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
        self._warnings: List[str] = []

        # Build matrix selections lookup for efficient checking
        self._matrix_selection_set = set(matrix_selections) if matrix_selections else None

    def export(
        self,
        filepath: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> None:
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

        logger.info(f"Starting export to {filepath}")
        logger.debug(f"Data source: {self._data_source.value}")

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
        # _Selected sheets (only if markers selected): Counts_Selected, Frequencies_Selected, MFI_Selected, Concatenated_Selected = 4
        # Optional: Keywords_Wide (+1), Tidy _All (+2), Tidy _Selected (+2 if markers selected)
        all_sheet_count = 4 if self._include_all_sheets else 0
        selected_sheet_count = 4 if has_selected_markers else 0
        tidy_all_count = 2 if self._include_tidy_frequencies and self._include_all_sheets else 0
        tidy_selected_count = 2 if self._include_tidy_frequencies and has_selected_markers else 0
        total_steps = 2 + all_sheet_count + selected_sheet_count + (1 if self._include_wide_keywords else 0) + tidy_all_count + tidy_selected_count
        current_step = 0

        # Sheet 1: Gating Strategy
        if status_callback:
            status_callback("Writing Gating_Strategy sheet...")
        ws_gates = wb.active
        ws_gates.title = "Gating_Strategy"
        self._write_gating_strategy(ws_gates)
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Sheet 2: Keywords (Tidy)
        if status_callback:
            status_callback("Writing Keywords sheet...")
        ws_keywords = wb.create_sheet("Keywords")
        self._write_keywords_tidy(ws_keywords)
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps)

        # Sheet 3 (optional): Keywords Wide
        if self._include_wide_keywords:
            if status_callback:
                status_callback("Writing Keywords_Wide sheet...")
            ws_keywords_wide = wb.create_sheet("Keywords_Wide")
            self._write_keywords_wide(ws_keywords_wide)
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
            stats_model.calculate_statistics(
                self._gate_ids,
                all_markers_combined,
                self._mfi_metrics,
                sample_ids=self._selected_sample_ids,  # Filter by selected samples
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

        # Sheet: Counts_All (wide format, counts only)
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing Counts_All sheet...")
            ws_counts_all = wb.create_sheet("Counts_All")
            self._write_frequencies_wide_sheet(
                ws_counts_all, stats_model, self._gate_ids, "All Gates Counts",
                data_type=FrequencyDataType.COUNTS
            )
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Counts_Selected (only if markers are selected)
        if has_selected_markers:
            if status_callback:
                status_callback("Writing Counts_Selected sheet...")
            ws_counts_selected = wb.create_sheet("Counts_Selected")
            self._write_frequencies_wide_sheet(
                ws_counts_selected, stats_model, self._gate_ids, "Selected Gates Counts",
                data_type=FrequencyDataType.COUNTS
            )
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
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Frequencies_Selected (only if markers are selected)
        if has_selected_markers:
            if status_callback:
                status_callback("Writing Frequencies_Selected sheet...")
            ws_freq_selected = wb.create_sheet("Frequencies_Selected")
            self._write_frequencies_wide_sheet(
                ws_freq_selected, stats_model, self._gate_ids, "Selected Gates Frequencies",
                data_type=FrequencyDataType.PERCENT
            )
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
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

            # Counts_Selected_Tidy (only if markers are selected)
            if has_selected_markers:
                if status_callback:
                    status_callback("Writing Counts_Selected_Tidy sheet...")
                ws_counts_selected_tidy = wb.create_sheet("Counts_Selected_Tidy")
                self._write_frequencies_tidy_sheet(
                    ws_counts_selected_tidy, stats_model, self._gate_ids, "Selected Gates Counts Tidy",
                    data_type=FrequencyDataType.COUNTS
                )
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
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps)

            # Frequencies_Selected_Tidy (only if markers are selected)
            if has_selected_markers:
                if status_callback:
                    status_callback("Writing Frequencies_Selected_Tidy sheet...")
                ws_freq_selected_tidy = wb.create_sheet("Frequencies_Selected_Tidy")
                self._write_frequencies_tidy_sheet(
                    ws_freq_selected_tidy, stats_model, self._gate_ids, "Selected Gates Frequencies Tidy",
                    data_type=FrequencyDataType.PERCENT
                )
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
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Concatenated_Selected - Gate stats + sparse MFI
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
                    include_gate_stats=True
                )
            else:
                self._write_statistics_sheet(
                    ws_concat_selected,
                    stats_model,
                    self._selected_markers,
                    "Concatenated Selected",
                    include_gate_stats=True
                )
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps)

        # Sheet: Concatenated_All - All gate stats + all MFI
        if self._include_all_sheets:
            if status_callback:
                status_callback("Writing Concatenated_All sheet...")
            ws_concat_all = wb.create_sheet("Concatenated_All")
            self._write_statistics_sheet(
                ws_concat_all,
                stats_model,
                self._all_markers,
                "Concatenated All",
                include_gate_stats=True
            )
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

        # Sheet (if warnings): Warnings
        if self._warnings:
            if status_callback:
                status_callback("Writing Warnings sheet...")
            ws_warnings = wb.create_sheet("Warnings")
            self._write_warnings(ws_warnings)
            logger.warning(f"Export completed with {len(self._warnings)} warnings")

        # Final cancellation check before saving
        if cancellation_token:
            cancellation_token.check_cancelled()

        # Save workbook
        if status_callback:
            status_callback("Saving Excel file...")
        wb.save(filepath)
        logger.info(f"Export saved to {filepath}")

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
        include_gate_stats: bool = True
    ) -> None:
        """
        Write statistics sheet using pre-calculated StatisticsModel.

        Args:
            ws: Worksheet to write to
            stats_model: Pre-calculated StatisticsModel with all needed data
            markers: List of markers to include in this sheet
            description: Description for logging
            include_gate_stats: If True, include count/%parent/%total columns.
                               If False, only include MFI columns (for MFI-only sheets).
        """
        logger.debug(f"Writing statistics sheet: {description}")

        # Get DataFrame (stats already calculated, just filters to requested markers)
        df = stats_model.get_statistics_dataframe(
            self._gate_ids,
            markers,
            self._mfi_metrics,
            include_keywords=True,
            include_gate_stats=include_gate_stats
        )

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

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
                freeze_col = chr(ord('A') + i)
                break

        ws.freeze_panes = f"{freeze_col}2"

    def _write_statistics_sheet_sparse(
        self,
        ws,
        stats_model: StatisticsModel,
        matrix_selections: List[tuple],
        description: str,
        include_gate_stats: bool = True
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
            include_gate_stats: If True, include count/%parent/%total for all tree-selected gates.
                               If False, only include MFI columns (for MFI-only sheets).
        """
        logger.debug(f"Writing sparse statistics sheet: {description}")
        logger.info(f"Sparse export: {len(matrix_selections)} specific gate/marker combinations")

        # Get DataFrame using sparse method
        df = stats_model.get_statistics_dataframe_sparse(
            selected_pairs=matrix_selections,
            metrics=self._mfi_metrics,
            include_keywords=True,
            include_gate_stats=include_gate_stats,
            all_gate_ids=self._gate_ids if include_gate_stats else None
        )

        if df.empty:
            ws.append([f"No data available for {description}"])
            return

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
                freeze_col = chr(ord('A') + i)
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
                freeze_col = chr(ord('A') + i)
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

    def _write_normalized_frequency_sheet(
        self,
        workbook,
        ref_gate_id: str,
        df: pd.DataFrame,
        existing_sheet_names: set
    ) -> str:
        """
        Write a single reference gate's normalized frequencies.

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
        base_sheet_name = f"Freq_of_{gate_name}"

        # Truncate to 31 chars (Excel limit) and handle duplicates
        base_sheet_name = base_sheet_name[:31]

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
            if '_count' in col or '_%of_ref' in col:
                freeze_col = chr(ord('A') + min(i, 25))  # Cap at 'Z'
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

        Args:
            ws: Worksheet to write to
            df: DataFrame containing the data
            decimal_places: If provided, round float values to this many places
                           and replace NaN with empty strings
        """
        if decimal_places is not None:
            # Preprocess: round floats and handle NaN in one pass
            def convert_value(val):
                if pd.isna(val):
                    return ""
                elif isinstance(val, float):
                    return round(val, decimal_places)
                return val

            # Stream row-by-row to avoid memory spike from tolist()
            for idx in range(len(df)):
                row = df.iloc[idx].values
                ws.append([convert_value(v) for v in row])
        else:
            # Simple case: use dataframe_to_rows (already imported)
            for row in dataframe_to_rows(df, index=False, header=False):
                ws.append(row)
