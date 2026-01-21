"""
Tests for the FCS file discovery module.

Uses a temporary directory structure to test:
- Recursive file discovery
- Case-insensitive extension matching
- Processing level detection
- Duplicate filename handling
"""

import pytest
from pathlib import Path
import tempfile
import os

from flowkit_gui.utils.fcs_discovery import (
    discover_fcs_files,
    resolve_fcs_file,
    get_fcs_file_list,
    ProcessingLevel,
    DiscoveryResult,
    _detect_processing_level,
    _is_fcs_file,
    DEFAULT_MAX_DEPTH,
)


@pytest.fixture
def temp_fcs_dir():
    """Create a temporary directory structure with FCS files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create nested structure similar to real experiments
        # Raw data
        raw_dir = root / "Raw" / "samples" / "Group_001"
        raw_dir.mkdir(parents=True)
        (raw_dir / "A1 M1.fcs").touch()
        (raw_dir / "A2 M2.fcs").touch()

        # Unmixed data (different processing level)
        unmixed_dir = root / "Unmixed" / "samples" / "Group_001"
        unmixed_dir.mkdir(parents=True)
        (unmixed_dir / "A1 M1.fcs").touch()  # Duplicate filename!
        (unmixed_dir / "A2 M2.fcs").touch()  # Duplicate filename!
        (unmixed_dir / "A3 M3.fcs").touch()  # Unique to Unmixed

        # Mixed case extensions
        mixed_dir = root / "MixedCase"
        mixed_dir.mkdir(parents=True)
        (mixed_dir / "sample1.FCS").touch()
        (mixed_dir / "sample2.Fcs").touch()
        (mixed_dir / "sample3.fcs").touch()

        # Non-FCS files (should be ignored)
        (root / "readme.txt").touch()
        (mixed_dir / "notes.csv").touch()

        yield root


@pytest.fixture
def simple_fcs_dir():
    """Create a simple flat directory with FCS files (no duplicates)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "sample_A.fcs").touch()
        (root / "sample_B.fcs").touch()
        (root / "sample_C.fcs").touch()

        yield root


class TestIsFcsFile:
    """Tests for _is_fcs_file helper."""

    def test_lowercase_fcs(self):
        assert _is_fcs_file(Path("sample.fcs")) is True

    def test_uppercase_fcs(self):
        assert _is_fcs_file(Path("sample.FCS")) is True

    def test_mixed_case_fcs(self):
        assert _is_fcs_file(Path("sample.Fcs")) is True

    def test_non_fcs_file(self):
        assert _is_fcs_file(Path("sample.txt")) is False

    def test_no_extension(self):
        assert _is_fcs_file(Path("sample")) is False

    def test_macos_resource_fork_excluded(self):
        """Test that macOS resource fork files (._*) are excluded."""
        # Resource forks have ._ prefix and match extension
        assert _is_fcs_file(Path("._sample.fcs")) is False
        assert _is_fcs_file(Path("._A1 M1.fcs")) is False
        assert _is_fcs_file(Path("._H4 B220.fcs")) is False

    def test_macos_resource_fork_uppercase_excluded(self):
        """Test that uppercase macOS resource forks are excluded."""
        assert _is_fcs_file(Path("._sample.FCS")) is False
        assert _is_fcs_file(Path("._SAMPLE.Fcs")) is False


class TestProcessingLevelDetection:
    """Tests for _detect_processing_level helper."""

    def test_raw_detection(self):
        path = Path("/data/Raw/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.RAW

    def test_unmixed_detection(self):
        path = Path("/data/Unmixed/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.UNMIXED

    def test_comp_detection(self):
        path = Path("/data/Compensated/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.COMPENSATED

    def test_unknown_detection(self):
        path = Path("/data/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.UNKNOWN

    def test_case_insensitive(self):
        path = Path("/data/RAW/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.RAW

        path = Path("/data/unmixed/samples/A1.fcs")
        assert _detect_processing_level(path) == ProcessingLevel.UNMIXED


class TestDiscoverFcsFiles:
    """Tests for discover_fcs_files function."""

    def test_discover_flat_directory(self, simple_fcs_dir):
        """Test discovery in a flat directory."""
        result = discover_fcs_files(simple_fcs_dir)

        assert result.total_count == 3
        assert result.root_dir == simple_fcs_dir
        assert not result.has_duplicates

    def test_discover_nested_directory(self, temp_fcs_dir):
        """Test discovery in nested directory structure."""
        result = discover_fcs_files(temp_fcs_dir)

        # Should find: 2 Raw + 3 Unmixed + 3 MixedCase = 8 total
        assert result.total_count == 8

    def test_detects_duplicates(self, temp_fcs_dir):
        """Test that duplicate filenames are detected."""
        result = discover_fcs_files(temp_fcs_dir)

        assert result.has_duplicates
        # A1 M1.fcs and A2 M2.fcs appear in both Raw and Unmixed
        assert "a1 m1.fcs" in result.duplicate_filenames
        assert "a2 m2.fcs" in result.duplicate_filenames
        assert len(result.duplicate_filenames["a1 m1.fcs"]) == 2

    def test_processing_level_grouping(self, temp_fcs_dir):
        """Test that files are grouped by processing level."""
        result = discover_fcs_files(temp_fcs_dir)

        raw_files = result.get_files_for_level(ProcessingLevel.RAW)
        unmixed_files = result.get_files_for_level(ProcessingLevel.UNMIXED)
        unknown_files = result.get_files_for_level(ProcessingLevel.UNKNOWN)

        assert len(raw_files) == 2
        assert len(unmixed_files) == 3
        assert len(unknown_files) == 3  # MixedCase directory

    def test_case_insensitive_extensions(self, temp_fcs_dir):
        """Test that all FCS extensions are found."""
        result = discover_fcs_files(temp_fcs_dir)

        # Check all mixed case files were found
        filenames = [f.name for f in result.fcs_files]
        assert "sample1.FCS" in filenames
        assert "sample2.Fcs" in filenames
        assert "sample3.fcs" in filenames

    def test_max_depth_limit(self, temp_fcs_dir):
        """Test that max_depth limits search depth."""
        result = discover_fcs_files(temp_fcs_dir, max_depth=1)

        # With depth 1, should only find MixedCase files (depth 1)
        # Raw and Unmixed are at depth 3 (Raw/samples/Group_001/)
        assert result.total_count == 3

    def test_nonexistent_directory(self):
        """Test handling of nonexistent directory."""
        result = discover_fcs_files("/nonexistent/path")

        assert result.total_count == 0
        assert not result.has_duplicates

    def test_empty_directory(self):
        """Test handling of empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_fcs_files(tmpdir)

            assert result.total_count == 0
            assert not result.has_duplicates

    def test_filename_map_excludes_duplicates(self, temp_fcs_dir):
        """Test that filename_map only contains unique filenames."""
        result = discover_fcs_files(temp_fcs_dir)

        # Unique files should be in filename_map
        assert "a3 m3.fcs" in result.filename_map
        assert "sample1.fcs" in result.filename_map

        # Duplicates should NOT be in filename_map
        assert "a1 m1.fcs" not in result.filename_map
        assert "a2 m2.fcs" not in result.filename_map

    def test_excludes_macos_resource_forks(self):
        """Test that macOS resource fork files (._*) are not discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create real FCS files
            (root / "A1 M1.fcs").touch()
            (root / "B2 M2.fcs").touch()

            # Create macOS resource fork files (._*)
            # These are automatically created by macOS and contain metadata
            (root / "._A1 M1.fcs").touch()
            (root / "._B2 M2.fcs").touch()
            (root / "._Hidden.fcs").touch()

            result = discover_fcs_files(root)

            # Should only find the 2 real FCS files, not the 3 resource forks
            assert result.total_count == 2

            # Verify no resource fork names in results
            filenames = [f.name for f in result.fcs_files]
            assert "A1 M1.fcs" in filenames
            assert "B2 M2.fcs" in filenames
            assert "._A1 M1.fcs" not in filenames
            assert "._B2 M2.fcs" not in filenames
            assert "._Hidden.fcs" not in filenames


class TestResolveFcsFile:
    """Tests for resolve_fcs_file function."""

    def test_resolve_unique_file(self, temp_fcs_dir):
        """Test resolving a unique filename."""
        result = discover_fcs_files(temp_fcs_dir)

        path = resolve_fcs_file("A3 M3.fcs", result)
        assert path is not None
        assert path.name == "A3 M3.fcs"

    def test_resolve_duplicate_without_preference(self, temp_fcs_dir):
        """Test resolving a duplicate filename without preference."""
        result = discover_fcs_files(temp_fcs_dir)

        path = resolve_fcs_file("A1 M1.fcs", result)
        assert path is not None
        assert path.name == "A1 M1.fcs"

    def test_resolve_duplicate_with_preference(self, temp_fcs_dir):
        """Test resolving a duplicate filename with processing level preference."""
        result = discover_fcs_files(temp_fcs_dir)

        path = resolve_fcs_file("A1 M1.fcs", result, ProcessingLevel.UNMIXED)
        assert path is not None
        assert "Unmixed" in str(path)

        path = resolve_fcs_file("A1 M1.fcs", result, ProcessingLevel.RAW)
        assert path is not None
        assert "Raw" in str(path)

    def test_resolve_nonexistent_file(self, temp_fcs_dir):
        """Test resolving a nonexistent filename."""
        result = discover_fcs_files(temp_fcs_dir)

        path = resolve_fcs_file("nonexistent.fcs", result)
        assert path is None

    def test_resolve_case_insensitive(self, temp_fcs_dir):
        """Test that filename resolution is case-insensitive."""
        result = discover_fcs_files(temp_fcs_dir)

        # Should resolve regardless of case
        path1 = resolve_fcs_file("sample1.fcs", result)
        path2 = resolve_fcs_file("SAMPLE1.FCS", result)

        assert path1 is not None
        assert path2 is not None


class TestGetFcsFileList:
    """Tests for get_fcs_file_list function."""

    def test_get_all_files(self, temp_fcs_dir):
        """Test getting all FCS files as strings."""
        result = discover_fcs_files(temp_fcs_dir)
        file_list = get_fcs_file_list(result)

        assert len(file_list) == 8
        assert all(isinstance(f, str) for f in file_list)

    def test_get_files_by_level(self, temp_fcs_dir):
        """Test getting files filtered by processing level."""
        result = discover_fcs_files(temp_fcs_dir)

        raw_list = get_fcs_file_list(result, ProcessingLevel.RAW)
        assert len(raw_list) == 2

        unmixed_list = get_fcs_file_list(result, ProcessingLevel.UNMIXED)
        assert len(unmixed_list) == 3


class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""

    def test_get_summary(self, temp_fcs_dir):
        """Test the summary string generation."""
        result = discover_fcs_files(temp_fcs_dir)
        summary = result.get_summary()

        assert "8 FCS files" in summary
        assert "raw" in summary.lower()
        assert "unmixed" in summary.lower()
        assert "duplicate" in summary.lower()

    def test_get_preferred_files_prefers_unmixed(self, temp_fcs_dir):
        """Test that get_preferred_files prefers Unmixed."""
        result = discover_fcs_files(temp_fcs_dir)

        preferred = result.get_preferred_files()
        # Should return Unmixed files since they're the highest priority
        assert len(preferred) == 3
        for path in preferred:
            assert "Unmixed" in str(path)
