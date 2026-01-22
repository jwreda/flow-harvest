"""
Config module for FlowKit GUI.

Provides centralized configuration values and constants.
"""

from .defaults import (
    SYSTEM_KEYWORD_PREFIXES,
    SYSTEM_KEYWORD_EXACT,
    SYSTEM_KEYWORD_SUFFIXES,
    CHANNEL_SUFFIXES,
    SCATTER_PREFIXES,
    FCS_MAX_SEARCH_DEPTH,
    FCS_EXTENSIONS,
    # Memory management settings
    CACHE_MEMORY_LIMIT_MB,
    BATCH_SIZE,
    GC_COLLECT_INTERVAL,
    STREAMING_EXPORT_ROW_THRESHOLD,
    MAX_PARALLEL_WORKERS,
)
