import importlib.util
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts/prepare_research_classification_sources.py"
SPEC = importlib.util.spec_from_file_location("classification_sources", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SourceTests(unittest.TestCase):
    def test_mesh_multiple_tree_positions_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mesh.xml"
            path.write_text('''<DescriptorRecordSet><DescriptorRecord><DescriptorUI>D000001</DescriptorUI>
            <DescriptorName><String>Example</String></DescriptorName><TreeNumberList>
            <TreeNumber>A01.123</TreeNumber><TreeNumber>B01.456</TreeNumber></TreeNumberList>
            </DescriptorRecord></DescriptorRecordSet>''')
            terms = module.parse_mesh(path)
            self.assertEqual(terms[0]["tree_numbers"], ["A01.123", "B01.456"])

    def test_mismatched_title_never_assigns_mesh(self):
        paper = {"publication_id": "p", "title": "One", "publication_year": 2020,
                 "attributes": {"incites": {"raw_fields": {"Pubmed ID": "MEDLINE:123"}}}}
        source = {"123": {"title": "Another", "abstract": "", "mesh": [{"code": "D1"}], "source_path": "x"}}
        row = module.review_record(paper, source, {})
        self.assertEqual(row["source_match_state"], "title_mismatch")
        self.assertEqual(row["mesh"], [])

    def test_known_code_does_not_make_assignment_approved(self):
        paper = {"publication_id": "p", "title": "A <i>title</i>", "publication_year": 2020,
                 "attributes": {"incites": {"raw_fields": {"Pubmed ID": "123", "研究方向": "BIOLOGY"}}}}
        source = {"123": {"title": "A title", "abstract": "text", "source_path": "x",
                          "mesh": [{"code": "D1", "name": "Example", "major_topic": True, "qualifiers": []}]}}
        row = module.review_record(paper, source, {"D1": {"name": "Example"}})
        self.assertEqual(row["mesh"][0]["review_state"], "pending")
        self.assertIsNone(row["mesh"][0]["assignment_year"])
        self.assertEqual(row["evaluation"]["raw_research_direction"], "BIOLOGY")
        self.assertEqual(row["nsfc"]["candidates"], [])


if __name__ == "__main__":
    unittest.main()
