"""Validate the committed paper-analysis cohort without local research CSVs."""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import re


COHORT_PATH = Path("assets/explorer/analysis-cohort.json")
COHORT_SOURCE = "data/fla_cleaned.csv"
COHORT_CRITERIA = "Quantitative studies with nonempty code availability, data citation/link, and data repository classifications."


class CohortError(ValueError):
    """The committed cohort or a proposed paper collection is inconsistent."""


def normalize_doi(value: object) -> str:
    if not isinstance(value, str):
        raise CohortError("Cohort DOI must be text")
    doi = value.strip().lower()
    if not re.fullmatch(r"10\.\d{4,9}/[^\s<>\"']+", doi):
        raise CohortError(f"Invalid cohort DOI: {value!r}")
    return doi


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CohortError(f"Repeated cohort JSON key: {key}")
        result[key] = value
    return result


def load_cohort(root: Path) -> set[str]:
    """Read a canonical, sorted DOI whitelist shared by stats and the Explorer."""
    path = Path(root) / COHORT_PATH
    try:
        cohort = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, ValueError) as error:
        raise CohortError(f"Cannot read analysis cohort {COHORT_PATH}: {error}") from error
    expected = {"schema_version", "source", "criteria", "paper_count", "dois"}
    if not isinstance(cohort, dict) or set(cohort) != expected:
        raise CohortError("Invalid analysis cohort schema")
    if type(cohort["schema_version"]) is not int or cohort["schema_version"] != 1:
        raise CohortError("Expected analysis cohort schema_version 1")
    if cohort["source"] != COHORT_SOURCE or cohort["criteria"] != COHORT_CRITERIA:
        raise CohortError("Analysis cohort source or selection criteria changed")
    count, dois = cohort["paper_count"], cohort["dois"]
    if type(count) is not int or count < 1 or not isinstance(dois, list) or len(dois) != count:
        raise CohortError("Analysis cohort paper_count does not match its DOI list")
    canonical = [normalize_doi(doi) for doi in dois]
    if canonical != dois or dois != sorted(set(canonical)):
        raise CohortError("Analysis cohort DOIs must be canonical, sorted, and unique")
    return set(dois)


def validate_cohort_membership(dois: Iterable[str], root: Path) -> set[str]:
    """Require exact paper identities, including no duplicates, rather than count alone."""
    expected = load_cohort(root)
    canonical = [normalize_doi(doi) for doi in dois]
    actual = set(canonical)
    if len(actual) != len(canonical):
        raise CohortError("Paper collection contains duplicate DOI identities")
    missing, extra = expected - actual, actual - expected
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing {len(missing)} DOI(s): {', '.join(sorted(missing)[:5])}")
        if extra:
            problems.append(f"outside cohort {len(extra)} DOI(s): {', '.join(sorted(extra)[:5])}")
        raise CohortError("Paper collection does not match the analysis cohort; " + "; ".join(problems))
    return actual
