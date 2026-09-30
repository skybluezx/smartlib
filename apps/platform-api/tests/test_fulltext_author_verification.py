import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/run_fulltext_author_verification.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fulltext_author_verification", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_awardee_pinyin_matches_reversed_english_name_in_fulltext() -> None:
    module = load_module()

    result = module.match_awardee("郭雷", ["Zi-Zhuo Li", "Guo Lei Guo Lei"], "Zi-Zhuo Li · Lei Guo")

    assert result["status"] == "confirmed"
    assert result["selected_author_order"] == 2
    assert result["selected_author_name"] == "Guo Lei"


def test_roles_extract_named_equal_contribution_and_corresponding_markers() -> None:
    module = load_module()
    text = """Zi-Zhuo Li1 · Lei Guo1 · Qiu-Yue Lin2 · Bo Zhang1
Zi-Zhuo Li and Lei Guo have contributed equally to this work.
Qiu-Yue Lin and Bo Zhang have contributed equally to this work.
* Qiu-Yue Lin
* Bo Zhang
* Corresponding authors
"""

    result = module.extract_author_roles(["Zi-Zhuo Li", "Lei Guo", "Qiu-Yue Lin", "Bo Zhang"], text)

    assert result["first_author_orders"] == [1]
    assert result["co_first_author_orders"] == [1, 2]
    assert result["equal_contribution_groups"] == [[1, 2], [3, 4]]
    assert result["corresponding_author_orders"] == [3, 4]
    assert result["co_corresponding_author"] is True


def test_doi_prefers_preverified_identifier_when_fulltext_contains_references() -> None:
    module = load_module()

    result = module.verify_doi(
        None,
        "10.1186/s12933-020-01087-4",
        "DOI 10.1186/s12933-020-01087-4 references 10.1016/j.hjc.2019.03.006",
    )

    assert result["status"] == "confirmed"
    assert result["selected_doi"] == "10.1186/s12933-020-01087-4"


def test_equal_contribution_star_is_not_misread_as_corresponding_marker() -> None:
    module = load_module()
    text = """Zhaohong Geng* · Yuchan Yuan* · Zheng Tang · Peng Qu
*These authors contributed equally to this work.
Corresponding authors: Z. Tang and P. Qu
"""

    result = module.extract_author_roles(["Zhaohong Geng", "Yuchan Yuan", "Zheng Tang", "Peng Qu"], text)

    assert result["co_first_author_orders"] == [1, 2]
    assert result["corresponding_author_orders"] == [3, 4]


def test_doi_discards_supplement_and_preprint_when_article_doi_is_present() -> None:
    module = load_module()

    supplement = module.verify_doi(
        None,
        None,
        "Article 10.1172/jci121685 Supplement 10.1172/jci121685ds1",
    )
    preprint = module.verify_doi(
        None,
        None,
        "Article 10.1186/s13046-024-03015-w Preprint 10.21203/rs.3.rs-3664228/v1",
    )

    assert supplement["selected_doi"] == "10.1172/jci121685"
    assert preprint["selected_doi"] == "10.1186/s13046-024-03015-w"


def test_author_name_discards_spreadsheet_parenthetical_noise() -> None:
    module = load_module()

    assert module.canonical_author_name("Ge Zhan (期刊 期刊 Ge Zhan") == "Ge Zhan"


def test_prose_starting_with_correspondence_is_not_a_role_declaration() -> None:
    module = load_module()

    result = module.extract_author_roles(
        ["Lei Guo", "Bo Zhang"],
        "Correspondence promotes communication between cells in this experiment.",
    )

    assert result["corresponding_author_orders"] == []
    assert result["evidence"]["corresponding_author"] == []
