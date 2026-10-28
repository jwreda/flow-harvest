"""
Flow Harvest - Main entry point.

A tool for extracting and analyzing flow cytometry data from FlowJo workspaces.
"""

import sys
import platform

# Minimum FlowKit version for full functionality
MIN_FLOWKIT_VERSION = "1.0.0"


def check_flowkit_version():
    """
    Check if FlowKit version meets minimum requirements.

    Returns:
        Tuple of (is_ok, message). is_ok is True if version is sufficient.
    """
    try:
        import flowkit as fk
        from packaging import version

        current = fk.__version__
        if version.parse(current) < version.parse(MIN_FLOWKIT_VERSION):
            return False, (
                f"FlowKit {current} is older than recommended version {MIN_FLOWKIT_VERSION}. "
                f"Some features (like keyword extraction) may not work. "
                f"Consider upgrading: pip install --upgrade FlowKit"
            )
        return True, None
    except ImportError:
        # packaging module not available - skip version check
        return True, None
    except Exception as e:
        # If we can't check, assume it's ok
        return True, None


def _install_global_exception_handler(app):
    """Install global exception handler for uncaught exceptions.

    Provides user-friendly crash dialog, crash log file, and
    copy-to-clipboard functionality instead of silent crashes.
    """
    import traceback
    import platform
    from datetime import datetime
    from pathlib import Path

    def exception_hook(exc_type, exc_value, exc_traceback):
        # Don't catch KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # Format exception
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        error_summary = f"{exc_type.__name__}: {exc_value}"

        error_details = (
            f"Flow Harvest Crash Report\n"
            f"{'=' * 60}\n"
            f"Time: {timestamp}\n"
            f"Version: {app.applicationVersion()}\n"
            f"Platform: {platform.system()} {platform.release()}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"\n{tb_text}"
        )

        # Write to crash log
        crash_log_dir = Path.home() / ".flowkit_gui"
        crash_log_dir.mkdir(exist_ok=True)
        crash_log_path = crash_log_dir / "flowkit_crash.log"
        try:
            with open(crash_log_path, "a") as f:
                f.write(f"\n\n{error_details}\n{'=' * 60}\n")
        except Exception:
            pass

        # Also log to debug log
        try:
            import logging
            logger = logging.getLogger("flowkit_gui")
            logger.critical(f"UNHANDLED EXCEPTION: {error_summary}\n{tb_text}")
        except Exception:
            pass

        # Show crash dialog
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton
        from PyQt5.QtCore import Qt, QTimer

        dialog = QDialog()
        dialog.setWindowTitle("Flow Harvest — Unexpected Error")
        dialog.setModal(True)
        dialog.resize(650, 450)

        layout = QVBoxLayout(dialog)

        msg = QLabel(
            f"<b>Flow Harvest encountered an unexpected error:</b><br><br>"
            f"<code>{error_summary}</code><br><br>"
            f"Error details saved to:<br>"
            f"<code>{crash_log_path}</code>"
        )
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.RichText)
        layout.addWidget(msg)

        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(error_details)
        details.setMaximumHeight(250)
        layout.addWidget(details)

        btn_layout = QHBoxLayout()

        copy_btn = QPushButton("Copy to Clipboard")
        def copy_details():
            app.clipboard().setText(error_details)
            copy_btn.setText("Copied!")
            QTimer.singleShot(2000, lambda: copy_btn.setText("Copy to Clipboard"))
        copy_btn.clicked.connect(copy_details)
        btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close Application")
        close_btn.setDefault(True)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        dialog.exec_()
        sys.exit(1)

    sys.excepthook = exception_hook


def main():
    """Application entry point."""
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import Qt, QTimer, QEventLoop
    from .views.main_window import MainWindow
    from .views.splash_screen import SplashScreen
    from .utils.theme import apply_theme

    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Flow Harvest")
    app.setOrganizationName("FlowHarvest")
    app.setOrganizationDomain("jwreda.github.io")
    app.setApplicationVersion("0.1.0")

    # Apply the pink theme with light/dark mode support
    apply_theme(app)

    # Install global exception handler for crash reporting
    _install_global_exception_handler(app)

    # macOS-specific: Activate app BEFORE showing any windows
    # This is critical when launching from scripts/Finder where app starts "in background"
    if platform.system() == 'Darwin':
        try:
            from AppKit import NSApplication, NSApp
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except ImportError:
            pass  # PyObjC not available

    # Show splash screen and wait for user to dismiss
    splash = SplashScreen()
    splash.show()

    # Ensure the splash is fully rendered before entering blocking wait
    # macOS window compositor needs multiple event loop iterations
    for _ in range(3):
        app.processEvents()
    splash.repaint()
    app.processEvents()

    # macOS-specific: Activate again and delay for compositor to finish rendering
    if platform.system() == 'Darwin':
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except ImportError:
            pass
        render_loop = QEventLoop()
        QTimer.singleShot(100, render_loop.quit)  # Increased delay
        render_loop.exec_()
        # Final raise after delay to ensure visibility
        splash.raise_()
        splash.activateWindow()
        app.processEvents()

    # Now block until user dismisses the splash
    splash.wait_for_close()

    # Check FlowKit version and warn if outdated
    version_ok, version_msg = check_flowkit_version()
    if not version_ok and version_msg:
        QMessageBox.warning(
            None,
            "FlowKit Version Warning",
            version_msg
        )

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
