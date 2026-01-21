"""
Custom styled delegate for tree view items with selection accent bar.
"""

from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtCore import Qt, QRect


class AccentedTreeItemDelegate(QStyledItemDelegate):
    """
    Tree item delegate that draws a 3px accent bar on selected items.

    The accent bar appears on the left side of selected items,
    providing a clear visual indicator of selection.
    """

    # Colors from the Deep Rose palette
    SELECTION_COLOR = "#FFDBE8"  # Rose Tint
    ACCENT_COLOR = "#E91E8C"     # Deep Rose
    HOVER_COLOR = "#FFF0F5"      # Light Blush

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        """Paint the item with custom selection/hover styling."""
        painter.save()

        # Check states
        is_selected = option.state & QStyle.State_Selected
        is_hovered = option.state & QStyle.State_MouseOver

        # Draw background based on state
        if is_selected:
            # Selection background
            painter.fillRect(option.rect, QColor(self.SELECTION_COLOR))

            # 3px accent bar on left
            accent_rect = QRect(
                option.rect.left(),
                option.rect.top(),
                3,
                option.rect.height()
            )
            painter.fillRect(accent_rect, QColor(self.ACCENT_COLOR))

        elif is_hovered:
            # Hover background
            painter.fillRect(option.rect, QColor(self.HOVER_COLOR))

        painter.restore()

        # Call base class to draw the item content (text, icon, etc.)
        super().paint(painter, option, index)
