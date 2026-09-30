import zipfile

from smartlib_platform.publications.intake import (
    automatic_eligibility,
    records_from_csv,
    records_from_xlsx,
)
from smartlib_platform.publications.models import PublicationImportRecordInput
from smartlib_platform.publications.verification_state import effective_verification_state


def test_automatic_eligibility_requires_doi_year_and_claimed_authors() -> None:
    eligible = PublicationImportRecordInput(
        title="Verified title",
        publication_year=2026,
        doi="10.1000/example",
        awardee_name="张三",
        authors=["Zhang San", "Li Si"],
    )
    assert automatic_eligibility(eligible) == (True, [])

    incomplete = PublicationImportRecordInput(title="Historical title", awardee_name="张三")
    allowed, reasons = automatic_eligibility(incomplete)
    assert allowed is False
    assert len(reasons) == 3


def test_csv_contract_accepts_chinese_headers_and_normalizes_doi() -> None:
    content = (
        "论文题名,期刊名称,发表年份,DOI,作者列表,获批人\n"
        "A paper,Journal,2026,https://doi.org/10.1000/ABC,Zhang San;Li Si,张三\n"
    ).encode()
    records = records_from_csv(content)
    assert records[0].title == "A paper"
    assert records[0].doi == "10.1000/abc"
    assert records[0].authors == ["Zhang San", "Li Si"]


def test_xlsx_contract_reads_first_sheet_without_external_runtime(tmp_path) -> None:
    path = tmp_path / "publications.xlsx"
    workbook = """<?xml version="1.0" encoding="UTF-8"?>
      <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
       <sheets><sheet name="论文" sheetId="1" r:id="rId1"/></sheets></workbook>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
      <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
       <Relationship Id="rId1" Target="worksheets/sheet1.xml"
        Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
      </Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8"?>
      <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
       <row r="1"><c r="A1" t="inlineStr"><is><t>论文题名</t></is></c>
        <c r="B1" t="inlineStr"><is><t>发表年份</t></is></c>
        <c r="C1" t="inlineStr"><is><t>DOI</t></is></c></row>
       <row r="2"><c r="A2" t="inlineStr"><is><t>Paper title</t></is></c>
        <c r="B2"><v>2026</v></c><c r="C2" t="inlineStr"><is><t>10.1/test</t></is></c></row>
      </sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    records = records_from_xlsx(path)
    assert records[0].publication_year == 2026
    assert records[0].doi == "10.1/test"


def test_effective_state_reopens_and_restores_prior_decision() -> None:
    base = {
        "verification_state": "auto_verified",
        "current_decision": "auto_verified",
        "identity_state": "verified",
        "has_human_correction": False,
        "has_blocking_layers": True,
        "has_blocking_conflict": False,
        "has_blocking_open": False,
        "fulltext_status": "ready",
    }
    assert effective_verification_state(base) == "auto_verified"
    assert effective_verification_state({**base, "has_blocking_open": True}) == "reverification_required"
    assert effective_verification_state({**base, "has_blocking_layers": False}) == "reverification_required"
    assert effective_verification_state({**base, "fulltext_status": "conflict"}) == "verification_conflict"
    assert effective_verification_state({**base, "has_human_correction": True}) == "corrected"
