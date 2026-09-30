import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/run_fulltext_preverification.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fulltext_preverification", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source() -> dict:
    return {
        "title": "A controlled publication title",
        "doi": "10.1000/example",
        "pmid": "12345678",
        "pmcid": None,
        "publication_year": 2024,
        "authors_raw_list": ["Alice Example", "Bob Scholar"],
    }


def match() -> dict:
    return {
        "sha256": "a" * 64,
        "match_reasons": ["title_exact_in_text", "year_present", "author_hits:2"],
        "first_pages_dois": ["10.1000/example"],
        "pdf_title": "A controlled publication title",
        "fulltext_extraction": {
            "state": "parsed", "page_count": 10, "text_length": 50000,
            "method": "embedded_text",
        },
    }


def test_fulltext_preverification_is_ready_only_when_blocking_evidence_passes() -> None:
    module = load_module()

    result = module.evaluate(match(), source(), [12])

    assert result["status"] == "ready"
    assert result["proposed_identifiers"]["doi"] == "10.1000/example"
    assert {item["code"]: item["status"] for item in result["checks"]}["awardee_attribution"] == "passed"


def test_fulltext_preverification_requires_review_when_author_is_not_located() -> None:
    module = load_module()
    candidate = match()
    candidate["match_reasons"] = ["title_exact_in_text", "year_present"]

    result = module.evaluate(candidate, source(), [12])

    assert result["status"] == "review_required"
    statuses = {item["code"]: item["status"] for item in result["checks"]}
    assert statuses["awardee_attribution"] == "review_required"
