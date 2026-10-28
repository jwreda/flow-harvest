"""
Tests for Gate Name Disambiguation in Gate Marker Matrix Model.

Tests that duplicate gate names are disambiguated with minimal parent prefixes
while unique names remain unchanged.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from flowkit_gui.models.gate_marker_matrix_model import (
    GateMarkerMatrixModel,
    _disambiguate_duplicate_names,
)
from flowkit_gui.models.workspace_model import GateInfo, ChannelInfo


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_gate(path: str) -> GateInfo:
    """Helper to create GateInfo from path string like 'Cells/Live/CD4+'."""
    parts = tuple(path.split('/'))
    return GateInfo(
        gate_id=path,
        name=parts[-1],
        path=parts,
        gate_type="PolygonGate"
    )


def _make_marker(pnn: str, pns: str = "") -> ChannelInfo:
    """Helper to create ChannelInfo."""
    return ChannelInfo(pnn_label=pnn, pns_label=pns)


class TestDisambiguateFunction:
    """Tests for the _disambiguate_duplicate_names helper function."""

    def test_simple_duplicates_one_parent(self):
        """Test duplicates resolved with one parent level."""
        result = _disambiguate_duplicate_names(
            "Reporter+",
            ["Cells/Live/CD4+/Reporter+", "Cells/Live/CD8+/Reporter+"]
        )
        assert result["Cells/Live/CD4+/Reporter+"] == "CD4+/Reporter+"
        assert result["Cells/Live/CD8+/Reporter+"] == "CD8+/Reporter+"

    def test_duplicates_need_grandparent(self):
        """Test duplicates that need grandparent prefix to be unique."""
        result = _disambiguate_duplicate_names(
            "Target",
            [
                "Cells/Branch1/Sub/Target",
                "Cells/Branch2/Sub/Target",
                "Cells/Branch3/Sub/Target",
            ]
        )
        # All have same parent "Sub", need grandparent
        assert result["Cells/Branch1/Sub/Target"] == "Branch1/Sub/Target"
        assert result["Cells/Branch2/Sub/Target"] == "Branch2/Sub/Target"
        assert result["Cells/Branch3/Sub/Target"] == "Branch3/Sub/Target"

    def test_two_level_duplicates(self):
        """Test duplicates at different depths."""
        result = _disambiguate_duplicate_names(
            "Target",
            ["Cells/Target", "Cells/Live/Target"]
        )
        # Different depths, one level prefix should work
        assert result["Cells/Target"] == "Cells/Target"
        assert result["Cells/Live/Target"] == "Live/Target"


class TestGateMarkerMatrixDisambiguation:
    """Tests for gate name disambiguation in the matrix model."""

    def test_unique_names_unchanged(self, qapp):
        """Test that unique gate names are not modified."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Lymphocytes"),
            _make_gate("Cells/Live/CD4+"),
            _make_gate("Cells/Live/CD8+"),
        ]
        markers = [_make_marker("BUV496-A", "CD4")]

        model.set_gates_and_markers(gates, markers)

        # All names are unique, should be unchanged
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "Lymphocytes"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD4+"
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "CD8+"

    def test_duplicate_names_get_parent_prefix(self, qapp):
        """Test that duplicate names get minimal parent prefix."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD4+/Reporter+"),
            _make_gate("Cells/Live/CD8+/Reporter+"),
            _make_gate("Cells/Live/CD4+"),
        ]
        markers = [_make_marker("BUV496-A", "CD4")]

        model.set_gates_and_markers(gates, markers)

        # "Reporter+" appears twice - needs parent prefix
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "CD4+/Reporter+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD8+/Reporter+"
        # "CD4+" is unique
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "CD4+"

    def test_triple_duplicate_needs_grandparent(self, qapp):
        """Test disambiguation when parent prefix still isn't unique."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Branch1/Sub/Target"),
            _make_gate("Cells/Branch2/Sub/Target"),
            _make_gate("Cells/Branch3/Sub/Target"),
        ]
        markers = [_make_marker("BUV496-A")]

        model.set_gates_and_markers(gates, markers)

        # "Target" appears 3x, all have "Sub" parent, need grandparent
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "Branch1/Sub/Target"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "Branch2/Sub/Target"
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "Branch3/Sub/Target"

    def test_mixed_unique_and_duplicate(self, qapp):
        """Test matrix with both unique and duplicate names."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells"),  # unique
            _make_gate("Cells/Live/CD4+/Foxp3+"),  # duplicate Foxp3+
            _make_gate("Cells/Live/CD8+/Foxp3+"),  # duplicate Foxp3+
            _make_gate("Debris"),  # unique
        ]
        markers = [_make_marker("BUV496-A")]

        model.set_gates_and_markers(gates, markers)

        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "Cells"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD4+/Foxp3+"
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "CD8+/Foxp3+"
        assert model.headerData(3, Qt.Vertical, Qt.DisplayRole) == "Debris"

    def test_depth_role_unchanged(self, qapp):
        """Test that depth (UserRole) remains unchanged after disambiguation."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD4+/Reporter+"),  # depth 3
            _make_gate("Cells/Live/CD8+/Reporter+"),  # depth 3
        ]
        markers = [_make_marker("BUV496-A")]

        model.set_gates_and_markers(gates, markers)

        # UserRole should return depth, not affected by disambiguation
        assert model.headerData(0, Qt.Vertical, Qt.UserRole) == 3
        assert model.headerData(1, Qt.Vertical, Qt.UserRole) == 3

    def test_tooltip_shows_full_path(self, qapp):
        """Test that tooltip still shows full gate path."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD4+/Reporter+"),
        ]
        markers = [_make_marker("BUV496-A")]

        model.set_gates_and_markers(gates, markers)

        tooltip = model.headerData(0, Qt.Vertical, Qt.ToolTipRole)
        assert "Cells/Live/CD4+/Reporter+" in tooltip

    def test_empty_gates_list(self, qapp):
        """Test handling of empty gates list."""
        model = GateMarkerMatrixModel()
        model.set_gates_and_markers([], [_make_marker("BUV496-A")])

        assert model.rowCount() == 0
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) is None

    def test_single_gate(self, qapp):
        """Test single gate returns base name."""
        model = GateMarkerMatrixModel()
        gates = [_make_gate("Cells/Live/CD4+")]
        markers = [_make_marker("BUV496-A")]

        model.set_gates_and_markers(gates, markers)

        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "CD4+"

    def test_reporter_under_every_population(self, qapp):
        """Test Collaborator's example: Reporter+ under every population gate."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD4+/Reporter+"),
            _make_gate("Cells/Live/CD8+/Reporter+"),
            _make_gate("Cells/Live/CD45+/Reporter+"),
            _make_gate("Cells/Live/Lymphocytes/Reporter+"),
        ]
        markers = [_make_marker("PE-A", "Reporter")]

        model.set_gates_and_markers(gates, markers)

        # Each Reporter+ should be prefixed with its unique parent
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "CD4+/Reporter+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD8+/Reporter+"
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "CD45+/Reporter+"
        assert model.headerData(3, Qt.Vertical, Qt.DisplayRole) == "Lymphocytes/Reporter+"


class TestPlusMinusVariations:
    """Tests ensuring + and - gate name variations are correctly distinguished."""

    def test_plus_minus_variations_not_confused(self, qapp):
        """Test that F4-80+ and F4-80- are different names, not duplicates."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD45+/F4-80+ CD11b+"),
            _make_gate("Cells/Live/CD45+/F4-80- CD11b+"),  # Different name!
        ]
        markers = [_make_marker("BUV496-A")]
        model.set_gates_and_markers(gates, markers)

        # These are DIFFERENT base names - should NOT be disambiguated
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "F4-80+ CD11b+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "F4-80- CD11b+"

    def test_actual_duplicates_with_plus_names(self, qapp):
        """Test true duplicates with + in name get proper disambiguation."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/CD45+/F4-80+ CD11b+"),
            _make_gate("Cells/Live/CD4+/F4-80+ CD11b+"),  # Same name, different parent
        ]
        markers = [_make_marker("BUV496-A")]
        model.set_gates_and_markers(gates, markers)

        # Same base name "F4-80+ CD11b+" - SHOULD be disambiguated
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "CD45+/F4-80+ CD11b+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD4+/F4-80+ CD11b+"

    def test_mixed_plus_minus_with_duplicates(self, qapp):
        """Test complex scenario with both +/- variations and true duplicates."""
        model = GateMarkerMatrixModel()
        gates = [
            # Two "F4-80+ CD11b+" gates - true duplicates, need disambiguation
            _make_gate("Cells/Live/CD45+/F4-80+ CD11b+"),
            _make_gate("Cells/Live/CD4+/F4-80+ CD11b+"),
            # One "F4-80- CD11b+" gate - unique, no disambiguation needed
            _make_gate("Cells/Live/CD45+/F4-80- CD11b+"),
        ]
        markers = [_make_marker("BUV496-A")]
        model.set_gates_and_markers(gates, markers)

        # The positive variants are duplicates and get disambiguated
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "CD45+/F4-80+ CD11b+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "CD4+/F4-80+ CD11b+"
        # The negative variant is unique and stays as-is
        assert model.headerData(2, Qt.Vertical, Qt.DisplayRole) == "F4-80- CD11b+"

    def test_gates_differing_only_in_plus_minus(self, qapp):
        """Test gates that differ only in + vs - suffix."""
        model = GateMarkerMatrixModel()
        gates = [
            _make_gate("Cells/Live/Foxp3+"),
            _make_gate("Cells/Live/Foxp3-"),
        ]
        markers = [_make_marker("BUV496-A")]
        model.set_gates_and_markers(gates, markers)

        # These are different names - exact string match matters
        assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "Foxp3+"
        assert model.headerData(1, Qt.Vertical, Qt.DisplayRole) == "Foxp3-"
