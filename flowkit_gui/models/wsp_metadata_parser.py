"""
WSP Metadata Parser - Lightweight parser for FlowJo workspace XML.

This module extracts metadata from WSP files WITHOUT loading FCS data,
enabling fast workspace preview for large datasets (70+ samples).

Extracted data includes:
- Sample names and IDs
- Group membership
- Gate hierarchy
- Compensation matrices
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import unquote
from lxml import etree

from ..utils.logging_config import get_logger

logger = get_logger("wsp_metadata_parser")


@dataclass
class SampleMetadata:
    """Metadata for a single sample extracted from WSP."""
    sample_id: str  # FlowKit uses filename as sample_id
    name: str  # Display name
    fcs_path: Optional[str] = None  # URI from WSP
    wsp_sample_id: Optional[str] = None  # Numeric ID in WSP
    event_count: Optional[int] = None  # From WSP if available


@dataclass
class GroupMetadata:
    """Metadata for a sample group."""
    name: str
    sample_ids: List[str] = field(default_factory=list)


@dataclass
class GateMetadata:
    """Metadata for a gate extracted from WSP."""
    gate_id: str  # Unique identifier
    name: str
    path: Tuple[str, ...]  # Full path from root
    parent_id: Optional[str] = None
    gate_type: str = "Unknown"
    owning_group: Optional[str] = None  # Group that owns this gate


@dataclass
class CompensationMetadata:
    """Metadata for a compensation matrix."""
    name: str
    matrix_id: str
    color: Optional[str] = None
    spectral: bool = False
    detectors: List[str] = field(default_factory=list)


@dataclass
class WSPMetadata:
    """Complete metadata extracted from a WSP file."""
    samples: Dict[str, SampleMetadata]  # sample_id -> metadata
    groups: Dict[str, GroupMetadata]  # group_name -> metadata
    gates: List[GateMetadata]
    compensation_matrices: List[CompensationMetadata]
    sample_compensation: Dict[str, Optional[str]]  # sample_id -> matrix_name or None
    wsp_path: Path


class WSPMetadataParser:
    """
    Lightweight parser for FlowJo WSP files.

    Extracts metadata without loading FCS data, enabling fast preview
    of large workspaces.

    Usage:
        parser = WSPMetadataParser()
        metadata = parser.parse("/path/to/workspace.wsp")

        # Access samples without loading FCS
        for sample_id, sample in metadata.samples.items():
            print(f"{sample.name}: {sample.fcs_path}")

        # Access groups
        for group_name, group in metadata.groups.items():
            print(f"Group {group_name}: {len(group.sample_ids)} samples")
    """

    # XML namespaces used in FlowJo WSP files
    TRANSFORMS_NS = '{http://www.isac-net.org/std/Gating-ML/v2.0/transformations}'
    DATA_TYPE_NS = '{http://www.isac-net.org/std/Gating-ML/v2.0/datatypes}'
    GATING_NS = '{http://www.isac-net.org/std/Gating-ML/v2.0/gating}'

    def __init__(self):
        self._root: Optional[etree._Element] = None
        self._wsp_path: Optional[Path] = None

    def parse(self, wsp_path: str | Path) -> WSPMetadata:
        """
        Parse a WSP file and extract all metadata.

        Args:
            wsp_path: Path to the FlowJo workspace file

        Returns:
            WSPMetadata containing all extracted information

        Raises:
            FileNotFoundError: If WSP file doesn't exist
            etree.XMLSyntaxError: If WSP is not valid XML
        """
        self._wsp_path = Path(wsp_path)
        if not self._wsp_path.exists():
            raise FileNotFoundError(f"WSP file not found: {wsp_path}")

        logger.info(f"Parsing WSP metadata: {self._wsp_path.name}")

        # Parse XML
        tree = etree.parse(str(self._wsp_path))
        self._root = tree.getroot()

        # Extract all metadata
        samples = self._parse_samples()
        groups = self._parse_groups(samples)
        gates = self._parse_gates()
        comp_matrices, sample_comp = self._parse_compensation()

        logger.info(
            f"WSP metadata parsed: {len(samples)} samples, "
            f"{len(groups)} groups, {len(gates)} gates, "
            f"{len(comp_matrices)} compensation matrices"
        )

        return WSPMetadata(
            samples=samples,
            groups=groups,
            gates=gates,
            compensation_matrices=comp_matrices,
            sample_compensation=sample_comp,
            wsp_path=self._wsp_path
        )

    def _parse_samples(self) -> Dict[str, SampleMetadata]:
        """Parse sample information from SampleList."""
        samples: Dict[str, SampleMetadata] = {}

        sample_list = self._root.find('.//SampleList')
        if sample_list is None:
            logger.warning("No SampleList found in WSP")
            return samples

        for sample_el in sample_list.findall('.//Sample'):
            metadata = self._parse_sample_element(sample_el)
            if metadata:
                samples[metadata.sample_id] = metadata

        logger.debug(f"Parsed {len(samples)} samples from WSP")
        return samples

    def _parse_sample_element(self, sample_el: etree._Element) -> Optional[SampleMetadata]:
        """Parse a single Sample element."""
        try:
            # Get DataSet element which contains the file reference
            dataset_el = sample_el.find('.//DataSet')
            if dataset_el is None:
                return None

            wsp_sample_id = dataset_el.get('sampleID')
            uri = dataset_el.get('uri', '')

            # Extract filename from URI (FlowKit uses filename as sample_id)
            if uri:
                # URI format: "file:/path/to/A5%20M5.fcs"
                filename = unquote(uri.split('/')[-1]) if '/' in uri else unquote(uri)
            else:
                filename = f"sample_{wsp_sample_id}"

            # Get sample name from SampleNode if available
            sample_node = sample_el.find('.//SampleNode')
            if sample_node is not None:
                name = sample_node.get('name', filename)
            else:
                name = filename

            # Try to get event count from Keywords
            event_count = None
            keywords_el = sample_el.find('.//Keywords')
            if keywords_el is not None:
                for kw in keywords_el.findall('.//Keyword'):
                    kw_name = kw.get('name', '')
                    if kw_name == '$TOT':
                        try:
                            event_count = int(kw.get('value', '0'))
                        except ValueError:
                            pass
                        break

            return SampleMetadata(
                sample_id=filename,
                name=name,
                fcs_path=uri,
                wsp_sample_id=wsp_sample_id,
                event_count=event_count
            )

        except Exception as e:
            logger.warning(f"Failed to parse sample element: {e}")
            return None

    def _parse_groups(self, samples: Dict[str, SampleMetadata]) -> Dict[str, GroupMetadata]:
        """Parse group membership from Groups section."""
        groups: Dict[str, GroupMetadata] = {}

        # Build lookup from WSP sample ID to FlowKit sample ID
        wsp_to_flowkit: Dict[str, str] = {}
        for sample_id, meta in samples.items():
            if meta.wsp_sample_id:
                wsp_to_flowkit[meta.wsp_sample_id] = sample_id

        groups_section = self._root.find('.//Groups')
        if groups_section is None:
            logger.debug("No Groups section found in WSP")
            return groups

        for group_node in groups_section.findall('.//GroupNode'):
            group_name = group_node.get('name', 'Unnamed Group')

            # Skip special groups
            if group_name in ('All Samples', 'Compensation'):
                continue

            sample_ids: List[str] = []

            # Parse SampleRefs within the group
            for sample_ref in group_node.findall('.//SampleRef'):
                wsp_id = sample_ref.get('sampleID')
                if wsp_id and wsp_id in wsp_to_flowkit:
                    sample_ids.append(wsp_to_flowkit[wsp_id])

            if sample_ids:  # Only add non-empty groups
                groups[group_name] = GroupMetadata(
                    name=group_name,
                    sample_ids=sample_ids
                )

        logger.debug(f"Parsed {len(groups)} groups from WSP")
        return groups

    def _parse_gates(self) -> List[GateMetadata]:
        """Parse gate hierarchy from Groups section."""
        gates: List[GateMetadata] = []
        seen_gate_ids: set = set()

        # Gates are defined within GroupNode elements
        groups_section = self._root.find('.//Groups')
        if groups_section is None:
            return gates

        for group_node in groups_section.findall('.//GroupNode'):
            group_name = group_node.get('name', '')

            # Find all Population elements (gates)
            for population in group_node.findall('.//Population'):
                gate = self._parse_population_element(population, (), group_name)
                if gate and gate.gate_id not in seen_gate_ids:
                    gates.append(gate)
                    seen_gate_ids.add(gate.gate_id)

                    # Parse nested populations recursively
                    self._parse_nested_populations(
                        population, (gate.name,), group_name, gates, seen_gate_ids
                    )

        logger.debug(f"Parsed {len(gates)} gates from WSP")
        return gates

    def _parse_population_element(
        self,
        population: etree._Element,
        parent_path: Tuple[str, ...],
        owning_group: str
    ) -> Optional[GateMetadata]:
        """Parse a single Population element into GateMetadata."""
        try:
            name = population.get('name', 'Unnamed Gate')
            full_path = parent_path + (name,)
            gate_id = '/'.join(full_path)

            # Try to determine gate type from Gate element
            gate_type = "Unknown"
            gate_el = population.find('.//Gate')
            if gate_el is not None:
                # Check for specific gate types
                for gtype in ['PolygonGate', 'RectangleGate', 'EllipsoidGate',
                              'BooleanGate', 'QuadrantGate', 'RangeGate']:
                    if gate_el.find(f'.//{self.GATING_NS}{gtype}') is not None:
                        gate_type = gtype.replace('Gate', '')
                        break
                    # Also check without namespace
                    if gate_el.find(f'.//{gtype}') is not None:
                        gate_type = gtype.replace('Gate', '')
                        break

            parent_id = '/'.join(parent_path) if parent_path else None

            return GateMetadata(
                gate_id=gate_id,
                name=name,
                path=full_path,
                parent_id=parent_id,
                gate_type=gate_type,
                owning_group=owning_group
            )

        except Exception as e:
            logger.warning(f"Failed to parse population element: {e}")
            return None

    def _parse_nested_populations(
        self,
        parent_el: etree._Element,
        parent_path: Tuple[str, ...],
        owning_group: str,
        gates: List[GateMetadata],
        seen_gate_ids: set
    ) -> None:
        """Recursively parse nested Population elements."""
        for population in parent_el.findall('./Population'):
            gate = self._parse_population_element(population, parent_path, owning_group)
            if gate and gate.gate_id not in seen_gate_ids:
                gates.append(gate)
                seen_gate_ids.add(gate.gate_id)

                # Recurse into children
                self._parse_nested_populations(
                    population,
                    parent_path + (gate.name,),
                    owning_group,
                    gates,
                    seen_gate_ids
                )

    def _parse_compensation(self) -> Tuple[
        List[CompensationMetadata],
        Dict[str, Optional[str]]
    ]:
        """Parse compensation matrices and per-sample assignments."""
        matrices: List[CompensationMetadata] = []
        sample_comp: Dict[str, Optional[str]] = {}

        # Parse global matrices from Matrices section
        matrices_section = self._root.find('.//Matrices')
        if matrices_section is not None:
            for matrix_el in matrices_section.findall(f'.//{self.TRANSFORMS_NS}spilloverMatrix'):
                matrix = self._parse_matrix_element(matrix_el)
                if matrix:
                    matrices.append(matrix)

        logger.debug(f"Parsed {len(matrices)} compensation matrices")

        # Parse per-sample compensation assignments
        sample_list = self._root.find('.//SampleList')
        if sample_list is not None:
            for sample_el in sample_list.findall('.//Sample'):
                dataset_el = sample_el.find('.//DataSet')
                if dataset_el is None:
                    continue

                uri = dataset_el.get('uri', '')
                if uri:
                    filename = unquote(uri.split('/')[-1]) if '/' in uri else unquote(uri)
                else:
                    continue

                # Check for compensation assignment
                matrix_el = sample_el.find(f'.//{self.TRANSFORMS_NS}spilloverMatrix')
                if matrix_el is not None:
                    matrix_name = matrix_el.get('name', '')
                    sample_comp[filename] = matrix_name if matrix_name else None
                else:
                    sample_comp[filename] = None

        return matrices, sample_comp

    def _parse_matrix_element(self, matrix_el: etree._Element) -> Optional[CompensationMetadata]:
        """Parse a spilloverMatrix element."""
        try:
            name = matrix_el.get('name', 'Unknown')
            matrix_id = matrix_el.get(f'{self.TRANSFORMS_NS}id', '')
            color = matrix_el.get('color')
            spectral = matrix_el.get('spectral', '0') == '1'

            # Parse detector list
            detectors: List[str] = []
            params_el = matrix_el.find(f'.//{self.DATA_TYPE_NS}parameters')
            if params_el is not None:
                for param_el in params_el.findall(f'.//{self.DATA_TYPE_NS}parameter'):
                    param_name = param_el.get(f'{self.DATA_TYPE_NS}name', '')
                    if param_name:
                        detectors.append(param_name)

            return CompensationMetadata(
                name=name,
                matrix_id=matrix_id,
                color=color,
                spectral=spectral,
                detectors=detectors
            )

        except Exception as e:
            logger.warning(f"Failed to parse compensation matrix: {e}")
            return None


def parse_wsp_metadata(wsp_path: str | Path) -> WSPMetadata:
    """
    Convenience function to parse WSP metadata.

    Args:
        wsp_path: Path to the FlowJo workspace file

    Returns:
        WSPMetadata containing all extracted information
    """
    parser = WSPMetadataParser()
    return parser.parse(wsp_path)
