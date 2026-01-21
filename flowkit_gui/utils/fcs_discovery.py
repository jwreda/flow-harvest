"""
FCS File Discovery - Recursive FCS file discovery utilities.

This module provides robust FCS file discovery that handles:
- Nested directory structures (Raw/Unmixed/samples/Group_001/etc.)
- Case-insensitive file extension matching (.fcs, .FCS, .Fcs)
- Processing level detection from path names
- Duplicate filename tracking
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set
import re

from ..utils.logging_config import get_logger

logger = get_logger("fcs_discovery")


class ProcessingLevel(Enum):
    """Processing level inferred from directory path."""
    RAW = "raw"
    UNMIXED = "unmixed"
    COMPENSATED = "compensated"
    UNKNOWN = "unknown"


# Case-insensitive FCS extensions
FCS_EXTENSIONS = {'.fcs', '.FCS', '.Fcs'}

# Maximum search depth to prevent infinite recursion
DEFAULT_MAX_DEPTH = 5

# Patterns for detecting processing level from path
PROCESSING_PATTERNS = {
    ProcessingLevel.RAW: re.compile(r'\b(raw|unprocessed)\b', re.IGNORECASE),
    ProcessingLevel.UNMIXED: re.compile(r'\b(unmixed|unmix)\b', re.IGNORECASE),
    ProcessingLevel.COMPENSATED: re.compile(r'\b(comp|compensated)\b', re.IGNORECASE),
}


@dataclass
class DiscoveryResult:
    """Result of FCS file discovery."""

    # All discovered FCS files
    fcs_files: List[Path] = field(default_factory=list)

    # Files grouped by processing level
    by_processing_level: Dict[ProcessingLevel, List[Path]] = field(default_factory=dict)

    # Filename -> Path mapping (for FlowKit file matching)
    # Uses lowercase filename as key for case-insensitive matching
    filename_map: Dict[str, Path] = field(default_factory=dict)

    # Filenames that appear multiple times (potential conflicts)
    duplicate_filenames: Dict[str, List[Path]] = field(default_factory=dict)

    # Root directory searched
    root_dir: Optional[Path] = None

    # Maximum depth reached
    max_depth_searched: int = 0

    @property
    def total_count(self) -> int:
        """Total number of unique FCS files found."""
        return len(self.fcs_files)

    @property
    def has_duplicates(self) -> bool:
        """True if any filenames appear multiple times."""
        return len(self.duplicate_filenames) > 0

    def get_files_for_level(self, level: ProcessingLevel) -> List[Path]:
        """Get all files for a specific processing level."""
        return self.by_processing_level.get(level, [])

    def get_preferred_files(self) -> List[Path]:
        """
        Get the best files to use, preferring Unmixed > Compensated > Raw > Unknown.

        This helps users when multiple processing levels exist.
        """
        for level in [ProcessingLevel.UNMIXED, ProcessingLevel.COMPENSATED,
                      ProcessingLevel.RAW, ProcessingLevel.UNKNOWN]:
            files = self.get_files_for_level(level)
            if files:
                return files
        return []

    def get_summary(self) -> str:
        """Get a human-readable summary of discovery results."""
        lines = [f"Found {self.total_count} FCS files in {self.root_dir}"]

        for level, files in self.by_processing_level.items():
            if files:
                lines.append(f"  - {level.value}: {len(files)} files")

        if self.has_duplicates:
            lines.append(f"  - Warning: {len(self.duplicate_filenames)} duplicate filenames")

        return "\n".join(lines)


def _detect_processing_level(path: Path) -> ProcessingLevel:
    """
    Detect processing level from a file's directory path.

    Examines parent directories for keywords like 'Raw', 'Unmixed', 'Compensated'.
    """
    path_str = str(path.parent)

    for level, pattern in PROCESSING_PATTERNS.items():
        if pattern.search(path_str):
            return level

    return ProcessingLevel.UNKNOWN


def _is_fcs_file(path: Path) -> bool:
    """
    Check if path is an FCS file (case-insensitive extension check).

    Excludes macOS resource fork files (._filename.fcs) which contain
    macOS metadata, not FCS data. These files cause FlowKit parsing errors.
    """
    # Skip macOS resource fork files (._filename.fcs)
    if path.name.startswith('._'):
        return False
    return path.suffix.lower() == '.fcs'


def discover_fcs_files(
    root_dir: str | Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    extensions: Optional[Set[str]] = None
) -> DiscoveryResult:
    """
    Recursively discover FCS files in a directory.

    Args:
        root_dir: Directory to search
        max_depth: Maximum directory depth to search (default 5)
        extensions: Set of extensions to match (default: {'.fcs'}, case-insensitive)

    Returns:
        DiscoveryResult with all discovered files and metadata
    """
    root_path = Path(root_dir)
    result = DiscoveryResult(root_dir=root_path)

    if not root_path.exists():
        logger.warning(f"Root directory does not exist: {root_path}")
        return result

    if not root_path.is_dir():
        logger.warning(f"Root path is not a directory: {root_path}")
        return result

    # Initialize processing level buckets
    for level in ProcessingLevel:
        result.by_processing_level[level] = []

    # Track seen filenames (lowercase for case-insensitive matching)
    seen_filenames: Dict[str, List[Path]] = {}

    def search_directory(dir_path: Path, current_depth: int):
        """Recursively search a directory for FCS files."""
        if current_depth > max_depth:
            return

        result.max_depth_searched = max(result.max_depth_searched, current_depth)

        try:
            for entry in dir_path.iterdir():
                if entry.is_file() and _is_fcs_file(entry):
                    # Found an FCS file
                    result.fcs_files.append(entry)

                    # Detect processing level
                    level = _detect_processing_level(entry)
                    result.by_processing_level[level].append(entry)

                    # Track by filename (lowercase for case-insensitive)
                    filename_key = entry.name.lower()
                    if filename_key not in seen_filenames:
                        seen_filenames[filename_key] = []
                    seen_filenames[filename_key].append(entry)

                elif entry.is_dir() and not entry.name.startswith('.'):
                    # Recurse into subdirectory (skip hidden directories)
                    search_directory(entry, current_depth + 1)

        except PermissionError as e:
            logger.warning(f"Permission denied accessing: {dir_path}")
        except Exception as e:
            logger.warning(f"Error scanning directory {dir_path}: {e}")

    # Start recursive search
    logger.info(f"Searching for FCS files in: {root_path} (max depth: {max_depth})")
    search_directory(root_path, 0)

    # Build filename map and track duplicates
    for filename_key, paths in seen_filenames.items():
        if len(paths) == 1:
            # Unique filename - add to map
            result.filename_map[filename_key] = paths[0]
        else:
            # Duplicate filename - track it
            result.duplicate_filenames[filename_key] = paths
            logger.warning(f"Duplicate filename '{paths[0].name}' found in {len(paths)} locations")

    logger.info(f"Discovery complete: {result.get_summary()}")
    return result


def resolve_fcs_file(
    filename: str,
    discovery_result: DiscoveryResult,
    preferred_level: Optional[ProcessingLevel] = None
) -> Optional[Path]:
    """
    Resolve a filename to a full path using discovery results.

    Handles duplicate filenames by preferring a specific processing level.

    Args:
        filename: FCS filename to resolve (e.g., "A1 M1.fcs")
        discovery_result: Result from discover_fcs_files()
        preferred_level: Preferred processing level if duplicates exist

    Returns:
        Full path to the FCS file, or None if not found
    """
    filename_key = filename.lower()

    # Check for unique match
    if filename_key in discovery_result.filename_map:
        return discovery_result.filename_map[filename_key]

    # Check for duplicates
    if filename_key in discovery_result.duplicate_filenames:
        paths = discovery_result.duplicate_filenames[filename_key]

        if preferred_level:
            # Filter by preferred level
            for path in paths:
                if _detect_processing_level(path) == preferred_level:
                    return path

        # Return first match if no preferred level or no match for preferred level
        logger.warning(f"Returning first of {len(paths)} duplicates for '{filename}'")
        return paths[0] if paths else None

    return None


def get_fcs_file_list(
    discovery_result: DiscoveryResult,
    processing_level: Optional[ProcessingLevel] = None
) -> List[str]:
    """
    Get list of FCS file paths as strings for FlowKit.

    Args:
        discovery_result: Result from discover_fcs_files()
        processing_level: Optional filter by processing level

    Returns:
        List of file paths as strings
    """
    if processing_level:
        files = discovery_result.get_files_for_level(processing_level)
    else:
        files = discovery_result.fcs_files

    return [str(f) for f in files]
