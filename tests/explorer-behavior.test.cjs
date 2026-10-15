"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {
  buildIndex, filterRecords, isDiscoveryMode, featuredPapers, paperBounds, inViewport, zoomRange, safeUrl, safeLinks, normalizeDoi,
  currentValue, correctionBody, issueQueueUrl, validateCorrection
} = require("../assets/explorer/explorer.js");

const defaults = {view: "code", topic: "All", journal: "All", availability: "All", query: "", scope: "all"};
const source = [
  {doi: "https://doi.org/10.1234/ABC", title: "Cycling travel planning", abstract: "Bus service in cities", year: 2024, journal: "Journal A", topic: "Mobility", code_available: true, data_available: false, code_links: ["javascript:alert(1)", "https://example.org/repo"], data_links: [], x: 1, y: 2},
  {doi: "10.1234/def", title: "Bus service network", abstract: "Cycling travel and cities", year: 2023, journal: "Journal B", topic: "Networks", code_available: false, data_available: true, code_links: [], data_links: ["https://data.example.org"], x: 3, y: 4}
];
const papers = buildIndex(source);
const featuredRows = Array.from({length: 12}, (_, index) => ({...source[0], doi: "10.1234/example-" + index,
  title: "Example paper " + String(index).padStart(2, "0"), abstract: "Full example abstract " + index, year: 2030 - index,
  code_available: true, data_available: true, code_links: ["https://example.org/code/" + index], data_links: ["https://example.org/data/" + index]}));

test("title search includes title matches and excludes abstract-only matches", () => {
  const query = {...defaults, query: "cycling travel"};
  assert.deepEqual(filterRecords(papers, {...query, scope: "title"}).map(paper => paper.doi), ["10.1234/abc"]);
  assert.deepEqual(filterRecords(papers, {...query, scope: "abstract"}).map(paper => paper.doi), ["10.1234/def"]);
  assert.equal(filterRecords(papers, query).length, 2);
  assert.equal(filterRecords(papers, {...defaults, query: "PLANNING cities"}).length, 1, "all words may match across the selected title and abstract");
  assert.equal(filterRecords(papers, {...defaults, query: "zzzyyxxx"}).length, 0, "nonmatches are removed from the returned list/map input");
});

test("search is case-insensitive, handles whitespace, and matches accented titles", () => {
  const records = buildIndex([{...source[0], title: "Mobilité à vélo"}]);
  assert.equal(filterRecords(records, {...defaults, query: "  MOBILITE   VELO  ", scope: "title"}).length, 1);
  assert.equal(filterRecords(records, {...defaults, query: "   "}).length, 1);
});

test("view, availability, topic, journal, and search combine in one filter", () => {
  assert.equal(filterRecords(papers, {...defaults, journal: "Journal B", view: "data", availability: "available"}).length, 1);
  assert.equal(filterRecords(papers, {...defaults, journal: "Journal B", view: "code", availability: "available"}).length, 0);
  assert.equal(filterRecords(papers, {...defaults, journal: "Journal A", topic: "Networks"}).length, 0);
  assert.equal(filterRecords(papers, {...defaults, journal: "Journal B", topic: "Networks", view: "data", availability: "available", query: "cycling"}).length, 1);
  assert.equal(filterRecords(papers, {...defaults, view: "data", availability: "unavailable"})[0].doi, "10.1234/abc");
});

test("discovery mode ends only for a nonblank query or an active collection filter", () => {
  assert.equal(isDiscoveryMode(defaults), true);
  assert.equal(isDiscoveryMode({...defaults, query: " \t ", scope: "title", view: "data"}), true);
  for (const changed of [{query: "bus"}, {topic: "Networks"}, {journal: "Journal A"}, {availability: "available"}, {availability: "unavailable"}]) {
    assert.equal(isDiscoveryMode({...defaults, ...changed}), false);
  }
});

test("featured papers require both reported resources with safe links and have a deterministic limit", () => {
  const records = buildIndex([...featuredRows, ...source, {...source[0], doi: "10.1234/unsafe", data_available: true, data_links: ["javascript:alert(1)"]}]);
  const original = records.map(record => record.id);
  const featured = featuredPapers(records);
  assert.equal(featured.length, 10);
  assert.deepEqual(featured.map(record => record.doi), featuredRows.slice(0, 10).map(record => record.doi));
  assert.ok(featured.every(record => record.available.code && record.available.data && record.links.code.length && record.links.data.length));
  assert.deepEqual(records.map(record => record.id), original, "choosing examples must not reorder the full collection");
  assert.deepEqual(featuredPapers(papers), [], "a single reported resource does not qualify");
  const tied = [{...featured[0], year: "2040", title: "Same title", id: "z"}, {...featured[0], year: "2040", title: "Same title", id: "a"}];
  assert.deepEqual(featuredPapers(tied).map(record => record.id), ["a", "z"]);
});

test("map bounds fit finite coordinates and remain usable for a single point", () => {
  const bounds = paperBounds([...papers, {x: null, y: 8}, {x: Infinity, y: 5}]);
  assert.deepEqual(bounds, {x: [0.5, 3.5], y: [1.5, 4.5]});
  assert.ok(papers.every(paper => inViewport(paper, bounds)));
  assert.deepEqual(paperBounds([{x: 5, y: -3}]), {x: [4.5, 5.5], y: [-3.5, -2.5]});
  assert.equal(paperBounds([]), null);
  assert.equal(inViewport({x: 3, y: 4}, {x: [3, 1], y: [4, 2]}), true, "viewport edges and reversed ranges are inclusive");
  assert.equal(inViewport({x: 3.1, y: 4}, {x: [1, 3], y: [2, 4]}), false);
  assert.equal(inViewport({x: null, y: 4}, null), false);
});

test("map zoom preserves the center and rejects unusable ranges", () => {
  assert.deepEqual(zoomRange([0, 10], 0.5), [2.5, 7.5]);
  assert.deepEqual(zoomRange([10, 0], 2), [15, -5]);
  assert.equal(zoomRange([0, Infinity], 1), null);
  assert.equal(zoomRange([0, 10], 0), null);
  const minimum = zoomRange([2, 2], 0.5);
  assert.ok(minimum[1] > minimum[0]);
});

test("DOI deduplication preserves available resources without mutating source records", () => {
  const duplicate = {...source[0], doi: "doi:10.1234/abc", data_available: true, data_links: ["https://example.org/dataset"]};
  const rows = [...source, duplicate];
  const original = JSON.stringify(rows);
  const records = buildIndex(rows);
  assert.equal(records.length, 2);
  assert.equal(JSON.stringify(rows), original);
  assert.equal(records[0].available.code, true);
  assert.equal(records[0].available.data, true);
  assert.deepEqual(records[0].links.code, ["https://example.org/repo"]);
  assert.deepEqual(records[0].links.data, ["https://example.org/dataset"]);
  assert.equal(normalizeDoi("https://dx.doi.org/10.1234/ABC"), "10.1234/abc");
});

test("resource links allow only absolute HTTP(S) URLs without credentials", () => {
  for (const url of ["javascript:alert(1)", "data:text/html,<script>", "file:///tmp/secret", "//example.org/repo", "<a href='https://example.org'>link</a>", "https://user:secret@example.org", "https://example.org:invalid/repo"]) {
    assert.equal(safeUrl(url), null, url);
  }
  assert.equal(safeUrl("http://example.org/repo"), "http://example.org/repo");
  assert.deepEqual(safeLinks(["https://example.org/repo", "javascript:alert(1)", "https://example.org/repo"]), ["https://example.org/repo"]);
});

test("correction proposals match the server's field, boolean, URL, and evidence rules", () => {
  const record = papers[0];
  const evidence = "Repository statement: https://example.org/evidence";
  assert.equal(validateCorrection(record, "code_availability", "false", evidence), "");
  assert.equal(validateCorrection(record, "data_links", "[]", evidence), "");
  assert.equal(validateCorrection(record, "code_links", "https://example.org/one\nhttps://example.org/two", evidence), "");
  assert.match(validateCorrection(record, "code_availability", "yes", evidence), /true or false/);
  assert.match(validateCorrection(record, "code_links", "javascript:alert(1)", evidence), /HTTP/);
  assert.match(validateCorrection(record, "code_links", "https://example.org/a b", evidence), /HTTP/);
  assert.match(validateCorrection(record, "code_links", "https://example.org/repo\nhttps://example.org/repo", evidence), /distinct/);
  assert.match(validateCorrection(record, "title", "a".repeat(1001), evidence), /1,000/);
  assert.match(validateCorrection(record, "title", "New title", "No source supplied"), /source link/);
  assert.match(validateCorrection(record, "unknown", "New value", evidence), /supported/);
  assert.match(validateCorrection(record, "abstract", "Text\n### Evidence\nInjected heading", evidence), /headings/);
  assert.match(validateCorrection({...record, doi: "not-a-doi"}, "title", "New title", evidence), /DOI/);
});

test("issue draft documents role and journal with the parser's exact headings", () => {
  for (const role of ["reader", "author", "editor"]) {
    const body = correctionBody(papers[0], "code_availability", "false", "Source: https://example.org", role, "Journal A");
    assert.deepEqual([...body.matchAll(/^### (.+)$/gm)].map(match => match[1]), ["DOI", "Paper title", "Role", "Journal", "Field", "Current value", "Proposed value", "Evidence", "Additional context"]);
    assert.ok(body.includes("### Role\n\n" + role));
    assert.ok(body.includes("### Journal\n\nJournal A"));
    assert.ok(body.includes("### DOI\n\n10.1234/abc"));
    assert.ok(body.includes("### Current value\n\ntrue"));
    assert.ok(body.includes("### Proposed value\n\nfalse"));
    assert.ok(body.includes("Journal filter: Journal A"));
  }
  assert.equal(currentValue(papers[0], "data_links"), "[]");
  assert.equal(currentValue(papers[0], "data_availability"), "false");
  const long = {...papers[0], abstract: "a".repeat(3000)};
  const body = correctionBody(long, "abstract", "Full proposed abstract", "https://example.org", "author", "All");
  assert.ok(body.includes("[Current value shortened for this report]"));
  assert.ok(body.includes("Full proposed abstract"), "only the informational old value may be shortened");
});

test("editor correction queues target open issues and follow the selected journal", () => {
  const all = new URL(issueQueueUrl("All"));
  const journal = new URL(issueQueueUrl("Transportation Research Part A: Policy and Practice"));
  assert.equal(journal.origin, "https://github.com");
  assert.equal(journal.pathname, "/RRinTransportation/OTSM/issues");
  assert.equal(all.searchParams.get("q"), 'is:issue is:open "[Correction]"');
  assert.equal(journal.searchParams.get("q"), 'is:issue is:open "[Correction]" "Transportation Research Part A: Policy and Practice"');
  assert.ok(!all.searchParams.get("q").includes("All"));
});

test("the deployable collection retains every unique paper and resource flag", () => {
  const payload = JSON.parse(fs.readFileSync(path.join(__dirname, "../assets/explorer/papers.json"), "utf8"));
  assert.equal(payload.schema_version, 1);
  const records = buildIndex(payload.papers);
  assert.equal(records.length, payload.papers.length);
  assert.equal(new Set(records.map(record => record.id)).size, payload.papers.length);
  assert.ok(records.length > 10000);
  assert.ok(records.every(record => record.x !== null && record.y !== null));
  for (const view of ["code", "data"]) {
    assert.equal(filterRecords(records, {...defaults, view, availability: "available"}).length, payload.papers.filter(record => record[view + "_available"]).length);
  }
  const title = filterRecords(records, {...defaults, query: "traffic", scope: "title"});
  const abstract = filterRecords(records, {...defaults, query: "traffic", scope: "abstract"});
  const combined = filterRecords(records, {...defaults, query: "traffic"});
  assert.ok(title.length > 0 && title.length < combined.length);
  assert.ok(abstract.length > 0 && abstract.length < combined.length);
  assert.equal(new Set([...title, ...abstract].map(record => record.id)).size, combined.length);
  const examples = featuredPapers(records);
  assert.equal(examples.length, 10);
  assert.ok(examples.every(record => record.available.code && record.available.data && record.links.code.length && record.links.data.length));
});

// Exercise the browser script against a small DOM surface. This checks actual
// event wiring and lazy rendering without adding a browser/test dependency.
function browserFixture({hasPlotly = true, fetchFails = false, width = 1200, coarsePointer = false, fixtureRows = source, query = ""} = {}) {
  const timers = new Set();
  const nodes = new Map();
  const document = {activeElement: null};
  class Node {
    constructor(tag) {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.textContent = "";
      this.value = "";
      this.className = "";
      this.hidden = false;
      this.disabled = false;
      this.attributes = new Map();
      this.listeners = new Map();
      const classes = new Set();
      this.classList = {
        add: value => classes.add(value),
        contains: value => classes.has(value),
        toggle(value, force) {
          const active = force === undefined ? !classes.has(value) : force;
          if (active) classes.add(value); else classes.delete(value);
          return active;
        }
      };
    }
    append(...items) {
      for (const item of items) {
        if (item.tagName === "#FRAGMENT") this.append(...item.children);
        else { item.parentNode = this; this.children.push(item); }
      }
    }
    replaceChildren(...items) { this.children = []; this.append(...items); }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    addEventListener(name, callback) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(callback);
    }
    dispatch(name, payload = {}) { (this.listeners.get(name) || []).forEach(callback => callback({target: this, preventDefault() {}, ...payload})); }
    on(name, callback) { this.addEventListener(name, callback); }
    focus() { document.activeElement = this; }
    scrollIntoView() { this.scrolledIntoView = true; }
    reset() {}
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); }
    showModal() { this.open = true; }
    close() { this.open = false; this.dispatch("close"); }
    querySelector(selector) { return descendants(this).find(node => node.tagName === selector.toUpperCase()) || null; }
  }
  const ids = ["plot", "plotStatus", "resultCount", "availableCount", "availabilityCaption", "resultList", "resultSummary", "loadingNotice", "loadMore", "emptyState", "viewCode", "viewData", "topicSelect", "availabilitySelect", "searchInput", "searchScope", "resetFilters", "randomPaper", "filterToggle", "filterPanel", "activeFilterCount", "paperDialog", "detailTitle", "detailMeta", "detailBody", "detailLinks", "correctionToggle", "closeDialog", "correctionForm", "correctionField", "correctionValue", "correctionEvidence", "correctionSubmit", "correctionStatus", "correctionHelp", "totalCount", "roleReader", "roleAuthor", "roleEditor", "roleHint", "journalSelect", "journalSummary", "editorCorrections", "retryLoad", "showList", "showMap", "resultsPanel", "mapPanel"];
  ids.push("mapTopicSelect", "mapZoomIn", "mapZoomOut", "mapReset", "mapInteraction", "mapCanvas", "mapSelection", "mapSelectedTitle", "mapSelectedMeta", "mapSelectedStatus", "mapOpenDetails", "mapClearSelection", "mapLocateSelection", "mapPaperList", "mapPaperCount", "mapLoadMore", "mapBrowseStatus", "mapAvailableOnly");
  ids.push("listContext", "resultCountLabel", "mapBrowserHeading");
  for (const id of ids) nodes.set(id, new Node("div"));
  for (const id of ["topicSelect", "mapTopicSelect", "journalSelect", "availabilitySelect"]) nodes.get(id).value = "All";
  nodes.get("searchScope").value = "all";
  nodes.get("searchInput").value = query;
  document.getElementById = id => nodes.get(id) || null;
  document.createElement = tag => new Node(tag);
  document.createDocumentFragment = () => new Node("#fragment");
  document.head = new Node("head");
  const calls = {newPlot: [], react: [], relayout: [], resize: 0};
  const plotly = {
    newPlot: async (_, data, layout, config) => { calls.newPlot.push({data, layout, config}); return nodes.get("plot"); },
    react: async (_, data, layout) => { calls.react.push({data, layout}); },
    relayout: async (_, update) => { calls.relayout.push(update); nodes.get("plot").dispatch("plotly_relayout", update); },
    Plots: {resize: () => { calls.resize++; }}
  };
  const windowListeners = new Map();
  const window = {innerWidth: width, matchMedia: query => ({matches: query === "(pointer: coarse)" && coarsePointer}), addEventListener(name, callback) { windowListeners.set(name, callback); }, dispatch: name => windowListeners.get(name)?.(), open() {}};
  if (hasPlotly) window.Plotly = plotly;
  const context = vm.createContext({
    document, window, URL, AbortController,
    fetch: async () => {
      if (fetchFails) throw new Error("Offline");
      return {ok: true, json: async () => ({schema_version: 1, papers: fixtureRows})};
    },
    setTimeout(callback, delay) {
      const timer = setTimeout(() => { timers.delete(timer); callback(); }, delay);
      timers.add(timer);
      return timer;
    },
    clearTimeout(timer) { timers.delete(timer); clearTimeout(timer); }
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../assets/explorer/explorer.js"), "utf8"), context);
  return {nodes, document, window, plotly, calls, cleanup: () => { timers.forEach(clearTimeout); }};
}

function descendants(node) {
  return node.children.flatMap(child => [child, ...descendants(child)]);
}

function nodeText(node) {
  return [node.textContent, ...node.children.map(nodeText)].join(" ");
}

const settle = async () => { await new Promise(setImmediate); await new Promise(setImmediate); };

test("catalog starts in List with compact rows and keeps abstracts in Details", async t => {
  const browser = browserFixture({fixtureRows: [...featuredRows, ...source]});
  t.after(browser.cleanup);
  assert.equal(browser.nodes.get("loadingNotice").hidden, false);
  assert.equal(browser.nodes.get("loadingNotice").textContent, "Loading papers…");
  await settle();
  const {nodes, calls, document} = browser;
  assert.equal(nodes.get("showList").getAttribute("aria-pressed"), "true");
  assert.equal(nodes.get("showMap").getAttribute("aria-pressed"), "false");
  assert.equal(nodes.get("resultsPanel").hidden, false);
  assert.equal(nodes.get("mapPanel").hidden, true);
  assert.equal(calls.newPlot.length, 0, "default catalog must not initialize a hidden plot");
  assert.equal(calls.react.length, 0);
  assert.equal(document.head.children.length, 0, "default catalog must not request the map library");
  assert.equal(nodes.get("loadingNotice").hidden, true);
  assert.equal(nodes.get("roleHint").hidden, true);
  const rows = nodes.get("resultList").children;
  assert.equal(rows.length, 10);
  assert.equal(nodes.get("loadMore").hidden, true);
  assert.equal(nodes.get("resultCount").textContent, "10");
  assert.equal(nodes.get("resultCountLabel").textContent, "examples");
  assert.equal(nodes.get("availabilityCaption").textContent, "with code + data");
  assert.ok(nodeText(rows[0]).includes(featuredRows[0].title));
  assert.ok(nodeText(rows[0]).includes("Journal A · 2030"));
  assert.ok(!nodeText(rows[0]).includes("Mobility"));
  assert.ok(!nodeText(rows[0]).includes(featuredRows[0].abstract));
  assert.ok(nodeText(rows[0]).includes("Code ✓"));
  assert.ok(nodeText(rows[0]).includes("Data ✓"));
  const buttons = descendants(rows[0]).filter(node => node.tagName === "BUTTON");
  assert.equal(buttons.length, 1, "one Details action per compact row");
  assert.equal(buttons[0].textContent, "Details");
  buttons[0].dispatch("click");
  assert.equal(nodes.get("paperDialog").open, true);
  assert.ok(nodeText(nodes.get("detailBody")).includes(featuredRows[0].abstract));
  assert.ok(nodeText(nodes.get("detailBody")).includes("Mobility"));
});

test("search uses the full collection with pages of ten and clearing restores the examples", async t => {
  const browser = browserFixture({fixtureRows: [...featuredRows, ...source]});
  t.after(browser.cleanup);
  await settle();
  const {nodes} = browser;
  nodes.get("searchInput").value = "example";
  nodes.get("searchScope").value = "title";
  nodes.get("searchScope").dispatch("change");
  assert.equal(nodes.get("resultCount").textContent, "12");
  assert.equal(nodes.get("resultList").children.length, 10);
  assert.equal(nodes.get("loadMore").hidden, false);
  assert.equal(nodes.get("listContext").textContent, "Search results");
  nodes.get("loadMore").dispatch("click");
  assert.equal(nodes.get("resultList").children.length, 12);
  nodes.get("searchInput").value = "network";
  nodes.get("searchScope").dispatch("change");
  assert.equal(nodes.get("resultList").children.length, 1);
  assert.ok(nodeText(nodes.get("resultList")).includes(source[1].title), "papers without both resources must remain searchable");
  assert.ok(nodeText(nodes.get("resultList")).includes("Code —"));
  nodes.get("searchInput").value = "zzzyyxxx";
  nodes.get("searchScope").dispatch("change");
  assert.equal(nodes.get("resultList").children.length, 0, "empty search results must not fall back to featured papers");
  nodes.get("searchInput").value = "   ";
  nodes.get("searchScope").dispatch("change");
  assert.equal(nodes.get("resultList").children.length, 10);
  assert.equal(nodes.get("loadMore").hidden, true);
  nodes.get("viewData").dispatch("click");
  assert.equal(nodes.get("resultCountLabel").textContent, "examples");
  assert.equal(nodes.get("availabilityCaption").textContent, "with code + data");
  nodes.get("journalSelect").value = "Journal B";
  nodes.get("journalSelect").dispatch("change");
  assert.equal(nodes.get("resultList").children.length, 1);
  assert.equal(nodes.get("listContext").textContent, "Filtered papers");
  nodes.get("resetFilters").dispatch("click");
  assert.equal(nodes.get("resultList").children.length, 10);
  assert.equal(nodes.get("loadMore").hidden, true);
});

test("default map shows ten eligible examples while keeping every filtered paper plotted", async t => {
  const browser = browserFixture({fixtureRows: [...featuredRows, ...source]});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(calls.newPlot[0].data.reduce((total, trace) => total + trace.x.length, 0), 14);
  assert.equal(nodes.get("mapPaperCount").textContent, "10");
  assert.equal(nodes.get("mapPaperList").children.length, 10);
  assert.equal(nodes.get("mapLoadMore").hidden, true);
  assert.equal(nodes.get("mapBrowserHeading").textContent, "Code + data examples");
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/def"}]});
  await settle();
  assert.equal(nodes.get("mapSelectedTitle").textContent, source[1].title, "background points outside the sample remain selectable");
  nodes.get("plot").dispatch("plotly_relayout", {"xaxis.range": [2.5, 3.5], "yaxis.range": [3.5, 4.5]});
  assert.equal(nodes.get("mapPaperCount").textContent, "0");
  assert.match(nodeText(nodes.get("mapPaperList")), /No examples with code and data/);
  nodes.get("searchInput").value = "network";
  nodes.get("searchScope").value = "title";
  nodes.get("searchScope").dispatch("change");
  await settle();
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  assert.equal(nodes.get("mapBrowserHeading").textContent, "Search results in view");
  assert.ok(nodeText(nodes.get("mapPaperList")).includes(source[1].title));
  nodes.get("resetFilters").dispatch("click");
  await settle();
  assert.equal(nodes.get("mapPaperCount").textContent, "10");
  assert.equal(nodes.get("mapLoadMore").hidden, true);
});

test("Map initializes only when shown and receives filters changed while hidden", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(calls.newPlot.length, 1);
  assert.equal(nodes.get("mapPanel").hidden, false);
  assert.equal(nodes.get("resultsPanel").hidden, true);
  assert.equal(nodes.get("showMap").getAttribute("aria-pressed"), "true");
  nodes.get("showList").dispatch("click");
  const previousRenders = calls.react.length;
  nodes.get("journalSelect").value = "Journal B";
  nodes.get("journalSelect").dispatch("change");
  await settle();
  assert.equal(calls.react.length, previousRenders, "filters must not render a hidden map");
  assert.equal(nodes.get("resultList").children.length, 1);
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(calls.newPlot.length, 1, "switching views reuses the initialized plot");
  assert.deepEqual([...calls.react.at(-1).data.flatMap(trace => trace.customdata)], ["10.1234/def"]);
});

test("map points and paper rows select a stable preview before opening Details", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(calls.newPlot[0].config.displayModeBar, false);
  assert.equal(nodes.get("mapPaperCount").textContent, "2");
  const first = descendants(nodes.get("mapPaperList")).find(node => node.tagName === "BUTTON");
  first.focus();
  first.dispatch("click");
  await settle();
  assert.equal(nodes.get("mapSelection").hidden, false);
  assert.equal(nodes.get("mapSelectedTitle").textContent, source[0].title);
  assert.notEqual(nodes.get("paperDialog").open, true);
  assert.equal(browser.document.activeElement, first);
  assert.equal(first.getAttribute("aria-pressed"), "true");
  const overlay = calls.react.at(-1).data.find(trace => trace.meta.selection);
  assert.deepEqual([...overlay.customdata], ["10.1234/abc"]);
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/def"}]});
  await settle();
  assert.equal(nodes.get("mapSelectedTitle").textContent, source[1].title);
  assert.notEqual(nodes.get("paperDialog").open, true);
  nodes.get("mapOpenDetails").dispatch("click");
  assert.equal(nodes.get("paperDialog").open, true);
  assert.equal(nodes.get("detailTitle").textContent, source[1].title);
});

test("panning updates the viewport browser without pruning or redrawing map points", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/def"}]});
  await settle();
  const previousDraws = calls.react.length;
  nodes.get("plot").dispatch("plotly_relayout", {"xaxis.range[0]": 0.5, "xaxis.range[1]": 1.5, "yaxis.range[0]": 1.5, "yaxis.range[1]": 2.5});
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  assert.ok(nodeText(nodes.get("mapPaperList")).includes(source[0].title));
  assert.equal(nodes.get("mapSelectedTitle").textContent, source[1].title, "selected filtered paper remains available outside the viewport");
  assert.equal(calls.react.length, previousDraws);
  nodes.get("plot").dispatch("plotly_relayout", {autosize: true});
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  nodes.get("mapLocateSelection").dispatch("click");
  await settle();
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  assert.ok(nodeText(nodes.get("mapPaperList")).includes(source[1].title));
  const located = calls.relayout.at(-1);
  assert.equal(located["xaxis.range"][1] - located["xaxis.range"][0], 1, "Locate keeps the current zoom");
  nodes.get("mapReset").dispatch("click");
  await settle();
  assert.equal(nodes.get("mapPaperCount").textContent, "2");
  const fittedWidth = calls.relayout.at(-1)["xaxis.range"][1] - calls.relayout.at(-1)["xaxis.range"][0];
  nodes.get("mapZoomIn").dispatch("click");
  await settle();
  const zoomedWidth = calls.relayout.at(-1)["xaxis.range"][1] - calls.relayout.at(-1)["xaxis.range"][0];
  assert.ok(zoomedWidth < fittedWidth);
  nodes.get("mapZoomOut").dispatch("click");
  await settle();
  const wider = calls.relayout.at(-1)["xaxis.range"][1] - calls.relayout.at(-1)["xaxis.range"][0];
  assert.ok(wider > zoomedWidth);
  assert.equal(calls.react.length, previousDraws, "fit and zoom use relayout, not full data rendering");
});

test("a pan during a slow selection redraw updates the viewport list and zoom center", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls, plotly} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  plotly.react = async (_, data, layout) => { calls.react.push({data, layout}); await gate; };
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/abc"}]});
  nodes.get("plot").dispatch("plotly_relayout", {"xaxis.range[0]": 0.5, "xaxis.range[1]": 1.5, "yaxis.range[0]": 1.5, "yaxis.range[1]": 2.5});
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  release();
  await settle();
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  nodes.get("mapZoomIn").dispatch("click");
  await settle();
  const range = calls.relayout.at(-1)["xaxis.range"];
  assert.equal((range[0] + range[1]) / 2, 1);
});

test("a stale redraw range cannot overwrite a newer filter's fitted viewport", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls, plotly} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  plotly.react = async (_, data, layout) => { calls.react.push({data, layout}); await gate; };
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/abc"}]});
  nodes.get("mapTopicSelect").value = "Networks";
  nodes.get("mapTopicSelect").dispatch("change");
  nodes.get("plot").dispatch("plotly_relayout", {"xaxis.range": [0.5, 1.5], "yaxis.range": [1.5, 2.5]});
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  assert.ok(nodeText(nodes.get("mapPaperList")).includes(source[1].title));
  release();
  await settle();
  assert.deepEqual([...calls.react.at(-1).layout.xaxis.range], [2.5, 3.5]);
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
});

test("map topic and available-only controls sync global filters and refit matching papers", async t => {
  const browser = browserFixture({query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, calls} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  nodes.get("plot").dispatch("plotly_click", {points: [{customdata: "10.1234/abc"}]});
  await settle();
  nodes.get("mapTopicSelect").value = "Networks";
  nodes.get("mapTopicSelect").dispatch("change");
  await settle();
  assert.equal(nodes.get("topicSelect").value, "Networks");
  assert.equal(nodes.get("mapSelection").hidden, true, "filtered-out selection must clear");
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  assert.deepEqual([...calls.react.at(-1).layout.xaxis.range], [2.5, 3.5]);
  nodes.get("mapAvailableOnly").dispatch("click");
  await settle();
  assert.equal(nodes.get("availabilitySelect").value, "available");
  assert.equal(nodes.get("mapAvailableOnly").getAttribute("aria-pressed"), "true");
  assert.equal(nodes.get("mapPaperCount").textContent, "0");
  nodes.get("viewData").dispatch("click");
  await settle();
  assert.equal(nodes.get("mapAvailableOnly").textContent, "Available data only");
  assert.equal(nodes.get("mapPaperCount").textContent, "1");
  nodes.get("availabilitySelect").value = "unavailable";
  nodes.get("availabilitySelect").dispatch("change");
  await settle();
  assert.equal(nodes.get("mapAvailableOnly").getAttribute("aria-pressed"), "false");
});

test("tablet and touch-screen maps keep gestures paused until explicitly enabled", async t => {
  for (const options of [{width: 768}, {width: 1024, coarsePointer: true}]) {
    const browser = browserFixture(options);
    t.after(browser.cleanup);
    await settle();
    browser.nodes.get("showMap").dispatch("click");
    await settle();
    assert.equal(browser.nodes.get("mapInteraction").getAttribute("aria-pressed"), "false");
    assert.equal(browser.nodes.get("mapCanvas").classList.contains("is-passive"), true);
  }
});

test("phone maps allow page scrolling by default and preserve a chosen gesture preference", async t => {
  const browser = browserFixture({width: 390});
  t.after(browser.cleanup);
  await settle();
  const {nodes, window} = browser;
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(nodes.get("mapInteraction").getAttribute("aria-pressed"), "false");
  assert.equal(nodes.get("mapCanvas").classList.contains("is-passive"), true);
  assert.equal(nodes.get("mapZoomIn").disabled, false, "explicit controls work while gestures are paused");
  window.innerWidth = 1200;
  window.dispatch("resize");
  await new Promise(resolve => setTimeout(resolve, 120));
  assert.equal(nodes.get("mapInteraction").getAttribute("aria-pressed"), "true");
  nodes.get("mapInteraction").dispatch("click");
  assert.equal(nodes.get("mapInteraction").getAttribute("aria-pressed"), "false");
  window.dispatch("resize");
  await new Promise(resolve => setTimeout(resolve, 120));
  assert.equal(nodes.get("mapInteraction").getAttribute("aria-pressed"), "false", "resize must not override the reader's preference");
});

test("switching to List during a map download prevents hidden plot initialization", async t => {
  const browser = browserFixture({hasPlotly: false});
  t.after(browser.cleanup);
  await settle();
  const {nodes, document, window, plotly, calls} = browser;
  assert.equal(document.head.children.length, 0);
  nodes.get("showMap").dispatch("click");
  assert.equal(document.head.children.length, 1);
  const script = document.head.children[0];
  assert.equal(script.src, "https://cdn.plot.ly/plotly-2.30.0.min.js");
  nodes.get("showList").dispatch("click");
  window.Plotly = plotly;
  script.onload();
  await settle();
  assert.equal(calls.newPlot.length, 0);
  nodes.get("showMap").dispatch("click");
  await settle();
  assert.equal(calls.newPlot.length, 1);
});

test("a map-library failure leaves List search and Details usable", async t => {
  const browser = browserFixture({hasPlotly: false, query: "travel"});
  t.after(browser.cleanup);
  await settle();
  const {nodes, document} = browser;
  nodes.get("showMap").dispatch("click");
  document.head.children[0].onerror();
  await settle();
  assert.equal(nodes.get("plotStatus").hidden, false);
  assert.match(nodes.get("plotStatus").textContent, /Map unavailable/);
  assert.equal(nodes.get("mapPaperCount").textContent, "2", "the linked paper browser remains available without Plotly");
  descendants(nodes.get("mapPaperList")).find(node => node.tagName === "BUTTON").dispatch("click");
  assert.equal(nodes.get("mapSelection").hidden, false);
  nodes.get("mapOpenDetails").dispatch("click");
  assert.equal(nodes.get("paperDialog").open, true);
  nodes.get("closeDialog").dispatch("click");
  nodes.get("showList").dispatch("click");
  nodes.get("searchInput").value = "network";
  nodes.get("searchScope").value = "title";
  nodes.get("searchScope").dispatch("change");
  assert.equal(nodes.get("searchInput").disabled, false);
  assert.equal(nodes.get("resultList").children.length, 1);
  const details = descendants(nodes.get("resultList")).find(node => node.tagName === "BUTTON");
  details.dispatch("click");
  assert.equal(nodes.get("paperDialog").open, true);
});

test("a collection fetch failure leaves a visible loading notice and retry action", async t => {
  const browser = browserFixture({fetchFails: true});
  t.after(browser.cleanup);
  await settle();
  assert.equal(browser.nodes.get("loadingNotice").hidden, false);
  assert.match(browser.nodes.get("loadingNotice").textContent, /Couldn't load papers/);
  assert.equal(browser.nodes.get("retryLoad").hidden, false);
  assert.equal(browser.nodes.get("searchInput").disabled, true);
  assert.equal(browser.nodes.get("resultsPanel").hidden, false);
});
