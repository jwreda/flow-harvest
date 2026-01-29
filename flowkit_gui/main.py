"""
FlowKit GUI - Main entry point.

A tool for extracting and analyzing flow cytometry data from FlowJo workspaces.
"""

import sys
import platform

# Minimum FlowKit version for full functionality
MIN_FLOWKIT_VERSION = "1.0.0"


def ensure_dependencies():
    """
    Check for and install missing optional dependencies.

    This ensures packages like natsort are available even if the user
    hasn't updated their environment after a FlowKit GUI update.
    """
    import subprocess

    dependencies = [
        ("natsort", "natsort>=8.0.0"),  # (import_name, pip_package)
    ]

    for import_name, pip_package in dependencies:
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installing missing dependency: {pip_package}")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_package],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print(f"Successfully installed {pip_package}")
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to install {pip_package}: {e}")


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


def main():
    """Application entry point."""
    # Ensure all dependencies are installed before importing modules that need them
    ensure_dependencies()

    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import Qt, QTimer, QEventLoop
    from .views.main_window import MainWindow
    from .views.splash_screen import SplashScreen
    from .utils.theme import apply_theme

    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("FlowJoe")
    app.setOrganizationName("FlowKit")
    app.setOrganizationDomain("flowkit.io")
    app.setApplicationVersion("0.1.0")

    # Apply the pink theme with light/dark mode support
    apply_theme(app)

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
