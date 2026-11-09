"use strict";

const MAX_BARS = 30;
const REFUSAL_HINTS = {
  chinook: "Try asking about what the store records: customers, employees, invoices, tracks, albums, artists and genres.",
};

const $ = (sel) => document.querySelector(sel);
const form = $("#ask-form");
const input = $("#question");
const tooltip = $("#tooltip");
const history = [];
let historyIndex = -1;
let current = null;            // the selected dataset: {key, title, ask_label, examples}
const feeds = new Map();       // dataset key -> its answers <section>, kept when switching

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

const isNumber = (v) => typeof v === "number" && Number.isFinite(v);
const fmt = (v) => {
  if (v === null || v === undefined) return "—";
  if (!isNumber(v)) return String(v);
  return v.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
};
const humanize = (name) => {
  let s = String(name).replace(/([a-z])([A-Z])/g, "$1_$2").replace(/[_\s]+/g, " ").trim().toLowerCase();
  s = s.replace(/^(num|number of|count of|total|cnt)\s+/, "").replace(/\s+(count|cnt)$/, "") || s;
  return s.charAt(0).toUpperCase() + s.slice(1);
};
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } },
};

/* ---------------------------------------------------------- status & datasets */

async function fetchStatus(key) {
  return (await fetch(`/api/status?dataset=${encodeURIComponent(key)}`)).json();
}

function feedFor(key) {
  if (!feeds.has(key)) {
    const feed = el("section", { class: "answers", "aria-live": "polite" });
    feeds.set(key, feed);
    $("#feeds").append(feed);
  }
  return feeds.get(key);
}

function renderSwitcher(datasets) {
  const nav = $("#dataset-switch");
  if (nav.childElementCount || datasets.length < 2) return;  // a switch with one choice is just noise
  for (const d of datasets) {
    nav.append(el("button", { type: "button", "data-key": d.key, onclick: () => selectDataset(d.key) }, d.title));
  }
}

async function selectDataset(key) {
  const status = await fetchStatus(key);
  current = status.dataset;
  store.set("dataset", current.key);
  renderSwitcher(status.datasets);
  document.querySelectorAll("#dataset-switch button")
    .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === current.key)));
  $("label[for=question]").textContent = current.ask_label;
  input.placeholder = current.examples[0];
  $("#library-summary").textContent = status.summary;
  for (const [k, feed] of feeds) feed.hidden = k !== current.key;
  const feed = feedFor(current.key);
  feed.hidden = false;
  $("#examples .chips").replaceChildren(
    ...current.examples.map((q) => el("button", { type: "button", onclick: () => submit(q) }, q)));
  $("#examples").hidden = feed.childElementCount > 0;
  input.focus();
}

async function pollStatus() {
  const statusEl = $("#model-status");
  try {
    const status = await fetchStatus(current ? current.key : "chinook");
    if (status.model_error) {
      statusEl.textContent = "Model failed to start";
      statusEl.className = "status failed";
      statusEl.title = status.model_error;
      return;
    }
    if (status.model_ready) {
      statusEl.textContent = "Ready";
      statusEl.className = "status ready";
      return;
    }
  } catch { /* server still starting */ }
  setTimeout(pollStatus, 800);
}

/* ---------------------------------------------------------- asking */

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit(input.value);
});

input.addEventListener("keydown", (event) => {
  if (!history.length || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  historyIndex = Math.max(-1, Math.min(history.length - 1, historyIndex + (event.key === "ArrowUp" ? 1 : -1)));
  input.value = historyIndex < 0 ? "" : history[historyIndex];
});

async function submit(question) {
  question = question.trim();
  if (!question || !current) return;
  const dataset = current.key;   // the answer belongs to this dataset even if the user switches meanwhile
  history.unshift(question);
  historyIndex = -1;
  $("#examples").hidden = true;

  const pending = el("article", { class: "entry pending" },
    el("p", { class: "question" }, question),
    el("p", { class: "answer" }, "Writing a query…"));
  feedFor(dataset).prepend(pending);
  input.value = "";
  const slow = setTimeout(() => {
    pending.querySelector(".answer").textContent = "Still working. The first question loads the model onto the GPU.";
  }, 6000);

  let result;
  try {
    result = await (await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, dataset }),
    })).json();
  } catch (err) {
    result = { question, error: `The app's server stopped responding (${err.message}).` };
  } finally {
    clearTimeout(slow);
  }
  // Questions run one at a time on the server, so several can be waiting here at once.
  pending.replaceWith(renderEntry(question, result, dataset));
}

/* ---------------------------------------------------------- rendering */

function renderEntry(question, r, dataset) {
  const entry = el("article", { class: "entry" }, el("p", { class: "question" }, question));

  if (r.refusal) {
    entry.append(
      el("p", { class: "answer muted" }, "This data can't answer that."),
      el("p", { class: "notice" }, `Missing: ${r.refusal}. ${REFUSAL_HINTS[dataset] || ""}`));
    return entry;
  }
  if (r.error && !r.sql) {
    entry.append(el("p", { class: "notice error" }, r.error));
    return entry;
  }
  if (r.error) {
    entry.append(
      el("p", { class: "answer muted" }, "That question didn't produce a working query."),
      el("p", { class: "notice error" }, `${r.error}. Try rephrasing it, or use exact names.`));
  } else {
    const answer = r.answer || "Here's what I found.";
    entry.append(el("p", { class: answer.length > 160 ? "answer long" : "answer" }, answer));
    for (const c of r.corrections || []) {
      entry.append(el("p", { class: "correction" }, `Matched “${c.typed}” to “${c.matched}”.`));
    }
    entry.append(renderEvidence(r));
  }
  entry.append(renderMeta(r));
  return entry;
}

function renderEvidence(r) {
  const wrap = el("div", { class: "evidence" });
  const { columns, rows } = r;
  if (!rows.length) {
    wrap.append(el("p", { class: "table-note" }, "The query ran but matched nothing."));
    return wrap;
  }
  if (rows.length === 1 && columns.length === 1 && isShort(rows[0][0])) {
    wrap.append(el("div", { class: "stat" },
      el("div", { class: "value" }, fmt(rows[0][0])),
      el("div", { class: "caption" }, humanize(columns[0]))));
    return wrap;
  }
  if (rows.length <= 3 && rows.some((row) => row.some((v) => !isShort(v)))) {
    wrap.append(...rows.map((row) => renderRecord(columns, row)));  // e.g. a title with its description
    return wrap;
  }

  const shape = barShape(columns, rows);
  const table = renderTable(columns, rows, r.truncated);
  if (!shape) {
    wrap.append(table);
    return wrap;
  }
  const chart = renderBars(shape);
  const views = { Chart: chart, Table: table };
  const switcher = el("div", { class: "view-switch", role: "group", "aria-label": "Show results as" });
  const holder = el("div", {}, chart);
  for (const name of Object.keys(views)) {
    switcher.append(el("button", {
      type: "button", "aria-pressed": String(name === "Chart"),
      onclick: (e) => {
        switcher.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
        holder.replaceChildren(views[name]);
      },
    }, name));
  }
  wrap.append(switcher, holder);
  return wrap;
}

const isShort = (v) => isNumber(v) || v === null || String(v).length <= 40;

/* One row as label/value pairs; long text (descriptions) wraps as a readable paragraph. */
function renderRecord(columns, row) {
  const list = el("dl", { class: "record" });
  columns.forEach((c, i) => {
    const long = !isShort(row[i]);
    list.append(el("dt", {}, humanize(c)), el("dd", { class: long ? "passage" : "" }, fmt(row[i])));
  });
  return list;
}

/* A ranking-shaped result: one text column, one numeric column, a handful of rows. */
function barShape(columns, rows) {
  if (rows.length < 2 || rows.length > MAX_BARS || columns.length < 2) return null;
  const numericCols = columns.map((_, i) => i).filter((i) => rows.every((row) => isNumber(row[i]) || row[i] === null));
  const textCols = columns.map((_, i) => i).filter((i) => !numericCols.includes(i));
  if (numericCols.length < 1 || textCols.length !== 1) return null;
  const valueCol = numericCols[numericCols.length - 1];  // usually the measure is last (title, year, COUNT)
  const labelCol = textCols[0];
  if (rows.some((row) => row[valueCol] < 0)) return null;
  return {
    measure: humanize(columns[valueCol]),
    items: rows.map((row) => ({ label: String(row[labelCol] ?? "—"), value: row[valueCol] ?? 0 })),
  };
}

function renderBars({ measure, items }) {
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  const longest = Math.max(...items.map((d) => Math.min(d.label.length, 30)));
  const width = 820, labelW = Math.max(90, Math.min(240, longest * 7.4 + 16)), barH = 20, gap = 8, top = 22;
  const plotW = width - labelW - 16;
  const max = Math.max(...items.map((d) => d.value)) || 1;
  const step = niceStep(max / 5);
  const axisMax = Math.ceil(max / step) * step;
  const height = top + items.length * (barH + gap);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${measure} by item` });

  for (let t = 0; t <= axisMax + 1e-9; t += step) {
    const x = labelW + (t / axisMax) * plotW;
    svg.append(svgEl("line", { class: "gridline", x1: x, x2: x, y1: top - 6, y2: height - gap }));
    const tick = svgEl("text", { class: "tick", x, y: 12, "text-anchor": "middle" });
    tick.textContent = fmt(t);
    svg.append(tick);
  }

  items.forEach((d, i) => {
    const y = top + i * (barH + gap);
    const label = svgEl("text", { class: "label", x: labelW - 12, y: y + barH / 2 + 4.5, "text-anchor": "end" });
    label.textContent = d.label.length > 30 ? d.label.slice(0, 29) + "…" : d.label;
    const w = Math.max(2, (d.value / axisMax) * plotW);
    const r = Math.min(4, w / 2);
    // Square at the baseline, 4px rounded at the data end.
    const bar = svgEl("path", {
      class: "bar",
      d: `M${labelW},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${barH - 2 * r} a${r},${r} 0 0 1 -${r},${r} h-${w - r} z`,
    });
    const hit = svgEl("rect", { class: "hit", x: 0, y: y - gap / 2, width, height: barH + gap });
    hit.addEventListener("mousemove", (e) => showTip(e, d.label, `${measure}: `, fmt(d.value), bar));
    hit.addEventListener("mouseleave", () => hideTip(bar));
    svg.append(label, hit, bar);
  });
  return el("div", { class: "chart" }, svg);
}

function niceStep(raw) {
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  const n = raw / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * pow;
}

function showTip(event, title, prefix, value, bar) {
  bar.classList.add("active");
  tooltip.replaceChildren(el("div", {}, title), el("div", {}, prefix, el("strong", {}, value)));
  tooltip.hidden = false;
  const pad = 14;
  const x = Math.min(event.clientX + pad, window.innerWidth - tooltip.offsetWidth - 8);
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${event.clientY + pad}px`;
}
function hideTip(bar) {
  bar.classList.remove("active");
  tooltip.hidden = true;
}

function renderTable(columns, rows, truncated) {
  const numeric = columns.map((_, i) => rows.every((row) => isNumber(row[i]) || row[i] === null));
  const table = el("table", {},
    el("thead", {}, el("tr", {}, ...columns.map((c, i) => el("th", { class: numeric[i] ? "num" : "" }, humanize(c))))),
    el("tbody", {}, ...rows.map((row) =>
      el("tr", {}, ...row.map((v, i) => el("td", { class: numeric[i] ? "num" : isShort(v) ? "" : "long" }, fmt(v)))))));
  const wrap = el("div", {}, el("div", { class: "table-wrap" }, table));
  const count = `${rows.length.toLocaleString()} ${rows.length === 1 ? "row" : "rows"}`;
  wrap.append(el("p", { class: "table-note" }, truncated ? `Showing the first ${count}.` : count));
  return wrap;
}

function renderMeta(r) {
  const sql = el("pre", { class: "sql", hidden: "" }, r.sql || "");
  const toggle = el("button", {
    class: "link", type: "button", "aria-expanded": "false",
    onclick: () => {
      sql.hidden = !sql.hidden;
      toggle.setAttribute("aria-expanded", String(!sql.hidden));
      toggle.textContent = sql.hidden ? "Show SQL" : "Hide SQL";
    },
  }, "Show SQL");
  const copy = el("button", {
    class: "link", type: "button",
    onclick: async () => {
      await navigator.clipboard.writeText(r.sql || "");
      copy.textContent = "Copied";
      setTimeout(() => (copy.textContent = "Copy SQL"), 1500);
    },
  }, "Copy SQL");
  const retries = r.attempts > 1 ? `, fixed its own query after ${r.attempts - 1} failed ${r.attempts === 2 ? "try" : "tries"}` : "";
  const meta = el("div", { class: "meta" }, toggle, copy, el("span", {}, `Answered in ${r.seconds} s${retries}`));
  return el("div", {}, meta, sql);
}

selectDataset(store.get("dataset") || "chinook").then(pollStatus, pollStatus);
// Browsers throttle timers in windows hidden behind others; re-check as soon as it's seen again.
document.addEventListener("visibilitychange", () => { if (!document.hidden) pollStatus(); });
window.addEventListener("focus", pollStatus);
