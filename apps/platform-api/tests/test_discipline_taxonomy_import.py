import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/import_discipline_taxonomies.py"
PACKAGE_PATH = REPOSITORY_ROOT / "data/imports/discipline-taxonomies-2026-09-04/taxonomies.json"


def load_import_module():
    spec = importlib.util.spec_from_file_location("discipline_taxonomy_import", IMPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_discipline_taxonomy_package_reconciles_and_excludes_gbt_level_three() -> None:
    package = load_import_module().load_package(PACKAGE_PATH)

    assert package["manifest"]["synthetic"] is False
    assert package["manifest"]["object_counts"] == {"concept": 4, "discipline": 2551}
    assert package["manifest"]["discipline_counts"] == {
        "MOE_GRADUATE_DISCIPLINE_2022": 255,
        "MOE_PREVIOUS_DISCIPLINE": 70,
        "NSFC_APPLICATION_CODE_2026": 1426,
        "GBT_13745_2009": 800,
    }
    assert package["manifest"]["excluded"]["records"] == 2306
    assert not any(item["scheme"] == "GBT_13745_2009" and item["level"] == 3 for item in package["objects"])


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_nsfc_manual_name_correction_is_preserved() -> None:
    package = load_import_module().load_package(PACKAGE_PATH)
    item = next(
        item
        for item in package["objects"]
        if item["scheme"] == "NSFC_APPLICATION_CODE_2026" and item["code"] == "H0113"
    )

    assert item["canonical_name"] == "呼吸介入、气管重建与肺移植"
    assert item["quality_state"] == "warning"
    assert "manual_name_correction:介人->介入" in item["attributes"]["ocr_flags"]


@pytest.mark.skipif(not (PACKAGE_PATH.exists()), reason='历史批次原文件未提供；保留原批次对账测试，不以替代数据冒充')
def test_package_rejects_gbt_level_three_record(tmp_path: Path) -> None:
    module = load_import_module()
    package = module.load_package(PACKAGE_PATH)
    item = next(item for item in package["objects"] if item["scheme"] == "GBT_13745_2009")
    item["level"] = 3
    package["manifest"]["object_counts"] = dict(
        module.Counter(record["object_type"] for record in package["objects"])
    )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="三级解析词项"):
        module.load_package(invalid_path)
