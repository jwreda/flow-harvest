"""
Tests for compensation matrix discovery in WSP metadata parsing.

Uses a small synthetic workspace, written the way FlowJo lays out
spilloverMatrix elements, so the tests run without the example data.
"""

import pytest

from flowkit_gui.models.wsp_metadata_parser import parse_wsp_metadata

TRANSFORMS_NS = "http://www.isac-net.org/std/Gating-ML/v2.0/transformations"
DATA_TYPE_NS = "http://www.isac-net.org/std/Gating-ML/v2.0/datatypes"


def _matrix(name, matrix_id, color=None, spectral=False, detectors=()):
    color_attr = f' color="{color}"' if color else ""
    params = "".join(
        f'<data-type:parameter data-type:name="{d}"/>' for d in detectors
    )
    return (
        f'<transforms:spilloverMatrix name="{name}" transforms:id="{matrix_id}"'
        f'{color_attr} spectral="{1 if spectral else 0}">'
        f"<data-type:parameters>{params}</data-type:parameters>"
        f"</transforms:spilloverMatrix>"
    )


def _sample(sample_id, filename, matrix=None):
    comp = (
        f'<transforms:spilloverMatrix name="{matrix}" transforms:id="{matrix}-id"/>'
        if matrix
        else ""
    )
    return (
        f"<Sample>"
        f'<DataSet sampleID="{sample_id}" uri="file:/data/{filename}"/>'
        f"{comp}"
        f'<SampleNode name="{filename}"/>'
        f"</Sample>"
    )


def _write_wsp(tmp_path, matrices, samples):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Workspace xmlns:transforms="{TRANSFORMS_NS}" xmlns:data-type="{DATA_TYPE_NS}">'
        f"<Matrices>{''.join(matrices)}</Matrices>"
        f"<SampleList>{''.join(samples)}</SampleList>"
        "</Workspace>"
    )
    wsp = tmp_path / "synthetic.wsp"
    wsp.write_text(xml, encoding="utf-8")
    return wsp


class TestCompensationDiscovery:
    def test_finds_every_matrix_with_its_properties(self, tmp_path):
        wsp = _write_wsp(
            tmp_path,
            matrices=[
                _matrix("Spleen comp", "m1", color="#FF9900", spectral=True,
                        detectors=["BV421-A", "PE-A", "APC-A"]),
                _matrix("Tumor comp", "m2", color="#3366CC",
                        detectors=["BV421-A", "PE-A"]),
                _matrix("Uncolored", "m3"),
            ],
            samples=[_sample("1", "Sample_01.fcs", matrix="Spleen comp")],
        )

        meta = parse_wsp_metadata(wsp)

        by_name = {m.name: m for m in meta.compensation_matrices}
        assert set(by_name) == {"Spleen comp", "Tumor comp", "Uncolored"}

        spleen = by_name["Spleen comp"]
        assert spleen.matrix_id == "m1"
        assert spleen.color == "#FF9900"
        assert spleen.spectral is True
        assert spleen.detectors == ["BV421-A", "PE-A", "APC-A"]

        tumor = by_name["Tumor comp"]
        assert tumor.color == "#3366CC"
        assert tumor.spectral is False
        assert tumor.detectors == ["BV421-A", "PE-A"]

        assert by_name["Uncolored"].color is None
        assert by_name["Uncolored"].detectors == []

    def test_per_sample_assignment_follows_the_workspace(self, tmp_path):
        wsp = _write_wsp(
            tmp_path,
            matrices=[
                _matrix("Spleen comp", "m1", detectors=["PE-A"]),
                _matrix("Tumor comp", "m2", detectors=["PE-A"]),
            ],
            samples=[
                _sample("1", "Sample_01.fcs", matrix="Spleen comp"),
                _sample("2", "Sample_02.fcs", matrix="Tumor comp"),
                _sample("3", "Sample_03.fcs", matrix="Spleen comp"),
                _sample("4", "Sample_04.fcs"),
            ],
        )

        meta = parse_wsp_metadata(wsp)

        assert meta.sample_compensation == {
            "Sample_01.fcs": "Spleen comp",
            "Sample_02.fcs": "Tumor comp",
            "Sample_03.fcs": "Spleen comp",
            "Sample_04.fcs": None,
        }

    def test_url_encoded_filenames_are_decoded(self, tmp_path):
        wsp = _write_wsp(
            tmp_path,
            matrices=[_matrix("Only comp", "m1")],
            samples=[_sample("1", "Plate%20A%2001.fcs", matrix="Only comp")],
        )

        meta = parse_wsp_metadata(wsp)

        assert meta.sample_compensation == {"Plate A 01.fcs": "Only comp"}
        assert "Plate A 01.fcs" in meta.samples

    def test_workspace_without_matrices(self, tmp_path):
        wsp = _write_wsp(
            tmp_path,
            matrices=[],
            samples=[_sample("1", "Sample_01.fcs")],
        )

        meta = parse_wsp_metadata(wsp)

        assert meta.compensation_matrices == []
        assert meta.sample_compensation == {"Sample_01.fcs": None}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_wsp_metadata(tmp_path / "nope.wsp")
