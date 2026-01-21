# FlowKit GUI

A Python GUI application for extracting gating strategies and sample keywords from FlowJo workspace (WSP) files and exporting analysis results to tidy XLSX format.

## Installation (macOS)

### Step 1: Install Homebrew (if not already installed)

Open Terminal and run:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the prompts. After installation, add Homebrew to your PATH if instructed.

### Step 2: Install Python

macOS comes with Python, but we recommend installing a recent version via Homebrew:
```bash
brew install python@3.11
```

Verify installation:
```bash
python3 --version  # Should show 3.11.x or higher
```

### Step 3: Clone or Download the Project

```bash
cd ~/Documents  # or wherever you keep projects
git clone <repository-url> flowkit
cd flowkit
```

Or if you have the folder already, just navigate to it:
```bash
cd "/path/to/flowkit"
```

### Step 4: Create and Activate Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it (you'll need to do this each time you open a new terminal)
source venv/bin/activate

# Your prompt should now show (venv) at the beginning
```

### Step 5: Install Dependencies

```bash
# Install the package and all dependencies
pip install -e .

# For development (includes pytest for running tests)
pip install -e ".[dev]"
```

### Step 6: Run the Application

```bash
# Make sure venv is activated (you should see (venv) in your prompt)
source venv/bin/activate

# Run the GUI
python -m flowkit_gui.main
```

### Quick Start (after initial setup)

Once installed, you only need these commands to run the app:
```bash
cd "/path/to/flowkit"
source venv/bin/activate
python -m flowkit_gui.main
```

---

## What This Tool Does

FlowKit GUI bridges the gap between FlowJo's excellent visual gating interface and downstream statistical analysis. It:

1. **Reads FlowJo Workspaces**: Parses WSP files to extract the complete gating hierarchy you've defined in FlowJo
2. **Applies Gates to FCS Data**: Uses the FlowKit library to calculate which events fall within each gate
3. **Calculates Statistics**: Computes cell counts, percentages, and Mean Fluorescence Intensity (MFI) for each gate
4. **Exports to Excel**: Generates analysis-ready XLSX files with multiple sheets in tidy format

### Why This Tool?

FlowJo remains excellent for visually drawing gates, but can be slow and cumbersome for systematic downstream analysis. Exporting statistics from FlowJo requires clicking through many dialogs, and the output format often needs manual reshaping.

This tool preserves your ability to set gating strategies in FlowJo while enabling efficient batch export of statistics in formats ready for R/tidyverse, GraphPad Prism, or other analysis tools.

---

## How It Works

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        main_window.py                        │
│                      (PyQt5 GUI Layer)                       │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ workspace_    │   │ gate_tree_      │   │ keywords_       │
│ model.py      │   │ model.py        │   │ model.py        │
│               │   │                 │   │                 │
│ FlowKit       │   │ Qt Tree with    │   │ Sample keyword  │
│ wrapper       │   │ checkboxes      │   │ extraction      │
└───────────────┘   └─────────────────┘   └─────────────────┘
        │
        ▼
┌───────────────┐   ┌─────────────────┐
│ statistics_   │   │ xlsx_exporter   │
│ model.py      │──▶│ .py             │──▶ Excel File
│               │   │                 │
│ MFI calcs     │   │ Multi-sheet     │
└───────────────┘   └─────────────────┘
```

### Data Flow

1. **Load Workspace**: User selects a WSP file. `workspace_model.py` uses FlowKit to parse the XML structure and locate associated FCS files.

2. **Analyze Samples**: FlowKit's `analyze_samples()` method applies all gates to the FCS event data, calculating which events belong to which gates.

3. **Display Hierarchy**: `gate_tree_model.py` builds a Qt tree widget showing the nested gate structure with checkboxes for selection.

4. **Calculate Statistics**: When exporting, `statistics_model.py` queries FlowKit for gate membership counts and calculates MFI values for selected channels.

5. **Export**: `xlsx_exporter.py` assembles all data into a multi-sheet Excel workbook with proper formatting.

### Key FlowKit Concepts

- **Workspace**: The parsed WSP file containing gate definitions and sample references
- **Sample**: An FCS file with event data (each row = one cell, columns = measured parameters)
- **Gate**: A region in parameter space (polygon, rectangle, quadrant, etc.) defining a cell population
- **Gate Membership**: Boolean array indicating which events fall within a gate

---

## Design Decisions

### Why PyQt5?

- Cross-platform (macOS, Windows, Linux) with native look and feel
- Mature ecosystem with good documentation
- QTreeView with checkboxes provides intuitive gate selection
- Better performance than web-based alternatives for desktop use

### Why FlowKit?

FlowKit is the most complete Python library for flow cytometry analysis:
- Full WSP parsing support (FlowJo 10.x workspaces)
- Handles all gate types (polygon, rectangle, ellipse, quadrant, boolean)
- Proper compensation and transformation support
- Active maintenance

### Why Tidy Data Format?

The export uses "tidy" data principles (one observation per row):
- Direct compatibility with R's tidyverse (`dplyr`, `ggplot2`)
- Easy pivot operations for tools that prefer wide format
- No manual reshaping needed before analysis
- Keywords sheet can be joined to statistics by sample_id

### Why Separate Models from Views?

The MVC-like architecture (models/, views/, exporters/) provides:
- Testability: Models can be unit tested without GUI
- Flexibility: Could add CLI export without changing core logic
- Maintainability: Clear separation of concerns

### Error Handling Philosophy

The application logs errors to `flowkit_debug.log` but continues processing when possible. This means:
- A single problematic gate won't block the entire export
- Missing FCS files are noted but don't crash the app
- Users can check the log file for diagnostic details

---

## Features

- **WSP Parsing**: Extract full gating hierarchy from FlowJo workspace files
- **FCS Support**: Apply gates to FCS files and calculate statistics
- **GUI Display**: Show gating strategy as navigable tree with checkboxes
- **Sample Keywords**: View and export custom keywords (Mouse #, Tumor, RT, etc.)
- **MFI Metrics**: Calculate Mean, Median, and/or Geometric Mean intensities
- **Marker Selection**: Choose specific markers for MFI or export all
- **XLSX Export**: Tidy format suitable for R/tidyverse, GraphPad Prism, etc.

---

## Usage

### Workflow

1. **Open WSP File**: Click "Open WSP" and select your FlowJo workspace file
2. **Select FCS Directory**: Choose the folder containing your FCS files (or use the WSP directory)
3. **Select Gates**: Check/uncheck gates in the hierarchy tree to include in export
4. **View Keywords**: Select samples from dropdown to view their keywords
5. **Configure MFI**: Select which MFI metrics to calculate (Mean, Median, Geometric Mean)
6. **Select Markers** (optional): Choose specific markers or leave blank for all
7. **Export**: Click "Export XLSX" to generate the analysis file

---

## Export Format

The XLSX file contains multiple sheets:

### Gating_Strategy
Documents the hierarchical gate structure with full paths:

| Gate Path | Gate Name | Depth | Gate Type | Parameters |
|-----------|-----------|-------|-----------|------------|
| Cells | Cells | 0 | PolygonGate | FSC-A, SSC-A |
| Cells/Single Cells | Single Cells | 1 | PolygonGate | FSC-A, FSC-H |

### Keywords (Tidy Format)
One row per keyword per sample - ready for `pivot_wider()` in R:

| sample_id | sample_name | keyword_name | keyword_value |
|-----------|-------------|--------------|---------------|
| 44 | A5 M5.fcs | Mouse # | 674 |
| 44 | A5 M5.fcs | Tumor | C |

### Keywords_Wide (Optional)
One row per sample with keywords as columns.

### Statistics_Selected / Statistics_All
MFI statistics for selected or all channels, with gate hierarchy preserved.

---

## Troubleshooting

### All Zeros in Output
If exported statistics show all zeros despite samples having event data:
1. Check `flowkit_debug.log` for error messages
2. Ensure FCS files are in the directory you selected
3. Verify the WSP file was saved in FlowJo after gating

### NumPy/Pandas Conflicts
If you see `numpy.core.multiarray failed to import`:
```bash
pip install --upgrade pandas numpy
```

### GUI Won't Launch
Ensure virtual environment is activated:
```bash
source venv/bin/activate
python -m flowkit_gui.main
```

---

## Running Tests

```bash
source venv/bin/activate
pytest           # Run all tests
pytest -v        # Verbose output
pytest tests/test_mfi_calculations.py -v  # Specific test file
```

---

## Project Structure

```
flowkit/
├── flowkit_gui/
│   ├── main.py                 # Application entry point
│   ├── models/
│   │   ├── workspace_model.py  # FlowKit WSP/FCS loading
│   │   ├── gate_tree_model.py  # Qt tree model with checkboxes
│   │   ├── keywords_model.py   # Keywords extraction
│   │   └── statistics_model.py # MFI calculation logic
│   ├── views/
│   │   └── main_window.py      # PyQt5 GUI
│   ├── exporters/
│   │   └── xlsx_exporter.py    # Multi-sheet Excel generation
│   ├── utils/
│   │   ├── mfi_calculations.py # Mean, median, geometric mean
│   │   ├── theme.py            # Theme, icons, QSS loading
│   │   └── logging_config.py   # Debug logging setup
│   └── resources/
│       ├── icons/              # Custom SVG icons
│       └── styles/             # flowkit_theme.qss stylesheet
├── tests/
├── pyproject.toml
├── CLAUDE.md                   # AI assistant instructions
└── README.md                   # This file
```

---

## Dependencies

- **FlowKit**: WSP parsing and FCS file handling
- **PyQt5**: Cross-platform GUI framework
- **openpyxl**: Excel file generation
- **pandas**: Data manipulation
- **numpy/scipy**: Numerical calculations

---

## License

MIT License
