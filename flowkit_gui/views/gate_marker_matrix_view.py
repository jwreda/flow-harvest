"""
Gate × Marker Matrix View - Custom widget with frozen headers and zoom support.

This module provides a matrix widget for selecting gate/marker combinations:
- Frozen row headers (gate names) and column headers (marker names)
- Rotated column header text (90 degrees)
- Zoom support via Cmd+/- and trackpad pinch
- Row/column click to select entire row/column
"""

from typing import Optional
from PyQt5.QtCore import Qt, QSize, QRect, pyqtSignal, QEvent, QPoint
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QPushButton, QLabel, QAbstractItemView, QStyle, QStyleOptionButton,
    QStyledItemDelegate, QScrollBar, QFrame, QSizePolicy, QToolTip
)
from PyQt5.QtGui import QPainter, QFont, QColor, QBrush, QPen, QWheelEvent, QKeyEvent, QMouseEvent

from ..models.gate_marker_matrix_model import GateMarkerMatrixModel
from ..utils.logging_config import get_logger

logger = get_logger("gate_marker_matrix_view")

# Okabe-Ito colorblind-friendly palette for depth indicators
# Each position in hierarchy gets a sequential color, cycling for deep hierarchies
DEPTH_COLORS = [
    "#CC79A7",  # 1st dot - reddish purple/pink
    "#D55E00",  # 2nd dot - vermillion/orange
    "#E79F00",  # 3rd dot - amber/orange
    "#F0E441",  # 4th dot - yellow
    "#019E73",  # 5th dot - bluish green/teal
    "#57B4E9",  # 6th dot - sky blue
    "#0072B2",  # 7th dot - blue (then cycles back to 1st)
]


class RotatedHeaderView(QHeaderView):
    """
    Custom header view with 90-degree rotated text for column headers.
    """

    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignCenter)
        self._min_section_size = 24
        self._zoom_level = 1.0
        self._base_dot_size = 8
        self._base_dot_margin = 4
        self._base_font_size = 9
        self.setMouseTracking(True)  # Enable mouse tracking for tooltips

    def set_zoom_level(self, zoom: float) -> None:
        """Set the zoom level for scaling text and dot sizes."""
        self._zoom_level = zoom
        self.viewport().update()

    def sizeHint(self) -> QSize:
        """Return size hint with extra height for rotated text."""
        base = super().sizeHint()
        if self.orientation() == Qt.Horizontal:
            # Need more height for rotated text
            return QSize(base.width(), 120)
        return base

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        """Paint section with rotated text and colored dot for horizontal headers."""
        if self.orientation() != Qt.Horizontal:
            super().paintSection(painter, rect, logicalIndex)
            return

        painter.save()

        # Draw background
        opt = self.style().standardIcon(QStyle.SP_TitleBarNormalButton)
        painter.fillRect(rect, self.palette().button())

        # Draw border
        painter.setPen(QPen(self.palette().mid().color()))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())

        # Get header text
        model = self.model()
        if model:
            text = model.headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole)
            if text:
                # Calculate scaled sizes
                dot_size = int(self._base_dot_size * self._zoom_level)
                dot_margin = int(self._base_dot_margin * self._zoom_level)
                font_size = max(6, int(self._base_font_size * self._zoom_level))

                # Rotate painter for vertical text
                painter.translate(rect.x() + rect.width() / 2,
                                  rect.y() + rect.height() - 5)
                painter.rotate(-90)

                # Draw colored dot for this column (cycles through palette)
                dot_color = QColor(DEPTH_COLORS[logicalIndex % len(DEPTH_COLORS)])
                painter.setBrush(QBrush(dot_color))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(0, -dot_size // 2, dot_size, dot_size)

                # Draw text offset after dot
                text_offset = dot_size + dot_margin
                font = painter.font()
                font.setPointSize(font_size)
                painter.setFont(font)
                painter.setPen(self.palette().text().color())

                # Calculate text rect (width becomes height after rotation)
                text_rect = QRect(text_offset, -rect.width() // 2, rect.height() - 10 - text_offset, rect.width())
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(text))

        painter.restore()

    def event(self, event: QEvent) -> bool:
        """Handle tooltip events to show marker name on hover."""
        if event.type() == QEvent.ToolTip:
            pos = event.pos()
            section = self.logicalIndexAt(pos)

            if section >= 0:
                model = self.model()
                if model:
                    tooltip = model.headerData(section, self.orientation(), Qt.ToolTipRole)
                    if tooltip:
                        QToolTip.showText(event.globalPos(), str(tooltip), self)
                        return True

            QToolTip.hideText()
            return True

        return super().event(event)


class ColoredDepthHeaderView(QHeaderView):
    """
    Custom vertical header view that displays colored depth dots before gate names.

    Uses the Okabe-Ito colorblind-friendly palette where each position in the
    hierarchy gets a distinct color: depth 3 shows pink + orange + amber dots.
    """

    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Base sizes (will be scaled by zoom level)
        self._base_dot_size = 8
        self._base_dot_spacing = 2
        self._base_text_margin = 6
        self._base_font_size = 9
        self._zoom_level = 1.0

        # Width resizing state (for vertical headers only)
        self._drag_start_x = None
        self._drag_start_width = None
        self._min_width = 80
        self._resize_handle_width = 10  # pixels for resize detection (increased from 5 for easier grabbing)
        self.setMouseTracking(True)

    def set_zoom_level(self, zoom: float) -> None:
        """Set the zoom level for scaling text and dot sizes."""
        self._zoom_level = zoom
        self.viewport().update()

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        """Paint section with colored depth dots and gate name."""
        if self.orientation() != Qt.Vertical:
            super().paintSection(painter, rect, logicalIndex)
            return

        painter.save()

        # Calculate scaled sizes
        dot_size = int(self._base_dot_size * self._zoom_level)
        dot_spacing = int(self._base_dot_spacing * self._zoom_level)
        text_margin = int(self._base_text_margin * self._zoom_level)
        font_size = max(6, int(self._base_font_size * self._zoom_level))

        # Draw background using theme-aware palette
        painter.fillRect(rect, self.palette().window())

        # Draw borders
        painter.setPen(QPen(self.palette().mid().color()))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())

        # Get gate name and depth from model
        model = self.model()
        if model:
            gate_name = model.headerData(logicalIndex, Qt.Vertical, Qt.DisplayRole)
            depth = model.headerData(logicalIndex, Qt.Vertical, Qt.UserRole)

            if gate_name is not None:
                # Calculate starting position for dots
                x_pos = rect.x() + 6
                y_center = rect.y() + rect.height() // 2

                # Draw colored depth dots
                if depth and depth > 0:
                    for i in range(depth):
                        # Get color for this position (cycle through palette)
                        color_idx = i % len(DEPTH_COLORS)
                        dot_color = QColor(DEPTH_COLORS[color_idx])

                        # Draw filled circle
                        painter.setBrush(QBrush(dot_color))
                        painter.setPen(Qt.NoPen)
                        dot_x = x_pos + i * (dot_size + dot_spacing)
                        dot_y = y_center - dot_size // 2
                        painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)

                    # Update x position for text
                    x_pos += depth * (dot_size + dot_spacing) + text_margin

                # Draw gate name text using theme-aware color
                font = painter.font()
                font.setPointSize(font_size)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(self.palette().text().color())

                text_rect = QRect(
                    x_pos,
                    rect.y(),
                    rect.width() - x_pos + rect.x() - 4,
                    rect.height()
                )
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(gate_name))

        # Draw subtle grip indicator at right edge for resize handle
        grip_x = rect.right() - 3
        grip_color = QColor("#888888")
        grip_color.setAlpha(120)  # Semi-transparent
        painter.setPen(QPen(grip_color, 1))
        # Draw 3 vertical dots
        y_mid = rect.y() + rect.height() // 2
        for offset in [-4, 0, 4]:
            painter.drawPoint(grip_x, y_mid + offset)

        painter.restore()

    def sizeHint(self) -> QSize:
        """Return size hint with extra width for depth dots."""
        base = super().sizeHint()
        # Add extra width to accommodate dots (assume max depth of 7), scaled by zoom
        dot_size = int(self._base_dot_size * self._zoom_level)
        dot_spacing = int(self._base_dot_spacing * self._zoom_level)
        text_margin = int(self._base_text_margin * self._zoom_level)
        max_dots_width = 7 * (dot_size + dot_spacing) + text_margin
        return QSize(base.width() + max_dots_width, base.height())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start width resize if clicking near right edge of vertical header."""
        if self.orientation() == Qt.Vertical and event.x() >= self.width() - self._resize_handle_width:
            self._drag_start_x = event.globalX()
            self._drag_start_width = self.width()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle resize cursor display and width dragging."""
        if self.orientation() == Qt.Vertical:
            if self._drag_start_x is not None:
                # Currently dragging - calculate new width
                delta = event.globalX() - self._drag_start_x
                new_width = self._drag_start_width + delta
                # Dynamic max width: 90% of parent viewport, with fallback
                max_width = int(self.parent().width() * 0.9) if self.parent() else 400
                new_width = max(self._min_width, min(max_width, new_width))
                self.setFixedWidth(new_width)
                event.accept()
                return
            elif event.x() >= self.width() - self._resize_handle_width:
                # Hovering near edge - show resize cursor
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End width resize drag operation."""
        if self._drag_start_x is not None:
            self._drag_start_x = None
            self._drag_start_width = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def event(self, event: QEvent) -> bool:
        """Handle tooltip events to show gate name on hover."""
        if event.type() == QEvent.ToolTip:
            # Get the section (row) at the mouse position
            pos = event.pos()
            section = self.logicalIndexAt(pos)

            if section >= 0:
                model = self.model()
                if model:
                    # Get tooltip from model
                    tooltip = model.headerData(section, self.orientation(), Qt.ToolTipRole)
                    if tooltip:
                        QToolTip.showText(event.globalPos(), str(tooltip), self)
                        return True

            QToolTip.hideText()
            return True

        return super().event(event)


class CheckboxDelegate(QStyledItemDelegate):
    """
    Delegate that renders colored checkboxes centered in cells.
    Each column gets a color from the Okabe-Ito palette, cycling through.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_checkbox_size = 16
        self._zoom_level = 1.0

    def set_zoom_level(self, zoom: float) -> None:
        """Set the zoom level for scaling checkbox size."""
        self._zoom_level = zoom

    def paint(self, painter: QPainter, option, index) -> None:
        """Paint a centered colored checkbox matching the column color."""
        painter.save()

        # Draw cell background
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        # Get check state
        check_state = index.data(Qt.CheckStateRole)
        is_checked = check_state == Qt.Checked

        # Get column color from palette (cycles through 7 colors)
        col_color = QColor(DEPTH_COLORS[index.column() % len(DEPTH_COLORS)])

        # Calculate scaled checkbox size
        checkbox_size = int(self._base_checkbox_size * self._zoom_level)
        checkbox_rect = QRect(0, 0, checkbox_size, checkbox_size)
        checkbox_rect.moveCenter(option.rect.center())

        # Scale other dimensions
        corner_radius = max(1, int(3 * self._zoom_level))
        pen_width = max(1, int(2 * self._zoom_level))
        inset = max(1, int(3 * self._zoom_level))

        # Enable anti-aliasing for smoother rendering
        painter.setRenderHint(QPainter.Antialiasing, True)

        if is_checked:
            # Filled box with white checkmark
            painter.setBrush(QBrush(col_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(checkbox_rect, corner_radius, corner_radius)

            # Draw white checkmark (scaled)
            painter.setPen(QPen(Qt.white, pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = checkbox_rect.x(), checkbox_rect.y()
            w, h = checkbox_rect.width(), checkbox_rect.height()
            # Checkmark path scaled proportionally
            painter.drawLine(x + inset, y + h // 2, x + w // 2 - 1, y + h - inset - 1)
            painter.drawLine(x + w // 2 - 1, y + h - inset - 1, x + w - inset, y + inset + 1)
        else:
            # Border only
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(col_color, pen_width))
            # Inset rect slightly to account for pen width
            inset_rect = checkbox_rect.adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(inset_rect, max(1, corner_radius - 1), max(1, corner_radius - 1))

        painter.restore()

    def editorEvent(self, event, model, option, index):
        """Handle mouse clicks to toggle checkbox."""
        if event.type() == event.MouseButtonRelease:
            current_state = index.data(Qt.CheckStateRole)
            new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
            model.setData(index, new_state, Qt.CheckStateRole)
            return True
        return False


class GateMarkerMatrixView(QWidget):
    """
    Matrix widget with frozen headers and zoom support.

    Features:
    - Frozen row headers (gate names on left)
    - Frozen column headers (marker names on top, rotated 90°)
    - Zoom via Cmd+/- and Ctrl+scroll
    - Click row/column headers to select entire row/column
    """

    # Signal emitted when selection changes
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._model: Optional[GateMarkerMatrixModel] = None
        self._zoom_level = 1.0
        self._base_cell_size = 24
        self._min_zoom = 0.5
        self._max_zoom = 2.5

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Toolbar
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)

        # Info label - styled via QSS using object name
        self._info_label = QLabel("Load a workspace to see gates and markers")
        self._info_label.setObjectName("matrixInfoLabel")
        layout.addWidget(self._info_label)

        # Table view
        self._table_view = QTableView()
        self._table_view.setSelectionMode(QAbstractItemView.NoSelection)
        self._table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # Use custom rotated header for columns
        self._table_view.setHorizontalHeader(RotatedHeaderView(Qt.Horizontal, self._table_view))

        # Use custom colored depth header for rows (gate names with colored dots)
        colored_header = ColoredDepthHeaderView(Qt.Vertical, self._table_view)
        colored_header.setMinimumWidth(150)
        colored_header.setMaximumWidth(800)
        colored_header.setFixedWidth(200)  # Initial default, will auto-size when model loaded
        self._table_view.setVerticalHeader(colored_header)
        v_header = self._table_view.verticalHeader()
        v_header.setVisible(True)
        v_header.setDefaultSectionSize(self._base_cell_size)
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.setSectionsClickable(True)
        v_header.sectionClicked.connect(self._on_row_header_clicked)

        # Set up horizontal header
        h_header = self._table_view.horizontalHeader()
        h_header.setDefaultSectionSize(self._base_cell_size)
        h_header.setSectionResizeMode(QHeaderView.Fixed)
        h_header.setSectionsClickable(True)
        h_header.sectionClicked.connect(self._on_column_header_clicked)

        # Use checkbox delegate
        self._delegate = CheckboxDelegate(self._table_view)
        self._table_view.setItemDelegate(self._delegate)

        # Style the table - use object name for theme-aware QSS styling
        self._table_view.setShowGrid(True)
        self._table_view.setGridStyle(Qt.SolidLine)
        self._table_view.setObjectName("gateMarkerMatrix")

        layout.addWidget(self._table_view, 1)

        # Selection summary - styled via QSS using object name
        self._summary_label = QLabel("No selections")
        self._summary_label.setObjectName("matrixSummaryLabel")
        layout.addWidget(self._summary_label)

    def _create_toolbar(self) -> QWidget:
        """Create the toolbar with selection and zoom controls."""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Selection buttons
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._on_select_all)
        layout.addWidget(select_all_btn)

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(self._on_clear_all)
        layout.addWidget(clear_all_btn)

        layout.addSpacing(20)

        # Zoom controls
        zoom_label = QLabel("Zoom:")
        layout.addWidget(zoom_label)

        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedWidth(30)
        zoom_out_btn.clicked.connect(lambda: self._adjust_zoom(0.9))
        zoom_out_btn.setToolTip("Zoom out (Cmd+-)")
        layout.addWidget(zoom_out_btn)

        self._zoom_display = QLabel("100%")
        self._zoom_display.setFixedWidth(50)
        self._zoom_display.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._zoom_display)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(30)
        zoom_in_btn.clicked.connect(lambda: self._adjust_zoom(1.1))
        zoom_in_btn.setToolTip("Zoom in (Cmd++)")
        layout.addWidget(zoom_in_btn)

        reset_zoom_btn = QPushButton("Reset")
        reset_zoom_btn.clicked.connect(self._reset_zoom)
        reset_zoom_btn.setToolTip("Reset to 100%")
        layout.addWidget(reset_zoom_btn)

        layout.addSpacing(20)

        # Disambiguation toggle
        self._disambiguate_btn = QPushButton("Full Names")
        self._disambiguate_btn.setCheckable(True)
        self._disambiguate_btn.setChecked(True)
        self._disambiguate_btn.setToolTip("Toggle between full names (with parent prefix for duplicates) and short names")
        self._disambiguate_btn.clicked.connect(self._on_disambiguate_toggled)
        layout.addWidget(self._disambiguate_btn)

        layout.addStretch()

        # Help text - styled via QSS using object name
        help_label = QLabel("Click row/column headers to select entire row/column")
        help_label.setObjectName("matrixHelpLabel")
        layout.addWidget(help_label)

        return toolbar

    def set_model(self, model: GateMarkerMatrixModel) -> None:
        """Set the matrix model."""
        self._model = model
        self._table_view.setModel(model)

        # Connect to model signals
        model.selectionChanged.connect(self._update_summary)
        model.modelReset.connect(self._update_info_label)
        model.modelReset.connect(self._auto_size_gate_header)

        # Update zoom
        self._apply_zoom()
        self._update_summary()
        self._update_info_label()
        self._auto_size_gate_header()

    def _update_info_label(self) -> None:
        """Update the info label based on model state."""
        if self._model:
            rows = self._model.rowCount()
            cols = self._model.columnCount()
            if rows > 0 and cols > 0:
                self._info_label.setText(f"{rows} gates × {cols} markers")
            else:
                self._info_label.setText("No gates or markers available")
        else:
            self._info_label.setText("Load a workspace to see gates and markers")

    def _auto_size_gate_header(self) -> None:
        """Calculate and set appropriate width for gate name header based on content."""
        if not self._model or self._model.rowCount() == 0:
            return

        v_header = self._table_view.verticalHeader()
        fm = v_header.fontMetrics()
        max_width = 150  # Minimum width

        for row in range(self._model.rowCount()):
            gate_name = self._model.headerData(row, Qt.Vertical, Qt.DisplayRole)
            depth = self._model.headerData(row, Qt.Vertical, Qt.UserRole) or 0

            # Calculate width: left margin + depth dots + text margin + text + right margin
            dot_width = depth * 10  # DOT_SIZE (8) + DOT_SPACING (2)
            text_width = fm.horizontalAdvance(str(gate_name)) if gate_name else 0
            row_width = 12 + dot_width + 6 + text_width + 12  # margins
            max_width = max(max_width, row_width)

        # Apply with bounds (min 150, max 600)
        final_width = min(max(max_width, 150), 600)
        v_header.setFixedWidth(final_width)

    def _update_summary(self) -> None:
        """Update the selection summary label."""
        if self._model:
            count = self._model.get_selection_count()
            total = self._model.rowCount() * self._model.columnCount()
            if total > 0:
                pct = count / total * 100
                self._summary_label.setText(f"{count:,} of {total:,} combinations selected ({pct:.1f}%)")
            else:
                self._summary_label.setText("No selections")
            self.selectionChanged.emit()
        else:
            self._summary_label.setText("No selections")

    def _on_select_all(self) -> None:
        """Select all combinations."""
        if self._model:
            self._model.select_all()

    def _on_clear_all(self) -> None:
        """Clear all selections."""
        if self._model:
            self._model.clear_all()

    def _on_disambiguate_toggled(self, checked: bool) -> None:
        """Toggle disambiguation mode for gate names."""
        if self._model:
            self._model.set_disambiguate_enabled(checked)
            self._disambiguate_btn.setText("Full Names" if checked else "Short Names")

    def _on_row_header_clicked(self, row: int) -> None:
        """Handle click on row header - toggle entire row."""
        if self._model:
            self._model.toggle_row(row)

    def _on_column_header_clicked(self, col: int) -> None:
        """Handle click on column header - toggle entire column."""
        if self._model:
            self._model.toggle_column(col)

    def _adjust_zoom(self, factor: float) -> None:
        """Adjust zoom level by factor."""
        new_zoom = self._zoom_level * factor
        new_zoom = max(self._min_zoom, min(self._max_zoom, new_zoom))

        if new_zoom != self._zoom_level:
            self._zoom_level = new_zoom
            self._apply_zoom()

    def _reset_zoom(self) -> None:
        """Reset zoom to 100%."""
        self._zoom_level = 1.0
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        """Apply current zoom level to cell sizes and all components."""
        cell_size = int(self._base_cell_size * self._zoom_level)

        # Update row heights
        v_header = self._table_view.verticalHeader()
        v_header.setDefaultSectionSize(cell_size)

        # Update column widths
        h_header = self._table_view.horizontalHeader()
        h_header.setDefaultSectionSize(cell_size)

        # Propagate zoom level to delegate and headers for content scaling
        self._delegate.set_zoom_level(self._zoom_level)
        h_header.set_zoom_level(self._zoom_level)
        v_header.set_zoom_level(self._zoom_level)

        # Force repaint of the table
        self._table_view.viewport().update()

        # Update zoom display
        self._zoom_display.setText(f"{int(self._zoom_level * 100)}%")

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle wheel events for zoom."""
        # Check for Cmd/Ctrl modifier
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._adjust_zoom(1.1)
            elif delta < 0:
                self._adjust_zoom(0.9)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts for zoom."""
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
                self._adjust_zoom(1.1)
                event.accept()
                return
            elif event.key() == Qt.Key_Minus:
                self._adjust_zoom(0.9)
                event.accept()
                return
            elif event.key() == Qt.Key_0:
                self._reset_zoom()
                event.accept()
                return
        super().keyPressEvent(event)

    def get_selections(self):
        """Get current selections from the model."""
        if self._model:
            return self._model.get_selections()
        return []

    def get_selections_by_gate(self):
        """Get selections organized by gate."""
        if self._model:
            return self._model.get_selections_by_gate()
        return {}
