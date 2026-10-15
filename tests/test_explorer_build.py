"""Contract tests for migration fidelity, trusted overlays, and static builds."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_explorer import (
    BuildError, apply_corrections, build, encode_payload, legacy_papers,
    links_from_html, papers_from_traces, validate_payload,
)
from scripts.analysis_cohort import CohortError


def example_traces():
    metadata = [
        "https://doi.org/10.1234/EXAMPLE", "2024", "Transportation Journal",
        '<a href="https://github.com/example/code?x=1&amp;y=2">Code</a>',
        "No link found", "A title with <characters> & accents é",
        "Abstract text\nwith a second line.", "Example institution", "Traffic, openness", "Grant A", "False",
    ]
    return [
        {"x": [1.25], "y": [-2.5], "customdata": [metadata], "meta": {"view": "code", "flag": True, "topic": "Traffic"}},
        {"x": [1.25], "y": [-2.5], "customdata": [deepcopy(metadata)], "meta": {"view": "data", "flag": False, "topic": "Traffic"}},
    ]


class MigrationTests(unittest.TestCase):
    def test_migration_preserves_complete_metadata_and_separate_flags(self):
        papers = papers_from_traces(example_traces())
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["doi"], "10.1234/example")
        self.assertEqual((paper["x"], paper["y"]), (1.25, -2.5))
        self.assertEqual(paper["title"], "A title with <characters> & accents é")
        self.assertEqual(paper["abstract"], "Abstract text\nwith a second line.")
        self.assertEqual((paper["institution"], paper["keywords"], paper["funding"]), ("Example institution", "Traffic, openness", "Grant A"))
        self.assertEqual((paper["year"], paper["journal"], paper["topic"]), (2024, "Transportation Journal", "Traffic"))
        self.assertIs(paper["open_access"], False)
        self.assertIs(paper["code_available"], True)
        self.assertIs(paper["data_available"], False)
        self.assertEqual(paper["code_links"], ["https://github.com/example/code?x=1&y=2"])
        self.assertEqual(paper["data_links"], [])

    def test_linkless_available_papers_remain_available(self):
        traces = example_traces()
        for trace in traces:
            trace["customdata"][0][3] = "No link found"
        paper = papers_from_traces(traces)[0]
        self.assertIs(paper["code_available"], True)
        self.assertEqual(paper["code_links"], [])

    def test_html_links_are_parsed_and_unsafe_schemes_are_discarded(self):
        html = """<script>https://evil.test/</script>
            <a href="javascript:alert(1)">Unsafe</a><a href="data:text/html,no">Unsafe</a>
            <a href="https://user:password@example.org/private">Credentials</a>
            <a href="https://example.org/ok?q=1&amp;x=2">Safe</a>
            <a href="https://example.org/ok?q=1&amp;x=2">Duplicate</a>
            <a href="//example.org/relative">Relative</a><a href="http://example.org/data">HTTP</a>"""
        self.assertEqual(links_from_html(html), ["https://example.org/ok?q=1&x=2", "http://example.org/data"])

    def test_conflicting_metadata_and_incomplete_views_fail_closed(self):
        traces = example_traces()
        traces[1]["customdata"][0][5] = "Different title"
        with self.assertRaisesRegex(BuildError, "Conflicting metadata"):
            papers_from_traces(traces)
        with self.assertRaisesRegex(BuildError, "both legacy"):
            papers_from_traces(example_traces()[:1])
        traces = example_traces()
        traces[0]["x"] = []
        with self.assertRaisesRegex(BuildError, "different lengths"):
            papers_from_traces(traces)

    def test_legacy_html_reader_extracts_json_without_executing_javascript(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.html"
            path.write_text("<script>const traces = " + json.dumps(example_traces()) + "; throw new Error('never execute');</script>")
            self.assertEqual(legacy_papers(path), papers_from_traces(example_traces()))


class CorrectionOverlayTests(unittest.TestCase):
    def setUp(self):
        self.papers = papers_from_traces(example_traces())

    def test_reviewed_changes_are_typed_ordered_and_idempotent(self):
        records = [
            {"doi": "10.1234/example", "field": "title", "proposed_value": "First correction"},
            {"doi": "10.1234/example", "field": "title", "proposed_value": "Final correction"},
            {"doi": "10.1234/example", "field": "code_availability", "proposed_value": False},
            {"doi": "10.1234/example", "field": "data_availability", "proposed_value": True},
            {"doi": "10.1234/example", "field": "data_links", "proposed_value": ["https://example.org/data"]},
            {"doi": "10.1234/example", "field": "other", "proposed_value": "Audit note only"},
        ]
        result = apply_corrections(self.papers, records)
        self.assertEqual(result[0]["title"], "Final correction")
        self.assertIs(result[0]["code_available"], False)
        self.assertIs(result[0]["data_available"], True)
        self.assertEqual(result[0]["data_links"], ["https://example.org/data"])
        self.assertEqual(apply_corrections(result, records), result)
        self.assertEqual(self.papers, papers_from_traces(example_traces()))
        self.assertNotIn("Audit note only", encode_payload(result))

    def test_unknown_doi_and_invalid_values_cannot_publish(self):
        with self.assertRaisesRegex(BuildError, "unknown DOI"):
            apply_corrections(self.papers, [{"doi": "10.1234/missing", "field": "title", "proposed_value": "Unknown"}])
        for field, value in [("code_availability", "false"), ("code_links", ["javascript:alert(1)"]), ("data_links", [None]), ("title", None)]:
            with self.subTest(field=field, value=value), self.assertRaises(BuildError):
                apply_corrections(self.papers, [{"doi": "10.1234/example", "field": field, "proposed_value": value}])


class BuildTests(unittest.TestCase):
    def make_repository(self, root):
        (root / "assets/explorer").mkdir(parents=True)
        (root / "assets/explorer/analysis-cohort.json").write_text(json.dumps({
            "schema_version": 1, "source": "data/fla_cleaned.csv",
            "criteria": "Quantitative studies with nonempty code availability, data citation/link, and data repository classifications.",
            "paper_count": 1, "dois": ["10.1234/example"],
        }))
        (root / "assets/explorer/papers.json").write_text(encode_payload(papers_from_traces(example_traces())))
        (root / "assets/explorer/template.html").write_text("<!doctype html>\n<title>Explorer</title>\n")
        (root / "corrections/records").mkdir(parents=True)
        (root / "corrections/index.json").write_text('{"schema_version":1,"records":[]}\n')

    def test_build_is_deterministic_and_check_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repository(root)
            first = build(root)
            paths = [root / "explorer.html", root / "assets/explorer/papers.json"]
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
            self.assertEqual(build(root, check=True), first)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)
            paths[0].write_text("stale output")
            with self.assertRaisesRegex(BuildError, "explorer.html is stale"):
                build(root, check=True)
            self.assertEqual(paths[0].read_text(), "stale output")
            build(root)
            self.assertEqual([path.read_bytes() for path in paths], [item[0] for item in before])

    def test_invalid_ledger_does_not_mutate_generated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repository(root)
            build(root)
            paths = [root / "explorer.html", root / "assets/explorer/papers.json"]
            before = [path.read_bytes() for path in paths]
            (root / "corrections/index.json").write_text('{"schema_version":1,"records":[{}]}')
            with self.assertRaises(ValueError):
                build(root)
            self.assertEqual([path.read_bytes() for path in paths], before)

    def test_build_restricts_old_payload_to_the_analysis_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repository(root)
            papers = papers_from_traces(example_traces())
            extra = deepcopy(papers[0])
            extra["doi"] = "10.1234/outside-analysis"
            path = root / "assets/explorer/papers.json"
            path.write_text(encode_payload(papers + [extra]))
            original = path.read_bytes()
            with self.assertRaisesRegex(BuildError, "papers.json is stale"):
                build(root, check=True)
            self.assertEqual(path.read_bytes(), original)
            build(root)
            published = json.loads(path.read_text())["papers"]
            self.assertEqual([paper["doi"] for paper in published], ["10.1234/example"])
            build(root, check=True)

    def test_missing_cohort_or_missing_paper_identity_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repository(root)
            path = root / "assets/explorer/papers.json"
            payload = json.loads(path.read_text())
            payload["papers"][0]["doi"] = "10.1234/different-same-count"
            path.write_text(json.dumps(payload))
            original = path.read_bytes()
            with self.assertRaisesRegex(CohortError, "missing analysis cohort"):
                build(root)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((root / "explorer.html").exists())
            (root / "assets/explorer/analysis-cohort.json").unlink()
            with self.assertRaisesRegex(CohortError, "Cannot read analysis cohort"):
                build(root)
            self.assertFalse((root / "explorer.html").exists())

    def test_committed_reviewed_record_changes_the_published_database(self):
        from scripts.corrections import json_text, make_record, manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_repository(root)
            issue = {
                "number": 42, "user": {"login": "example-author"},
                "created_at": "2026-10-14T12:00:00Z", "updated_at": "2026-10-14T13:00:00Z",
                "body": "### DOI\n10.1234/example\n\n### Field\ntitle\n\n### Proposed value\nA reviewed title\n\n### Evidence\nhttps://example.org/publisher\n",
            }
            record = make_record(issue, "example-editor", "2026-10-14T14:00:00Z", "123456")
            (root / "corrections/records/issue-42.json").write_text(json_text(record))
            (root / "corrections/index.json").write_text(json_text(manifest([record])))
            build(root)
            published = json.loads((root / "assets/explorer/papers.json").read_text())
            self.assertEqual(published["papers"][0]["title"], "A reviewed title")
            self.assertEqual(build(root, check=True)["papers"], 1)

    def test_duplicate_dois_and_nonfinite_coordinates_are_rejected(self):
        papers = papers_from_traces(example_traces())
        with self.assertRaises(BuildError):
            validate_payload({"schema_version": 1, "papers": papers * 2})
        papers[0]["x"] = float("nan")
        with self.assertRaisesRegex(BuildError, "finite coordinate"):
            validate_payload({"schema_version": 1, "papers": papers})


if __name__ == "__main__":
    unittest.main()
