from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_publication_funding_review.py"
SPEC = importlib.util.spec_from_file_location("funding_review", SCRIPT)
assert SPEC and SPEC.loader
funding_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(funding_review)


def test_funding_entities_are_extracted_only_from_bounded_region() -> None:
    text = """Department of Neurology, China 2 Department, 215123
ABSTRACT
This study investigates Nav1.6. The recordings used pClamp10.3 software.
\f
ACKNOWLEDGEMENTS
This work was supported by the National Natural Science Foundation of China
(81571061, 82101275, 82101661, 81870897 and 81901296), Liaoning Provincial
Key R&D Program (2019020048- JH2/103), Liaoning Revitalization Talents Program
(XLYC1902044), Natural Science Foundation of Jiangsu Province (BK20181436),
Guangdong Key Project (2018B030335001), and Team Innovation Funding Program
of the Second Affiliated Hospital of Soochow University (XKTJ- TD20203).
CONFLICT OF INTEREST
The authors declare no conflict of interest.
REFERENCES
China 2 Department received a grant in a cited article.
"""

    normalized = funding_review.normalize_pdf_text(text)
    regions = funding_review.extract_evidence(normalized)

    assert len(regions) == 1
    assert regions[0]["region_type"] == "acknowledgements_section"
    focus = funding_review.funding_focus(regions[0]["evidence_text"])
    identifiers = funding_review.grant_ids(focus)
    assert "2019020048-JH2/103" in identifiers
    assert "XKTJ-TD20203" in identifiers
    assert "215123" not in identifiers
    assert "pClamp10.3" not in identifiers
    names = " ".join(item["funder_name_raw"] for item in funding_review.funders(focus))
    assert "China 2 Department" not in names


def test_explicit_no_funding_statement_is_a_bounded_fallback_region() -> None:
    text = (
        "Results\nThe intervention changed the outcome.\n"
        "This research received no external funding.\n"
        "References\nFunding patterns in medicine."
    )

    regions = funding_review.extract_evidence(text)

    assert len(regions) == 1
    assert regions[0]["region_type"] == "explicit_statement_region"
    assert regions[0]["explicit_no_funding"] is True
    assert "Funding patterns in medicine" not in regions[0]["evidence_text"]


def test_loose_reference_and_affiliation_mentions_do_not_create_regions() -> None:
    text = """Department of Foundation Medicine, Example University
INTRODUCTION
Prior work was supported by the National Science Foundation.
REFERENCES
1. Smith A. Grant funding and outcomes. 2021.
"""

    assert funding_review.extract_evidence(text) == []


def test_right_column_acknowledgement_beats_interleaved_front_page_sidebar() -> None:
    text = """Funding information
This work was supported by National Natural Science Foundation of China (81571061),
prose ducing text (2019020048- ducing).
\f
left-column methods text                         AC K N OW L E D G E M E N T S
more methods text                                This work was supported by the National Natural Science
left-column magni-                               Foundation of China (81571061) and Liaoning Program
software pClamp10.3                              supported project
postal code 215123                               (2019020048- JH2/103).
left-column methods text                         C O N F L I C T O F I N T E R E S T
"""

    regions = funding_review.extract_evidence(funding_review.normalize_pdf_text(text))

    assert len(regions) == 1
    assert regions[0]["extraction_method"] == "bounded_two_column_region"
    assert "pClamp10.3" not in regions[0]["evidence_text"]
    assert "magni" not in regions[0]["evidence_text"]
    assert funding_review.grant_ids(regions[0]["evidence_text"]) == [
        "81571061",
        "2019020048-JH2/103",
    ]


def test_normalized_alias_suppresses_shorter_generic_duplicates() -> None:
    text = (
        "This work was supported by the National Natural Sciences Foundation of China "
        "and Team Innovation Funding Program of the Second Affiliated Hospital of Soochow University."
    )

    values = funding_review.funders(text)

    assert [item["funder_name_normalized"] for item in values] == [
        "国家自然科学基金委员会（NSFC）",
        "苏州大学附属第二医院团队创新资助计划",
    ]
