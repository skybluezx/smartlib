import importlib.util
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "apps/platform-api/scripts/affiliation_candidates.py"


def load_module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("affiliation_candidates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chinese_author_names_never_collapse_to_empty_identity():
    module = load_module()
    assert module.normalized_name("贾晶晶") == "贾晶晶"
    assert module.normalized_name("刘安澜") != module.normalized_name("贾晶晶")
    assert module.normalized_name("He, Bin") == module.normalized_name("He,Bin")


def test_same_name_without_orcid_gets_separate_provisional_slot_identities():
    module = load_module()
    class NoLookup:
        def execute(self, *args):
            raise AssertionError("Unverified name must not trigger a global person lookup")
    author = {"person_object_id": None, "author_name_raw": "Wei Wang", "orcid": None,
              "publication_authorship_id": "slot-1"}
    first, method = module.author_person_id(NoLookup(), author, [], [])
    second, _ = module.author_person_id(NoLookup(), {**author, "publication_authorship_id": "slot-2"}, [], [])
    assert first != second
    assert method == "new_provisional_authorship_identity"


def test_extract_affiliations_maps_numbered_units_to_authors() -> None:
    module = load_module()
    result = module.extract_affiliations(
        ["Lei Guo", "Bo Zhang"],
        """Lei Guo1, Bo Zhang2
1 Dalian Medical University, Dalian, China
2 First Affiliated Hospital, Dalian, China
Abstract
Background text
""",
    )

    assert result[1][0]["organization_name"] == "Dalian Medical University"
    assert result[2][0]["organization_name"] == "First Affiliated Hospital"


def test_rejects_generic_or_context_contaminated_organization_names() -> None:
    module = load_module()

    assert module.organization_names("1 University, Dalian, China") == []
    assert module.organization_names("1 First Hospital, Dalian, China") == []
    assert module.organization_names("1 The University, London, UK") == []
    assert module.organization_names("of Milan") == []
    assert module.organization_names("Downloaded from https://doi.org/x by Dalian Medical University") == []
    assert module.organization_names("Dalian Medical University University of Science Malaysia") == [
        "Dalian Medical University",
        "University of Science Malaysia",
    ]


def test_chinese_organization_identity_key_is_not_empty() -> None:
    module = load_module()

    assert module.normalized_entity_name("大连医科大学附属第一医院") == "大连医科大学附属第一医院"


def test_group_author_keeps_original_name_when_parenthetical_cleanup_would_empty_it() -> None:
    module = load_module()

    assert module.display_author_name("(The Consortium)") == "(The Consortium)"
    assert module.display_author_name("(2) Ke Cheng") == "Ke Cheng"


def test_publication_level_affiliation_block_is_not_assigned_to_each_author() -> None:
    module = load_module()
    raw = "; ".join(
        [
            "Dalian Medical University",
            "University of Science Malaysia",
            "Henan Normal University",
            "Northwestern Polytechnical University",
        ]
    )

    assert module.metadata_affiliation_assignments(raw) == []


def test_organization_names_discards_shorter_overlapping_fragment() -> None:
    module = load_module()

    assert module.organization_names("Dalian University of Technology, Dalian, China") == [
        "Dalian University of Technology"
    ]
