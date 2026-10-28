"""
Splash screen for Flow Harvest.

Shows application branding, version information, and workflow guidance
at startup before the main window appears.
"""

import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QPushButton
from PyQt5.QtCore import Qt, QEventLoop, pyqtSignal
from PyQt5.QtGui import QFont

from ..utils.theme import get_colors


def get_version_info() -> dict:
    """
    Gather version information for all key dependencies.

    Returns:
        Dictionary with version strings for each component.
    """
    versions = {
        "Flow Harvest": "0.1.0",
        "FlowKit": "unknown",
        "PyQt5": "unknown",
        "Python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "NumPy": "unknown",
        "Pandas": "unknown",
    }

    try:
        import flowkit as fk
        versions["FlowKit"] = fk.__version__
    except (ImportError, AttributeError):
        pass

    try:
        from PyQt5.QtCore import QT_VERSION_STR
        versions["PyQt5"] = QT_VERSION_STR
    except ImportError:
        pass

    try:
        import numpy as np
        versions["NumPy"] = np.__version__
    except (ImportError, AttributeError):
        pass

    try:
        import pandas as pd
        versions["Pandas"] = pd.__version__
    except (ImportError, AttributeError):
        pass

    return versions


class SplashScreen(QWidget):
    """
    Startup splash screen with version info and workflow guidance.

    Features:
    - App branding at top
    - Workflow steps in the middle
    - Version info in muted text at bottom
    - Dismisses on button click or click anywhere
    """

    closed = pyqtSignal()  # Emitted when splash is dismissed

    def __init__(self, parent=None):
        """
        Initialize the splash screen.

        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)
        self._setup_ui()

    def _get_theme_colors(self) -> dict:
        """
        Get theme-aware colors for the splash screen.

        Returns a dictionary of color values based on the current light/dark theme.
        Brand colors (pink accents) are kept constant across themes; only surface,
        text, and border colors adapt.

        Returns:
            Dict with keys: text_primary, text_secondary, text_muted, background,
                            border, btn_bg, btn_text, btn_hover, btn_pressed.
        """
        palette = get_colors()  # auto-detects current theme

        return {
            # Adaptive colors - differ between light and dark
            "text_primary": palette["text_primary"],
            "text_secondary": palette["text_secondary"],
            "text_muted": palette["text_disabled"],
            "background": palette["background"],
            "border": palette["border"],
            # Brand/constant colors - work on both themes
            "brand_pink": "#FF69B4",
            "btn_bg": "#FF69B4",
            "btn_text": "white",
            "btn_hover": "#FF1493",
            "btn_pressed": "#DB1493",
        }

    def _setup_ui(self):
        """Set up the splash screen UI."""
        # Resolve theme-aware colors at build time
        c = self._get_theme_colors()

        # Window configuration
        self.setObjectName("splashScreen")
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(420, 380)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # App title - "Flow" in theme text color, "Joe" in brand pink
        title_label = QLabel(
            f'<span style="color: {c["text_primary"]};">Flow</span>'
            f'<span style="color: {c["brand_pink"]};">Joe</span>'
        )
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setWeight(QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("margin-bottom: 4px;")
        layout.addWidget(title_label)

        # Tagline
        tagline_label = QLabel("Your daily dose of flow")
        tagline_label.setAlignment(Qt.AlignCenter)
        tagline_font = QFont()
        tagline_font.setPointSize(11)
        tagline_label.setFont(tagline_font)
        tagline_label.setStyleSheet(f"color: {c['text_secondary']}; margin-bottom: 20px;")
        layout.addWidget(tagline_label)

        # Workflow section header
        workflow_header = QLabel("Getting Started")
        workflow_header.setAlignment(Qt.AlignLeft)
        workflow_header_font = QFont()
        workflow_header_font.setPointSize(13)
        workflow_header_font.setWeight(QFont.DemiBold)
        workflow_header.setFont(workflow_header_font)
        workflow_header.setStyleSheet(
            f"color: {c['text_primary']}; margin-top: 8px; margin-bottom: 12px;"
        )
        layout.addWidget(workflow_header)

        # Workflow steps
        workflow_steps = [
            ("1.", "Open a FlowJo workspace (.wsp) file"),
            ("2.", "Select the FCS file directory when prompted"),
            ("3.", "Choose gates and markers for analysis"),
            ("4.", "Export statistics to Excel"),
        ]

        for number, text in workflow_steps:
            step_layout = QVBoxLayout()
            step_layout.setContentsMargins(0, 0, 0, 8)
            step_layout.setSpacing(0)

            step_label = QLabel(
                f'<span style="color: {c["brand_pink"]}; font-weight: 600;">{number}</span> {text}'
            )
            step_label.setAlignment(Qt.AlignLeft)
            step_font = QFont()
            step_font.setPointSize(11)
            step_label.setFont(step_font)
            step_label.setStyleSheet(f"color: {c['text_primary']};")
            step_label.setWordWrap(True)

            layout.addWidget(step_label)

        # Spacer
        layout.addStretch()

        # Version info section
        versions = get_version_info()
        version_parts = [f"{name} {ver}" for name, ver in versions.items()]
        version_text = " | ".join(version_parts[:3])  # First line: GUI, FlowKit, PyQt5
        version_text_2 = " | ".join(version_parts[3:])  # Second line: Python, NumPy, Pandas

        version_label = QLabel(version_text)
        version_label.setAlignment(Qt.AlignCenter)
        version_font = QFont()
        version_font.setPointSize(9)
        version_label.setFont(version_font)
        version_label.setStyleSheet(f"color: {c['text_muted']}; margin-top: 12px;")
        layout.addWidget(version_label)

        version_label_2 = QLabel(version_text_2)
        version_label_2.setAlignment(Qt.AlignCenter)
        version_label_2.setFont(version_font)
        version_label_2.setStyleSheet(f"color: {c['text_muted']}; margin-top: 2px;")
        layout.addWidget(version_label_2)

        # Get Started button
        get_started_btn = QPushButton("Get Started")
        get_started_btn.setObjectName("getStartedButton")
        get_started_btn.clicked.connect(self.close)
        get_started_btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(get_started_btn)

        # Click hint
        hint_label = QLabel("or click anywhere to continue")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_font = QFont()
        hint_font.setPointSize(9)
        hint_font.setItalic(True)
        hint_label.setFont(hint_font)
        hint_label.setStyleSheet(f"color: {c['text_muted']}; margin-top: 8px;")
        layout.addWidget(hint_label)

        # Apply card styling with theme-aware surface and border colors
        self.setStyleSheet(f"""
            #splashScreen {{
                background-color: {c['background']};
                border: 1px solid {c['border']};
                border-radius: 12px;
            }}
            #getStartedButton {{
                background-color: {c['btn_bg']};
                color: {c['btn_text']};
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 13px;
                margin-top: 16px;
            }}
            #getStartedButton:hover {{
                background-color: {c['btn_hover']};
            }}
            #getStartedButton:pressed {{
                background-color: {c['btn_pressed']};
            }}
        """)

    def mousePressEvent(self, event):
        """Handle mouse click to dismiss."""
        self.close()

    def keyPressEvent(self, event):
        """Handle key press to dismiss."""
        self.close()

    def showEvent(self, event):
        """Center the splash screen and bring to focus."""
        super().showEvent(event)
        self._center_on_screen()
        self.raise_()
        self.activateWindow()

        # macOS-specific: Bring app to foreground
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except ImportError:
            pass  # Not on macOS or PyObjC unavailable

    def _center_on_screen(self):
        """Center the widget on the primary screen."""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            x = (screen_geometry.width() - self.width()) // 2 + screen_geometry.x()
            y = (screen_geometry.height() - self.height()) // 2 + screen_geometry.y()
            self.move(x, y)

    def wait_for_close(self):
        """Block until the splash screen is closed (by timeout or user interaction)."""
        loop = QEventLoop()
        self.closed.connect(loop.quit)
        loop.exec_()

    def close(self):
        """Override close to emit the closed signal."""
        self.closed.emit()
        super().close()
