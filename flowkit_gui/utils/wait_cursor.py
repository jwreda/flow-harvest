"""
Wait Cursor Utility - Context manager for showing wait cursor during long operations.

This module provides a simple context manager that:
- Shows a wait cursor when entering the context
- Processes events to ensure cursor updates immediately
- Restores the original cursor when exiting
"""

from contextlib import contextmanager
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


@contextmanager
def wait_cursor():
    """
    Context manager to show a wait cursor during long operations.

    Usage:
        with wait_cursor():
            # Long operation here
            do_something_slow()

    The cursor is automatically restored when exiting the context,
    even if an exception occurs.
    """
    try:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        yield
    finally:
        QApplication.restoreOverrideCursor()
