import pytest

from smartlib_platform.publications.models import PublicationVerificationDecisionCommand
from smartlib_platform.publications.service import unresolved_blocking_checks


def test_unresolved_blocking_checks_require_explicit_resolution() -> None:
    checks = [
        {
            "check_code": "doi",
            "check_label": "DOI一致性",
            "check_status": "conflict",
            "severity": "blocking",
        },
        {
            "check_code": "abstract",
            "check_label": "摘要",
            "check_status": "missing",
            "severity": "info",
        },
    ]

    unresolved = unresolved_blocking_checks(
        checks, PublicationVerificationDecisionCommand(reason="人工核验")
    )
    assert [item["check_code"] for item in unresolved] == ["doi"]

    resolved = unresolved_blocking_checks(
        checks,
        PublicationVerificationDecisionCommand(
            reason="人工核验", accepted_check_codes=["doi"]
        ),
    )
    assert resolved == []


def test_author_selection_resolves_awardee_check_but_author_list_cannot_be_overridden() -> None:
    awardee_check = {
        "check_code": "awardee_author_match",
        "check_label": "获批人作者身份",
        "check_status": "pending",
        "severity": "blocking",
    }
    assert unresolved_blocking_checks(
        [awardee_check],
        PublicationVerificationDecisionCommand(reason="人工核验", awardee_author_order=2),
    ) == []

    author_list_check = {
        "check_code": "author_list_available",
        "check_label": "权威作者列表",
        "check_status": "missing",
        "severity": "blocking",
    }
    with pytest.raises(ValueError, match="cannot be manually overridden"):
        unresolved_blocking_checks(
            [author_list_check],
            PublicationVerificationDecisionCommand(
                reason="人工核验", accepted_check_codes=["author_list_available"]
            ),
        )


def test_legacy_identifier_check_requires_evidence_despite_old_passed_status() -> None:
    check = {
        "check_code": "identifier_triangle",
        "check_label": "DOI、PMID、PMCID交叉一致性",
        "check_status": "passed",
        "severity": "blocking",
        "source_value": {"doi": None, "pmid": None, "pmcid": None},
        "authoritative_value": {
            "crossref_doi": "10.1000/unlinked",
            "pubmed_doi": None,
            "pubmed_pmcid": None,
        },
    }

    unresolved = unresolved_blocking_checks(
        [check], PublicationVerificationDecisionCommand(reason="人工核验")
    )
    assert [item["check_code"] for item in unresolved] == ["identifier_triangle"]
