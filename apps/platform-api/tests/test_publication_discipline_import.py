import pytest
import importlib.util
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_publication_discipline_relations.py"
REVIEW = REPOSITORY_ROOT / "outputs/2026_nsf_publication_discipline_review/论文全文学科对应_待确认.json"


def load_module():
    spec = importlib.util.spec_from_file_location("publication_discipline_import", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (REVIEW.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_review_package_builds_one_pending_primary_per_scheme_and_publication() -> None:
    module = load_module()
    review = module.load_review(REVIEW)
    records = module.relation_records(review)

    assert len(records) == 813
    assert len({record["relation_id"] for record in records}) == 813
    assert len({record["publication_id"] for record in records}) == 271
    assert {record["scheme"] for record in records} == module.EXPECTED_SCHEMES
    assert all(record["attributes"]["classification_role"] == "primary" for record in records)
    assert all(
        record["attributes"]["verification_task_state"] == "deferred_not_created" for record in records
    )


@pytest.mark.skipif(not (REVIEW.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_relation_ids_are_stable_across_reloads() -> None:
    module = load_module()

    first = module.relation_records(module.load_review(REVIEW))
    second = module.relation_records(module.load_review(REVIEW))

    assert [record["relation_id"] for record in first] == [record["relation_id"] for record in second]
