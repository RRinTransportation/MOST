#!/usr/bin/env python3
"""Generate availability summaries and the MOST stats page.

This script intentionally uses only the Python standard library so the static
website can be regenerated in a minimal environment:

    python3 stats_analysis.py
"""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "fla_cleaned.csv"
OUTPUT_HTML = ROOT / "stats.html"
OUTPUT_JSON = ROOT / "data" / "stats_summary.json"
SHARED_NAVBAR_PATH = ROOT / "assets" / "rerite" / "navbar.html"
EXPECTED_ANALYSIS_N = 10480

DATA_CATEGORIES = ("available", "cite", "both", "none")
CODE_CATEGORIES = ("yes", "no")
REQUIRED_AVAILABILITY_FIELDS = (
    "is_code_publicly_available",
    "is_data_cited_or_linked",
    "is_data_repository_available",
)
GROUPS = (
    ("topic", "lda_topic", "Topic", None),
    ("journal", "journal", "Journal", None),
    ("primary_region", "clean_primary_region", "Primary Region", 25),
)
DEFAULT_GROUP = "journal"

DATA_COLORS = {
    "available": "#2B7A9B",
    "cite": "#C98A3A",
    "both": "#4B8F55",
    "none": "#D8D1C8",
}
DATA_LABELS = {
    "available": "repository only",
    "cite": "cite/link only",
    "both": "both",
    "none": "none",
}
CODE_LABELS = {
    "yes": "yes",
    "no": "no",
}
CODE_COLORS = {
    "yes": "#2B7A9B",
    "no": "#D8D1C8",
}
JOURNAL_SHORT_NAMES = {
    "Transportation Research Part A: Policy and Practice": "TR-A",
    "Transportation Research Part B: Methodological": "TR-B",
    "Transportation Research Part C: Emerging Technologies": "TR-C",
    "Transportation Research Part D: Transport and Environment": "TR-D",
    "Transportation Research Part E: Logistics and Transportation Review": "TR-E",
    "Transportation Research Part F: Traffic Psychology and Behaviour": "TR-F",
    "Transportation Research Interdisciplinary Perspectives": "TRIP",
}


def boolish(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def clean_label(value: str | None, fallback: str = "Unknown") -> str:
    value = str(value or "").strip()
    return value if value else fallback


def group_label(row: dict[str, str], field: str) -> str:
    return clean_label(row.get(field))


def display_label(label: object) -> str:
    value = str(label)
    return JOURNAL_SHORT_NAMES.get(value, value)


def data_availability(row: dict[str, str]) -> str:
    cited = boolish(row.get("is_data_cited_or_linked"))
    available = boolish(row.get("is_data_repository_available"))

    if cited and available:
        return "both"
    if available:
        return "available"
    if cited:
        return "cite"
    return "none"


def code_availability(row: dict[str, str]) -> str:
    return "yes" if boolish(row.get("is_code_publicly_available")) else "no"


def read_rows() -> list[dict[str, str]]:
    with DATA_PATH.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    return analysis_rows(rows)


def shared_navbar_html() -> str:
    """Load the vendored navbar so regenerated stats keep the shared UI."""
    try:
        navbar = SHARED_NAVBAR_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise RuntimeError(
            "Shared RERITE assets are missing; run "
            "`python3 sync_rerite.py --apply` before rebuilding stats."
        ) from error

    if '<nav class="navbar">' not in navbar:
        raise RuntimeError(f"Invalid shared navbar asset: {SHARED_NAVBAR_PATH}")
    return "\n".join(f"  {line}" if line else line for line in navbar.splitlines())


def has_complete_availability(row: dict[str, str]) -> bool:
    return all(str(row.get(field) or "").strip() for field in REQUIRED_AVAILABILITY_FIELDS)


def analysis_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Match the paper analysis set: quantitative research articles with coded availability."""
    filtered = [
        row
        for row in rows
        if boolish(row.get("is_quantitative_study")) and has_complete_availability(row)
    ]
    if len(filtered) != EXPECTED_ANALYSIS_N:
        raise RuntimeError(
            f"Expected {EXPECTED_ANALYSIS_N:,} paper-analysis rows after filtering, "
            f"but found {len(filtered):,}."
        )
    return filtered


def empty_record(label: str) -> dict[str, object]:
    return {
        "group": label,
        "n": 0,
        "code": Counter({category: 0 for category in CODE_CATEGORIES}),
        "data": Counter({category: 0 for category in DATA_CATEGORIES}),
    }


def summarize_group(rows: list[dict[str, str]], field: str) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}

    for row in rows:
        label = group_label(row, field)
        record = grouped.setdefault(label, empty_record(label))
        record["n"] = int(record["n"]) + 1
        record["code"][code_availability(row)] += 1  # type: ignore[index]
        record["data"][data_availability(row)] += 1  # type: ignore[index]

    summaries = list(grouped.values())
    summaries.sort(key=lambda item: (-int(item["n"]), str(item["group"]).lower()))
    return summaries


def pct(count: int, total: int) -> float:
    return round((count / total) * 100, 1) if total else 0.0


def flatten_record(record: dict[str, object]) -> dict[str, object]:
    total = int(record["n"])
    code = record["code"]  # type: ignore[assignment]
    data = record["data"]  # type: ignore[assignment]
    flat: dict[str, object] = {
        "group": record["group"],
        "display_group": display_label(record["group"]),
        "n": total,
    }

    for category in CODE_CATEGORIES:
        count = int(code[category])  # type: ignore[index]
        flat[f"code_{category}"] = count
        flat[f"code_{category}_pct"] = pct(count, total)

    for category in DATA_CATEGORIES:
        count = int(data[category])  # type: ignore[index]
        flat[f"data_{category}"] = count
        flat[f"data_{category}_pct"] = pct(count, total)

    flat["data_repository_any"] = int(data["available"]) + int(data["both"])  # type: ignore[index]
    flat["data_repository_any_pct"] = pct(int(flat["data_repository_any"]), total)
    flat["data_cite_or_link_any"] = int(data["cite"]) + int(data["both"])  # type: ignore[index]
    flat["data_cite_or_link_any_pct"] = pct(int(flat["data_cite_or_link_any"]), total)
    return flat


def write_summary_csv(slug: str, records: list[dict[str, object]]) -> None:
    output_path = ROOT / "data" / f"stats_summary_by_{slug}.csv"
    rows = [flatten_record(record) for record in records]
    fields = [
        "group",
        "display_group",
        "n",
        "code_yes",
        "code_yes_pct",
        "code_no",
        "code_no_pct",
        "data_available",
        "data_available_pct",
        "data_cite",
        "data_cite_pct",
        "data_both",
        "data_both_pct",
        "data_none",
        "data_none_pct",
        "data_repository_any",
        "data_repository_any_pct",
        "data_cite_or_link_any",
        "data_cite_or_link_any_pct",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(summary: dict[str, object]) -> None:
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def svg_text(value: object) -> str:
    return html.escape(str(value), quote=False)


def stacked_bar_svg(
    records: list[dict[str, object]],
    categories: tuple[str, ...],
    colors: dict[str, str],
    prefix: str,
    title: str,
    limit: int | None = None,
) -> str:
    shown = records[:limit] if limit else records
    row_height = 32
    left_width = 245
    bar_width = 430
    right_width = 70
    top = 36
    bottom = 34
    width = left_width + bar_width + right_width
    height = top + bottom + row_height * len(shown)

    parts = [
        f'<svg class="availability-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        f'<text x="0" y="18" class="chart-title">{svg_text(title)}</text>',
    ]

    for index, record in enumerate(shown):
        y = top + index * row_height
        label = str(record["group"])
        total = int(record["n"])
        parts.append(f'<text x="0" y="{y + 20}" class="chart-label">{svg_text(label)}</text>')
        parts.append(f'<rect x="{left_width}" y="{y + 6}" width="{bar_width}" height="18" rx="4" class="bar-bg"></rect>')
        x = left_width
        for category in categories:
            value = int(record[prefix][category])  # type: ignore[index]
            segment_width = 0 if total == 0 else bar_width * value / total
            if segment_width > 0:
                label_text = f"{category}: {value} ({pct(value, total)}%)"
                parts.append(
                    f'<rect x="{x:.2f}" y="{y + 6}" width="{segment_width:.2f}" '
                    f'height="18" fill="{colors[category]}"><title>{svg_text(label_text)}</title></rect>'
                )
            x += segment_width
        parts.append(f'<text x="{left_width + bar_width + 12}" y="{y + 20}" class="chart-n">n={total}</text>')

    legend_y = height - 14
    legend_x = left_width
    for category in categories:
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 10}" width="10" height="10" fill="{colors[category]}"></rect>')
        parts.append(f'<text x="{legend_x + 16}" y="{legend_y}" class="legend-label">{svg_text(category)}</text>')
        legend_x += 110

    parts.append("</svg>")
    return "\n".join(parts)


def render_html(summary: dict[str, object]) -> str:
    groups = summary["groups"]  # type: ignore[assignment]
    overall = summary["overall"]  # type: ignore[assignment]
    total = int(overall["n"])  # type: ignore[index]

    serializable = {
        "overall": flatten_record(overall),
        "groups": {
            slug: [flatten_record(record) for record in groups[slug]]  # type: ignore[index]
            for slug, *_ in GROUPS
        },
    }
    group_meta = {
        slug: {
            "title": title,
            "defaultLimit": limit or 0,
            "csv": f"data/stats_summary_by_{slug}.csv",
        }
        for slug, _field, title, limit in GROUPS
    }
    stats_json = json.dumps(serializable, ensure_ascii=False)
    meta_json = json.dumps(group_meta, ensure_ascii=False)

    sections = []
    for slug, _field, title, limit in GROUPS:
        count_note = f"Showing the top {limit} groups by article count." if limit else "Showing all groups."
        sections.append(
            f"""
      <section class="stats-section" id="{slug}" data-section="{slug}">
        <div class="section-heading">
          <h2>{html.escape(title)}</h2>
          <p>{count_note} Use the sort controls inside the chart, and hover over bar segments for counts.</p>
        </div>
        <div class="visual-stack">
          <div class="chart-panel" data-view="data">
            <div class="chart-toolbar">
              <label>
                Data sort
                <select data-control="data-sort">
                  <option value="n">Article number</option>
                  <option value="data_repository_any_pct">Any repository data %</option>
                  <option value="data_cite_or_link_any_pct">Any cite/link data %</option>
                  <option value="data_available_pct">Repository only %</option>
                  <option value="data_cite_pct">Cite/link only %</option>
                  <option value="data_none_pct" selected>Data none %</option>
                  <option value="group">Name</option>
                </select>
              </label>
              <label>
                Direction
                <select data-control="data-direction">
                  <option value="desc">High to low</option>
                  <option value="asc" selected>Low to high</option>
                </select>
              </label>
              <label class="average-toggle">
                <input type="checkbox" data-control="data-average">
                Show average line
              </label>
            </div>
            <div data-role="data-chart"></div>
          </div>
          <div class="chart-panel" data-view="code">
            <div class="chart-toolbar">
              <label>
                Code sort
                <select data-control="code-sort">
                  <option value="n">Article number</option>
                  <option value="code_yes_pct" selected>Code yes %</option>
                  <option value="code_no_pct">Code no %</option>
                  <option value="group">Name</option>
                </select>
              </label>
              <label>
                Direction
                <select data-control="code-direction">
                  <option value="desc" selected>High to low</option>
                  <option value="asc">Low to high</option>
                </select>
              </label>
              <label class="average-toggle">
                <input type="checkbox" data-control="code-average">
                Show average line
              </label>
            </div>
            <div data-role="code-chart"></div>
          </div>
        </div>
      </section>
"""
        )

    grouping_options = "\n".join(
        f'          <option value="{html.escape(slug)}"{" selected" if slug == DEFAULT_GROUP else ""}>{html.escape(title)}</option>'
        for slug, _field, title, _limit in GROUPS
    )
    view_controls = f"""
    <section class="stats-view-controls" aria-label="Choose visible stats views">
      <div class="control-group control-intro">
        <h2>Choose View</h2>
        <p>Focus the page on one analysis at a time.</p>
      </div>
      <div class="control-group">
        <label>
          Grouping
          <select data-group-select>
{grouping_options}
          </select>
        </label>
      </div>
      <div class="control-group">
        <label>
          Chart
          <select data-chart-select>
            <option value="data">Data Chart</option>
            <option value="code">Code Chart</option>
          </select>
        </label>
      </div>
    </section>
"""

    html_doc = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MOST Availability Stats</title>
  <link rel="stylesheet" href="mostyles.css">
  <!-- RERITE_SHARED_STYLES:START -->
  <link rel="stylesheet" href="assets/rerite/rerite-base.css">
  <link rel="stylesheet" href="assets/rerite/rerite-navbar.css">
  <!-- RERITE_SHARED_STYLES:END -->
  <style>
    .stats-hero {{
      padding: 2.4rem 1rem 1.8rem;
      background: linear-gradient(135deg, var(--secondary-color) 0%, #f5e8d8 100%);
      border-bottom: 1px solid var(--border-color);
    }}
    .stats-hero h1, .stats-hero p {{
      max-width: 980px;
      margin-left: auto;
      margin-right: auto;
      text-align: center;
    }}
    .stats-hero p {{
      font-size: 1.05rem;
      color: var(--text-dark);
      margin-bottom: 0;
    }}
    .stats-layout {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 1.25rem 1rem 4rem;
    }}
    .chart-panel {{
      background: #fff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      box-shadow: var(--shadow-md);
    }}
    .stats-section {{
      margin-top: 1.5rem;
    }}
    .stats-section.is-hidden,
    [data-view].is-hidden {{
      display: none !important;
    }}
    .section-heading {{
      margin: 1.5rem 0 0.85rem;
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: end;
      flex-wrap: wrap;
    }}
    .section-heading p {{
      max-width: 820px;
      margin-bottom: 0;
      font-size: 0.98rem;
    }}
    .chart-toolbar select:focus,
    .control-group select:focus {{
      outline: 2px solid rgba(43, 122, 155, 0.18);
      border-color: var(--primary-color);
    }}
    .stats-view-controls {{
      display: grid;
      grid-template-columns: 1.5fr minmax(180px, 260px) minmax(180px, 240px);
      gap: 1rem;
      align-items: end;
      margin-top: 1.25rem;
      padding: 1rem;
      background: #fff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      box-shadow: var(--shadow-md);
    }}
    .stats-view-controls h2,
    .stats-view-controls h3,
    .stats-view-controls p {{
      margin-bottom: 0.35rem;
    }}
    .stats-view-controls h2 {{
      font-size: 1.25rem;
    }}
    .stats-view-controls h3 {{
      font-family: 'Karla', sans-serif;
      font-size: 0.95rem;
      font-weight: 700;
    }}
    .control-group {{
      min-width: 0;
    }}
    .control-intro p {{
      margin-bottom: 0;
      font-size: 0.95rem;
    }}
    .control-group label {{
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      font-family: 'Karla', sans-serif;
      font-size: 0.9rem;
      font-weight: 700;
    }}
    .control-group select {{
      min-height: 38px;
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 0.45rem 0.55rem;
      background: #fbfaf7;
      color: var(--text-dark);
      font-family: 'Karla', sans-serif;
      font-size: 0.95rem;
      max-width: 320px;
    }}
    .toggle-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}
    .toggle-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      min-height: 38px;
      padding: 0.35rem 0.7rem;
      border: 1px solid var(--border-color);
      border-radius: 999px;
      background: #fbfaf7;
      color: var(--text-dark);
      font-family: 'Karla', sans-serif;
      font-size: 0.92rem;
      font-weight: 700;
      cursor: pointer;
    }}
    .toggle-pill:has(input:checked) {{
      border-color: var(--primary-color);
      background: rgba(43, 122, 155, 0.1);
      color: var(--primary-dark);
    }}
    .toggle-pill input {{
      accent-color: var(--primary-color);
    }}
    .visual-stack {{
      display: grid;
      gap: 1rem;
      align-items: start;
    }}
    .chart-panel {{
      padding: 1rem 1rem 0.85rem;
      overflow-x: auto;
    }}
    .chart-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: end;
      margin: -0.1rem 0 0.85rem;
      padding: 0 0 0.85rem;
      border-bottom: 1px solid var(--border-color);
      font-family: 'Karla', sans-serif;
    }}
    .chart-toolbar label {{
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--text-dark);
    }}
    .chart-toolbar select {{
      min-height: 34px;
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 0.35rem 0.5rem;
      background: #fbfaf7;
      color: var(--text-dark);
      font-family: 'Karla', sans-serif;
      font-size: 0.92rem;
    }}
    .chart-toolbar .average-toggle {{
      min-height: 34px;
      flex-direction: row;
      align-items: center;
      gap: 0.45rem;
      padding-top: 1.1rem;
      white-space: nowrap;
    }}
    .average-toggle input {{
      accent-color: var(--primary-color);
      margin: 0;
    }}
    .availability-chart {{
      display: block;
      width: 100%;
      min-width: 760px;
      height: auto;
      font-family: 'Karla', sans-serif;
    }}
    .chart-title {{
      font-size: 16px;
      font-weight: 700;
      fill: var(--text-dark);
    }}
    .chart-label {{
      font-size: 12px;
      fill: var(--text-dark);
    }}
    .chart-n, .legend-label {{
      font-size: 11.5px;
      fill: var(--text-light);
    }}
    .axis-label {{
      font-size: 10.5px;
      fill: var(--text-light);
    }}
    .axis-grid {{
      stroke: #ece5dc;
      stroke-width: 1;
    }}
    .average-line {{
      stroke: #c23b2e;
      stroke-width: 2;
      stroke-dasharray: 5 4;
      pointer-events: none;
    }}
    .average-label {{
      fill: #c23b2e;
      font-size: 10.5px;
      font-weight: 700;
    }}
    .chart-percent {{
      font-size: 10px;
      fill: #fff;
      font-weight: 700;
      pointer-events: none;
    }}
    .chart-percent.is-dark {{
      fill: var(--text-dark);
    }}
    .bar-bg {{
      fill: #f2eee8;
    }}
    .chart-segment {{
      cursor: help;
      transition: opacity 0.15s ease;
    }}
    .chart-segment:hover {{
      opacity: 0.82;
    }}
    .chart-tooltip {{
      position: fixed;
      z-index: 2000;
      display: none;
      max-width: 320px;
      padding: 0.45rem 0.6rem;
      border-radius: 6px;
      background: rgba(44, 62, 80, 0.96);
      color: #fff;
      font-family: 'Karla', sans-serif;
      font-size: 0.86rem;
      line-height: 1.35;
      pointer-events: none;
      box-shadow: var(--shadow-md);
    }}
    .chart-tooltip.is-visible {{
      display: block;
    }}
    @media (max-width: 900px) {{
      .stats-view-controls {{
        grid-template-columns: 1fr 1fr;
      }}
      .control-intro {{
        grid-column: 1 / -1;
      }}
      .stats-hero {{
        padding: 2rem 1rem 1.5rem;
      }}
    }}
    @media (max-width: 560px) {{
      .stats-view-controls {{
        grid-template-columns: 1fr;
      }}
      .control-intro {{
        grid-column: auto;
      }}
    }}
  </style>
</head>
<body>
  <!-- RERITE_SHARED_NAV:START -->
__RERITE_SHARED_NAV__
  <!-- RERITE_SHARED_NAV:END -->

  <header class="stats-hero">
    <h1>Availability Stats</h1>
    <p>Explore code and data availability by topic, journal, and primary region for the paper analysis set (N=10,480).</p>
  </header>

  <main class="stats-layout">
    __VIEW_CONTROLS__

    __SECTIONS__
  </main>
  <div class="chart-tooltip" data-role="chart-tooltip"></div>

  <footer>
    <div class="container">
      <div class="footer-bottom">
        <p>&copy; 2024 - 2026 <a href="https://rerite.org/MOST">MOST Project</a>. All rights reserved.</p>
      </div>
    </div>
  </footer>
  <script>
    const STATS_DATA = __STATS_JSON__;
    const GROUP_META = __GROUP_META_JSON__;
    const CODE_CATEGORIES = ["yes", "no"];
    const DATA_CATEGORIES = ["available", "cite", "both", "none"];
    const CODE_COLORS = {"yes": "#2B7A9B", "no": "#D8D1C8"};
    const DATA_COLORS = {"available": "#2B7A9B", "cite": "#C98A3A", "both": "#4B8F55", "none": "#D8D1C8"};
    const CODE_LABELS = {"yes": "yes", "no": "no"};
    const DATA_LABELS = {"available": "repository only", "cite": "cite/link only", "both": "both", "none": "none"};
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, function(char) {
        return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char];
      });
    }

    function percent(count, total) {
      return total ? Math.round((count / total * 100) * 10) / 10 : 0;
    }

    function shortLabel(value, maxLength = 34) {
      const text = String(value ?? "");
      return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
    }

    function sortRows(rows, metric, direction) {
      const multiplier = direction === "asc" ? 1 : -1;
      return rows.slice().sort((a, b) => {
        if (metric === "group") {
          return a.display_group.localeCompare(b.display_group) * multiplier;
        }
        const diff = (Number(a[metric]) || 0) - (Number(b[metric]) || 0);
        if (diff !== 0) return diff * multiplier;
        return a.display_group.localeCompare(b.display_group);
      });
    }

    function isLightColor(hexColor) {
      const hex = String(hexColor || "").replace("#", "");
      if (hex.length !== 6) return false;
      const red = parseInt(hex.slice(0, 2), 16);
      const green = parseInt(hex.slice(2, 4), 16);
      const blue = parseInt(hex.slice(4, 6), 16);
      const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
      return luminance > 0.62;
    }

    function metricLabel(metric) {
      const labels = {
        data_repository_any_pct: "any repository data",
        data_cite_or_link_any_pct: "any cite/link data",
        data_available_pct: "repository only",
        data_cite_pct: "cite/link only",
        data_none_pct: "data none",
        code_yes_pct: "code yes",
        code_no_pct: "code no",
      };
      return labels[metric] || "";
    }

    function averageReference(metric, invertFromHundred = false, labelOverride = null) {
      const rawValue = Number(STATS_DATA.overall?.[metric]);
      const label = labelOverride || metricLabel(metric);
      if (!Number.isFinite(rawValue) || !label) return null;
      const value = invertFromHundred ? Math.round((100 - rawValue) * 10) / 10 : rawValue;
      const detail = `${value}%`;
      return {
        value,
        label: `Overall average: ${label} = ${detail}`,
      };
    }

    function chartSvg(rows, categories, colors, labels, prefix, title, average) {
      const rowHeight = 36;
      const leftWidth = 292;
      const barWidth = 520;
      const rightWidth = 88;
      const top = 58;
      const bottom = 52;
      const width = leftWidth + barWidth + rightWidth;
      const height = top + bottom + rowHeight * rows.length;
      let svg = `<svg class="availability-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}">`;
      svg += `<text x="0" y="18" class="chart-title">${escapeHtml(title)}</text>`;
      svg += `<text x="${leftWidth}" y="18" class="axis-label">Share of articles</text>`;

      [0, 25, 50, 75, 100].forEach((tick) => {
        const x = leftWidth + barWidth * tick / 100;
        svg += `<line x1="${x.toFixed(2)}" y1="${top - 8}" x2="${x.toFixed(2)}" y2="${top + rowHeight * rows.length - 6}" class="axis-grid"></line>`;
        svg += `<text x="${x.toFixed(2)}" y="${top - 16}" text-anchor="middle" class="axis-label">${tick}%</text>`;
      });

      rows.forEach((row, index) => {
        const y = top + index * rowHeight;
        const total = Number(row.n) || 0;
        svg += `<text x="0" y="${y + 22}" class="chart-label">${escapeHtml(shortLabel(row.display_group))}<title>${escapeHtml(row.group)}</title></text>`;
        svg += `<rect x="${leftWidth}" y="${y + 7}" width="${barWidth}" height="20" rx="5" class="bar-bg"></rect>`;
        let x = leftWidth;
        categories.forEach((category) => {
          const value = Number(row[`${prefix}_${category}`]) || 0;
          const segmentWidth = total ? barWidth * value / total : 0;
          if (segmentWidth > 0) {
            const pct = percent(value, total);
            const groupDetail = row.display_group === row.group ? row.group : `${row.display_group} (${row.group})`;
            const categoryLabel = labels[category] || category;
            const tooltip = `${groupDetail}: ${categoryLabel} = ${value.toLocaleString()} articles (${pct}%)`;
            svg += `<rect x="${x.toFixed(2)}" y="${y + 7}" width="${segmentWidth.toFixed(2)}" height="20" fill="${colors[category]}" class="chart-segment" data-tooltip="${escapeHtml(tooltip)}"><title>${escapeHtml(tooltip)}</title></rect>`;
            if (segmentWidth > 40) {
              const percentClass = isLightColor(colors[category]) ? "chart-percent is-dark" : "chart-percent";
              svg += `<text x="${(x + segmentWidth / 2).toFixed(2)}" y="${y + 21}" text-anchor="middle" class="${percentClass}">${pct}%</text>`;
            }
          }
          x += segmentWidth;
        });
        svg += `<text x="${leftWidth + barWidth + 14}" y="${y + 22}" class="chart-n">n=${total.toLocaleString()}</text>`;
      });

      if (average && Number.isFinite(average.value)) {
        const averageValue = Math.max(0, Math.min(100, Number(average.value)));
        const averageX = leftWidth + barWidth * averageValue / 100;
        const labelX = Math.max(leftWidth + 4, Math.min(leftWidth + barWidth - 4, averageX));
        const labelAnchor = averageValue > 84 ? "end" : averageValue < 16 ? "start" : "middle";
        const lineBottom = top + rowHeight * rows.length - 6;
        svg += `<line x1="${averageX.toFixed(2)}" y1="${top - 8}" x2="${averageX.toFixed(2)}" y2="${lineBottom}" class="average-line"><title>${escapeHtml(average.label)}</title></line>`;
        svg += `<text x="${labelX.toFixed(2)}" y="${top - 31}" text-anchor="${labelAnchor}" class="average-label">${escapeHtml(average.label)}</text>`;
      }

      let legendX = leftWidth;
      const legendY = height - 18;
      categories.forEach((category) => {
        svg += `<rect x="${legendX}" y="${legendY - 10}" width="10" height="10" fill="${colors[category]}"></rect>`;
        svg += `<text x="${legendX + 16}" y="${legendY}" class="legend-label">${escapeHtml(labels[category] || category)}</text>`;
        legendX += 122;
      });
      svg += "</svg>";
      return svg;
    }

    function dataCategoryOrder(sortMetric) {
      if (["data_cite_or_link_any_pct", "data_cite_pct"].includes(sortMetric)) {
        return ["cite", "both", "available", "none"];
      }
      return ["available", "both", "cite", "none"];
    }

    function renderSection(section) {
      const slug = section.dataset.section;
      const meta = GROUP_META[slug];
      const dataSortMetric = section.querySelector('[data-control="data-sort"]').value;
      const dataDirection = section.querySelector('[data-control="data-direction"]').value;
      const codeSortMetric = section.querySelector('[data-control="code-sort"]').value;
      const codeDirection = section.querySelector('[data-control="code-direction"]').value;
      const showDataAverage = section.querySelector('[data-control="data-average"]').checked;
      const showCodeAverage = section.querySelector('[data-control="code-average"]').checked;
      const limitValue = Number(meta.defaultLimit) || 0;
      const rows = STATS_DATA.groups[slug] || [];
      const dataSorted = sortRows(rows, dataSortMetric, dataDirection);
      const codeSorted = sortRows(rows, codeSortMetric, codeDirection);
      const dataShown = limitValue > 0 ? dataSorted.slice(0, limitValue) : dataSorted;
      const codeShown = limitValue > 0 ? codeSorted.slice(0, limitValue) : codeSorted;
      section.querySelector('[data-role="data-chart"]').innerHTML = chartSvg(dataShown, dataCategoryOrder(dataSortMetric), DATA_COLORS, DATA_LABELS, "data", `Data availability by ${meta.title}`, showDataAverage ? averageReference("data_none_pct", true, "(100% - data none)") : null);
      section.querySelector('[data-role="code-chart"]').innerHTML = chartSvg(codeShown, CODE_CATEGORIES, CODE_COLORS, CODE_LABELS, "code", `Code availability by ${meta.title}`, showCodeAverage ? averageReference("code_yes_pct") : null);
    }

    function applyViewPreferences() {
      const selectedSection = document.querySelector("[data-group-select]")?.value;
      const selectedView = document.querySelector("[data-chart-select]")?.value;
      document.querySelectorAll("[data-section]").forEach((section) => {
        const sectionVisible = section.dataset.section === selectedSection;
        section.classList.toggle("is-hidden", !sectionVisible);
        section.querySelectorAll("[data-view]").forEach((view) => {
          view.classList.toggle("is-hidden", view.dataset.view !== selectedView);
        });
      });
    }

    document.querySelectorAll("[data-section]").forEach((section) => {
      section.querySelectorAll('[data-control$="-sort"], [data-control$="-direction"], [data-control$="-average"]').forEach((control) => {
        control.addEventListener("change", () => renderSection(section));
      });
      renderSection(section);
    });
    document.querySelectorAll("[data-group-select], [data-chart-select]").forEach((input) => {
      input.addEventListener("change", applyViewPreferences);
    });
    const tooltip = document.querySelector('[data-role="chart-tooltip"]');
    document.addEventListener("mousemove", (event) => {
      if (!tooltip || !tooltip.classList.contains("is-visible")) return;
      tooltip.style.left = `${event.clientX + 12}px`;
      tooltip.style.top = `${event.clientY + 12}px`;
    });
    document.addEventListener("mouseover", (event) => {
      const segment = event.target.closest?.(".chart-segment");
      if (!tooltip || !segment) return;
      tooltip.textContent = segment.dataset.tooltip || "";
      tooltip.style.left = `${event.clientX + 12}px`;
      tooltip.style.top = `${event.clientY + 12}px`;
      tooltip.classList.add("is-visible");
    });
    document.addEventListener("mouseout", (event) => {
      if (!tooltip || !event.target.closest?.(".chart-segment")) return;
      tooltip.classList.remove("is-visible");
    });
    applyViewPreferences();
  </script>
</body>
</html>
"""
    html_doc = html_doc.replace("{{", "{").replace("}}", "}")
    return (
        html_doc.replace("__VIEW_CONTROLS__", view_controls)
        .replace("__SECTIONS__", "".join(sections))
        .replace("__STATS_JSON__", stats_json)
        .replace("__GROUP_META_JSON__", meta_json)
        .replace("__RERITE_SHARED_NAV__", shared_navbar_html())
    )


def main() -> None:
    rows = read_rows()
    overall = empty_record("Overall")
    for row in rows:
        overall["n"] = int(overall["n"]) + 1
        overall["code"][code_availability(row)] += 1  # type: ignore[index]
        overall["data"][data_availability(row)] += 1  # type: ignore[index]

    groups = {}
    for slug, field, _title, _limit in GROUPS:
        records = summarize_group(rows, field)
        groups[slug] = records
        write_summary_csv(slug, records)

    summary = {"overall": overall, "groups": groups}
    serializable = {
        "overall": flatten_record(overall),
        "groups": {
            slug: [flatten_record(record) for record in records]
            for slug, records in groups.items()
        },
    }
    write_summary_json(serializable)
    OUTPUT_HTML.write_text(render_html(summary), encoding="utf-8")
    print(f"Wrote {OUTPUT_HTML.relative_to(ROOT)}")
    print(f"Wrote {OUTPUT_JSON.relative_to(ROOT)}")
    for slug, *_ in GROUPS:
        print(f"Wrote data/stats_summary_by_{slug}.csv")


if __name__ == "__main__":
    main()
