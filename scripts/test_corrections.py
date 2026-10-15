"""Offline contract and trust-boundary tests for the correction intake."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import corrections as c


BODY = """### DOI
https://doi.org/10.1234/Example

### Paper title
Example paper

### Role
author

### Journal
Example Journal

### Field
code_availability

### Current value
false

### Proposed value
true

### Evidence
The repository is now public: https://github.com/example/research

### Additional context
Updated after publication.
"""


def event_fixture():
    return {
        "action": "labeled", "label": {"name": c.APPROVAL_LABEL},
        "repository": {"full_name": c.REPOSITORY}, "sender": {"login": "maintainer"},
        "issue": {
            "number": 17, "body": BODY, "title": "[Correction] Example paper",
            "state": "open", "labels": [{"name": c.APPROVAL_LABEL}],
            "user": {"login": "reader"}, "created_at": "2026-10-14T12:00:00Z",
            "updated_at": "2026-10-14T13:00:00Z",
        },
    }


def record_fixture():
    issue = event_fixture()["issue"]
    return c.make_record(issue, "maintainer", issue["updated_at"], 123)


class FakeGitHub:
    """A deterministic in-memory GitHub API, including base-tree blob reads."""

    def __init__(self):
        self.event = event_fixture()
        self.live_issue = deepcopy(self.event["issue"])
        self.permission = "write"
        self.existing_prs = []
        self.existing_branch = None
        self.posts = []
        self.blobs = {}
        paper = {
            "doi": "10.1234/example", "x": 1.0, "y": 2.0, "year": 2026,
            "title": "Example paper", "abstract": "A paper.",
            "journal": "Example Journal", "topic": "Transport", "institution": "",
            "keywords": "", "funding": "", "open_access": False,
            "code_available": False, "data_available": False,
            "code_links": [], "data_links": [],
        }
        contents = {
            "corrections/index.json": c.json_text(c.manifest([])),
            "assets/explorer/papers.json": json.dumps({"schema_version": 1, "papers": [paper]}) + "\n",
            "assets/explorer/analysis-cohort.json": json.dumps({
                "schema_version": 1,
                "source": "data/fla_cleaned.csv",
                "criteria": "Quantitative studies with nonempty code availability, data citation/link, and data repository classifications.",
                "paper_count": 1,
                "dois": ["10.1234/example"],
            }) + "\n",
            "assets/explorer/template.html": "<!doctype html><html lang=\"en\"><title>Explorer</title></html>\n",
            "explorer.html": "<!doctype html><html lang=\"en\"><title>Explorer</title></html>\n",
        }
        self.entries = []
        for path, content in contents.items():
            sha = self.add_blob(content)
            self.entries.append({"path": path, "type": "blob", "mode": "100644", "sha": sha, "size": len(content.encode())})

    def add_blob(self, content):
        sha = hashlib.sha256(content.encode()).hexdigest()
        self.blobs[sha] = content
        return sha

    def request(self, method, path, data=None, missing_ok=False):
        prefix = "/repos/" + c.REPOSITORY
        if method == "GET":
            if path.endswith("/permission"):
                return {"permission": self.permission}
            if path == prefix + "/issues/17":
                return deepcopy(self.live_issue)
            if path == prefix:
                return {"default_branch": "main"}
            if path.startswith(prefix + "/pulls?"):
                return self.existing_prs
            if path == prefix + "/git/ref/heads/corrections/issue-17":
                return self.existing_branch
            if path == prefix + "/git/ref/heads/main":
                return {"object": {"sha": "base-sha"}}
            if path == prefix + "/git/commits/base-sha":
                return {"tree": {"sha": "base-tree"}}
            if path == prefix + "/git/trees/base-tree?recursive=1":
                return {"sha": "base-tree", "tree": deepcopy(self.entries), "truncated": False}
            if path.startswith(prefix + "/git/blobs/"):
                text = self.blobs[path.rsplit("/", 1)[-1]]
                return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
        if method == "POST":
            self.posts.append((path, deepcopy(data)))
            if path.endswith("/git/blobs"):
                return {"sha": self.add_blob(data["content"])}
            if path.endswith("/git/trees"):
                return {"sha": "new-tree"}
            if path.endswith("/git/commits"):
                return {"sha": "new-commit"}
            if path.endswith("/git/refs"):
                return {"ref": data["ref"]}
            if path.endswith("/pulls"):
                return {"html_url": "https://github.com/" + c.REPOSITORY + "/pull/99"}
        raise AssertionError(f"Unexpected request: {method} {path}")


class CorrectionTests(unittest.TestCase):
    def test_intake_accepts_an_aggregate_manifest_larger_than_one_record(self):
        api = FakeGitHub()
        records = []
        for number in range(100, 150):
            issue = deepcopy(api.event["issue"])
            issue["number"] = number
            record = c.make_record(issue, "maintainer", issue["updated_at"], "123")
            record["context"] = ("Reviewed supporting context. " * 120).strip()
            c.validate_record(record)
            records.append(record)
            text = c.json_text(record)
            api.entries.append({"path": f"corrections/records/issue-{number}.json", "type": "blob", "mode": "100644", "sha": api.add_blob(text), "size": len(text.encode())})
        index = c.json_text(c.manifest(records))
        self.assertGreater(len(index.encode()), 131072)
        entry = next(entry for entry in api.entries if entry["path"] == "corrections/index.json")
        entry.update(sha=api.add_blob(index), size=len(index.encode()))
        self.assertEqual(c.publish(api, api.event, "123"), "https://github.com/" + c.REPOSITORY + "/pull/99")

    def test_parse_preserves_role_and_normalizes_doi_and_boolean(self):
        value = c.parse_issue_body(BODY)
        self.assertEqual(value["doi"], "10.1234/example")
        self.assertIs(value["proposed_value"], True)
        self.assertEqual(value["role"], "author")
        self.assertEqual(value["journal"], "Example Journal")

    def test_links_are_typed_and_empty_list_is_explicit(self):
        body = BODY.replace("code_availability", "code_links").replace("\ntrue\n", "\nhttps://example.org/a\nhttps://example.org/b\n")
        self.assertEqual(c.parse_issue_body(body)["proposed_value"], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(c.proposed_value("data_links", "[]"), [])

    def test_unsafe_urls_and_invalid_types_are_rejected(self):
        for url in ("javascript:alert(1)", "data:text/html,hello", "https://user:secret@example.org", "https://example.org/\nother", "https://example.org:bad/path", "https://example.org/'><script>"):
            with self.subTest(url=url), self.assertRaises(c.ValidationError):
                c.proposed_value("code_links", url)
        with self.assertRaises(c.ValidationError):
            c.proposed_value("code_availability", "yes")

    def test_duplicate_headings_and_missing_evidence_are_rejected(self):
        for body in (BODY + "\n### DOI\n10.1234/other", BODY.replace("https://github.com/example/research", "no source"), BODY.replace("### Field", "### Unrecognized field")):
            with self.subTest(body=body[-70:]), self.assertRaises(c.ValidationError):
                c.parse_issue_body(body)

    def test_role_is_self_described_but_constrained(self):
        with self.assertRaises(c.ValidationError):
            c.parse_issue_body(BODY.replace("\nauthor\n", "\nverified-editor\n"))

    def test_shell_markup_remains_inert_plain_text(self):
        body = BODY.replace("code_availability", "title").replace("\ntrue\n", "\n$(touch /tmp/should-not-exist) <script>alert(1)</script>\n")
        self.assertEqual(c.parse_issue_body(body)["proposed_value"], "$(touch /tmp/should-not-exist) <script>alert(1)</script>")

    def test_record_provenance_and_typed_values(self):
        record = record_fixture()
        self.assertEqual(record["id"], "issue-17")
        self.assertEqual(record["review"]["approved_by"], "maintainer")
        for value in (1, "true"):
            broken = deepcopy(record)
            broken["proposed_value"] = value
            with self.assertRaises(c.ValidationError):
                c.validate_record(broken)

    def test_manifest_is_verified_against_per_issue_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "corrections/records").mkdir(parents=True)
            record = record_fixture()
            (root / "corrections/records/issue-17.json").write_text(c.json_text(record))
            index = root / "corrections/index.json"
            index.write_text(c.json_text(c.manifest([record])))
            self.assertEqual(c.load_records(root), [record])
            index.write_text(c.json_text(c.manifest([])))
            with self.assertRaises(c.ValidationError):
                c.load_records(root)

    def test_manifest_rejects_boolean_schema_and_json_duplicate_keys(self):
        with self.assertRaises(c.ValidationError):
            c.validate_manifest({"schema_version": True, "records": []})
        with self.assertRaises(c.ValidationError):
            c.read_json('{"schema_version":1,"schema_version":2}')

    def test_approval_order_uses_time_then_issue_number(self):
        later = record_fixture()
        later["review"]["approved_at"] = "2026-10-14T13:00:00.123Z"
        earlier = record_fixture()
        earlier["id"] = "issue-18"
        earlier["issue"]["number"] = 18
        earlier["issue"]["url"] = f"https://github.com/{c.REPOSITORY}/issues/18"
        self.assertEqual([record["id"] for record in c.manifest([later, earlier])["records"]], ["issue-18", "issue-17"])

    def test_untrusted_labeler_cannot_create_a_branch(self):
        api = FakeGitHub()
        api.permission = "triage"
        with self.assertRaises(c.ValidationError):
            c.publish(api, api.event, 123)
        self.assertEqual(api.posts, [])

    def test_changed_issue_removed_label_and_closed_issue_do_not_publish(self):
        for change in ({"body": BODY + "Reader changed it"}, {"labels": []}, {"state": "closed"}, {"pull_request": {}}):
            api = FakeGitHub()
            api.live_issue.update(change)
            with self.subTest(change=change), self.assertRaises(c.ValidationError):
                c.publish(api, api.event, 123)
            self.assertEqual(api.posts, [])

    def test_existing_pr_is_idempotent_and_existing_branch_is_never_overwritten(self):
        api = FakeGitHub()
        api.existing_prs = [{"html_url": "https://example.org/existing-pr"}]
        self.assertEqual(c.publish(api, api.event, 123), "https://example.org/existing-pr")
        self.assertEqual(api.posts, [])
        api.existing_prs = []
        api.existing_branch = {"object": {"sha": "do-not-overwrite"}}
        with self.assertRaises(c.ValidationError):
            c.publish(api, api.event, 123)
        self.assertEqual(api.posts, [])

    def test_unknown_doi_fails_before_any_github_mutation(self):
        api = FakeGitHub()
        api.event["issue"]["body"] = BODY.replace("10.1234/Example", "10.1234/missing")
        api.live_issue = deepcopy(api.event["issue"])
        with self.assertRaises(ValueError):
            c.publish(api, api.event, 123)
        self.assertEqual(api.posts, [])

    def test_missing_analysis_cohort_fails_before_any_github_mutation(self):
        api = FakeGitHub()
        api.entries = [entry for entry in api.entries if entry["path"] != "assets/explorer/analysis-cohort.json"]
        with self.assertRaisesRegex(c.ValidationError, "static Explorer build inputs"):
            c.publish(api, api.event, 123)
        self.assertEqual(api.posts, [])

    def test_rebuild_preserves_exact_cohort_and_rejects_corrections_outside_it(self):
        for correct_excluded_paper in (False, True):
            api = FakeGitHub()
            entry = next(item for item in api.entries if item["path"] == "assets/explorer/papers.json")
            payload = json.loads(api.blobs[entry["sha"]])
            extra = deepcopy(payload["papers"][0])
            extra["doi"] = "10.1234/excluded"
            payload["papers"].append(extra)
            text = json.dumps(payload) + "\n"
            entry.update(sha=api.add_blob(text), size=len(text.encode()))
            with self.subTest(correct_excluded_paper=correct_excluded_paper):
                if correct_excluded_paper:
                    api.event["issue"]["body"] = BODY.replace("10.1234/Example", extra["doi"])
                    api.live_issue = deepcopy(api.event["issue"])
                    with self.assertRaisesRegex(ValueError, "unknown DOI"):
                        c.publish(api, api.event, 123)
                    self.assertEqual(api.posts, [])
                else:
                    c.publish(api, api.event, 123)
                    tree = next(data for path, data in api.posts if path.endswith("/git/trees"))
                    output = next(item for item in tree["tree"] if item["path"] == "assets/explorer/papers.json")
                    accepted = json.loads(api.blobs[output["sha"]])["papers"]
                    self.assertEqual([paper["doi"] for paper in accepted], ["10.1234/example"])
                    self.assertIs(accepted[0]["code_available"], True)

    def test_publish_changes_only_ledger_and_rebuilt_database(self):
        api = FakeGitHub()
        self.assertEqual(c.publish(api, api.event, 123), f"https://github.com/{c.REPOSITORY}/pull/99")
        trees = [data for path, data in api.posts if path.endswith("/git/trees")]
        self.assertEqual(len(trees), 1)
        self.assertEqual(trees[0]["base_tree"], "base-tree")
        changes = {entry["path"]: entry for entry in trees[0]["tree"]}
        self.assertEqual(set(changes), {"corrections/records/issue-17.json", "corrections/index.json", "assets/explorer/papers.json"})
        payload = json.loads(api.blobs[changes["assets/explorer/papers.json"]["sha"]])
        self.assertEqual([paper["doi"] for paper in payload["papers"]], ["10.1234/example"])
        self.assertIs(payload["papers"][0]["code_available"], True)
        refs = [data for path, data in api.posts if path.endswith("/git/refs")]
        self.assertEqual(refs, [{"ref": "refs/heads/corrections/issue-17", "sha": "new-commit"}])
        prs = [data for path, data in api.posts if path.endswith("/pulls")]
        self.assertEqual(prs[0]["base"], "main")
        self.assertIn("Closes #17", prs[0]["body"])


if __name__ == "__main__":
    unittest.main()
