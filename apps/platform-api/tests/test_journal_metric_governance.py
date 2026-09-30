import pytest
from pathlib import Path

from smartlib_platform.journal_metrics.workbook import (
    build_package,
    normalize_issn,
    parse_categories,
    parse_quartile,
    parse_rank,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JCR_DIRECTORY = REPOSITORY_ROOT / "outputs/jcr_2026"


def test_jcr_normalization_preserves_category_and_rank_meaning() -> None:
    assert normalize_issn("0007 9235") == "0007-9235"
    assert parse_quartile("q1") == "Q1"
    assert parse_rank("1/326") == (1, 326)
    assert parse_categories("ONCOLOGY(SCIE); PSYCHIATRY(SCIE, SSCI)") == [
        {"category_order": 1, "category_name": "ONCOLOGY", "citation_indexes": ["SCIE"]},
        {
            "category_order": 2,
            "category_name": "PSYCHIATRY",
            "citation_indexes": ["SCIE", "SSCI"],
        },
    ]


@pytest.mark.skipif(not (JCR_DIRECTORY / "2025年科睿唯安JCR期刊分区表.xlsx").exists(), reason="历史2025 JCR原文件未提供")
def test_local_2025_jcr_workbook_is_complete_but_not_authority_approved() -> None:
    package = build_package(JCR_DIRECTORY / "2025年科睿唯安JCR期刊分区表.xlsx", "jcr-2025")
    manifest = package["manifest"]
    records = package["records"]

    assert manifest["expected_record_count"] == 22_249
    assert manifest["source_file_sha256"] == (
        "2bb1dbf5737aa84b4d13798b7dfd1e5bd9a022d0f9a39f71bea2c458bf001cca"
    )
    assert manifest["source_authority_status"] == "unverified"
    assert manifest["license_authorization_state"] == "pending"
    assert manifest["release_state"] == "staged"
    assert any(record["record_granularity"] == "journal" for record in records)
    assert any(record["impact_factor_is_upper_bound"] for record in records)


@pytest.mark.skipif(
    not (JCR_DIRECTORY / "2026年度JCR期刊分区表全名单.xlsx").exists(),
    reason="历史2026 JCR原文件未提供；保留原批次对账测试，不以替代数据冒充",
)
def test_local_2026_jcr_workbook_retains_one_record_per_journal_category() -> None:
    package = build_package(JCR_DIRECTORY / "2026年度JCR期刊分区表全名单.xlsx", "jcr-2026")
    manifest = package["manifest"]
    records = package["records"]

    assert manifest["expected_record_count"] == 32_215
    assert manifest["source_file_sha256"] == (
        "0ec498bf01c3b9fc8dbc9b4d63136f6f1b422a69e1791390b58cdcbc592283a2"
    )
    assert all(record["record_granularity"] == "journal_category" for record in records)
    drug_discovery = [
        record
        for record in records
        if record["journal"]["canonical_title"] == "NATURE REVIEWS DRUG DISCOVERY"
    ]
    assert [record["categories"][0]["category_name"] for record in drug_discovery] == [
        "BIOTECHNOLOGY & APPLIED MICROBIOLOGY",
        "PHARMACOLOGY & PHARMACY",
    ]


def test_journal_metric_migrations_keep_publication_links_auditable() -> None:
    migration = (
        REPOSITORY_ROOT / "database/migrations/V21__create_journal_metric_governance.sql"
    ).read_text()
    tightening = (
        REPOSITORY_ROOT / "database/migrations/V22__tighten_journal_metric_match_contract.sql"
    ).read_text()

    assert "publication_journal_metric_match" in migration
    assert "publish_journal_metric_release" in migration
    assert "publication_governance' = ANY(license.allowed_purposes)" in migration
    assert "release.release_state = 'published'" in migration
    assert "journal metric publish permission required" in migration
    assert "assert_knowledge_object_type" in tightening
    assert "decision_reason IS NOT NULL" in tightening
