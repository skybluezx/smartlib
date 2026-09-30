import io
import zipfile
import pytest
from smartlib_platform.library_work.parser import normalize, parse_upload, CATALOG
from smartlib_platform.library_work.models import WorkRevision


def csv_data(rows):
    return ("时间,内容,听众人数,填表人,序号\n" + rows).encode("utf-8-sig")


def test_catalog_and_partial_dates_and_missingness():
    assert len(CATALOG) == 25
    a = normalize("reader_training", {"内容": "测试活动", "时间": "2025年3月", "听众人数": "约30人"})
    assert (a["year"], a["month"], a["date_precision"], a["audience"]) == (2025, 3, "month", None)
    b = normalize("reader_training", {"内容": "测试活动", "时间": "2025-02-30", "听众人数": "0"})
    assert b["year"] is None and b["audience"] == 0
    assert b["fields"]["时间"] == "2025-02-30"
    c = normalize("textbooks", {"书名": "模拟教材", "出版年": "2024"})
    assert c["date_precision"] == "year" and c["month"] is None


def test_csv_duplicates_headers_and_blocking_validation():
    p = parse_upload(
        "读者培训.csv",
        csv_data(
            "2025-01-02,检索培训,20,模拟馆员,1\n时间,内容,听众人数,填表人,序号\n2025-01-02,检索培训,20,模拟馆员,2\n2025-01-03,,5,模拟馆员,3"
        ),
    )
    assert len(p["records"]) == 1 and len(p["errors"]) == 2 and p["skipped_rows"] == 1
    assert p["records"][0]["origin"]["row"] == 2
    assert "重复" in p["errors"][0]["message"]


def test_import_retains_every_field_and_unknown_headers_block():
    p = parse_upload("reader.csv", csv_data("2025-02,测试,30,模拟馆员,1"), category="reader_training")
    assert not p["errors"] and p["records"][0]["fields"]["填表人"] == "模拟馆员"
    p = parse_upload("读者培训.csv", "时间,内容,未知字段\n2025,测试,不能丢弃".encode())
    assert p["errors"] and not p["records"]
    p = parse_upload("读者培训.csv", "时间,内容\n2025,测试,不能丢弃".encode())
    assert "表头以外" in p["errors"][0]["message"]


def test_zip_path_and_formula_safety():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("../读者培训.csv", csv_data("2025,测试,1,,1"))
    with pytest.raises(ValueError, match="不安全"):
        parse_upload("data.zip", stream.getvalue())
    with pytest.raises(ValueError):
        normalize("reader_training", {"内容": "a", "inject": "b"})
    with pytest.raises(ValueError):
        WorkRevision(
            category="reader_training",
            fields={"内容": "a"},
            mode="unknown",
            reason="修订依据",
            base_version=1,
        )


def workbook(formula=False):
    stream = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def cell(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    with zipfile.ZipFile(stream, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="报告" sheetId="1" r:id="a"/><sheet name="总表" sheetId="2" r:id="b"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="a" Target="worksheets/sheet1.xml"/><Relationship Id="b" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        z.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{ns}"><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
        )
        z.writestr("xl/worksheets/sheet1.xml", "not data")
        z.writestr(
            "xl/worksheets/sheet2.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row r="1">{cell("A1", "时间")}{cell("B1", "内容")}</row><row r="2"><c r="A2" s="1"><v>45658</v></c>{cell("B2", "模拟培训")}</row>'
            + ('<row r="3"><c r="A3"><f>1+1</f><v>2</v></c></row>' if formula else "")
            + "</sheetData></worksheet>",
        )
    return stream.getvalue()


def test_xlsx_total_sheet_and_excel_serial_dates():
    p = parse_upload("读者培训.xlsx", workbook())
    assert not p["errors"] and len(p["records"]) == 1
    assert p["records"][0]["fields"]["时间"] == "2025-01-01"
    assert p["records"][0]["origin"]["sheet"] == "总表"
    assert "公式" in parse_upload("读者培训.xlsx", workbook(True))["errors"][0]["message"]


def test_original_trial_date_range_is_grouped_by_start_without_losing_raw_value():
    value = "2018.3.19-2018.6.18"
    record = normalize("database_trials", {"数据库名称": "模拟试用资源", "时间": value})
    assert (record["year"], record["month"], record["date_precision"]) == (2018, 3, "day")
    assert record["fields"]["时间"] == value
    assert "区间" in record["warnings"][0]


def test_unnamed_column_data_never_disappears():
    result = parse_upload("读者培训.csv", "时间,内容,,听众人数\n2025,测试,重要字段,30".encode())
    assert result["errors"] and not result["records"]
