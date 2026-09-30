from smartlib_platform.publications.models import PublicationVerificationDecisionCommand
from smartlib_platform.publications.service import (
    _plain_title,
    _selected_fields,
    unresolved_blocking_checks,
)


def test_field_selection_defaults_conflicts_to_source_and_matches_to_candidate() -> None:
    fields = [
        {
            "field_name": "title",
            "source_value": "Source title",
            "candidate_value": "Candidate title",
            "verification_status": "conflict",
        },
        {
            "field_name": "doi",
            "source_value": "10.1/source",
            "candidate_value": "10.1/candidate",
            "verification_status": "matched",
        },
    ]

    assert _selected_fields(fields, {}) == {
        "title": "Source title",
        "doi": "10.1/candidate",
    }
    assert _selected_fields(fields, {"title": "candidate"})["title"] == "Candidate title"


def test_candidate_title_markup_is_not_written_to_canonical_title() -> None:
    assert _plain_title("A study of <i>GGT7</i>") == "A study of GGT7"
    assert (
        _plain_title("The\n&lt;i&gt;m6A&lt;/i&gt;  study")
        == "The m6A study"
    )
    assert _plain_title("CD146\n<sup>+</sup>\npericyte") == "CD146+ pericyte"


def test_selected_text_fields_decode_html_entities() -> None:
    fields = [
        {
            "field_name": "journal_name",
            "source_value": None,
            "candidate_value": "Trends in Endocrinology &amp; Metabolism",
            "verification_status": "matched",
        }
    ]

    assert _selected_fields(fields, {}) == {
        "journal_name": "Trends in Endocrinology & Metabolism"
    }


def test_fulltext_field_overrides_take_precedence_over_source_and_candidate() -> None:
    fields = [
        {
            "field_name": "doi",
            "source_value": None,
            "candidate_value": "10.1/wrong-candidate",
            "verification_status": "conflict",
        }
    ]

    assert _selected_fields(
        fields,
        {"doi": "candidate"},
        {"doi": "10.1/fulltext", "publication_year": 2024},
    ) == {"doi": "10.1/fulltext", "publication_year": 2024}


def test_missing_external_author_list_can_use_complete_fulltext_evidence() -> None:
    checks = [
        {
            "check_code": "author_list_available",
            "check_label": "Author list",
            "check_status": "missing",
            "severity": "blocking",
        },
        {
            "check_code": "fulltext_parse_completeness",
            "check_label": "Fulltext parse",
            "check_status": "passed",
            "severity": "blocking",
        },
        {
            "check_code": "fulltext_title_identity",
            "check_label": "Fulltext title",
            "check_status": "passed",
            "severity": "blocking",
        },
    ]
    command = PublicationVerificationDecisionCommand(
        reason="fulltext evidence reviewed",
        awardee_author_order=1,
        accepted_check_codes=["author_list_available"],
    )

    assert unresolved_blocking_checks(checks, command) == []
