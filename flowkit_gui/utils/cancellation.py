"""
Cancellation support for long-running operations.

This module provides a thread-safe cancellation mechanism that allows
users to interrupt export operations, sample analysis, and other
time-consuming tasks without losing data or corrupting state.
"""

import threading
from typing import Optional


class CancellationError(Exception):
    """Raised when an operation is cancelled by the user."""

    def __init__(self, message: str = "Operation cancelled by user"):
        super().__init__(message)
        self.message = message


class CancellationToken:
    """
    Thread-safe cancellation token for long-running operations.

    Usage:
        # Create token
        token = CancellationToken()

        # In worker thread, check periodically
        for item in items:
            token.check_cancelled()  # Raises CancellationError if cancelled
            process(item)

        # From main thread, cancel the operation
        token.cancel()

    The token can be passed to functions that support cancellation,
    allowing the user to interrupt operations gracefully.
    """

    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()
        self._cancel_message: Optional[str] = None

    def cancel(self, message: Optional[str] = None) -> None:
        """
        Request cancellation of the operation.

        This is thread-safe and can be called from any thread.

        Args:
            message: Optional message explaining why cancellation was requested
        """
        with self._lock:
            self._cancelled = True
            self._cancel_message = message

    @property
    def is_cancelled(self) -> bool:
        """
        Check if cancellation has been requested.

        This is thread-safe and can be called from any thread.

        Returns:
            True if cancel() has been called, False otherwise
        """
        with self._lock:
            return self._cancelled

    @property
    def cancel_message(self) -> Optional[str]:
        """Get the cancellation message, if any."""
        with self._lock:
            return self._cancel_message

    def check_cancelled(self) -> None:
        """
        Check if cancelled and raise CancellationError if so.

        This is a convenience method for operations that want to
        abort immediately when cancelled.

        Raises:
            CancellationError: If cancellation has been requested
        """
        if self.is_cancelled:
            message = self.cancel_message or "Operation cancelled by user"
            raise CancellationError(message)

    def reset(self) -> None:
        """
        Reset the token to non-cancelled state.

        This allows reusing the same token for multiple operations,
        though creating a new token is generally preferred.
        """
        with self._lock:
            self._cancelled = False
            self._cancel_message = None

    def __repr__(self) -> str:
        status = "cancelled" if self.is_cancelled else "active"
        return f"CancellationToken({status})"
