"""Tests for the TBox/ABox constraint checker (align.py) (Stage 7)."""

from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation
from onto3gpp.ontology.align import (
    AlignResult,
    align_abox,
    conformance_ratio,
)
from onto3gpp.ontology.tbox import RelationTypeConstraint, TBox


def _tbox() -> TBox:
    return TBox(
        concept_types=["network_function", "procedure", "information_element"],
        relation_types=["uses", "selects", "part_of", "is_a"],
        relation_type_constraints=[
            RelationTypeConstraint("network_function", "uses", "network_function"),
            RelationTypeConstraint("network_function", "selects", "network_function"),
            RelationTypeConstraint("procedure", "uses", "information_element"),
            RelationTypeConstraint("procedure", "part_of", "procedure"),
        ],
    )


def _abox() -> ABox:
    return ABox(
        concepts=[
            ABoxConcept(id="smf", canonical="SMF", type="network_function"),
            ABoxConcept(id="upf", canonical="UPF", type="network_function"),
            ABoxConcept(id="pdu", canonical="PDU", type="information_element"),
            ABoxConcept(id="bogus", canonical="BOGUS", type="not_a_type"),
        ],
        relations=[
            ABoxRelation(source="smf", rel="selects", target="upf"),
            ABoxRelation(source="smf", rel="uses", target="pdu"),
            ABoxRelation(source="smf", rel="part_of", target="upf"),
        ],
    )


def test_align_accepts_conforming_abox():
    tbox = _tbox()
    abox = ABox(
        concepts=[
            ABoxConcept(id="smf", canonical="SMF", type="network_function"),
            ABoxConcept(id="upf", canonical="UPF", type="network_function"),
        ],
        relations=[ABoxRelation(source="smf", rel="selects", target="upf")],
    )
    result = align_abox(abox, tbox)
    assert result.errors == []
    assert result.conforming_relations == 1
    assert result.total_relations == 1


def test_align_reports_unknown_concept_type():
    tbox = _tbox()
    abox = ABox(
        concepts=[ABoxConcept(id="bogus", canonical="BOGUS", type="not_a_type")],
        relations=[],
    )
    result = align_abox(abox, tbox)
    assert any("not_a_type" in e for e in result.errors)


def test_align_reports_unknown_relation_type():
    tbox = _tbox()
    abox = ABox(
        concepts=[
            ABoxConcept(id="smf", canonical="SMF", type="network_function"),
            ABoxConcept(id="upf", canonical="UPF", type="network_function"),
        ],
        relations=[ABoxRelation(source="smf", rel="bogus_rel", target="upf")],
    )
    result = align_abox(abox, tbox)
    assert any("bogus_rel" in e for e in result.errors)


def test_align_reports_constraint_violation():
    tbox = _tbox()
    abox = ABox(
        concepts=[
            ABoxConcept(id="smf", canonical="SMF", type="network_function"),
            ABoxConcept(id="upf", canonical="UPF", type="network_function"),
        ],
        # network_function part_of network_function is not in the TBox
        relations=[ABoxRelation(source="smf", rel="part_of", target="upf")],
    )
    result = align_abox(abox, tbox)
    assert any("part_of" in e for e in result.errors)


def test_align_reports_dangling_endpoint():
    tbox = _tbox()
    abox = ABox(
        concepts=[ABoxConcept(id="smf", canonical="SMF", type="network_function")],
        relations=[ABoxRelation(source="smf", rel="uses", target="missing")],
    )
    result = align_abox(abox, tbox)
    assert any("missing" in e for e in result.errors)


def test_conformance_ratio():
    tbox = _tbox()
    abox = _abox()
    result = align_abox(abox, tbox)
    # 3 relations total; only "smf selects upf" conforms (uses->pdu is
    # network_function uses information_element, not in TBox; part_of is a
    # constraint violation). So 1/3 conforming.
    assert result.conforming_relations == 1
    assert result.total_relations == 3
    assert conformance_ratio(result) == 1 / 3


def test_conformance_ratio_empty():
    result = AlignResult(errors=[], conforming_relations=0, total_relations=0)
    assert conformance_ratio(result) == 1.0
