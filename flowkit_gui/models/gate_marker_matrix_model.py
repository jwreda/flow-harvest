"""
Gate × Marker Matrix Model - Qt model for sparse gate/marker selection.

This module provides the data model for a matrix where:
- Rows = gates (from the gating hierarchy)
- Columns = markers (fluorescent channels)
- Cells = checkboxes for selecting which MFI calculations to perform

The model uses sparse storage - only selected combinations are stored.
"""

from typing import Dict, List, Optional, Set, Tuple, Any
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal

from .workspace_model import ChannelInfo, GateInfo
from ..utils.logging_config import get_logger

logger = get_logger("gate_marker_matrix_model")


def _disambiguate_duplicate_names(gate_name: str, gate_ids: List[str]) -> Dict[str, str]:
    """
    Add minimal parent prefix to disambiguate duplicate gate names.

    Args:
        gate_name: The base name that appears multiple times
        gate_ids: List of full path gate_ids sharing this name

    Returns:
        Dict mapping gate_id to disambiguated display name
    """
    # Parse paths: "Cells/Live/CD4+/Reporter+" -> ["Cells", "Live", "CD4+", "Reporter+"]
    parsed_paths = {gate_id: gate_id.split('/') for gate_id in gate_ids}

    # Start with 1 parent prefix level
    prefix_levels = 1
    max_depth = max(len(p) for p in parsed_paths.values())

    while prefix_levels < max_depth:
        # Build candidate names with current prefix level
        candidates: Dict[str, str] = {}
        for gate_id, path_parts in parsed_paths.items():
            # Get the last (prefix_levels + 1) components
            # e.g., prefix_levels=1 for "Cells/Live/CD4+/Reporter+" -> "CD4+/Reporter+"
            start_idx = max(0, len(path_parts) - prefix_levels - 1)
            display_name = "/".join(path_parts[start_idx:])
            candidates[gate_id] = display_name

        # Check if all candidate names are unique
        seen_names: Set[str] = set()
        all_unique = True
        for display_name in candidates.values():
            if display_name in seen_names:
                all_unique = False
                break
            seen_names.add(display_name)

        if all_unique:
            return candidates

        # Need more prefix levels
        prefix_levels += 1

    # Fallback: use full paths (should rarely happen)
    return {gate_id: gate_id for gate_id in gate_ids}


class GateMarkerMatrixModel(QAbstractTableModel):
    """
    Qt model for gate × marker selection matrix.

    Uses sparse storage - only stores (gate_id, channel) pairs that are selected.
    This is efficient for typical use cases where users select specific combinations
    rather than the entire matrix.
    """

    # Signal emitted when selection changes
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Gate info: list of (gate_id, gate_name, depth)
        self._gates: List[Tuple[str, str, int]] = []

        # Marker info: list of (channel, display_name)
        self._markers: List[Tuple[str, str]] = []

        # Sparse selection storage: set of (gate_id, channel) tuples
        self._selections: Set[Tuple[str, str]] = set()

        # Disambiguated display names: gate_id -> display name
        self._display_names: Dict[str, str] = {}

    def _compute_display_names(self) -> None:
        """
        Compute disambiguated display names for all gates.

        For gates with unique names, uses the simple name.
        For gates with duplicate names, adds minimal parent prefix until unique.
        Populates self._display_names dict mapping gate_id -> display name.
        """
        self._display_names.clear()

        if not self._gates:
            return

        # Step 1: Count occurrences of each base name
        name_to_gate_ids: Dict[str, List[str]] = {}
        for gate_id, gate_name, _ in self._gates:
            if gate_name not in name_to_gate_ids:
                name_to_gate_ids[gate_name] = []
            name_to_gate_ids[gate_name].append(gate_id)

        # Step 2: Build display names
        for gate_name, gate_ids in name_to_gate_ids.items():
            if len(gate_ids) == 1:
                # Unique name - use as-is
                self._display_names[gate_ids[0]] = gate_name
            else:
                # Duplicate names - need disambiguation
                disambiguated = _disambiguate_duplicate_names(gate_name, gate_ids)
                self._display_names.update(disambiguated)

    def set_gates_and_markers(
        self,
        gates: List[GateInfo],
        markers: List[ChannelInfo]
    ) -> None:
        """
        Initialize the matrix dimensions with gates and markers.

        Args:
            gates: List of GateInfo objects (become rows)
            markers: List of ChannelInfo objects (become columns)
        """
        self.beginResetModel()

        self._gates = [(g.gate_id, g.name, g.depth) for g in gates]
        self._markers = [(m.pnn_label, m.display_name) for m in markers]
        self._selections.clear()
        self._compute_display_names()

        self.endResetModel()

        logger.info(f"Matrix initialized: {len(self._gates)} gates × {len(self._markers)} markers")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of rows (gates)."""
        if parent.isValid():
            return 0
        return len(self._gates)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of columns (markers)."""
        if parent.isValid():
            return 0
        return len(self._markers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Return data for the given index and role."""
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self._gates):
            return None
        if col < 0 or col >= len(self._markers):
            return None

        gate_id, gate_name, _ = self._gates[row]
        channel, _ = self._markers[col]

        if role == Qt.CheckStateRole:
            return Qt.Checked if (gate_id, channel) in self._selections else Qt.Unchecked

        if role == Qt.ToolTipRole:
            _, marker_name = self._markers[col]
            selected = "Selected" if (gate_id, channel) in self._selections else "Not selected"
            return f"{marker_name} MFI for {gate_name}\n{selected}"

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        """Set data for the given index."""
        if not index.isValid() or role != Qt.CheckStateRole:
            return False

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self._gates):
            return False
        if col < 0 or col >= len(self._markers):
            return False

        gate_id, _, _ = self._gates[row]
        channel, _ = self._markers[col]
        key = (gate_id, channel)

        if value == Qt.Checked:
            self._selections.add(key)
        else:
            self._selections.discard(key)

        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.selectionChanged.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Return item flags - all cells are checkable."""
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole
    ) -> Any:
        """Return header data."""
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                # Column headers = marker names
                if 0 <= section < len(self._markers):
                    _, display_name = self._markers[section]
                    return display_name
            else:
                # Row headers = disambiguated gate names (without depth dots - custom header paints those)
                if 0 <= section < len(self._gates):
                    gate_id, gate_name, _ = self._gates[section]
                    return self._display_names.get(gate_id, gate_name)
        elif role == Qt.UserRole:
            # Return depth for vertical headers (used by ColoredDepthHeaderView)
            if orientation == Qt.Vertical and 0 <= section < len(self._gates):
                _, _, depth = self._gates[section]
                return depth
        elif role == Qt.ToolTipRole:
            if orientation == Qt.Horizontal and 0 <= section < len(self._markers):
                channel, display_name = self._markers[section]
                return f"{display_name}\nChannel: {channel}"
            elif orientation == Qt.Vertical and 0 <= section < len(self._gates):
                gate_id, gate_name, depth = self._gates[section]
                return f"{gate_name}\nDepth: {depth}\nFull path: {gate_id}\nClick to toggle entire row"
        return None

    # Selection manipulation methods

    def toggle_selection(self, gate_id: str, channel: str) -> None:
        """Toggle selection state for a gate/marker combination."""
        key = (gate_id, channel)
        if key in self._selections:
            self._selections.discard(key)
        else:
            self._selections.add(key)
        self._emit_data_changed_for_cell(gate_id, channel)
        self.selectionChanged.emit()

    def is_selected(self, gate_id: str, channel: str) -> bool:
        """Check if a gate/marker combination is selected."""
        return (gate_id, channel) in self._selections

    def select_row(self, row: int) -> None:
        """Select all markers for a gate (entire row)."""
        if 0 <= row < len(self._gates):
            gate_id, _, _ = self._gates[row]
            for channel, _ in self._markers:
                self._selections.add((gate_id, channel))
            self._emit_row_changed(row)
            self.selectionChanged.emit()

    def deselect_row(self, row: int) -> None:
        """Deselect all markers for a gate (entire row)."""
        if 0 <= row < len(self._gates):
            gate_id, _, _ = self._gates[row]
            for channel, _ in self._markers:
                self._selections.discard((gate_id, channel))
            self._emit_row_changed(row)
            self.selectionChanged.emit()

    def toggle_row(self, row: int) -> None:
        """Toggle entire row - if any selected, deselect all; otherwise select all."""
        if 0 <= row < len(self._gates):
            gate_id, _, _ = self._gates[row]
            # Check if any in this row are selected
            any_selected = any(
                (gate_id, channel) in self._selections
                for channel, _ in self._markers
            )
            if any_selected:
                self.deselect_row(row)
            else:
                self.select_row(row)

    def select_column(self, col: int) -> None:
        """Select all gates for a marker (entire column)."""
        if 0 <= col < len(self._markers):
            channel, _ = self._markers[col]
            for gate_id, _, _ in self._gates:
                self._selections.add((gate_id, channel))
            self._emit_column_changed(col)
            self.selectionChanged.emit()

    def deselect_column(self, col: int) -> None:
        """Deselect all gates for a marker (entire column)."""
        if 0 <= col < len(self._markers):
            channel, _ = self._markers[col]
            for gate_id, _, _ in self._gates:
                self._selections.discard((gate_id, channel))
            self._emit_column_changed(col)
            self.selectionChanged.emit()

    def toggle_column(self, col: int) -> None:
        """Toggle entire column - if any selected, deselect all; otherwise select all."""
        if 0 <= col < len(self._markers):
            channel, _ = self._markers[col]
            any_selected = any(
                (gate_id, channel) in self._selections
                for gate_id, _, _ in self._gates
            )
            if any_selected:
                self.deselect_column(col)
            else:
                self.select_column(col)

    def select_all(self) -> None:
        """Select all gate/marker combinations."""
        self.beginResetModel()
        self._selections = set(
            (gate_id, channel)
            for gate_id, _, _ in self._gates
            for channel, _ in self._markers
        )
        self.endResetModel()
        self.selectionChanged.emit()

    def clear_all(self) -> None:
        """Clear all selections."""
        self.beginResetModel()
        self._selections.clear()
        self.endResetModel()
        self.selectionChanged.emit()

    def get_selections(self) -> List[Tuple[str, str]]:
        """
        Get list of selected (gate_id, channel) tuples.

        Returns:
            List of tuples, each containing (gate_id, channel_name)
        """
        return list(self._selections)

    def get_selections_by_gate(self) -> Dict[str, List[str]]:
        """
        Get selections organized by gate.

        Returns:
            Dict mapping gate_id to list of selected channels
        """
        result: Dict[str, List[str]] = {}
        for gate_id, channel in self._selections:
            if gate_id not in result:
                result[gate_id] = []
            result[gate_id].append(channel)
        return result

    def get_selections_by_channel(self) -> Dict[str, List[str]]:
        """
        Get selections organized by channel.

        Returns:
            Dict mapping channel to list of selected gate_ids
        """
        result: Dict[str, List[str]] = {}
        for gate_id, channel in self._selections:
            if channel not in result:
                result[channel] = []
            result[channel].append(gate_id)
        return result

    def get_selection_count(self) -> int:
        """Get number of selected combinations."""
        return len(self._selections)

    def get_gate_id_for_row(self, row: int) -> Optional[str]:
        """Get gate ID for a row index."""
        if 0 <= row < len(self._gates):
            return self._gates[row][0]
        return None

    def get_channel_for_column(self, col: int) -> Optional[str]:
        """Get channel name for a column index."""
        if 0 <= col < len(self._markers):
            return self._markers[col][0]
        return None

    # Helper methods for emitting data changed signals

    def _emit_data_changed_for_cell(self, gate_id: str, channel: str) -> None:
        """Emit dataChanged for a specific cell."""
        row = next((i for i, (gid, _, _) in enumerate(self._gates) if gid == gate_id), -1)
        col = next((i for i, (ch, _) in enumerate(self._markers) if ch == channel), -1)
        if row >= 0 and col >= 0:
            idx = self.index(row, col)
            self.dataChanged.emit(idx, idx, [Qt.CheckStateRole])

    def _emit_row_changed(self, row: int) -> None:
        """Emit dataChanged for an entire row."""
        if self._markers:
            start_idx = self.index(row, 0)
            end_idx = self.index(row, len(self._markers) - 1)
            self.dataChanged.emit(start_idx, end_idx, [Qt.CheckStateRole])

    def _emit_column_changed(self, col: int) -> None:
        """Emit dataChanged for an entire column."""
        if self._gates:
            start_idx = self.index(0, col)
            end_idx = self.index(len(self._gates) - 1, col)
            self.dataChanged.emit(start_idx, end_idx, [Qt.CheckStateRole])
