# MOST

Webpage for Measuring Open Science in Transportation Research.

## GitHub Pages hosting

The canonical site is:

```text
https://www.rerite.org/MOST/
```

## Research explorer

`explorer.html` provides selectable reader, author, and journal editor views.
The landing list shows 10 examples with both reported code/data availability and
recorded repository links. Readers can search titles and abstracts across all
10,480 papers or apply journal/topic/resource filters; results replace the
examples and appear 10 at a time. Clearing search and filters restores the examples.
Full abstracts, resource links, and correction
forms appear on demand in Details. The optional Map tab loads its plotting library
only when selected; the default list does not depend on the map CDN.
The map pairs topic/zoom controls with a synchronized paper browser. Its default
list shows up to 10 code-and-data examples within the viewport; search or active
filters show matching papers instead. The underlying map still includes the full
filtered analysis cohort.
Selecting a point or a paper highlights it and opens a stable preview; full
details remain a separate action. Pan and zoom update the nearby-paper list,
and **Fit results** restores the current filtered collection. Map gestures start
paused on phones and tablets so scrolling over the map still scrolls the page.
Authors get a title-search shortcut and can propose corrected resource links.
Editors can choose a journal and inspect availability counts and percentages
among matching papers. Perspectives are public views, not verified accounts or
access permissions.

The explorer uses the same **10,480-paper analysis cohort** as the statistics:
quantitative studies with nonempty code-availability, data-citation/link, and
data-repository classifications. `assets/explorer/analysis-cohort.json` records
the exact DOI membership derived from `stats_analysis.py` and
`data/fla_cleaned.csv`. Both builds check membership against it; a matching count
alone is insufficient. Explorer rebuilds omit records outside the cohort and
fail if any cohort DOI is missing.

The older dashboard included one additional DOI, `10.1016/j.tre.2021.102358`,
whose data classifications were missing. It is excluded here under the same
completeness rule used by the paper analysis.

The responsive shell lives in `assets/explorer/template.html`; styles and behavior
live beside it. The deployable paper database is
`assets/explorer/papers.json`. It stores each DOI once, instead of duplicating
the full metadata for code and data views. Edit the template rather than generated
`explorer.html`, then rebuild using Python's standard library:

```bash
python3 scripts/build_explorer.py
python3 scripts/build_explorer.py --check
python3 -m unittest discover -s tests
python3 -m unittest discover -s scripts -p 'test_corrections.py'
node --test tests/explorer-behavior.test.cjs
python3 -m http.server 8000
```

Open `http://localhost:8000/explorer.html`. Serve the site over HTTP rather than
opening the HTML as a local file, because the explorer fetches its JSON database.
The paper list and search remain usable if the external Plotly map library fails
to load. `dash-all-search.py` still refreshes the database from local research
CSV/metadata using pandas, then uses
the same renderer and reapplies accepted corrections.

### Reader corrections

Each paper has a **Suggest a correction** form that prepares a public GitHub
issue for the reader to review and submit. Maintainers review the evidence and
apply `correction-approved`; a GitHub Action then prepares a pull request
containing the correction audit record, manifest, and updated explorer database.
Merging the PR accepts the correction and includes it in the next Pages
deployment. There are no browser credentials or direct public database writes.

This uses GitHub Issues and Actions alongside static Pages hosting, so a separate
application server is unnecessary. Readers need a GitHub account. Repository
setup, the approval process, and the database schema are documented in
[docs/corrections.md](docs/corrections.md). The workflow files must be pushed to
the default branch, Issues and Actions must be enabled, and the repository must
allow Actions to create pull requests before automated intake can run.

## Sync the shared RERITE navigation and styles

The organization website repository is the source of truth for the shared
navbar, typography, colors, and navigation behavior. This repository vendors a
validated copy under `assets/rerite/` so the site stays static, reviewable, and
usable even if the upstream site is temporarily unavailable.

Check GitHub for updates without changing files:

```bash
python3 sync_rerite.py --check
```

Apply available updates:

```bash
python3 sync_rerite.py --apply
```

If the organization website is cloned beside this repository, the same check
can be performed without network access. This reads that clone's current
working tree, including any uncommitted navbar or stylesheet edits:

```bash
python3 sync_rerite.py --check --source-dir ../RRinTransportation.github.io
python3 sync_rerite.py --apply --source-dir ../RRinTransportation.github.io
```

The check command exits with status `0` when current, `1` when updates are
available, and `2` on a fetch or validation error. `GITHUB_TOKEN` or `GH_TOKEN`
is optional for public GitHub requests and can be set if anonymous API requests
are rate-limited.

The script:

- fetches `navbar.html` and `styles.css` from one pinned upstream commit;
- validates the expected navbar and CSS section structure before writing;
- normalizes project links to `/MOST/` so nested blog pages work;
- generates `assets/rerite/rerite-base.css` and `rerite-navbar.css`;
- updates the marked navbar/style blocks in the homepage, stats page, blog
  templates, and generated blog pages; and
- records source and generated hashes in `assets/rerite/sync-manifest.json`.

Do not edit content between `RERITE_SHARED_*` markers or generated files under
`assets/rerite/`; the next sync intentionally replaces them. The dashboard in
`explorer.html` does not currently contain a navbar and is not modified.

This UI sync does not rebuild the blog, statistics, or explorer data. The blog
templates and stats generator use the vendored assets, so later rebuilds keep
the synchronized UI. If upstream UI updates and statistics both need to be
refreshed, sync first and then regenerate:

```bash
python3 sync_rerite.py --apply
python3 stats_analysis.py
```

After applying an update, inspect and preview it before committing:

```bash
git diff --stat
python3 -m http.server 8000
```

## Blog

The blog is generated from Markdown files in `blog/posts/`:

1. Add a Markdown file to `blog/posts/`.
2. Run `python3 build_blog.py`.
3. Commit the updated HTML in `blog/`.

Blog build dependencies are `markdown` and `jinja2`:

```bash
python3 -m pip install markdown jinja2
```
