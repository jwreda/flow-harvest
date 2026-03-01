"""Export configuration dataclass for XLSXExporter."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict

from ..models.statistics_model import MFIMetric
from ..models.workspace_model import DataSource


@dataclass
class ExportConfig:
    """Configuration for XLSX export operations.

    Groups all export parameters except live model objects
    (workspace, keywords_model) and runtime params (filepath, callbacks).
    """

    # Gate and marker selection
    gate_ids: List[str] = field(default_factory=list)
    selected_markers: List[str] = field(default_factory=list)
    all_markers: List[str] = field(default_factory=list)
    mfi_metrics: List[MFIMetric] = field(default_factory=list)
    matrix_selections: Optional[List[tuple]] = None

    # Sheet inclusion flags
    include_wide_keywords: bool = False
    include_tidy_frequencies: bool = False
    include_all_sheets: bool = False

    # Data source and filtering
    data_source: DataSource = DataSource.AUTO
    selected_sample_ids: Optional[List[str]] = None
    selected_keywords: Optional[List[str]] = None
    index_columns: Optional[List[str]] = None

    # Frequency normalization
    reference_gate_ids: Optional[List[str]] = None
    descendant_depth: int = 0

    # Volume normalization
    volume_normalize: bool = False
    volume_denominator: float = 100.0

    # Bead normalization
    bead_normalize: bool = False
    bead_gate_id: Optional[str] = None
    bead_user_number: float = 1000.0
    bead_mode: str = "per_n_beads"

    # Scale factors
    scale_factors: Optional[Dict[str, float]] = None

    def __post_init__(self):
        """Validate field combinations."""
        if self.bead_normalize and not self.bead_gate_id:
            raise ValueError("bead_normalize=True requires bead_gate_id to be set")
        if self.volume_normalize and self.volume_denominator <= 0:
            raise ValueError("volume_denominator must be positive when volume_normalize is True")
        if self.bead_normalize and self.bead_user_number <= 0:
            raise ValueError("bead_user_number must be positive when bead_normalize is True")
