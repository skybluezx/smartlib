from uuid import uuid4

import pytest
from pydantic import ValidationError

from smartlib_platform.ingestion.models import IngestionCreate
from smartlib_platform.relations.models import RelationCreate


def test_non_publication_api_input_has_no_spreadsheet_requirements():
    command = IngestionCreate(
        source_system_id=uuid4(),
        dataset_version="api:v1",
        source_kind="api",
        pipeline_key="catalog",
        records=[
            {"source_record_key": "external:123", "record_kind": "dataset", "raw_payload": {"name": "data"}}
        ],
    )
    assert command.source_uri is None
    assert command.records[0].source_locator == {}


def test_duplicate_source_keys_are_rejected_before_writing():
    with pytest.raises(ValidationError, match="must be unique"):
        IngestionCreate(
            source_system_id=uuid4(),
            dataset_version="api:v1",
            source_kind="api",
            pipeline_key="catalog",
            records=[{"source_record_key": "same", "record_kind": "dataset", "raw_payload": {}}] * 2,
        )


def test_generic_relation_rejects_legacy_publication_field():
    with pytest.raises(ValidationError, match="Extra inputs"):
        RelationCreate(
            subject_id=uuid4(),
            object_id=uuid4(),
            predicate="person.affiliated_with",
            fact_class="literature_fact",
            source_publication_authorship_id=uuid4(),
        )
