#!/usr/bin/env python3
"""Build the static explorer without requiring the research-data dependencies.

The checked-in JSON is the deployable paper database. Accepted, reviewed
corrections are overlaid before publication. The original data-processing script
can also call ``publish_traces`` to refresh this database from its source data.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from html.parser import HTMLParser
import importlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analysis_cohort import CohortError, load_cohort

PAPERS_PATH = Path("assets/explorer/papers.json")
TEMPLATE_PATH = Path("assets/explorer/template.html")
TEXT_FIELDS = ("title", "abstract", "journal", "topic", "institution", "keywords", "funding")
BOOL_FIELDS = ("open_access", "code_available", "data_available")
LINK_FIELDS = ("code_links", "data_links")
PAPER_FIELDS = {"doi", "x", "y", "year", *TEXT_FIELDS, *BOOL_FIELDS, *LINK_FIELDS}
CORRECTION_FIELDS = {
    "title": "title", "abstract": "abstract", "topic": "topic",
    "code_availability": "code_available", "data_availability": "data_available",
    "code_links": "code_links", "data_links": "data_links",
}


class BuildError(ValueError):
    """Invalid source data or an invalid reviewed correction."""


def canonical_doi(value: str) -> str:
    """Normalize DOI resolver URLs and DOI strings to one stable identifier."""
    if not isinstance(value, str):
        raise BuildError("DOI must be text")
    doi = value.strip()
    if doi.lower().startswith(("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/")):
        doi = unquote(urlsplit(doi).path.lstrip("/"))
    if doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    doi = doi.lower()
    if not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi):
        raise BuildError(f"Invalid DOI: {value!r}")
    return doi


def safe_url(value: object) -> str | None:
    """Accept absolute HTTP(S) resource URLs, with no credentials or controls."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None or "\\" in parsed.netloc:
            return None
        parsed.port  # Reject malformed port numbers as well.
    except ValueError:
        return None
    return value


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        url = safe_url(href)
        if url and url not in self.links:
            self.links.append(url)


def links_from_html(value: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(value)
    parser.close()
    return parser.links


def _legacy_bool(value: object) -> bool:
    if type(value) is bool:
        return value
    if value in ("True", "true", "1", 1):
        return True
    if value in ("False", "false", "0", 0, "", None):
        return False
    raise BuildError(f"Invalid legacy boolean: {value!r}")


def papers_from_traces(traces: list[dict]) -> list[dict]:
    """Deduplicate the old code/data Plotly views without dropping metadata."""
    if not isinstance(traces, list) or not traces:
        raise BuildError("Legacy traces must be a non-empty list")
    papers: dict[str, dict] = {}
    seen_views: dict[str, set[str]] = {}
    for trace in traces:
        meta = trace.get("meta", {})
        view = meta.get("view")
        if view not in {"code", "data"} or type(meta.get("flag")) is not bool:
            raise BuildError("Every trace needs a code/data view and a boolean availability flag")
        xs, ys, rows = trace.get("x", []), trace.get("y", []), trace.get("customdata", [])
        if not len(xs) == len(ys) == len(rows):
            raise BuildError("Legacy trace coordinates and metadata have different lengths")
        for x, y, row in zip(xs, ys, rows):
            if not isinstance(row, list) or len(row) != 11:
                raise BuildError("Legacy metadata must contain exactly 11 fields")
            doi = canonical_doi(row[0])
            try:
                year = int(row[1])
            except (TypeError, ValueError) as error:
                raise BuildError(f"Invalid publication year for {doi}") from error
            paper = {
                "doi": doi, "x": x, "y": y,
                "title": row[5], "abstract": row[6], "year": year,
                "journal": row[2], "topic": meta.get("topic", ""),
                "institution": row[7], "keywords": row[8], "funding": row[9],
                "open_access": _legacy_bool(row[10]),
                "code_available": False, "data_available": False,
                "code_links": links_from_html(row[3]), "data_links": links_from_html(row[4]),
            }
            if doi in papers:
                if view in seen_views[doi]:
                    raise BuildError(f"Duplicate {view} record for {doi}")
                shared_fields = PAPER_FIELDS - {"code_available", "data_available"}
                if any(papers[doi][field] != paper[field] for field in shared_fields):
                    raise BuildError(f"Conflicting metadata across legacy views for {doi}")
            else:
                papers[doi] = paper
                seen_views[doi] = set()
            papers[doi][f"{view}_available"] = meta["flag"]
            seen_views[doi].add(view)
    if any(views != {"code", "data"} for views in seen_views.values()):
        raise BuildError("Every paper must occur in both legacy availability views")
    result = [papers[doi] for doi in sorted(papers)]
    validate_payload({"schema_version": 1, "papers": result})
    return result


def legacy_papers(path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    marker = "const traces = "
    try:
        start = source.index(marker) + len(marker)
        traces, _ = json.JSONDecoder().raw_decode(source, start)
    except (ValueError, json.JSONDecodeError) as error:
        raise BuildError(f"Cannot read legacy traces from {path}") from error
    return papers_from_traces(traces)


def validate_payload(payload: object) -> None:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "papers"} or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise BuildError("Expected a schema_version 1 paper database")
    papers = payload["papers"]
    if not isinstance(papers, list) or not papers:
        raise BuildError("Paper database must contain a non-empty papers list")
    seen: set[str] = set()
    for paper in papers:
        if not isinstance(paper, dict) or set(paper) != PAPER_FIELDS:
            raise BuildError("Paper record has missing or unsupported fields")
        doi = canonical_doi(paper["doi"])
        if doi != paper["doi"] or doi in seen:
            raise BuildError(f"DOI is noncanonical or repeated: {doi}")
        seen.add(doi)
        for field in ("x", "y"):
            value = paper[field]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise BuildError(f"{doi}: {field} must be a finite coordinate")
        if type(paper["year"]) is not int or not 1800 <= paper["year"] <= 2200:
            raise BuildError(f"{doi}: year must be a publication year")
        for field in TEXT_FIELDS:
            if not isinstance(paper[field], str):
                raise BuildError(f"{doi}: {field} must be text")
        for field in BOOL_FIELDS:
            if type(paper[field]) is not bool:
                raise BuildError(f"{doi}: {field} must be boolean")
        for field in LINK_FIELDS:
            values = paper[field]
            if not isinstance(values, list) or any(not isinstance(value, str) or safe_url(value) != value for value in values) or len(set(values)) != len(values):
                raise BuildError(f"{doi}: {field} must contain unique absolute HTTP(S) URLs")


def load_corrections(root: Path) -> list[dict]:
    """Use the same reviewed-record validator as correction intake."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        helper = importlib.import_module("scripts.corrections")
    except ModuleNotFoundError as error:
        if error.name == "scripts.corrections" and not (root / "corrections").exists():
            return []
        raise BuildError("Correction validator is unavailable; refusing to publish unchecked records") from error
    return helper.load_records(root)


def apply_corrections(papers: list[dict], records: list[dict]) -> list[dict]:
    """Overlay accepted changes; reports for other fields remain audit entries."""
    result = {paper["doi"]: deepcopy(paper) for paper in papers}
    for record in records:
        doi = canonical_doi(record["doi"])
        if doi not in result:
            raise BuildError(f"Accepted correction refers to an unknown DOI: {doi}")
        field = record["field"]
        if field in CORRECTION_FIELDS:
            result[doi][CORRECTION_FIELDS[field]] = deepcopy(record["proposed_value"])
        elif field != "other":
            raise BuildError(f"Unsupported correction field: {field}")
    output = [result[doi] for doi in sorted(result)]
    validate_payload({"schema_version": 1, "papers": output})
    return output


def encode_payload(papers: list[dict]) -> str:
    return json.dumps({"schema_version": 1, "papers": papers}, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def build(root: Path = REPO_ROOT, *, papers: list[dict] | None = None, check: bool = False) -> dict:
    root = Path(root).resolve()
    data_path = root / PAPERS_PATH
    template_path = root / TEMPLATE_PATH
    if papers is None:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        validate_payload(payload)
        papers = payload["papers"]
    else:
        validate_payload({"schema_version": 1, "papers": papers})
    cohort = load_cohort(root)
    available_dois = {paper["doi"] for paper in papers}
    missing = cohort - available_dois
    if missing:
        raise CohortError("Explorer source is missing analysis cohort DOI(s): " + ", ".join(sorted(missing)[:5]))
    papers = [paper for paper in papers if paper["doi"] in cohort]
    records = load_corrections(root)
    papers = apply_corrections(papers, records)
    data = encode_payload(papers)
    template = template_path.read_text(encoding="utf-8")
    if not template.strip().lower().startswith("<!doctype html>"):
        raise BuildError("Explorer template must be a complete HTML document")
    output_path = root / "explorer.html"
    if check:
        if data_path.read_text(encoding="utf-8") != data:
            raise BuildError("papers.json is stale; run python3 scripts/build_explorer.py")
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != template:
            raise BuildError("explorer.html is stale; run python3 scripts/build_explorer.py")
    else:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(data, encoding="utf-8")
        output_path.write_text(template, encoding="utf-8")
    return {"papers": len(papers), "journals": len({paper["journal"] for paper in papers}), "data_bytes": len(data.encode("utf-8")), "html_bytes": len(template.encode("utf-8"))}


def publish_traces(traces: list[dict], root: Path = REPO_ROOT) -> dict:
    return build(root, papers=papers_from_traces(traces))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root (default: this script's repository)")
    parser.add_argument("--check", action="store_true", help="Validate the database, corrections, and generated page without writing files")
    parser.add_argument("--migrate-legacy", type=Path, metavar="HTML", help="Import the old inline code/data traces before building")
    args = parser.parse_args(argv)
    if args.check and args.migrate_legacy:
        parser.error("--check and --migrate-legacy cannot be combined")
    try:
        papers = legacy_papers(args.migrate_legacy) if args.migrate_legacy else None
        summary = build(args.root, papers=papers, check=args.check)
    except (BuildError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Explorer build failed: {error}", file=sys.stderr)
        return 1
    print(("Verified" if args.check else "Built") + f" explorer: {summary['papers']:,} papers, {summary['journals']} journals; " + f"{summary['data_bytes']:,} JSON bytes + {summary['html_bytes']:,} HTML bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
