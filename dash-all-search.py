import pandas as pd, ast, json, numpy as np, os, re
from pathlib import Path
import matplotlib
import matplotlib.pyplot as plt

csv_path = "data/dashboard.csv"
df = pd.read_csv(csv_path)

# Ensure booleans
df['is_code_publicly_available'] = df['is_code_publicly_available'].astype(bool)
pd.set_option('future.no_silent_downcasting', True)
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
        path = Path('meta') / filename
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
df['meta_ack'] = df['doi'].apply(lambda x: get_meta_field(x, 'acknowledgement', ''))
df['meta_open_access'] = df['doi'].apply(lambda x: get_meta_field(x, 'open_access', 'False'))

# Topic column
topic_col = 'lda_topic'
topics = sorted(df[topic_col].fillna("Unknown").unique().tolist())

# Color palette (modern colormaps API; sample N distinct colors)
n_colors = max(len(topics), 1)
cmap = matplotlib.colormaps.get_cmap('tab20')
def rgba_from_cmap(i, a=1.0):
  # distribute topic indices evenly across [0, 1]
  t = 0.0 if n_colors == 1 else i / (n_colors - 1)
  r, g, b, _ = cmap(t)
  return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{a})"

topic_color = {t: rgba_from_cmap(i, 1.0) for i,t in enumerate(topics)}

def safe_str(x):
    return "" if pd.isna(x) else str(x)

# Build traces: 2 sets (Code View, Data View)
traces = []

# Helper to build traces for a specific view
def add_view_traces(view_name, flag_col, link_col, link_disp_idx):
    for t in topics:
        sub = df[df[topic_col].fillna("Unknown") == t]
        for flag in [True, False]:
            g = sub[sub[flag_col] == flag]
            if g.empty:
                continue
            
            x = g['tsne_x'].astype(float).tolist()
            y = g['tsne_y'].astype(float).tolist()
            doi = g['doi'].apply(safe_str).tolist()
            doi_url = g['doi_url'].apply(safe_str).tolist()
            year = g['year'].apply(safe_str).tolist()
            journal = g['journal'].apply(safe_str).tolist()
            
            # Metadata fields
            def short_title(title):
              if pd.isna(title):
                return ""
              words = str(title).split()
              if len(words) > 10:
                return " ".join(words[:10]) + "..."
              return str(title)
            meta_title = g['meta_title'].apply(short_title).tolist()
            meta_full_title = g['meta_title'].tolist()
            meta_abstract = g['meta_abstract'].tolist()
            meta_inst = g['meta_inst'].tolist()
            meta_keywords = g['meta_keywords'].tolist()
            meta_funding = g['meta_funding'].tolist()
            meta_ack = g['meta_ack'].tolist()
            meta_open_access = g['meta_open_access'].tolist()
            
            # Precompute display strings for both code and data
            code_links_list = g['code_links'].tolist()
            data_links_list = g['data_links'].tolist()
            
            code_disp_list = []
            for links in code_links_list:
                if not links:
                    code_disp_list.append("No link found")
                else:
                    anchors = [f"<a href='{u}' target='_blank' rel='noopener noreferrer'>{u}</a>" for u in links[:3]]
                    code_disp_list.append("<br>".join(anchors))
            
            data_disp_list = []
            for links in data_links_list:
                if not links:
                    data_disp_list.append("No link found")
                else:
                    anchors = [f"<a href='{u}' target='_blank' rel='noopener noreferrer'>{u}</a>" for u in links[:3]]
                    data_disp_list.append("<br>".join(anchors))

            color = topic_color[t]
            
            # Determine marker style based on the CURRENT view's flag
            if flag:
                # Available (Star)
                marker = {
                    "symbol": "star",
                    "size": 10,
                    "color": color.replace("rgba(", "rgba(").replace(",1.0)", ",0.85)"),
                    "line": {"color": color.replace(",1.0)", ",1)"), "width": 0.8},
                }
                name = t
                showlegend = True
            else:
                # Not Available (Circle)
                m = re.match(r"rgba\((\d+),(\d+),(\d+),", color)
                if m:
                    r, g_, b = m.group(1), m.group(2), m.group(3)
                    line_color = f"rgba({r},{g_},{b},0.5)"
                else:
                    line_color = "rgba(0,0,0,0.8)"
                marker = {
                    "symbol": "circle",
                    "size": 6,
                    "color": "rgba(0,0,0,0)",
                    "line": {"color": line_color, "width": 1},
                }
                name = t + f" (no {view_name})"
                showlegend = False

            # Hover template
            hovertemplate = (
                "<b>%{text}</b><br>"
                f"Topic: {t}<br>"
                "Year: %{customdata[1]}<br>"
                "Journal: %{customdata[2]}<br>"
                "<b>Code</b>: %{customdata[3]}<br>"
                "<b>Data</b>: %{customdata[4]}"
                "<extra></extra>"
            )

            trace = {
                "type": "scattergl",
                "mode": "markers",
                "name": name,
                "showlegend": showlegend,
                "x": x,
                "y": y,
                "text": meta_title,
                # customdata: [doi_url, year, journal, code_disp, data_disp, title, abstract, inst, keywords, funding, ack, open_access]
                "customdata": list(map(list, zip(doi_url, year, journal, code_disp_list, data_disp_list, meta_full_title, meta_abstract, meta_inst, meta_keywords, meta_funding, meta_ack, meta_open_access))),
                "hovertemplate": hovertemplate,
                "hoverlabel": {"bgcolor": "#f3f4f6", "bordercolor": "#d1d5db", "font": {"color": "#111827"}} if flag else {},
                "marker": marker,
                "meta": {"topic": t, "view": view_name, "flag": flag},
                # Initially, only show 'code' view
                "visible": (view_name == "code")
            }
            traces.append(trace)

# Generate traces for Code View
add_view_traces("code", "is_code_publicly_available", "code_links", 3)
# Generate traces for Data View
add_view_traces("data", "is_data_repository_available", "data_links", 4)

topic_options = ["All"] + topics
code_options = ["All", "Code available", "No code"]
data_options = ["All", "Data available", "No data"]

html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Open Science Explorer for Transportation Research</title>
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    :root {{
      --bg: #ffffff;
      --card: #f9fafb;
      --muted: #6b7280;
      --text: #111827;
      --border: rgba(15,23,42,0.08);
      --shadow: rgba(15,23,42,0.15);
      --radius: 14px;
    }}
    html, body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Palatino Linotype", "Book Antiqua", Palatino, "Times New Roman", serif;
    }}
    .wrap {{
      max-width: 1400px;
      margin: 28px auto;
      padding: 0 16px;
      display: flex;
      gap: 24px;
      align-items: flex-start;
    }}
    .sidebar {{
      flex: 0 0 300px;
      display: flex;
      flex-direction: column;
      gap: 24px;
      position: sticky;
      top: 28px;
      height: calc(100vh - 56px);
      overflow-y: auto;
    }}
    .main-content {{
      flex: 1;
      min-width: 0; /* Prevent flex item from overflowing */
      height: calc(100vh - 56px);
      display: flex;
      flex-direction: column;
    }}
    h1 {{
      font-size: 22px;
      margin: 0;
      letter-spacing: -0.01em;
      line-height: 1.3;
      font-weight: 600;
    }}
    .sub {{
      font-size: 14px;
      color: var(--muted);
      margin-top: 8px;
      line-height: 1.5;
    }}
    .controls {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .control {{
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      width: 100%;
      box-sizing: border-box;
      transition: box-shadow 0.2s;
    }}
    .control:hover {{
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }}
    label {{
      font-size: 13px;
      color: var(--text);
      font-weight: 600;
    }}
    select {{
      background: #f9fafb;
      color: var(--text);
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      outline: none;
      font-size: 14px;
      padding: 8px 10px;
      cursor: pointer;
      width: 100%;
      transition: border-color 0.2s;
    }}
    select:hover {{
      border-color: #d1d5db;
    }}
    select:focus {{
      border-color: #2563eb;
      ring: 2px solid rgba(37,99,235,0.1);
    }}
    input[type="text"] {{
      background: #f9fafb;
      color: var(--text);
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      outline: none;
      font-size: 14px;
      padding: 8px 10px;
      width: 100%;
      box-sizing: border-box;
      transition: border-color 0.2s;
    }}
    input[type="text"]:hover {{
      border-color: #d1d5db;
    }}
    input[type="text"]:focus {{
      border-color: #2563eb;
      ring: 2px solid rgba(37,99,235,0.1);
    }}
    .card {{
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      overflow: hidden;
      position: relative;
      flex: 1;
      display: flex;
      flex-direction: column;
    }}
    #plot {{
      flex: 1;
      width: 100%;
      height: 100%;
      min-height: 0; /* Allow shrinking */
    }}
    .footer {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }}
    .kbd {{
      font-family: "Palatino Linotype", "Book Antiqua", Palatino, "Times New Roman", serif;
      padding: 2px 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255,255,255,0.03);
      color: var(--text);
    }}
    /* Modal styles */
    .modal {{
      display: none; 
      position: fixed; 
      z-index: 1000; 
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      background-color: rgba(0,0,0,0.4);
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: auto;
    }}
    .modal-content {{
      background-color: #fefefe;
      padding: 20px;
      border: 1px solid #e5e7eb;
      border-radius: var(--radius);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
      font-family: "Palatino Linotype", "Book Antiqua", Palatino, "Times New Roman", serif;
      pointer-events: auto; /* Re-enable clicks on content */
      max-height: 80vh;
      overflow-y: auto;
      width: 90%;
      max-width: 500px;
    }}
    .close {{
      color: #aaa;
      float: right;
      font-size: 24px;
      font-weight: bold;
      cursor: pointer;
      line-height: 1;
      margin-left: 10px;
    }}
    .close:hover,
    .close:focus {{
      color: #000;
      text-decoration: none;
      cursor: pointer;
    }}
    .modal-header {{
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #e5e7eb;
    }}
    .modal-body {{
        margin-bottom: 1.5rem;
        line-height: 1.6;
    }}
    .modal-body p {{
        margin: 0.5rem 0;
    }}
    .modal-footer {{
        display: flex;
        justify-content: flex-end;
        gap: 10px;
    }}
    .btn {{
        display: inline-flex;
        align-items: center;
        padding: 0.5rem 1rem;
        font-size: 0.875rem;
        font-weight: 500;
        border-radius: 0.375rem;
        text-decoration: none;
        color: white;
        background-color: #2563eb;
        transition: background-color 0.2s;
    }}
    .btn:hover {{
        background-color: #1d4ed8;
    }}
    .btn-toggle {{
        flex: 1;
        padding: 8px;
        border: 1px solid #e5e7eb;
        background: #f9fafb;
        cursor: pointer;
        border-radius: 6px;
        font-weight: 600;
        color: var(--muted);
        transition: all 0.2s;
    }}
    .btn-toggle.active {{
        background: #2563eb;
        color: white;
        border-color: #2563eb;
    }}
    @media (max-width: 1024px) {{
      .wrap {{
        flex-direction: column;
        gap: 24px;
        margin: 16px auto;
        padding: 0 12px;
      }}
      .sidebar {{
        flex: none;
        width: 100%;
        height: auto;
        position: static;
        overflow-y: visible;
      }}
      .main-content {{
        height: 70vh;
        min-height: 400px;
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="sidebar">
      <div style="display: flex; flex-direction: column; gap: 16px;">
        <a href="https://rerite.org" target="_blank" rel="noopener noreferrer" style="display: inline-block; transition: opacity 0.2s;">
            <img src="./images/logo_png.png" alt="Logo" style="height: 60px; width: auto; align-self: flex-start;">
        </a>
        <div>
          <h1>Open Science Explorer for Transportation Research</h1>
          <div class="sub">Click a dot to view details.</div>
        </div>
      </div>
      <div class="controls">
        <div class="control">
            <label>View Mode</label>
            <div style="display: flex; gap: 8px; width: 100%;">
                <button id="btnCodeView" class="btn-toggle active">Code</button>
                <button id="btnDataView" class="btn-toggle">Data</button>
            </div>
        </div>
        <div class="control">
          <label for="topicSelect">Topic</label>
          <select id="topicSelect">
            {''.join([f'<option value="{t}">{t}</option>' for t in topic_options])}
          </select>
        </div>
        <div class="control" id="codeControl">
          <label for="codeSelect">Code Availability</label>
          <select id="codeSelect">
            {''.join([f'<option value="{c}">{c}</option>' for c in code_options])}
          </select>
        </div>
        <div class="control" id="dataControl" style="display: none;">
          <label for="dataSelect">Data Availability</label>
          <select id="dataSelect">
            {''.join([f'<option value="{d}">{d}</option>' for d in data_options])}
          </select>
        </div>
        <div class="control">
          <label for="searchInput">Search abstract (beta)</label>
          <input type="text" id="searchInput" placeholder="e.g., calibration" />
        </div>
        <div class="control">
          <button id="btnRandomWalk" class="btn" style="width: 100%; justify-content: center; background-color: #059669; border: none; cursor: pointer;">🎲 Random Walk</button>
          <div class="sub" style="margin-top: 4px; font-size: 12px;">Discover a random paper with open data or code.</div>
        </div>
      </div>
      <div class="footer" style="flex-direction: column; margin-top: auto;">
        <div>
          <span class="kbd">How to use?</span>
        </div>

        <div class="help-popup" id="helpPopup" role="dialog">
          <div class="help-content">
            <p>
              Hello! This is an interactive website for our LLM-based measurement of open science practices in transportation journals.
              By searching keywords (under beta testing) you can get a sense of the papers on the topic (circles) and which have available code or data (stars).
              Feedback is welcome! Contact
              <a href="mailto:junyi.ji@vanderbilt.edu"
                onclick="navigator.clipboard.writeText('junyi.ji@vanderbilt.edu')">
                junyi.ji@vanderbilt.edu
              </a>.
            </p>
          </div>
        </div>

        <div style="margin-top: 1rem; font-size: 0.75rem; color: var(--muted);">
            <strong>Citation:</strong>
            <pre style="white-space: pre-wrap; word-wrap: break-word; background: #f3f4f6; padding: 8px; border-radius: 4px; margin-top: 4px; font-family: monospace; font-size: 0.7rem;">@misc{{RERITE2026OTSM,
  title  = {{Measuring the State of Open Science in Transportation Using Large Language Models}},
  author = {{Ji, Junyi and Lu, Ruth and Belkessa, Linda and Wang, Liming and Varotto, Silvia and Dong, Yongqi and Saunier, Nicolas and Ameli, Mostafa and Macfarlane, Gregory S. and Madadi, Bahman and Wu, Cathy}},
  note   = {{Working paper}},
  year   = {{2025}}
}}</pre>
        </div>
      </div>
    </div>

    <div class="main-content">
      <div class="card">
        <div id="plot"></div>
        <!-- Modal -->
        <div id="infoModal" class="modal">
          <div class="modal-content">
            <span class="close">&times;</span>
            <div class="modal-header">
                <h2 id="modalTitle" style="margin:0; font-size: 1.25rem;">🔬 Discovering Open Science...</h2>
            </div>
            <div id="modalBody" class="modal-body">
            </div>
            <div id="modalFooter" class="modal-footer">
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const traces = {json.dumps(traces)};
    const layout = {{
      margin: {{l: 50, r: 22, t: 18, b: 45}},
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      hovermode: "closest",
      dragmode: "pan",
      font: {{
        family: "'Palatino Linotype', 'Book Antiqua', Palatino, 'Times New Roman', serif",
        color: "rgba(15,23,42,0.85)"
      }},
      xaxis: {{
        title: {{
          text: "x (t-SNE)",
          font: {{family: "'Palatino Linotype', 'Book Antiqua', Palatino, 'Times New Roman', serif"}}
        }},
        zeroline: false,
        gridcolor: "rgba(0,0,0,0.06)",
        color: "rgba(15,23,42,0.85)"
      }},
      yaxis: {{
        title: {{
          text: "y (t-SNE)",
          font: {{family: "'Palatino Linotype', 'Book Antiqua', Palatino, 'Times New Roman', serif"}}
        }},
        zeroline: false,
        gridcolor: "rgba(0,0,0,0.06)",
        color: "rgba(15,23,42,0.85)"
      }},
      legend: {{
        orientation: "h",
        y: 1.02,
        x: 0,
        font: {{
          size: 11,
          color: "rgba(15,23,42,0.85)",
          family: "'Palatino Linotype', 'Book Antiqua', Palatino, 'Times New Roman', serif"
        }},
        bgcolor: "rgba(0,0,0,0)"
      }}
    }};

    const config = {{
      responsive: true,
      displaylogo: false,
      scrollZoom: true
    }};

    // View state
    let currentView = "code"; // 'code' or 'data'

    // Modal logic
    const modal = document.getElementById("infoModal");
    const span = document.getElementsByClassName("close")[0];
    
    // Hide modal initially
    modal.style.display = "none";

    span.onclick = function() {{
      modal.style.display = "none";
    }}
    
    window.onclick = function(event) {{
      if (event.target == modal) {{
        modal.style.display = "none";
      }}
    }}

    function showDetails(pt) {{
        const cd = pt.customdata;
        // customdata: [doi_url, year, journal, code_disp, data_disp, title, abstract, inst, keywords]
        const doiUrl = cd && cd[0] ? cd[0] : "#";
        const year = cd && cd[1] ? cd[1] : "N/A";
        const journal = cd && cd[2] ? cd[2] : "N/A";
        const codeDisp = cd && cd[3] ? cd[3] : "No code link";
        const dataDisp = cd && cd[4] ? cd[4] : "No data link";
        const metaTitle = cd && cd[5] ? cd[5] : (pt.text || "No Title");
        const metaAbstract = cd && cd[6] ? cd[6] : "No abstract available.";
        const metaInst = cd && cd[7] ? cd[7] : "Unknown Institution";
        const metaKeywords = cd && cd[8] ? cd[8] : "";
        const metaFunding = cd && cd[9] ? cd[9] : "";
        const metaAck = cd && cd[10] ? cd[10] : "";
        const metaOpenAccess = cd && cd[11] ? cd[11] : "False";
        
        const topic = (pt.data && pt.data.meta) ? pt.data.meta.topic : (pt.topic || "Unknown");

        const modalTitle = document.getElementById("modalTitle");
        const modalBody = document.getElementById("modalBody");
        const modalFooter = document.getElementById("modalFooter");

        modalTitle.innerText = metaTitle;
        
        let content = `<p><strong>Topic:</strong> ${{topic}}</p>`;
        content += `<p><strong>Year:</strong> ${{year}}</p>`;
        content += `<p><strong>Journal:</strong> ${{journal}}</p>`;
        content += `<p><strong>Institution:</strong> ${{metaInst}}</p>`;
        content += `<p><strong>Open Access:</strong> ${{metaOpenAccess}}</p>`;
        if (metaKeywords) {{
            content += `<p><strong>Keywords:</strong> ${{metaKeywords}}</p>`;
        }}
        if (metaOpenAccess === "True" && metaFunding) {{
            content += `<p><strong>Funding:</strong> ${{metaFunding}}</p>`;
        }}
        content += `<hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 1rem 0;">`;
        content += `<p><strong>Abstract:</strong></p><p style="font-size: 0.95em; color: #374151;">${{metaAbstract}}</p>`;
        content += `<hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 1rem 0;">`;
        content += `<p><strong>Code:</strong> ${{codeDisp}}</p>`;
        content += `<p><strong>Data:</strong> ${{dataDisp}}</p>`;
        
        modalBody.innerHTML = content;

        let footerContent = "";
        if (doiUrl && doiUrl !== "#") {{
            footerContent += `<a href="${{doiUrl}}" target="_blank" class="btn">Open Paper</a>`;
        }}
        
        modalFooter.innerHTML = footerContent;

        modal.style.display = "flex";
    }}

    Plotly.newPlot("plot", traces, layout, config).then(gd => {{
      gd.on("plotly_click", (ev) => {{
        if (!ev || !ev.points || !ev.points.length) return;
        showDetails(ev.points[0]);
      }});
    }});

    function randomWalk() {{
      const candidates = [];
      traces.forEach(tr => {{
        if (tr.meta && tr.meta.flag === true) {{
          for (let i = 0; i < tr.x.length; i++) {{
            candidates.push({{
              customdata: tr.customdata[i],
              text: tr.text[i],
              topic: tr.meta.topic,
              data: tr
            }});
          }}
        }}
      }});

      if (candidates.length > 0) {{
        const randomPt = candidates[Math.floor(Math.random() * candidates.length)];
        showDetails(randomPt);
      }}
    }}

    function updateVisibility() {{
      const topic = document.getElementById("topicSelect").value;
      const code = document.getElementById("codeSelect").value;
      const data = document.getElementById("dataSelect").value;
      const searchInput = document.getElementById("searchInput");
      const searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : "";

      const vis = [];
      const markerOpacities = [];

      function matchesSearch(text, term) {{
        if (!term) return true;
        const lowerText = (text || "").toLowerCase();
        const words = term.split(/\s+/).filter(Boolean);
        if (!words.length) return true;
        // simple fuzzy-ish search: all words must appear (case-insensitive, partial match)
        return words.every(w => lowerText.includes(w));
      }}

      traces.forEach(tr => {{
        // 1. Check View
        let visible = (tr.meta.view === currentView);

        // 2. Check Topic
        if (visible) {{
          const okTopic = (topic === "All") || (tr.meta.topic === topic);
          if (!okTopic) visible = false;
        }}

        // 3. Check Filter based on View
        if (visible) {{
          if (currentView === "code") {{
              if (code === "All") {{
                  // keep visible
              }} else if (code === "Code available" && tr.meta.flag === true) {{
                  // keep visible
              }} else if (code === "No code" && tr.meta.flag === false) {{
                  // keep visible
              }} else {{
                  visible = false;
              }}
          }} else {{
              if (data === "All") {{
                  // keep visible
              }} else if (data === "Data available" && tr.meta.flag === true) {{
                  // keep visible
              }} else if (data === "No data" && tr.meta.flag === false) {{
                  // keep visible
              }} else {{
                  visible = false;
              }}
          }}
        }}

        vis.push(visible);

        // 4. Per-point opacity based on abstract search
        if (!visible) {{
          markerOpacities.push(1);
          return;
        }}

        if (!searchTerm) {{
          // no search term: show all points fully
          markerOpacities.push(1);
        }} else {{
          const cd = tr.customdata || [];
          const opacities = cd.map(row => {{
            const abstract = row && row.length > 6 ? row[6] : "";
            return matchesSearch(abstract, searchTerm) ? 1 : 0.05;
          }});
          markerOpacities.push(opacities);
        }}
      }});

      Plotly.restyle("plot", "visible", vis);
      Plotly.restyle("plot", {{"marker.opacity": markerOpacities}});
    }}

    function setView(view) {{
        currentView = view;
        
        // Update UI buttons
        document.getElementById("btnCodeView").classList.toggle("active", view === "code");
        document.getElementById("btnDataView").classList.toggle("active", view === "data");
        
        // Show/Hide controls
        document.getElementById("codeControl").style.display = (view === "code") ? "flex" : "none";
        document.getElementById("dataControl").style.display = (view === "data") ? "flex" : "none";

        updateVisibility();
    }}

    document.getElementById("btnCodeView").addEventListener("click", () => setView("code"));
    document.getElementById("btnDataView").addEventListener("click", () => setView("data"));
    document.getElementById("btnRandomWalk").addEventListener("click", randomWalk);

    document.getElementById("topicSelect").addEventListener("change", updateVisibility);
    document.getElementById("codeSelect").addEventListener("change", updateVisibility);
    document.getElementById("dataSelect").addEventListener("change", updateVisibility);
    document.getElementById("searchInput").addEventListener("input", updateVisibility);
  </script>
</body>
</html>
"""

out_path = "explorer.html"
Path(out_path).write_text(html, encoding="utf-8")
out_path