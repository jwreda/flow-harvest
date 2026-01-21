# CLAUDE.md - Project Instructions

## Project Overview

FlowKit GUI is a PyQt5 application for flow cytometry data analysis. It wraps the FlowKit library to parse FlowJo workspace (WSP) files, display gating hierarchies, and export statistics to Excel.

## Quick Start Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Run the application
python -m flowkit_gui.main

# Run all tests
pytest

# Run tests with verbose output
pytest -v
```

## Architecture

### Models (flowkit_gui/models/)
- **workspace_model.py**: Core FlowKit wrapper - loads WSP files, extracts samples/gates/channels
- **gate_tree_model.py**: Qt tree model (QStandardItemModel) with checkbox support for gate selection
- **keywords_model.py**: Extracts custom keywords (filters system keywords), generates tidy and wide DataFrames
- **statistics_model.py**: MFI calculation orchestration, MFIMetric enum

### Views (flowkit_gui/views/)
- **main_window.py**: Main PyQt5 window with all UI components

### Exporters (flowkit_gui/exporters/)
- **xlsx_exporter.py**: Multi-sheet Excel export with formatting (freeze panes, auto-width)

### Utils (flowkit_gui/utils/)
- **mfi_calculations.py**: Mean, median, geometric mean functions
- **theme.py**: Theme loading, icon utilities, and QSS stylesheet application
- **logging_config.py**: Configures logging to `flowkit_debug.log`

### Resources (flowkit_gui/resources/)
- **icons/**: Custom SVG icons for the UI
- **styles/**: `flowkit_theme.qss` - pink-accented modern theme stylesheet

## Key Technical Details

### FlowKit Sample Analysis
Before querying gate membership or statistics, samples MUST be analyzed. Use the `analyze_samples` method (plural) with keyword argument:
```python
# Correct - analyze_samples with sample_id keyword argument
workspace.analyze_samples(sample_id=sample_id)

# WRONG - analyze_sample doesn't exist
workspace.analyze_sample(sample_id)  # AttributeError!
```

### FlowKit Gate IDs
FlowKit returns gate IDs as tuples: `(gate_name, (path_tuple))`. When calling `get_gate()`, pass the gate name and path separately:
```python
gate_name, gate_path_tuple = gate_info
gate = workspace.get_gate(sample_id, gate_name, gate_path=gate_path_tuple)
```

### System Keywords Filtering
The `Sample.get_custom_keywords()` method filters out system keywords (starting with `$`, `P1-P35`, `FSC`, etc.) to show only user-defined keywords like `Mouse #`, `Tumor`, `RT`.

### Test Data
- WSP file: `example_workspace.wsp` (45MB, 72 samples referenced)
- FCS files: `A1 M1.fcs`, `A2 M2.fcs`, `A3 M3.fcs` (3 available locally)

## Testing

All tests use pytest. Some tests require PyQt5's QApplication:
```python
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
```

The xlsx_exporter tests use a MockWorkspaceModel to avoid FlowKit dependency in unit tests.

## Export Sheets

1. **Gating_Strategy**: Full gate paths, types, parameters
2. **Keywords**: Tidy format (one row per keyword per sample)
3. **Keywords_Wide** (optional): Pivot format with keywords as columns
4. **Statistics_Selected**: MFI for user-selected markers
5. **Statistics_All**: MFI for all channels

## Common Issues

### NumPy Version Conflicts
If you see `numpy.core.multiarray failed to import`, upgrade pandas:
```bash
pip install --upgrade pandas
```

### Floating Point Precision
Geometric mean calculations may have floating point imprecision. Use approximate comparisons:
```python
assert abs(result - expected) < 0.0001  # Not: assert result == expected
```

### All Zeros in Output
If exported statistics show all zeros despite samples having event data, check `flowkit_debug.log` for errors. Common causes:
- FlowKit API called incorrectly (see "FlowKit Sample Analysis" above)
- Silent exception handling hiding the real error - always log exceptions before continuing
