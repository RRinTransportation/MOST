/* Accessible list and responsive map for the public, static explorer. */
(() => {
  "use strict";

  const PAGE_SIZE = 10;
  const MAP_PAGE_SIZE = 10;
  const ISSUE_BASE = "https://github.com/RRinTransportation/OTSM/issues/new";
  const PLOTLY_URL = "https://cdn.plot.ly/plotly-2.30.0.min.js";
  const CORRECTION_FIELDS = new Set(["code_availability", "data_availability", "code_links", "data_links", "title", "abstract", "topic", "other"]);
  const COLORS = ["#326b89", "#b56735", "#557b51", "#8361a0", "#a44c66", "#638343", "#487d80", "#926c35", "#5a6bb0", "#a75343", "#706b97", "#698452", "#9a648b", "#597b93", "#8c7454"];
  const normalize = value => String(value ?? "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  function safeUrl(value) {
    try {
      const url = new URL(String(value ?? "").trim());
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function safeLinks(values) {
    return [...new Set((Array.isArray(values) ? values : []).map(safeUrl).filter(Boolean))];
  }

  function normalizeDoi(value) {
    return String(value ?? "").trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "").replace(/^doi:\s*/i, "").toLowerCase();
  }

  function doiUrl(value) {
    const doi = normalizeDoi(value);
    if (!/^10\.\d{4,9}\/[^\s<>"']+$/i.test(doi)) return null;
    const url = new URL("https://doi.org/");
    url.pathname = "/" + doi;
    return url.href;
  }

  function buildIndex(rows) {
    const unique = new Map();
    rows.forEach(row => {
      if (!row || typeof row !== "object") return;
      const doi = normalizeDoi(row.doi);
      const title = String(row.title || "Untitled paper");
      const journal = String(row.journal || "Journal not recorded");
      const id = doi || [normalize(title), row.year || "", normalize(journal)].join("|");
      const record = {
        id, doi, title, journal,
        year: String(row.year || ""),
        abstract: String(row.abstract || ""),
        topic: String(row.topic || "Uncategorized"),
        institution: String(row.institution || ""),
        keywords: String(row.keywords || ""),
        funding: String(row.funding || ""),
        openAccess: row.open_access === true,
        x: typeof row.x === "number" && Number.isFinite(row.x) ? row.x : null,
        y: typeof row.y === "number" && Number.isFinite(row.y) ? row.y : null,
        available: {code: row.code_available === true, data: row.data_available === true},
        links: {code: safeLinks(row.code_links), data: safeLinks(row.data_links)},
        searchTitle: normalize(title), searchAbstract: normalize(row.abstract)
      };
      if (!unique.has(id)) unique.set(id, record);
      else {
        const existing = unique.get(id);
        ["code", "data"].forEach(view => {
          existing.available[view] ||= record.available[view];
          existing.links[view] = [...new Set([...existing.links[view], ...record.links[view]])];
        });
      }
    });
    return [...unique.values()];
  }

  function filterRecords(records, filters) {
    const words = normalize(filters.query).trim().split(/\s+/).filter(Boolean);
    return records.filter(record => {
      if (filters.topic !== "All" && record.topic !== filters.topic) return false;
      if (filters.journal !== "All" && record.journal !== filters.journal) return false;
      if (filters.availability === "available" && !record.available[filters.view]) return false;
      if (filters.availability === "unavailable" && record.available[filters.view]) return false;
      const text = filters.scope === "title" ? record.searchTitle : filters.scope === "abstract" ? record.searchAbstract : record.searchTitle + " " + record.searchAbstract;
      return words.every(word => text.includes(word));
    });
  }

  function isDiscoveryMode(filters) {
    return !String(filters.query || "").trim() && (filters.topic || "All") === "All"
      && (filters.journal || "All") === "All" && (filters.availability || "All") === "All";
  }

  function newestFirst(a, b) {
    return Number(b.year) - Number(a.year) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
  }

  function featuredPapers(records, limit = 10) {
    return records.filter(record => record.available.code && record.available.data && record.links.code.length && record.links.data.length)
      .sort(newestFirst).slice(0, Math.max(0, limit));
  }

  function paperBounds(records, padding = 0.08) {
    let left = Infinity, right = -Infinity, bottom = Infinity, top = -Infinity;
    records.forEach(record => {
      if (!Number.isFinite(record.x) || !Number.isFinite(record.y)) return;
      left = Math.min(left, record.x); right = Math.max(right, record.x);
      bottom = Math.min(bottom, record.y); top = Math.max(top, record.y);
    });
    if (!Number.isFinite(left)) return null;
    const padX = Math.max((right - left) * padding, 0.5);
    const padY = Math.max((top - bottom) * padding, 0.5);
    return {x: [left - padX, right + padX], y: [bottom - padY, top + padY]};
  }

  function inViewport(record, viewport) {
    if (!Number.isFinite(record.x) || !Number.isFinite(record.y)) return false;
    if (!viewport) return true;
    return record.x >= Math.min(...viewport.x) && record.x <= Math.max(...viewport.x)
      && record.y >= Math.min(...viewport.y) && record.y <= Math.max(...viewport.y);
  }

  function zoomRange(range, factor) {
    if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isFinite) || !Number.isFinite(factor) || factor <= 0) return null;
    const center = (range[0] + range[1]) / 2;
    const half = Math.max(Math.abs(range[1] - range[0]) * factor / 2, 0.001);
    return range[0] > range[1] ? [center + half, center - half] : [center - half, center + half];
  }

  function escapePlotText(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function currentValue(record, field) {
    if (field === "code_availability") return String(record.available.code);
    if (field === "data_availability") return String(record.available.data);
    if (field === "code_links") return record.links.code.join("\n") || "[]";
    if (field === "data_links") return record.links.data.join("\n") || "[]";
    return ["title", "abstract", "topic"].includes(field) ? record[field] : "";
  }

  function correctionBody(record, field, proposed, evidence, role, journal) {
    const current = currentValue(record, field);
    const shortCurrent = current.length > 800 ? current.slice(0, 800) + "\n[Current value shortened for this report]" : current;
    return [
      ["DOI", record.doi], ["Paper title", record.title], ["Role", role],
      ["Journal", record.journal], ["Field", field], ["Current value", shortCurrent],
      ["Proposed value", proposed], ["Evidence", evidence],
      ["Additional context", "Submitted from the Open Science Explorer (" + role + " view). Journal filter: " + (journal === "All" ? "All journals" : journal) + ". This is a proposed correction for maintainer review."]
    ].map(([heading, value]) => "### " + heading + "\n\n" + (value || "_No response_")).join("\n\n");
  }

  function issueQueueUrl(journal) {
    const url = new URL("https://github.com/RRinTransportation/OTSM/issues");
    const journalQuery = journal && journal !== "All" ? " \"" + String(journal).replace(/["\\]/g, " ").trim() + "\"" : "";
    url.searchParams.set("q", "is:issue is:open \"[Correction]\"" + journalQuery);
    return url.href;
  }

  function validateCorrection(record, field, proposed, evidence) {
    if (!doiUrl(record.doi)) return "A valid paper DOI is required to record a correction.";
    if (!CORRECTION_FIELDS.has(field)) return "Choose a supported correction field.";
    if (!proposed.trim()) return "Describe the proposed corrected value.";
    if (proposed.length > 20000 || evidence.length > 8000) return "Please shorten the proposed value or evidence before continuing.";
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(proposed + evidence)) return "Remove control characters from the proposed value or evidence.";
    if (["title", "topic"].includes(field) && proposed.trim().length > 1000) return "Titles and topics must be at most 1,000 characters.";
    if (/^###\s+/m.test(proposed + "\n" + evidence)) return "Use plain text without level-three Markdown headings so the correction fields remain unambiguous.";
    if (["code_availability", "data_availability"].includes(field) && !["true", "false"].includes(proposed.trim())) return "Enter true or false for availability.";
    const validSource = value => value.length <= 2048 && !/[\s<>"'\\]/.test(value) && safeUrl(value);
    if (["code_links", "data_links"].includes(field) && proposed.trim() !== "[]") {
      const links = proposed.trim().split(/\r?\n/).map(value => value.trim()).filter(Boolean);
      if (!links.length || links.some(value => !validSource(value))) return "Enter one complete HTTP or HTTPS link per line, or [] to remove all links.";
      if (links.length > 20 || new Set(links).size !== links.length) return "Enter up to 20 distinct resource links.";
    }
    const evidenceUrls = evidence.match(/https?:\/\/[^\s<>"']+/gi) || [];
    if (!evidenceUrls.some(value => validSource(value.replace(/[).,;\]}]+$/, "")))) return "Include at least one complete HTTP or HTTPS source link in the evidence.";
    return "";
  }

  // Pure functions are exported for the data/search regression checks.
  if (typeof module !== "undefined" && module.exports) module.exports = {safeUrl, safeLinks, normalizeDoi, buildIndex, filterRecords, isDiscoveryMode, featuredPapers, paperBounds, inViewport, zoomRange, currentValue, correctionBody, issueQueueUrl, validateCorrection};
  if (typeof document === "undefined") return;

  const $ = id => document.getElementById(id);
  const defaultMapInteraction = () => window.innerWidth > 900 && !window.matchMedia?.("(pointer: coarse)")?.matches;
  const state = {view: "code", presentation: "list", topic: "All", journal: "All", availability: "All", query: "", scope: "all", role: "reader", mapInteraction: defaultMapInteraction()};
  const roles = {
    reader: {hint: "Search papers"},
    author: {hint: "Find my paper"},
    editor: {hint: "Choose journal"}
  };
  let records = [];
  let byId = new Map();
  let matches = [];
  let matchingIds = new Set();
  let shown = PAGE_SIZE;
  let selectedPaper = null;
  let lastFocus = null;
  let searchTimer;
  let mapReady = false;
  let mapInitializing = false;
  let mapFailed = false;
  let mapBusy = false;
  let mapPending = false;
  let loading = false;
  let plotlyLoading;
  let viewport = null;
  let mapSelectedId = null;
  let mapShown = MAP_PAGE_SIZE;
  let mapFilterKey = "";
  let mapFitRevision = 0;
  let mapRenderingRevision = -1;
  let interactionTouched = false;
  let programmaticRelayout = 0;
  const mapPaperButtons = new Map();
  let lastRandom = null;
  const visitedRandom = new Set();
  const topicColors = new Map();
  const plot = $("plot");
  const dialog = $("paperDialog");
  const plotLayout = {
    autosize: true, margin: {l: 8, r: 8, t: 12, b: 8},
    paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff", showlegend: false,
    hovermode: "closest", dragmode: "pan", uirevision: "explorer-v2",
    font: {family: "Inter, system-ui, sans-serif", color: "#243749"},
    xaxis: {showgrid: false, zeroline: false, showticklabels: false, title: ""},
    yaxis: {showgrid: false, zeroline: false, showticklabels: false, title: ""}
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setText(id, value) {
    if ($(id)) $(id).textContent = value;
  }

  function externalLink(url, label, className) {
    const anchor = element("a", className, label);
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
  }

  function badge(label, available) {
    return element("span", "badge " + (available ? "badge--available" : "badge--unavailable"), label);
  }

  function addBadges(container, record, compact = false) {
    ["code", "data"].forEach(view => {
      const name = view === "code" ? "Code" : "Data";
      const available = record.available[view];
      const label = available ? name + " reported available" : "No " + view + " reported";
      const status = badge(compact ? name + (available ? " ✓" : " —") : label, available);
      status.setAttribute("aria-label", label);
      status.title = label;
      container.append(status);
    });
  }

  function showPaper(record, opener) {
    selectedPaper = record;
    lastFocus = opener || document.activeElement;
    setText("detailTitle", record.title);
    setText("detailMeta", [record.year, record.journal].filter(Boolean).join(" · "));
    $("detailBody").replaceChildren();
    const badges = element("div", "paper-card__badges");
    addBadges(badges, record);
    const facts = element("dl", "detail-facts");
    [["Topic", record.topic], ["Institution", record.institution], ["Keywords", record.keywords], ["Open access", record.openAccess ? "Reported as open access" : "Not reported as open access"], ["Funding", record.funding]].forEach(([label, value]) => {
      if (value) facts.append(element("dt", "", label), element("dd", "", value));
    });
    const abstractHeading = element("h3", "", "Abstract");
    const abstract = element("p", "detail-abstract", record.abstract || "No abstract is recorded for this paper.");
    $("detailBody").append(badges, facts, abstractHeading, abstract);
    $("detailLinks").replaceChildren();
    const paperUrl = doiUrl(record.doi);
    if (paperUrl) $("detailLinks").append(externalLink(paperUrl, "Open paper ↗", "text-link"));
    ["code", "data"].forEach(view => {
      const group = element("section", "resource-group");
      group.append(element("h3", "", view === "code" ? "Code links" : "Data links"));
      if (!record.links[view].length) group.append(element("p", "", "No valid link is recorded."));
      else {
        const list = element("ul", "resource-links");
        record.links[view].forEach(url => {
          const item = element("li");
          item.append(externalLink(url, url, "text-link"));
          list.append(item);
        });
        group.append(list);
      }
      $("detailLinks").append(group);
    });
    $("correctionForm").hidden = true;
    $("correctionForm").reset();
    $("correctionToggle").setAttribute("aria-expanded", "false");
    $("correctionField").value = state.view + "_links";
    setText("correctionStatus", "");
    $("correctionDraftPanel")?.remove();
    updateCorrectionHelp();
    if (!dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else { dialog.hidden = false; dialog.setAttribute("open", ""); }
    }
    $("closeDialog").focus();
  }

  function closePaper() {
    if (typeof dialog.close === "function") dialog.close();
    else { dialog.hidden = true; dialog.removeAttribute("open"); }
    lastFocus?.focus();
  }

  function renderList() {
    const discovery = isDiscoveryMode(state);
    const listRecords = discovery ? featuredPapers(matches) : matches;
    const fragment = document.createDocumentFragment();
    listRecords.slice(0, shown).forEach(record => {
      const item = element("li", "paper-card");
      const info = element("div", "paper-card__info");
      const heading = element("h3", "paper-card__title", record.title);
      const meta = element("p", "paper-card__meta", [record.journal, record.year].filter(Boolean).join(" · "));
      info.append(heading, meta);
      const badges = element("div", "paper-card__badges");
      addBadges(badges, record, true);
      const actions = element("div", "paper-card__actions");
      const details = element("button", "text-link", "Details");
      details.type = "button";
      details.setAttribute("aria-label", "Details and corrections for " + record.title);
      details.addEventListener("click", () => showPaper(record, details));
      actions.append(details);
      item.append(info, badges, actions);
      fragment.append(item);
    });
    $("resultList").replaceChildren(fragment);
    $("loadMore").hidden = discovery || shown >= listRecords.length;
    $("emptyState").hidden = listRecords.length > 0;
    setText("listContext", discovery ? listRecords.length.toLocaleString() + " papers with code and data" : state.query.trim() ? "Search results" : "Filtered papers");
    setText("resultSummary", discovery ? listRecords.length.toLocaleString() + " examples with code and data" : matches.length ? Math.min(shown, matches.length).toLocaleString() + " of " + matches.length.toLocaleString() + " matching papers" : "No matching papers");
  }

  function updateMapControls() {
    const usable = mapReady && !mapFailed && !mapInitializing && !mapBusy && matches.some(record => Number.isFinite(record.x) && Number.isFinite(record.y));
    ["mapZoomIn", "mapZoomOut", "mapReset"].forEach(id => { $(id).disabled = !usable; });
    $("mapInteraction").disabled = !mapReady || mapFailed;
    $("mapInteraction").setAttribute("aria-pressed", String(state.mapInteraction));
    setText("mapInteraction", state.mapInteraction ? "Pause map gestures" : "Enable map gestures");
    $("mapCanvas").classList.toggle("is-passive", !state.mapInteraction);
    $("mapAvailableOnly").setAttribute("aria-pressed", String(state.availability === "available"));
    setText("mapAvailableOnly", "Available " + state.view + " only");
  }

  function renderMapSelection() {
    const record = mapSelectedId && matchingIds.has(mapSelectedId) ? byId.get(mapSelectedId) : null;
    $("mapSelection").hidden = !record;
    if (record) {
      setText("mapSelectedTitle", record.title);
      setText("mapSelectedMeta", [record.journal, record.year].filter(Boolean).join(" · "));
      $("mapSelectedStatus").replaceChildren();
      addBadges($("mapSelectedStatus"), record, true);
    }
    mapPaperButtons.forEach((button, id) => {
      const selected = id === mapSelectedId;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function renderMapBrowser() {
    const focusedId = document.activeElement?.getAttribute("data-map-paper");
    const discovery = isDiscoveryMode(state);
    const inView = matches.filter(record => inViewport(record, viewport));
    const visible = discovery ? featuredPapers(inView) : inView.sort(newestFirst);
    const fragment = document.createDocumentFragment();
    mapPaperButtons.clear();
    visible.slice(0, mapShown).forEach(record => {
      const row = element("li", "map-paper-row");
      const button = element("button", "map-paper-button");
      button.type = "button";
      button.setAttribute("data-map-paper", record.id);
      button.setAttribute("aria-label", "Select " + record.title);
      button.append(element("span", "map-paper-title", record.title), element("span", "map-paper-meta", [record.journal, record.year].filter(Boolean).join(" · ")));
      const badges = element("span", "paper-card__badges");
      addBadges(badges, record, true);
      button.append(badges);
      button.addEventListener("click", () => selectMapPaper(record, true));
      mapPaperButtons.set(record.id, button);
      row.append(button);
      fragment.append(row);
    });
    if (!visible.length) fragment.append(element("li", "map-paper-empty", discovery ? "No examples with code and data in this area. Zoom out or search all papers." : matches.length ? "No papers in this area. Zoom out or fit results." : "No matching papers. Try fewer filters."));
    $("mapPaperList").replaceChildren(fragment);
    setText("mapPaperCount", visible.length.toLocaleString());
    $("mapLoadMore").hidden = discovery || mapShown >= visible.length;
    setText("mapBrowserHeading", discovery ? "Code + data examples" : state.query.trim() ? "Search results in view" : "Papers in view");
    setText("mapBrowseStatus", discovery ? visible.length.toLocaleString() + " examples with code and data in view." : visible.length.toLocaleString() + " papers in view. Showing " + Math.min(mapShown, visible.length).toLocaleString() + ".");
    renderMapSelection();
    if (focusedId) mapPaperButtons.get(focusedId)?.focus({preventScroll: true});
  }

  function selectMapPaper(record, fromList = false) {
    if (!matchingIds.has(record.id)) return;
    mapSelectedId = record.id;
    renderMapSelection();
    setText("mapBrowseStatus", "Selected: " + record.title);
    updateMap();
    if (fromList && window.innerWidth <= 720) {
      const reducedMotion = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      $("mapSelection").scrollIntoView?.({behavior: reducedMotion ? "auto" : "smooth", block: "nearest"});
    }
  }

  function fitMapResults() {
    viewport = paperBounds(matches);
    mapFitRevision++;
    mapShown = MAP_PAGE_SIZE;
    renderMapBrowser();
  }

  function mapLayout() {
    const range = viewport || {x: [-1, 1], y: [-1, 1]};
    return {...plotLayout, uirevision: "explorer-map-" + mapFitRevision,
      xaxis: {...plotLayout.xaxis, range: [...range.x], autorange: false},
      yaxis: {...plotLayout.yaxis, range: [...range.y], autorange: false}};
  }

  async function applyViewport(next) {
    if (!next || !mapReady || mapFailed || state.presentation !== "map") return;
    viewport = next;
    mapShown = MAP_PAGE_SIZE;
    renderMapBrowser();
    programmaticRelayout++;
    try {
      await window.Plotly.relayout(plot, {"xaxis.range": [...next.x], "yaxis.range": [...next.y], "xaxis.autorange": false, "yaxis.autorange": false});
    } catch (_) {
      mapStatus("Map controls unavailable. You can still select papers from the list.", true);
    } finally {
      programmaticRelayout--;
    }
  }

  function handleMapRelayout(update) {
    if (state.presentation !== "map" || mapInitializing || programmaticRelayout || (mapBusy && mapRenderingRevision !== mapFitRevision)) return;
    if (update["xaxis.autorange"] === true || update["yaxis.autorange"] === true) {
      fitMapResults();
      applyViewport(viewport);
      return;
    }
    const previous = viewport || paperBounds(matches);
    if (!previous) return;
    let changed = false;
    const next = {x: [...previous.x], y: [...previous.y]};
    ["x", "y"].forEach(axis => {
      const whole = update[axis + "axis.range"];
      if (Array.isArray(whole) && whole.length === 2 && whole.every(Number.isFinite)) { next[axis] = [...whole]; changed = true; }
      [0, 1].forEach(index => {
        const value = update[axis + "axis.range[" + index + "]"];
        if (Number.isFinite(value)) { next[axis][index] = value; changed = true; }
      });
    });
    if (!changed) return;
    viewport = next;
    mapShown = MAP_PAGE_SIZE;
    renderMapBrowser();
  }

  function mapTraces() {
    const grouped = new Map();
    const compact = window.innerWidth < 640;
    matches.forEach(record => {
      if (record.x === null || record.y === null) return;
      const available = record.available[state.view];
      const key = record.topic + "/" + available;
      if (!grouped.has(key)) grouped.set(key, {
        type: "scattergl", mode: "markers", name: record.topic, showlegend: false,
        x: [], y: [], customdata: [], text: [], hovertemplate: "%{text}<extra></extra>",
        marker: {symbol: available ? "star" : "circle-open", size: available ? (compact ? 8 : 10) : (compact ? 4 : 5.5), color: topicColors.get(record.topic) || COLORS[0], opacity: available ? 0.95 : 0.65, line: {width: 1}},
        meta: {topic: record.topic, view: state.view, flag: available}
      });
      const trace = grouped.get(key);
      trace.x.push(record.x); trace.y.push(record.y); trace.customdata.push(record.id);
      trace.text.push(escapePlotText(record.title) + "<br>" + escapePlotText([record.year, record.topic].filter(Boolean).join(" · ")) + "<br>" + (available ? "Reported " + state.view + " available" : "No " + state.view + " reported"));
    });
    const result = [...grouped.values()];
    const selected = mapSelectedId && matchingIds.has(mapSelectedId) ? byId.get(mapSelectedId) : null;
    if (selected && Number.isFinite(selected.x) && Number.isFinite(selected.y)) result.push({
      type: "scattergl", mode: "markers", name: "Selected paper", showlegend: false,
      x: [selected.x], y: [selected.y], customdata: [selected.id], hoverinfo: "skip",
      marker: {symbol: "circle-open", size: 23, color: "#173d51", line: {width: 3}}, meta: {selection: true}
    });
    return result;
  }

  function mapStatus(message, error = false, hidden = false) {
    setText("plotStatus", message);
    $("plotStatus").classList.toggle("is-error", error);
    $("plotStatus").hidden = hidden;
  }

  async function updateMap() {
    mapPending = true;
    if (state.presentation !== "map" || !mapReady || mapBusy || mapFailed) return;
    mapBusy = true;
    updateMapControls();
    try {
      while (mapPending && state.presentation === "map") {
        mapPending = false;
        mapRenderingRevision = mapFitRevision;
        await window.Plotly.react(plot, mapTraces(), mapLayout(), plotConfig);
      }
      mapStatus(matches.length ? "Drag to pan. Select a point for details." : "No matching map points. Try fewer filters.", false, matches.length > 0);
    } catch (_) {
      mapFailed = true;
      mapStatus("Map unavailable. Switch to List to browse papers.", true);
    } finally {
      mapBusy = false;
      updateMapControls();
    }
  }

  const plotConfig = {responsive: true, displaylogo: false, scrollZoom: false, displayModeBar: false, doubleClick: false};

  function loadPlotly() {
    if (window.Plotly && typeof window.Plotly.newPlot === "function") return Promise.resolve();
    if (plotlyLoading) return plotlyLoading;
    plotlyLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = PLOTLY_URL;
      script.async = true;
      const timeout = setTimeout(() => { script.remove(); reject(new Error("Map library timed out")); }, 20000);
      script.onload = () => {
        clearTimeout(timeout);
        if (window.Plotly && typeof window.Plotly.newPlot === "function") resolve();
        else reject(new Error("Map library unavailable"));
      };
      script.onerror = () => { clearTimeout(timeout); script.remove(); reject(new Error("Map library failed to load")); };
      document.head.append(script);
    });
    plotlyLoading.catch(() => { plotlyLoading = null; });
    return plotlyLoading;
  }

  async function initializeMap() {
    if (state.presentation !== "map" || !records.length || mapInitializing || mapReady) return;
    mapInitializing = true;
    mapFailed = false;
    mapStatus("Loading map…");
    let timeout;
    try {
      await loadPlotly();
      // A reader may switch back to the list while the map library downloads.
      if (state.presentation !== "map") return;
      mapStatus("Drawing map…");
      await Promise.race([
        window.Plotly.newPlot(plot, mapTraces(), mapLayout(), plotConfig),
        new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("Map timed out")), 20000); })
      ]);
      mapReady = true;
      mapFailed = false;
      plot.on("plotly_click", event => {
        const record = byId.get(event?.points?.[0]?.customdata);
        if (record) selectMapPaper(record);
      });
      plot.on("plotly_relayout", handleMapRelayout);
      updateMap();
      resize();
    } catch (_) {
      mapFailed = true;
      mapStatus("Map unavailable. Switch to List to browse papers.", true);
    } finally {
      clearTimeout(timeout);
      mapInitializing = false;
      updateMapControls();
    }
  }

  function setPresentation(presentation) {
    const enteringMap = presentation === "map" && state.presentation !== "map";
    state.presentation = presentation;
    $("resultsPanel").hidden = presentation !== "list";
    $("mapPanel").hidden = presentation !== "map";
    ["list", "map"].forEach(value => {
      const button = $(value === "list" ? "showList" : "showMap");
      button.setAttribute("aria-pressed", String(value === presentation));
      button.classList.toggle("active", value === presentation);
    });
    if (presentation === "map" && records.length) {
      if (enteringMap) fitMapResults();
      if (mapReady && !mapFailed) { updateMap(); resize(); }
      else { mapReady = false; initializeMap(); }
    }
  }

  function refresh({keepPage = false} = {}) {
    if (!records.length) return;
    state.topic = $("topicSelect").value;
    $("mapTopicSelect").value = state.topic;
    state.journal = $("journalSelect").value;
    state.availability = $("availabilitySelect").value;
    state.query = $("searchInput").value;
    state.scope = $("searchScope").value;
    if (!keepPage) shown = PAGE_SIZE;
    matches = filterRecords(records, state);
    matchingIds = new Set(matches.map(record => record.id));
    if (!matchingIds.has(mapSelectedId)) mapSelectedId = null;
    const nextMapKey = JSON.stringify([state.view, state.topic, state.journal, state.availability, state.query.trim(), state.scope]);
    if (nextMapKey !== mapFilterKey) { mapFilterKey = nextMapKey; fitMapResults(); }
    else renderMapSelection();
    updateMapControls();
    const available = matches.filter(record => record.available[state.view]).length;
    const discovery = isDiscoveryMode(state);
    const exampleCount = discovery ? featuredPapers(matches).length : 0;
    setText("resultCount", (discovery ? exampleCount : matches.length).toLocaleString());
    setText("resultCountLabel", discovery ? "examples" : "papers");
    setText("availableCount", (discovery ? exampleCount : available).toLocaleString());
    $("availableCount").setAttribute("aria-label", discovery ? exampleCount + " examples report code and data with recorded links" : available.toLocaleString() + " matching papers report available " + state.view);
    setText("availabilityCaption", discovery ? "with code + data" : "with " + state.view);
    setText("availabilityRate", matches.length ? Math.round(100 * available / matches.length) + "%" : "—");
    const rate = matches.length ? Math.round(100 * available / matches.length) + "%" : "0%";
    setText("journalSummary", available.toLocaleString() + " / " + matches.length.toLocaleString() + " matching papers report " + state.view + " (" + rate + ")");
    updateEditorQueue();
    const activeCount = Number(state.topic !== "All") + Number(state.journal !== "All") + Number(state.availability !== "All") + Number(Boolean(state.query.trim()));
    setText("activeFilterCount", activeCount ? String(activeCount) : "");
    $("randomPaper").disabled = available === 0;
    $("randomPaper").title = available ? "Open a matching paper with reported " + state.view : "No matching paper reports available " + state.view;
    $("resetFilters").disabled = activeCount === 0 && state.scope === "all";
    ["code", "data"].forEach(view => {
      const button = $(view === "code" ? "viewCode" : "viewData");
      button.setAttribute("aria-pressed", String(view === state.view));
      button.classList.toggle("active", view === state.view);
    });
    renderList();
    updateMap();
  }

  function setRole(role) {
    state.role = role;
    ["reader", "author", "editor"].forEach(value => {
      const button = $("role" + value[0].toUpperCase() + value.slice(1));
      if (button) {
        button.setAttribute("aria-pressed", String(role === value));
        button.classList.toggle("active", role === value);
      }
    });
    setText("roleHint", roles[role].hint);
    if ($("roleHint")) $("roleHint").hidden = role === "reader";
    $("journalSummary").hidden = role !== "editor";
    updateEditorQueue();
  }

  function updateEditorQueue() {
    const link = $("editorCorrections");
    if (!link) return;
    link.hidden = state.role !== "editor";
    link.textContent = "Journal corrections ↗";
    link.href = issueQueueUrl(state.journal);
    link.setAttribute("aria-label", state.journal === "All" ? "Review open correction issues across all journals on GitHub" : "Review open correction issues mentioning " + state.journal + " on GitHub");
  }

  function updateCorrectionHelp() {
    const field = $("correctionField").value;
    const guidance = field.endsWith("_availability") ? "Use true if the resource is available, or false if it is unavailable." : field.endsWith("_links") ? "Enter one complete HTTP or HTTPS URL per line. Use [] to remove all recorded links." : "Describe the corrected value. Add a source link in the evidence field.";
    setText("correctionHelp", guidance);
    $("correctionValue").placeholder = field.endsWith("_availability") ? "true or false" : field.endsWith("_links") ? "https://github.com/…" : "Proposed corrected value";
  }

  function openCorrection(event) {
    event.preventDefault();
    if (!selectedPaper) return;
    const field = $("correctionField").value;
    const proposed = $("correctionValue").value.trim();
    const evidence = $("correctionEvidence").value.trim();
    const error = validateCorrection(selectedPaper, field, proposed, evidence);
    setText("correctionStatus", error);
    if (error) return;
    const body = correctionBody(selectedPaper, field, proposed, evidence, state.role, state.journal);
    const url = new URL(ISSUE_BASE);
    url.searchParams.set("template", "correction.md");
    url.searchParams.set("title", "[Correction] " + selectedPaper.title.slice(0, 160));
    url.searchParams.set("body", body);
    if (url.href.length > 14000) {
      // Long abstracts and non-Latin text can exceed URL limits. Keep the full
      // proposal visible and copyable rather than silently truncating evidence.
      $("correctionDraftPanel")?.remove();
      const panel = element("div", "correction-draft");
      panel.id = "correctionDraftPanel";
      const label = element("label", "", "Full correction draft");
      label.htmlFor = "correctionDraft";
      const draft = element("textarea");
      draft.id = "correctionDraft";
      draft.value = body;
      draft.readOnly = true;
      draft.rows = 10;
      url.searchParams.delete("body");
      panel.append(label, draft, externalLink(url.href, "Open GitHub and paste this draft ↗", "text-link"));
      $("correctionForm").append(panel);
      draft.focus();
      draft.select();
      setText("correctionStatus", "This draft is too long to prefill safely. Copy the complete draft below, open GitHub, and paste it into the issue body. Nothing has been submitted yet.");
      return;
    }
    window.open(url.href, "_blank", "noopener,noreferrer");
    setText("correctionStatus", "Your draft is ready on GitHub. Sign in and submit the issue there; maintainers review it before the database changes.");
  }

  function populateSelect(id, values, allLabel) {
    const select = $(id);
    const previous = select.value || "All";
    select.replaceChildren();
    const all = element("option", "", allLabel);
    all.value = "All";
    select.append(all);
    values.forEach(value => {
      const option = element("option", "", value);
      option.value = value;
      select.append(option);
    });
    select.value = values.includes(previous) ? previous : "All";
  }

  function disableControls(disabled) {
    ["viewCode", "viewData", "journalSelect", "topicSelect", "mapTopicSelect", "mapAvailableOnly", "availabilitySelect", "searchInput", "searchScope", "randomPaper", "resetFilters", "loadMore"].forEach(id => {
      $(id).disabled = disabled;
    });
  }

  async function loadData() {
    if (loading) return;
    loading = true;
    disableControls(true);
    $("resultList").setAttribute("aria-busy", "true");
    $("retryLoad") && ($("retryLoad").hidden = true);
    $("emptyState").hidden = true;
    $("loadMore").hidden = true;
    $("randomPaper").disabled = true;
    mapStatus("Loading the research collection…");
    setText("resultSummary", "Loading papers…");
    setText("loadingNotice", "Loading papers…");
    if ($("loadingNotice")) $("loadingNotice").hidden = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch("./assets/explorer/papers.json", {signal: controller.signal, headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("Collection request failed");
      const payload = await response.json();
      if (payload.schema_version !== 1 || !Array.isArray(payload.papers) || !payload.papers.length) throw new Error("Invalid collection format");
      records = buildIndex(payload.papers);
      if (!records.length) throw new Error("No usable records");
      byId = new Map(records.map(record => [record.id, record]));
      const topics = [...new Set(records.map(record => record.topic))].sort((a, b) => a.localeCompare(b));
      topics.forEach((topic, index) => topicColors.set(topic, COLORS[index % COLORS.length]));
      populateSelect("topicSelect", topics, "All topics");
      populateSelect("mapTopicSelect", topics, "All topics");
      populateSelect("journalSelect", [...new Set(records.map(record => record.journal))].sort((a, b) => a.localeCompare(b)), "All journals");
      setText("totalCount", records.length.toLocaleString());
      if ($("loadingNotice")) $("loadingNotice").hidden = true;
      disableControls(false);
      refresh();
      if (state.presentation === "map") initializeMap();
    } catch (_) {
      mapStatus("The paper collection could not be loaded. Check your connection and try again.", true);
      setText("resultSummary", "Papers are temporarily unavailable.");
      setText("loadingNotice", "Couldn't load papers. Please try again.");
      if ($("loadingNotice")) $("loadingNotice").hidden = false;
      if ($("retryLoad")) $("retryLoad").hidden = false;
    } finally {
      loading = false;
      clearTimeout(timeout);
      $("resultList").setAttribute("aria-busy", "false");
    }
  }

  ["topicSelect", "journalSelect", "availabilitySelect", "searchScope"].forEach(id => $(id).addEventListener("change", () => { clearTimeout(searchTimer); refresh(); }));
  $("mapTopicSelect").addEventListener("change", () => { $("topicSelect").value = $("mapTopicSelect").value; clearTimeout(searchTimer); refresh(); });
  $("mapAvailableOnly").addEventListener("click", () => { $("availabilitySelect").value = state.availability === "available" ? "All" : "available"; clearTimeout(searchTimer); refresh(); });
  $("mapZoomIn").addEventListener("click", () => {
    if (viewport) applyViewport({x: zoomRange(viewport.x, 0.65), y: zoomRange(viewport.y, 0.65)});
  });
  $("mapZoomOut").addEventListener("click", () => {
    if (viewport) applyViewport({x: zoomRange(viewport.x, 1.55), y: zoomRange(viewport.y, 1.55)});
  });
  $("mapReset").addEventListener("click", () => { fitMapResults(); applyViewport(viewport); });
  $("mapInteraction").addEventListener("click", () => { interactionTouched = true; state.mapInteraction = !state.mapInteraction; updateMapControls(); });
  $("mapLoadMore").addEventListener("click", () => {
    const previous = mapShown;
    mapShown += MAP_PAGE_SIZE;
    renderMapBrowser();
    $("mapPaperList").children[previous]?.querySelector("button")?.focus({preventScroll: true});
  });
  $("mapOpenDetails").addEventListener("click", () => {
    const record = mapSelectedId && byId.get(mapSelectedId);
    if (record && matchingIds.has(record.id)) showPaper(record, $("mapOpenDetails"));
  });
  $("mapClearSelection").addEventListener("click", () => {
    const previous = mapSelectedId;
    mapSelectedId = null;
    renderMapSelection();
    updateMap();
    (mapPaperButtons.get(previous) || $("mapTopicSelect")).focus({preventScroll: true});
  });
  $("mapLocateSelection")?.addEventListener("click", () => {
    const record = mapSelectedId && byId.get(mapSelectedId);
    if (!record || !viewport) return;
    const width = Math.max(Math.abs(viewport.x[1] - viewport.x[0]), 0.01);
    const height = Math.max(Math.abs(viewport.y[1] - viewport.y[0]), 0.01);
    applyViewport({x: [record.x - width / 2, record.x + width / 2], y: [record.y - height / 2, record.y + height / 2]});
  });
  $("showList").addEventListener("click", () => setPresentation("list"));
  $("showMap").addEventListener("click", () => setPresentation("map"));
  $("searchInput").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => refresh(), 160);
  });
  ["code", "data"].forEach(view => $(view === "code" ? "viewCode" : "viewData").addEventListener("click", () => { state.view = view; clearTimeout(searchTimer); refresh(); }));
  ["reader", "author", "editor"].forEach(role => $("role" + role[0].toUpperCase() + role.slice(1))?.addEventListener("click", () => setRole(role)));
  $("roleHint")?.addEventListener("click", () => {
    $("filterPanel").classList.add("is-open");
    $("filterToggle").setAttribute("aria-expanded", "true");
    if (state.role === "editor") $("journalSelect").focus();
    else {
      if (state.role === "author") { $("searchScope").value = "title"; refresh(); }
      $("searchInput").focus();
    }
  });
  $("resetFilters").addEventListener("click", () => {
    clearTimeout(searchTimer);
    ["topicSelect", "journalSelect", "availabilitySelect"].forEach(id => { $(id).value = "All"; });
    $("searchInput").value = "";
    $("searchScope").value = "all";
    refresh();
  });
  $("loadMore").addEventListener("click", () => {
    const previousCount = Math.min(shown, matches.length);
    shown += PAGE_SIZE;
    renderList();
    const next = $("resultList").children[previousCount]?.querySelector("button");
    next?.focus({preventScroll: true});
  });
  $("randomPaper").addEventListener("click", () => {
    clearTimeout(searchTimer);
    refresh({keepPage: true});
    const candidates = matches.filter(record => record.available[state.view]);
    let pool = candidates.filter(record => !visitedRandom.has(record.id));
    if (!pool.length) {
      visitedRandom.clear();
      pool = candidates.filter(record => candidates.length === 1 || record.id !== lastRandom);
    }
    if (!pool.length) return;
    const record = pool[Math.floor(Math.random() * pool.length)];
    visitedRandom.add(record.id);
    lastRandom = record.id;
    showPaper(record, $("randomPaper"));
  });
  $("filterToggle").addEventListener("click", () => {
    const expanded = $("filterToggle").getAttribute("aria-expanded") !== "true";
    $("filterToggle").setAttribute("aria-expanded", String(expanded));
    $("filterPanel").classList.toggle("is-open", expanded);
  });
  $("closeDialog").addEventListener("click", closePaper);
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closePaper();
  });
  dialog.addEventListener("close", () => { lastFocus?.focus(); });
  $("correctionToggle").addEventListener("click", () => {
    const expanded = $("correctionToggle").getAttribute("aria-expanded") !== "true";
    $("correctionToggle").setAttribute("aria-expanded", String(expanded));
    $("correctionForm").hidden = !expanded;
    if (expanded) $("correctionField").focus();
  });
  $("correctionField").addEventListener("change", updateCorrectionHelp);
  $("correctionForm").addEventListener("submit", openCorrection);
  $("retryLoad")?.addEventListener("click", loadData);

  let resizeTimer;
  const resize = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (!interactionTouched) { state.mapInteraction = defaultMapInteraction(); updateMapControls(); }
      if (state.presentation === "map" && mapReady && !mapFailed) {
        try { window.Plotly.Plots.resize(plot); } catch (_) { /* The list remains usable if a map resize fails. */ }
      }
    }, 100);
  };
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(plot);
  else window.addEventListener("resize", resize);
  setRole("reader");
  setPresentation("list");
  updateMapControls();
  loadData();
})();
