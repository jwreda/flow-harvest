"""
Tests for Gate Tree Model.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from flowkit_gui.models.gate_tree_model import Gate, GateTreeModel


# Create QApplication for Qt tests (required for QStandardItemModel)
@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestGate:
    """Tests for Gate dataclass."""

    def test_gate_creation(self):
        """Test basic gate creation."""
        gate = Gate(
            gate_id="live",
            name="Live Cells",
            path=("Cells", "Single Cells", "Live Cells"),
            gate_type="PolygonGate"
        )
        assert gate.gate_id == "live"
        assert gate.name == "Live Cells"
        assert gate.gate_type == "PolygonGate"

    def test_full_path_string(self):
        """Test full path string generation."""
        gate = Gate(
            gate_id="cd4",
            name="CD4+",
            path=("Cells", "Single Cells", "Live", "CD45+", "CD4+"),
            gate_type="RectangleGate"
        )
        assert gate.full_path_string == "Cells/Single Cells/Live/CD45+/CD4+"

    def test_depth_calculation(self):
        """Test depth calculation."""
        root_gate = Gate(
            gate_id="cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate"
        )
        assert root_gate.depth == 0

        nested_gate = Gate(
            gate_id="tregs",
            name="Tregs",
            path=("Cells", "Single Cells", "Live", "CD45+", "CD4+", "Foxp3+"),
            gate_type="RectangleGate"
        )
        assert nested_gate.depth == 5

    def test_gate_children(self):
        """Test gate with children."""
        child1 = Gate(gate_id="cd4", name="CD4+", path=("Cells", "CD4+"), gate_type="RectangleGate")
        child2 = Gate(gate_id="cd8", name="CD8+", path=("Cells", "CD8+"), gate_type="RectangleGate")

        parent = Gate(
            gate_id="cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate",
            children=[child1, child2]
        )
        assert len(parent.children) == 2
        assert parent.children[0].name == "CD4+"
        assert parent.children[1].name == "CD8+"

    def test_gate_default_selected(self):
        """Test that gates are selected by default."""
        gate = Gate(gate_id="test", name="Test", path=("Test",), gate_type="PolygonGate")
        assert gate.is_selected is True


class TestGateTreeModel:
    """Tests for GateTreeModel."""

    def test_model_initialization(self, qapp):
        """Test model initializes with correct headers."""
        model = GateTreeModel()
        assert model.columnCount() == 4
        assert model.headerData(0, Qt.Horizontal) == "Gate"
        assert model.headerData(1, Qt.Horizontal) == "Ref"
        assert model.headerData(2, Qt.Horizontal) == "Events"
        assert model.headerData(3, Qt.Horizontal) == "% Parent"

    def test_populate_single_gate(self, qapp):
        """Test populating with a single gate."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        assert model.rowCount() == 1
        item = model.item(0, 0)
        assert item.text() == "Cells"
        assert item.isCheckable()
        assert item.checkState() == Qt.Checked

    def test_populate_nested_hierarchy(self, qapp):
        """Test populating with nested gate hierarchy."""
        model = GateTreeModel()

        child = Gate(
            gate_id="single",
            name="Single Cells",
            path=("Cells", "Single Cells"),
            gate_type="PolygonGate"
        )
        parent = Gate(
            gate_id="cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate",
            children=[child]
        )

        model.populate_from_hierarchy([parent])

        assert model.rowCount() == 1
        root_item = model.item(0, 0)
        assert root_item.text() == "Cells"
        assert root_item.rowCount() == 1

        child_item = root_item.child(0, 0)
        assert child_item.text() == "Single Cells"

    def test_get_selected_gates(self, qapp):
        """Test getting selected gates."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate"),
            Gate(gate_id="debris", name="Debris", path=("Debris",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        # Both should be selected by default
        selected = model.get_selected_gates()
        assert len(selected) == 2

        # Uncheck one
        model.item(0, 0).setCheckState(Qt.Unchecked)
        selected = model.get_selected_gates()
        assert len(selected) == 1
        assert selected[0].name == "Debris"

    def test_get_selected_gate_ids(self, qapp):
        """Test getting selected gate IDs."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate"),
            Gate(gate_id="debris", name="Debris", path=("Debris",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        ids = model.get_selected_gate_ids()
        assert "cells" in ids
        assert "debris" in ids

    def test_select_all(self, qapp):
        """Test select all functionality."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="g1", name="Gate1", path=("Gate1",), gate_type="PolygonGate"),
            Gate(gate_id="g2", name="Gate2", path=("Gate2",), gate_type="PolygonGate"),
        ]
        model.populate_from_hierarchy(gates)

        # Uncheck all first
        model.deselect_all()
        assert len(model.get_selected_gates()) == 0

        # Select all
        model.select_all()
        assert len(model.get_selected_gates()) == 2

    def test_deselect_all(self, qapp):
        """Test deselect all functionality."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="g1", name="Gate1", path=("Gate1",), gate_type="PolygonGate"),
            Gate(gate_id="g2", name="Gate2", path=("Gate2",), gate_type="PolygonGate"),
        ]
        model.populate_from_hierarchy(gates)

        model.deselect_all()
        assert len(model.get_selected_gates()) == 0

    def test_deselection_propagates_to_children(self, qapp):
        """Test that unchecking a parent gate unchecks all children."""
        model = GateTreeModel()

        grandchild = Gate(
            gate_id="cd4",
            name="CD4+",
            path=("Cells", "Live", "CD4+"),
            gate_type="RectangleGate"
        )
        child = Gate(
            gate_id="live",
            name="Live",
            path=("Cells", "Live"),
            gate_type="PolygonGate",
            children=[grandchild]
        )
        parent = Gate(
            gate_id="cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate",
            children=[child]
        )

        model.populate_from_hierarchy([parent])

        # All should be selected initially
        assert len(model.get_selected_gates()) == 3

        # Uncheck the parent
        model.item(0, 0).setCheckState(Qt.Unchecked)

        # All children should now be unchecked
        selected = model.get_selected_gates()
        assert len(selected) == 0

        # Verify internal state is also updated
        assert model.get_gate_by_id("live").is_selected is False
        assert model.get_gate_by_id("cd4").is_selected is False

    def test_selection_does_not_propagate_to_children(self, qapp):
        """Test that checking a parent does NOT auto-check children."""
        model = GateTreeModel()

        child = Gate(
            gate_id="live",
            name="Live",
            path=("Cells", "Live"),
            gate_type="PolygonGate",
            is_selected=False
        )
        parent = Gate(
            gate_id="cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate",
            children=[child],
            is_selected=False
        )

        model.populate_from_hierarchy([parent])

        # Verify initial state - both unchecked
        assert len(model.get_selected_gates()) == 0

        # Check the parent
        model.item(0, 0).setCheckState(Qt.Checked)

        # Child should remain unchecked
        child_item = model.item(0, 0).child(0, 0)
        assert child_item.checkState() == Qt.Unchecked

        # Only parent should be selected
        selected = model.get_selected_gates()
        assert len(selected) == 1
        assert selected[0].gate_id == "cells"

    def test_clear_gates(self, qapp):
        """Test clearing all gates."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)
        assert model.rowCount() == 1

        model.clear_gates()
        assert model.rowCount() == 0

    def test_get_gate_by_id(self, qapp):
        """Test getting gate by ID."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        gate = model.get_gate_by_id("cells")
        assert gate is not None
        assert gate.name == "Cells"

        gate = model.get_gate_by_id("nonexistent")
        assert gate is None

    def test_update_gate_statistics(self, qapp):
        """Test updating gate statistics."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        model.update_gate_statistics("cells", 100000, 85.5)

        gate = model.get_gate_by_id("cells")
        assert gate.event_count == 100000
        assert gate.percent_parent == 85.5

    def test_event_count_display(self, qapp):
        """Test that event count displays with formatting."""
        model = GateTreeModel()
        gates = [
            Gate(
                gate_id="cells",
                name="Cells",
                path=("Cells",),
                gate_type="PolygonGate",
                event_count=1000000,
                percent_parent=100.0
            )
        ]
        model.populate_from_hierarchy(gates)

        # Check the count column has formatted number
        count_item = model.item(0, model.COLUMN_COUNT)
        assert count_item.text() == "1,000,000"


class TestReferenceGates:
    """Tests for reference gate tracking functionality."""

    def test_reference_gates_initially_empty(self, qapp):
        """Test that reference gates set is empty initially."""
        model = GateTreeModel()
        assert model.get_reference_gates() == []

    def test_toggle_reference_gate(self, qapp):
        """Test toggling reference gate status."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        # Toggle on
        model.toggle_reference_gate("cells")
        assert model.is_reference_gate("cells")
        assert "cells" in model.get_reference_gates()

        # Toggle off
        model.toggle_reference_gate("cells")
        assert not model.is_reference_gate("cells")
        assert "cells" not in model.get_reference_gates()

    def test_set_reference_gate(self, qapp):
        """Test explicitly setting reference gate status."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        # Set as reference
        model.set_reference_gate("cells", True)
        assert model.is_reference_gate("cells")

        # Set as not reference
        model.set_reference_gate("cells", False)
        assert not model.is_reference_gate("cells")

    def test_multiple_reference_gates(self, qapp):
        """Test setting multiple gates as references."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="g1", name="Gate1", path=("Gate1",), gate_type="PolygonGate"),
            Gate(gate_id="g2", name="Gate2", path=("Gate2",), gate_type="PolygonGate"),
            Gate(gate_id="g3", name="Gate3", path=("Gate3",), gate_type="PolygonGate"),
        ]
        model.populate_from_hierarchy(gates)

        model.set_reference_gate("g1", True)
        model.set_reference_gate("g3", True)

        ref_gates = model.get_reference_gates()
        assert len(ref_gates) == 2
        assert "g1" in ref_gates
        assert "g3" in ref_gates
        assert "g2" not in ref_gates

    def test_clear_reference_gates(self, qapp):
        """Test clearing all reference gates."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="g1", name="Gate1", path=("Gate1",), gate_type="PolygonGate"),
            Gate(gate_id="g2", name="Gate2", path=("Gate2",), gate_type="PolygonGate"),
        ]
        model.populate_from_hierarchy(gates)

        model.set_reference_gate("g1", True)
        model.set_reference_gate("g2", True)
        assert len(model.get_reference_gates()) == 2

        model.clear_reference_gates()
        assert len(model.get_reference_gates()) == 0

    def test_clear_gates_clears_references(self, qapp):
        """Test that clearing gates also clears reference selections."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        model.set_reference_gate("cells", True)
        assert len(model.get_reference_gates()) == 1

        model.clear_gates()
        assert len(model.get_reference_gates()) == 0

    def test_reference_column_exists(self, qapp):
        """Test that reference column is created with checkbox."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        ref_item = model.item(0, model.COLUMN_REFERENCE)
        assert ref_item is not None
        assert ref_item.isCheckable()
        assert ref_item.checkState() == Qt.Unchecked

    def test_reference_checkbox_updates_with_toggle(self, qapp):
        """Test that reference checkbox updates when toggled programmatically."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="cells", name="Cells", path=("Cells",), gate_type="PolygonGate")
        ]
        model.populate_from_hierarchy(gates)

        ref_item = model.item(0, model.COLUMN_REFERENCE)
        assert ref_item.checkState() == Qt.Unchecked

        model.toggle_reference_gate("cells")
        assert ref_item.checkState() == Qt.Checked

        model.toggle_reference_gate("cells")
        assert ref_item.checkState() == Qt.Unchecked

    def test_sync_reference_from_ui(self, qapp):
        """Test syncing reference gates from UI checkbox states."""
        model = GateTreeModel()
        gates = [
            Gate(gate_id="g1", name="Gate1", path=("Gate1",), gate_type="PolygonGate"),
            Gate(gate_id="g2", name="Gate2", path=("Gate2",), gate_type="PolygonGate"),
        ]
        model.populate_from_hierarchy(gates)

        # Directly set checkbox state (simulating user interaction)
        model.item(0, model.COLUMN_REFERENCE).setCheckState(Qt.Checked)
        model.item(1, model.COLUMN_REFERENCE).setCheckState(Qt.Unchecked)

        # Sync from UI
        model.sync_reference_from_ui()

        assert model.is_reference_gate("g1")
        assert not model.is_reference_gate("g2")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
