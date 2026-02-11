"""
Custom styled delegate for gate tree view with colored depth dots.

This module provides a delegate that renders:
- Colored depth dots using the Okabe-Ito colorblind-friendly palette
- Selection/hover styling with accent bar (like AccentedTreeItemDelegate)
- Checkbox and gate name text
"""

from PyQt5.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionButton, QApplication
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen, QPalette
from PyQt5.QtCore import Qt, QRect, QSize

from .gate_marker_matrix_view import DEPTH_COLORS
from ..utils.theme import get_colors


class ColoredGateTreeDelegate(QStyledItemDelegate):
    """
    Tree item delegate that draws colored depth dots before gate names.

    Uses the Okabe-Ito colorblind-friendly palette where each position in the
    hierarchy gets a distinct color: depth 3 shows pink + orange + amber dots.

    Also provides selection/hover accent styling.
    """

    # Accent color (same in both themes)
    ACCENT_COLOR = "#E91E8C"     # Deep Rose

    # Dot styling (matching ColoredDepthHeaderView)
    DOT_SIZE = 8
    DOT_SPACING = 2
    TEXT_MARGIN = 6

    # Data role for depth
    DEPTH_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option, index):
        """Paint the item with colored depth dots and accent styling."""
        painter.save()
        painter.setClipRect(option.rect)  # Clip all drawing to cell boundaries

        # Only apply custom rendering to the gate name column (column 0)
        if index.column() != 0:
            # Draw themed background for columns 1-3 (matching column 0)
            colors = get_colors()
            is_selected = option.state & QStyle.State_Selected
            is_hovered = option.state & QStyle.State_MouseOver

            if is_selected:
                painter.fillRect(option.rect, QColor(colors["selection"]))
            elif is_hovered:
                painter.fillRect(option.rect, QColor(colors["hover"]))
            else:
                alt_row_color = colors.get("alt_row", "#FFF5F8")
                bg_color = colors.get("background", "#FFFFFF")
                if index.row() % 2 == 0:
                    painter.fillRect(option.rect, QColor(bg_color))
                else:
                    painter.fillRect(option.rect, QColor(alt_row_color))

            painter.restore()

            # Set palette text color for theme awareness
            text_color = QColor(colors.get("text_primary", "#333333"))
            option.palette.setColor(QPalette.Text, text_color)
            option.palette.setColor(QPalette.WindowText, text_color)
            super().paint(painter, option, index)
            return

        # Check states
        is_selected = option.state & QStyle.State_Selected
        is_hovered = option.state & QStyle.State_MouseOver
        is_enabled = option.state & QStyle.State_Enabled

        # Get theme-aware colors
        colors = get_colors()
        selection_color = colors["selection"]
        hover_color = colors["hover"]

        # ALWAYS draw background to prevent QSS/alternating colors from overwriting content
        # This is critical for the depth dots to be visible
        if is_selected:
            painter.fillRect(option.rect, QColor(selection_color))
            # 3px accent bar on left
            accent_rect = QRect(
                option.rect.left(),
                option.rect.top(),
                3,
                option.rect.height()
            )
            painter.fillRect(accent_rect, QColor(self.ACCENT_COLOR))
        elif is_hovered:
            painter.fillRect(option.rect, QColor(hover_color))
        else:
            # Draw normal background with alternating colors
            alt_row_color = colors.get("alt_row", "#FFF5F8")
            bg_color = colors.get("background", "#FFFFFF")
            if index.row() % 2 == 0:
                painter.fillRect(option.rect, QColor(bg_color))
            else:
                painter.fillRect(option.rect, QColor(alt_row_color))

        # Get depth from item data
        depth = index.data(self.DEPTH_ROLE)
        if depth is None:
            depth = 0

        # Calculate positions
        rect = option.rect
        x_pos = rect.x() + 4  # Start position
        y_center = rect.y() + rect.height() // 2

        # Draw checkbox first
        checkbox_size = 16
        checkbox_rect = QRect(x_pos, y_center - checkbox_size // 2, checkbox_size, checkbox_size)

        check_state = index.data(Qt.CheckStateRole)
        if check_state is not None:
            opt = QStyleOptionButton()
            opt.rect = checkbox_rect
            opt.state = QStyle.State_Enabled if is_enabled else QStyle.State_None
            if check_state == Qt.Checked:
                opt.state |= QStyle.State_On
            elif check_state == Qt.PartiallyChecked:
                opt.state |= QStyle.State_NoChange
            else:
                opt.state |= QStyle.State_Off
            QApplication.style().drawControl(QStyle.CE_CheckBox, opt, painter)
            x_pos = checkbox_rect.right() + 6

        # Draw colored depth dots
        if depth > 0:
            for i in range(depth):
                color_idx = i % len(DEPTH_COLORS)
                dot_color = QColor(DEPTH_COLORS[color_idx])

                # Gray out dots if item is disabled
                if not is_enabled:
                    dot_color.setAlpha(100)

                painter.setBrush(QBrush(dot_color))
                painter.setPen(Qt.NoPen)
                dot_x = x_pos + i * (self.DOT_SIZE + self.DOT_SPACING)
                dot_y = y_center - self.DOT_SIZE // 2
                painter.drawEllipse(dot_x, dot_y, self.DOT_SIZE, self.DOT_SIZE)

            x_pos += depth * (self.DOT_SIZE + self.DOT_SPACING) + self.TEXT_MARGIN

        # Draw gate name text
        text = index.data(Qt.DisplayRole)
        if text:
            text_color = QColor(colors.get("text_primary", "#333333"))
            if not is_enabled:
                text_color.setAlpha(100)

            painter.setPen(text_color)
            font = painter.font()
            painter.setFont(font)

            text_rect = QRect(
                x_pos,
                rect.y(),
                rect.width() - x_pos + rect.x() - 4,
                rect.height()
            )
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(text))

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        """Return size hint with extra width for depth dots."""
        base = super().sizeHint(option, index)

        # Get depth to calculate required width
        depth = index.data(self.DEPTH_ROLE)
        if depth is None:
            depth = 0

        # Add width for dots
        dots_width = depth * (self.DOT_SIZE + self.DOT_SPACING) + self.TEXT_MARGIN if depth > 0 else 0

        return QSize(base.width() + dots_width, max(base.height(), 24))
