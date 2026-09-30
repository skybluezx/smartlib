from smartlib_platform.fulltext.affiliations import (
    discover_root_hints,
    parse_affiliation,
    split_affiliation_values,
)

ROOTS = (
    "Dalian Medical University",
    "Dalian University of Technology",
    "China Medical University",
    "University of Chinese Academy of Sciences",
    "Chinese Academy of Sciences",
)


def test_preserves_full_branch_and_builds_parent_hierarchy() -> None:
    parsed = parse_affiliation(
        "Department of Immunology, College of Basic Medical Science, "
        "Dalian Medical University, Dalian, Liaoning, China",
        root_hints=ROOTS,
    )[0]

    assert parsed.canonical_name == (
        "Department of Immunology, College of Basic Medical Science, "
        "Dalian Medical University"
    )
    assert parsed.root_name == "Dalian Medical University"
    assert parsed.hierarchy == (
        "Dalian Medical University",
        "College of Basic Medical Science, Dalian Medical University",
        "Department of Immunology, College of Basic Medical Science, "
        "Dalian Medical University",
    )
    assert parsed.address == "Dalian, Liaoning, China"


def test_removes_street_and_postal_address_after_parent() -> None:
    parsed = parse_affiliation(
        "School of Stomatology, Dalian Medical University, No.9 West Section, "
        "Lvshunnan Road, Dalian, 116044, China",
        root_hints=ROOTS,
    )[0]

    assert parsed.canonical_name == "School of Stomatology, Dalian Medical University"
    assert parsed.root_name == "Dalian Medical University"
    assert "116044" in (parsed.address or "")


def test_trims_unpunctuated_city_postcode_country_tail() -> None:
    parsed = parse_affiliation(
        "State Key Laboratory of Fine Chemicals Frontiers Science Center for Smart Materials "
        "Dalian University of Technology Dalian 116024 China",
        root_hints=ROOTS,
    )[0]

    assert parsed.canonical_name.endswith("Dalian University of Technology")
    assert not parsed.canonical_name.endswith("Dalian")
    assert parsed.root_name == "Dalian University of Technology"


def test_keeps_affiliated_hospital_name_and_links_university_parent() -> None:
    parsed = parse_affiliation(
        "Department of Cardiology, The First Affiliated Hospital of Dalian Medical University, "
        "Dalian, China",
        root_hints=ROOTS,
    )[0]

    assert parsed.canonical_name == (
        "Department of Cardiology, The First Affiliated Hospital of Dalian Medical University"
    )
    assert parsed.hierarchy == (
        "Dalian Medical University",
        "The First Affiliated Hospital of Dalian Medical University",
        "Department of Cardiology, The First Affiliated Hospital of Dalian Medical University",
    )


def test_splits_multiple_author_affiliations_without_splitting_commas() -> None:
    values = split_affiliation_values(
        "College of Pharmacy, Dalian Medical University, Dalian, China; "
        "Department of Chemistry, Dalian University of Technology, Dalian, China"
    )

    assert len(values) == 2


def test_rejects_publisher_and_download_context() -> None:
    assert parse_affiliation(
        "Published by Wiley on behalf of Shanghai Institute of Clinical Bioinformatics",
        root_hints=ROOTS,
    ) == []
    assert parse_affiliation(
        "Downloaded from https://example.test at Dalian Medical University",
        root_hints=ROOTS,
    ) == []


def test_discovers_china_named_university_as_root_hint() -> None:
    hints = discover_root_hints(
        ["Department of Physiology, China Medical University, Shenyang, China"]
    )

    assert "China Medical University" in hints


def test_splits_cross_column_country_marker_and_cleans_numeric_prefix() -> None:
    parsed = parse_affiliation(
        "China, 2 Department of Morphology, College of Basic Medical Sciences, "
        "Dalian Medical University",
        root_hints=ROOTS,
    )

    assert len(parsed) == 1
    assert parsed[0].canonical_name.startswith("Department of Morphology")


def test_cleans_correspondence_and_published_prefixes() -> None:
    correspondence = parse_affiliation(
        "*Address correspondence to: Department of Physiology, China Medical University",
        root_hints=ROOTS,
    )[0]
    published = parse_affiliation(
        "PUBLISHED 24 November 2025 The First Affiliated Hospital of Dalian Medical University",
        root_hints=ROOTS,
    )[0]

    assert correspondence.canonical_name.startswith("Department of Physiology")
    assert published.canonical_name == "The First Affiliated Hospital of Dalian Medical University"


def test_splits_country_period_followed_by_next_numbered_affiliation() -> None:
    parsed = parse_affiliation(
        "Department of Oncology, The First Affiliated Hospital of Dalian Medical University, "
        "Dalian, China. 6Shanghai Information Center for Life Sciences",
        root_hints=ROOTS,
    )

    assert parsed[0].canonical_name == (
        "Department of Oncology, The First Affiliated Hospital of Dalian Medical University"
    )


def test_rejects_non_affiliation_committee_context() -> None:
    assert parse_affiliation(
        "Biosafety Committee at China Pharmaceutical University", root_hints=ROOTS
    ) == []


def test_removes_author_initials_from_publisher_affiliation() -> None:
    parsed = parse_affiliation(
        "From the Institute of Heart and Vascular Diseases "
        "(Y.L., R.T., X.A., X.N., X.Y., Y.-L.X.), "
        "the First Affiliated Hospital of Dalian Medical University, China",
        root_hints=ROOTS,
    )[0]

    assert "Y.L" not in parsed.canonical_name
    assert parsed.canonical_name == (
        "Institute of Heart and Vascular Diseases, "
        "the First Affiliated Hospital of Dalian Medical University"
    )
