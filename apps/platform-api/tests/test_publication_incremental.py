from smartlib_platform.publications.incremental import _candidate_drafts, _impact
from smartlib_platform.publications.models import (
    FulltextSupplementInput,
    FundingSupplementInput,
    PublicationSupplementCreate,
)


def current_metadata() -> dict[str, object]:
    return {
        "title": "Verified title",
        "journal_name": "Verified journal",
        "publication_year": 2026,
        "abstract": None,
        "attributes": {"keywords": ["existing"]},
    }


def test_additive_metadata_is_auto_applied_but_identity_change_reopens_review() -> None:
    additive = _candidate_drafts(
        current_metadata(), {},
        PublicationSupplementCreate(
            source_kind="metadata", source_label="Repository metadata",
            metadata={"abstract": "New abstract", "keywords": ["new"]},
        ),
    )
    assert {item["field_path"] for item in additive} == {"abstract", "attributes.keywords"}
    assert {item["status"] for item in additive} == {"auto_applied"}
    assert _impact(additive) == "additive"

    identity_change = _candidate_drafts(
        current_metadata(), {},
        PublicationSupplementCreate(
            source_kind="metadata", source_label="Corrected metadata",
            metadata={"title": "Different title"},
        ),
    )
    assert identity_change[0]["risk"] == "critical"
    assert identity_change[0]["status"] == "pending"
    assert _impact(identity_change) == "critical"


def test_fulltext_and_funding_create_separate_traceable_candidates() -> None:
    command = PublicationSupplementCreate(
        source_kind="fulltext",
        source_label="Deposited author manuscript",
        fulltext=FulltextSupplementInput(
            file_name="paper.pdf",
            storage_uri="s3://smartlib-publications/paper.pdf",
            content_checksum="a" * 64,
            extracted_metadata={"abstract": "Extracted abstract"},
        ),
        funding=[FundingSupplementInput(funder_name="NSFC", grant_id="82000001")],
    )
    drafts = _candidate_drafts(current_metadata(), {}, command)

    by_path = {item["field_path"]: item for item in drafts}
    assert by_path["abstract"]["status"] == "auto_applied"
    assert by_path[f"fulltext.{'a' * 64}"]["status"] == "auto_applied"
    assert by_path["funding.1"]["change_type"] == "relation_add"
    assert by_path["funding.1"]["status"] == "pending"


def test_funding_acknowledgement_is_evidence_not_an_organization_relation():
    from uuid import uuid4
    from smartlib_platform.publications.incremental import _apply_funding_relation
    class Connection:
        def __init__(self): self.calls=[]
        def execute(self, sql, params):
            self.calls.append((sql,params))
            return self
        def fetchone(self): return {'version':1}
    c=Connection()
    pid,eid,actor=uuid4(),uuid4(),uuid4()
    _apply_funding_relation(c,pid,eid,{'funder_name':'Foundation'},actor,'test')
    assert len(c.calls)==1 and 'funding_source_clues' in c.calls[0][0]
    assert next(iter(c.calls[0][1][0].obj.values()))['match_state']=='project_unresolved'
    c=Connection()
    _apply_funding_relation(c,pid,eid,{'funder_name':'Foundation','grant_id':'123','source_section':'Acknowledgements'},actor,'test')
    relation=next(params for sql,params in c.calls if 'INSERT INTO smartlib.relation_assertion' in sql)
    assert relation[2]=='publication.supported_by_project'
    assert relation[-1].obj['funding_source_note']['source_section']=='Acknowledgements'
    assert any('INSERT INTO smartlib.relation_evidence' in sql for sql,_ in c.calls)
