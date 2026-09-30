import importlib.util
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/prepare_publication_discipline_review.py"


def load_module():
    spec = importlib.util.spec_from_file_location("publication_discipline_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def taxonomy(*entries: tuple[str, str, str]) -> dict:
    return {
        (scheme, code): {
            "object_id": f"{scheme}:{code}",
            "canonical_name": name,
            "level": 2,
        }
        for scheme, code, name in entries
    }


def test_chinese_cardiovascular_review_uses_title_and_fulltext() -> None:
    module = load_module()
    records = taxonomy(
        (module.SCHEMES[0], "1001", "基础医学"),
        (module.SCHEMES[0], "1002", "临床医学"),
        (module.SCHEMES[1], "H02", "循环系统"),
        (module.SCHEMES[1], "H0202", "心肌损伤、修复、重构和再生"),
        (module.SCHEMES[2], "310", "基础医学"),
        (module.SCHEMES[2], "32024", "内科学"),
    )

    candidates, summary = module.classify(
        {
            "title": "丙酮酸脱氢酶在心血管病中的细胞调控作用",
            "abstract": None,
            "attributes": {},
        },
        "本文综述丙酮酸脱氢酶复合体对心肌细胞代谢的调控。",
        records,
    )

    assert len(candidates) == 6
    assert summary["primary_by_scheme"][module.SCHEMES[1]]["code"] == "H02"
    assert "题名" in summary["primary_by_scheme"][module.SCHEMES[1]]["signal_fields"]


def test_medical_ai_specific_terms_outrank_generic_biomedical_terms() -> None:
    module = load_module()
    records = taxonomy(
        (module.SCHEMES[0], "0812", "计算机科学与技术"),
        (module.SCHEMES[0], "0831", "生物医学工程"),
        (module.SCHEMES[1], "F06", "人工智能"),
        (module.SCHEMES[1], "H2709", "医学影像大数据与人工智能"),
        (module.SCHEMES[2], "52020", "人工智能"),
        (module.SCHEMES[2], "41660", "生物医学工程学"),
    )

    _, summary = module.classify(
        {
            "title": "A BERT model for a medical dialogue system",
            "abstract": "A deep learning method for medical dialogue.",
            "attributes": {},
        },
        "The artificial intelligence system supports medical dialogue.",
        records,
    )

    assert summary["primary_by_scheme"][module.SCHEMES[0]]["code"] == "0812"
    assert summary["primary_by_scheme"][module.SCHEMES[1]]["code"] == "F06"
    assert summary["primary_by_scheme"][module.SCHEMES[2]]["code"] == "52020"
