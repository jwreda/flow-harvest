"""
Gate Tree Model - Qt model for displaying gating hierarchy with checkboxes.

This module provides:
- Gate dataclass for representing gates
- GateTreeModel for Qt tree view with checkbox support
- Reference gate tracking for normalization features
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from PyQt5.QtCore import Qt, QModelIndex
from PyQt5.QtGui import QStandardItemModel, QStandardItem


@dataclass
class Gate:
    """Represents a gate in the hierarchy with selection state."""
    gate_id: str
    name: str
    path: tuple  # Full path from root
    gate_type: str
    parent_id: Optional[str] = None
    children: List['Gate'] = field(default_factory=list)
    is_selected: bool = True  # Checkbox state
    event_count: int = 0
    percent_parent: float = 0.0
    parameters: List[str] = field(default_factory=list)

    @property
    def full_path_string(self) -> str:
        """Returns path as 'Cells/Single Cells/Live/CD45+'"""
        return "/".join(self.path)

    @property
    def depth(self) -> int:
        """Returns hierarchy depth (0 = root)."""
        return len(self.path) - 1

    @property
    def bullet_prefix(self) -> str:
        """Returns bullet prefix for this depth (e.g., '●●●' for depth 3)."""
        return "●" * self.depth

    @property
    def compact_display(self) -> str:
        """Returns compact display: ●●●CD4+ for depth 3 gate named CD4+."""
        if self.depth == 0:
            return self.name
        return f"{'●' * self.depth}{self.name}"

    @property
    def hierarchical_path_string(self) -> str:
        """Returns 'Live, ●CD45+, ●●CD3+, ●●●CD4+CD8-' format."""
        parts = []
        for i, gate_name in enumerate(self.path):
            if i == 0:
                parts.append(gate_name)
            else:
                parts.append(f"{'●' * i}{gate_name}")
        return ", ".join(parts)


class GateTreeModel(QStandardItemModel):
    """
    Qt model for displaying gating hierarchy with checkboxes.

    Features:
    - Hierarchical display of gates
    - Checkbox support for gate selection
    - Reference gate tracking for normalization
    - Event count and percentage columns
    """

    COLUMN_GATE = 0
    COLUMN_REFERENCE = 1
    COLUMN_COUNT = 2
    COLUMN_PERCENT = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Gate", "Ref", "Events", "% Parent"])
        self._gates: Dict[str, Gate] = {}  # gate_id -> Gate mapping
        self._reference_gates: Set[str] = set()  # gate_ids marked as reference
        self._use_full_names: bool = True  # Full (disambiguated) vs short names
        self._display_names: Dict[str, str] = {}  # gate_id -> display name
        self._available_gate_ids: Set[str] = set()  # Gates available for selected samples
        self._updating: bool = False  # Prevents recursive signal loops

        # Connect itemChanged to propagate deselection to children
        self.itemChanged.connect(self._on_item_changed)

    def clear_gates(self):
        """Clear all gates from the model."""
        self.clear()
        self.setHorizontalHeaderLabels(["Gate", "Ref", "Events", "% Parent"])
        self._gates.clear()
        self._reference_gates.clear()
        self._display_names.clear()
        self._available_gate_ids.clear()

    def populate_from_hierarchy(self, gates: List[Gate]) -> None:
        """
        Build tree from list of Gate objects.

        Args:
            gates: List of Gate objects (can be flat or nested)
        """
        self.clear_gates()

        def add_gate_item(gate: Gate, parent_item: Optional[QStandardItem] = None):
            # Store gate reference
            self._gates[gate.gate_id] = gate

            # Create item with checkbox for gate selection
            item = QStandardItem(gate.name)
            item.setCheckable(True)
            item.setCheckState(Qt.Checked if gate.is_selected else Qt.Unchecked)
            item.setData(gate.gate_id, Qt.UserRole)  # Store gate_id
            item.setData(gate.depth, Qt.UserRole + 1)  # Store depth for colored dots

            # Reference checkbox column (for normalization)
            ref_item = QStandardItem()
            ref_item.setCheckable(True)
            ref_item.setCheckState(Qt.Checked if gate.gate_id in self._reference_gates else Qt.Unchecked)
            ref_item.setData(gate.gate_id, Qt.UserRole)  # For identification
            ref_item.setEditable(False)

            # Event count column
            count_str = f"{gate.event_count:,}" if gate.event_count > 0 else ""
            count_item = QStandardItem(count_str)
            count_item.setEditable(False)
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            # Percent column
            pct_str = f"{gate.percent_parent:.2f}%" if gate.percent_parent > 0 else ""
            pct_item = QStandardItem(pct_str)
            pct_item.setEditable(False)
            pct_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            row = [item, ref_item, count_item, pct_item]

            if parent_item is None:
                self.appendRow(row)
            else:
                parent_item.appendRow(row)

            # Recursively add children
            for child in gate.children:
                add_gate_item(child, item)

        # Add root gates
        for gate in gates:
            add_gate_item(gate)

    def get_selected_gates(self) -> List[Gate]:
        """
        Returns list of all checked gates.

        Returns:
            List of Gate objects that are checked
        """
        selected = []

        def traverse(item: QStandardItem):
            if item.checkState() == Qt.Checked:
                gate_id = item.data(Qt.UserRole)
                if gate_id and gate_id in self._gates:
                    selected.append(self._gates[gate_id])

            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    traverse(child)

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                traverse(item)

        return selected

    def get_selected_gate_ids(self) -> List[str]:
        """Returns list of gate IDs for all checked gates."""
        return [gate.gate_id for gate in self.get_selected_gates()]

    def select_all(self) -> None:
        """Check all gates."""
        self._set_all_check_state(Qt.Checked)

    def deselect_all(self) -> None:
        """Uncheck all gates."""
        self._set_all_check_state(Qt.Unchecked)

    def _set_all_check_state(self, state: Qt.CheckState) -> None:
        """Set check state for all items."""
        def traverse(item: QStandardItem):
            item.setCheckState(state)
            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    traverse(child)

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                traverse(item)

    def _on_item_changed(self, item: QStandardItem) -> None:
        """Handle item checkbox changes - propagate deselection to children."""
        if self._updating:
            return

        # Only handle COLUMN_GATE changes
        if item.column() != self.COLUMN_GATE:
            return

        # Only propagate when unchecking (not when checking)
        if item.checkState() == Qt.Unchecked:
            self._updating = True
            try:
                self._uncheck_children(item)
            finally:
                self._updating = False

    def _uncheck_children(self, item: QStandardItem) -> None:
        """Recursively uncheck all children of an item."""
        for i in range(item.rowCount()):
            child = item.child(i, self.COLUMN_GATE)
            if child:
                child.setCheckState(Qt.Unchecked)
                # Update internal gate state
                gate_id = child.data(Qt.UserRole)
                if gate_id and gate_id in self._gates:
                    self._gates[gate_id].is_selected = False
                # Recurse to grandchildren
                self._uncheck_children(child)

    def get_gate_by_id(self, gate_id: str) -> Optional[Gate]:
        """Get a Gate object by its ID."""
        return self._gates.get(gate_id)

    def update_gate_statistics(self, gate_id: str, event_count: int, percent_parent: float) -> None:
        """
        Update statistics for a specific gate.

        Args:
            gate_id: The gate ID to update
            event_count: New event count
            percent_parent: New percent of parent
        """
        if gate_id in self._gates:
            gate = self._gates[gate_id]
            gate.event_count = event_count
            gate.percent_parent = percent_parent

            # Find and update the corresponding item
            item = self._find_item_by_gate_id(gate_id)
            if item:
                parent = item.parent() if item.parent() else self.invisibleRootItem()
                row = item.row()

                # Update count column (now COLUMN_COUNT = 2)
                count_item = parent.child(row, self.COLUMN_COUNT) if item.parent() else self.item(row, self.COLUMN_COUNT)
                if count_item:
                    count_item.setText(f"{event_count:,}")

                # Update percent column (now COLUMN_PERCENT = 3)
                pct_item = parent.child(row, self.COLUMN_PERCENT) if item.parent() else self.item(row, self.COLUMN_PERCENT)
                if pct_item:
                    pct_item.setText(f"{percent_parent:.2f}%")

    def _find_item_by_gate_id(self, gate_id: str) -> Optional[QStandardItem]:
        """Find a QStandardItem by gate ID."""
        def search(item: QStandardItem) -> Optional[QStandardItem]:
            if item.data(Qt.UserRole) == gate_id:
                return item
            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    result = search(child)
                    if result:
                        return result
            return None

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                result = search(item)
                if result:
                    return result
        return None

    # =========================================================================
    # Reference Gate Methods (for normalization feature)
    # =========================================================================

    def toggle_reference_gate(self, gate_id: str) -> None:
        """
        Toggle whether a gate is a normalization reference.

        Args:
            gate_id: The gate ID to toggle
        """
        if gate_id in self._reference_gates:
            self._reference_gates.discard(gate_id)
            new_state = Qt.Unchecked
        else:
            self._reference_gates.add(gate_id)
            new_state = Qt.Checked

        # Update checkbox state in tree
        item = self._find_item_by_gate_id(gate_id)
        if item:
            parent = item.parent() if item.parent() else self.invisibleRootItem()
            row = item.row()

            # Get the reference column item
            ref_item = parent.child(row, self.COLUMN_REFERENCE) if item.parent() else self.item(row, self.COLUMN_REFERENCE)
            if ref_item:
                ref_item.setCheckState(new_state)

    def set_reference_gate(self, gate_id: str, is_reference: bool) -> None:
        """
        Explicitly set whether a gate is a reference gate.

        Args:
            gate_id: The gate ID to set
            is_reference: True to mark as reference, False to unmark
        """
        if is_reference:
            if gate_id not in self._reference_gates:
                self._reference_gates.add(gate_id)
        else:
            self._reference_gates.discard(gate_id)

        # Update checkbox state in tree
        item = self._find_item_by_gate_id(gate_id)
        if item:
            parent = item.parent() if item.parent() else self.invisibleRootItem()
            row = item.row()

            ref_item = parent.child(row, self.COLUMN_REFERENCE) if item.parent() else self.item(row, self.COLUMN_REFERENCE)
            if ref_item:
                ref_item.setCheckState(Qt.Checked if is_reference else Qt.Unchecked)

    def get_reference_gates(self) -> List[str]:
        """
        Return list of gate_ids marked as reference gates.

        Returns:
            List of gate IDs that are marked as reference gates
        """
        return list(self._reference_gates)

    def is_reference_gate(self, gate_id: str) -> bool:
        """
        Check if a gate is marked as a reference gate.

        Args:
            gate_id: The gate ID to check

        Returns:
            True if the gate is a reference gate, False otherwise
        """
        return gate_id in self._reference_gates

    def clear_reference_gates(self) -> None:
        """Clear all reference gate selections."""
        # Update UI for all currently marked reference gates
        for gate_id in list(self._reference_gates):
            item = self._find_item_by_gate_id(gate_id)
            if item:
                parent = item.parent() if item.parent() else self.invisibleRootItem()
                row = item.row()

                ref_item = parent.child(row, self.COLUMN_REFERENCE) if item.parent() else self.item(row, self.COLUMN_REFERENCE)
                if ref_item:
                    ref_item.setCheckState(Qt.Unchecked)

        self._reference_gates.clear()

    def sync_reference_from_ui(self) -> None:
        """
        Sync the _reference_gates set from the current UI checkbox states.

        Call this after the user interacts with reference checkboxes directly.
        """
        self._reference_gates.clear()

        def traverse(item: QStandardItem):
            gate_id = item.data(Qt.UserRole)
            if gate_id:
                parent = item.parent() if item.parent() else self.invisibleRootItem()
                row = item.row()

                ref_item = parent.child(row, self.COLUMN_REFERENCE) if item.parent() else self.item(row, self.COLUMN_REFERENCE)
                if ref_item and ref_item.checkState() == Qt.Checked:
                    self._reference_gates.add(gate_id)

            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    traverse(child)

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                traverse(item)

    # --- Display Mode Methods ---

    def set_display_mode(self, use_full_names: bool) -> None:
        """Set whether to show full (disambiguated) or short gate names.

        Args:
            use_full_names: True for full names with parent prefix, False for short names
        """
        if self._use_full_names == use_full_names:
            return

        self._use_full_names = use_full_names
        self._compute_display_names()
        self._refresh_display_names()

    def _compute_display_names(self) -> None:
        """Compute display names for all gates based on current mode.

        For full names mode: Add minimal parent prefix to disambiguate duplicate names.
        For short names mode: Use just the gate name.
        """
        self._display_names.clear()

        if not self._use_full_names:
            # Short names mode - just use base name
            for gate_id, gate in self._gates.items():
                self._display_names[gate_id] = gate.name
            return

        # Full names mode - disambiguate duplicates with parent prefix
        # First, find all duplicate names
        name_count: Dict[str, List[str]] = {}  # name -> list of gate_ids
        for gate_id, gate in self._gates.items():
            if gate.name not in name_count:
                name_count[gate.name] = []
            name_count[gate.name].append(gate_id)

        # For each gate, compute display name
        for gate_id, gate in self._gates.items():
            if len(name_count[gate.name]) == 1:
                # Unique name - use as is
                self._display_names[gate_id] = gate.name
            else:
                # Duplicate name - add minimal parent prefix to disambiguate
                self._display_names[gate_id] = self._disambiguate_gate_name(
                    gate_id, name_count[gate.name]
                )

    def _disambiguate_gate_name(self, gate_id: str, duplicate_gate_ids: List[str]) -> str:
        """Add minimal parent prefix to disambiguate a gate name.

        Args:
            gate_id: The gate to get display name for
            duplicate_gate_ids: List of gate_ids with the same base name

        Returns:
            Disambiguated name like 'CD3+/CD4+' if multiple gates named 'CD4+'
        """
        gate = self._gates[gate_id]

        # Try progressively longer prefixes until unique
        path = list(gate.path)
        base_name = path[-1] if path else gate.name

        for prefix_len in range(1, len(path)):
            # Build candidate name with prefix
            prefix_start = len(path) - 1 - prefix_len
            prefix_parts = path[prefix_start:-1]
            candidate = "/".join(prefix_parts) + "/" + base_name

            # Check if this is unique among duplicates
            is_unique = True
            for other_id in duplicate_gate_ids:
                if other_id == gate_id:
                    continue
                other_gate = self._gates[other_id]
                other_path = list(other_gate.path)
                other_prefix_start = len(other_path) - 1 - prefix_len
                if other_prefix_start >= 0:
                    other_prefix = other_path[other_prefix_start:-1]
                    other_candidate = "/".join(other_prefix) + "/" + base_name
                    if candidate == other_candidate:
                        is_unique = False
                        break

            if is_unique:
                return candidate

        # If still not unique, use full path
        return "/".join(path)

    def _refresh_display_names(self) -> None:
        """Update all gate items with their computed display names."""
        def traverse(item: QStandardItem):
            gate_id = item.data(Qt.UserRole)
            if gate_id and gate_id in self._display_names:
                item.setText(self._display_names[gate_id])

            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    traverse(child)

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                traverse(item)

    # --- Gate Availability Methods ---

    def set_available_gates(self, available_gate_ids: Set[str]) -> None:
        """Set which gates are available (have data in selected samples).

        Unavailable gates are grayed out and their checkboxes are disabled.

        Args:
            available_gate_ids: Set of gate_ids that have data
        """
        self._available_gate_ids = available_gate_ids
        self._update_gate_availability_display()

    def _update_gate_availability_display(self) -> None:
        """Update visual state of gates based on availability."""
        def traverse(item: QStandardItem):
            gate_id = item.data(Qt.UserRole)
            if gate_id and gate_id in self._gates:
                is_available = not self._available_gate_ids or gate_id in self._available_gate_ids
                item.setEnabled(is_available)
                if not is_available:
                    # Uncheck unavailable gates
                    item.setCheckState(Qt.Unchecked)

            for i in range(item.rowCount()):
                child = item.child(i, self.COLUMN_GATE)
                if child:
                    traverse(child)

        for i in range(self.rowCount()):
            item = self.item(i, self.COLUMN_GATE)
            if item:
                traverse(item)

    def get_available_gate_ids(self) -> Set[str]:
        """Get the set of currently available gate IDs."""
        return self._available_gate_ids
