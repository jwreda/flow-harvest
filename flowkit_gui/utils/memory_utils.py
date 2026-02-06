"""Memory safety utilities for FlowKit GUI."""
import logging
import psutil

logger = logging.getLogger("flowkit_gui.memory_utils")


def get_memory_info():
    """Return (available_mb, total_mb, percent_used)."""
    mem = psutil.virtual_memory()
    return mem.available // (1024**2), mem.total // (1024**2), mem.percent


def check_memory_available(required_mb, operation_name="operation"):
    """Check if sufficient memory is available. Returns True if OK."""
    available_mb, total_mb, percent_used = get_memory_info()
    safe_available = available_mb * 0.8
    if required_mb > safe_available:
        logger.warning(
            f"Insufficient memory for {operation_name}: "
            f"~{required_mb}MB needed, {available_mb}MB available "
            f"({percent_used:.1f}% used)"
        )
        return False
    return True


def estimate_export_memory(num_samples, num_gates, avg_events=50000):
    """Estimate MB required for statistics export."""
    stats_mb = (num_samples * num_gates * 10 * 8) / (1024**2)
    event_mb = (avg_events * 40 * 8) / (1024**2)
    return int((stats_mb * 3 + event_mb) * 1.5)
