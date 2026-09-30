import pytest
import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_controlled_nsf_projects.py"
PACKAGE_PATH = REPOSITORY_ROOT / "data/imports/2026-nsf-representative-publications-v1/scholars.json"


def load_import_module():
    spec = importlib.util.spec_from_file_location("controlled_nsf_project_import", IMPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_project_plan_creates_one_individual_grant_per_awardee() -> None:
    module = load_import_module()
    package = module.load_scholar_package(PACKAGE_PATH)
    records = module.project_records(package)

    assert len(records) == 58
    assert len({record["project_id"] for record in records}) == 58
    assert len({record["lead_relation_id"] for record in records}) == 58
    assert records[0]["name"] == "丁俊莹"
    assert records[-1]["name"] == "宁静"
    assert all("项目名称待补" in record["canonical_name"] for record in records)
