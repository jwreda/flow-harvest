"""
Tests for Keywords Model.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from flowkit_gui.models.keywords_model import KeywordsModel
from flowkit_gui.models.workspace_model import Sample


def create_sample(sample_id, name, keywords):
    """Helper to create sample with keywords."""
    return Sample(
        sample_id=sample_id,
        name=name,
        fcs_path=None,
        group="",
        keywords=keywords,
        event_count=10000
    )


class TestKeywordsModel:
    """Tests for KeywordsModel."""

    def test_model_initialization(self):
        """Test model initializes empty."""
        model = KeywordsModel()
        assert model.keyword_names == []

    def test_set_samples(self):
        """Test setting samples extracts keyword names."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C", "$FIL": "Sample1.fcs"}),
            create_sample("s2", "Sample2.fcs", {"Mouse #": "456", "RT": "RT", "$FIL": "Sample2.fcs"}),
        ]
        model.set_samples(samples)

        # Should only include custom keywords, not system ones
        assert "Mouse #" in model.keyword_names
        assert "Tumor" in model.keyword_names
        assert "RT" in model.keyword_names
        assert "$FIL" not in model.keyword_names

    def test_tidy_dataframe_structure(self):
        """Test tidy dataframe has correct structure."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C"}),
        ]
        model.set_samples(samples)

        df = model.get_tidy_dataframe()

        assert "sample_id" in df.columns
        assert "sample_name" in df.columns
        assert "keyword_name" in df.columns
        assert "keyword_value" in df.columns

    def test_tidy_dataframe_rows(self):
        """Test tidy dataframe has one row per keyword per sample."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C"}),
            create_sample("s2", "Sample2.fcs", {"Mouse #": "456", "Tumor": "V"}),
        ]
        model.set_samples(samples)

        df = model.get_tidy_dataframe()

        # 2 samples * 2 keywords = 4 rows
        assert len(df) == 4

        # Check specific values
        s1_mouse = df[(df['sample_id'] == 's1') & (df['keyword_name'] == 'Mouse #')]
        assert len(s1_mouse) == 1
        assert s1_mouse['keyword_value'].values[0] == '123'

    def test_wide_dataframe_structure(self):
        """Test wide dataframe has keywords as columns."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C", "RT": "No RT"}),
        ]
        model.set_samples(samples)

        df = model.get_wide_dataframe()

        assert "sample_id" in df.columns
        assert "sample_name" in df.columns
        assert "Mouse #" in df.columns
        assert "Tumor" in df.columns
        assert "RT" in df.columns

    def test_wide_dataframe_rows(self):
        """Test wide dataframe has one row per sample."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C"}),
            create_sample("s2", "Sample2.fcs", {"Mouse #": "456", "Tumor": "V"}),
        ]
        model.set_samples(samples)

        df = model.get_wide_dataframe()

        # One row per sample
        assert len(df) == 2

    def test_wide_dataframe_column_order(self):
        """Test wide dataframe has sample_name first, then keywords, then sample_id."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C", "RT": "RT"}),
        ]
        model.set_samples(samples)

        df = model.get_wide_dataframe()
        columns = list(df.columns)

        # sample_name should be first (primary identifier)
        assert columns[0] == "sample_name"

        # sample_id should be last (reference)
        assert columns[-1] == "sample_id"

        # Keywords should be in between
        mouse_idx = columns.index("Mouse #")
        sample_name_idx = columns.index("sample_name")
        sample_id_idx = columns.index("sample_id")

        assert sample_name_idx < mouse_idx < sample_id_idx

    def test_get_keywords_for_sample(self):
        """Test getting keywords for specific sample."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "Tumor": "C", "$FIL": "file"}),
            create_sample("s2", "Sample2.fcs", {"Mouse #": "456", "Tumor": "V", "$FIL": "file"}),
        ]
        model.set_samples(samples)

        kw = model.get_keywords_for_sample("s1")
        assert kw["Mouse #"] == "123"
        assert kw["Tumor"] == "C"
        assert "$FIL" not in kw  # System keyword filtered

        kw = model.get_keywords_for_sample("s2")
        assert kw["Mouse #"] == "456"

    def test_get_keywords_for_nonexistent_sample(self):
        """Test getting keywords for nonexistent sample returns empty dict."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123"}),
        ]
        model.set_samples(samples)

        kw = model.get_keywords_for_sample("nonexistent")
        assert kw == {}

    def test_get_keyword_values(self):
        """Test getting all unique values for a keyword."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Tumor": "C"}),
            create_sample("s2", "Sample2.fcs", {"Tumor": "V"}),
            create_sample("s3", "Sample3.fcs", {"Tumor": "C"}),  # Duplicate
        ]
        model.set_samples(samples)

        values = model.get_keyword_values("Tumor")
        assert "C" in values
        assert "V" in values
        assert len(values) == 2  # Only unique values

    def test_empty_keyword_handling(self):
        """Test handling of empty/None keyword values."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Mouse #": "123", "RT": ""}),
            create_sample("s2", "Sample2.fcs", {"Mouse #": "456", "RT": None}),
        ]
        model.set_samples(samples)

        df = model.get_wide_dataframe()

        # Empty values should be empty strings
        assert df[df['sample_id'] == 's1']['RT'].values[0] == ''

    def test_system_keyword_filtering(self):
        """Test that system keywords are properly filtered."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {
                "Mouse #": "123",
                "$FIL": "filename",
                "P1DISPLAY": "LOG",
                "FSC-A": "Forward Scatter",
                "SPILL": "matrix",
                "BEGINDATA": "0",
                "Custom Key": "value"
            }),
        ]
        model.set_samples(samples)

        keywords = model.keyword_names
        assert "Mouse #" in keywords
        assert "Custom Key" in keywords
        assert "$FIL" not in keywords
        assert "P1DISPLAY" not in keywords
        assert "BEGINDATA" not in keywords

    def test_wide_dataframe_custom_index(self):
        """Test wide dataframe with custom index columns after sample_name."""
        model = KeywordsModel()
        samples = [
            create_sample("s1", "Sample1.fcs", {"Group": "A", "Treatment": "Drug1", "Mouse #": "123"}),
            create_sample("s2", "Sample2.fcs", {"Group": "B", "Treatment": "Control", "Mouse #": "456"}),
        ]
        model.set_samples(samples)

        df = model.get_wide_dataframe(index_columns=["Group", "Treatment"])
        columns = list(df.columns)

        # sample_name is always first (primary identifier)
        assert columns[0] == "sample_name"
        # Custom index columns come after sample_name
        assert columns[1] == "Group"
        assert columns[2] == "Treatment"
        # sample_id is always last
        assert columns[-1] == "sample_id"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
