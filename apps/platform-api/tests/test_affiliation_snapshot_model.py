from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from smartlib_platform.governance.models import ReviewTaskCreate
from smartlib_platform.publications.provenance import PublicationRelationCreate
from smartlib_platform.relations.models import EvidenceCreate

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_v29_enforces_paper_scoped_affiliation_snapshots() -> None:
    migration = (
        REPOSITORY_ROOT
        / "database/migrations/V29__create_paper_affiliation_snapshot_model.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE smartlib.review_task" in migration
    assert "context_object_id" in migration
    assert "source_publication_authorship_id" in migration
    assert "approved affiliation snapshot requires confirmed PDF affiliation evidence" in migration
    assert "person_affiliation_publication_snapshot_idx" in migration
    assert "legacy_affiliation_without_page_locator" in migration


def test_affiliation_api_models_carry_pdf_and_paper_context() -> None:
    fulltext_id = uuid4()
    evidence = EvidenceCreate(
        evidence_type="publication",
        evidence_kind="author_affiliation",
        fulltext_resource_id=fulltext_id,
        page_number=1,
        evidence_locator={"marker": "1"},
        verification_state="confirmed",
        citation="PDF page 1",
        excerpt="Department of Medicine, Example University",
    )
    relation = PublicationRelationCreate(
        subject_id=uuid4(),
        predicate="person.affiliated_with",
        object_id=uuid4(),
        context_object_id=uuid4(),
        publication_authorship_id=uuid4(),
        fact_class="literature_fact",
        review_state="approved",
        evidence_ids=[uuid4()],
    )

    assert evidence.fulltext_resource_id == fulltext_id
    assert relation.context_object_id is not None
    assert relation.publication_authorship_id is not None


def test_review_task_requires_target_id_to_match_typed_reference() -> None:
    evidence_id = uuid4()
    task = ReviewTaskCreate(
        issue_type="PDF_AFFILIATION_MAPPING_UNCERTAIN",
        target_type="evidence",
        target_id=evidence_id,
        evidence_id=evidence_id,
        publication_id=uuid4(),
        publication_authorship_id=uuid4(),
        reason_code="author_marker_ambiguous",
    )
    assert task.evidence_id == evidence_id

    with pytest.raises(ValidationError):
        ReviewTaskCreate(
            issue_type="PDF_AFFILIATION_MAPPING_UNCERTAIN",
            target_type="evidence",
            target_id=evidence_id,
            evidence_id=uuid4(),
            reason_code="author_marker_ambiguous",
        )


def test_obsolete_materialization_entry_points_are_removed() -> None:
    for name in ("apply_fulltext_affiliation_rebuild.py", "import_fulltext_authors_and_affiliations.py"):
        assert not (REPOSITORY_ROOT / "apps/platform-api/scripts" / name).exists()
