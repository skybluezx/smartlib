import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PREPARE_SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/prepare_controlled_publications.py"
IMPORT_SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_controlled_publications.py"
WORKBOOK_PATH = REPOSITORY_ROOT / "outputs/2026_nsf_all_publications/2026国自然代表性论著全部信息_283篇.xlsx"
SCHOLAR_PACKAGE_PATH = REPOSITORY_ROOT / "data/imports/2026-nsf-representative-publications-v1/scholars.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (WORKBOOK_PATH.exists() and SCHOLAR_PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_publication_package_preserves_all_source_rows() -> None:
    package = load_module(PREPARE_SCRIPT, "prepare_publications").build_package(
        WORKBOOK_PATH, SCHOLAR_PACKAGE_PATH
    )

    assert package["manifest"]["expected_item_count"] == 283
    assert package["manifest"]["unique_awardees"] == 58
    assert package["manifest"]["rows_missing_publication_year"] == 2
    assert package["items"][0]["source_excel_row"] == 2
    assert package["items"][-1]["source_excel_row"] == 284
    assert package["items"][0]["raw_payload"]["题名"]
    assert package["items"][0]["normalized_payload"]["doi"] == "10.1002/adma.202400196"


@pytest.mark.skipif(not (WORKBOOK_PATH.exists() and SCHOLAR_PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_publication_import_package_reconciles(tmp_path: Path) -> None:
    prepare = load_module(PREPARE_SCRIPT, "prepare_publications_for_import")
    importer = load_module(IMPORT_SCRIPT, "controlled_publication_import")
    package = prepare.build_package(WORKBOOK_PATH, SCHOLAR_PACKAGE_PATH)
    package_path = tmp_path / "publications.json"
    package_path.write_text(prepare.json.dumps(package, ensure_ascii=False), encoding="utf-8")

    loaded = importer.load_package(package_path)

    assert len(loaded["items"]) == 283
    assert loaded["manifest"]["initial_verification_state"] == "normalized"


@pytest.mark.skipif(not (WORKBOOK_PATH.exists() and SCHOLAR_PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_publication_import_rejects_noncontiguous_serials(tmp_path: Path) -> None:
    prepare = load_module(PREPARE_SCRIPT, "prepare_publications_invalid")
    importer = load_module(IMPORT_SCRIPT, "controlled_publication_import_invalid")
    package = prepare.build_package(WORKBOOK_PATH, SCHOLAR_PACKAGE_PATH)
    package["items"][1]["source_serial"] = 99
    package_path = tmp_path / "invalid-publications.json"
    package_path.write_text(prepare.json.dumps(package, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="serials are not contiguous"):
        importer.load_package(package_path)


def test_portable_publication_package_enforces_identity_and_serials(tmp_path):
    import json
    from uuid import uuid4
    module = load_module(IMPORT_SCRIPT, 'portable_publication_import')
    items = [{'source_serial': i + 1, 'record_id': str(uuid4()),
              'awardee_person_id': str(uuid4()), 'row_checksum': 'a' * 64} for i in range(2)]
    package = {'manifest': {'synthetic': False, 'expected_item_count': 2}, 'items': items}
    path = tmp_path / 'test-only-publications.json'
    path.write_text(json.dumps(package))
    assert len(module.load_package(path)['items']) == 2
    items[1]['source_serial'] = 99
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match='serials are not contiguous'):
        module.load_package(path)
    items[1]['source_serial'] = 2
    items[1]['record_id'] = items[0]['record_id']
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match='duplicate publication'):
        module.load_package(path)
