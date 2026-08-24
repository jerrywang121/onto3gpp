/* onto3gpp explorer frontend — vanilla JS, no build step. */

const $ = (id) => document.getElementById(id);

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
  });
});

/* ---------- meta ---------- */
async function loadMeta() {
  try {
    const m = await (await fetch("/api/meta")).json();
    const specs = Object.entries(m.specs)
      .map(([s, n]) => `${s} (${n})`)
      .join(", ");
    $("meta").textContent =
      `chunks ${m.chunks} · concepts ${m.concepts} · relations ${m.relations} · ` +
      `dict ${m.dictionary_entries} · specs: ${specs}`;
  } catch (e) {
    $("meta").textContent = "meta unavailable";
  }
}

/* ---------- query ---------- */
function readParams() {
  return {
    top_k: parseInt($("p-topk").value, 10) || 10,
    max_hops: parseInt($("p-hops").value, 10) || 1,
    fuzzy_threshold: parseFloat($("p-fuzzy").value) || 0,
    use_chain: $("p-chain").checked,
    use_ontology: $("p-ontology").checked,
    use_structure: $("p-structure").checked,
  };
}

function renderResults(data) {
  const el = $("query-results");
  if (!data.results.length) {
    el.innerHTML = '<div class="empty">No results.</div>';
    return;
  }

  const trace = `
    <div class="trace">
      <h3>Search plan</h3>
      <div class="row"><b>primary:</b> ${data.plan.primary_terms.map(tag).join(" ") || "—"}</div>
      <div class="row"><b>related:</b> ${data.plan.related_terms.map(tag).join(" ") || "—"}</div>
      <div class="row"><b>NER matches:</b> ${
        data.ner_matches
          .map((m) => `<span class="tag">${esc(m.canonical)} <span class="lvl">L${m.level}</span></span>`)
          .join(" ") || "—"
      }</div>
      <div class="row"><b>explanation:</b></div>
      ${data.plan.explanation.map((e) => `<div class="row">· ${esc(e)}</div>`).join("") || ""}
    </div>`;

  const results = data.results
    .map((r) => `
      <div class="result">
        <div class="head">
          <span class="rank">#${r.rank}</span>
          <span class="score">${r.score}</span>
          <span class="clause">${esc(r.clause)}</span>
          <span class="title">${esc(r.title)}</span>
          <span class="spec">${esc(r.spec)}</span>
        </div>
        <div class="text">${esc(r.text)}</div>
      </div>`)
    .join("");

  el.innerHTML = trace + results;
}

function tag(t) {
  return `<span class="tag">${esc(t)}</span>`;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function runQuery() {
  const query = $("query-input").value.trim();
  if (!query) return;
  const params = readParams();
  $("query-results").innerHTML = '<div class="empty">Searching…</div>';
  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, ...params }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    renderQuery(await res.json());
  } catch (e) {
    $("query-results").innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
  }
}

function renderQuery(data) {
  renderResults(data);
  // offer to jump to the graph for the top resolved concept
  const primary = data.plan.primary_terms[0];
  if (primary) {
    $("graph-concept").value = primary;
  }
}

$("query-btn").addEventListener("click", runQuery);
$("query-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runQuery();
});

/* ---------- concepts ---------- */
async function loadConceptTypes() {
  try {
    const res = await fetch("/api/concepts?limit=1000");
    const data = await res.json();
    const types = new Set(data.concepts.map((c) => c.type));
    const sel = $("concept-type");
    types.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
  } catch (e) {
    /* ignore */
  }
}

async function filterConcepts() {
  const q = $("concept-filter").value.trim();
  const type = $("concept-type").value;
  const params = new URLSearchParams({ limit: "500" });
  if (q) params.set("q", q);
  if (type) params.set("type", type);
  const el = $("concept-list");
  el.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const res = await fetch("/api/concepts?" + params.toString());
    const data = await res.json();
    if (!data.concepts.length) {
      el.innerHTML = '<div class="empty">No concepts match.</div>';
      return;
    }
    el.innerHTML = data.concepts
      .map(
        (c) => `
        <div class="concept">
          <span class="canonical">${esc(c.canonical)}</span>
          <span class="type">${esc(c.type)}</span>
          <span class="aliases">${c.aliases.map(esc).join(", ") || ""}</span>
          <button class="go" data-concept="${esc(c.canonical)}">graph</button>
        </div>`
      )
      .join("");
    el.querySelectorAll(".go").forEach((b) =>
      b.addEventListener("click", () => {
        $("graph-concept").value = b.dataset.concept;
        document.querySelector('[data-tab="graph"]').click();
        loadGraph();
      })
    );
  } catch (e) {
    el.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
  }
}

$("concept-btn").addEventListener("click", filterConcepts);
$("concept-filter").addEventListener("keydown", (e) => {
  if (e.key === "Enter") filterConcepts();
});

/* ---------- graph (cytoscape.js) ---------- */
let cy = null;
let graphState = null;

async function loadGraph() {
  const concept = $("graph-concept").value.trim();
  const radius = parseInt($("graph-radius").value, 10) || 1;
  const limit = parseInt($("graph-limit").value, 10) || 200;
  if (!concept) return;
  $("graph-info").textContent = "Loading…";
  try {
    const res = await fetch(
      `/api/graph?concept=${encodeURIComponent(concept)}&radius=${radius}&limit=${limit}`
    );
    if (!res.ok) {
      $("graph-info").textContent = (await res.json()).detail || "error";
      return;
    }
    const data = await res.json();
    graphState = data;
    $("graph-info").textContent =
      `${data.nodes.length} nodes, ${data.edges.length} edges (center: ${data.center})`;
    drawGraph(data);
  } catch (e) {
    $("graph-info").textContent = "Error: " + e.message;
  }
}

$("graph-btn").addEventListener("click", loadGraph);
$("graph-concept").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadGraph();
});

function drawGraph(data) {
  const container = $("graph-container");
  if (cy) {
    cy.destroy();
    cy = null;
  }

  const elements = [
    ...data.nodes.map((n) => ({
      data: {
        id: n.id,
        label: n.canonical,
        canonical: n.canonical,
        type: n.type,
        is_center: n.is_center,
      },
    })),
    ...data.edges.map((e) => ({
      data: {
        id: `${e.source}--${e.rel}--${e.target}`,
        source: e.source,
        target: e.target,
        rel: e.rel,
        label: e.rel,
      },
    })),
  ];

  cy = cytoscape({
    container,
    elements,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "#4f8cff",
          "border-color": "#2e3a55",
          "border-width": 1,
          label: "data(label)",
          color: "#e6ecf5",
          "font-size": 11,
          "text-valign": "bottom",
          "text-margin-y": 4,
          width: 22,
          height: 22,
        },
      },
      {
        selector: "node[is_center]",
        style: {
          "background-color": "#ffb454",
          width: 30,
          height: 30,
          "border-width": 2,
        },
      },
      {
        selector: "edge",
        style: {
          width: 1,
          "line-color": "#2e3a55",
          "target-arrow-color": "#2e3a55",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          label: "data(label)",
          "font-size": 8,
          color: "#8b98b3",
          "text-rotation": "autorotate",
        },
      },
      {
        selector: ":selected",
        style: {
          "background-color": "#37d0a0",
          "line-color": "#37d0a0",
          "target-arrow-color": "#37d0a0",
        },
      },
    ],
    layout: {
      name: "cose",
      animate: false,
      padding: 40,
      nodeRepulsion: 8000,
      idealEdgeLength: 90,
      gravity: 0.3,
    },
    wheelSensitivity: 0.2,
    minZoom: 0.1,
    maxZoom: 4,
  });

  // Click a node or edge -> show details in the side panel.
  cy.on("tap", "node", (evt) => {
    const n = evt.target;
    showNodeDetails(n.data());
  });
  cy.on("tap", "edge", (evt) => {
    const e = evt.target;
    showEdgeDetails(e.data());
  });
  cy.on("tap", (evt) => {
    if (evt.target === cy) {
      $("graph-details-body").innerHTML =
        '<div class="empty">Click a node or edge to see its details.</div>';
    }
  });

  // Fit the graph into the viewport.
  cy.fit(undefined, 40);
}

function showNodeDetails(d) {
  const body = $("graph-details-body");
  body.innerHTML = `
    <div class="detail-row"><span class="k">canonical</span><span class="v">${esc(d.canonical)}</span></div>
    <div class="detail-row"><span class="k">id</span><span class="v">${esc(d.id)}</span></div>
    <div class="detail-row"><span class="k">type</span><span class="v">${esc(d.type)}</span></div>
    <div class="detail-row"><span class="k">center</span><span class="v">${d.is_center ? "yes" : "no"}</span></div>
    <div class="detail-row"><span class="k">degree</span><span class="v">${cy.getElementById(d.id).degree()}</span></div>
  `;
}

function showEdgeDetails(d) {
  const body = $("graph-details-body");
  body.innerHTML = `
    <div class="detail-row"><span class="k">relation</span><span class="v">${esc(d.rel)}</span></div>
    <div class="detail-row"><span class="k">source</span><span class="v">${esc(d.source)}</span></div>
    <div class="detail-row"><span class="k">target</span><span class="v">${esc(d.target)}</span></div>
  `;
}

/* ---------- init ---------- */
loadMeta();
loadConceptTypes();
