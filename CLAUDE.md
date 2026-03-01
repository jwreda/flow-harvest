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

### Config (flowkit_gui/config/)
- **defaults.py**: Cache memory limits, batch size, GC interval, worker count defaults

### Controllers (flowkit_gui/controllers/)
- **export_controller.py**: Business logic for export operations (validation, config building, execution)

### Models (flowkit_gui/models/)
- **workspace_model.py**: Core FlowKit wrapper - loads WSP files, extracts samples/gates/channels, `_failed_samples` tracking
- **gate_tree_model.py**: Qt tree model (QStandardItemModel) with checkbox support for gate selection
- **keywords_model.py**: Extracts custom keywords (filters system keywords), generates tidy and wide DataFrames
- **statistics_model.py**: MFI calculation orchestration, MFIMetric enum, volume/bead normalization, scale factors
- **gate_marker_matrix_model.py**: Data model for the gate-marker selection matrix
- **sample_selection_model.py**: Sample list model with Events, Comp, and ScaleFactor columns
- **wsp_metadata_parser.py**: WSP XML metadata extraction utilities

### Views (flowkit_gui/views/)
- **main_window.py**: Main PyQt5 window with all UI orchestration (~2700+ lines)
- **gate_tree_view.py**: Gate hierarchy tree view widget
- **gate_marker_matrix_view.py**: Gate-marker matrix grid view for selecting markers per gate
- **colored_gate_tree_delegate.py**: Custom tree delegate with colored gate indicators
- **styled_tree_delegate.py**: Themed tree item delegate for consistent styling
- **export_summary_dialog.py**: Post-export summary dialog
- **splash_screen.py**: Theme-aware startup splash screen with progress

### Exporters (flowkit_gui/exporters/)
- **xlsx_exporter.py**: Multi-sheet Excel export with formatting (freeze panes, auto-width)
- **export_config.py**: ExportConfig dataclass with 20 fields, dual-mode constructor

### Utils (flowkit_gui/utils/)
- **mfi_calculations.py**: Mean, median, geometric mean functions
- **theme.py**: Theme loading, icon tinting (CompositionMode_SourceIn), icon cache, QSS application
- **theme_manager.py**: Dark/light theme switching and persistence
- **logging_config.py**: Configures logging to `flowkit_debug.log`
- **settings_manager.py**: QSettings wrapper for persistent user preferences (performance, theme, geometry)
- **memory_utils.py**: psutil-based memory checks and export memory estimation
- **animations.py**: UI animation helpers
- **cache.py**: Data caching utilities
- **cancellation.py**: Cancellation token for long-running operations
- **colors_dark.py**: Dark theme color palette constants
- **colors_light.py**: Light theme color palette constants
- **fcs_discovery.py**: FCS file search and matching logic
- **timing.py**: Performance timing utilities
- **wait_cursor.py**: Context manager for busy cursor display

### Resources (flowkit_gui/resources/)
- **icons/**: 23 Lucide SVG icons (stroke="currentColor"), auto-tinted via `get_icon()`
- **styles/**: `base.qss` - base QSS stylesheet for theming

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
