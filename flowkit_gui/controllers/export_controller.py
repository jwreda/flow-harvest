"""
Export Controller - Business logic for export operations.

Extracts validation, config construction, and export execution
from MainWindow into a testable, UI-independent controller.
"""

from typing import Optional, List, Dict, Callable, Any

from ..exporters.export_config import ExportConfig
from ..exporters.xlsx_exporter import XLSXExporter
from ..models.workspace_model import WorkspaceModel, DataSource
from ..models.keywords_model import KeywordsModel
from ..models.sample_selection_model import SampleSelectionModel
from ..models.gate_tree_model import GateTreeModel
from ..models.gate_marker_matrix_model import GateMarkerMatrixModel
from ..models.statistics_model import MFIMetric
from ..utils.logging_config import get_logger
from ..utils.memory_utils import check_memory_available, estimate_export_memory
from ..utils.cancellation import CancellationToken, CancellationError
from ..config import defaults as config_defaults

logger = get_logger("export_controller")


class ExportController:
    """Business logic controller for export operations.

    Handles validation, ExportConfig construction, and export execution.
    All UI concerns (dialogs, progress bars, threading) remain in MainWindow.
    This class does NOT import PyQt5.
    """

    def __init__(
        self,
        workspace_model: WorkspaceModel,
        keywords_model: KeywordsModel,
        sample_selection_model: SampleSelectionModel,
        gate_tree_model: GateTreeModel,
        gate_marker_matrix_model: GateMarkerMatrixModel,
    ):
        """Store model references.

        Args:
            workspace_model: Core FlowKit wrapper model.
            keywords_model: Keywords extraction model.
            sample_selection_model: Sample selection/scale factor model.
            gate_tree_model: Gate tree with checkbox support.
            gate_marker_matrix_model: Gate/marker matrix selections.
        """
        self._workspace_model = workspace_model
        self._keywords_model = keywords_model
        self._sample_selection_model = sample_selection_model
        self._gate_tree_model = gate_tree_model
        self._gate_marker_matrix_model = gate_marker_matrix_model

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_export_preconditions(self, ui_state: dict) -> Optional[str]:
        """Return an error message if export cannot proceed, or None if OK.

        Checks performed:
        1. At least one sample is selected.
        2. At least one gate is selected.
        3. At least one MFI metric is selected.

        Args:
            ui_state: Dictionary of UI state values gathered by MainWindow.

        Returns:
            A user-facing error string, or None when validation passes.
        """
        selected_sample_ids = self._sample_selection_model.get_selected_sample_ids()
        if not selected_sample_ids:
            return "Please select at least one sample to export."

        selected_gates = self._gate_tree_model.get_selected_gates()
        if not selected_gates:
            return "Please select at least one gate to export."

        mfi_metrics = ui_state.get("mfi_metrics", [])
        if not mfi_metrics:
            return "Please select at least one MFI metric."

        return None

    def check_compensation_warning(self, ui_state: dict) -> Optional[str]:
        """Check if compensation mode will cause problems.

        Returns:
            Warning message string if there is a concern, None otherwise.
        """
        data_source = ui_state.get("data_source", DataSource.AUTO)
        if data_source == DataSource.COMP:
            summary = self._sample_selection_model.get_selection_summary()
            missing_comp = summary.get("missing_compensation", 0)
            if missing_comp > 0:
                return (
                    f"{missing_comp} selected sample(s) are missing compensation.\n\n"
                    "Export will fail for these samples with 'Force Compensated' mode.\n\n"
                    "Continue anyway?"
                )
        return None

    def find_gates_without_data(
        self, selected_sample_ids: List[str]
    ) -> tuple:
        """Identify gates that don't exist in any selected sample.

        Returns:
            Tuple of (gates_to_exclude set, readable_names list, filtered_gate_ids list).
            gates_to_exclude is the set of gate IDs to remove.
            readable_names is a list of human-readable gate path strings.
            filtered_gate_ids is the gate ID list after exclusion.
        """
        gate_ids_initial = self._gate_tree_model.get_selected_gate_ids()
        gates_to_exclude = self._workspace_model.get_gates_without_data_in_samples(
            gate_ids=gate_ids_initial,
            sample_ids=selected_sample_ids,
        )

        readable_names = []
        if gates_to_exclude:
            for gate_id in gates_to_exclude:
                gate = self._gate_tree_model.get_gate_by_id(gate_id)
                if gate:
                    readable_names.append(gate.full_path_string)
                else:
                    readable_names.append(gate_id)

        filtered_gate_ids = [
            gid for gid in gate_ids_initial if gid not in gates_to_exclude
        ]
        return gates_to_exclude, readable_names, filtered_gate_ids

    def check_memory(
        self, num_samples: int, num_gates: int
    ) -> Optional[str]:
        """Check whether enough memory is available for the export.

        Returns:
            Warning message if memory is low, None otherwise.
        """
        estimated_mb = estimate_export_memory(num_samples, num_gates)
        if not check_memory_available(estimated_mb, operation_name="export"):
            return (
                f"This export may require approximately {estimated_mb} MB of memory, "
                f"but available system memory is low.\n\n"
                f"Suggestions:\n"
                f"  - Switch to Low Resource or Minimal mode in Settings > Performance Mode\n"
                f"  - Close other applications (browser, Zoom, etc.)\n"
                f"  - Export fewer samples or gates\n\n"
                f"Continue anyway?"
            )
        return None

    # ------------------------------------------------------------------
    # Config construction
    # ------------------------------------------------------------------

    def build_export_config(self, ui_state: dict) -> ExportConfig:
        """Build an ExportConfig from a dictionary of UI state values.

        The ui_state dict is populated by MainWindow._gather_export_ui_state().

        Expected keys:
            mfi_metrics: List[MFIMetric]
            data_source: DataSource
            matrix_selections: list of (gate_id, channel) tuples
            selected_markers: List[str]
            include_wide_keywords: bool
            include_tidy_frequencies: bool
            include_all_sheets: bool
            index_columns: Optional[List[str]]
            selected_keywords: List[str]
            reference_gate_ids: List[str]
            descendant_depth: int
            volume_normalize: bool
            volume_denominator: float
            bead_normalize: bool
            bead_gate_id: Optional[str]
            bead_user_number: float
            bead_mode: str
            scale_factors: Optional[Dict[str, float]]
            gate_ids: List[str]  (filtered gate IDs)
            allowed_system_keywords: set

        Returns:
            A fully populated ExportConfig instance.
        """
        matrix_selections = ui_state.get("matrix_selections", [])

        # Extract unique markers from matrix selections if present,
        # otherwise fall back to explicitly selected markers.
        if matrix_selections:
            selected_markers = list(
                set(channel for _, channel in matrix_selections)
            )
        else:
            selected_markers = ui_state.get("selected_markers", [])

        all_markers = self._workspace_model.channels

        include_wide_keywords = ui_state.get("include_wide_keywords", False)
        index_columns = (
            ui_state.get("index_columns") if include_wide_keywords else None
        )

        # Handle bead normalization — disable if no gate selected
        bead_normalize = ui_state.get("bead_normalize", False)
        bead_gate_id = ui_state.get("bead_gate_id")
        if bead_normalize and not bead_gate_id:
            bead_normalize = False
            logger.info(
                "Bead normalization checkbox checked but no gate selected - skipping"
            )

        # Normalise empty scale_factors dict to None
        scale_factors = ui_state.get("scale_factors")
        if scale_factors is not None and not scale_factors:
            scale_factors = None

        # Update keywords model with allowed system keywords
        allowed_system_keywords = ui_state.get("allowed_system_keywords", set())
        self._keywords_model.set_allowed_system_keywords(allowed_system_keywords)
        logger.info(f"System keywords for export: {allowed_system_keywords}")

        gate_ids = ui_state.get("gate_ids", [])
        selected_sample_ids = ui_state.get("selected_sample_ids")

        # Logging
        logger.info(
            f"Starting export: {len(selected_sample_ids or [])} samples, "
            f"{len(gate_ids)} gates"
        )
        logger.info(
            f"Matrix selections: {len(matrix_selections)} gate/marker combinations"
        )
        data_source = ui_state.get("data_source", DataSource.AUTO)
        logger.info(f"Data source: {data_source.value}")
        selected_keywords = ui_state.get("selected_keywords", [])
        logger.info(f"Selected keywords for export: {len(selected_keywords)}")
        if index_columns:
            logger.info(f"Index columns for Keywords_Wide: {index_columns}")
        reference_gate_ids = ui_state.get("reference_gate_ids", [])
        descendant_depth = ui_state.get("descendant_depth", 0)
        if reference_gate_ids:
            logger.info(
                f"Reference gates for normalization: {reference_gate_ids}"
            )
            logger.info(
                f"Descendant depth: "
                f"{'unlimited' if descendant_depth == 0 else descendant_depth}"
            )
        volume_normalize = ui_state.get("volume_normalize", False)
        volume_denominator = ui_state.get("volume_denominator", 100.0)
        if volume_normalize:
            logger.info(
                f"Volume normalization enabled: per {volume_denominator} \u03bcL"
            )
        if bead_normalize and bead_gate_id:
            bead_user_number = ui_state.get("bead_user_number", 1000.0)
            bead_mode = ui_state.get("bead_mode", "per_n_beads")
            logger.info(
                f"Bead normalization enabled: gate={bead_gate_id}, "
                f"number={bead_user_number}, mode={bead_mode}"
            )
        if scale_factors:
            logger.info(
                f"Scale factors enabled for {len(scale_factors)} samples"
            )

        return ExportConfig(
            gate_ids=gate_ids,
            selected_markers=selected_markers,
            all_markers=all_markers,
            mfi_metrics=ui_state.get("mfi_metrics", []),
            include_wide_keywords=include_wide_keywords,
            include_tidy_frequencies=ui_state.get("include_tidy_frequencies", False),
            include_all_sheets=ui_state.get("include_all_sheets", False),
            data_source=data_source,
            index_columns=index_columns,
            selected_keywords=selected_keywords,
            selected_sample_ids=selected_sample_ids,
            matrix_selections=matrix_selections if matrix_selections else None,
            reference_gate_ids=reference_gate_ids if reference_gate_ids else None,
            descendant_depth=descendant_depth,
            volume_normalize=volume_normalize,
            volume_denominator=volume_denominator,
            bead_normalize=bead_normalize,
            bead_gate_id=bead_gate_id,
            bead_user_number=ui_state.get("bead_user_number", 1000.0),
            bead_mode=ui_state.get("bead_mode", "per_n_beads"),
            scale_factors=scale_factors,
        )

    # ------------------------------------------------------------------
    # Pre-analysis
    # ------------------------------------------------------------------

    def pre_analyze_samples(
        self,
        selected_sample_ids: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, str]:
        """Analyze samples before export, respecting performance settings.

        Uses parallel or sequential analysis based on config_defaults.

        Args:
            selected_sample_ids: Sample IDs to analyze.
            progress_callback: Optional (completed, total) callback for UI.

        Returns:
            Dict of {sample_id: error_message} for any analysis failures.
        """
        effective_workers = config_defaults.MAX_PARALLEL_WORKERS

        if effective_workers is None or effective_workers > 1:
            self._workspace_model.analyze_samples_parallel(
                sample_ids=selected_sample_ids,
                max_workers=effective_workers,
                progress_callback=progress_callback,
            )
        else:
            for i, sid in enumerate(selected_sample_ids):
                self._workspace_model.analyze_samples(sample_ids=[sid])
                if progress_callback:
                    progress_callback(i + 1, len(selected_sample_ids))

        return self._workspace_model.get_analysis_failures()

    # ------------------------------------------------------------------
    # Export execution
    # ------------------------------------------------------------------

    def execute_export(
        self,
        config: ExportConfig,
        output_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ):
        """Run the export and return the ExportSummary.

        Args:
            config: Fully populated ExportConfig.
            output_path: Filesystem path for the output .xlsx file.
            progress_callback: Optional (current, total) progress callback.
            status_callback: Optional status message callback.
            cancellation_token: Optional cancellation token.

        Returns:
            An ExportSummary dataclass from XLSXExporter.export().
        """
        exporter = XLSXExporter(
            workspace=self._workspace_model,
            keywords_model=self._keywords_model,
            config=config,
        )

        summary = exporter.export(
            output_path,
            progress_callback=progress_callback,
            status_callback=status_callback,
            cancellation_token=cancellation_token,
        )

        logger.info(f"Export completed: {output_path}")
        return summary

    def clear_data_cache(self) -> None:
        """Clear workspace data caches after export to free memory."""
        self._workspace_model.clear_data_cache()
        logger.info("Cleared data caches after export (analysis state preserved)")
