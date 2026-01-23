"""
Main Window - Primary application window for FlowKit GUI.

This module provides the main application window with:
- Menu bar and toolbar
- Gate tree view (left panel)
- Sample/keywords panel (right panel)
- MFI selection controls
- Export functionality
"""

import sys
from pathlib import Path
from typing import Optional, List, Set

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeView, QTableView, QComboBox, QGroupBox, QCheckBox,
    QPushButton, QFileDialog, QMessageBox, QProgressDialog, QProgressBar,
    QStatusBar, QMenuBar, QAction, QToolBar, QLabel,
    QHeaderView, QAbstractItemView, QScrollArea, QGridLayout,
    QFrame, QRadioButton, QButtonGroup, QTabWidget, QListWidget,
    QListWidgetItem, QActionGroup, QDialog, QDialogButtonBox,
    QTextEdit, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon, QKeySequence, QColor

from ..models.workspace_model import WorkspaceModel, DataSource, CompensationMatrixInfo
from ..models.gate_tree_model import GateTreeModel, Gate
from ..models.keywords_model import KeywordsModel
from ..models.statistics_model import StatisticsModel, MFIMetric
from ..models.sample_selection_model import SampleSelectionModel
from ..models.gate_marker_matrix_model import GateMarkerMatrixModel
from .gate_marker_matrix_view import GateMarkerMatrixView
from .styled_tree_delegate import AccentedTreeItemDelegate
from .colored_gate_tree_delegate import ColoredGateTreeDelegate
from ..exporters.xlsx_exporter import XLSXExporter
from ..utils.logging_config import setup_logging, get_logger
from ..utils.theme import get_icon, cycle_theme, set_theme_mode, get_current_mode
from ..utils.theme_manager import ThemeMode, get_theme_manager
from ..utils.animations import AnimatedButton
from ..utils.fcs_discovery import (
    discover_fcs_files, get_fcs_file_list, ProcessingLevel, DiscoveryResult
)
from ..utils.cancellation import CancellationToken, CancellationError
from ..config import FCS_MAX_SEARCH_DEPTH

# Initialize logging
setup_logging()
logger = get_logger("main_window")


class FCSDirectoryDialog(QDialog):
    """
    Dialog for selecting FCS files with recursive discovery.

    Auto-scans the WSP parent directory and shows:
    - File count by processing level (Raw/Unmixed/Compensated)
    - Option to select processing level if multiple exist
    - Warnings about duplicate filenames
    """

    def __init__(self, wsp_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select FCS Files")
        self.setMinimumSize(500, 400)

        self._wsp_path = Path(wsp_path)
        self._search_dir: Path = self._wsp_path.parent
        self._discovery_result: Optional[DiscoveryResult] = None
        self._selected_level: Optional[ProcessingLevel] = None
        self._selected_files: List[str] = []

        self._init_ui()
        self._start_discovery()

    def _init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)

        # Info label with folder change button
        info_layout = QHBoxLayout()
        info_label = QLabel(
            "Searching for FCS files in the workspace directory and subdirectories..."
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label, 1)  # Stretch factor 1

        change_dir_btn = QPushButton()
        change_dir_btn.setIcon(get_icon("folder-sparkle"))
        change_dir_btn.setToolTip("Change search directory")
        change_dir_btn.setFixedSize(32, 32)
        change_dir_btn.clicked.connect(self._on_change_directory)
        info_layout.addWidget(change_dir_btn)

        layout.addLayout(info_layout)
        self._info_label = info_label
        self._change_dir_btn = change_dir_btn

        # Results group
        results_group = QGroupBox("Discovery Results")
        results_layout = QVBoxLayout(results_group)

        self._results_text = QTextEdit()
        self._results_text.setReadOnly(True)
        self._results_text.setMaximumHeight(150)
        results_layout.addWidget(self._results_text)

        layout.addWidget(results_group)

        # Processing level selection
        level_group = QGroupBox("Processing Level")
        level_layout = QVBoxLayout(level_group)

        self._level_btn_group = QButtonGroup(self)

        self._auto_radio = QRadioButton("Auto (prefer Unmixed > Compensated > Raw)")
        self._level_btn_group.addButton(self._auto_radio, 0)
        level_layout.addWidget(self._auto_radio)

        self._unmixed_radio = QRadioButton("Unmixed only")
        self._unmixed_radio.setChecked(True)  # Default to Unmixed
        self._level_btn_group.addButton(self._unmixed_radio, 1)
        level_layout.addWidget(self._unmixed_radio)

        self._raw_radio = QRadioButton("Raw only")
        self._level_btn_group.addButton(self._raw_radio, 2)
        level_layout.addWidget(self._raw_radio)

        self._all_radio = QRadioButton("All files (may include duplicates)")
        self._level_btn_group.addButton(self._all_radio, 3)
        level_layout.addWidget(self._all_radio)

        layout.addWidget(level_group)
        self._level_group = level_group

        # Info label when no unmixed files found
        self._no_unmixed_info = QLabel()
        self._no_unmixed_info.setWordWrap(True)
        self._no_unmixed_info.setStyleSheet(
            "color: #2563eb; font-weight: bold; padding: 8px; "
            "background-color: #dbeafe; border-radius: 4px;"
        )
        self._no_unmixed_info.setVisible(False)
        layout.addWidget(self._no_unmixed_info)

        # Warning label for duplicates
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #e67700; font-weight: bold;")
        self._warning_label.setVisible(False)
        layout.addWidget(self._warning_label)

        # Stretch to push buttons to bottom
        layout.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self._button_box = button_box

        # Initially disable OK until discovery completes
        self._button_box.button(QDialogButtonBox.Ok).setEnabled(False)

    def _on_change_directory(self):
        """Handle change directory button click."""
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Select FCS Files Directory",
            str(self._search_dir)
        )
        if new_dir:
            self._search_dir = Path(new_dir)
            self._start_discovery()

    def _start_discovery(self):
        """Start FCS file discovery."""
        self._info_label.setText(f"Searching in: {self._search_dir}")

        # Run discovery (this is fast enough to run synchronously for most directories)
        self._discovery_result = discover_fcs_files(
            self._search_dir,
            max_depth=FCS_MAX_SEARCH_DEPTH
        )

        self._update_ui_with_results()

    def _update_ui_with_results(self):
        """Update UI with discovery results."""
        result = self._discovery_result

        if result.total_count == 0:
            self._results_text.setText(
                "No FCS files found.\n\n"
                "You can click Cancel and manually select a directory containing FCS files."
            )
            self._level_group.setEnabled(False)
            return

        # Build results summary
        lines = [f"Found {result.total_count} FCS files:\n"]

        level_counts = {}
        for level in [ProcessingLevel.UNMIXED, ProcessingLevel.COMPENSATED,
                      ProcessingLevel.RAW, ProcessingLevel.UNKNOWN]:
            count = len(result.get_files_for_level(level))
            if count > 0:
                level_counts[level] = count
                lines.append(f"  • {level.value.title()}: {count} files")

        self._results_text.setText("\n".join(lines))

        # Enable/disable radio buttons based on what's available
        unmixed_available = ProcessingLevel.UNMIXED in level_counts
        self._unmixed_radio.setEnabled(unmixed_available)
        self._raw_radio.setEnabled(ProcessingLevel.RAW in level_counts)

        # Show info if no unmixed files (since Unmixed is default)
        if not unmixed_available:
            self._no_unmixed_info.setText(
                "ℹ️ No unmixed files found. Select another option or use Auto for best results."
            )
            self._no_unmixed_info.setVisible(True)
            # Fall back to Auto since default Unmixed is unavailable
            self._auto_radio.setChecked(True)
        else:
            self._no_unmixed_info.setVisible(False)

        # If only one level, select it automatically
        if len(level_counts) == 1:
            level = list(level_counts.keys())[0]
            if level == ProcessingLevel.UNMIXED:
                self._unmixed_radio.setChecked(True)
            elif level == ProcessingLevel.RAW:
                self._raw_radio.setChecked(True)

        # Show duplicate warning if needed
        if result.has_duplicates:
            dup_count = len(result.duplicate_filenames)
            self._warning_label.setText(
                f"⚠️ Warning: {dup_count} filename(s) appear in multiple locations. "
                f"Select a specific processing level to avoid conflicts."
            )
            self._warning_label.setVisible(True)

        # Enable OK button
        self._button_box.button(QDialogButtonBox.Ok).setEnabled(True)

        # Update info label
        self._info_label.setText(
            f"Searched: {result.root_dir}\n"
            f"Depth: {result.max_depth_searched} levels"
        )

    def _on_accept(self):
        """Handle OK button click."""
        result = self._discovery_result
        if not result or result.total_count == 0:
            self.reject()
            return

        # Determine which files to use based on selection
        checked_id = self._level_btn_group.checkedId()

        if checked_id == 0:  # Auto
            self._selected_files = get_fcs_file_list(result)
            # Use preferred level logic
            preferred = result.get_preferred_files()
            if preferred:
                self._selected_files = [str(f) for f in preferred]
                logger.info(f"Auto-selected {len(self._selected_files)} files from preferred level")
        elif checked_id == 1:  # Unmixed
            self._selected_files = get_fcs_file_list(result, ProcessingLevel.UNMIXED)
            self._selected_level = ProcessingLevel.UNMIXED
        elif checked_id == 2:  # Raw
            self._selected_files = get_fcs_file_list(result, ProcessingLevel.RAW)
            self._selected_level = ProcessingLevel.RAW
        elif checked_id == 3:  # All
            self._selected_files = get_fcs_file_list(result)

        logger.info(f"Selected {len(self._selected_files)} FCS files")
        self.accept()

    def get_selected_files(self) -> List[str]:
        """Return the list of selected FCS file paths."""
        return self._selected_files

    def get_discovery_result(self) -> Optional[DiscoveryResult]:
        """Return the full discovery result."""
        return self._discovery_result


class WorkspaceLoaderWorker(QThread):
    """Background worker for loading workspace and analyzing samples."""

    progress = pyqtSignal(str)  # Status message
    finished = pyqtSignal(bool, str)  # success, error_message
    result = pyqtSignal(int, int)  # num_samples, num_gates

    def __init__(
        self,
        workspace_model: "WorkspaceModel",
        wsp_path: str,
        fcs_dir: Optional[str] = None,
        fcs_files: Optional[List[str]] = None
    ):
        super().__init__()
        self._workspace_model = workspace_model
        self._wsp_path = wsp_path
        self._fcs_dir = fcs_dir
        self._fcs_files = fcs_files

    def run(self):
        """Execute workspace loading in background thread."""
        try:
            self.progress.emit("Loading workspace...")
            num_samples, num_gates = self._workspace_model.load_workspace(
                self._wsp_path,
                fcs_dir=self._fcs_dir,
                fcs_files=self._fcs_files,
                ignore_missing=True
            )

            # Note: analyze_samples() is now deferred to export time
            # to reduce memory usage with large datasets (70+ samples)
            self.progress.emit("Workspace loaded successfully")

            self.result.emit(num_samples, num_gates)
            self.finished.emit(True, "")

        except Exception as e:
            logger.error(f"Failed to load workspace: {type(e).__name__}: {e}")
            self.finished.emit(False, str(e))


class LoadingDialog(QDialog):
    """Modal dialog showing loading progress with animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Loading...")
        self.setModal(True)
        self.setFixedSize(350, 120)
        # Remove close button to prevent user from closing during operation
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Status label
        self._status_label = QLabel("Initializing...")
        self._status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status_label)

        # Progress bar (indeterminate mode)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Indeterminate mode
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

    def set_status(self, message: str):
        """Update the status message."""
        self._status_label.setText(message)


class MainWindow(QMainWindow):
    """Main application window for FlowKit GUI."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("FlowKit Analysis - Flow Cytometry Data Export")
        self.setMinimumSize(1200, 800)

        # Models
        self._workspace_model = WorkspaceModel()
        self._gate_tree_model = GateTreeModel()
        self._keywords_model = KeywordsModel()
        self._sample_selection_model = SampleSelectionModel()
        self._gate_marker_matrix_model = GateMarkerMatrixModel()

        # UI state
        self._selected_markers: List[str] = []
        self._marker_checkboxes: dict = {}
        self._use_full_gate_names: bool = True  # Shared state for full/short name toggle
        self._available_gate_ids: Set[str] = set()  # Gates available for selected samples

        # Initialize UI
        self._init_menu()
        self._init_toolbar()
        self._init_central_widget()
        self._init_statusbar()

        # Initial state
        self._update_ui_state()

    def _init_menu(self):
        """Initialize menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        open_action = QAction("&Open WSP...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_wsp)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        export_action = QAction("&Export to XLSX...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        # Theme submenu
        theme_menu = view_menu.addMenu("&Theme")

        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)

        self._theme_system_action = QAction("&System", self)
        self._theme_system_action.setCheckable(True)
        self._theme_system_action.triggered.connect(lambda: self._on_theme_changed(ThemeMode.SYSTEM))
        self._theme_action_group.addAction(self._theme_system_action)
        theme_menu.addAction(self._theme_system_action)

        self._theme_light_action = QAction("&Light", self)
        self._theme_light_action.setCheckable(True)
        self._theme_light_action.triggered.connect(lambda: self._on_theme_changed(ThemeMode.LIGHT))
        self._theme_action_group.addAction(self._theme_light_action)
        theme_menu.addAction(self._theme_light_action)

        self._theme_dark_action = QAction("&Dark", self)
        self._theme_dark_action.setCheckable(True)
        self._theme_dark_action.triggered.connect(lambda: self._on_theme_changed(ThemeMode.DARK))
        self._theme_action_group.addAction(self._theme_dark_action)
        theme_menu.addAction(self._theme_dark_action)

        # Set the correct checked state based on current mode
        self._update_theme_menu_state()

        view_menu.addSeparator()

        # Cycle theme shortcut
        cycle_theme_action = QAction("Cycle &Theme", self)
        cycle_theme_action.setShortcut("Ctrl+Shift+T")
        cycle_theme_action.triggered.connect(self._on_cycle_theme)
        view_menu.addAction(cycle_theme_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _init_toolbar(self):
        """Initialize toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_btn = QPushButton("  Open WSP")
        open_btn.setIcon(get_icon("folder-sparkle"))
        open_btn.clicked.connect(self._on_open_wsp)
        toolbar.addWidget(open_btn)

        toolbar.addSeparator()

        self._export_btn = AnimatedButton("  Export to XLSX", primary=True)
        self._export_btn.setIcon(get_icon("export-heart"))
        self._export_btn.setObjectName("exportButton")
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        toolbar.addWidget(self._export_btn)

    def _init_central_widget(self):
        """Initialize central widget with panels."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # Main splitter (horizontal)
        splitter = QSplitter(Qt.Horizontal)

        # Left panel - Gate tree
        left_panel = self._create_gate_panel()
        splitter.addWidget(left_panel)

        # Right panel - Sample info and options
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        splitter.setSizes([450, 750])

        main_layout.addWidget(splitter)

        # Bottom panel - Export button and options
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        # Checkbox for including _All sheets
        self._include_all_sheets_checkbox = QCheckBox("Include _All sheets")
        self._include_all_sheets_checkbox.setChecked(False)
        self._include_all_sheets_checkbox.setToolTip(
            "Include Counts_All, Frequencies_All, MFI_All, and Concatenated_All sheets"
        )
        bottom_layout.addWidget(self._include_all_sheets_checkbox)

        self._main_export_btn = AnimatedButton("  Export to XLSX", primary=True)
        self._main_export_btn.setIcon(get_icon("sparkles-arrow"))
        self._main_export_btn.setObjectName("mainExportButton")
        self._main_export_btn.setMinimumWidth(200)
        self._main_export_btn.setMinimumHeight(40)
        self._main_export_btn.clicked.connect(self._on_export)
        self._main_export_btn.setEnabled(False)
        bottom_layout.addWidget(self._main_export_btn)

        bottom_layout.addStretch()
        main_layout.addLayout(bottom_layout)

    def _create_gate_panel(self) -> QWidget:
        """Create the gate tree panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Header
        header = QLabel("Gating Hierarchy")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        # Tree view
        self._gate_tree_view = QTreeView()
        self._gate_tree_view.setModel(self._gate_tree_model)
        self._gate_tree_view.setAlternatingRowColors(True)
        self._gate_tree_view.setAnimated(True)
        self._gate_tree_view.setMouseTracking(True)
        self._gate_tree_view.header().setStretchLastSection(True)

        # Configure column widths for 4 columns:
        # Column 0: Gate name (stretch to fill)
        # Column 1: Reference checkbox (narrow)
        # Column 2: Events count
        # Column 3: % Parent
        self._gate_tree_view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._gate_tree_view.setColumnWidth(1, 28)   # Reference checkbox (narrow)
        self._gate_tree_view.setColumnWidth(2, 80)   # Events count
        self._gate_tree_view.setColumnWidth(3, 80)   # % Parent

        # Connect itemChanged signal to sync reference gates when user clicks checkboxes
        self._gate_tree_model.itemChanged.connect(self._on_gate_item_changed)

        # Apply custom delegate for colored depth dots and selection accent
        self._gate_tree_delegate = ColoredGateTreeDelegate(self._gate_tree_view)
        self._gate_tree_view.setItemDelegate(self._gate_tree_delegate)

        layout.addWidget(self._gate_tree_view)

        # Select all/none buttons
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("  Select All")
        select_all_btn.setIcon(get_icon("check-star"))
        select_all_btn.clicked.connect(self._on_select_all_gates)
        btn_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("  Deselect All")
        deselect_all_btn.setIcon(get_icon("x-swoop"))
        deselect_all_btn.clicked.connect(self._on_deselect_all_gates)
        btn_layout.addWidget(deselect_all_btn)

        btn_layout.addStretch()

        # Name toggle button (Full Names / Short Names)
        self._gate_name_toggle_btn = QPushButton("Full Names")
        self._gate_name_toggle_btn.setCheckable(True)
        self._gate_name_toggle_btn.setChecked(True)
        self._gate_name_toggle_btn.setToolTip("Toggle between full names (with parent prefix for duplicates) and short names")
        self._gate_name_toggle_btn.clicked.connect(self._on_name_toggle_changed)
        btn_layout.addWidget(self._gate_name_toggle_btn)

        layout.addLayout(btn_layout)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Create the right panel with tabbed interface."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setObjectName("mainTabWidget")

        # Tab 1: Sample & Keywords
        self._tab_widget.addTab(
            self._create_sample_keywords_tab(),
            get_icon("sample"),
            "Sample"
        )

        # Tab 2: Keywords (for export selection)
        self._tab_widget.addTab(
            self._create_keywords_export_tab(),
            get_icon("sample"),  # Reuse sample icon
            "Keywords"
        )

        # Tab 3: MFI / Statistics
        self._tab_widget.addTab(
            self._create_markers_tab(),
            get_icon("markers"),
            "MFI / Statistics"
        )

        # Tab 4: Settings
        self._tab_widget.addTab(
            self._create_settings_tab(),
            get_icon("settings"),
            "Settings"
        )

        layout.addWidget(self._tab_widget)
        return panel

    def _create_sample_keywords_tab(self) -> QWidget:
        """Create the Sample & Keywords tab content with sample selection."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Horizontal splitter for sample selection and keywords
        splitter = QSplitter(Qt.Horizontal)

        # Left side: Sample Selection Tree
        sample_selection_widget = QWidget()
        sample_selection_layout = QVBoxLayout(sample_selection_widget)
        sample_selection_layout.setContentsMargins(0, 0, 0, 0)

        # Sample selection header with count
        self._sample_selection_header = QLabel("Sample Selection")
        self._sample_selection_header.setObjectName("headerLabel")
        sample_selection_layout.addWidget(self._sample_selection_header)

        # Sample selection tree
        self._sample_selection_tree = QTreeView()
        self._sample_selection_tree.setModel(self._sample_selection_model)
        self._sample_selection_tree.setAlternatingRowColors(True)
        self._sample_selection_tree.setAnimated(True)
        self._sample_selection_tree.setMouseTracking(True)
        self._sample_selection_tree.header().setStretchLastSection(True)
        self._sample_selection_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._sample_selection_tree.clicked.connect(self._on_sample_tree_clicked)

        # Apply custom delegate for selection accent bar
        self._sample_tree_delegate = AccentedTreeItemDelegate(self._sample_selection_tree)
        self._sample_selection_tree.setItemDelegate(self._sample_tree_delegate)

        sample_selection_layout.addWidget(self._sample_selection_tree)

        # Sample selection buttons
        sample_btn_layout = QHBoxLayout()
        select_all_samples_btn = QPushButton("  Select All")
        select_all_samples_btn.setIcon(get_icon("check-star"))
        select_all_samples_btn.clicked.connect(self._on_select_all_samples)
        sample_btn_layout.addWidget(select_all_samples_btn)

        deselect_all_samples_btn = QPushButton("  Deselect All")
        deselect_all_samples_btn.setIcon(get_icon("x-swoop"))
        deselect_all_samples_btn.clicked.connect(self._on_deselect_all_samples)
        sample_btn_layout.addWidget(deselect_all_samples_btn)

        invert_samples_btn = QPushButton("  Invert")
        invert_samples_btn.clicked.connect(self._on_invert_samples)
        sample_btn_layout.addWidget(invert_samples_btn)

        sample_selection_layout.addLayout(sample_btn_layout)

        # Expand/collapse buttons row
        expand_btn_layout = QHBoxLayout()

        expand_all_btn = QPushButton("  Expand All")
        expand_all_btn.setIcon(get_icon("chevron-down"))
        expand_all_btn.setToolTip("Expand all groups")
        expand_all_btn.clicked.connect(self._sample_selection_tree.expandAll)
        expand_btn_layout.addWidget(expand_all_btn)

        collapse_all_btn = QPushButton("  Collapse All")
        collapse_all_btn.setIcon(get_icon("chevron-right"))
        collapse_all_btn.setToolTip("Collapse all groups")
        collapse_all_btn.clicked.connect(self._sample_selection_tree.collapseAll)
        expand_btn_layout.addWidget(collapse_all_btn)

        expand_btn_layout.addStretch()
        sample_selection_layout.addLayout(expand_btn_layout)

        # Compensation status warning banner (hidden by default)
        self._comp_warning_banner = QLabel()
        self._comp_warning_banner.setWordWrap(True)
        self._comp_warning_banner.setStyleSheet(
            "background-color: #fef3c7; color: #92400e; padding: 8px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self._comp_warning_banner.setVisible(False)
        sample_selection_layout.addWidget(self._comp_warning_banner)

        # Collapsible compensation details panel
        self._comp_details_widget = QWidget()
        comp_details_layout = QVBoxLayout(self._comp_details_widget)
        comp_details_layout.setContentsMargins(0, 4, 0, 0)
        comp_details_layout.setSpacing(4)

        # Header with toggle button
        comp_header_layout = QHBoxLayout()
        comp_header_layout.setContentsMargins(0, 0, 0, 0)
        self._comp_details_toggle = QPushButton("▶ Compensation Details")
        self._comp_details_toggle.setStyleSheet(
            "QPushButton { text-align: left; border: none; padding: 4px; "
            "font-weight: bold; color: #666; } "
            "QPushButton:hover { color: #333; background-color: #f0f0f0; }"
        )
        self._comp_details_toggle.setCheckable(True)
        self._comp_details_toggle.clicked.connect(self._toggle_comp_details)
        comp_header_layout.addWidget(self._comp_details_toggle)
        comp_header_layout.addStretch()
        comp_details_layout.addLayout(comp_header_layout)

        # Content area (hidden by default)
        self._comp_details_content = QWidget()
        content_layout = QVBoxLayout(self._comp_details_content)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(4)

        # Matrix legend label
        self._comp_matrix_legend = QLabel("No compensation matrices loaded")
        self._comp_matrix_legend.setWordWrap(True)
        self._comp_matrix_legend.setStyleSheet("font-size: 11px;")
        content_layout.addWidget(self._comp_matrix_legend)

        # Expandable matrix details (for viewing spillover values)
        self._comp_matrix_details_btn = QPushButton("Show Matrix Values...")
        self._comp_matrix_details_btn.setStyleSheet("font-size: 11px;")
        self._comp_matrix_details_btn.clicked.connect(self._show_compensation_matrix_dialog)
        self._comp_matrix_details_btn.setVisible(False)
        content_layout.addWidget(self._comp_matrix_details_btn)

        self._comp_details_content.setVisible(False)
        comp_details_layout.addWidget(self._comp_details_content)

        self._comp_details_widget.setVisible(False)  # Hidden until workspace loaded
        sample_selection_layout.addWidget(self._comp_details_widget)

        splitter.addWidget(sample_selection_widget)

        # Right side: Sample preview and keywords
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        # Sample selector for preview (kept for viewing individual sample keywords)
        sample_group = QGroupBox("Sample Preview")
        sample_layout = QVBoxLayout(sample_group)

        self._sample_combo = QComboBox()
        self._sample_combo.currentIndexChanged.connect(self._on_sample_changed)
        sample_layout.addWidget(self._sample_combo)

        preview_layout.addWidget(sample_group)

        # Keywords table - expands to fill available space
        keywords_group = QGroupBox("Keywords")
        keywords_layout = QVBoxLayout(keywords_group)

        self._keywords_table = QTableView()
        self._keywords_table.setAlternatingRowColors(True)
        self._keywords_model_view = QStandardItemModel()
        self._keywords_model_view.setHorizontalHeaderLabels(["Keyword", "Value"])
        self._keywords_table.setModel(self._keywords_model_view)
        self._keywords_table.horizontalHeader().setStretchLastSection(True)
        keywords_layout.addWidget(self._keywords_table)

        preview_layout.addWidget(keywords_group, 1)

        splitter.addWidget(preview_widget)

        # Set splitter proportions
        splitter.setSizes([400, 400])

        layout.addWidget(splitter)

        return tab

    def _create_markers_tab(self) -> QWidget:
        """Create the MFI/Statistics tab content with Gate×Marker matrix."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Explanatory text at the top
        help_label = QLabel(
            "Select gate/marker combinations for MFI calculation. "
            "Each checkbox represents calculating that marker's MFI for events in that gate. "
            "Click row headers (gate names) or column headers (marker names) to select entire rows/columns."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(help_label)

        # Gate × Marker matrix view
        self._gate_marker_matrix_view = GateMarkerMatrixView()
        self._gate_marker_matrix_view.set_model(self._gate_marker_matrix_model)
        layout.addWidget(self._gate_marker_matrix_view, 1)  # Stretch factor 1 to expand

        # Connect MFI matrix's name toggle to shared handler
        self._gate_marker_matrix_view._disambiguate_btn.clicked.disconnect()
        self._gate_marker_matrix_view._disambiguate_btn.clicked.connect(self._on_mfi_name_toggle_changed)

        # MFI metrics selection - fixed at bottom
        mfi_group = QGroupBox("Statistics to Calculate (select at least one)")
        mfi_layout = QHBoxLayout(mfi_group)

        self._mean_check = QCheckBox("Mean")
        self._mean_check.setChecked(True)
        mfi_layout.addWidget(self._mean_check)

        self._median_check = QCheckBox("Median")
        self._median_check.setChecked(True)
        mfi_layout.addWidget(self._median_check)

        self._geomean_check = QCheckBox("Geometric Mean")
        mfi_layout.addWidget(self._geomean_check)

        mfi_layout.addStretch()
        layout.addWidget(mfi_group)

        # Keep legacy marker checkboxes hidden for backward compatibility
        # (used by _get_selected_markers if matrix is empty)
        self._marker_widget = QWidget()
        self._marker_widget.setVisible(False)
        self._marker_grid = QGridLayout(self._marker_widget)

        return tab

    def _create_keywords_export_tab(self) -> QWidget:
        """Create the Keywords export selection tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Explanatory text at the top
        help_label = QLabel(
            "Select which custom keywords to include in the exported Excel file. "
            "Selected keywords will appear in Keywords, Keywords_Wide, and Frequencies sheets."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(help_label)

        # Keyword selection group
        keyword_group = QGroupBox("Keywords for Export")
        keyword_layout = QVBoxLayout(keyword_group)

        self._keyword_selection_list = QListWidget()
        self._keyword_selection_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._keyword_selection_list.setToolTip(
            "Select keywords to include in the exported Excel file.\n"
            "Only selected keywords will appear in Keywords and Frequencies sheets."
        )
        keyword_layout.addWidget(self._keyword_selection_list, 1)  # Stretch factor

        # Select All / Clear All buttons
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("  Select All")
        select_all_btn.setIcon(get_icon("check-star"))
        select_all_btn.clicked.connect(self._on_select_all_export_keywords)
        btn_layout.addWidget(select_all_btn)

        clear_all_btn = QPushButton("  Clear All")
        clear_all_btn.setIcon(get_icon("x-swoop"))
        clear_all_btn.clicked.connect(self._on_clear_all_export_keywords)
        btn_layout.addWidget(clear_all_btn)

        keyword_layout.addLayout(btn_layout)
        layout.addWidget(keyword_group, 1)  # Stretch factor to expand

        return tab

    def _create_settings_tab(self) -> QWidget:
        """Create the Settings tab content."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Data source selection (compensation)
        data_source_group = QGroupBox("Data Source (Compensation)")
        data_source_layout = QVBoxLayout(data_source_group)

        self._data_source_btn_group = QButtonGroup(self)

        self._auto_radio = QRadioButton("Auto (compensated with raw fallback)")
        self._auto_radio.setChecked(True)
        self._auto_radio.setToolTip("Attempts to use compensated data; falls back to raw if unavailable")
        self._data_source_btn_group.addButton(self._auto_radio, 0)
        data_source_layout.addWidget(self._auto_radio)

        self._raw_radio = QRadioButton("Force Raw (uncompensated)")
        self._raw_radio.setToolTip("Always use raw, uncompensated event data")
        self._data_source_btn_group.addButton(self._raw_radio, 1)
        data_source_layout.addWidget(self._raw_radio)

        self._comp_radio = QRadioButton("Force Compensated")
        self._comp_radio.setToolTip("Require compensated data; will fail if unavailable")
        self._data_source_btn_group.addButton(self._comp_radio, 2)
        data_source_layout.addWidget(self._comp_radio)

        # Compensation matrix dropdown (hidden until needed)
        comp_matrix_layout = QHBoxLayout()
        self._comp_matrix_label = QLabel("Matrix:")
        self._comp_matrix_label.setVisible(False)
        comp_matrix_layout.addWidget(self._comp_matrix_label)

        self._comp_matrix_combo = QComboBox()
        self._comp_matrix_combo.setVisible(False)
        self._comp_matrix_combo.setToolTip("Select compensation matrix to use")
        comp_matrix_layout.addWidget(self._comp_matrix_combo)
        comp_matrix_layout.addStretch()

        data_source_layout.addLayout(comp_matrix_layout)
        layout.addWidget(data_source_group)

        # Normalization Reference Settings
        norm_group = QGroupBox("Normalization Reference")
        norm_layout = QHBoxLayout(norm_group)

        norm_layout.addWidget(QLabel("Descendant depth:"))

        self._descendant_depth_combo = QComboBox()
        self._descendant_depth_combo.addItems(["Unlimited", "1 level", "2 levels", "3 levels"])
        self._descendant_depth_combo.setCurrentIndex(0)  # Default: Unlimited
        self._descendant_depth_combo.setToolTip(
            "How many levels below reference gates to include in normalized frequencies"
        )
        norm_layout.addWidget(self._descendant_depth_combo)

        norm_layout.addStretch()
        layout.addWidget(norm_group)

        # Export options
        export_group = QGroupBox("Export Options")
        export_layout = QVBoxLayout(export_group)

        self._wide_keywords_check = QCheckBox("Include Keywords_Wide sheet (pivot format)")
        self._wide_keywords_check.setChecked(True)  # Default to enabled
        self._wide_keywords_check.setToolTip(
            "Generates a wide-format keywords sheet with one row per sample.\n"
            "sample_name is always the first column as the primary identifier.\n"
            "Additional index columns can be selected below."
        )
        self._wide_keywords_check.stateChanged.connect(self._on_wide_keywords_toggled)
        export_layout.addWidget(self._wide_keywords_check)

        # Keyword index selection (for Keywords_Wide sheet)
        self._index_columns_label = QLabel("Additional index columns for Keywords_Wide:")
        self._index_columns_label.setEnabled(True)  # Enabled by default since checkbox is checked
        export_layout.addWidget(self._index_columns_label)

        self._index_columns_list = QListWidget()
        self._index_columns_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._index_columns_list.setMaximumHeight(100)
        self._index_columns_list.setEnabled(True)  # Enabled by default since checkbox is checked
        self._index_columns_list.setToolTip(
            "Select additional keywords to use as index columns.\n"
            "sample_name is always first; these appear after it."
        )
        export_layout.addWidget(self._index_columns_list)

        self._tidy_frequencies_check = QCheckBox("Include tidy sheets (long format)")
        self._tidy_frequencies_check.setToolTip(
            "Adds tidy (long-format) sheets for counts and frequencies:\n"
            "Counts_All_Tidy, Counts_Selected_Tidy,\n"
            "Frequencies_All_Tidy, Frequencies_Selected_Tidy\n"
            "(useful for analysis in R/Python)"
        )
        export_layout.addWidget(self._tidy_frequencies_check)

        layout.addWidget(export_group)

        # Push content to top
        layout.addStretch()

        return tab

    def _init_statusbar(self):
        """Initialize status bar."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Ready - Open a WSP file to begin")

        # Add theme indicator to right side of status bar
        self._theme_indicator = QLabel()
        self._theme_indicator.setObjectName("themeIndicator")
        self._statusbar.addPermanentWidget(self._theme_indicator)
        self._update_theme_indicator()

    def _update_ui_state(self):
        """Update UI enabled states based on loaded data."""
        is_loaded = self._workspace_model.is_loaded

        self._export_btn.setEnabled(is_loaded)
        self._main_export_btn.setEnabled(is_loaded)

        if is_loaded:
            self._statusbar.showMessage(
                f"Loaded: {len(self._workspace_model.samples)} samples, "
                f"{len(self._workspace_model.gates)} gates"
            )

    def _on_open_wsp(self):
        """Handle Open WSP action."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open FlowJo Workspace",
            "",
            "FlowJo Workspace (*.wsp);;All Files (*)"
        )

        if not file_path:
            return

        # Show FCS discovery dialog
        fcs_files = None
        fcs_dir = None

        discovery_dialog = FCSDirectoryDialog(file_path, self)
        if discovery_dialog.exec_() == QDialog.Accepted:
            fcs_files = discovery_dialog.get_selected_files()
            if fcs_files:
                logger.info(f"Using {len(fcs_files)} discovered FCS files")
            else:
                # Discovery found nothing, fall back to manual selection
                fcs_files = None

        # If no files from discovery, ask for directory manually
        if not fcs_files:
            fcs_dir = QFileDialog.getExistingDirectory(
                self,
                "Select FCS Files Directory (Cancel to use WSP directory)",
                str(Path(file_path).parent)
            )
            if not fcs_dir:
                fcs_dir = str(Path(file_path).parent)
            logger.info(f"Using manual FCS directory: {fcs_dir}")

        logger.info(f"Loading workspace: {file_path}")

        # Create and show loading dialog
        self._loading_dialog = LoadingDialog(self)

        # Create worker thread
        self._loader_worker = WorkspaceLoaderWorker(
            self._workspace_model,
            file_path,
            fcs_dir=fcs_dir,
            fcs_files=fcs_files
        )

        # Connect signals
        self._loader_worker.progress.connect(self._on_loading_progress)
        self._loader_worker.result.connect(self._on_loading_result)
        self._loader_worker.finished.connect(self._on_loading_finished)

        # Store values for later
        self._pending_num_samples = 0
        self._pending_num_gates = 0

        # Start loading
        self._loader_worker.start()
        self._loading_dialog.exec_()  # Modal, blocks until closed

    def _on_loading_progress(self, message: str):
        """Handle progress update from worker."""
        self._loading_dialog.set_status(message)
        self._statusbar.showMessage(message)

    def _on_loading_result(self, num_samples: int, num_gates: int):
        """Handle successful workspace load result."""
        self._pending_num_samples = num_samples
        self._pending_num_gates = num_gates

    def _on_loading_finished(self, success: bool, error_msg: str):
        """Handle loading completion (success or failure)."""
        self._loading_dialog.accept()  # Close the loading dialog

        if success:
            self._finalize_workspace_load()
        else:
            QMessageBox.critical(
                self,
                "Error Loading Workspace",
                f"Failed to load workspace:\n{error_msg}"
            )
            self._statusbar.showMessage("Error loading workspace")

    def _finalize_workspace_load(self):
        """Finalize UI after successful workspace load."""
        num_samples = self._pending_num_samples
        num_gates = self._pending_num_gates

        # Update keywords model
        self._keywords_model.set_samples(self._workspace_model.samples)

        # Scan compensation status with progress dialog
        self._statusbar.showMessage("Scanning compensation status...")
        num_samples_total = len(self._workspace_model.samples)

        # Create progress dialog with minimum duration so it only shows if slow
        progress = QProgressDialog(
            "Scanning compensation status...",
            None,  # No cancel button for this operation
            0,
            num_samples_total,
            self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)  # Only show if takes > 500ms
        progress.setWindowTitle("Scanning Compensation")

        def update_progress(current, total):
            progress.setValue(current)
            QApplication.processEvents()

        # Use WSP-based compensation scanning for accurate status with colors
        comp_status = self._workspace_model.scan_compensation_status_from_wsp(
            progress_callback=update_progress
        )
        progress.close()

        # Get compensation assignments with colors for UI display
        comp_assignments = self._workspace_model.compensation_assignments

        # Get sample groups
        groups = self._workspace_model.get_sample_groups()

        # Populate sample selection model with compensation info
        self._sample_selection_model.populate_from_groups(
            groups=groups,
            all_samples=self._workspace_model.samples,
            compensation_status=comp_status,
            compensation_assignments=comp_assignments,
            default_selected=True
        )
        self._sample_selection_tree.expandAll()
        self._update_sample_selection_header()
        self._update_comp_details_panel()

        # Connect sample selection changes to gate availability filtering
        self._sample_selection_model.selectionChanged.connect(self._on_sample_selection_for_gates)

        # Populate UI
        self._populate_gate_tree()

        # Initialize available gates (all gates available when all samples selected)
        self._available_gate_ids = {g.gate_id for g in self._workspace_model.gates}
        self._populate_sample_combo()
        self._populate_marker_checkboxes()
        self._populate_index_columns_list()
        self._populate_keyword_selection()

        # Populate gate×marker matrix
        self._populate_gate_marker_matrix()

        # Trigger initial statistics update for first sample
        if self._sample_combo.count() > 0:
            self._on_sample_changed(0)

        # Populate compensation matrix dropdown if multiple available
        self._populate_compensation_matrices()

        self._update_ui_state()

        # Get FCS data status
        samples_with_data = self._workspace_model.get_samples_with_data()
        samples_without_data = self._workspace_model.get_samples_without_data()

        # Build info message
        msg = (
            f"Successfully loaded workspace:\n"
            f"- {num_samples} samples\n"
            f"- {num_gates} gates\n"
            f"- {len(self._workspace_model.channels)} channels\n\n"
            f"FCS Data Status:\n"
            f"- {len(samples_with_data)} samples have FCS data\n"
            f"- {len(samples_without_data)} samples missing FCS data"
        )

        # Warn if many samples missing data
        if len(samples_without_data) > 0:
            logger.warning(f"{len(samples_without_data)} samples are missing FCS data")
            msg += "\n\nNote: Samples without FCS data will show zero measurements."

        self._statusbar.showMessage("Workspace loaded successfully")

        QMessageBox.information(
            self,
            "Workspace Loaded",
            msg
        )

    def _populate_gate_tree(self):
        """Populate the gate tree view from workspace."""
        gates = []
        for gate_info in self._workspace_model.gates:
            gate = Gate(
                gate_id=gate_info.gate_id,
                name=gate_info.name,
                path=gate_info.path,
                gate_type=gate_info.gate_type,
                parameters=gate_info.parameters,
                is_selected=True
            )
            gates.append(gate)

        # Build hierarchy (simplified - just flat list for now)
        self._gate_tree_model.populate_from_hierarchy(gates)
        self._gate_tree_view.expandAll()

    def _populate_sample_combo(self):
        """Populate sample dropdown."""
        self._sample_combo.clear()

        for sample in self._workspace_model.samples:
            self._sample_combo.addItem(sample.name, sample.sample_id)

    def _populate_marker_checkboxes(self):
        """Populate marker selection checkboxes with reagent names (legacy, kept for compatibility)."""
        # Clear existing
        for cb in self._marker_checkboxes.values():
            cb.deleteLater()
        self._marker_checkboxes.clear()

        # Add checkboxes for each channel with reagent names
        channel_info_list = self._workspace_model.channel_info
        cols = 4

        for i, ch_info in enumerate(channel_info_list):
            cb = QCheckBox(ch_info.display_name)
            cb.setToolTip(f"Channel: {ch_info.pnn_label}")
            self._marker_checkboxes[ch_info.pnn_label] = cb  # Key remains pnn_label
            row = i // cols
            col = i % cols
            self._marker_grid.addWidget(cb, row, col)

    def _populate_gate_marker_matrix(self):
        """Populate the gate×marker matrix with gates and channels."""
        gates = self._workspace_model.gates
        markers = self._workspace_model.channel_info

        self._gate_marker_matrix_model.set_gates_and_markers(gates, markers)

    def _populate_compensation_matrices(self):
        """Populate compensation matrix dropdown if multiple available."""
        self._comp_matrix_combo.clear()

        matrices = self._workspace_model.get_compensation_matrices()
        logger.debug(f"Available compensation matrices: {matrices}")

        if len(matrices) > 1:
            # Show dropdown if multiple matrices available
            self._comp_matrix_label.setVisible(True)
            self._comp_matrix_combo.setVisible(True)
            for matrix_name in matrices:
                self._comp_matrix_combo.addItem(matrix_name)
        else:
            # Hide dropdown if only one or no matrices
            self._comp_matrix_label.setVisible(False)
            self._comp_matrix_combo.setVisible(False)

    def _on_sample_changed(self, index: int):
        """Handle sample selection change."""
        if index < 0:
            return

        sample_id = self._sample_combo.currentData()
        if not sample_id:
            return

        # Update keywords table
        keywords = self._keywords_model.get_keywords_for_sample(sample_id)

        self._keywords_model_view.clear()
        self._keywords_model_view.setHorizontalHeaderLabels(["Keyword", "Value"])

        for kw_name, kw_value in keywords.items():
            name_item = QStandardItem(kw_name)
            name_item.setEditable(False)
            value_item = QStandardItem(str(kw_value) if kw_value else "")
            value_item.setEditable(False)
            self._keywords_model_view.appendRow([name_item, value_item])

        # Update gate statistics for this sample
        self._update_gate_statistics(sample_id)

    def _update_gate_statistics(self, sample_id: str):
        """Update gate tree with statistics for the selected sample."""
        for gate_info in self._workspace_model.gates:
            stats = self._workspace_model.get_gate_statistics(sample_id, gate_info.gate_id)
            self._gate_tree_model.update_gate_statistics(
                gate_info.gate_id,
                stats.get('count', 0),
                stats.get('percent_parent', 0.0)
            )

    def _on_select_all_gates(self):
        """Select all gates."""
        self._gate_tree_model.select_all()
        self._update_mfi_matrix_filter()

    def _on_deselect_all_gates(self):
        """Deselect all gates."""
        self._gate_tree_model.deselect_all()
        self._update_mfi_matrix_filter()

    def _on_name_toggle_changed(self, checked: bool) -> None:
        """Handle name toggle change from gate tree panel - sync to MFI matrix."""
        self._use_full_gate_names = checked

        # Update button text
        btn_text = "Full Names" if checked else "Short Names"
        self._gate_name_toggle_btn.setText(btn_text)

        # Update gate tree model display names
        self._gate_tree_model.set_display_mode(use_full_names=checked)

        # Update MFI matrix model (sync toggle button state)
        if hasattr(self, '_gate_marker_matrix_view'):
            self._gate_marker_matrix_view._disambiguate_btn.setChecked(checked)
            self._gate_marker_matrix_model.set_disambiguate_enabled(checked)

    def _on_mfi_name_toggle_changed(self, checked: bool) -> None:
        """Handle name toggle change from MFI matrix panel - sync to gate tree."""
        self._use_full_gate_names = checked

        # Sync gate tree toggle button
        self._gate_name_toggle_btn.setChecked(checked)
        btn_text = "Full Names" if checked else "Short Names"
        self._gate_name_toggle_btn.setText(btn_text)

        # Update both models
        self._gate_tree_model.set_display_mode(use_full_names=checked)
        self._gate_marker_matrix_model.set_disambiguate_enabled(checked)

    def _on_gate_item_changed(self, item):
        """Handle changes to gate tree items, including reference checkboxes.

        This slot is connected to the model's itemChanged signal to sync
        the reference gates set when users click the reference checkbox column,
        and to update MFI matrix filtering when gate selection changes.
        """
        from PyQt5.QtCore import Qt

        if item.column() == self._gate_tree_model.COLUMN_REFERENCE:
            # Handle reference column changes
            gate_id = item.data(Qt.UserRole)
            if gate_id:
                is_reference = item.checkState() == Qt.Checked
                self._gate_tree_model.set_reference_gate(gate_id, is_reference)

        elif item.column() == self._gate_tree_model.COLUMN_GATE:
            # Handle gate selection changes - update MFI matrix filter
            self._update_mfi_matrix_filter()

    def _update_mfi_matrix_filter(self) -> None:
        """Update the MFI matrix to show only selected and available gates."""
        if not hasattr(self, '_gate_marker_matrix_model'):
            return

        # Get selected gates from tree
        selected_gate_ids = self._gate_tree_model.get_selected_gate_ids()

        # Filter by available gates (if set)
        if self._available_gate_ids:
            visible_gate_ids = [
                gid for gid in selected_gate_ids
                if gid in self._available_gate_ids
            ]
        else:
            visible_gate_ids = selected_gate_ids

        # Apply filter to MFI matrix
        self._gate_marker_matrix_model.set_gate_filter(visible_gate_ids)

    def _on_sample_selection_for_gates(self, sample_id: str, is_selected: bool) -> None:
        """Handle sample selection changes - update available gates with debouncing."""
        from PyQt5.QtCore import QTimer

        # Use debouncing to avoid excessive updates during rapid selection changes
        if not hasattr(self, '_gate_filter_timer'):
            self._gate_filter_timer = QTimer(self)
            self._gate_filter_timer.setSingleShot(True)
            self._gate_filter_timer.timeout.connect(self._update_available_gates)

        # Reset timer - will fire 100ms after last selection change
        self._gate_filter_timer.start(100)

    def _update_available_gates(self) -> None:
        """Recalculate which gates are available for selected samples."""
        selected_sample_ids = self._sample_selection_model.get_selected_sample_ids()

        if not selected_sample_ids:
            # No samples selected - show all gates
            self._available_gate_ids = {g.gate_id for g in self._workspace_model.gates}
        else:
            # Find gates that exist in ANY selected sample
            all_gate_ids = [g.gate_id for g in self._workspace_model.gates]
            gates_without_data = self._workspace_model.get_gates_without_data_in_samples(
                gate_ids=all_gate_ids,
                sample_ids=selected_sample_ids
            )
            self._available_gate_ids = set(all_gate_ids) - set(gates_without_data)

        # Update gate tree availability display
        self._gate_tree_model.set_available_gates(self._available_gate_ids)

        # Update MFI matrix filter
        self._update_mfi_matrix_filter()

    def _on_select_all_samples(self):
        """Select all samples."""
        self._sample_selection_model.select_all()
        self._update_sample_selection_header()

    def _on_deselect_all_samples(self):
        """Deselect all samples."""
        self._sample_selection_model.deselect_all()
        self._update_sample_selection_header()

    def _on_invert_samples(self):
        """Invert sample selection."""
        self._sample_selection_model.invert_selection()
        self._update_sample_selection_header()

    def _on_sample_tree_clicked(self, index):
        """Handle click in sample selection tree - update preview."""
        item = self._sample_selection_model.itemFromIndex(index)
        if item:
            sample_id = item.data(Qt.UserRole)
            if sample_id and sample_id != "__group__":
                # Find and select this sample in the combo box
                for i in range(self._sample_combo.count()):
                    if self._sample_combo.itemData(i) == sample_id:
                        self._sample_combo.setCurrentIndex(i)
                        break

    def _update_sample_selection_header(self):
        """Update the sample selection header with count."""
        summary = self._sample_selection_model.get_selection_summary()
        selected = summary.get("selected", 0)
        total = summary.get("total", 0)
        self._sample_selection_header.setText(f"Sample Selection ({selected}/{total} selected)")

        # Update compensation info banner
        with_comp = summary.get("with_compensation", 0)
        without_comp = summary.get("without_compensation", 0)
        comp_error = summary.get("compensation_error", 0)

        # Show banner with compensation summary
        if comp_error > 0:
            # Show warning for errors
            self._comp_warning_banner.setText(
                f"⚠️ {comp_error} selected sample(s) have compensation errors. "
                f"Using 'Force Compensated' will fail for these samples."
            )
            self._comp_warning_banner.setStyleSheet(
                "background-color: #fef3c7; color: #92400e; padding: 8px; "
                "border-radius: 4px; font-weight: bold;"
            )
            self._comp_warning_banner.setVisible(True)
        elif with_comp > 0 or without_comp > 0:
            # Show informational summary
            parts = []
            if with_comp > 0:
                parts.append(f"{with_comp} with compensation")
            if without_comp > 0:
                parts.append(f"{without_comp} unmixed (no compensation)")
            self._comp_warning_banner.setText(f"ℹ️ Selected: {', '.join(parts)}")
            self._comp_warning_banner.setStyleSheet(
                "background-color: #dbeafe; color: #1e40af; padding: 8px; "
                "border-radius: 4px;"
            )
            self._comp_warning_banner.setVisible(True)
        else:
            self._comp_warning_banner.setVisible(False)

    def _toggle_comp_details(self):
        """Toggle the compensation details panel expansion."""
        is_expanded = self._comp_details_toggle.isChecked()
        self._comp_details_content.setVisible(is_expanded)
        self._comp_details_toggle.setText(
            "▼ Compensation Details" if is_expanded else "▶ Compensation Details"
        )

    def _update_comp_details_panel(self):
        """Update the compensation details panel with matrix information."""
        if not self._workspace_model.is_loaded:
            self._comp_details_widget.setVisible(False)
            return

        # Get compensation info from workspace
        comp_info = self._workspace_model.get_workspace_compensation_info()
        global_matrices = comp_info.get('global_matrices', [])
        summary = comp_info.get('summary', {})

        if not global_matrices:
            self._comp_matrix_legend.setText("No compensation matrices in workspace")
            self._comp_matrix_details_btn.setVisible(False)
            self._comp_details_widget.setVisible(True)
            return

        # Build legend HTML with colored squares
        legend_parts = []
        matrix_usage = summary.get('matrix_usage', {})

        for matrix in global_matrices:
            color = matrix.color or "#808080"
            name = matrix.name
            count = matrix_usage.get(name, 0)
            spectral_tag = " (spectral)" if matrix.spectral else ""

            # Create colored square using HTML
            legend_parts.append(
                f'<span style="color: {color}; font-size: 14px;">●</span> '
                f'<b>{name}</b>{spectral_tag}: {count} samples'
            )

        # Add count for samples without compensation
        without_comp = summary.get('samples_without_compensation', 0)
        if without_comp > 0:
            legend_parts.append(
                f'<span style="color: #808080; font-size: 14px;">○</span> '
                f'<i>No compensation</i>: {without_comp} samples'
            )

        legend_html = "<br>".join(legend_parts)
        self._comp_matrix_legend.setText(legend_html)

        # Show matrix details button if we have matrices with detectors
        has_detectors = any(m.detectors for m in global_matrices)
        self._comp_matrix_details_btn.setVisible(has_detectors)

        # Store matrices for dialog
        self._cached_comp_matrices = global_matrices

        self._comp_details_widget.setVisible(True)

    def _show_compensation_matrix_dialog(self):
        """Show a dialog with full compensation matrix details."""
        if not hasattr(self, '_cached_comp_matrices') or not self._cached_comp_matrices:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Compensation Matrix Details")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        # Create tab widget for multiple matrices
        tabs = QTabWidget()

        for matrix in self._cached_comp_matrices:
            # Create tab for this matrix
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)

            # Matrix info header
            info_label = QLabel()
            spectral_text = "Spectral (OLS)" if matrix.spectral else "Conventional"
            status_text = f" - {matrix.status}" if matrix.status else ""
            info_label.setText(
                f"<b>Name:</b> {matrix.name}<br>"
                f"<b>Type:</b> {spectral_text}{status_text}<br>"
                f"<b>Detectors:</b> {len(matrix.detectors)}"
            )
            tab_layout.addWidget(info_label)

            # Detector list
            if matrix.detectors:
                detector_label = QLabel("<b>Detector Channels:</b>")
                tab_layout.addWidget(detector_label)

                detector_list = QTextEdit()
                detector_list.setReadOnly(True)
                detector_list.setMaximumHeight(150)
                detector_list.setText("\n".join(matrix.detectors))
                tab_layout.addWidget(detector_list)

            tab_layout.addStretch()

            # Tab name with color indicator
            tab_name = f"● {matrix.name}"
            tabs.addTab(tab, tab_name)

            # Try to set tab color (this is tricky in PyQt5)
            tab_index = tabs.count() - 1
            tabs.tabBar().setTabTextColor(tab_index, QColor(matrix.color or "#808080"))

        layout.addWidget(tabs)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec_()

    def _on_select_all_markers(self):
        """Select all markers."""
        for cb in self._marker_checkboxes.values():
            cb.setChecked(True)

    def _on_clear_all_markers(self):
        """Clear all marker selections."""
        for cb in self._marker_checkboxes.values():
            cb.setChecked(False)

    def _get_selected_markers(self) -> List[str]:
        """Get list of selected marker channels."""
        selected = []
        for channel, cb in self._marker_checkboxes.items():
            if cb.isChecked():
                selected.append(channel)
        return selected

    def _get_selected_mfi_metrics(self) -> List[MFIMetric]:
        """Get list of selected MFI metrics."""
        metrics = []
        if self._mean_check.isChecked():
            metrics.append(MFIMetric.MEAN)
        if self._median_check.isChecked():
            metrics.append(MFIMetric.MEDIAN)
        if self._geomean_check.isChecked():
            metrics.append(MFIMetric.GEOMETRIC_MEAN)
        return metrics

    def _get_selected_data_source(self) -> DataSource:
        """Get the selected data source (compensation setting)."""
        checked_id = self._data_source_btn_group.checkedId()
        if checked_id == 1:
            return DataSource.RAW
        elif checked_id == 2:
            return DataSource.COMP
        else:
            return DataSource.AUTO

    def _get_descendant_depth(self) -> int:
        """Get the descendant depth setting (0 = unlimited)."""
        index = self._descendant_depth_combo.currentIndex()
        return 0 if index == 0 else index  # 0=unlimited, 1=1level, 2=2levels, 3=3levels

    def _on_wide_keywords_toggled(self, state: int):
        """Handle Keywords_Wide checkbox state change."""
        enabled = state == Qt.Checked
        self._index_columns_label.setEnabled(enabled)
        self._index_columns_list.setEnabled(enabled)

    def _populate_index_columns_list(self):
        """Populate the index columns list with discovered keywords."""
        self._index_columns_list.clear()

        # Get available keywords from the keywords model
        available_keywords = self._keywords_model.get_available_keywords()

        for keyword in available_keywords:
            item = QListWidgetItem(keyword)
            self._index_columns_list.addItem(item)
            # Don't auto-select any keywords - sample_name is always first by default
            # User can select additional index columns if needed

    def _get_selected_index_columns(self) -> List[str]:
        """Get list of selected index columns for Keywords_Wide sheet."""
        selected = []
        for item in self._index_columns_list.selectedItems():
            selected.append(item.text())
        return selected

    def _populate_keyword_selection(self):
        """Populate keyword selection list from workspace."""
        self._keyword_selection_list.clear()
        available_keywords = self._keywords_model.get_available_keywords()
        for keyword in sorted(available_keywords):
            item = QListWidgetItem(keyword)
            item.setSelected(True)  # Select all by default
            self._keyword_selection_list.addItem(item)

    def _on_select_all_export_keywords(self):
        """Select all keywords for export."""
        self._keyword_selection_list.selectAll()

    def _on_clear_all_export_keywords(self):
        """Clear all keyword selections for export."""
        self._keyword_selection_list.clearSelection()

    def _get_selected_export_keywords(self) -> List[str]:
        """Get list of selected keywords for export."""
        return [item.text() for item in self._keyword_selection_list.selectedItems()]

    def _on_export(self):
        """Handle export action."""
        # Validate sample selection
        selected_sample_ids = self._sample_selection_model.get_selected_sample_ids()
        if not selected_sample_ids:
            QMessageBox.warning(
                self,
                "No Samples Selected",
                "Please select at least one sample to export."
            )
            return

        # Validate gate selection (from gate tree)
        selected_gates = self._gate_tree_model.get_selected_gates()
        if not selected_gates:
            QMessageBox.warning(
                self,
                "No Gates Selected",
                "Please select at least one gate to export."
            )
            return

        mfi_metrics = self._get_selected_mfi_metrics()
        if not mfi_metrics:
            QMessageBox.warning(
                self,
                "No MFI Metrics Selected",
                "Please select at least one MFI metric."
            )
            return

        # Get matrix selections (gate/marker combinations)
        matrix_selections = self._gate_marker_matrix_model.get_selections()

        # Check compensation status if using Force Compensated
        data_source = self._get_selected_data_source()
        if data_source == DataSource.COMP:
            summary = self._sample_selection_model.get_selection_summary()
            missing_comp = summary.get("missing_compensation", 0)
            if missing_comp > 0:
                result = QMessageBox.warning(
                    self,
                    "Compensation Warning",
                    f"{missing_comp} selected sample(s) are missing compensation.\n\n"
                    "Export will fail for these samples with 'Force Compensated' mode.\n\n"
                    "Continue anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if result == QMessageBox.No:
                    return

        # Check for gates that don't exist in any selected sample
        gate_ids_initial = self._gate_tree_model.get_selected_gate_ids()
        gates_to_exclude = self._workspace_model.get_gates_without_data_in_samples(
            gate_ids=gate_ids_initial,
            sample_ids=selected_sample_ids
        )

        if gates_to_exclude:
            # Build readable list of excluded gates
            excluded_gate_names = []
            for gate_id in gates_to_exclude:
                gate = self._gate_tree_model.get_gate_by_id(gate_id)
                if gate:
                    excluded_gate_names.append(gate.full_path_string)
                else:
                    excluded_gate_names.append(gate_id)

            # Format the message (show up to 5, then "... and X more")
            if len(excluded_gate_names) <= 5:
                gate_list = "\n".join(f"  • {name}" for name in excluded_gate_names)
            else:
                gate_list = "\n".join(f"  • {name}" for name in excluded_gate_names[:5])
                gate_list += f"\n  ... and {len(excluded_gate_names) - 5} more"

            result = QMessageBox.warning(
                self,
                "Gates Without Data",
                f"The following {len(gates_to_exclude)} gate(s) do not exist in any of the "
                f"{len(selected_sample_ids)} selected sample(s) and will be excluded from export:\n\n"
                f"{gate_list}\n\n"
                "Continue with export?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes  # Default to Yes since this is informational
            )

            if result == QMessageBox.No:
                return

            # Filter out excluded gates for the rest of export
            gate_ids_filtered = [gid for gid in gate_ids_initial if gid not in gates_to_exclude]
        else:
            gate_ids_filtered = gate_ids_initial

        # Check if any gates remain after filtering
        if not gate_ids_filtered:
            QMessageBox.warning(
                self,
                "No Valid Gates",
                "None of the selected gates exist in the selected samples.\n\n"
                "Please select different gates or samples."
            )
            return

        # Get file path
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Excel",
            "flowkit_export.xlsx",
            "Excel Files (*.xlsx)"
        )

        if not file_path:
            return

        try:
            # Use filtered gate_ids from the earlier validation
            gate_ids = gate_ids_filtered

            # Extract unique markers from matrix selections (for MFI calculations)
            # If no matrix selections, fall back to all selected markers
            if matrix_selections:
                selected_markers = list(set(channel for _, channel in matrix_selections))
            else:
                selected_markers = self._get_selected_markers()

            all_markers = self._workspace_model.channels
            include_wide_keywords = self._wide_keywords_check.isChecked()
            include_tidy_frequencies = self._tidy_frequencies_check.isChecked()
            index_columns = self._get_selected_index_columns() if include_wide_keywords else None
            selected_keywords = self._get_selected_export_keywords()

            # Get reference gates and depth settings for normalized frequencies
            reference_gate_ids = self._gate_tree_model.get_reference_gates()
            descendant_depth = self._get_descendant_depth()

            logger.info(f"Starting export: {len(selected_sample_ids)} samples, {len(gate_ids)} gates")
            logger.info(f"Matrix selections: {len(matrix_selections)} gate/marker combinations")
            logger.info(f"Data source: {data_source.value}")
            logger.info(f"Selected keywords for export: {len(selected_keywords)}")
            if index_columns:
                logger.info(f"Index columns for Keywords_Wide: {index_columns}")
            if reference_gate_ids:
                logger.info(f"Reference gates for normalization: {reference_gate_ids}")
                logger.info(f"Descendant depth: {'unlimited' if descendant_depth == 0 else descendant_depth}")

            # Create exporter with selected samples and matrix selections
            include_all_sheets = self._include_all_sheets_checkbox.isChecked()
            exporter = XLSXExporter(
                workspace=self._workspace_model,
                keywords_model=self._keywords_model,
                gate_ids=gate_ids,
                selected_markers=selected_markers,
                all_markers=all_markers,
                mfi_metrics=mfi_metrics,
                include_wide_keywords=include_wide_keywords,
                include_tidy_frequencies=include_tidy_frequencies,
                include_all_sheets=include_all_sheets,
                data_source=data_source,
                index_columns=index_columns,
                selected_keywords=selected_keywords,
                selected_sample_ids=selected_sample_ids,
                matrix_selections=matrix_selections,
                reference_gate_ids=reference_gate_ids,
                descendant_depth=descendant_depth
            )

            # Show progress dialog with detailed status
            progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(400)  # Wider to show detailed status

            # Create cancellation token for user-initiated cancellation
            cancellation_token = CancellationToken()

            def on_cancel():
                cancellation_token.cancel("Export cancelled by user")
                logger.info("User requested export cancellation")

            progress.canceled.connect(on_cancel)

            def update_progress(current, total):
                progress.setValue(int(current / total * 100))
                # Check if user cancelled
                if cancellation_token.is_cancelled:
                    return

            def update_status(message):
                progress.setLabelText(message)
                # Process events to ensure UI updates during long operations
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()

            # Export with progress, status, and cancellation callbacks
            exporter.export(
                file_path,
                progress_callback=update_progress,
                status_callback=update_status,
                cancellation_token=cancellation_token
            )

            progress.close()

            # Check for warnings
            warnings = exporter.get_warnings()
            if warnings:
                warning_msg = f"Export completed with {len(warnings)} warning(s).\n\n"
                warning_msg += "See 'Warnings' sheet in the exported file for details."
                QMessageBox.warning(
                    self,
                    "Export Complete (with warnings)",
                    warning_msg
                )
            else:
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Data exported successfully to:\n{file_path}"
                )

            logger.info(f"Export completed: {file_path}")

        except CancellationError:
            logger.info("Export cancelled by user")
            QMessageBox.information(
                self,
                "Export Cancelled",
                "Export was cancelled."
            )
        except Exception as e:
            logger.error(f"Export failed: {type(e).__name__}: {e}")
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export data:\n{str(e)}"
            )
        finally:
            # Clear caches after export to free memory for large datasets
            self._workspace_model.clear_cache()
            logger.info("Cleared caches after export")

    def _on_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About FlowKit GUI",
            "FlowKit GUI v0.1.0\n\n"
            "A tool for extracting and analyzing\n"
            "flow cytometry data from FlowJo workspaces.\n\n"
            "Built with FlowKit and PyQt5."
        )

    def _on_theme_changed(self, mode: ThemeMode):
        """Handle theme mode change from menu."""
        set_theme_mode(mode)
        self._update_theme_menu_state()
        self._update_theme_indicator()

    def _on_cycle_theme(self):
        """Cycle through theme modes."""
        cycle_theme()
        self._update_theme_menu_state()
        self._update_theme_indicator()

    def _update_theme_menu_state(self):
        """Update the checked state of theme menu items."""
        current_mode = get_current_mode()
        if current_mode == ThemeMode.SYSTEM:
            self._theme_system_action.setChecked(True)
        elif current_mode == ThemeMode.LIGHT:
            self._theme_light_action.setChecked(True)
        elif current_mode == ThemeMode.DARK:
            self._theme_dark_action.setChecked(True)

    def _update_theme_indicator(self):
        """Update the theme indicator in the status bar."""
        if hasattr(self, '_theme_indicator'):
            theme_manager = get_theme_manager()
            mode = theme_manager.mode
            actual = theme_manager.get_actual_theme()

            if mode == ThemeMode.SYSTEM:
                text = f"Theme: System ({actual.title()})"
            else:
                text = f"Theme: {mode.value.title()}"

            self._theme_indicator.setText(text)


def main():
    """Application entry point."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("FlowKit GUI")
    app.setOrganizationName("FlowKit")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
