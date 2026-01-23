"""
Timing utilities for performance monitoring and diagnostics.

This module provides:
- PipelineTimer for tracking timing across multiple pipeline steps
- timed_operation context manager for individual operations
"""

import time
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Optional, Generator

from .logging_config import get_logger

logger = get_logger("timing")


class PipelineTimer:
    """
    Track timing across multiple pipeline steps.

    Usage:
        timer = PipelineTimer("Excel Export")
        timer.start()

        with timer.step("Write gating strategy"):
            write_gating_strategy(...)

        with timer.step("Calculate statistics"):
            calculate_statistics(...)

        timer.summary(cache_stats=workspace.get_cache_stats())
    """

    def __init__(self, pipeline_name: str):
        """
        Initialize the timer.

        Args:
            pipeline_name: Descriptive name for the pipeline being timed
        """
        self.pipeline_name = pipeline_name
        self.steps: Dict[str, float] = {}
        self.start_time: Optional[float] = None

    def start(self) -> None:
        """Start the pipeline timer."""
        self.start_time = time.perf_counter()
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] === Starting {self.pipeline_name} ===")

    @contextmanager
    def step(self, step_name: str) -> Generator[None, None, None]:
        """
        Time a single step within the pipeline.

        Args:
            step_name: Descriptive name for this step

        Yields:
            None - use as context manager
        """
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] Starting {step_name}...")
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.steps[step_name] = elapsed
            ts = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[{ts}] {step_name} complete ({elapsed:.1f}s)")

    def summary(self, cache_stats: Optional[Dict[str, float]] = None) -> None:
        """
        Log a summary of all timed steps.

        Args:
            cache_stats: Optional dict with cache memory usage stats
                        (keys: 'event', 'membership' with values in MB)
        """
        if self.start_time is None:
            logger.warning("PipelineTimer.summary() called without start()")
            return

        total = time.perf_counter() - self.start_time
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] === {self.pipeline_name} Complete ({total:.1f}s) ===")

        for step_name, elapsed in self.steps.items():
            pct = (elapsed / total * 100) if total > 0 else 0
            logger.info(f"  - {step_name}: {elapsed:.1f}s ({pct:.0f}%)")

        if cache_stats:
            event_mb = cache_stats.get('event', 0)
            membership_mb = cache_stats.get('membership', 0)
            logger.info(f"  Cache: event={event_mb:.0f}MB, membership={membership_mb:.0f}MB")

    def get_total_elapsed(self) -> float:
        """Get total elapsed time since start() was called."""
        if self.start_time is None:
            return 0.0
        return time.perf_counter() - self.start_time


@contextmanager
def timed_operation(operation_name: str, context: str = "") -> Generator[None, None, None]:
    """
    Context manager for timing a single operation.

    Args:
        operation_name: Name of the operation being timed
        context: Optional additional context to log (e.g., "14 samples, 34 gates")

    Yields:
        None - use as context manager

    Example:
        with timed_operation("Statistics calculation", "14 samples, 34 gates"):
            calculate_statistics(...)
    """
    ts = datetime.now().strftime("%H:%M:%S")
    msg = f"[{ts}] Starting {operation_name}"
    if context:
        msg += f" - {context}"
    logger.info(msg + "...")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] {operation_name} complete ({elapsed:.1f}s)")
