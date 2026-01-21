"""
Gate × Marker Matrix View - Custom widget with frozen headers and zoom support.

This module provides a matrix widget for selecting gate/marker combinations:
- Frozen row headers (gate names) and column headers (marker names)
- Rotated column header text (90 degrees)
- Zoom support via Cmd+/- and trackpad pinch
- Row/column click to select entire row/column
"""

from typing import Optional
from PyQt5.QtCore import Qt, QSize, QRect, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QPushButton, QLabel, QAbstractItemView, QStyle, QStyleOptionButton,
    QStyledItemDelegate, QScrollBar, QFrame, QSizePolicy
)
from PyQt5.QtGui import QPainter, QFont, QColor, QBrush, QPen, QWheelEvent, QKeyEvent

from ..models.gate_marker_matrix_model import GateMarkerMatrixModel
from ..utils.logging_config import get_logger

logger = get_logger("gate_marker_matrix_view")


class RotatedHeaderView(QHeaderView):
    """
    Custom header view with 90-degree rotated text for column headers.
    """

    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignCenter)
        self._min_section_size = 24

    def sizeHint(self) -> QSize:
        """Return size hint with extra height for rotated text."""
        base = super().sizeHint()
        if self.orientation() == Qt.Horizontal:
            # Need more height for rotated text
            return QSize(base.width(), 120)
        return base

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        """Paint section with rotated text for horizontal headers."""
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
                # Rotate painter for vertical text
                painter.translate(rect.x() + rect.width() / 2,
                                  rect.y() + rect.height() - 5)
                painter.rotate(-90)

                # Draw text
                font = painter.font()
                font.setPointSize(9)
                painter.setFont(font)
                painter.setPen(self.palette().text().color())

                # Calculate text rect (width becomes height after rotation)
                text_rect = QRect(0, -rect.width() // 2, rect.height() - 10, rect.width())
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(text))

        painter.restore()


class CheckboxDelegate(QStyledItemDelegate):
    """
    Delegate that renders checkboxes centered in cells.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkbox_size = 16

    def paint(self, painter: QPainter, option, index) -> None:
        """Paint a centered checkbox."""
        painter.save()

        # Draw cell background
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        # Get check state
        check_state = index.data(Qt.CheckStateRole)
        is_checked = check_state == Qt.Checked

        # Calculate checkbox rect (centered)
        checkbox_rect = QRect(0, 0, self._checkbox_size, self._checkbox_size)
        checkbox_rect.moveCenter(option.rect.center())

        # Draw checkbox
        style_option = QStyleOptionButton()
        style_option.rect = checkbox_rect
        style_option.state = QStyle.State_Enabled
        if is_checked:
            style_option.state |= QStyle.State_On
        else:
            style_option.state |= QStyle.State_Off

        # Use the widget's style to draw the checkbox
        widget = option.widget
        if widget:
            widget.style().drawControl(QStyle.CE_CheckBox, style_option, painter, widget)
        else:
            QApplication.style().drawControl(QStyle.CE_CheckBox, style_option, painter)

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

        # Info label
        self._info_label = QLabel("Load a workspace to see gates and markers")
        self._info_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self._info_label)

        # Table view
        self._table_view = QTableView()
        self._table_view.setSelectionMode(QAbstractItemView.NoSelection)
        self._table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # Use custom rotated header for columns
        self._table_view.setHorizontalHeader(RotatedHeaderView(Qt.Horizontal, self._table_view))

        # Set up vertical header (row headers - gate names)
        v_header = self._table_view.verticalHeader()
        v_header.setVisible(True)
        v_header.setDefaultSectionSize(self._base_cell_size)
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.sectionClicked.connect(self._on_row_header_clicked)

        # Set up horizontal header
        h_header = self._table_view.horizontalHeader()
        h_header.setDefaultSectionSize(self._base_cell_size)
        h_header.setSectionResizeMode(QHeaderView.Fixed)
        h_header.sectionClicked.connect(self._on_column_header_clicked)

        # Use checkbox delegate
        self._delegate = CheckboxDelegate(self._table_view)
        self._table_view.setItemDelegate(self._delegate)

        # Style the table
        self._table_view.setShowGrid(True)
        self._table_view.setGridStyle(Qt.SolidLine)
        self._table_view.setStyleSheet("""
            QTableView {
                gridline-color: #ddd;
                background-color: white;
            }
            QTableView::item {
                padding: 0px;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 4px;
                border: 1px solid #ddd;
                font-weight: bold;
            }
        """)

        layout.addWidget(self._table_view, 1)

        # Selection summary
        self._summary_label = QLabel("No selections")
        self._summary_label.setStyleSheet("color: #666;")
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

        layout.addStretch()

        # Help text
        help_label = QLabel("Click row/column headers to select entire row/column")
        help_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(help_label)

        return toolbar

    def set_model(self, model: GateMarkerMatrixModel) -> None:
        """Set the matrix model."""
        self._model = model
        self._table_view.setModel(model)

        # Connect to model signals
        model.selectionChanged.connect(self._update_summary)

        # Update zoom
        self._apply_zoom()
        self._update_summary()
        self._update_info_label()

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
        """Apply current zoom level to cell sizes."""
        cell_size = int(self._base_cell_size * self._zoom_level)

        # Update row heights
        v_header = self._table_view.verticalHeader()
        v_header.setDefaultSectionSize(cell_size)

        # Update column widths
        h_header = self._table_view.horizontalHeader()
        h_header.setDefaultSectionSize(cell_size)

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
