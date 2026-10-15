# Reader corrections

The Explorer supports public, evidence-backed corrections through GitHub Issues.
It continues to run on GitHub Pages: Pages serves static HTML, CSS, and JavaScript,
so the browser cannot write directly into a repository database. Issues provide
the submission inbox; a reviewed pull request records an accepted correction and
updates the static paper database. No separate server or browser API token is
needed. [GitHub Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

## Reader experience

1. Select a paper in the Explorer and open **Suggest a correction**.
2. Choose a role: reader, author, or editor. This is self-described context;
   it does not authenticate an identity or grant approval privileges. The
   submission includes the paper DOI, title, and journal.
3. Choose one field, enter its proposed value, and include a public source URL
   with enough explanation for a maintainer to check it.
4. Open the prefilled GitHub issue, review the text, and submit it on GitHub.
   A GitHub account is required. Nothing is submitted until the reader chooses
   **Submit new issue**. Issues and their evidence are public.

The browser uses `title`, `body`, and `template=correction.md` URL parameters.
It does not request labels: ordinary readers may not have label permissions.
GitHub also limits URL length; if a long correction cannot open, use the linked
issue template directly and paste the details. [GitHub issue URL documentation](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue#creating-an-issue-from-a-url-query)

The fallback template is
[correction.md](../.github/ISSUE_TEMPLATE/correction.md). Keep its `###` headings
unchanged; duplicate or unexpected headings are rejected by the parser. Optional
fields can be blank. Use one correction field per issue.

| Field | Proposed value | Effect after a reviewed merge |
| --- | --- | --- |
| `code_availability` | `true` or `false` | Changes the code availability flag |
| `data_availability` | `true` or `false` | Changes the data availability flag |
| `code_links` | One HTTP(S) URL per line, or `[]` | Replaces the complete code link list |
| `data_links` | One HTTP(S) URL per line, or `[]` | Replaces the complete data link list |
| `title` | Plain text | Updates the title, including title search |
| `abstract` | Plain text | Updates the abstract |
| `topic` | Plain text | Updates the topic grouping/filter |
| `other` | Plain text | Records the reviewed report; a maintainer implements any additional change separately |

Availability and links are separate fields. A new repository link does not by
itself change the availability flag. If both need changing, submit two issues
and explain the relationship in the context field.

## Activate once in GitHub

These files only become active after they are committed to the repository's
default branch. This local implementation does not change repository settings,
publish a site, or submit any external issues or pull requests.

1. Enable **Issues** and **Actions** in `RRinTransportation/OTSM` if needed.
2. Create the issue label `correction-approved`. Its exact spelling matters.
3. Under **Settings → Actions → General → Workflow permissions**, enable
   **Allow GitHub Actions to create and approve pull requests** if organizational
   policy permits it. The intake workflow requests `contents: write`,
   `pull-requests: write`, and `issues: read` for its job. It only creates PRs;
   it does not approve or merge them. An organization policy can restrict this
   setting. [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests)
4. Keep the existing GitHub Pages publishing configuration. Merging a correction
   PR updates the checked-in static database; the site's normal deployment
   process then publishes it.

No personal access token, GitHub App installation, third-party form service,
or database account is required. The Actions runtime supplies `GITHUB_TOKEN`;
it is never shipped to readers.

## Maintainer review

1. Check the DOI, current record, evidence, and proposed value. Ask for a revised
   issue body if necessary. The reader's selected role is context only.
2. Add `correction-approved` to the open issue using a GitHub account with
   repository write, maintain, or admin access. A triage-only labeler is rejected.
3. The **Prepare reviewed correction** workflow verifies permissions, checks that
   the issue remains open and approved, and rejects issue-body/title changes made
   after approval. It parses and validates the proposal without executing reader
   text. The workflow runs trusted default-branch code and needs no raw `data/`
   or `meta/` files. The `issues: labeled` trigger only runs when the workflow is
   on the default branch. [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues)
4. The workflow opens a PR from `corrections/issue-N` with the audit JSON, updated
   manifest, and rebuilt paper database. Unknown DOIs, malformed values, or an
   inconsistent ledger fail before a branch is created. Review the evidence and
   generated diff, run the checks, and merge through the normal review process.
5. If GitHub displays **Approve workflows to run** on an automation-created PR,
   a maintainer with write access must approve those CI runs. Current GitHub
   behavior can require this for PRs created using `GITHUB_TOKEN`.
   [Triggering workflows from workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)

The approval label is a staging gate. The merge is the acceptance boundary.
There is no automatic merge and no direct mutation of the research source files.
To withdraw a proposal, remove the label and close its PR. Removing a label does
not retroactively delete a PR that has already been prepared.

Retries do not create duplicate open PRs or overwrite an existing branch. If a
PR could not be created because repository policy blocks it, the prepared branch
may remain; inspect it and open a PR manually. If the issue changed, close the old
PR, remove its branch, review the new issue text, and remove/re-add the label.
Two simultaneous accepted proposals can conflict in the manifest/database; resolve
them with a normal merge and rebuild, or recreate the later proposal from the
current default branch. Previously merged records are immutable audit entries;
use a new issue for a later revision.

## Repository database and rebuilds

`assets/explorer/papers.json` is the committed, deployable paper database.
Its DOI membership is fixed by `assets/explorer/analysis-cohort.json`, shared
with the paper analysis (10,480 papers). The intake rebuild fetches that manifest
alongside the database and template, excludes out-of-cohort records, and rejects
corrections for excluded or unknown DOIs. A cohort change requires a separate
reviewed update to the analysis manifest and source analysis.

`corrections/records/issue-N.json` stores each reviewed correction's canonical
DOI, field, typed proposed value, previous displayed value, evidence, context,
self-described role, journal, source issue, and approval account/time/Actions run.
The previous value is reader-provided context; it is not an automatic conflict
check. Reviewers must compare the proposal with the current database before merge.

`corrections/index.json` is a generated manifest containing the full records:

```json
{"schema_version": 1, "records": []}
```

It starts empty. Accepted records are ordered by approval time and issue number;
the later record wins when more than one changes the same DOI/field. Individual
JSON records and the manifest must agree exactly. A paper's DOI identifies its
record independently of title edits.

The intake PR builds from the same default-branch Git SHA used for its ledger.
It fetches only static input files, uses the trusted local builder, and commits
the new record, manifest, and generated output together. Reader content never
becomes a shell command or executable code. A maintainer then reviews that PR.

For a local regeneration or upstream research-data refresh:

```bash
python3 scripts/corrections.py validate
python3 scripts/build_explorer.py
python3 scripts/build_explorer.py --check
```

The builder overlays every accepted correction, including after a full refresh
through `dash-all-search.py`, so a raw-data rebuild retains reviewed fixes. It
supports the fields in the table above and fails on an unknown DOI. Changes to
`other` are audit-only. Raw `data/` and `meta/` remain outside this GitHub intake.

After intentionally adding or resolving ledger JSON files during a reviewed
local change, regenerate the manifest and database:

```bash
python3 scripts/corrections.py index
python3 scripts/build_explorer.py
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/explorer-behavior.test.cjs
```

The tests exercise typed parsing, evidence and URL checks, provenance, manifest
agreement, authorization, issue edits after approval, idempotence, unknown DOIs,
and an offline end-to-end simulated GitHub API PR. They do not send live issues,
labels, branches, or PRs. A real GitHub Actions run remains the final deployment
verification after maintainers activate the repository settings.
