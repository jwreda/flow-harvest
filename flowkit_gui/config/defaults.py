"""
Default configuration values for FlowKit GUI.

This module centralizes configurable values that were previously hardcoded,
making the application work with any WSP/FCS files.
"""

# System keyword prefixes to filter out when extracting custom keywords
# These are standard FCS file metadata fields, not user-defined keywords
SYSTEM_KEYWORD_PREFIXES = (
    '$',      # Standard FCS keywords (e.g., $FIL, $DATE, $PAR)
    'FCS',    # FCS version info
    'SPILL',  # Spillover/compensation matrix
    'COMP',   # Compensation-related
    'LASER',  # Laser settings
    'FSC',    # Forward scatter parameters
    # Parameter keywords P1-P35 (covers most cytometers)
    'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9',
    'P10', 'P11', 'P12', 'P13', 'P14', 'P15', 'P16', 'P17', 'P18', 'P19',
    'P20', 'P21', 'P22', 'P23', 'P24', 'P25', 'P26', 'P27', 'P28', 'P29',
    'P30', 'P31', 'P32', 'P33', 'P34', 'P35',
)

# Exact system keyword matches to filter out
SYSTEM_KEYWORD_EXACT = {
    # Unique identifiers (not user-meaningful)
    'GUID',
    # FCS structure keywords
    'BEGINDATA', 'ENDDATA', 'BEGINANALYSIS', 'ENDANALYSIS',
    'BEGINSTEXT', 'ENDSTEXT', 'BEGINTEXT', 'ENDTEXT',
    'BYTEORD', 'DATATYPE', 'MODE', 'NEXTDATA', 'TOT', 'PAR',
    # Timing keywords
    'BTIM', 'ETIM', 'DATE', 'TIMESTEP',
    # Cytometer/instrument keywords
    'CYT', 'CYTSN', 'INST', 'OP', 'SRC',
    # Sample/experiment metadata (VOL intentionally NOT filtered - needed for normalization)
    'FIL', 'PLATENAME', 'PLATEID',
    # FlowJo/application keywords
    'APPLY COMPENSATION', 'WINDOW EXTENSION', 'THRESHOLD',
    'USERSETTINGNAME', 'CHARSET', 'CREATOR', 'TUBENAME',
    'GROUPNAME', 'PLATEROWS', 'PLATECOLS', 'FILENAME',
    'FJ_FCS_VERSION',
}

# System keyword suffixes to filter out
SYSTEM_KEYWORD_SUFFIXES = (
    'DISPLAY',  # Display settings (e.g., P1DISPLAY)
)

# Channel suffixes for standard flow cytometry parameters
# Used to identify fluorescence channels vs scatter/time
CHANNEL_SUFFIXES = ('-A', '-H', '-W')

# Prefixes for scatter and time channels (excluded from marker selection)
SCATTER_PREFIXES = ('FSC', 'SSC', 'Time')

# FCS file discovery settings
FCS_MAX_SEARCH_DEPTH = 5  # Maximum directory depth for recursive FCS search
FCS_EXTENSIONS = ('.fcs', '.FCS', '.Fcs')  # Supported FCS file extensions

# =============================================================================
# Memory Management Settings
# =============================================================================
# These settings control memory usage for large experiments (70+ samples)

# Total cache memory limit in megabytes
# Split between event cache (70%) and membership cache (30%)
CACHE_MEMORY_LIMIT_MB = 4096  # 4GB default

# Batch size for sample analysis
# Smaller batches use less peak memory but take slightly longer
BATCH_SIZE = 10  # Samples per batch

# Garbage collection interval (number of samples between gc.collect() calls)
GC_COLLECT_INTERVAL = 5

# Streaming export threshold
# Use write_only mode when total rows exceed this threshold
STREAMING_EXPORT_ROW_THRESHOLD = 5000

# Maximum workers for parallel sample analysis
# None = auto-detect (min of 4 and CPU count)
MAX_PARALLEL_WORKERS = None
