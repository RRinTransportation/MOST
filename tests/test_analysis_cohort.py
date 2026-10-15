"""The Explorer and analysis must use the same identities, not just the same N."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.analysis_cohort import CohortError, load_cohort, validate_cohort_membership
import stats_analysis


def cohort_manifest(dois):
    return {
        "schema_version": 1, "source": "data/fla_cleaned.csv",
        "criteria": "Quantitative studies with nonempty code availability, data citation/link, and data repository classifications.",
        "paper_count": len(dois), "dois": dois,
    }


def write_manifest(root, value):
    path = root / "assets/explorer/analysis-cohort.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class CohortTests(unittest.TestCase):
    def test_exact_membership_accepts_input_order_and_normalizes_doi_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, cohort_manifest(["10.1234/first", "10.1234/second"]))
            self.assertEqual(load_cohort(root), {"10.1234/first", "10.1234/second"})
            self.assertEqual(validate_cohort_membership(["10.1234/SECOND", "10.1234/first"], root), load_cohort(root))

    def test_matching_count_cannot_hide_a_different_paper_or_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, cohort_manifest(["10.1234/first", "10.1234/second"]))
            with self.assertRaisesRegex(CohortError, "missing 1 DOI.*outside cohort 1 DOI"):
                validate_cohort_membership(["10.1234/first", "10.1234/different"], root)
            with self.assertRaisesRegex(CohortError, "duplicate DOI"):
                validate_cohort_membership(["10.1234/first", "10.1234/FIRST"], root)

    def test_bad_schema_count_order_and_noncanonical_identities_are_rejected(self):
        valid = cohort_manifest(["10.1234/first", "10.1234/second"])
        invalid = []
        for key, value in [("schema_version", True), ("source", "data/dashboard.csv"), ("criteria", "Another cohort"), ("paper_count", 1), ("paper_count", True), ("dois", ["10.1234/second", "10.1234/first"]), ("dois", ["10.1234/first", "10.1234/first"]), ("dois", ["10.1234/FIRST", "10.1234/second"]), ("dois", ["not a DOI", "10.1234/second"])]:
            value_manifest = deepcopy(valid)
            value_manifest[key] = value
            invalid.append(value_manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(CohortError):
                    write_manifest(root, value)
                    load_cohort(root)

    def test_missing_and_repeated_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(CohortError, "Cannot read analysis cohort"):
                load_cohort(root)
            write_manifest(root, cohort_manifest(["10.1234/example"]))
            path = root / "assets/explorer/analysis-cohort.json"
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaisesRegex(CohortError, "Repeated cohort JSON key"):
                load_cohort(root)


class AnalysisSelectionTests(unittest.TestCase):
    def test_existing_predicate_and_false_classifications_still_select_the_cohort(self):
        valid = {
            "doi": "10.1234/example", "is_quantitative_study": "True",
            "is_code_publicly_available": "False", "is_data_cited_or_linked": "False",
            "is_data_repository_available": "False",
        }
        missing = {**valid, "doi": "10.1234/missing-data", "is_data_cited_or_linked": ""}
        nonquantitative = {**valid, "doi": "10.1234/nonquantitative", "is_quantitative_study": "False"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, cohort_manifest(["10.1234/example"]))
            with patch.object(stats_analysis, "ROOT", root), patch.object(stats_analysis, "EXPECTED_ANALYSIS_N", 1):
                self.assertEqual(stats_analysis.analysis_rows([valid, missing, nonquantitative]), [valid])
                changed_identity = {**valid, "doi": "10.1234/different-same-count"}
                with self.assertRaisesRegex(CohortError, "does not match the analysis cohort"):
                    stats_analysis.analysis_rows([changed_identity])


if __name__ == "__main__":
    unittest.main()
