import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COLLECTOR = REPOSITORY_ROOT / "apps/platform-api/scripts/collect_publication_verification.py"
APPLIER = REPOSITORY_ROOT / "apps/platform-api/scripts/apply_publication_verification.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("publication_verification_collector", COLLECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_crossref_year_accepts_incomplete_date_parts() -> None:
    collector = load_collector()

    assert collector.crossref_year({"published": {"date-parts": [[None]]}}) is None


def test_exact_doi_requires_strict_title_and_year_match() -> None:
    collector = load_collector()
    source = {
        "title": "A controlled publication title",
        "journal_or_conference": "Test Journal",
        "publication_year": 2026,
    }
    candidate = {
        "title": "A controlled publication title",
        "journal_name": "Test Journal",
        "publication_year": 2026,
    }

    assert collector.classify(source, candidate, "exact_doi")["classification"] == "auto_verified"
    candidate["publication_year"] = 2020
    assert collector.classify(source, candidate, "exact_doi")["classification"] == "conflict"


def test_database_field_status_preserves_conflicts() -> None:
    spec = importlib.util.spec_from_file_location("publication_verification_applier", APPLIER)
    assert spec is not None and spec.loader is not None
    applier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(applier)
    record = {
        "classification": "conflict",
        "method": "exact_doi",
        "scores": {"title_score": 0.4, "journal_score": 0.9, "year_distance": 4},
    }

    assert applier.field_status("title", record) == ("conflict", 0.4)
    assert applier.field_status("journal_name", record) == ("matched", 0.9)
    assert applier.field_status("publication_year", record)[0] == "conflict"
