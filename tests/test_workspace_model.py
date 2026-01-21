"""
Tests for WorkspaceModel - FlowKit wrapper functionality.
"""

import pytest
from pathlib import Path
import sys

# Add the project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flowkit_gui.models.workspace_model import WorkspaceModel, Sample, GateInfo


# Path to test data
TEST_DATA_DIR = Path(__file__).parent.parent
WSP_FILE = TEST_DATA_DIR / "example_workspace.wsp"


class TestSample:
    """Tests for the Sample dataclass."""

    def test_sample_creation(self):
        """Test basic Sample creation."""
        sample = Sample(
            sample_id="1",
            name="test.fcs",
            fcs_path=Path("/path/to/test.fcs"),
            group="Group1",
            keywords={"Mouse #": "123", "Tumor": "C", "$P1N": "FSC-A"},
            event_count=1000
        )

        assert sample.sample_id == "1"
        assert sample.name == "test.fcs"
        assert sample.event_count == 1000

    def test_get_custom_keywords_filters_system_keys(self):
        """Test that get_custom_keywords filters out system keywords."""
        sample = Sample(
            sample_id="1",
            name="test.fcs",
            fcs_path=None,
            group="",
            keywords={
                "Mouse #": "123",
                "Tumor": "C",
                "RT": "No RT",
                "$P1N": "FSC-A",
                "$P2N": "SSC-A",
                "FCSversion": "3.1",
                "SPILL": "matrix data",
                "TOT": "100000",
                "BYTEORD": "1,2,3,4"
            }
        )

        custom = sample.get_custom_keywords()

        # Should include user keywords
        assert "Mouse #" in custom
        assert "Tumor" in custom
        assert "RT" in custom

        # Should exclude system keywords
        assert "$P1N" not in custom
        assert "FCSversion" not in custom
        assert "SPILL" not in custom
        assert "TOT" not in custom


class TestGateInfo:
    """Tests for the GateInfo dataclass."""

    def test_gate_info_creation(self):
        """Test basic GateInfo creation."""
        gate = GateInfo(
            gate_id="CD45+",
            name="CD45+",
            path=("Cells", "Single Cells", "Live", "CD45+"),
            gate_type="RectangleGate",
            parameters=["BV605-A"]
        )

        assert gate.gate_id == "CD45+"
        assert gate.depth == 3
        assert gate.full_path_string == "Cells/Single Cells/Live/CD45+"

    def test_gate_depth_root(self):
        """Test depth calculation for root gate."""
        gate = GateInfo(
            gate_id="Cells",
            name="Cells",
            path=("Cells",),
            gate_type="PolygonGate"
        )

        assert gate.depth == 0

    def test_full_path_string(self):
        """Test full path string generation."""
        gate = GateInfo(
            gate_id="CD8+",
            name="CD8+",
            path=("Cells", "Single Cells", "Live", "CD45+", "CD3+", "CD8+"),
            gate_type="RectangleGate"
        )

        assert gate.full_path_string == "Cells/Single Cells/Live/CD45+/CD3+/CD8+"


class TestWorkspaceModel:
    """Tests for the WorkspaceModel class."""

    def test_model_initialization(self):
        """Test that model initializes correctly."""
        model = WorkspaceModel()

        assert not model.is_loaded
        assert model.samples == []
        assert model.gates == []
        assert model.channels == []

    def test_load_nonexistent_file_raises(self):
        """Test that loading non-existent file raises FileNotFoundError."""
        model = WorkspaceModel()

        with pytest.raises(FileNotFoundError):
            model.load_workspace("/nonexistent/path/file.wsp")

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_load_workspace(self):
        """Test loading actual workspace file."""
        model = WorkspaceModel()

        num_samples, num_gates = model.load_workspace(str(WSP_FILE))

        assert model.is_loaded
        assert num_samples > 0
        assert num_gates > 0

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_samples_extracted(self):
        """Test that samples are extracted from workspace."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        assert len(model.samples) > 0

        # Check first sample has expected attributes
        sample = model.samples[0]
        assert sample.sample_id is not None
        assert sample.name is not None

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_gates_extracted(self):
        """Test that gates are extracted from workspace."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        assert len(model.gates) > 0

        # Check that gates have proper structure
        for gate in model.gates:
            assert gate.gate_id is not None
            assert gate.path is not None
            assert len(gate.path) > 0

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_channels_extracted(self):
        """Test that fluorescence channels are extracted."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        # Should have fluorescence channels
        assert len(model.channels) > 0

        # Channels should end with -A, -H, or -W
        for channel in model.channels:
            assert channel.endswith(('-A', '-H', '-W'))

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_sample_keywords_contain_custom_fields(self):
        """Test that sample keywords include custom fields like Mouse #."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        # Find a sample with custom keywords
        found_custom = False
        for sample in model.samples:
            custom = sample.get_custom_keywords()
            if "Mouse #" in custom or "Tumor" in custom or "RT" in custom:
                found_custom = True
                break

        assert found_custom, "No samples found with custom keywords (Mouse #, Tumor, RT)"

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_get_sample_by_id(self):
        """Test retrieving sample by ID."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        if model.samples:
            first_sample = model.samples[0]
            retrieved = model.get_sample_by_id(first_sample.sample_id)

            assert retrieved is not None
            assert retrieved.sample_id == first_sample.sample_id

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_get_sample_by_id_not_found(self):
        """Test that non-existent sample returns None."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        result = model.get_sample_by_id("nonexistent_id_12345")
        assert result is None

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_gate_hierarchy_ascii(self):
        """Test getting ASCII representation of gate hierarchy."""
        model = WorkspaceModel()
        model.load_workspace(str(WSP_FILE))

        hierarchy = model.get_gate_hierarchy_ascii()

        # Should return non-empty string
        assert hierarchy is not None
        assert len(hierarchy) > 0


class TestWorkspaceModelWithMissingFiles:
    """Tests for handling missing FCS files gracefully."""

    @pytest.mark.skipif(not WSP_FILE.exists(), reason="WSP test file not available")
    def test_load_with_missing_fcs_files(self):
        """Test that workspace loads even when FCS files are missing."""
        model = WorkspaceModel()

        # Load with a directory that definitely doesn't have the FCS files
        num_samples, num_gates = model.load_workspace(
            str(WSP_FILE),
            fcs_dir="/tmp",
            ignore_missing=True
        )

        # Should still load the workspace structure
        assert model.is_loaded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
