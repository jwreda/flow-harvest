"""
Memory-bounded LRU cache for large numpy arrays.

This module provides caching infrastructure optimized for flow cytometry data,
where event arrays can be hundreds of megabytes each. The cache automatically
evicts least-recently-used entries when memory limits are exceeded.
"""

from collections import OrderedDict
from typing import Any, Optional, TypeVar, Generic
import sys
import threading
import numpy as np

from .logging_config import get_logger

logger = get_logger("cache")

T = TypeVar('T')


class MemoryBoundedLRUCache(Generic[T]):
    """
    LRU cache with memory limit for numpy arrays and other large objects.

    This cache tracks memory usage and automatically evicts the least-recently-used
    entries when the memory limit would be exceeded by a new insertion.

    Attributes:
        max_bytes: Maximum memory (in bytes) the cache is allowed to use
        current_bytes: Current memory usage of all cached items
    """

    def __init__(self, max_bytes: int = 4 * 1024**3):
        """
        Initialize the cache with a memory limit.

        Args:
            max_bytes: Maximum memory in bytes (default 4GB)
        """
        self._cache: OrderedDict[str, T] = OrderedDict()
        self._lock = threading.Lock()
        self._max_bytes = max_bytes
        self._current_bytes = 0
        self._eviction_count = 0

    def _estimate_size(self, value: Any) -> int:
        """
        Estimate memory size of a cached value.

        Args:
            value: The value to measure

        Returns:
            Estimated size in bytes
        """
        if isinstance(value, np.ndarray):
            return value.nbytes
        if isinstance(value, tuple):
            # Handle (array, labels) tuples from channel-selective loading
            total = 0
            for item in value:
                if isinstance(item, np.ndarray):
                    total += item.nbytes
                else:
                    total += sys.getsizeof(item)
            return total
        return sys.getsizeof(value)

    def get(self, key: str) -> Optional[T]:
        """
        Retrieve an item from the cache.

        This also marks the item as recently used (moves to end of LRU queue).

        Args:
            key: The cache key

        Returns:
            The cached value, or None if not found
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)  # Mark as recently used
                return self._cache[key]
            return None

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        with self._lock:
            return key in self._cache

    def put(self, key: str, value: T) -> None:
        """
        Insert or update an item in the cache.

        If the item would exceed the memory limit, the least-recently-used
        items are evicted until there's room.

        Args:
            key: The cache key
            value: The value to cache
        """
        size = self._estimate_size(value)

        # If this single item is larger than max, don't cache it
        if size > self._max_bytes:
            logger.warning(
                f"Item too large to cache ({size / 1024**2:.1f}MB > {self._max_bytes / 1024**2:.1f}MB limit): {key}"
            )
            return

        with self._lock:
            # Evict oldest entries until we have space
            while self._current_bytes + size > self._max_bytes and self._cache:
                oldest_key, oldest_value = self._cache.popitem(last=False)
                evicted_size = self._estimate_size(oldest_value)
                self._current_bytes -= evicted_size
                self._eviction_count += 1
                logger.debug(
                    f"LRU evicted '{oldest_key}' ({evicted_size / 1024**2:.1f}MB), "
                    f"freed {evicted_size / 1024**2:.1f}MB"
                )

            # If key already exists, remove its size first
            if key in self._cache:
                old_size = self._estimate_size(self._cache[key])
                self._current_bytes -= old_size

            # Insert new item
            self._cache[key] = value
            self._cache.move_to_end(key)
            self._current_bytes += size

            logger.debug(
                f"Cached '{key}' ({size / 1024**2:.1f}MB), "
                f"total: {self._current_bytes / 1024**2:.1f}MB / {self._max_bytes / 1024**2:.1f}MB"
            )

    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            item_count = len(self._cache)
            self._cache.clear()
            self._current_bytes = 0
            if item_count > 0:
                logger.info(f"Cleared {item_count} cached items")

    @property
    def memory_usage_mb(self) -> float:
        """Current memory usage in megabytes."""
        return self._current_bytes / (1024**2)

    @property
    def memory_limit_mb(self) -> float:
        """Memory limit in megabytes."""
        return self._max_bytes / (1024**2)

    @property
    def utilization(self) -> float:
        """Cache utilization as a fraction (0.0 to 1.0)."""
        if self._max_bytes == 0:
            return 0.0
        return self._current_bytes / self._max_bytes

    @property
    def eviction_count(self) -> int:
        """Total number of evictions since cache creation."""
        return self._eviction_count

    def __len__(self) -> int:
        """Number of items in the cache."""
        return len(self._cache)

    def __repr__(self) -> str:
        return (
            f"MemoryBoundedLRUCache("
            f"items={len(self)}, "
            f"usage={self.memory_usage_mb:.1f}MB/{self.memory_limit_mb:.1f}MB, "
            f"evictions={self._eviction_count})"
        )
