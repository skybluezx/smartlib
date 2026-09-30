from uuid import UUID

import pytest

from smartlib_platform.publications.service import _existing_publication_for_verification

A = UUID("d369de09-f017-5c69-9eb8-13a70f6056fb")
B = UUID("092078aa-04d9-5d35-a610-124ca844ed01")


class Connection:
    def __init__(self, *rows):
        self.rows = iter(rows)

    def execute(self, query, params):
        self.result = next(self.rows)
        return self

    def fetchone(self):
        return self.result


def test_doi_missing_reverification_keeps_established_canonical_publication():
    assert _existing_publication_for_verification(Connection({"publication_id": A}), A, None) == {
        "publication_id": A
    }


def test_unmatched_record_without_doi_can_still_create_a_new_identity():
    assert _existing_publication_for_verification(Connection(), None, None) is None


def test_verified_doi_reuses_existing_publication_for_new_import():
    assert _existing_publication_for_verification(
        Connection({"publication_id": A}), None, "10.1172/jci121685"
    ) == {"publication_id": A}


def test_later_doi_enrichment_does_not_create_a_second_publication():
    assert _existing_publication_for_verification(
        Connection({"publication_id": A}, None, None), A, "10.1172/jci121685"
    ) == {"publication_id": A}


def test_doi_cannot_silently_switch_an_existing_import_to_another_paper():
    with pytest.raises(ValueError, match="指向不同对象"):
        _existing_publication_for_verification(
            Connection({"publication_id": A}, {"publication_id": B}), A, "10.1186/s13046-024-03015-w"
        )


def test_doi_cannot_override_an_already_verified_different_doi():
    with pytest.raises(ValueError, match="不一致"):
        _existing_publication_for_verification(
            Connection({"publication_id": A}, None, {"publication_identifier_id": B}), A, "10.1/wrong"
        )


def test_retired_identity_without_a_live_merge_target_is_not_recreated():
    with pytest.raises(ValueError, match="已失效"):
        _existing_publication_for_verification(Connection(None), A, None)
