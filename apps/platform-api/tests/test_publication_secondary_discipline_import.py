import pytest
import importlib.util
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_publication_secondary_discipline_relations.py"
REVIEW = REPOSITORY_ROOT / "outputs/2026_nsf_publication_discipline_review/论文全文学科对应_待确认.json"
TAXONOMY = REPOSITORY_ROOT / "data/imports/discipline-taxonomies-2026-09-04/taxonomies.json"


def load_module():
    spec = importlib.util.spec_from_file_location("publication_secondary_discipline_import", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (REVIEW.exists() and TAXONOMY.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_secondary_selection_is_distinct_supported_and_reconciled() -> None:
    module = load_module()
    review = module.load_review(REVIEW)
    package = module.load_taxonomy(TAXONOMY)
    records, exclusions = module.select_secondary_records(review, package)
    parents = module.parent_map(package)

    assert len(records) == 330
    assert len({record["relation_id"] for record in records}) == 330
    assert len({record["publication_id"] for record in records}) == 164
    assert Counter(record["scheme"] for record in records) == {
        "NSFC_APPLICATION_CODE_2026": 135,
        "MOE_GRADUATE_DISCIPLINE_2022": 100,
        "GBT_13745_2009": 95,
    }
    assert set(record["attributes"]["secondary_role"] for record in records) == {
        "application",
        "interdisciplinary",
        "method",
    }
    assert all(
        not module.hierarchy_related(
            record["attributes"]["primary_discipline_object_id"],
            str(record["discipline_id"]),
            parents,
        )
        for record in records
    )
    assert exclusions["low_confidence"] == 401
    assert exclusions["score_ratio_below_0_75"] == 849


@pytest.mark.skipif(not (REVIEW.exists() and TAXONOMY.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_secondary_relation_ids_are_stable() -> None:
    module = load_module()
    review = module.load_review(REVIEW)
    package = module.load_taxonomy(TAXONOMY)

    first, _ = module.select_secondary_records(review, package)
    second, _ = module.select_secondary_records(review, package)

    assert [record["relation_id"] for record in first] == [record["relation_id"] for record in second]
