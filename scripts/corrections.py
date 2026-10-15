#!/usr/bin/env python3
"""Validate the correction ledger and propose reviewed issue records via GitHub.

No reader input is executed. ``publish`` is only used by the trusted default-
branch issues workflow; it creates a reviewable PR, never merges or edits data/.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


REPOSITORY = "RRinTransportation/OTSM"
APPROVAL_LABEL = "correction-approved"
FIELDS = {
    "code_availability", "data_availability", "code_links", "data_links",
    "title", "abstract", "topic", "other",
}
HEADINGS = {
    "DOI": "doi", "Paper title": "paper_title", "Role": "role",
    "Journal": "journal", "Field": "field", "Current value": "previous_value",
    "Proposed value": "proposed_value", "Evidence": "evidence",
    "Additional context": "context",
}
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?\Z")


class ValidationError(ValueError):
    """Reader data or ledger data does not satisfy the correction contract."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(text):
    return json.loads(text, object_pairs_hook=_unique_object)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def plain_text(value, name, limit=20000, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"{name} must be text of at most {limit} characters")
    if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in value):
        raise ValidationError(f"{name} contains control characters")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{name} is required")
    return value


def normalize_doi(value):
    value = plain_text(value, "DOI", 512, required=True)
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    if not re.fullmatch(r"10\.\d{4,9}/[^\s<>\"']+", value):
        raise ValidationError("DOI must be a DOI such as 10.1016/j.example.2026.123456")
    return value.lower()


def http_url(value):
    value = plain_text(value, "URL", 2048, required=True)
    if re.search(r"[\s<>\"'\\]", value):
        raise ValidationError("URLs must not contain whitespace, quotes, or markup")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
        # Accessing port also rejects malformed ports.
        parsed.port
    except ValueError as error:
        raise ValidationError("Invalid URL") from error
    if not valid:
        raise ValidationError("Use an HTTP(S) URL without embedded credentials")
    return value


def evidence_text(value):
    value = plain_text(value, "Evidence", 8000, required=True)
    candidates = re.findall(r"https?://[^\s<>\"']+", value)
    valid = False
    for candidate in candidates:
        try:
            http_url(candidate.rstrip(").,;]}"))
            valid = True
        except ValidationError:
            pass
    if not valid:
        raise ValidationError("Evidence must include at least one HTTP(S) source URL")
    return value


def proposed_value(field, value):
    if field not in FIELDS:
        raise ValidationError("Unknown correction field")
    value = plain_text(value, "Proposed value", required=True)
    if field.endswith("_availability"):
        if value.lower() not in {"true", "false"}:
            raise ValidationError("Availability must be true or false")
        return value.lower() == "true"
    if field in {"code_links", "data_links"}:
        if value == "[]":
            return []
        links = [http_url(line.strip()) for line in value.splitlines() if line.strip()]
        if not links or len(links) > 20 or len(links) != len(set(links)):
            raise ValidationError("Supply up to 20 distinct links, one per line, or []")
        return links
    if field in {"title", "topic"} and len(value) > 1000:
        raise ValidationError("Title and topic must be at most 1000 characters")
    return value


def parse_issue_body(body):
    body = plain_text(body, "Issue body", 65536, required=True).replace("\r\n", "\n")
    matches = list(re.finditer(r"^### (.+?)\s*$", body, re.M))
    values = {}
    for index, match in enumerate(matches):
        heading = match.group(1)
        if heading not in HEADINGS:
            raise ValidationError(f"Unexpected issue heading: {heading}")
        key = HEADINGS[heading]
        if key in values:
            raise ValidationError(f"Repeated issue heading: {heading}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end():end].strip()
        values[key] = "" if value in {"_No response_", "<!-- optional -->"} else value
    for key in {"doi", "field", "proposed_value", "evidence"}:
        if not values.get(key):
            raise ValidationError(f"Missing required issue field: {key}")
    values["doi"] = normalize_doi(values["doi"])
    values["field"] = values["field"].strip()
    values["proposed_value"] = proposed_value(values["field"], values["proposed_value"])
    values["evidence"] = evidence_text(values["evidence"])
    values["role"] = values.get("role", "reader").strip().lower() or "reader"
    if values["role"] not in {"reader", "author", "editor"}:
        raise ValidationError("Role must be reader, author, or editor (self-described)")
    for key, limit in {"paper_title": 1000, "journal": 1000, "previous_value": 20000, "context": 8000}.items():
        values[key] = plain_text(values.get(key, ""), key, limit)
    return values


def timestamp(value, name):
    value = plain_text(value, name, 40, required=True)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
    except ValueError as error:
        raise ValidationError(f"{name} must be an ISO 8601 timestamp with timezone") from error
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def login(value):
    if not isinstance(value, str) or not LOGIN.fullmatch(value):
        raise ValidationError("Invalid GitHub account name")
    return value


def positive_integer(value, name):
    if type(value) is not int or value < 1:
        raise ValidationError(f"{name} must be a positive integer")
    return value


def make_record(issue, reviewer, approved_at, action_run_id):
    number = positive_integer(issue.get("number"), "Issue number")
    values = parse_issue_body(issue.get("body", ""))
    if not re.fullmatch(r"\d+", str(action_run_id)):
        raise ValidationError("Invalid Actions run ID")
    record = {
        "schema_version": 1, "id": f"issue-{number}", **values,
        "issue": {
            "number": number,
            "url": f"https://github.com/{REPOSITORY}/issues/{number}",
            "author": login(issue.get("user", {}).get("login")),
            "created_at": timestamp(issue.get("created_at"), "Issue creation time"),
            "updated_at": timestamp(issue.get("updated_at"), "Issue update time"),
        },
        "review": {
            "approved_by": login(reviewer),
            "approved_at": timestamp(approved_at, "Approval time"),
            "action_run_url": f"https://github.com/{REPOSITORY}/actions/runs/{action_run_id}",
        },
    }
    return validate_record(record)


def validate_record(record):
    expected = {"schema_version", "id", "doi", "paper_title", "role", "journal", "field", "previous_value", "proposed_value", "evidence", "context", "issue", "review"}
    if not isinstance(record, dict) or set(record) != expected or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValidationError("Invalid correction record schema")
    issue, review = record["issue"], record["review"]
    if not isinstance(issue, dict) or set(issue) != {"number", "url", "author", "created_at", "updated_at"}:
        raise ValidationError("Invalid issue provenance")
    if not isinstance(review, dict) or set(review) != {"approved_by", "approved_at", "action_run_url"}:
        raise ValidationError("Invalid review provenance")
    number = positive_integer(issue["number"], "Issue number")
    if record["id"] != f"issue-{number}" or issue["url"] != f"https://github.com/{REPOSITORY}/issues/{number}":
        raise ValidationError("Issue identity does not match record")
    if normalize_doi(record["doi"]) != record["doi"]:
        raise ValidationError("Record DOI is not canonical")
    if record["role"] not in {"reader", "author", "editor"} or record["field"] not in FIELDS:
        raise ValidationError("Invalid role or field")
    for key, limit in {"paper_title": 1000, "journal": 1000, "previous_value": 20000, "context": 8000}.items():
        if plain_text(record[key], key, limit) != record[key]:
            raise ValidationError(f"{key} must be trimmed")
    value = record["proposed_value"]
    if record["field"].endswith("_availability"):
        if type(value) is not bool:
            raise ValidationError("Availability record value must be boolean")
    elif record["field"] in {"code_links", "data_links"}:
        if not isinstance(value, list) or len(value) > 20:
            raise ValidationError("Links record value must be an array")
        checked = [http_url(link) for link in value]
        if checked != value or len(value) != len(set(checked)):
            raise ValidationError("Duplicate links")
    elif proposed_value(record["field"], value) != value:
        raise ValidationError("Invalid proposed text")
    if evidence_text(record["evidence"]) != record["evidence"]:
        raise ValidationError("Evidence must be trimmed")
    login(issue["author"])
    login(review["approved_by"])
    for key in ("created_at", "updated_at"):
        timestamp(issue[key], key)
    timestamp(review["approved_at"], "approved_at")
    if not re.fullmatch(rf"https://github\.com/{re.escape(REPOSITORY)}/actions/runs/\d+", review["action_run_url"]):
        raise ValidationError("Invalid Actions provenance URL")
    return record


def manifest(records):
    for record in records:
        validate_record(record)
    if len({record["id"] for record in records}) != len(records):
        raise ValidationError("Duplicate issue records")
    return {"schema_version": 1, "records": sorted(records, key=lambda record: (dt.datetime.fromisoformat(timestamp(record["review"]["approved_at"], "approved_at").replace("Z", "+00:00")), record["issue"]["number"]))}


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "records"} or type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["records"], list):
        raise ValidationError("Invalid correction manifest schema")
    if value != manifest(value["records"]):
        raise ValidationError("Correction manifest records must be in approval order")
    return value


def load_records(repo_root):
    """Load accepted, committed records and verify their generated manifest."""
    root = Path(repo_root) / "corrections"
    records = []
    for path in sorted((root / "records").glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 131072:
            raise ValidationError(f"Invalid ledger file: {path.name}")
        record = validate_record(read_json(path.read_text(encoding="utf-8")))
        if path.name != record["id"] + ".json":
            raise ValidationError(f"Record filename does not match issue: {path.name}")
        records.append(record)
    expected = manifest(records)
    actual = validate_manifest(read_json((root / "index.json").read_text(encoding="utf-8")))
    if actual != expected:
        raise ValidationError("corrections/index.json does not match corrections/records; run the index command")
    return expected["records"]


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, data=None, missing_ok=False):
        if not path.startswith("/") or path.startswith("//"):
            raise ValidationError("Invalid API path")
        request = Request(
            "https://api.github.com" + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "MOST-correction-ledger"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                return read_json(response.read().decode())
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            # Do not log the request headers, token, or untrusted API response body.
            raise RuntimeError(f"GitHub API {method} {path.split('?')[0]} returned HTTP {error.code}") from None


def _approved_issue(api, event):
    if event.get("action") != "labeled" or event.get("label", {}).get("name") != APPROVAL_LABEL:
        raise ValidationError("Expected a correction-approved labeling event")
    if event.get("repository", {}).get("full_name") != REPOSITORY:
        raise ValidationError("Unexpected repository")
    snapshot = event.get("issue", {})
    number = positive_integer(snapshot.get("number"), "Issue number")
    reviewer = login(event.get("sender", {}).get("login"))
    permission = api.request("GET", f"/repos/{REPOSITORY}/collaborators/{quote(reviewer)}/permission")
    if permission.get("permission") not in {"write", "maintain", "admin"}:
        raise ValidationError("Approval requires repository write, maintain, or admin access")
    live = api.request("GET", f"/repos/{REPOSITORY}/issues/{number}")
    if "pull_request" in live or live.get("state") != "open":
        raise ValidationError("Correction must be an open issue")
    if APPROVAL_LABEL not in {label.get("name") for label in live.get("labels", [])}:
        raise ValidationError("Approval label has been removed")
    # Never silently accept a reader edit made after the maintainer labeled it.
    if live.get("body") != snapshot.get("body") or live.get("title") != snapshot.get("title"):
        raise ValidationError("Issue changed after approval; review it and remove/re-add the approval label")
    return snapshot, reviewer


def _blob_text(api, prefix, entry, limit=52428800):
    if entry["type"] != "blob" or entry["mode"] != "100644" or entry.get("size", 0) > limit:
        raise ValidationError("Invalid or oversized repository input file")
    blob = api.request("GET", prefix + "/git/blobs/" + entry["sha"])
    if blob.get("encoding") != "base64":
        raise ValidationError("Unsupported repository blob encoding")
    return base64.b64decode(blob["content"]).decode("utf-8")


def rebuild_files(api, prefix, entries, records):
    """Build the reviewed proposal using trusted local code and base-SHA data."""
    source_paths = (
        "assets/explorer/papers.json",
        "assets/explorer/template.html",
        "assets/explorer/analysis-cohort.json",
    )
    if any(path not in entries for path in source_paths):
        raise ValidationError("Default branch does not contain the static Explorer build inputs")
    root_path = str(Path(__file__).resolve().parents[1])
    if root_path not in sys.path:
        sys.path.insert(0, root_path)
    builder = importlib.import_module("scripts.build_explorer")
    with tempfile.TemporaryDirectory(prefix="most-correction-") as directory:
        root = Path(directory)
        for path in source_paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_blob_text(api, prefix, entries[path]), encoding="utf-8")
        (root / "corrections/records").mkdir(parents=True)
        for record in records:
            (root / "corrections/records" / (record["id"] + ".json")).write_text(json_text(record), encoding="utf-8")
        (root / "corrections/index.json").write_text(json_text(manifest(records)), encoding="utf-8")
        builder.build(root)
        builder.build(root, check=True)
        return {path: (root / path).read_text(encoding="utf-8") for path in ("assets/explorer/papers.json", "explorer.html")}


def publish(api, event, action_run_id):
    issue, reviewer = _approved_issue(api, event)
    record = make_record(issue, reviewer, issue["updated_at"], action_run_id)
    prefix = f"/repos/{REPOSITORY}"
    repository = api.request("GET", prefix)
    default_branch = repository["default_branch"]
    branch = "corrections/" + record["id"]
    head_query = urlencode({"state": "open", "head": REPOSITORY.split("/")[0] + ":" + branch})
    existing_prs = api.request("GET", prefix + "/pulls?" + head_query)
    if existing_prs:
        return existing_prs[0]["html_url"]
    existing_branch = api.request("GET", prefix + "/git/ref/heads/" + quote(branch, safe="/"), missing_ok=True)
    if existing_branch:
        raise ValidationError(f"Branch {branch} already exists. Review it and create the PR manually, or delete it before retrying; it will not be overwritten")
    base = api.request("GET", prefix + "/git/ref/heads/" + quote(default_branch, safe="/"))["object"]["sha"]
    base_tree = api.request("GET", prefix + "/git/commits/" + base)["tree"]["sha"]
    tree = api.request("GET", prefix + "/git/trees/" + base_tree + "?recursive=1")
    if tree.get("truncated"):
        raise ValidationError("Repository tree is truncated; refusing an incomplete correction index")
    records, old_index = [], None
    entries = {entry["path"]: entry for entry in tree["tree"]}
    for entry in tree["tree"]:
        path = entry["path"]
        if path == "corrections/index.json" or re.fullmatch(r"corrections/records/issue-\d+\.json", path):
            # The manifest aggregates every accepted record and grows over time.
            # It must not inherit the much smaller limit for individual reports.
            limit = 52428800 if path == "corrections/index.json" else 262144
            value = read_json(_blob_text(api, prefix, entry, limit))
            if path == "corrections/index.json":
                old_index = validate_manifest(value)
            else:
                validate_record(value)
                if path != "corrections/records/" + value["id"] + ".json":
                    raise ValidationError("Ledger filename does not match record identity")
                records.append(value)
        elif path.startswith("corrections/records/") and path.endswith(".json"):
            raise ValidationError("Unexpected correction ledger filename")
    if old_index != manifest(records):
        raise ValidationError("Default-branch correction manifest is inconsistent")
    if record["id"] in {item["id"] for item in records}:
        raise ValidationError("This issue already has a merged record; submit a new issue to revise it")
    accepted = records + [record]
    files = {
        "corrections/records/" + record["id"] + ".json": json_text(record),
        "corrections/index.json": json_text(manifest(accepted)),
        **rebuild_files(api, prefix, entries, accepted),
    }
    changes = []
    for path, content in files.items():
        blob = api.request("POST", prefix + "/git/blobs", {"content": content, "encoding": "utf-8"})
        if path not in entries or entries[path]["sha"] != blob["sha"]:
            changes.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = api.request("POST", prefix + "/git/trees", {"base_tree": tree["sha"], "tree": changes})
    commit = api.request("POST", prefix + "/git/commits", {"message": f"Record reviewed correction from issue #{issue['number']}", "tree": new_tree["sha"], "parents": [base]})
    # Recheck before creating any visible branch/PR; never merge automatically.
    _approved_issue(api, event)
    api.request("POST", prefix + "/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    pr = api.request("POST", prefix + "/pulls", {
        "title": f"Record correction #{issue['number']} in the review ledger",
        "head": branch, "base": default_branch,
        "body": f"Records the maintainer-reviewed proposal from #{issue['number']} with its evidence and approval provenance, and rebuilds the static Explorer database.\n\nReview the proposed value, evidence, and generated database diff before merging. Merging accepts the correction into the public ledger and Explorer. The raw data files are unchanged.\n\nCloses #{issue['number']}.",
    })
    return pr["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "index", "publish"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--event", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            print(f"Validated {len(load_records(args.root))} correction records")
        elif args.command == "index":
            records = [validate_record(read_json(path.read_text(encoding="utf-8"))) for path in (args.root / "corrections/records").glob("*.json")]
            (args.root / "corrections/index.json").write_text(json_text(manifest(records)), encoding="utf-8")
            load_records(args.root)
            print(f"Indexed {len(records)} correction records")
        else:
            if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or not args.event:
                raise ValidationError("Publishing requires the repository Actions environment and --event")
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise ValidationError("GITHUB_TOKEN is required")
            event = read_json(args.event.read_text(encoding="utf-8"))
            print(publish(GitHub(token), event, os.environ.get("GITHUB_RUN_ID", "")))
        return 0
    except (ValidationError, ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(f"Correction error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
