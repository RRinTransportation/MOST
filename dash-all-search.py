import ast
from html import escape
import json
from pathlib import Path
import re

import pandas as pd

from scripts.analysis_cohort import load_cohort, normalize_doi, validate_cohort_membership

ROOT = Path(__file__).resolve().parent
csv_path = ROOT / "data/dashboard.csv"
df = pd.read_csv(csv_path)

# The committed analysis DOI set is also available in minimal GitHub builds.
# Restrict before metadata IO so an upstream refresh cannot add excluded papers.
cohort = load_cohort(ROOT)
normalized_dois = df['doi'].map(normalize_doi)
df = df.loc[normalized_dois.isin(cohort)].copy()
validate_cohort_membership(df['doi'], ROOT)

# Ensure booleans
df['is_code_publicly_available'] = df['is_code_publicly_available'].astype(bool)
df['is_data_repository_available'] = df['is_data_repository_available'].fillna(False).infer_objects(copy=False).astype(bool)

def parse_list_str(x):
    if pd.isna(x):
        return []
    if isinstance(x, list):
        return x
    s = str(x).strip()
    if s in ("[]", "", "nan", "None", "null"):
        return []
    try:
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return [str(i) for i in v if str(i).strip()]
        # sometimes a single string
        return [str(v)]
    except Exception:
        # fallback: try to extract urls
        urls = re.findall(r'https?://[^\s\'"\]]+', s)
        return urls

def ensure_https(urls):
    """Ensure all URLs have https:// prefix"""
    result = []
    for url in urls:
        url = str(url).strip()
        if url and not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        result.append(url)
    return result

df['code_links'] = df['code_link'].apply(parse_list_str).apply(ensure_https)
df['data_links'] = df['links_to_the_data_repository'].apply(parse_list_str).apply(ensure_https)

# Load metadata from JSON files
def load_meta(doi):
    if pd.isna(doi):
        return {}
    try:
        # Replace / with _ for filename
        filename = doi.replace('/', '_') + '.json'
        path = ROOT / 'meta' / filename
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# Pre-load metadata to avoid repeated IO
meta_cache = {}
for doi in df['doi'].unique():
    meta_cache[doi] = load_meta(doi)

def get_meta_field(doi, field, default=""):
    data = meta_cache.get(doi, {})
    val = data.get(field, default)
    if isinstance(val, list):
        return ", ".join(val)
    return str(val)

df['meta_title'] = df['doi'].apply(lambda x: get_meta_field(x, 'title', ''))
df['meta_abstract'] = df['doi'].apply(lambda x: get_meta_field(x, 'abstract', ''))
df['meta_inst'] = df['doi'].apply(lambda x: get_meta_field(x, 'primary_institution', ''))
df['meta_keywords'] = df['doi'].apply(lambda x: get_meta_field(x, 'keywords', ''))
df['meta_funding'] = df['doi'].apply(lambda x: get_meta_field(x, 'funding_agencies', ''))
df['meta_open_access'] = df['doi'].apply(lambda x: get_meta_field(x, 'open_access', 'False'))

# Topic column
topic_col = 'lda_topic'
topics = sorted(df[topic_col].fillna("Unknown").unique().tolist())

def safe_str(x):
    return "" if pd.isna(x) else str(x)

# Build traces: 2 sets (Code View, Data View)
traces = []

# Helper to build traces for a specific view
def add_view_traces(view_name, flag_col):
    for t in topics:
        sub = df[df[topic_col].fillna("Unknown") == t]
        for flag in [True, False]:
            g = sub[sub[flag_col] == flag]
            if g.empty:
                continue
            
            x = g['tsne_x'].astype(float).tolist()
            y = g['tsne_y'].astype(float).tolist()
            doi_url = g['doi_url'].apply(safe_str).tolist()
            year = g['year'].apply(safe_str).tolist()
            journal = g['journal'].apply(safe_str).tolist()
            
            # Full metadata is kept once per DOI in the published database.
            meta_full_title = g['meta_title'].tolist()
            meta_abstract = g['meta_abstract'].tolist()
            meta_inst = g['meta_inst'].tolist()
            meta_keywords = g['meta_keywords'].tolist()
            meta_funding = g['meta_funding'].tolist()
            meta_open_access = g['meta_open_access'].tolist()
            
            # Precompute display strings for both code and data
            code_links_list = g['code_links'].tolist()
            data_links_list = g['data_links'].tolist()
            
            code_disp_list = []
            for links in code_links_list:
                if not links:
                    code_disp_list.append("No link found")
                else:
                    anchors = [f"<a href='{escape(u, quote=True)}' target='_blank' rel='noopener noreferrer'>{escape(u)}</a>" for u in links]
                    code_disp_list.append("<br>".join(anchors))
            
            data_disp_list = []
            for links in data_links_list:
                if not links:
                    data_disp_list.append("No link found")
                else:
                    anchors = [f"<a href='{escape(u, quote=True)}' target='_blank' rel='noopener noreferrer'>{escape(u)}</a>" for u in links]
                    data_disp_list.append("<br>".join(anchors))

            trace = {
                "x": x,
                "y": y,
                # [doi_url, year, journal, code, data, title, abstract, institution,
                #  keywords, funding, open_access]
                "customdata": list(map(list, zip(doi_url, year, journal, code_disp_list, data_disp_list, meta_full_title, meta_abstract, meta_inst, meta_keywords, meta_funding, meta_open_access))),
                "meta": {"topic": t, "view": view_name, "flag": flag},
            }
            traces.append(trace)

# Generate traces for Code View
add_view_traces("code", "is_code_publicly_available")
# Generate traces for Data View
add_view_traces("data", "is_data_repository_available")

# Publish one canonical record per DOI. Presentation lives in the reusable template.
# The lightweight builder can also rebuild the site directly from checked-in JSON.
from scripts.build_explorer import publish_traces

summary = publish_traces(traces, Path(__file__).resolve().parent)
print(f"Built explorer with {summary['papers']:,} unique papers")
