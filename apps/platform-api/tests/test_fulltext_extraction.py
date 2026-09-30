from smartlib_platform.fulltext.extraction import structure_text


def test_structure_text_extracts_sections_and_identifiers() -> None:
    text = """Sample title
Abstract
This study describes a useful result.
Keywords: graph; library; medicine
Introduction
Body text DOI 10.1000/xyz.123 PMID: 12345678 PMCID: PMC7654321
Funding
Supported by grant 82000001.
References
[1] Example reference
"""
    result = structure_text(text, page_count=3, method="embedded_text", ocr_page_count=0)
    assert result["abstract"] == "This study describes a useful result."
    assert result["keywords"] == ["graph", "library", "medicine"]
    assert result["detected_dois"] == ["10.1000/xyz.123"]
    assert result["detected_pmids"] == ["12345678"]
    assert result["detected_pmcids"] == ["PMC7654321"]
    assert result["funding_text"] == "Supported by grant 82000001."


def test_structure_text_keeps_a_bounded_preview() -> None:
    result = structure_text("A" * 6000, 1, "ocr", 1)
    assert len(result["text_preview"]) == 4000
    assert result["ocr_page_count"] == 1


def test_structure_text_handles_two_column_publisher_layout() -> None:
    text = """University address Abstract
An extracted abstract across a publisher layout.
KEYWORDS
tumor vaccine, photoactivatable, immunotherapy
1 | INTRODUCTION
Body
"""
    result = structure_text(text, 2, "embedded_text", 0)
    assert result["abstract"] == "An extracted abstract across a publisher layout."
    assert result["keywords"] == ["tumor vaccine", "photoactivatable", "immunotherapy"]
    assert "introduction" in result["section_headings"]
