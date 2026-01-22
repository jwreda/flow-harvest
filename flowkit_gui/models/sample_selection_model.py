"""
Sample Selection Model - Qt model for sample selection with group support.

This module provides:
- SampleSelectionModel for Qt tree view with group-based sample organization
- Checkbox sync across multiple group memberships
- Compensation status indicators
"""

from typing import Dict, List, Optional, Set, Any
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QBrush, QColor, QIcon

from .workspace_model import Sample, SampleCompensationAssignment
from ..utils.logging_config import get_logger

logger = get_logger("sample_selection_model")


class SampleSelectionModel(QStandardItemModel):
    """
    Qt model for displaying samples organized by groups with checkboxes.

    Features:
    - Hierarchical display of groups with sample children
    - Samples can appear in multiple groups (checkboxes stay synced)
    - Tri-state group checkboxes based on child selection
    - Compensation status with colored dots matching FlowJo matrix colors
    """

    COLUMN_SAMPLE = 0
    COLUMN_EVENTS = 1
    COLUMN_STATUS = 2

    # Signal emitted when sample selection changes
    selectionChanged = pyqtSignal(str, bool)  # sample_id, is_selected

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Sample", "Events", "Comp"])

        # Single source of truth for selection state
        self._selection_state: Dict[str, bool] = {}  # sample_id -> is_selected

        # Track all QStandardItem instances per sample (for sync)
        self._sample_items: Dict[str, List[QStandardItem]] = {}  # sample_id -> list of items

        # Track group items for tri-state updates
        self._group_items: Dict[str, QStandardItem] = {}  # group_name -> item

        # Store sample info for reference
        self._samples: Dict[str, Sample] = {}  # sample_id -> Sample

        # Compensation status (legacy: 'valid'/'missing')
        self._compensation_status: Dict[str, str] = {}

        # Compensation assignments with colors (new: from WSP parsing)
        self._compensation_assignments: Dict[str, SampleCompensationAssignment] = {}

        # Prevent recursive updates during sync
        self._updating = False

        # Connect item changed signal
        self.itemChanged.connect(self._on_item_changed)

    def clear_samples(self):
        """Clear all samples from the model."""
        self._updating = True
        self.clear()
        self.setHorizontalHeaderLabels(["Sample", "Events", "Comp"])
        self._selection_state.clear()
        self._sample_items.clear()
        self._group_items.clear()
        self._samples.clear()
        self._compensation_status.clear()
        self._compensation_assignments.clear()
        self._updating = False

    def populate_from_groups(
        self,
        groups: Dict[str, List[str]],
        all_samples: List[Sample],
        compensation_status: Optional[Dict[str, str]] = None,
        compensation_assignments: Optional[Dict[str, SampleCompensationAssignment]] = None,
        default_selected: bool = True
    ) -> None:
        """
        Build tree from group data.

        Args:
            groups: Dict mapping group name to list of sample IDs
            all_samples: List of all Sample objects
            compensation_status: Optional dict of sample_id -> 'valid'/'missing'/'none'
            compensation_assignments: Optional dict of sample_id -> SampleCompensationAssignment
                                     (includes matrix color from WSP)
            default_selected: Whether samples are selected by default
        """
        self.clear_samples()
        self._updating = True

        # Store sample info
        for sample in all_samples:
            self._samples[sample.sample_id] = sample
            self._selection_state[sample.sample_id] = default_selected

        # Store compensation status and assignments
        if compensation_status:
            self._compensation_status = compensation_status
        if compensation_assignments:
            self._compensation_assignments = compensation_assignments

        # Track which samples are in groups
        samples_in_groups: Set[str] = set()

        # Create group nodes with sample children
        for group_name, sample_ids in sorted(groups.items()):
            group_item = self._create_group_item(group_name, len(sample_ids))
            self._group_items[group_name] = group_item

            for sample_id in sample_ids:
                samples_in_groups.add(sample_id)
                if sample_id in self._samples:
                    sample = self._samples[sample_id]
                    self._add_sample_to_group(sample, group_item)

            self.appendRow([group_item, QStandardItem(), QStandardItem()])

        # Create "Ungrouped" section for samples not in any group
        ungrouped_samples = [
            s for s in all_samples
            if s.sample_id not in samples_in_groups
        ]
        if ungrouped_samples:
            ungrouped_item = self._create_group_item("Ungrouped", len(ungrouped_samples))
            self._group_items["Ungrouped"] = ungrouped_item

            for sample in ungrouped_samples:
                self._add_sample_to_group(sample, ungrouped_item)

            self.appendRow([ungrouped_item, QStandardItem(), QStandardItem()])

        # If no groups exist, show all samples as flat list
        if not groups and not ungrouped_samples:
            for sample in all_samples:
                self._add_sample_to_root(sample)

        self._updating = False

        # Update all group tri-states
        self._update_all_group_states()

        logger.info(f"Populated sample selection: {len(all_samples)} samples in {len(groups)} groups")

    def _create_group_item(self, name: str, count: int) -> QStandardItem:
        """Create a group header item."""
        item = QStandardItem(f"{name} ({count})")
        item.setCheckable(True)
        item.setCheckState(Qt.Checked)
        item.setData("__group__", Qt.UserRole)  # Mark as group
        item.setData(name, Qt.UserRole + 1)  # Store group name
        # Make group items bold
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def _add_sample_to_group(self, sample: Sample, group_item: QStandardItem) -> None:
        """Add a sample as a child of a group item."""
        item = self._create_sample_item(sample)

        # Track this item for sync
        if sample.sample_id not in self._sample_items:
            self._sample_items[sample.sample_id] = []
        self._sample_items[sample.sample_id].append(item)

        # Create event count column
        events_str = f"{sample.event_count:,}" if sample.event_count > 0 else "No data"
        events_item = QStandardItem(events_str)
        events_item.setEditable(False)
        events_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if sample.event_count == 0:
            events_item.setForeground(QBrush(QColor("#888888")))

        # Create compensation status column with colored dot
        status_item = self._create_compensation_status_item(sample.sample_id)

        group_item.appendRow([item, events_item, status_item])

    def _create_compensation_status_item(self, sample_id: str) -> QStandardItem:
        """Create a status item showing compensation with colored dot.

        Uses the compensation assignment color from WSP if available,
        otherwise falls back to legacy status indicators.
        """
        status_item = QStandardItem()
        status_item.setEditable(False)
        status_item.setTextAlignment(Qt.AlignCenter)
        self._apply_compensation_display(status_item, sample_id)
        return status_item

    def _apply_compensation_display(self, status_item: QStandardItem, sample_id: str) -> None:
        """Apply compensation status display to a status item.

        This is the single source of truth for compensation display logic,
        used by both _create_compensation_status_item and _update_status_item_display.
        """
        # Color constants
        COLOR_VALID = "#22c55e"      # Green - has compensation
        COLOR_NONE = "#808080"       # Gray - no compensation (valid for unmixed)
        COLOR_ERROR = "#ef4444"      # Red - compensation error
        COLOR_UNKNOWN = "#888888"    # Dark gray - unknown status

        # Try to use WSP-parsed assignment with color
        assignment = self._compensation_assignments.get(sample_id)
        if assignment is not None:
            if assignment.matrix_name is not None:
                # Has compensation - show colored dot with matrix color
                color = assignment.color or COLOR_VALID
                status_item.setText("●")
                status_item.setForeground(QBrush(QColor(color)))
                tooltip = f"Compensation: {assignment.matrix_name}"
                if assignment.spectral:
                    tooltip += " (spectral)"
                status_item.setToolTip(tooltip)
            else:
                # No compensation assigned - gray dot (valid for unmixed data)
                status_item.setText("○")
                status_item.setForeground(QBrush(QColor(COLOR_NONE)))
                status_item.setToolTip("No compensation (unmixed data)")
            return

        # Fall back to legacy status if no assignment info
        comp_status = self._compensation_status.get(sample_id, "")
        if comp_status == "valid":
            status_item.setText("●")
            status_item.setForeground(QBrush(QColor(COLOR_VALID)))
            status_item.setToolTip("Compensation available")
        elif comp_status == "none":
            status_item.setText("○")
            status_item.setForeground(QBrush(QColor(COLOR_NONE)))
            status_item.setToolTip("No compensation (unmixed data)")
        elif comp_status == "missing":
            status_item.setText("✗")
            status_item.setForeground(QBrush(QColor(COLOR_ERROR)))
            status_item.setToolTip("Compensation error")
        else:
            status_item.setText("?")
            status_item.setForeground(QBrush(QColor(COLOR_UNKNOWN)))
            status_item.setToolTip("Compensation status unknown")

    def _add_sample_to_root(self, sample: Sample) -> None:
        """Add a sample directly to the root (no group)."""
        item = self._create_sample_item(sample)

        if sample.sample_id not in self._sample_items:
            self._sample_items[sample.sample_id] = []
        self._sample_items[sample.sample_id].append(item)

        events_str = f"{sample.event_count:,}" if sample.event_count > 0 else "No data"
        events_item = QStandardItem(events_str)
        events_item.setEditable(False)

        # Use colored dot status
        status_item = self._create_compensation_status_item(sample.sample_id)

        self.appendRow([item, events_item, status_item])

    def _create_sample_item(self, sample: Sample) -> QStandardItem:
        """Create a sample item with checkbox."""
        item = QStandardItem(sample.name)
        item.setCheckable(True)
        is_selected = self._selection_state.get(sample.sample_id, True)
        item.setCheckState(Qt.Checked if is_selected else Qt.Unchecked)
        item.setData(sample.sample_id, Qt.UserRole)  # Store sample_id
        item.setToolTip(f"Sample ID: {sample.sample_id}\nPath: {sample.fcs_path or 'N/A'}")
        return item

    def _on_item_changed(self, item: QStandardItem) -> None:
        """Handle item checkbox changes."""
        if self._updating:
            return

        self._updating = True
        try:
            data = item.data(Qt.UserRole)

            if data == "__group__":
                # Group checkbox changed - update all children
                group_name = item.data(Qt.UserRole + 1)
                new_state = item.checkState()
                if new_state != Qt.PartiallyChecked:  # Only act on full check/uncheck
                    self._set_group_children_state(item, new_state == Qt.Checked)
            elif data:
                # Sample checkbox changed - sync across groups
                sample_id = data
                is_checked = item.checkState() == Qt.Checked
                self._sync_sample_selection(sample_id, is_checked, source_item=item)

        finally:
            self._updating = False

        # Update group tri-states after any change
        self._update_all_group_states()

    def _set_group_children_state(self, group_item: QStandardItem, selected: bool) -> None:
        """Set selection state for all samples in a group."""
        for i in range(group_item.rowCount()):
            child = group_item.child(i, self.COLUMN_SAMPLE)
            if child:
                sample_id = child.data(Qt.UserRole)
                if sample_id and sample_id != "__group__":
                    self._selection_state[sample_id] = selected
                    # Sync across all instances
                    for item in self._sample_items.get(sample_id, []):
                        item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
                    self.selectionChanged.emit(sample_id, selected)

    def _sync_sample_selection(self, sample_id: str, is_selected: bool, source_item: QStandardItem) -> None:
        """Sync selection state across all instances of a sample."""
        self._selection_state[sample_id] = is_selected

        # Update all other items for this sample
        for item in self._sample_items.get(sample_id, []):
            if item is not source_item:
                item.setCheckState(Qt.Checked if is_selected else Qt.Unchecked)

        self.selectionChanged.emit(sample_id, is_selected)

    def _update_all_group_states(self) -> None:
        """Update tri-state for all group items based on children."""
        self._updating = True
        try:
            for group_item in self._group_items.values():
                self._update_group_state(group_item)
        finally:
            self._updating = False

    def _update_group_state(self, group_item: QStandardItem) -> None:
        """Update group checkbox state based on children."""
        checked_count = 0
        total_count = group_item.rowCount()

        for i in range(total_count):
            child = group_item.child(i, self.COLUMN_SAMPLE)
            if child and child.checkState() == Qt.Checked:
                checked_count += 1

        if checked_count == 0:
            group_item.setCheckState(Qt.Unchecked)
        elif checked_count == total_count:
            group_item.setCheckState(Qt.Checked)
        else:
            group_item.setCheckState(Qt.PartiallyChecked)

    def get_selected_sample_ids(self) -> List[str]:
        """Get list of selected sample IDs."""
        return [sid for sid, selected in self._selection_state.items() if selected]

    def get_selected_samples(self) -> List[Sample]:
        """Get list of selected Sample objects."""
        return [
            self._samples[sid]
            for sid in self.get_selected_sample_ids()
            if sid in self._samples
        ]

    def select_all(self) -> None:
        """Select all samples."""
        self._updating = True
        try:
            for sample_id, items in self._sample_items.items():
                self._selection_state[sample_id] = True
                for item in items:
                    item.setCheckState(Qt.Checked)
        finally:
            self._updating = False
        self._update_all_group_states()

    def deselect_all(self) -> None:
        """Deselect all samples."""
        self._updating = True
        try:
            for sample_id, items in self._sample_items.items():
                self._selection_state[sample_id] = False
                for item in items:
                    item.setCheckState(Qt.Unchecked)
        finally:
            self._updating = False
        self._update_all_group_states()

    def invert_selection(self) -> None:
        """Invert selection state for all samples."""
        self._updating = True
        try:
            for sample_id, items in self._sample_items.items():
                new_state = not self._selection_state.get(sample_id, False)
                self._selection_state[sample_id] = new_state
                for item in items:
                    item.setCheckState(Qt.Checked if new_state else Qt.Unchecked)
        finally:
            self._updating = False
        self._update_all_group_states()

    def get_selection_summary(self) -> Dict[str, int]:
        """Get summary of selection state."""
        selected = sum(1 for v in self._selection_state.values() if v)
        total = len(self._selection_state)

        # Count compensation status for selected samples
        # Check assignments first (more accurate), fall back to legacy status
        with_comp = 0
        without_comp = 0
        comp_error = 0

        for sid, sel in self._selection_state.items():
            if not sel:
                continue

            assignment = self._compensation_assignments.get(sid)
            if assignment is not None:
                if assignment.matrix_name is not None:
                    with_comp += 1
                else:
                    without_comp += 1
            else:
                # Fall back to legacy status
                status = self._compensation_status.get(sid, "")
                if status == "valid":
                    with_comp += 1
                elif status == "none":
                    without_comp += 1
                elif status == "missing":
                    comp_error += 1

        return {
            "selected": selected,
            "total": total,
            "with_compensation": with_comp,
            "without_compensation": without_comp,
            "compensation_error": comp_error,
            # Legacy keys for compatibility
            "valid_compensation": with_comp,
            "missing_compensation": comp_error
        }

    def update_compensation_status(
        self,
        status: Dict[str, str],
        assignments: Optional[Dict[str, SampleCompensationAssignment]] = None
    ) -> None:
        """Update compensation status display for all samples.

        Args:
            status: Dict of sample_id -> 'valid'/'none'/'missing'/'error'
            assignments: Optional dict of sample_id -> SampleCompensationAssignment
                        (includes matrix color from WSP)
        """
        self._compensation_status = status
        if assignments:
            self._compensation_assignments = assignments

        # Update status column for all sample items
        for sample_id, items in self._sample_items.items():
            for item in items:
                # Find the status column sibling
                parent = item.parent()
                if parent:
                    row = item.row()
                    status_item = parent.child(row, self.COLUMN_STATUS)
                    if status_item:
                        self._update_status_item_display(status_item, sample_id)

    def _update_status_item_display(self, status_item: QStandardItem, sample_id: str) -> None:
        """Update a status item's display based on compensation info."""
        self._apply_compensation_display(status_item, sample_id)
