# MOST

Webpage for Measuring Open Science in Transportation Research.

## GitHub Pages hosting

The canonical site is:

```text
https://www.rerite.org/MOST/
```

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
