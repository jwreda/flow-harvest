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
from typing import Dict, List, Optional, Tuple, Any, Set
import gc
import re
import flowkit as fk
import pandas as pd
import numpy as np

from ..utils.logging_config import get_logger
from ..config import (
    SYSTEM_KEYWORD_PREFIXES,
    SYSTEM_KEYWORD_EXACT,
    SYSTEM_KEYWORD_SUFFIXES,
)

logger = get_logger("workspace_model")


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

    def get_custom_keywords(self) -> Dict[str, str]:
        """Returns only user-defined keywords, filtering out system keys."""
        result = {}
        for k, v in self.keywords.items():
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
        self._gates: List[GateInfo] = []
        self._channels: List[str] = []
        self._channel_info: List[ChannelInfo] = []
        # Track which gates exist in which samples (not all gates exist in all samples)
        self._sample_gates: Dict[str, Set[str]] = {}  # sample_id → set of gate_ids
        # Caches for performance optimization
        self._event_cache: Dict[str, np.ndarray] = {}  # "sample_id:source" -> events array
        self._membership_cache: Dict[Tuple[str, str], np.ndarray] = {}  # (sample_id, gate_id) -> membership
        # Track which samples have been analyzed (for on-demand analysis)
        self._analyzed_samples: Set[str] = set()

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

    def clear_cache(self) -> None:
        """Clear all cached event and membership data to free memory."""
        cache_size = len(self._event_cache) + len(self._membership_cache)
        self._event_cache.clear()
        self._membership_cache.clear()
        self._analyzed_samples.clear()  # Clear analysis tracking too
        gc.collect()  # Force garbage collection to release memory
        if cache_size > 0:
            logger.info(f"Cleared {cache_size} cached items and ran garbage collection")

    def _ensure_sample_analyzed(self, sample_id: str) -> None:
        """Ensure a sample has been analyzed (on-demand analysis).

        FlowKit requires samples to be analyzed before gate membership
        or statistics can be computed. This method ensures analysis
        happens lazily, only when needed.
        """
        if sample_id in self._analyzed_samples:
            return

        if not self._workspace:
            return

        try:
            logger.debug(f"On-demand analysis for sample: {sample_id}")
            self._workspace.analyze_samples(sample_id=sample_id)
            self._analyzed_samples.add(sample_id)
            logger.debug(f"Successfully analyzed sample: {sample_id}")
        except Exception as e:
            logger.warning(f"Failed to analyze sample {sample_id}: {e}")
            # Still mark as attempted to avoid repeated failures
            self._analyzed_samples.add(sample_id)

    def _get_cached_events(self, sample_id: str, source: str) -> np.ndarray:
        """Get events from cache or load and cache them."""
        cache_key = f"{sample_id}:{source}"
        if cache_key not in self._event_cache:
            # Ensure sample is analyzed before getting events (on-demand)
            self._ensure_sample_analyzed(sample_id)
            sample = self._workspace.get_sample(sample_id)
            self._event_cache[cache_key] = sample.get_events(source=source)
            logger.debug(f"Cached events for {cache_key}")
        return self._event_cache[cache_key]

    def _get_gate_name_from_id(self, gate_id: str) -> str:
        """Extract gate name from full-path gate_id (e.g., 'Cells/Live/CD45+' -> 'CD45+')."""
        return gate_id.rsplit('/', 1)[-1] if '/' in gate_id else gate_id

    def _get_cached_membership(self, sample_id: str, gate_id: str) -> np.ndarray:
        """Get gate membership from cache or compute and cache it."""
        cache_key = (sample_id, gate_id)
        if cache_key not in self._membership_cache:
            # Ensure sample is analyzed before getting membership (on-demand)
            self._ensure_sample_analyzed(sample_id)
            fk_path = self.get_fk_gate_path(gate_id)
            # Extract gate name from full-path gate_id for FlowKit API
            gate_name = self._get_gate_name_from_id(gate_id)
            self._membership_cache[cache_key] = self._workspace.get_gate_membership(
                sample_id, gate_name, gate_path=fk_path
            )
            logger.debug(f"Cached membership for sample='{sample_id}', gate='{gate_id}'")
        return self._membership_cache[cache_key]

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
                                parameters=params,
                                fk_gate_path=gate_path_tuple  # Store FlowKit's path for API calls
                            )
                    except Exception as e:
                        # Log when gates fail to load (was silently skipped before)
                        logger.warning(f"Failed to load gate '{gate_name}' at path {gate_path_tuple}: {type(e).__name__}: {e}")
                        continue
            except Exception:
                # Sample might not have gates defined
                continue

        # Convert to list (preserves order from dict in Python 3.7+)
        self._gates = list(all_gate_info.values())

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
        for sample in self._samples:
            if sample.sample_id == sample_id:
                return sample
        return None

    def get_fk_gate_path(self, gate_id: str) -> Optional[Tuple[str, ...]]:
        """Get the FlowKit gate_path tuple for API calls."""
        for gate in self._gates:
            if gate.gate_id == gate_id:
                return gate.fk_gate_path
        return None

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
        reference_gate = None
        for gate in self._gates:
            if gate.gate_id == reference_gate_id:
                reference_gate = gate
                break

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
                    if sample_id in self._analyzed_samples:
                        logger.debug(f"Sample {sample_id} already analyzed, skipping")
                        continue

                    logger.debug(f"Analyzing sample: {sample_id}")
                    self._workspace.analyze_samples(sample_id=sample_id)
                    self._analyzed_samples.add(sample_id)

                    if progress_callback:
                        progress_callback(batch_start + i + 1, total)
                except Exception as e:
                    logger.error(f"analyze_sample FAILED for {sample_id}: {type(e).__name__}: {e}")
                    import traceback
                    logger.debug(f"Full traceback:\n{traceback.format_exc()}")
                    # Mark as attempted to avoid retrying
                    self._analyzed_samples.add(sample_id)
                    continue

            # Force garbage collection between batches to release memory
            gc.collect()
            logger.debug(f"Garbage collection after batch {batch_num}")

        logger.info(f"Successfully analyzed {len(self._analyzed_samples)} samples")

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

            count = int(result.sum()) if hasattr(result, 'sum') else len(result[result])
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
        for gate in self._gates:
            if gate.gate_id == gate_id and gate.depth > 0:
                # Construct parent gate_id from path (e.g., "Cells/Live/CD45+" -> "Cells/Live")
                parent_path = gate.path[:-1]  # All but last element
                if parent_path:
                    parent_gate_id = "/".join(parent_path)
                    # Find the parent gate's fk_gate_path
                    parent_fk_path = self.get_fk_gate_path(parent_gate_id)
                    return parent_gate_id, parent_fk_path
        return None, None

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
                # Force compensated data (cached)
                logger.debug("Using COMP (compensated) data as requested")
                events = self._get_cached_events(sample_id, 'comp')
                source_used = 'comp'

            else:  # DataSource.AUTO
                # Check cache first, then try compensated, fallback to raw
                comp_cache_key = f"{sample_id}:comp"
                raw_cache_key = f"{sample_id}:raw"

                if comp_cache_key in self._event_cache:
                    events = self._event_cache[comp_cache_key]
                    source_used = 'comp'
                elif raw_cache_key in self._event_cache:
                    events = self._event_cache[raw_cache_key]
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
            all_labels = list(sample.pnn_labels)
            logger.debug(f"Available channels: {all_labels}")

            if channels:
                # Filter to requested channels
                channel_indices = []
                found_channels = []
                missing_channels = []

                for ch in channels:
                    if ch in all_labels:
                        channel_indices.append(all_labels.index(ch))
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
