import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "src/smartlib_platform/relations/research_classification.py"
SPEC = importlib.util.spec_from_file_location("research_classification", PATH)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def assignment(**changes):
    return {"publication_id": "p1", "scheme": "NSFC_APPLICATION_CODE", "scheme_version": "2026",
            "code": "H02", "source_kind": "human_classification", "source_reference": "pdf",
            "evidence_id": "e1", "method_version": "v1", "review_state": "approved",
            "reviewed_by": "reviewer", "reviewed_at": "2026-09-09", **changes}


class PolicyTests(unittest.TestCase):
    def test_no_unevidenced_approval(self):
        for changes in ({"evidence_id": None}, {"reviewed_by": None}, {"scheme_version": None}):
            with self.assertRaises(ValueError):
                policy.validate_assignment(assignment(**changes))

    def test_pending_inference_is_allowed_but_not_aggregated(self):
        row = assignment(source_kind="algorithmic_inference", review_state="pending", reviewed_by=None)
        policy.validate_assignment(row)
        self.assertEqual(self.aggregate([row])["rows"], [])

    def aggregate(self, assignments, memberships=None):
        return policy.aggregate_profile(assignments, memberships or [
            {"entity_id": "s1", "entity_type": "person", "publication_id": "p1",
             "membership_kind": "authorship", "review_state": "approved"}], {"p1": 2020, "p2": 2010},
            scheme="NSFC_APPLICATION_CODE", scheme_version="2026", start_year=2019, end_year=2026)

    def test_dedup_and_multiple_labels(self):
        result = self.aggregate([assignment(), assignment(), assignment(code="H18")])
        self.assertEqual([r["paper_count"] for r in result["rows"]], [1, 1])
        self.assertEqual(result["coverage"][0]["classified_papers"], 1)

    def test_versions_and_years_are_not_mixed(self):
        result = self.aggregate([assignment(scheme_version="2025"), assignment(publication_id="p2")])
        self.assertEqual(result["rows"], [])

    def test_employment_is_not_paper_affiliation(self):
        base = {"entity_id": "o1", "entity_type": "organization", "publication_id": "p1",
                "review_state": "approved", "membership_kind": "hr_employment", "evidence_id": "e"}
        self.assertEqual(self.aggregate([assignment()], [base])["rows"], [])
        base["membership_kind"] = "publication_snapshot"
        self.assertEqual(self.aggregate([assignment()], [base])["rows"][0]["paper_count"], 1)


if __name__ == "__main__":
    unittest.main()
