"""
Workspace Model - FlowKit wrapper for WSP/FCS file handling.

This module provides the core integration with FlowKit library for:
- Loading FlowJo workspace (WSP) files
- Handling FCS file path remapping
- Extracting gate hierarchies
- Extracting sample keywords
- Running gate analysis
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set, Callable
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
import multiprocessing
import re
import threading
from lxml import etree
import flowkit as fk
from flowkit import Matrix as FKMatrix
import pandas as pd
import numpy as np
from natsort import natsorted, ns

from ..utils.logging_config import get_logger
from ..utils.cache import MemoryBoundedLRUCache
from ..utils.cancellation import CancellationToken, CancellationError
from .wsp_metadata_parser import WSPMetadataParser, WSPMetadata
from ..config import (
    SYSTEM_KEYWORD_PREFIXES,
    SYSTEM_KEYWORD_EXACT,
    SYSTEM_KEYWORD_SUFFIXES,
    CACHE_MEMORY_LIMIT_MB,
)

logger = get_logger("workspace_model")


class CompensationError(Exception):
    """Raised when required compensation cannot be applied or is missing."""
    pass


def _extract_dimension_id(dim_str: str) -> str:
    """Extract ID from 'Dimension(id: VALUE)' format.

    Args:
        dim_str: String representation of a FlowKit Dimension object

    Returns:
        The extracted ID value, or the original string if pattern doesn't match
    """
    match = re.search(r'Dimension\(id:\s*(.+?)\)', dim_str)
    return match.group(1) if match else dim_str


class DataSource(Enum):
    """Event data source options."""
    AUTO = "auto"      # Try compensated, fallback to raw
    RAW = "raw"        # Force raw/uncompensated
    COMP = "comp"      # Force compensated only


@dataclass
class Sample:
    """Represents an FCS sample with associated metadata."""
    sample_id: str
    name: str
    fcs_path: Optional[Path]
    group: str
    keywords: Dict[str, str] = field(default_factory=dict)
    event_count: int = 0

    def get_custom_keywords(
        self,
        include_system_keywords: Optional[Set[str]] = None
    ) -> Dict[str, str]:
        """
        Returns only user-defined keywords, filtering out system keys.

        Args:
            include_system_keywords: Optional set of system keyword names to include
                                    even though they would normally be filtered out.
                                    For example, {'$VOL', '$DATE'} to include those
                                    keywords in the output. Default is None (filter all).

        Returns:
            Dict of keyword name to value for non-system keywords
            (plus any explicitly included system keywords).
        """
        if include_system_keywords is None:
            include_system_keywords = set()

        result = {}
        for k, v in self.keywords.items():
            # Check if explicitly included (before filtering)
            if k in include_system_keywords or k.upper() in {s.upper() for s in include_system_keywords}:
                result[k] = v
                continue

            # Skip if starts with system prefix
            if any(k.upper().startswith(prefix) for prefix in SYSTEM_KEYWORD_PREFIXES):
                continue
            # Skip if exact match to system key
            if k.upper() in SYSTEM_KEYWORD_EXACT or k in SYSTEM_KEYWORD_EXACT:
                continue
            # Skip if ends with system suffix
            if any(k.upper().endswith(suffix) for suffix in SYSTEM_KEYWORD_SUFFIXES):
                continue
            # Keep this keyword
            result[k] = v

        return result


@dataclass
class GateInfo:
    """Information about a gate extracted from the workspace."""
    gate_id: str
    name: str
    path: Tuple[str, ...]  # Full path from root
    gate_type: str
    parent_id: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    fk_gate_path: Tuple[str, ...] = ()  # FlowKit's gate_path tuple for API calls

    @property
    def full_path_string(self) -> str:
        """Returns path as 'Cells/Single Cells/Live/CD45+'"""
        return "/".join(self.path)

    @property
    def depth(self) -> int:
        """Returns hierarchy depth (0 = root)"""
        return len(self.path) - 1

    @property
    def bullet_prefix(self) -> str:
        """Returns bullet prefix for this depth (e.g., '●●●' for depth 3)."""
        return "●" * self.depth

    @property
    def compact_display(self) -> str:
        """Returns compact display: ●●●CD4+ for depth 3 gate named CD4+."""
        if self.depth == 0:
            return self.name
        return f"{'●' * self.depth}{self.name}"

    @property
    def hierarchical_path_string(self) -> str:
        """Returns 'Live, ●CD45+, ●●CD3+, ●●●CD4+CD8-' format."""
        parts = []
        for i, gate_name in enumerate(self.path):
            if i == 0:
                parts.append(gate_name)
            else:
                parts.append(f"{'●' * i}{gate_name}")
        return ", ".join(parts)


@dataclass
class ChannelInfo:
    """Information about a fluorescence channel."""
    pnn_label: str       # Fluorophore name (e.g., "BUV496-A")
    pns_label: str       # Reagent/stain name (e.g., "CD4"), may be empty

    @property
    def display_name(self) -> str:
        """Returns 'CD4 [BUV496-A]' or 'BUV496-A' if no reagent name."""
        if self.pns_label:
            return f"{self.pns_label} [{self.pnn_label}]"
        return self.pnn_label


@dataclass
class CompensationMatrixInfo:
    """Information about a compensation matrix from the WSP file."""
    name: str                    # Human-readable name (e.g., "Compensation-copy")
    matrix_id: str               # UUID from transforms:id attribute
    color: str                   # Hex color for display (e.g., "#00ccff")
    spectral: bool               # True if spectral (OLS-based), False if conventional
    detectors: List[str] = field(default_factory=list)  # Channel labels
    editable: bool = False       # Whether matrix is user-editable
    status: str = ""             # Processing status (e.g., "FINALIZED")


@dataclass
class SampleCompensationAssignment:
    """Compensation assignment for a single sample."""
    matrix_name: Optional[str]   # Name of assigned matrix, or None if no compensation
    matrix_id: Optional[str]     # UUID of assigned matrix
    color: Optional[str]         # Color of assigned matrix (for UI display)
    spectral: Optional[bool]     # Whether assigned matrix is spectral


class WorkspaceModel:
    """
    Main model for loading and interacting with FlowJo workspaces.

    This class wraps FlowKit's Workspace class and provides methods for:
    - Loading WSP files with optional FCS path remapping
    - Extracting gate hierarchy
    - Extracting sample keywords
    - Running analysis and calculating statistics
    """

    def __init__(self):
        self._workspace: Optional[fk.Workspace] = None
        self._wsp_path: Optional[Path] = None
        self._fcs_dir: Optional[Path] = None
        self._samples: List[Sample] = []
        self._sample_by_id: Dict[str, Sample] = {}
        self._gates: List[GateInfo] = []
        self._gate_by_id: Dict[str, GateInfo] = {}
        self._fk_gate_path_by_id: Dict[str, Tuple[str, ...]] = {}
        self._parent_gate_by_id: Dict[str, Optional[str]] = {}
        self._channels: List[str] = []
        self._channel_info: List[ChannelInfo] = []
        # Track which gates exist in which samples (not all gates exist in all samples)
        self._sample_gates: Dict[str, Set[str]] = {}  # sample_id -> set of gate_ids
        # Memory-bounded LRU caches for performance optimization
        # Split configured memory limit: 70% for events, 30% for membership
        cache_bytes = CACHE_MEMORY_LIMIT_MB * 1024 * 1024
        self._event_cache: MemoryBoundedLRUCache = MemoryBoundedLRUCache(
            max_bytes=int(cache_bytes * 0.7)
        )
        self._membership_cache: MemoryBoundedLRUCache = MemoryBoundedLRUCache(
            max_bytes=int(cache_bytes * 0.3)
        )
        # Track which samples have been analyzed (for on-demand analysis)
        self._analyzed_samples: Set[str] = set()
        self._analyzed_samples_lock = threading.Lock()
        # Track samples that failed analysis (sample_id -> error message)
        self._failed_samples: Dict[str, str] = {}
        self._failed_samples_lock = threading.Lock()
        # Lock to serialize compensation retry (mutates shared gating_strategy)
        self._comp_retry_lock = threading.Lock()
        # Lock to serialize FlowKit workspace.analyze_samples() calls (not thread-safe)
        self._workspace_analysis_lock = threading.Lock()
        # Track which samples have had compensation applied
        self._samples_with_compensation_applied: Set[str] = set()
        self._compensation_lock = threading.Lock()
        # Two-phase loading state
        self._metadata_only: bool = False
        self._wsp_metadata: Optional[WSPMetadata] = None
        logger.info(
            f"Initialized caches: event={self._event_cache.memory_limit_mb:.0f}MB, "
            f"membership={self._membership_cache.memory_limit_mb:.0f}MB"
        )

    def _rebuild_sample_lookup(self) -> None:
        """Rebuild fast sample lookup map from the current sample list."""
        self._sample_by_id = {sample.sample_id: sample for sample in self._samples}

    def _rebuild_gate_lookups(self) -> None:
        """Rebuild fast gate lookup maps from the current gate list."""
        self._gate_by_id = {}
        self._fk_gate_path_by_id = {}
        self._parent_gate_by_id = {}

        for gate in self._gates:
            self._gate_by_id[gate.gate_id] = gate
            self._fk_gate_path_by_id[gate.gate_id] = gate.fk_gate_path
            if gate.parent_id is not None:
                parent_id = gate.parent_id
            elif len(gate.path) > 1:
                parent_id = "/".join(gate.path[:-1])
            else:
                parent_id = None
            self._parent_gate_by_id[gate.gate_id] = parent_id

    @property
    def is_loaded(self) -> bool:
        """Returns True if a workspace is currently loaded."""
        return self._workspace is not None

    @property
    def samples(self) -> List[Sample]:
        """Returns list of samples in the workspace."""
        return self._samples

    @property
    def gates(self) -> List[GateInfo]:
        """Returns list of gates in the workspace."""
        return self._gates

    @property
    def channels(self) -> List[str]:
        """Returns list of fluorescence channels available."""
        return self._channels

    @property
    def channel_info(self) -> List[ChannelInfo]:
        """Returns list of ChannelInfo with fluorophore and reagent names."""
        return self._channel_info

    @property
    def wsp_path(self) -> Optional[Path]:
        """Returns the path to the loaded WSP file."""
        return self._wsp_path

    def clear_data_cache(self) -> None:
        """Clear cached event and membership data to free memory, preserving analysis state."""
        event_count = len(self._event_cache)
        membership_count = len(self._membership_cache)
        event_evictions = self._event_cache.eviction_count
        membership_evictions = self._membership_cache.eviction_count

        self._event_cache.clear()
        self._membership_cache.clear()
        gc.collect()  # Force garbage collection to release memory

        total_items = event_count + membership_count
        if total_items > 0:
            logger.info(
                f"Cleared {total_items} cached items "
                f"(events={event_count}, membership={membership_count}, "
                f"prior evictions: events={event_evictions}, membership={membership_evictions})"
            )

    def clear_cache(self) -> None:
        """Clear all cached data AND analysis tracking (full reset)."""
        self.clear_data_cache()
        with self._analyzed_samples_lock:
            self._analyzed_samples.clear()
        with self._failed_samples_lock:
            self._failed_samples.clear()
        logger.info("Full cache clear: analysis and failure tracking also reset")

    def get_cache_stats(self) -> Dict[str, float]:
        """
        Get current cache memory usage statistics.

        Returns:
            Dict with 'event' and 'membership' keys containing memory usage in MB
        """
        return {
            'event': self._event_cache.memory_usage_mb,
            'membership': self._membership_cache.memory_usage_mb,
        }

    def apply_compensation_to_samples(
        self,
        sample_ids: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, str]:
        """
        Apply compensation matrices to samples.

        This method applies the compensation matrix assigned to each sample
        in FlowJo. After calling this, compensated event data can be retrieved
        using get_gated_events() with DataSource.COMP.

        Args:
            sample_ids: Optional list of sample IDs to process (default: all samples)
            progress_callback: Optional callback(current, total) for progress updates
            status_callback: Optional callback(message) for status text updates

        Returns:
            Dict mapping sample_id to status:
            - 'applied': Compensation matrix applied successfully
            - 'none': No compensation assigned (valid for spectral/unmixed data)
            - 'error': Compensation application failed
        """
        results: Dict[str, str] = {}

        if not self._workspace:
            logger.warning("apply_compensation_to_samples called but workspace not loaded")
            return results

        target_sample_ids = sample_ids if sample_ids else [s.sample_id for s in self._samples]
        total_samples = len(target_sample_ids)

        logger.info(f"Applying compensation to {total_samples} samples...")

        applied_count = 0
        none_count = 0
        error_count = 0

        for i, sample_id in enumerate(target_sample_ids):
            # Report progress
            if progress_callback:
                progress_callback(i + 1, total_samples)
            if status_callback:
                status_callback(f"Applying compensation ({i + 1}/{total_samples})...")
            try:
                # Try to get the compensation matrix for this sample
                # FlowKit's get_comp_matrix returns the matrix assigned in the WSP
                matrix = None
                if hasattr(self._workspace, 'get_comp_matrix'):
                    try:
                        matrix = self._workspace.get_comp_matrix(sample_id)
                    except Exception as e:
                        logger.debug(f"get_comp_matrix failed for {sample_id}: {e}")

                if matrix is not None:
                    # Apply compensation to the sample
                    sample = self._workspace.get_sample(sample_id)
                    sample.apply_compensation(matrix)
                    with self._compensation_lock:
                        self._samples_with_compensation_applied.add(sample_id)
                    results[sample_id] = 'applied'
                    applied_count += 1
                    logger.debug(f"Applied compensation to sample {sample_id}")
                else:
                    # No compensation matrix assigned - valid for unmixed/spectral data
                    results[sample_id] = 'none'
                    none_count += 1
                    logger.debug(f"No compensation matrix for sample {sample_id}")

            except Exception as e:
                results[sample_id] = 'error'
                error_count += 1
                logger.error(f"Failed to apply compensation to {sample_id}: {type(e).__name__}: {e}")

        logger.info(
            f"Compensation application complete: {applied_count} applied, "
            f"{none_count} no matrix, {error_count} errors"
        )

        return results

    def _ensure_sample_analyzed(self, sample_id: str) -> None:
        """Ensure a sample has been analyzed (on-demand analysis).

        FlowKit requires samples to be analyzed before gate membership
        or statistics can be computed. This method ensures analysis
        happens lazily, only when needed.

        Uses double-checked locking: quick unlocked check first (safe because
        we only ever ADD to _analyzed_samples), then re-check under lock
        before doing work.
        """
        # Fast path (unlocked) — safe because _analyzed_samples is only added to
        if sample_id in self._analyzed_samples:
            return

        if not self._workspace:
            return

        # Acquire lock and re-check before doing work (double-checked locking)
        with self._analyzed_samples_lock:
            # Re-check under lock
            if sample_id in self._analyzed_samples:
                return

            with self._failed_samples_lock:
                if sample_id in self._failed_samples:
                    logger.debug(f"Skipping previously failed sample: {sample_id}")
                    return

            try:
                logger.debug(f"On-demand analysis for sample: {sample_id}")
                self._workspace.analyze_samples(sample_id=sample_id)
                self._analyzed_samples.add(sample_id)
                logger.debug(f"Successfully analyzed sample: {sample_id}")
            except Exception as e:
                if "Detectors must be a subset" in str(e) or "detectors" in str(e).lower():
                    logger.warning(
                        f"Comp mismatch for {sample_id}, retrying without compensation: {e}"
                    )
                    if self._retry_analysis_without_comp(sample_id):
                        self._analyzed_samples.add(sample_id)
                        return

                logger.warning(f"Failed to analyze sample {sample_id}: {e}")
                # Track as failed — do NOT mark as analyzed so statistics aren't silently zero
                with self._failed_samples_lock:
                    self._failed_samples[sample_id] = f"{type(e).__name__}: {str(e)}"

    def _retry_analysis_without_comp(self, sample_id: str) -> bool:
        """Retry sample analysis by replacing compensation with identity matrices.

        FlowKit embeds compensation transforms in each sample's gating strategy.
        When the comp matrix detectors don't match the sample channels, analysis
        fails. This method replaces each comp matrix with an identity matrix
        whose detectors match the sample's actual fluorochrome channels. This
        preserves the comp_matrices keys so gate dimension references still
        resolve, but applies no actual compensation (identity @ events = events).

        For unmixed/spectral data, this is scientifically correct since spectral
        unmixing has already been applied upstream.

        Returns True if retry succeeded, False otherwise.
        """
        with self._comp_retry_lock:
            try:
                sample_data = self._workspace._sample_data_lut.get(sample_id)
                if not sample_data:
                    logger.debug(f"Retry skip: no sample_data for {sample_id}")
                    return False

                gating_strategy = sample_data.get('gating_strategy')
                if not gating_strategy:
                    logger.debug(f"Retry skip: no gating_strategy for {sample_id}")
                    return False

                if not gating_strategy.comp_matrices:
                    logger.debug(f"Retry skip: no comp_matrices for {sample_id}")
                    return False

                # Get the sample's actual fluorochrome channel labels
                sample = self._workspace.get_sample(sample_id)
                fluoro_labels = [sample.pnn_labels[i] for i in sample.fluoro_indices]
                n = len(fluoro_labels)
                if n == 0:
                    logger.debug(f"Retry skip: no fluoro channels for {sample_id}")
                    return False

                # Save originals, replace with identity matrices
                original_comps = dict(gating_strategy.comp_matrices)
                identity_data = np.eye(n)

                for comp_ref in list(gating_strategy.comp_matrices.keys()):
                    identity_matrix = FKMatrix(
                        identity_data,
                        fluoro_labels,
                        fluorochromes=fluoro_labels
                    )
                    gating_strategy.comp_matrices[comp_ref] = identity_matrix

                try:
                    with self._workspace_analysis_lock:
                        self._workspace.analyze_samples(sample_id=sample_id)
                    logger.info(f"Successfully analyzed {sample_id} with identity compensation (uncompensated)")
                    return True
                except Exception as retry_e:
                    logger.warning(f"Retry with identity comp also failed for {sample_id}: {retry_e}")
                    # Restore original comp matrices
                    gating_strategy.comp_matrices.update(original_comps)
                    return False
            except Exception as access_e:
                logger.debug(f"Cannot access FlowKit internals for {sample_id}: {access_e}")
                return False

    def _get_cached_events(self, sample_id: str, source: str) -> np.ndarray:
        """Get events from cache or load and cache them.

        Uses LRU cache with memory bounds - least recently used entries
        are automatically evicted when memory limit is reached.
        """
        cache_key = f"{sample_id}:{source}"
        cached = self._event_cache.get(cache_key)
        if cached is not None:
            return cached

        # Ensure sample is analyzed before getting events (on-demand)
        self._ensure_sample_analyzed(sample_id)
        sample = self._workspace.get_sample(sample_id)
        events = sample.get_events(source=source)
        self._event_cache.put(cache_key, events)
        return events

    def _get_cached_events_selective(
        self,
        sample_id: str,
        source: str,
        channels: List[str]
    ) -> Tuple[np.ndarray, List[str]]:
        """Get events for specific channels only, with caching.

        This method optimizes memory usage by caching only the requested
        channels rather than all channels. Different channel sets create
        different cache entries.

        Args:
            sample_id: Sample identifier
            source: Data source ('raw' or 'comp')
            channels: List of channel names to load

        Returns:
            Tuple of (events array with only requested channels, list of found channel names)

        Note:
            If the same channel set is requested multiple times for the
            same sample, it will be served from cache. This is particularly
            useful for MFI calculations that repeatedly access the same
            marker channels.
        """
        # Create cache key that includes the channels
        channel_key = ','.join(sorted(channels))
        cache_key = f"{sample_id}:{source}:channels={channel_key}"

        cached = self._event_cache.get(cache_key)
        if cached is not None:
            # Cache stores (events, labels) tuple
            return cached

        # Ensure sample is analyzed before getting events (on-demand)
        self._ensure_sample_analyzed(sample_id)
        sample = self._workspace.get_sample(sample_id)
        all_events = sample.get_events(source=source)
        all_labels = list(sample.pnn_labels) if hasattr(sample, 'pnn_labels') else []
        label_to_idx = {label: idx for idx, label in enumerate(all_labels)}

        # Filter to requested channels
        channel_indices = []
        found_channels = []
        for ch in channels:
            idx = label_to_idx.get(ch)
            if idx is not None:
                channel_indices.append(idx)
                found_channels.append(ch)

        if not channel_indices:
            logger.warning(f"None of requested channels found: {channels}")
            return np.array([]).reshape(0, 0), []

        # Extract only requested channel columns
        filtered_events = all_events[:, channel_indices]

        # Cache the filtered result
        result = (filtered_events, found_channels)
        self._event_cache.put(cache_key, result)

        logger.debug(
            f"Cached selective events for {sample_id}: "
            f"{len(found_channels)}/{len(channels)} channels, "
            f"{filtered_events.nbytes / 1024**2:.1f}MB"
        )

        return result

    def _get_gate_name_from_id(self, gate_id: str) -> str:
        """Extract gate name from full-path gate_id (e.g., 'Cells/Live/CD45+' -> 'CD45+')."""
        return gate_id.rsplit('/', 1)[-1] if '/' in gate_id else gate_id

    def _get_cached_membership(self, sample_id: str, gate_id: str) -> np.ndarray:
        """Get gate membership from cache or compute and cache it.

        Uses LRU cache with memory bounds - least recently used entries
        are automatically evicted when memory limit is reached.
        """
        cache_key = f"{sample_id}|{gate_id}"  # String key for LRU cache
        cached = self._membership_cache.get(cache_key)
        if cached is not None:
            return cached

        # Ensure sample is analyzed before getting membership (on-demand)
        self._ensure_sample_analyzed(sample_id)
        fk_path = self.get_fk_gate_path(gate_id)
        # Extract gate name from full-path gate_id for FlowKit API
        gate_name = self._get_gate_name_from_id(gate_id)
        membership = self._workspace.get_gate_membership(
            sample_id, gate_name, gate_path=fk_path
        )
        self._membership_cache.put(cache_key, membership)
        return membership

    def load_workspace(
        self,
        wsp_path: str,
        fcs_dir: Optional[str] = None,
        fcs_files: Optional[List[str]] = None,
        ignore_missing: bool = True
    ) -> Tuple[int, int]:
        """
        Load a FlowJo workspace file.

        Args:
            wsp_path: Path to the WSP file
            fcs_dir: Optional directory containing FCS files (for path remapping).
                     Used only if fcs_files is not provided.
            fcs_files: Optional list of FCS file paths. When provided, these files
                       are passed directly to FlowKit instead of searching a directory.
                       This takes precedence over fcs_dir.
            ignore_missing: If True, continue loading even if some FCS files are missing

        Returns:
            Tuple of (number of samples loaded, number of gates found)

        Raises:
            FileNotFoundError: If WSP file doesn't exist
            ValueError: If WSP file is invalid
        """
        self._wsp_path = Path(wsp_path)
        if not self._wsp_path.exists():
            raise FileNotFoundError(f"WSP file not found: {wsp_path}")

        # Clear any cached data from previous workspace
        self.clear_cache()

        # Determine FCS source: explicit file list takes precedence over directory
        if fcs_files:
            # Use explicit file list - FlowKit accepts a list of paths
            logger.info(f"Loading workspace with {len(fcs_files)} explicit FCS files")
            fcs_samples = fcs_files
            self._fcs_dir = None
        else:
            # Use directory (original behavior)
            self._fcs_dir = Path(fcs_dir) if fcs_dir else self._wsp_path.parent
            fcs_samples = str(self._fcs_dir)
            logger.info(f"Loading workspace with FCS directory: {self._fcs_dir}")

        # Load workspace with FlowKit
        # fcs_samples can be a directory path OR a list of file paths
        # find_fcs_files_from_wsp=False so we use our fcs_samples
        self._workspace = fk.Workspace(
            str(self._wsp_path),
            fcs_samples=fcs_samples,
            find_fcs_files_from_wsp=False
        )

        # Extract samples
        self._extract_samples()

        # Extract gate hierarchy
        self._extract_gates()

        # Extract available channels
        self._extract_channels()

        return len(self._samples), len(self._gates)

    @property
    def has_fcs_loaded(self) -> bool:
        """
        Check if FCS data is loaded (not just metadata).

        Returns:
            True if FCS data is loaded and available for analysis,
            False if only metadata is loaded or nothing is loaded.
        """
        return self._workspace is not None and not self._metadata_only

    def load_metadata_only(self, wsp_path: str) -> WSPMetadata:
        """
        Phase 1: Parse WSP XML to extract metadata without loading FCS files.

        This enables fast workspace preview for large datasets (70+ samples)
        by parsing only the XML structure. Users can then select which samples
        to load in Phase 2.

        Args:
            wsp_path: Path to the WSP file

        Returns:
            WSPMetadata containing samples, groups, gates, and compensation info

        Raises:
            FileNotFoundError: If WSP file doesn't exist
        """
        self._wsp_path = Path(wsp_path)
        if not self._wsp_path.exists():
            raise FileNotFoundError(f"WSP file not found: {wsp_path}")

        # Clear any previous state
        self.clear_cache()
        self._workspace = None
        self._metadata_only = True
        with self._compensation_lock:
            self._samples_with_compensation_applied.clear()

        logger.info(f"Phase 1: Parsing WSP metadata only: {self._wsp_path.name}")

        # Parse WSP metadata
        parser = WSPMetadataParser()
        self._wsp_metadata = parser.parse(wsp_path)

        # Populate internal sample list from metadata (without FCS data)
        self._samples = []
        for sample_id, meta in self._wsp_metadata.samples.items():
            self._samples.append(Sample(
                sample_id=meta.sample_id,
                name=meta.name,
                fcs_path=Path(meta.fcs_path) if meta.fcs_path else None,
                group="",  # Groups handled separately
                keywords={},  # Keywords not available without FCS
                event_count=meta.event_count or 0  # May have count from WSP
            ))

        # Sort samples naturally by name (e.g., A1, A2, A10 not A1, A10, A2)
        self._samples = natsorted(self._samples, key=lambda s: s.name, alg=ns.IGNORECASE)
        self._rebuild_sample_lookup()

        # Populate gates from metadata
        self._gates = []
        for gate_meta in self._wsp_metadata.gates:
            self._gates.append(GateInfo(
                gate_id=gate_meta.gate_id,
                name=gate_meta.name,
                path=gate_meta.path,
                gate_type=gate_meta.gate_type,
                parent_id="/".join(gate_meta.path[:-1]) if len(gate_meta.path) > 1 else None,
                parameters=[]  # Parameters require FCS data
            ))
        self._rebuild_gate_lookups()

        logger.info(
            f"Metadata loaded: {len(self._samples)} samples, "
            f"{len(self._wsp_metadata.groups)} groups, {len(self._gates)} gates"
        )

        return self._wsp_metadata

    def load_selected_fcs(
        self,
        selected_sample_ids: List[str],
        fcs_files: List[str],
        ignore_missing: bool = True
    ) -> Tuple[int, int]:
        """
        Phase 2: Load FCS data for selected samples only.

        After Phase 1 (load_metadata_only), call this method to load FCS data
        for the user-selected samples. This avoids loading all 70+ samples
        when only 14 are needed.

        Args:
            selected_sample_ids: List of sample IDs to load (from metadata)
            fcs_files: List of FCS file paths to search for matching files
            ignore_missing: If True, continue even if some FCS files are missing

        Returns:
            Tuple of (number of samples loaded, number of gates found)

        Raises:
            ValueError: If load_metadata_only was not called first
        """
        if self._wsp_path is None:
            raise ValueError("load_metadata_only must be called before load_selected_fcs")

        logger.info(
            f"Phase 2: Loading FCS data for {len(selected_sample_ids)} of "
            f"{len(self._wsp_metadata.samples) if self._wsp_metadata else '?'} samples"
        )

        # Filter FCS files to only those matching selected samples
        selected_set = set(selected_sample_ids)
        filtered_fcs_files = []

        for fcs_path in fcs_files:
            fcs_name = Path(fcs_path).name
            # FlowKit uses filename as sample_id
            if fcs_name in selected_set:
                filtered_fcs_files.append(fcs_path)
                logger.debug(f"Including FCS file: {fcs_name}")

        if not filtered_fcs_files:
            logger.warning("No matching FCS files found for selected samples")
            # Try with all FCS files as fallback
            filtered_fcs_files = fcs_files
            logger.info(f"Fallback: using all {len(fcs_files)} FCS files")

        logger.info(f"Loading {len(filtered_fcs_files)} FCS files for selected samples")

        # Create FlowKit workspace with only selected FCS files
        self._workspace = fk.Workspace(
            str(self._wsp_path),
            fcs_samples=filtered_fcs_files,
            find_fcs_files_from_wsp=False
        )

        # Clear metadata-only mode
        self._metadata_only = False

        # Re-extract samples from FlowKit (now with FCS data)
        self._extract_samples()

        # Re-extract gates (now with full info)
        self._extract_gates()

        # Extract channels
        self._extract_channels()

        logger.info(
            f"Phase 2 complete: {len(self._samples)} samples loaded, "
            f"{len(self._gates)} gates found"
        )

        return len(self._samples), len(self._gates)

    def get_metadata_groups(self) -> Dict[str, List[str]]:
        """
        Get sample groups from metadata (available in Phase 1).

        Returns:
            Dict mapping group name to list of sample IDs
        """
        if self._wsp_metadata is None:
            return {}
        return {
            name: group.sample_ids
            for name, group in self._wsp_metadata.groups.items()
        }

    def _extract_samples(self) -> None:
        """Extract sample information from the loaded workspace."""
        self._samples = []

        sample_ids = self._workspace.get_sample_ids()
        logger.info(f"Found {len(sample_ids)} sample IDs in workspace")

        samples_with_data = 0
        samples_without_data = 0

        for sample_id in sample_ids:
            try:
                sample = self._workspace.get_sample(sample_id)

                # Get keywords - try workspace method first (FlowKit 1.0+),
                # fallback to sample metadata for older versions
                if hasattr(self._workspace, 'get_keywords'):
                    keywords = self._workspace.get_keywords(sample_id) or {}
                else:
                    # Fallback for older FlowKit versions
                    keywords = {}
                    if hasattr(sample, 'metadata'):
                        keywords = sample.metadata or {}
                    if not keywords:
                        logger.debug(f"FlowKit version lacks get_keywords(); keywords unavailable for '{sample_id}'")

                # Get sample name - sample_id is typically the filename
                name = sample_id
                if hasattr(sample, 'original_filename') and sample.original_filename:
                    name = sample.original_filename

                # Get event count
                event_count = 0
                if hasattr(sample, 'event_count'):
                    event_count = sample.event_count

                # Get FCS path if available
                fcs_path = None
                if hasattr(sample, 'current_filename') and sample.current_filename:
                    fcs_path = Path(sample.current_filename)

                # Log FCS data status
                if event_count > 0:
                    samples_with_data += 1
                    logger.debug(f"Sample '{name}': {event_count} events, FCS: {fcs_path}")
                else:
                    samples_without_data += 1
                    logger.warning(f"Sample '{name}': NO EVENT DATA (event_count=0)")

                self._samples.append(Sample(
                    sample_id=sample_id,
                    name=name,
                    fcs_path=fcs_path,
                    group="",  # Use get_sample_groups() for group info (samples can be in multiple groups)
                    keywords=keywords,
                    event_count=event_count
                ))
            except Exception as e:
                # Sample might be missing or unreadable, skip it
                logger.error(f"Failed to extract sample '{sample_id}': {type(e).__name__}: {e}")
                continue

        # Sort samples naturally by name (e.g., A1, A2, A10 not A1, A10, A2)
        self._samples = natsorted(self._samples, key=lambda s: s.name, alg=ns.IGNORECASE)
        self._rebuild_sample_lookup()
        logger.debug(f"Sorted {len(self._samples)} samples by natural order")

        logger.info(f"Sample extraction complete: {samples_with_data} with data, {samples_without_data} without data")

    def _extract_gates(self) -> None:
        """Extract gate hierarchy from the loaded workspace.

        Iterates all samples to build:
        1. Union of all gates (for UI display)
        2. Per-sample gate availability tracking (_sample_gates)

        This handles workspaces where gates differ between samples.
        """
        self._gates = []
        self._sample_gates = {}

        if not self._samples:
            self._rebuild_gate_lookups()
            return

        # Track all unique gates and which samples have them
        all_gate_info: Dict[str, GateInfo] = {}  # gate_id -> GateInfo

        for sample in self._samples:
            sample_id = sample.sample_id
            self._sample_gates[sample_id] = set()

            try:
                # FlowKit returns gate_ids as list of tuples: (gate_name, (path_tuple))
                gate_ids = self._workspace.get_gate_ids(sample_id)

                for gate_tuple in gate_ids:
                    try:
                        # Unpack the tuple - gate_tuple is (gate_name, (path, to, gate))
                        gate_name, gate_path_tuple = gate_tuple

                        # Build path excluding 'root' for unique identification
                        path_list = [p for p in gate_path_tuple if p != 'root']
                        path_list.append(gate_name)
                        path_tuple = tuple(path_list)

                        # Create unique gate ID using full path (not just name)
                        # This handles gates with same name in different branches
                        gate_unique_id = "/".join(path_tuple)

                        # Track this gate exists for this sample (use full path ID)
                        self._sample_gates[sample_id].add(gate_unique_id)

                        # If we haven't seen this gate before, extract its info
                        if gate_unique_id not in all_gate_info:
                            # Get the gate object using name and path separately
                            gate = self._workspace.get_gate(sample_id, gate_name, gate_path=gate_path_tuple)

                            # Get gate type (strip 'Gate' suffix for cleaner display)
                            gate_type_raw = type(gate).__name__
                            gate_type = gate_type_raw.removesuffix('Gate') if gate_type_raw.endswith('Gate') else gate_type_raw

                            # Get parameters/dimensions used by this gate (extract IDs only)
                            params = []
                            if hasattr(gate, 'dimensions'):
                                params = [_extract_dimension_id(str(d)) for d in gate.dimensions]

                            all_gate_info[gate_unique_id] = GateInfo(
                                gate_id=gate_unique_id,  # Use full path as ID
                                name=gate_name,  # Keep original name for display
                                path=path_tuple,
                                gate_type=gate_type,
                                parent_id="/".join(path_tuple[:-1]) if len(path_tuple) > 1 else None,
                                parameters=params,
                                fk_gate_path=gate_path_tuple  # Store FlowKit's path for API calls
                            )
                    except Exception as e:
                        # Log when gates fail to load (was silently skipped before)
                        logger.warning(f"Failed to load gate '{gate_name}' at path {gate_path_tuple}: {type(e).__name__}: {e}")
                        continue
            except Exception as e:
                # Sample might not have gates defined - log for debugging
                logger.debug(f"Sample '{sample_id}' gate enumeration failed: {type(e).__name__}: {e}")
                continue

        # Convert to list (preserves order from dict in Python 3.7+)
        self._gates = list(all_gate_info.values())
        self._rebuild_gate_lookups()

        # Log gate availability summary with type breakdown
        total_gates = len(self._gates)
        samples_with_all_gates = sum(
            1 for gates in self._sample_gates.values()
            if len(gates) == total_gates
        )

        # Count gates by type for diagnostic purposes
        gate_type_counts: Dict[str, int] = {}
        for gate in self._gates:
            gate_type_counts[gate.gate_type] = gate_type_counts.get(gate.gate_type, 0) + 1

        logger.info(
            f"Extracted {total_gates} unique gates across {len(self._samples)} samples "
            f"({samples_with_all_gates} samples have all gates)"
        )
        logger.info(f"Gate types: {gate_type_counts}")

    def _find_gate_path(self, gate_id: str, sample_id: str) -> Tuple[str, ...]:
        """Find the full path for a gate in the hierarchy."""
        try:
            # FlowKit provides gate paths through get_gate_hierarchy
            hierarchy = self._workspace.get_gate_hierarchy(sample_id, output='list')

            # Build path by traversing hierarchy
            # The hierarchy is a nested structure, we need to find our gate
            def find_path(items, target_id, current_path=()):
                for item in items:
                    if isinstance(item, dict):
                        for name, children in item.items():
                            new_path = current_path + (name,)
                            if name == target_id:
                                return new_path
                            if children:
                                result = find_path(children, target_id, new_path)
                                if result:
                                    return result
                    elif isinstance(item, str):
                        new_path = current_path + (item,)
                        if item == target_id:
                            return new_path
                return None

            path = find_path(hierarchy if isinstance(hierarchy, list) else [hierarchy], gate_id)
            return path if path else (gate_id,)
        except Exception:
            return (gate_id,)

    def _extract_channels(self) -> None:
        """Extract available fluorescence channels with reagent names."""
        self._channels = []
        self._channel_info = []

        if not self._samples:
            return

        try:
            sample_id = self._samples[0].sample_id
            sample = self._workspace.get_sample(sample_id)

            pnn_labels = list(sample.pnn_labels) if hasattr(sample, 'pnn_labels') else []
            pns_labels = list(sample.pns_labels) if hasattr(sample, 'pns_labels') else []

            # Pad pns_labels if shorter
            while len(pns_labels) < len(pnn_labels):
                pns_labels.append('')

            for i, pnn in enumerate(pnn_labels):
                if pnn.endswith(('-A', '-H', '-W')) and not pnn.startswith(('FSC', 'SSC', 'Time')):
                    self._channels.append(pnn)
                    pns = pns_labels[i] if i < len(pns_labels) else ''
                    self._channel_info.append(ChannelInfo(pnn_label=pnn, pns_label=pns))

            logger.info(f"Extracted {len(self._channels)} channels with reagent info")
        except Exception as e:
            logger.warning(f"Failed to extract channels: {e}")

    def get_sample_by_id(self, sample_id: str) -> Optional[Sample]:
        """Get a sample by its ID."""
        return self._sample_by_id.get(sample_id)

    def get_fk_gate_path(self, gate_id: str) -> Optional[Tuple[str, ...]]:
        """Get the FlowKit gate_path tuple for API calls."""
        return self._fk_gate_path_by_id.get(gate_id)

    def gate_exists_for_sample(self, sample_id: str, gate_id: str) -> bool:
        """Check if a gate exists for a specific sample.

        Not all gates exist in all samples - FlowJo workspaces can have
        sample-specific gating strategies.

        Args:
            sample_id: Sample ID to check
            gate_id: Gate ID to check

        Returns:
            True if the gate exists for this sample, False otherwise
        """
        return gate_id in self._sample_gates.get(sample_id, set())

    def get_missing_gates_info(self, gate_ids: List[str]) -> Dict[str, List[str]]:
        """Get information about which gates are missing from which samples.

        Args:
            gate_ids: List of gate IDs to check

        Returns:
            Dict mapping gate_id to list of sample_ids where it's missing
        """
        missing_info: Dict[str, List[str]] = {}
        for gate_id in gate_ids:
            missing_samples = []
            for sample in self._samples:
                if not self.gate_exists_for_sample(sample.sample_id, gate_id):
                    missing_samples.append(sample.sample_id)
            if missing_samples:
                missing_info[gate_id] = missing_samples
        return missing_info

    def get_descendant_gates(
        self,
        reference_gate_id: str,
        max_depth: int = 0  # 0 = unlimited
    ) -> List[GateInfo]:
        """
        Get all descendant gates of a reference gate.

        Args:
            reference_gate_id: The gate ID to find descendants for (e.g., "Cells/Live/CD8+")
            max_depth: Maximum depth to traverse (0 = unlimited, 1 = direct children only)

        Returns:
            List of GateInfo objects that are descendants
        """
        # Find the reference gate
        reference_gate = self._gate_by_id.get(reference_gate_id)

        if not reference_gate:
            return []

        descendants = []
        ref_path = reference_gate.path
        ref_depth = len(ref_path)

        for gate in self._gates:
            # Skip the reference gate itself
            if gate.gate_id == reference_gate_id:
                continue

            # Check if this gate's path starts with the reference path
            if len(gate.path) > ref_depth and gate.path[:ref_depth] == ref_path:
                # Calculate relative depth
                relative_depth = len(gate.path) - ref_depth

                # Apply depth filter (0 = unlimited)
                if max_depth == 0 or relative_depth <= max_depth:
                    descendants.append(gate)

        return descendants

    def get_gates_without_data_in_samples(
        self,
        gate_ids: List[str],
        sample_ids: List[str]
    ) -> List[str]:
        """
        Get gates that don't exist in ANY of the specified samples.

        Useful for filtering out stain control gates when those samples
        are deselected for export.

        Args:
            gate_ids: List of gate IDs to check
            sample_ids: List of sample IDs to check against

        Returns:
            List of gate_ids that have no data in any of the specified samples
        """
        gates_without_data = []
        for gate_id in gate_ids:
            has_data_in_any_sample = any(
                self.gate_exists_for_sample(sample_id, gate_id)
                for sample_id in sample_ids
            )
            if not has_data_in_any_sample:
                gates_without_data.append(gate_id)
        return gates_without_data

    def get_gate_hierarchy_ascii(self, sample_id: Optional[str] = None) -> str:
        """Get ASCII representation of gate hierarchy."""
        if not self._workspace:
            return ""

        if sample_id is None and self._samples:
            sample_id = self._samples[0].sample_id

        if sample_id:
            try:
                return self._workspace.get_gate_hierarchy(sample_id, output='ascii')
            except Exception:
                return ""
        return ""

    def analyze_samples(
        self,
        sample_ids: Optional[List[str]] = None,
        gate_ids: Optional[List[str]] = None,
        progress_callback: Optional[callable] = None,
        batch_callback: Optional[callable] = None
    ) -> None:
        """
        Run analysis on samples to calculate gate statistics.

        Args:
            sample_ids: List of sample IDs to analyze (default: all)
            gate_ids: List of gate IDs to include (default: all)
            progress_callback: Optional callback for progress updates (receives current, total)
            batch_callback: Optional callback for batch progress (receives batch_num, total_batches, batch_description)
        """
        if not self._workspace:
            return

        if sample_ids is None:
            sample_ids = [s.sample_id for s in self._samples]

        total = len(sample_ids)
        all_samples = len(sample_ids) == len(self._samples)

        # Process samples in batches to limit peak memory usage
        # Batch size of 10 keeps memory footprint manageable for large datasets
        batch_size = 10
        logger.info(f"Analyzing {total} samples in batches of {batch_size}...")

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = sample_ids[batch_start:batch_end]
            batch_num = (batch_start // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} samples)")

            # Notify batch progress
            if batch_callback:
                batch_callback(batch_num, total_batches, f"Analyzing batch {batch_num}/{total_batches}")

            for i, sample_id in enumerate(batch):
                try:
                    # Skip if already analyzed (on-demand analysis may have done it)
                    with self._analyzed_samples_lock:
                        if sample_id in self._analyzed_samples:
                            logger.debug(f"Sample {sample_id} already analyzed, skipping")
                            continue

                    # Skip if previously failed
                    with self._failed_samples_lock:
                        if sample_id in self._failed_samples:
                            logger.debug(f"Sample {sample_id} previously failed, skipping")
                            continue

                    logger.debug(f"Analyzing sample: {sample_id}")
                    self._workspace.analyze_samples(sample_id=sample_id)
                    with self._analyzed_samples_lock:
                        self._analyzed_samples.add(sample_id)

                    if progress_callback:
                        progress_callback(batch_start + i + 1, total)
                except Exception as e:
                    if "Detectors must be a subset" in str(e) or "detectors" in str(e).lower():
                        logger.warning(f"Comp mismatch for {sample_id}, retrying without comp")
                        if self._retry_analysis_without_comp(sample_id):
                            with self._analyzed_samples_lock:
                                self._analyzed_samples.add(sample_id)
                            if progress_callback:
                                progress_callback(batch_start + i + 1, total)
                            continue

                    logger.error(f"analyze_sample FAILED for {sample_id}: {type(e).__name__}: {e}")
                    import traceback
                    logger.debug(f"Full traceback:\n{traceback.format_exc()}")
                    # Track as failed — do NOT mark as analyzed
                    with self._failed_samples_lock:
                        self._failed_samples[sample_id] = f"{type(e).__name__}: {str(e)}"
                    continue

            # Force garbage collection between batches to release memory
            gc.collect()
            logger.debug(f"Garbage collection after batch {batch_num}")

        logger.info(f"Successfully analyzed {len(self._analyzed_samples)} samples")

    def analyze_samples_parallel(
        self,
        sample_ids: Optional[List[str]] = None,
        max_workers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> Dict[str, bool]:
        """
        Analyze samples in parallel using a thread pool.

        FlowKit uses numpy which releases the GIL, allowing true parallelism
        with ThreadPoolExecutor. This can provide 2-4x speedup on multi-core
        systems for large workspaces.

        Args:
            sample_ids: List of sample IDs to analyze (default: all)
            max_workers: Maximum number of parallel workers (default: min(4, cpu_count))
            progress_callback: Optional callback(current, total) for progress updates
            cancellation_token: Optional token to support cancellation

        Returns:
            Dict mapping sample_id to success status (True=success, False=failed)

        Raises:
            CancellationError: If cancellation_token is cancelled

        Note:
            If parallel analysis encounters thread-safety issues with FlowKit,
            use the sequential analyze_samples() method instead.
        """
        if not self._workspace:
            return {}

        if sample_ids is None:
            sample_ids = [s.sample_id for s in self._samples]

        # Filter out already-analyzed and already-failed samples
        with self._analyzed_samples_lock:
            with self._failed_samples_lock:
                samples_to_analyze = [
                    sid for sid in sample_ids
                    if sid not in self._analyzed_samples and sid not in self._failed_samples
                ]

        if not samples_to_analyze:
            logger.info("All samples already analyzed")
            return {sid: True for sid in sample_ids}

        # Determine worker count — scale dynamically based on CPU and sample count
        if max_workers is None:
            cpu_workers = min(4, multiprocessing.cpu_count())
            sample_workers = max(1, len(samples_to_analyze) // 3)
            max_workers = min(cpu_workers, sample_workers)

        total = len(samples_to_analyze)
        completed = 0
        results: Dict[str, bool] = {}

        logger.info(f"Parallel analysis: {total} samples with {max_workers} workers")

        def analyze_one(sample_id: str) -> Tuple[str, bool, str]:
            """Analyze a single sample. Returns (sample_id, success, error_msg)."""
            try:
                with self._workspace_analysis_lock:
                    self._workspace.analyze_samples(sample_id=sample_id)
                return (sample_id, True, "")
            except Exception as e:
                if "Detectors must be a subset" in str(e) or "detectors" in str(e).lower():
                    logger.warning(f"Comp mismatch for {sample_id}, retrying without comp")
                    if self._retry_analysis_without_comp(sample_id):
                        return (sample_id, True, "")
                return (sample_id, False, str(e))

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                futures = {
                    executor.submit(analyze_one, sid): sid
                    for sid in samples_to_analyze
                }

                # Process completed tasks as they finish
                for future in as_completed(futures):
                    # Check for cancellation
                    if cancellation_token and cancellation_token.is_cancelled:
                        # Cancel pending futures
                        for f in futures:
                            f.cancel()
                        raise CancellationError("Parallel analysis cancelled by user")

                    sample_id, success, error = future.result()
                    results[sample_id] = success

                    if success:
                        with self._analyzed_samples_lock:
                            self._analyzed_samples.add(sample_id)
                        logger.debug(f"Parallel analysis completed: {sample_id}")
                    else:
                        # Track as failed — do NOT mark as analyzed
                        with self._failed_samples_lock:
                            self._failed_samples[sample_id] = error or "Unknown error"
                        logger.warning(f"Parallel analysis failed for {sample_id}: {error}")

                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total)

        except CancellationError:
            raise
        except Exception as e:
            logger.error(f"Parallel analysis error: {type(e).__name__}: {e}")
            # Fall back results for remaining samples
            for sid in samples_to_analyze:
                if sid not in results:
                    results[sid] = False

        # Garbage collection after parallel work
        gc.collect()

        success_count = sum(1 for v in results.values() if v)
        logger.info(f"Parallel analysis complete: {success_count}/{total} successful")

        # Include already-analyzed samples in results
        for sid in sample_ids:
            if sid not in results:
                results[sid] = sid in self._analyzed_samples

        return results

    def get_gate_statistics(
        self,
        sample_id: str,
        gate_id: str
    ) -> Dict[str, Any]:
        """
        Get statistics for a specific gate on a specific sample.

        Returns dict with:
            - count: event count in gate
            - percent_parent: percentage of parent gate
            - percent_total: percentage of total events

        If the gate doesn't exist for this sample, returns zeros (expected behavior
        for workspaces with sample-specific gating strategies).
        """
        if not self._workspace:
            logger.warning(f"get_gate_statistics called but workspace not loaded")
            return {}

        # Check if gate exists for this sample BEFORE attempting to query FlowKit
        if not self.gate_exists_for_sample(sample_id, gate_id):
            logger.debug(f"Gate '{gate_id}' does not exist for sample '{sample_id}' - returning zeros")
            return {'count': 0, 'percent_parent': 0.0, 'percent_total': 0.0}

        try:
            # Get gate membership (cached for performance)
            logger.debug(f"Getting gate membership for sample='{sample_id}', gate='{gate_id}'")

            result = self._get_cached_membership(sample_id, gate_id)
            logger.debug(f"Gate membership result: type={type(result)}, shape={getattr(result, 'shape', 'N/A')}")

            # Get parent gate membership for percent calculation (also cached)
            parent_id, parent_fk_path = self._get_parent_gate_info(gate_id)
            parent_count = None
            if parent_id is not None:
                parent_count = self._get_cached_membership(sample_id, parent_id)

            count = int(result.sum()) if hasattr(result, 'sum') else int(np.count_nonzero(result))
            total = self._get_sample_event_count(sample_id)

            logger.debug(f"Gate '{gate_id}' stats: count={count}, total_events={total}")

            # Calculate parent sum safely (avoid divide-by-zero)
            parent_sum = parent_count.sum() if parent_count is not None else 0
            percent_parent = (count / parent_sum * 100) if parent_sum > 0 else 0.0

            return {
                'count': count,
                'percent_parent': percent_parent,
                'percent_total': (count / total * 100) if total > 0 else 0.0
            }
        except Exception as e:
            # Log at debug level - this is expected for some sample/gate combinations
            logger.debug(f"Gate statistics unavailable for sample='{sample_id}', gate='{gate_id}': {e}")
            return {'count': 0, 'percent_parent': 0.0, 'percent_total': 0.0}

    def _get_parent_gate_info(self, gate_id: str) -> Tuple[Optional[str], Optional[Tuple[str, ...]]]:
        """Get the parent gate ID (full path) and FlowKit path for a given gate."""
        parent_gate_id = self._parent_gate_by_id.get(gate_id)
        if parent_gate_id is None:
            return None, None
        return parent_gate_id, self.get_fk_gate_path(parent_gate_id)

    def _get_sample_event_count(self, sample_id: str) -> int:
        """Get total event count for a sample."""
        sample = self.get_sample_by_id(sample_id)
        return sample.event_count if sample else 0

    def get_gated_events(
        self,
        sample_id: str,
        gate_id: str,
        channels: Optional[List[str]] = None,
        data_source: DataSource = DataSource.AUTO
    ) -> Optional[pd.DataFrame]:
        """
        Get events that fall within a specific gate.

        Args:
            sample_id: Sample ID
            gate_id: Gate ID
            channels: Optional list of channels to include (default: all)
            data_source: Event data source - AUTO (try comp, fallback to raw),
                        RAW (force uncompensated), or COMP (force compensated)

        Returns:
            DataFrame with event data for the gated population
        """
        if not self._workspace:
            logger.warning("get_gated_events called but workspace not loaded")
            return None

        try:
            # Get gate membership (cached for performance)
            logger.debug(f"Getting gated events: sample='{sample_id}', gate='{gate_id}', data_source={data_source.value}")

            membership = self._get_cached_membership(sample_id, gate_id)
            membership_count = int(membership.sum()) if hasattr(membership, 'sum') else 0
            logger.debug(f"Gate membership: {membership_count} events in gate (of {len(membership)} total)")

            if membership_count == 0:
                logger.warning(f"No events in gate '{gate_id}' for sample '{sample_id}'")
                return pd.DataFrame()

            # Optimization: If specific channels requested, use selective loading
            # This reduces memory usage significantly for MFI calculations
            if channels and data_source in (DataSource.RAW, DataSource.COMP):
                source = 'raw' if data_source == DataSource.RAW else 'comp'

                # For COMP mode with selective loading, verify compensation was applied
                with self._compensation_lock:
                    comp_not_applied = data_source == DataSource.COMP and sample_id not in self._samples_with_compensation_applied
                if comp_not_applied:
                    comp_status = self._compensation_status.get(sample_id) if hasattr(self, '_compensation_status') else None
                    if comp_status == 'none':
                        raise CompensationError(
                            f"Compensated data requested but sample '{sample_id}' has no compensation "
                            f"assigned in FlowJo (unmixed/spectral data). Use 'Auto' mode instead."
                        )
                    else:
                        raise CompensationError(
                            f"Compensated data requested but compensation not applied to sample '{sample_id}'. "
                            f"Check compensation matrix assignment in FlowJo."
                        )

                logger.debug(f"Using selective channel loading for {len(channels)} channels")
                try:
                    events, columns = self._get_cached_events_selective(
                        sample_id, source, channels
                    )
                    if events.size == 0:
                        logger.error(f"Selective loading failed for channels: {channels}")
                        return None
                    # Apply gate membership filter
                    gated_events = events[membership]
                    logger.debug(f"Selective gated events shape: {gated_events.shape}")
                    return pd.DataFrame(gated_events, columns=columns)
                except Exception as e:
                    logger.warning(f"Selective loading failed, falling back to full load: {e}")
                    # Fall through to standard path

            # Get sample events (cached for performance)
            sample = self._workspace.get_sample(sample_id)
            events = None
            source_used = None

            if data_source == DataSource.RAW:
                # Force raw data (cached)
                logger.debug("Using RAW (uncompensated) data as requested")
                events = self._get_cached_events(sample_id, 'raw')
                source_used = 'raw'

            elif data_source == DataSource.COMP:
                # Force compensated data - fail if compensation wasn't applied
                with self._compensation_lock:
                    comp_not_applied = sample_id not in self._samples_with_compensation_applied
                if comp_not_applied:
                    # Check if sample has compensation status from WSP
                    comp_status = self._compensation_status.get(sample_id) if hasattr(self, '_compensation_status') else None
                    if comp_status == 'none':
                        raise CompensationError(
                            f"Compensated data requested but sample '{sample_id}' has no compensation "
                            f"assigned in FlowJo (unmixed/spectral data). Use 'Auto' mode instead."
                        )
                    else:
                        raise CompensationError(
                            f"Compensated data requested but compensation not applied to sample '{sample_id}'. "
                            f"Check compensation matrix assignment in FlowJo."
                        )
                logger.debug("Using COMP (compensated) data as requested")
                events = self._get_cached_events(sample_id, 'comp')
                source_used = 'comp'

            else:  # DataSource.AUTO
                # Check cache first, then try compensated, fallback to raw
                comp_cache_key = f"{sample_id}:comp"
                raw_cache_key = f"{sample_id}:raw"

                # Try to get from cache using LRU cache API
                cached_comp = self._event_cache.get(comp_cache_key)
                cached_raw = self._event_cache.get(raw_cache_key)

                if cached_comp is not None:
                    events = cached_comp
                    source_used = 'comp'
                elif cached_raw is not None:
                    events = cached_raw
                    source_used = 'raw'
                else:
                    # Try compensated first, fallback to raw
                    try:
                        logger.debug("AUTO mode: trying compensated data first...")
                        events = self._get_cached_events(sample_id, 'comp')
                        source_used = 'comp'
                        logger.debug("Successfully retrieved compensated events")
                    except Exception as comp_error:
                        logger.warning(f"Compensated data unavailable: {type(comp_error).__name__}: {comp_error}")
                        logger.info("Falling back to raw (uncompensated) data")
                        events = self._get_cached_events(sample_id, 'raw')
                        source_used = 'raw'

            if events is None:
                logger.error(f"sample.get_events() returned None for sample '{sample_id}'")
                return None

            logger.debug(f"Event data retrieved: shape={events.shape}, source={source_used}")

            if events.shape[0] == 0:
                logger.warning(f"Event array is empty for sample '{sample_id}'")
                return pd.DataFrame()

            # Get channel labels
            all_labels = list(sample.pnn_labels) if hasattr(sample, 'pnn_labels') else []
            label_to_idx = {label: idx for idx, label in enumerate(all_labels)}
            logger.debug(f"Available channels: {all_labels}")

            if channels:
                # Filter to requested channels
                channel_indices = []
                found_channels = []
                missing_channels = []

                for ch in channels:
                    idx = label_to_idx.get(ch)
                    if idx is not None:
                        channel_indices.append(idx)
                        found_channels.append(ch)
                    else:
                        missing_channels.append(ch)

                if missing_channels:
                    logger.warning(f"Requested channels not found in FCS: {missing_channels}")

                if not channel_indices:
                    logger.error(f"None of the requested channels found: {channels}")
                    return None

                events = events[:, channel_indices]
                columns = found_channels
                logger.debug(f"Filtered to {len(columns)} channels: {columns}")
            else:
                columns = all_labels

            # Filter to gated events
            gated_events = events[membership]
            logger.debug(f"Gated events shape: {gated_events.shape}")

            return pd.DataFrame(gated_events, columns=columns)

        except Exception as e:
            logger.error(f"get_gated_events FAILED for sample='{sample_id}', gate='{gate_id}': {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"Full traceback:\n{traceback.format_exc()}")
            return None

    def get_analysis_report(self) -> pd.DataFrame:
        """
        Get full analysis report with all gates and samples.

        Returns a DataFrame suitable for export.
        """
        if not self._workspace:
            return pd.DataFrame()

        try:
            return self._workspace.get_analysis_report()
        except Exception:
            return pd.DataFrame()

    def get_analysis_failures(self) -> Dict[str, str]:
        """Get samples that failed analysis with error messages."""
        with self._failed_samples_lock:
            return self._failed_samples.copy()

    def get_analysis_summary(self) -> Dict[str, int]:
        """Get summary of analysis status across all samples."""
        total = len(self._samples) if self._samples else 0
        analyzed = len(self._analyzed_samples)
        with self._failed_samples_lock:
            failed = len(self._failed_samples)
        pending = total - analyzed - failed
        return {
            'total': total,
            'analyzed': analyzed,
            'failed': failed,
            'pending': pending
        }

    def has_fcs_data(self, sample_id: str) -> bool:
        """
        Check if a sample has actual FCS event data loaded.

        Args:
            sample_id: Sample ID to check

        Returns:
            True if sample has event data, False otherwise
        """
        sample = self.get_sample_by_id(sample_id)
        if sample is None:
            return False
        return sample.event_count > 0

    def get_samples_with_data(self) -> List[Sample]:
        """Get list of samples that have FCS data loaded."""
        return [s for s in self._samples if s.event_count > 0]

    def get_samples_without_data(self) -> List[Sample]:
        """Get list of samples that are missing FCS data."""
        return [s for s in self._samples if s.event_count == 0]

    def get_compensation_matrices(self) -> List[str]:
        """
        Get list of available compensation matrices in the workspace.

        Returns:
            List of compensation matrix names/IDs
        """
        if not self._workspace:
            return []

        try:
            # FlowKit exposes compensation matrices through the workspace
            # This depends on the FlowKit version and workspace structure
            matrices = []

            # Try to get compensation from the first sample
            if self._samples:
                sample_id = self._samples[0].sample_id
                sample = self._workspace.get_sample(sample_id)

                # Check if sample has compensation
                if hasattr(sample, 'compensation'):
                    comp = sample.compensation
                    if comp is not None:
                        matrices.append('default')

                # FlowKit might also have workspace-level compensation
                if hasattr(self._workspace, 'get_comp_matrices'):
                    ws_matrices = self._workspace.get_comp_matrices()
                    if ws_matrices:
                        matrices.extend([str(m) for m in ws_matrices])

            logger.debug(f"Found compensation matrices: {matrices}")
            return matrices

        except Exception as e:
            logger.warning(f"Could not retrieve compensation matrices: {e}")
            return []

    def get_sample_groups(self) -> Dict[str, List[str]]:
        """
        Get sample groups from the workspace.

        FlowJo workspaces organize samples into groups (e.g., 'Tumor Samples',
        'FMO Controls', 'Single Stains'). This method extracts those groups.

        Returns:
            Dict mapping group name to list of sample IDs in that group.
            A sample can belong to multiple groups.
        """
        if not self._workspace:
            return {}

        try:
            groups: Dict[str, List[str]] = {}

            # FlowKit's get_sample_groups() returns list of group names
            if hasattr(self._workspace, 'get_sample_groups'):
                group_names = self._workspace.get_sample_groups()
                logger.debug(f"Found {len(group_names)} sample groups in workspace")

                for group_name in group_names:
                    # get_sample_ids with group_name filter returns samples in that group
                    sample_ids = list(self._workspace.get_sample_ids(group_name=group_name))
                    if sample_ids:
                        groups[group_name] = sample_ids
                        logger.debug(f"Group '{group_name}': {len(sample_ids)} samples")
            else:
                logger.debug("FlowKit version does not support get_sample_groups()")

            return groups

        except Exception as e:
            logger.warning(f"Failed to get sample groups: {e}")
            return {}

    def scan_compensation_status(
        self,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, str]:
        """
        Pre-scan compensation availability for all samples.

        This is useful for showing users which samples have valid compensation
        before they attempt to export with 'Force Compensated' mode.

        Args:
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Dict mapping sample_id to status: 'valid', 'missing', or 'error'
        """
        status: Dict[str, str] = {}

        if not self._workspace or not self._samples:
            return status

        total = len(self._samples)
        logger.info(f"Scanning compensation status for {total} samples...")

        for i, sample in enumerate(self._samples):
            sample_id = sample.sample_id
            try:
                # Try to get compensated events - this will fail if no compensation
                fk_sample = self._workspace.get_sample(sample_id)
                fk_sample.get_events(source='comp')
                status[sample_id] = 'valid'
                logger.debug(f"Sample '{sample.name}': compensation valid")
            except Exception as e:
                status[sample_id] = 'missing'
                logger.debug(f"Sample '{sample.name}': compensation missing ({type(e).__name__})")

            if progress_callback:
                progress_callback(i + 1, total)

        # Summary logging
        valid_count = sum(1 for s in status.values() if s == 'valid')
        missing_count = sum(1 for s in status.values() if s == 'missing')
        logger.info(f"Compensation scan complete: {valid_count} valid, {missing_count} missing")

        self._compensation_status = status
        return status

    @property
    def compensation_status(self) -> Dict[str, str]:
        """Get cached compensation status from last scan."""
        return getattr(self, '_compensation_status', {})

    def _parse_compensation_from_wsp(self) -> Tuple[
        List[CompensationMatrixInfo],
        Dict[str, SampleCompensationAssignment]
    ]:
        """
        Parse compensation matrices and per-sample assignments directly from WSP XML.

        FlowKit's API doesn't expose all compensation metadata (colors, UUIDs),
        so we parse the WSP file directly to extract this information.

        Returns:
            Tuple of:
            - List of global CompensationMatrixInfo objects
            - Dict mapping sample_id to SampleCompensationAssignment
        """
        global_matrices: List[CompensationMatrixInfo] = []
        sample_assignments: Dict[str, SampleCompensationAssignment] = {}

        if not self._wsp_path or not self._wsp_path.exists():
            logger.warning("WSP path not set or file doesn't exist")
            return global_matrices, sample_assignments

        try:
            # Parse WSP XML
            tree = etree.parse(str(self._wsp_path))
            root = tree.getroot()

            # Define namespaces used in FlowJo WSP files
            ns = {
                'transforms': 'http://www.isac-net.org/std/Gating-ML/v2.0/transformations',
                'data-type': 'http://www.isac-net.org/std/Gating-ML/v2.0/datatypes'
            }

            # Build namespace-aware tag names
            transforms_ns = '{http://www.isac-net.org/std/Gating-ML/v2.0/transformations}'
            data_type_ns = '{http://www.isac-net.org/std/Gating-ML/v2.0/datatypes}'

            # 1. Parse global matrices from <Matrices> section
            matrices_section = root.find('.//Matrices')
            if matrices_section is not None:
                for matrix_el in matrices_section.findall(f'.//{transforms_ns}spilloverMatrix'):
                    matrix_info = self._parse_spillover_matrix_element(matrix_el, transforms_ns, data_type_ns)
                    if matrix_info:
                        global_matrices.append(matrix_info)
                        logger.debug(f"Found global matrix: {matrix_info.name} (color={matrix_info.color})")

            logger.info(f"Parsed {len(global_matrices)} global compensation matrices from WSP")

            # Build lookup by matrix_id for quick assignment
            matrix_lookup = {m.matrix_id: m for m in global_matrices}

            # 2. Parse per-sample compensation assignments
            sample_list = root.find('.//SampleList')
            if sample_list is not None:
                for sample_el in sample_list.findall('.//Sample'):
                    # Get sample ID from DataSet element
                    dataset_el = sample_el.find('.//DataSet')
                    if dataset_el is None:
                        continue

                    sample_id_attr = dataset_el.get('sampleID')
                    if not sample_id_attr:
                        continue

                    # Find FlowKit's sample_id (which is the filename)
                    # The sampleID in WSP is numeric, we need to map to filename
                    uri = dataset_el.get('uri', '')
                    # Extract filename from URI like "file:/path/to/A5%20M5.fcs"
                    if uri:
                        filename = unquote(uri.split('/')[-1]) if '/' in uri else unquote(uri)
                    else:
                        filename = None

                    # Look for spilloverMatrix in this sample
                    sample_matrix_el = sample_el.find(f'.//{transforms_ns}spilloverMatrix')

                    if sample_matrix_el is not None:
                        # Sample has compensation assigned
                        matrix_id = sample_matrix_el.get(f'{transforms_ns}id', '')
                        matrix_name = sample_matrix_el.get('name', '')
                        color = sample_matrix_el.get('color', '#808080')
                        spectral_str = sample_matrix_el.get('spectral', '0')
                        spectral = spectral_str == '1'

                        assignment = SampleCompensationAssignment(
                            matrix_name=matrix_name,
                            matrix_id=matrix_id,
                            color=color,
                            spectral=spectral
                        )
                    else:
                        # No compensation for this sample
                        assignment = SampleCompensationAssignment(
                            matrix_name=None,
                            matrix_id=None,
                            color=None,
                            spectral=None
                        )

                    # Map using filename (FlowKit's sample_id)
                    if filename:
                        sample_assignments[filename] = assignment

            logger.info(f"Parsed compensation assignments for {len(sample_assignments)} samples")

            # Log summary of assignments
            with_comp = sum(1 for a in sample_assignments.values() if a.matrix_name is not None)
            without_comp = sum(1 for a in sample_assignments.values() if a.matrix_name is None)
            logger.info(f"Compensation assignments: {with_comp} with matrix, {without_comp} without")

        except Exception as e:
            logger.error(f"Failed to parse compensation from WSP: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"Full traceback:\n{traceback.format_exc()}")

        return global_matrices, sample_assignments

    def _parse_spillover_matrix_element(
        self,
        matrix_el: etree._Element,
        transforms_ns: str,
        data_type_ns: str
    ) -> Optional[CompensationMatrixInfo]:
        """Parse a single spilloverMatrix element into CompensationMatrixInfo."""
        try:
            name = matrix_el.get('name', 'Unknown')
            matrix_id = matrix_el.get(f'{transforms_ns}id', '')
            color = matrix_el.get('color', '#808080')  # Default gray
            spectral_str = matrix_el.get('spectral', '0')
            spectral = spectral_str == '1'
            editable_str = matrix_el.get('editable', '0')
            editable = editable_str == '1'
            status = matrix_el.get('status', '')

            # Parse detector list from parameters
            detectors = []
            params_el = matrix_el.find(f'.//{data_type_ns}parameters')
            if params_el is not None:
                for param_el in params_el.findall(f'.//{data_type_ns}parameter'):
                    param_name = param_el.get(f'{data_type_ns}name', '')
                    if param_name:
                        detectors.append(param_name)

            return CompensationMatrixInfo(
                name=name,
                matrix_id=matrix_id,
                color=color,
                spectral=spectral,
                detectors=detectors,
                editable=editable,
                status=status
            )
        except Exception as e:
            logger.warning(f"Failed to parse spillover matrix element: {e}")
            return None

    def get_workspace_compensation_info(self) -> Dict[str, Any]:
        """
        Get comprehensive compensation information from the workspace.

        This method parses the WSP file directly to extract compensation
        matrices with their colors and per-sample assignments.

        Returns:
            Dict with:
            - 'global_matrices': List of CompensationMatrixInfo objects
            - 'sample_assignments': Dict mapping sample_id to SampleCompensationAssignment
            - 'summary': Dict with counts and matrix usage statistics
        """
        global_matrices, sample_assignments = self._parse_compensation_from_wsp()

        # Build summary statistics
        matrix_usage: Dict[str, int] = {}
        samples_without_comp = 0

        for assignment in sample_assignments.values():
            if assignment.matrix_name:
                matrix_usage[assignment.matrix_name] = matrix_usage.get(assignment.matrix_name, 0) + 1
            else:
                samples_without_comp += 1

        summary = {
            'total_matrices': len(global_matrices),
            'samples_with_compensation': len(sample_assignments) - samples_without_comp,
            'samples_without_compensation': samples_without_comp,
            'matrix_usage': matrix_usage
        }

        return {
            'global_matrices': global_matrices,
            'sample_assignments': sample_assignments,
            'summary': summary
        }

    def scan_compensation_status_from_wsp(
        self,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, str]:
        """
        Scan compensation status using WSP-parsed assignments.

        This is more accurate than scan_compensation_status() because it uses
        the actual WSP assignments rather than trying to get compensated events.

        For unmixed data without additional compensation, this correctly
        returns 'none' (valid state) rather than 'missing' (error state).

        Args:
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            Dict mapping sample_id to status:
            - 'valid': Has compensation matrix assigned in WSP
            - 'none': No compensation assigned (valid for pure unmixed data)
            - 'error': Error reading compensation info
        """
        status: Dict[str, str] = {}

        if not self._workspace or not self._samples:
            return status

        # Parse WSP compensation info
        _, sample_assignments = self._parse_compensation_from_wsp()

        total = len(self._samples)
        logger.info(f"Scanning compensation status (WSP-based) for {total} samples...")

        for i, sample in enumerate(self._samples):
            sample_id = sample.sample_id

            if sample_id in sample_assignments:
                assignment = sample_assignments[sample_id]
                if assignment.matrix_name is not None:
                    status[sample_id] = 'valid'
                else:
                    status[sample_id] = 'none'
            else:
                # Sample not found in WSP assignments - might be missing FCS
                status[sample_id] = 'none'

            if progress_callback:
                progress_callback(i + 1, total)

        # Summary logging
        valid_count = sum(1 for s in status.values() if s == 'valid')
        none_count = sum(1 for s in status.values() if s == 'none')
        logger.info(f"Compensation scan (WSP-based) complete: {valid_count} with matrix, {none_count} without")

        # Store for later access
        self._compensation_status_wsp = status
        self._compensation_assignments = sample_assignments

        return status

    @property
    def compensation_assignments(self) -> Dict[str, SampleCompensationAssignment]:
        """Get cached compensation assignments from last WSP-based scan."""
        return getattr(self, '_compensation_assignments', {})
