"""
Custom QTreeView for gate hierarchy with multi-select batch toggle support.

Enables Shift+Click range selection, Ctrl+Click toggle, Shift+Arrow,
and Space bar batch-toggling of checkboxes across all selected rows.
"""

from PyQt5.QtWidgets import QTreeView, QAbstractItemView, QStyle
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QKeyEvent, QMouseEvent


class GateTreeView(QTreeView):
    """QTreeView subclass with ExtendedSelection and batch checkbox toggling."""

    batchToggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Space bar batch-toggles checkboxes for all selected rows."""
        if event.key() == Qt.Key_Space:
            selected_indexes = self.selectionModel().selectedRows(0)
            if selected_indexes:
                model = self.model()
                first_item = model.itemFromIndex(selected_indexes[0])
                if first_item:
                    new_state = (Qt.Unchecked if first_item.checkState() == Qt.Checked
                                 else Qt.Checked)
                    self._batch_set_check_state(new_state, selected_indexes)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Intercept checkbox clicks to batch-apply across multi-selection."""
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if (index.isValid()
                    and index.column() == 0
                    and self.selectionModel()
                    and self.selectionModel().isSelected(index)):
                selected_rows = self.selectionModel().selectedRows(0)
                if len(selected_rows) > 1 and self._is_click_on_checkbox(event.pos(), index):
                    model = self.model()
                    item = model.itemFromIndex(index)
                    if item:
                        new_state = (Qt.Unchecked if item.checkState() == Qt.Checked
                                     else Qt.Checked)
                        self._batch_set_check_state(new_state, selected_rows)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _is_click_on_checkbox(self, pos, index) -> bool:
        """Test whether a click position falls within the checkbox area of column 0."""
        rect = self.visualRect(index)
        # Checkbox position matches delegate: rect.x() + 4, size 16x16
        checkbox_left = rect.x() + 4
        checkbox_right = checkbox_left + 16
        checkbox_top = rect.y() + (rect.height() - 16) // 2
        checkbox_bottom = checkbox_top + 16
        return (checkbox_left <= pos.x() <= checkbox_right
                and checkbox_top <= pos.y() <= checkbox_bottom)

    def _batch_set_check_state(self, state, selected_indexes=None):
        """Apply check state to all selected rows, skipping disabled items.

        Respects existing asymmetric propagation: uncheck cascades to children
        (handled by model's _on_item_changed), check does not.
        """
        if selected_indexes is None:
            selected_indexes = self.selectionModel().selectedRows(0)
        model = self.model()
        if not model:
            return
        for idx in selected_indexes:
            item = model.itemFromIndex(idx)
            if item and item.isEnabled():
                item.setCheckState(state)
        self.batchToggled.emit()
