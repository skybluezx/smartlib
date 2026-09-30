import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_controlled_scholars.py"
PACKAGE_PATH = REPOSITORY_ROOT / "data/imports/2026-nsf-representative-publications-v1/scholars.json"


def load_import_module():
    spec = importlib.util.spec_from_file_location("controlled_scholar_import", IMPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_controlled_scholar_package_reconciles_to_source_rows() -> None:
    package = load_import_module().load_package(PACKAGE_PATH)

    assert package["manifest"]["synthetic"] is False
    assert package["manifest"]["unique_scholars"] == 58
    assert package["manifest"]["source_publication_rows"] == 283
    assert sum(item["publication_row_count"] for item in package["scholars"]) == 283
    assert package["scholars"][0]["canonical_name"] == "丁俊莹"
    assert package["scholars"][-1]["canonical_name"] == "宁静"


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_controlled_scholar_package_rejects_duplicate_names(tmp_path: Path) -> None:
    module = load_import_module()
    package = module.load_package(PACKAGE_PATH)
    package["scholars"][1]["canonical_name"] = package["scholars"][0]["canonical_name"]
    duplicate_package = tmp_path / "duplicate.json"
    duplicate_package.write_text(module.json.dumps(package, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate canonical names"):
        module.load_package(duplicate_package)


def test_portable_scholar_package_checks_counts_and_identity(tmp_path):
    """Small generated fixture exercises validation only; never written to a database."""
    import json
    from uuid import uuid4
    module = load_import_module()
    scholars = [{'canonical_name': name, 'publication_row_count': 1,
        **{key: str(uuid4()) for key in ('object_id','source_reference_id','evidence_id','outbox_event_id','audit_event_id')}}
        for name in ('测试作者甲','测试作者乙')]
    package = {'manifest': {'synthetic': False, 'unique_scholars': 2, 'source_publication_rows': 2}, 'scholars': scholars}
    path = tmp_path / 'test-only-scholars.json'
    path.write_text(json.dumps(package))
    assert len(module.load_package(path)['scholars']) == 2
    scholars[1]['canonical_name'] = scholars[0]['canonical_name']
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match='duplicate canonical names'):
        module.load_package(path)
    scholars[1]['canonical_name'] = '测试作者乙'
    package['manifest']['source_publication_rows'] = 3
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match='row count'):
        module.load_package(path)
