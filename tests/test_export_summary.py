"""
Tests for Export Summary functionality.
"""

import pytest
from flowkit_gui.exporters.xlsx_exporter import (
    ExportSummary, CompensationSummary, StatisticsSummary
)
from flowkit_gui.models.workspace_model import DataSource


def test_compensation_summary_creation():
    """Test CompensationSummary data structure."""
    comp = CompensationSummary(
        mode=DataSource.AUTO,
        total_samples=10,
        matrices_used={"Matrix-A": 8, "Matrix-B": 2},
        failed_samples=0,
        spectral_samples=2
    )

    assert comp.mode == DataSource.AUTO
    assert comp.total_samples == 10
    assert len(comp.matrices_used) == 2
    assert comp.matrices_used["Matrix-A"] == 8
    assert comp.matrices_used["Matrix-B"] == 2
    assert comp.failed_samples == 0
    assert comp.spectral_samples == 2


def test_compensation_summary_raw_mode():
    """Test CompensationSummary with RAW data mode."""
    comp = CompensationSummary(
        mode=DataSource.RAW,
        total_samples=10,
        matrices_used={},  # No matrices in raw mode
        failed_samples=0,
        spectral_samples=0
    )

    assert comp.mode == DataSource.RAW
    assert len(comp.matrices_used) == 0


def test_compensation_summary_with_failures():
    """Test CompensationSummary with compensation failures."""
    comp = CompensationSummary(
        mode=DataSource.COMP,
        total_samples=10,
        matrices_used={"Matrix-A": 8},
        failed_samples=2,  # 2 samples failed
        spectral_samples=0
    )

    assert comp.failed_samples == 2
    assert comp.total_samples == 10


def test_statistics_summary_creation():
    """Test StatisticsSummary data structure."""
    stats = StatisticsSummary(
        gates_exported=5,
        channels_analyzed=12,
        mfi_metrics=["Mean", "Median", "GeoMean"],
        total_mfi_calculations=1800,  # 5 * 12 * 3 * 10 samples
        frequency_calculations=50  # 5 * 10 samples
    )

    assert stats.gates_exported == 5
    assert stats.channels_analyzed == 12
    assert len(stats.mfi_metrics) == 3
    assert "Mean" in stats.mfi_metrics
    assert "Median" in stats.mfi_metrics
    assert "GeoMean" in stats.mfi_metrics
    assert stats.total_mfi_calculations == 1800
    assert stats.frequency_calculations == 50


def test_statistics_summary_single_metric():
    """Test StatisticsSummary with single metric."""
    stats = StatisticsSummary(
        gates_exported=3,
        channels_analyzed=8,
        mfi_metrics=["Mean"],
        total_mfi_calculations=240,  # 3 * 8 * 1 * 10
        frequency_calculations=30
    )

    assert len(stats.mfi_metrics) == 1
    assert stats.mfi_metrics[0] == "Mean"


def test_export_summary_full():
    """Test complete ExportSummary structure."""
    summary = ExportSummary(
        success=True,
        filepath="/path/to/export.xlsx",
        samples_processed=10,
        gates_exported=5,
        keywords_exported=8,
        compensation=CompensationSummary(
            mode=DataSource.COMP,
            total_samples=10,
            matrices_used={"Matrix-A": 10},
            failed_samples=0,
            spectral_samples=0
        ),
        statistics=StatisticsSummary(
            gates_exported=5,
            channels_analyzed=12,
            mfi_metrics=["Mean", "Median"],
            total_mfi_calculations=1200,
            frequency_calculations=50
        ),
        sheets_created=["Gating_Strategy", "Keywords", "MFI_Selected"],
        warnings=[],
        errors=[]
    )

    assert summary.success == True
    assert summary.filepath == "/path/to/export.xlsx"
    assert summary.samples_processed == 10
    assert summary.gates_exported == 5
    assert summary.keywords_exported == 8
    assert len(summary.sheets_created) == 3
    assert "Gating_Strategy" in summary.sheets_created
    assert len(summary.warnings) == 0
    assert len(summary.errors) == 0


def test_export_summary_with_warnings():
    """Test ExportSummary with warnings and failures."""
    summary = ExportSummary(
        success=True,
        filepath="/path/to/export.xlsx",
        samples_processed=10,
        gates_exported=5,
        keywords_exported=8,
        compensation=CompensationSummary(
            mode=DataSource.AUTO,
            total_samples=10,
            matrices_used={"Matrix-A": 8},
            failed_samples=2,  # 2 samples failed compensation
            spectral_samples=0
        ),
        statistics=StatisticsSummary(
            gates_exported=5,
            channels_analyzed=12,
            mfi_metrics=["Mean"],
            total_mfi_calculations=600,
            frequency_calculations=50
        ),
        sheets_created=["Gating_Strategy", "Keywords", "Warnings"],
        warnings=[
            "Sample 'S9' compensation failed",
            "Sample 'S10' compensation failed"
        ],
        errors=[]
    )

    assert summary.compensation.failed_samples == 2
    assert len(summary.warnings) == 2
    assert "Warnings" in summary.sheets_created
    # Still marked as success since export completed
    assert summary.success == True


def test_export_summary_all_sheets():
    """Test ExportSummary with many sheets created."""
    all_sheets = [
        "Gating_Strategy", "Keywords", "Keywords_Wide",
        "Counts_All", "Counts_Selected",
        "Frequencies_All", "Frequencies_Selected",
        "MFI_Selected", "MFI_All",
        "Concatenated_Selected", "Concatenated_All"
    ]

    summary = ExportSummary(
        success=True,
        filepath="/path/to/export.xlsx",
        samples_processed=50,
        gates_exported=10,
        keywords_exported=5,
        compensation=CompensationSummary(
            mode=DataSource.AUTO,
            total_samples=50,
            matrices_used={"Compensation-copy": 50},
            failed_samples=0,
            spectral_samples=0
        ),
        statistics=StatisticsSummary(
            gates_exported=10,
            channels_analyzed=20,
            mfi_metrics=["Mean", "Median", "GeoMean"],
            total_mfi_calculations=30000,  # 10 * 20 * 3 * 50
            frequency_calculations=500
        ),
        sheets_created=all_sheets,
        warnings=[],
        errors=[]
    )

    assert len(summary.sheets_created) == 11
    assert summary.statistics.total_mfi_calculations == 30000


def test_export_summary_spectral_compensation():
    """Test ExportSummary with spectral compensation."""
    summary = ExportSummary(
        success=True,
        filepath="/path/to/export.xlsx",
        samples_processed=20,
        gates_exported=5,
        keywords_exported=3,
        compensation=CompensationSummary(
            mode=DataSource.AUTO,
            total_samples=20,
            matrices_used={"Spectral-unmix-v1": 20},
            failed_samples=0,
            spectral_samples=20  # All samples use spectral
        ),
        statistics=StatisticsSummary(
            gates_exported=5,
            channels_analyzed=30,  # Spectral typically has many channels
            mfi_metrics=["Mean"],
            total_mfi_calculations=3000,
            frequency_calculations=100
        ),
        sheets_created=["Gating_Strategy", "Keywords", "MFI_Selected"],
        warnings=[],
        errors=[]
    )

    assert summary.compensation.spectral_samples == 20
    assert summary.compensation.total_samples == 20


def test_export_summary_multiple_matrices():
    """Test ExportSummary with multiple compensation matrices."""
    summary = ExportSummary(
        success=True,
        filepath="/path/to/export.xlsx",
        samples_processed=30,
        gates_exported=5,
        keywords_exported=4,
        compensation=CompensationSummary(
            mode=DataSource.AUTO,
            total_samples=30,
            matrices_used={
                "Compensation-Panel1": 15,
                "Compensation-Panel2": 10,
                "Compensation-Panel3": 5
            },
            failed_samples=0,
            spectral_samples=0
        ),
        statistics=StatisticsSummary(
            gates_exported=5,
            channels_analyzed=10,
            mfi_metrics=["Mean", "Median"],
            total_mfi_calculations=3000,
            frequency_calculations=150
        ),
        sheets_created=["Gating_Strategy", "Keywords"],
        warnings=[],
        errors=[]
    )

    assert len(summary.compensation.matrices_used) == 3
    total_from_matrices = sum(summary.compensation.matrices_used.values())
    assert total_from_matrices == 30
