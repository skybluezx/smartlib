from smartlib_platform.journals.normalization import clean_title, journal_key, normalized_title


def test_normalized_title_decodes_html_and_normalizes_width() -> None:
    assert clean_title("Cell Death &amp; Disease") == "Cell Death & Disease"
    assert normalized_title("  Clinical &amp; Translational  Medicine ") == (
        "clinical & translational medicine"
    )
    assert normalized_title("\uff21\uff23\uff33\u3000\uff2e\uff21\uff2e\uff2f") == "acs nano"


def test_journal_key_unifies_latin_variants() -> None:
    assert journal_key("The Journal of Cell Biology") == journal_key("JOURNAL OF CELL BIOLOGY")
    assert journal_key("Clinical & Translational Medicine") == journal_key(
        "Clinical and Translational Medicine"
    )


def test_journal_key_preserves_distinct_chinese_titles() -> None:
    titles = ["世界中医药", "中华现代护理杂志", "中华高血压杂志", "中国科学\uff1a生命科学"]
    keys = {journal_key(title) for title in titles}
    assert len(keys) == len(titles)
    assert "" not in keys
