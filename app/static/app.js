"use strict";

// ---------------------------------------------------------------- helpers

const $ = (id) => document.getElementById(id);
const MAX_FILES = 3;
const MAX_BYTES = 10 * 1024 * 1024;

const money = (x) =>
  x == null ? "" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: Number.isInteger(x) ? 0 : 2, maximumFractionDigits: 2,
  }).format(x);

/** Build a DOM node. Text is always set with textContent, so quote content cannot inject HTML. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

function track(name, value = "") {
  const body = new FormData();
  body.append("name", name);
  body.append("value", String(value).slice(0, 40));
  fetch("/api/events", { method: "POST", body }).catch(() => {});
}

function show(view) {
  for (const id of ["view-upload", "view-processing", "view-results"]) {
    $(id).classList.toggle("hidden", id !== view);
  }
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------- upload view

const state = { files: [], mode: "pdf", texts: ["", ""] };

function setMode(mode) {
  state.mode = mode;
  $("pane-pdf").classList.toggle("hidden", mode !== "pdf");
  $("pane-text").classList.toggle("hidden", mode !== "text");
  const on = "bg-white text-slate-900 shadow-sm", off = "text-slate-500 hover:text-slate-700";
  $("tab-pdf").className = `rounded-md px-3 py-1.5 ${mode === "pdf" ? on : off}`;
  $("tab-text").className = `rounded-md px-3 py-1.5 ${mode === "text" ? on : off}`;
  $("tab-pdf").setAttribute("aria-selected", mode === "pdf");
  $("tab-text").setAttribute("aria-selected", mode === "text");
  renderTextBoxes();
  refreshAnalyze();
}

function showUploadError(msg) {
  const el = $("upload-error");
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

function addFiles(list) {
  showUploadError("");
  for (const f of list) {
    if (state.files.length >= MAX_FILES) { showUploadError("You can compare up to 3 quotes."); break; }
    if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") { showUploadError(`${f.name} is not a PDF. You can paste text instead.`); continue; }
    if (f.size > MAX_BYTES) { showUploadError(`${f.name} is larger than 10 MB.`); continue; }
    state.files.push(f);
  }
  renderFiles();
}

function renderFiles() {
  const ul = $("file-list");
  ul.replaceChildren(...state.files.map((f, i) =>
    h("li", { class: "flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm" },
      h("span", { class: "flex min-w-0 items-center gap-2" },
        h("span", { class: "rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700" }, "PDF"),
        h("span", { class: "truncate font-medium text-slate-700" }, f.name),
        h("span", { class: "flex-none text-slate-400" }, `${(f.size / 1024).toFixed(0)} KB`)),
      h("button", { type: "button", class: "ml-3 text-slate-400 hover:text-red-600", "aria-label": `Remove ${f.name}`,
        onclick: () => { state.files.splice(i, 1); renderFiles(); } }, "Remove"))));
  refreshAnalyze();
}

function renderTextBoxes() {
  const box = $("text-boxes");
  box.replaceChildren(...state.texts.map((t, i) =>
    h("div", {},
      h("label", { class: "text-sm font-medium text-slate-700", for: `text-${i}` }, `Quote ${i + 1}`),
      h("textarea", {
        id: `text-${i}`, rows: 6, maxlength: 60000, placeholder: "Paste the quote text here",
        class: "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100",
        oninput: (e) => { state.texts[i] = e.target.value; refreshAnalyze(); },
      }, t))));
  $("add-text").classList.toggle("hidden", state.texts.length >= MAX_FILES);
}

function inputCount() {
  return state.mode === "pdf" ? state.files.length : state.texts.filter((t) => t.trim()).length;
}

function refreshAnalyze() {
  const n = inputCount();
  $("analyze").disabled = n < 2 || n > MAX_FILES;
  $("analyze").textContent = n < 2 ? "Add at least 2 quotes to compare" : `Compare ${n} quotes`;
}

// ---------------------------------------------------------------- streaming

const STEPS = [
  ["extract", "Reading quotes", "Pulling out prices, fees and terms, with the source text for each"],
  ["normalize", "Normalizing prices", "Converting monthly, yearly and per-visit pricing to annual cost"],
  ["compare", "Comparing vendors", "Lining up what each vendor includes and leaves out"],
  ["risk_check", "Checking terms", "Looking for auto-renewals, escalators, lock-ins and extra fees"],
  ["recommend", "Choosing a vendor", "Weighing true cost against risk"],
  ["draft_email", "Drafting email", "Writing a negotiation email that uses your leverage"],
];

function renderSteps() {
  $("steps").replaceChildren(...STEPS.map(([id, label, sub]) =>
    h("li", { id: `step-${id}`, class: "flex items-start gap-3", "data-status": "pending" },
      h("span", { class: "step-icon mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full border-2 border-slate-200" }),
      h("div", {}, h("div", { class: "step-label font-medium text-slate-400" }, label),
        h("div", { class: "text-sm text-slate-400" }, sub)))));
}

function setStep(id, status) {
  const li = $(`step-${id}`);
  if (!li) return;
  li.dataset.status = status;
  const icon = li.querySelector(".step-icon"), label = li.querySelector(".step-label");
  icon.replaceChildren();
  icon.className = "step-icon mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full";
  label.className = "step-label font-medium";
  if (status === "running") {
    icon.append(h("span", { class: "spinner h-5 w-5" }));
    label.classList.add("text-slate-900");
  } else if (status === "done") {
    icon.classList.add("bg-emerald-500", "text-white");
    icon.innerHTML = '<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.8 3.8 6.8-6.8a1 1 0 011.4 0z" clip-rule="evenodd"/></svg>';
    label.classList.add("text-slate-700");
  } else if (status === "error") {
    icon.classList.add("bg-red-500", "text-white", "text-xs", "font-bold");
    icon.textContent = "!";
    label.classList.add("text-red-700");
  } else {
    icon.classList.add("border-2", "border-slate-200");
    label.classList.add("text-slate-400");
  }
}

function procError(msg) {
  $("proc-error-msg").textContent = msg;
  $("proc-error").classList.remove("hidden");
}

async function stream(url, body) {
  renderSteps();
  $("proc-error").classList.add("hidden");
  show("view-processing");
  let res;
  try {
    res = await fetch(url, { method: "POST", body });
  } catch {
    return procError("Could not reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let msg = "Something went wrong. Please try again.";
    try { msg = (await res.json()).detail || msg; } catch { /* keep default */ }
    return procError(msg);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", gotResult = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const data = block.split("\n").find((l) => l.startsWith("data: "));
      if (!data) continue;
      const ev = JSON.parse(data.slice(6));
      if (ev.event === "step") setStep(ev.step, ev.status);
      else if (ev.event === "error") return procError(ev.message);
      else if (ev.event === "result") { gotResult = true; renderResults(ev.data); show("view-results"); }
    }
  }
  if (!gotResult) procError("The analysis ended unexpectedly. Please try again.");
}

function analyzeOwn() {
  const body = new FormData();
  if (state.mode === "pdf") state.files.forEach((f) => body.append("files", f));
  else state.texts.filter((t) => t.trim()).forEach((t) => body.append("texts", t));
  body.append("context", $("context").value);
  stream("/api/analyze", body);
}

function analyzeSample(category) {
  const body = new FormData();
  body.append("category", category);
  stream("/api/analyze-sample", body);
}

// ---------------------------------------------------------------- results

const SEV = {
  high: { label: "High", badge: "bg-red-100 text-red-700", bar: "border-l-red-500" },
  medium: { label: "Medium", badge: "bg-amber-100 text-amber-800", bar: "border-l-amber-400" },
  low: { label: "Low", badge: "bg-slate-100 text-slate-600", bar: "border-l-slate-300" },
};

const card = (...c) => h("div", { class: "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" }, ...c);
const sectionTitle = (t, sub) => h("div", { class: "mb-4" },
  h("h3", { class: "text-lg font-semibold text-slate-900" }, t), sub && h("p", { class: "text-sm text-slate-500" }, sub));

function renderResults(d) {
  const root = $("results");
  root.replaceChildren(
    summaryCard(d), comparisonCard(d), flagsCard(d), emailCard(d), feedbackCard(),
    d.warnings.length && h("p", { class: "text-xs text-slate-400" },
      `Notes: ${d.warnings.length} extracted value(s) were dropped because they could not be matched to the quote text.`),
    h("p", { class: "text-xs text-slate-400" }, `Analyzed in ${(d.time_to_results_ms / 1000).toFixed(1)} seconds.`),
  );
}

function stat(label, value, sub) {
  return h("div", { class: "rounded-xl bg-slate-50 p-4" },
    h("div", { class: "text-xs font-medium uppercase tracking-wide text-slate-500" }, label),
    h("div", { class: "mt-1 text-2xl font-bold text-slate-900" }, value),
    sub && h("div", { class: "mt-0.5 text-sm text-slate-500" }, sub));
}

function summaryCard(d) {
  const r = d.recommendation;
  const cost = r.like_for_like_low === r.like_for_like_high
    ? money(r.like_for_like_low) : `${money(r.like_for_like_low)} to ${money(r.like_for_like_high)}`;
  return h("div", { class: "overflow-hidden rounded-2xl border border-indigo-200 bg-white shadow-sm" },
    h("div", { class: "bg-gradient-to-r from-indigo-600 to-violet-600 px-6 py-5 text-white" },
      h("div", { class: "text-xs font-semibold uppercase tracking-wider text-indigo-200" }, "Recommended"),
      h("div", { class: "mt-1 text-3xl font-bold tracking-tight" }, r.vendor)),
    h("div", { class: "p-5 sm:p-6" },
      h("div", { class: "grid gap-3 sm:grid-cols-3" },
        stat("True first-year cost", cost, "Same scope, before tax"),
        stat("Potential savings", money(r.savings_vs_most_expensive),
          r.savings_vs_most_expensive > 0 ? `${r.savings_percent}% less than ${r.most_expensive_vendor}` : "No cheaper gap found"),
        stat("Runner-up", r.runner_up || "None", r.alternatives[0] ? `${money(Math.abs(r.alternatives[0].more_than_recommended))} ${r.alternatives[0].more_than_recommended >= 0 ? "more" : "less"} per year` : "")),
      h("ul", { class: "mt-5 space-y-2 text-slate-700" },
        r.reasoning.map((t) => h("li", { class: "flex gap-2" },
          h("span", { class: "mt-2 h-1.5 w-1.5 flex-none rounded-full bg-indigo-500" }), h("span", {}, t)))),
      r.caveats.length > 0 && h("p", { class: "mt-4 text-xs text-slate-500" }, r.caveats.join(" "))));
}

function valueCell(cost, snippet, missingLabel) {
  if (cost == null) {
    return h("td", { class: "px-4 py-3 text-right align-top" },
      missingLabel ? h("span", { class: "rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800" }, "Not included")
        : h("span", { class: "text-slate-300" }, "None"));
  }
  const src = snippet && h("div", { class: "mt-1.5 hidden rounded-md bg-slate-50 p-2 text-left text-xs italic text-slate-600" }, `"${snippet}"`);
  return h("td", { class: "px-4 py-3 text-right align-top" },
    h("div", { class: "font-medium tabular-nums text-slate-900" }, money(cost)),
    snippet && h("button", {
      type: "button", class: "text-xs text-indigo-600 underline decoration-dotted hover:text-indigo-800",
      onclick: (e) => { src.classList.toggle("hidden"); e.target.textContent = src.classList.contains("hidden") ? "source" : "hide source"; },
    }, "source"),
    src);
}

function comparisonCard(d) {
  const c = d.comparison, vendors = c.vendors.map((v) => v.vendor), rec = d.recommendation.vendor;
  const th = (v) => h("th", { class: `px-4 py-3 text-right text-sm font-semibold ${v === rec ? "bg-indigo-50 text-indigo-900" : "text-slate-700"}` },
    v, v === rec && h("div", { class: "text-[10px] font-semibold uppercase tracking-wide text-indigo-600" }, "Recommended"));
  const group = (t) => h("tr", {}, h("td", { colspan: vendors.length + 1, class: "bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500" }, t));
  const rowsOf = (kind) => c.rows.filter((r) => r.kind === kind).map((r) =>
    h("tr", { class: "border-t border-slate-100" },
      h("td", { class: "px-4 py-3 align-top text-sm text-slate-700" }, r.label),
      vendors.map((v) => valueCell(r.costs[v], r.snippets[v], r.kind === "item" && r.known_concept))));
  const sum = (label, fn, strong) => h("tr", { class: `border-t ${strong ? "border-slate-300 bg-slate-50" : "border-slate-100"}` },
    h("td", { class: `px-4 py-3 text-sm ${strong ? "font-semibold text-slate-900" : "text-slate-600"}` }, label),
    c.vendors.map((v) => h("td", { class: `px-4 py-3 text-right tabular-nums ${strong ? "font-semibold text-slate-900" : "text-slate-600"} ${v.vendor === rec ? "bg-indigo-50/60" : ""}` }, fn(v))));

  const fees = rowsOf("fee");
  return card(
    sectionTitle("Side-by-side comparison", "Annual cost of every line, after converting monthly, yearly and per-visit pricing. Click source to see the quote text."),
    h("div", { class: "-mx-5 overflow-x-auto sm:mx-0" },
      h("table", { class: "w-full min-w-[560px] border-collapse text-left" },
        h("thead", {}, h("tr", {}, h("th", { class: "px-4 py-3 text-sm font-semibold text-slate-500" }, ""), vendors.map(th))),
        h("tbody", {},
          group("Services"), rowsOf("item"),
          fees.length > 0 && group("Fees and extras"), fees,
          sum("First-year total, as quoted", (v) => money(v.year1_total), false),
          sum("Same-scope first-year cost", (v) => v.like_for_like_low === v.like_for_like_high ? money(v.like_for_like_low) : `${money(v.like_for_like_low)} to ${money(v.like_for_like_high)}`, true),
          sum("Year 2 estimate", (v) => money(v.year2_total), false),
          sum("With tax", (v) => v.year1_total_with_tax == null ? "Rate not stated" : money(v.year1_total_with_tax), false)))),
    c.missing.length > 0 && h("p", { class: "mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900" },
      "Same-scope cost adds back items a vendor left out, using the range from the other quotes."));
}

function flagsCard(d) {
  const order = [d.recommendation.vendor, ...d.normalized.map((n) => n.vendor).filter((v) => v !== d.recommendation.vendor)];
  const groups = order.map((v) => [v, d.flags.filter((f) => f.vendor === v)]).filter(([, fs]) => fs.length);
  return card(
    sectionTitle("Risks and hidden costs", "Color shows how much it matters. Tell us if a flag was useful."),
    h("div", { class: "space-y-6" }, groups.map(([vendor, fs]) =>
      h("div", {},
        h("h4", { class: "mb-2 flex items-center gap-2 font-semibold text-slate-800" }, vendor,
          vendor === d.recommendation.vendor && h("span", { class: "rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-indigo-700" }, "Recommended")),
        h("div", { class: "space-y-2" }, fs.map(flagItem))))),
    groups.length === 0 && h("p", { class: "text-slate-500" }, "No risks found."));
}

function flagItem(f) {
  const s = SEV[f.severity];
  const fb = h("div", { class: "flex flex-none items-center gap-1" });
  const vote = (dir, glyph, label) => h("button", {
    type: "button", "aria-label": label, "aria-pressed": "false",
    class: "rounded-md border border-slate-200 px-2 py-1 text-sm text-slate-500 transition hover:bg-slate-50",
    onclick: (e) => {
      const btn = e.currentTarget;
      fb.querySelectorAll("button").forEach((b) => { b.setAttribute("aria-pressed", "false"); b.className = b.className.replace(/ ?(bg-emerald-100|bg-red-100) ?/g, " "); });
      btn.setAttribute("aria-pressed", "true");
      btn.classList.add(dir === "up" ? "bg-emerald-100" : "bg-red-100");
      track("flag_feedback", `${dir}:${f.rule}`);
    },
  }, glyph);
  fb.append(vote("up", "\u{1F44D}", "This flag was useful"), vote("down", "\u{1F44E}", "This flag was not useful"));
  return h("div", { class: `rounded-lg border border-slate-200 border-l-4 ${s.bar} bg-white p-3.5` },
    h("div", { class: "flex items-start justify-between gap-3" },
      h("div", { class: "min-w-0" },
        h("div", { class: "flex flex-wrap items-center gap-2" },
          h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold ${s.badge}` }, s.label),
          h("span", { class: "font-medium text-slate-900" }, f.title),
          f.source === "llm" && h("span", { class: "rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700" }, "AI review")),
        h("p", { class: "mt-1 text-sm text-slate-600" }, f.explanation),
        f.source_snippet && h("blockquote", { class: "mt-2 border-l-2 border-slate-200 pl-3 text-xs italic text-slate-500" }, `"${f.source_snippet}"`)),
      fb));
}

function emailCard(d) {
  const e = d.email;
  const subject = h("input", { type: "text", value: e.subject, "aria-label": "Email subject",
    class: "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" });
  const body = h("textarea", { rows: 14, "aria-label": "Email body",
    class: "mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm leading-relaxed focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" }, e.body);
  const status = h("span", { class: "text-sm text-emerald-600", "aria-live": "polite" });
  const copy = h("button", {
    type: "button", class: "rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700",
    onclick: async () => {
      const text = `Subject: ${subject.value}\n\n${body.value}`;
      try { await navigator.clipboard.writeText(text); }
      catch { body.select(); document.execCommand("copy"); }
      status.textContent = "Copied";
      setTimeout(() => (status.textContent = ""), 2000);
      track("email_copied");
    },
  }, "Copy email");
  return card(
    sectionTitle(`Negotiation email to ${d.recommendation.vendor}`,
      "Polite, specific, and uses your other quotes as leverage without naming them. Edit it before sending."),
    subject, body,
    h("div", { class: "mt-3 flex items-center justify-between" },
      h("div", { class: "flex items-center gap-3" }, copy, status),
      h("span", { class: "text-xs text-slate-400" }, e.source === "llm" ? "Drafted by AI" : "Built from a template")));
}

function feedbackCard() {
  const box = card(sectionTitle("One quick question", "Did this change your choice of vendor?"));
  const done = h("p", { class: "hidden font-medium text-emerald-700" }, "Thanks, that helps.");
  const opt = (label, value) => h("button", {
    type: "button", class: "rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:border-indigo-400 hover:bg-indigo-50",
    onclick: () => { track("choice_changed_answer", value); row.classList.add("hidden"); done.classList.remove("hidden"); },
  }, label);
  const row = h("div", { class: "flex flex-wrap gap-2" },
    opt("Yes, it changed my choice", "changed"), opt("It confirmed my choice", "confirmed"), opt("Not sure yet", "unsure"));
  box.append(row, done);
  return box;
}

// ---------------------------------------------------------------- wiring

function init() {
  $("tab-pdf").onclick = () => setMode("pdf");
  $("tab-text").onclick = () => setMode("text");
  $("add-text").onclick = () => { state.texts.push(""); renderTextBoxes(); };
  $("analyze").onclick = analyzeOwn;
  $("restart").onclick = () => show("view-upload");
  $("proc-retry").onclick = () => show("view-upload");
  document.querySelectorAll(".sample-btn").forEach((b) => (b.onclick = () => analyzeSample(b.dataset.sample)));

  const input = $("file-input"), dz = $("dropzone");
  input.onchange = () => { addFiles([...input.files]); input.value = ""; };
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("dragover"); }));
  dz.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));

  setMode("pdf");
}

init();
