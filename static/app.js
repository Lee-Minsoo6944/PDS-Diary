"use strict";
// Text is always inserted with textContent (never innerHTML), so script-like text shows up as plain text.

const PRI = { 1: "High", 2: "Normal", 3: "Low" };
const SORT_LABEL = { due: "Due date", priority: "Priority (high → low)", estimate: "Estimate", created: "Created", title: "Title" };
const STAT_LABEL = {
  planned: "Planned", done: "Done", delayed: "Overdue", blocked: "Blocked",
  estimated_minutes: "Estimated (min)", actual_minutes: "Actual (min)", diff_minutes: "Difference (actual − est., min)",
};
// Korea Standard Time (UTC+9, no daylight saving). "Asia/Seoul" is the IANA zone for all of South Korea.
const fmtKST = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const S = {
  user: null, plans: [], planId: null, plan: null, tab: "calendar", ev: null, today: "", completeKeys: new Map(), editingPlan: false,
  month: "", day: "", memo: { day: "", timer: null, dirty: false }, dayPlan: { day: "", id: null },
};
const PLAN_COLORS = 8; // matches .pc0 … .pc7 in style.css
const WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// ---------------------------------------------------------------- helpers
const $ = (sel) => document.querySelector(sel);
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function clear(el) { el.replaceChildren(); return el; }
function showUTC(s) { return s ? fmtKST.format(new Date(s)).replace(",", "") : ""; }
function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
function kstLocalInput(date) { // Date → 'YYYY-MM-DDTHH:MM' (Korea time)
  return new Date(date.getTime() + 9 * 3600e3).toISOString().slice(0, 16);
}
function localInputToISO(v) { return v ? v + ":00+09:00" : ""; } // inputs are read as Korea time
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}
async function api(method, url, body) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-PDS"] = "1"; // the server rejects writes without it (blocks cross-site requests)
  const res = await fetch(url, {
    method, headers, credentials: "same-origin",
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !url.startsWith("/api/auth/")) { showAuth("Your session has ended. Please log in again."); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
function formData(form) { return Object.fromEntries(new FormData(form).entries()); }

// ---------------------------------------------------------------- URL hash ↔ state
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  let tab = p.get("tab") || "calendar";
  if (tab === "export") tab = "account"; // old links
  return { plan: Number(p.get("plan")) || null, tab, ev: p.get("ev") || null };
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.planId) p.set("plan", S.planId);
  p.set("tab", S.tab);
  if (S.ev) p.set("ev", S.ev);
  const next = "#" + p.toString();
  if (location.hash !== next) history.pushState(null, "", next);
}
async function go(tab, ev = null) { S.tab = tab; S.ev = ev; writeHash(); await render(); }

// ---------------------------------------------------------------- rendering
async function loadPlans() {
  S.plans = await api("GET", "/api/plans");
  const sel = clear($("#plan-select"));
  for (const p of S.plans) sel.append(h("option", { value: p.id }, `#${planNo(p.id)} ${p.title}`));
  if (!S.plans.find((p) => p.id === S.planId)) S.planId = S.plans.length ? S.plans[S.plans.length - 1].id : null;  // 목록은 오름차순, 처음엔 가장 최근 계획
  sel.value = S.planId ?? "";
}

// Which plan a to-do on day d goes into: plans have no dates, so the plan picked at the top.
function planForDay(_d) {
  return S.plans.find((p) => p.id === S.planId) || S.plans[0] || null;
}
function planById(id) { return S.plans.find((p) => p.id === id) || null; }
// 화면에 보이는 계획 번호: DB 번호(모든 계정이 같이 씀) 대신 내 계획 안에서의 순서 1, 2, 3 …
function planNo(id) { const i = S.plans.findIndex((p) => p.id === id); return i < 0 ? "?" : i + 1; }
// 계획마다 정해진 색: 만든 순서(번호 오름차순)로 8가지 색을 차례로 씀 → 계획 8개까지 겹치지 않음
function planColor(id) {
  const i = S.plans.map((p) => p.id).sort((a, b) => a - b).indexOf(id);
  return `pc${(i < 0 ? id : i) % PLAN_COLORS}`;
}
function planDot(id) {
  const p = planById(id);
  return h("i", { class: `pdot ${planColor(id)}`, title: p ? `Plan #${planNo(p.id)} ${p.title}` : "Plan" });
}
// 달력 위 범례: 계획 이름을 색과 함께, 누르면 그 계획을 고름
function renderLegend() {
  const box = clear($("#plan-legend"));
  box.hidden = S.plans.length < 2;
  for (const p of [...S.plans].sort((a, b) => a.id - b.id))
    box.append(h("button", { type: "button", class: `chip ${planColor(p.id)}${p.id === S.planId ? " on" : ""}`,
      title: `Pick plan #${planNo(p.id)}`, onclick: () => { S.planId = p.id; S.ev = null; writeHash(); render(); } },
      h("i", { class: `pdot ${planColor(p.id)}` }), p.title));
}

async function render() {
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === S.tab);
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== "tab-" + S.tab;
  $("#plan-select").value = S.planId ?? "";
  $("#plan-swatch").className = S.planId ? `pdot big ${planColor(S.planId)}` : "pdot big";
  renderLegend();
  S.plan = S.planId ? await api("GET", `/api/plans/${S.planId}`) : null;
  if (!S.plan && !["plan", "account", "calendar"].includes(S.tab)) {
    // To-dos·Done·Review 는 계획에 딸린 화면이라, 계획이 없으면 Plan 으로 보내고 이유를 알려 줌
    toast("Make a plan first — To-dos, Done and Review show the items of a plan.");
    S.tab = "plan"; return render();
  }
  if (S.tab === "calendar") await renderCalendar();
  if (S.tab === "plan") renderPlan();
  if (S.tab === "todos") await renderTodos();
  if (S.tab === "logs") await renderLogs();
  if (S.tab === "review") await renderReview();
  if (S.tab === "account") $("#acct-name").textContent = S.user ? S.user.username : "";
}

// ---- 1. Plan
function renderPlan() {
  const p = S.plan;
  $("#plan-empty").hidden = !!p;
  const view = clear($("#plan-view"));
  view.hidden = !p;
  const versions = clear($("#plan-versions"));
  if (!p) { if (!S.editingPlan) openPlanForm(null); return; }
  view.append(
    h("h2", {}, `#${planNo(p.id)} ${p.title}`, h("small", { class: "muted" }, `  version ${p.current_version}`)),
    p.carried_from ? h("p", { class: "carried" }, `Improvement carried over from reflection #${p.carried_from.id}: `, h("b", {}, p.carried_from.improvement)) : "",
    h("dl", { class: "grid" },
      h("dt", {}, "Completion criteria"), h("dd", {}, p.success_criteria),
      h("dt", {}, "Created"), h("dd", {}, showUTC(p.created_at)),
    ),
    h("button", { type: "button", onclick: () => openPlanForm(p) }, "Edit plan"),
  );
  const tbl = h("table", { class: "list" },
    h("thead", {}, h("tr", {}, ["Ver.", "Name", "Completion criteria", "Reason", "Saved"].map((x) => h("th", {}, x)))));
  const tb = h("tbody");
  p.versions.forEach((v, i) => {
    const prev = p.versions[i - 1];
    const cell = (k, text) => h("td", { class: prev && prev[k] !== v[k] ? "changed" : null }, text);
    tb.append(h("tr", {},
      h("td", {}, `v${v.version}${v.version === 1 ? " (original)" : ""}`),
      cell("title", v.title), cell("success_criteria", v.success_criteria),
      h("td", {}, v.change_note), h("td", {}, showUTC(v.created_at))));
  });
  tbl.append(tb);
  versions.append(tbl, h("p", { class: "muted small" }, "Highlighted cells changed from the previous version. Every version is kept in full."));
}

function openPlanForm(plan, carried = null) {
  S.editingPlan = true;
  const f = $("#plan-form");
  f.reset(); f.hidden = false; f.dataset.id = plan ? plan.id : "";
  $("#plan-form-title").textContent = plan ? `Edit plan #${planNo(plan.id)}` : "New plan";
  $("#change-note-label").hidden = !plan;
  const c = $("#plan-form-carried");
  c.hidden = !carried;
  f.elements.carried_from_reflection_id.value = carried ? carried.id : "";
  if (carried) c.textContent = `Improvement carried over from reflection #${carried.id}: ${carried.improvement}`;
  if (plan) for (const k of ["title", "success_criteria"]) f.elements[k].value = plan[k];
  if (carried && !plan) f.elements.success_criteria.value = `(Applying improvement) ${carried.improvement}`;
  f.elements.title.focus();
}

// ---- 2. To-dos
function todoQuery() {
  const p = new URLSearchParams({ plan_id: S.planId, sort: $("#f-sort").value, dir: $("#f-dir").value });
  for (const [k, id] of [["q", "#f-q"], ["status", "#f-status"], ["priority", "#f-priority"], ["tag", "#f-tag"]]) {
    if ($(id).value) p.set(k, $(id).value);
  }
  return p;
}

async function evidenceIds(key) {
  const r = await api("GET", `/api/plans/${S.planId}/review?${reviewQuery()}`);
  return r.evidence[key] ? r.evidence[key] : null;
}

async function renderTodos() {
  { const f = $("#todo-form"); if (!f.elements.id.value && !f.elements.due_date.value) f.elements.due_date.value = S.today || ""; }
  const all = await api("GET", `/api/todos?plan_id=${S.planId}`);
  // The tag list is built from all to-dos in the plan
  const tagSel = $("#f-tag"), cur = tagSel.value;
  const tags = [...new Set(all.items.flatMap((t) => t.tags))].sort();
  clear(tagSel).append(h("option", { value: "" }, "All"), ...tags.map((t) => h("option", { value: t }, t)));
  tagSel.value = tags.includes(cur) ? cur : "";

  const q = todoQuery();
  const note = $("#evidence-filter");
  note.hidden = true;
  if (S.ev) {
    const ev = await evidenceIds(S.ev);
    if (ev && ev.todo_ids) {
      q.set("ids", ev.todo_ids.join(",") || "0");
      note.hidden = false;
      clear(note).append(`Showing only the ${ev.todo_ids.length} to-do(s) behind “${STAT_LABEL[S.ev]}” `,
        h("button", { type: "button", class: "ghost small", onclick: () => go("todos") }, "Show all"));
    }
  }
  const data = await api("GET", `/api/todos?${q}`);
  $("#sort-explain").textContent =
    `Sorted by ${SORT_LABEL[data.sort]}, ${data.dir === "asc" ? "ascending" : "descending"}` +
    (data.sort === "due" ? " (no due date goes last)" : "") +
    " · ties broken by ID. Filtering and sorting run on the server.";
  const ul = clear($("#todo-list"));
  if (!data.items.length) ul.append(h("li", { class: "empty" }, "No to-dos match these filters."));
  for (const t of data.items) ul.append(todoItem(t, { showDue: true }));
}

// One checklist row (shared by the To-dos tab and the day page)
function todoItem(t, { showDue = false, showPlan = false } = {}) {
  const done = t.status === "done";
  const meta = [
    `#${t.id}`,
    showPlan ? (planById(t.plan_id)?.title || "Plan") : null,
    showDue ? `Due ${t.due_date || "—"}` : null,
    PRI[t.priority],
    `Est. ${t.estimated_minutes} min`,
    `Actual ${t.actual_minutes} min (${t.log_count} log${t.log_count === 1 ? "" : "s"})`,
  ].filter(Boolean).join(" · ");
  return h("li", { class: [done && "done", "pbar", planColor(t.plan_id)].filter(Boolean).join(" "), id: `todo-${t.id}` },
    h("input", { type: "checkbox", checked: done, title: done ? "Mark as open" : "Mark as done",
      "aria-label": `Complete ${t.title}`, onclick: (e) => { e.preventDefault(); done ? reopen(t.id) : complete(t.id); } }),
    h("div", { class: "body" },
      h("div", { class: "title" }, t.title,
        t.overdue ? h("span", { class: "badge red" }, "Overdue") : null,
        t.blocked ? h("span", { class: "badge amber" }, "Blocked") : null),
      h("div", { class: "meta" }, showPlan ? planDot(t.plan_id) : null, meta, " ", t.tags.map((g) => h("span", { class: "tag" }, "#" + g))),
      t.note ? h("div", { class: "meta" }, t.note) : null),
    h("div", { class: "acts" },
      h("button", { type: "button", class: "link", onclick: () => showTodoFromAnywhere(t.id) }, "Details"),
      h("button", { type: "button", class: "link", onclick: () => editTodoFromAnywhere(t) }, "Edit"),
      h("button", { type: "button", class: "link", onclick: () => addLogFor(t.id) }, "Log"),
      h("button", { type: "button", class: "link", onclick: () => removeTodo(t) }, "Delete")));
}
async function showTodoFromAnywhere(id) { if (S.tab !== "todos") await go("todos"); showTodo(id); }
async function editTodoFromAnywhere(t) { if (S.tab !== "todos") await go("todos"); editTodo(t); }
async function refreshCurrent() {
  if (S.tab === "calendar") await renderCalendar();
  else await renderTodos();
}

async function complete(id) {
  // The same 'complete' intent reuses one key, so repeated clicks are recognised by the server as one request.
  if (!S.completeKeys.has(id)) S.completeKeys.set(id, uuid());
  const key = S.completeKeys.get(id);
  try {
    const r = await api("POST", `/api/todos/${id}/complete`, { idempotency_key: key });
    S.completeKeys.delete(id);
    toast(r.created ? `#${id} marked as done` : `#${id} is already done (no duplicate recorded)`);
  } catch (e) { toast(e.message, true); }
  await refreshCurrent();
}
async function reopen(id) {
  try { await api("POST", `/api/todos/${id}/reopen`); toast(`#${id} reopened`); } catch (e) { toast(e.message, true); }
  await refreshCurrent();
}
async function removeTodo(t) {
  if (!confirm(`Delete to-do #${t.id} “${t.title}”?`)) return;
  try { await api("DELETE", `/api/todos/${t.id}`); toast(`#${t.id} deleted`); } catch (e) { toast(e.message, true); }
  $("#todo-detail").hidden = true;
  await refreshCurrent();
}
function editTodo(t) {
  const f = $("#todo-form");
  f.elements.id.value = t.id;
  for (const k of ["title", "due_date", "priority", "estimated_minutes", "note"]) f.elements[k].value = t[k] ?? "";
  f.elements.tags.value = t.tags.join(", ");
  $("#todo-form-title").textContent = `Edit to-do #${t.id}`;
  $("#todo-submit").textContent = "Save changes";
  $("#todo-cancel").hidden = false;
  f.scrollIntoView({ behavior: "smooth" });
  f.elements.title.focus();
}
function resetTodoForm() {
  const f = $("#todo-form");
  f.reset(); f.elements.id.value = "";
  f.elements.due_date.value = S.today || "";  // 할 일마다 날짜를 정함 — 기본은 오늘
  $("#todo-form-title").textContent = "Add a to-do";
  $("#todo-submit").textContent = "Add";
  $("#todo-cancel").hidden = true;
}
async function showTodo(id) {
  const t = await api("GET", `/api/todos/${id}`);
  const box = clear($("#todo-detail"));
  box.hidden = false;
  box.append(
    h("h3", {}, `To-do #${t.id} · ${t.title}`),
    h("p", { class: "muted" }, `Plan #${planNo(t.plan_id)} ${planById(t.plan_id)?.title || ""} · Due ${t.due_date || "—"} · ${PRI[t.priority]} priority · Est. ${t.estimated_minutes} min · Actual ${t.actual_minutes} min`),
    h("h3", {}, `Work logs (${t.logs.length})`),
    t.logs.length ? h("ul", {}, t.logs.map((w) => h("li", {},
      `#${w.id} ${showUTC(w.started_at)} → ${showUTC(w.ended_at)} · ${w.actual_minutes} min`,
      w.blocker ? h("span", { class: "badge amber" }, "Blocked: " + w.blocker) : null))) : h("p", { class: "muted" }, "None yet."),
    h("h3", {}, "Completions"),
    t.completions.length ? h("ul", {}, t.completions.map((c) => h("li", {},
      `#${c.id} done ${showUTC(c.completed_at)}`, c.undone_at ? ` · reopened ${showUTC(c.undone_at)}` : " · active"))) : h("p", { class: "muted" }, "None yet."),
    h("button", { type: "button", class: "small", onclick: () => addLogFor(t.id) }, "Add a work log for this to-do"));
  box.scrollIntoView({ behavior: "smooth" });
}

// ---- 3. Work log
async function fillLogTodoSelect(selectedId) {
  const all = await api("GET", `/api/todos?plan_id=${S.planId}&sort=created`);
  const sel = clear($("#log-todo"));
  for (const t of all.items) sel.append(h("option", { value: t.id }, `#${t.id} ${t.title}`));
  if (selectedId) sel.value = selectedId;
}
async function renderLogs(selectedTodo) {
  await fillLogTodoSelect(selectedTodo);
  const f = $("#log-form");
  if (!f.elements.started_at.value) {
    const now = new Date();
    f.elements.started_at.value = kstLocalInput(new Date(now - 30 * 60e3));
    f.elements.ended_at.value = kstLocalInput(now);
  }
  const q = new URLSearchParams({ plan_id: S.planId });
  const note = $("#log-evidence-filter");
  note.hidden = true;
  if (S.ev) {
    const ev = await evidenceIds(S.ev);
    if (ev && ev.log_ids) {
      q.set("ids", ev.log_ids.join(",") || "0");
      note.hidden = false;
      clear(note).append(`Showing only the ${ev.log_ids.length} log(s) behind “${STAT_LABEL[S.ev]}” `,
        h("button", { type: "button", class: "ghost small", onclick: () => go("logs") }, "Show all"));
    }
  }
  const logs = await api("GET", `/api/logs?${q}`);
  const ul = clear($("#log-list"));
  if (!logs.length) ul.append(h("li", { class: "muted" }, "No work logs yet."));
  let sum = 0;
  for (const w of logs) {
    sum += w.actual_minutes;
    ul.append(h("li", {},
      h("div", {}, h("b", {}, `#${w.id} `),
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); showTodoFromAnywhere(w.todo_id); } }, `To-do #${w.todo_id} ${w.todo_title}`),
        ` · ${w.actual_minutes} min `, h("span", { class: "muted small" }, `(estimated ${w.todo_estimated_minutes} min)`),
        h("button", { type: "button", class: "link", onclick: () => removeLog(w) }, "Delete")),
      h("div", { class: "when" }, `${showUTC(w.started_at)} → ${showUTC(w.ended_at)}`),
      w.blocker ? h("div", {}, h("span", { class: "badge amber" }, "Blocked"), " ", w.blocker) : null));
  }
  if (logs.length) ul.append(h("li", { class: "sum" }, `Total ${sum} min (${logs.length} log${logs.length === 1 ? "" : "s"})`));
}
async function addLogFor(todoId) { S.tab = "logs"; S.ev = null; writeHash(); await render(); $("#log-todo").value = todoId; $("#log-form").scrollIntoView(); }
async function removeLog(w) {
  if (!confirm(`Delete work log #${w.id}?`)) return;
  try { await api("DELETE", `/api/logs/${w.id}`); toast("Deleted"); } catch (e) { toast(e.message, true); }
  await renderLogs();
}

// ---- 4. Review
function reviewQuery() {
  const p = new URLSearchParams();
  if ($("#r-from").value) p.set("from", $("#r-from").value);
  if ($("#r-to").value) p.set("to", $("#r-to").value);
  return p;
}
// Day-by-day table for the 5-day record: the same rule is applied to every day (see daily.rules).
function renderDaily(d) {
  $("#daily-range").textContent = `${d.from} – ${d.to} · ${d.days} day${d.days === 1 ? "" : "s"}`;
  const t = clear($("#daily"));
  t.append(h("thead", {}, h("tr", {}, ["Date (KST)", "Logs", "Actual (min)", "Done", "Notes"].map((x) => h("th", {}, x)))));
  const tb = h("tbody");
  for (const r of d.rows) {
    const notes = [r.duplicates ? `${r.duplicates} duplicate ignored` : null, r.outliers ? `${r.outliers} over 720 min` : null]
      .filter(Boolean).join(" · ");
    const wd = WEEK[fromYmd(r.date).getUTCDay()].slice(0, 3);
    tb.append(h("tr", { class: r.logs || r.done ? null : "empty" },
      h("td", {}, `${r.date} ${wd}`), h("td", { class: "n" }, r.logs), h("td", { class: "n" }, r.actual_minutes),
      h("td", { class: "n" }, r.done), h("td", { class: "muted" }, notes)));
  }
  tb.append(h("tr", { class: "sum" }, h("td", {}, "Total"), h("td", { class: "n" }, d.total.logs),
    h("td", { class: "n" }, d.total.actual_minutes), h("td", { class: "n" }, d.total.done), h("td", {})));
  tb.append(h("tr", { class: "sum" }, h("td", {}, `Average per day (÷${d.days})`), h("td", {}),
    h("td", { class: "n" }, d.average.actual_minutes.toFixed(1)), h("td", { class: "n" }, d.average.done.toFixed(1)), h("td", {})));
  t.append(tb);
  const R = d.rules;
  $("#daily-rules").textContent = `Rules: ${R.date}; ${R.missing}; ${R.duplicates}; ${R.outliers}; ${R.rounding}; weeks start on ${R.week_starts}.` +
    " Set “Due from / to” to choose the days.";
}

async function renderReview() {
  const r = await api("GET", `/api/plans/${S.planId}/review?${reviewQuery()}`);
  $("#review-meta").textContent = `#${planNo(r.plan_id)} ${r.plan_title} · Today (KST) ${r.today_kst}` +
    (r.period.from || r.period.to ? ` · Due ${r.period.from || "start"} – ${r.period.to || "end"}` : " · All dates");
  const box = clear($("#stats"));
  for (const [k, label] of Object.entries(STAT_LABEL)) {
    const ev = r.evidence[k];
    const target = ev.log_ids && !ev.todo_ids ? "logs" : "todos";
    const v = r.stats[k];
    box.append(h("button", { type: "button", class: "stat" + (k === "diff_minutes" ? (v > 0 ? " over" : v < 0 ? " under" : "") : ""),
      title: `Click to see the ${target === "logs" ? "work logs" : "to-dos"} behind this number`, onclick: () => go(target, k) },
      h("span", { class: "num" }, k === "diff_minutes" && v > 0 ? "+" + v : v), h("span", { class: "lbl" }, label)));
  }
  renderDaily(r.daily);
  const list = clear($("#reflections"));
  if (!S.plan.reflections.length) list.append(h("p", { class: "muted" }, "No reflections yet."));
  for (const rf of S.plan.reflections) {
    const s = rf.stats;
    list.append(h("div", { class: "reflection" },
      h("p", {}, h("b", {}, `#${rf.id} `), showUTC(rf.created_at),
        h("span", { class: "muted" }, ` · planned ${s.planned} / done ${s.done} / overdue ${s.delayed} / blocked ${s.blocked} / est. ${s.estimated_minutes} min / actual ${s.actual_minutes} min / diff ${s.diff_minutes} min`)),
      rf.note ? h("p", {}, rf.note) : null,
      h("p", { class: "carried" }, "Improve: ", h("b", {}, rf.improvement)),
      rf.carried_to_plan_ids.length
        ? h("p", {}, "Carried into plan: ", rf.carried_to_plan_ids.map((id) => h("a", { href: `#plan=${id}&tab=plan` }, `#${id} `)))
        : h("button", { type: "button", class: "small", onclick: () => { S.tab = "plan"; S.ev = null; writeHash(); render().then(() => openPlanForm(null, rf)); } },
          "Start the next plan with this improvement")));
  }
}

// ---- Calendar (left page) + one day (right page)
const ymd = (d) => d.toISOString().slice(0, 10);                 // UTC date object → 'YYYY-MM-DD'
const fromYmd = (s) => new Date(s + "T00:00:00Z");
const addDays = (s, n) => ymd(new Date(fromYmd(s).getTime() + n * 864e5));
function monthRange(month) { // 'YYYY-MM' → first/last day shown (weeks start on Sunday)
  const first = fromYmd(month + "-01");
  const start = addDays(ymd(first), -first.getUTCDay());
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
  const end = addDays(ymd(last), 6 - last.getUTCDay());
  return { start, end };
}
function shiftMonth(month, n) {
  const d = fromYmd(month + "-01");
  return ymd(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1))).slice(0, 7);
}

async function renderCalendar() {
  const [y, m] = S.month.split("-").map(Number);
  $("#cal-title").textContent = `${MONTHS[m - 1]} ${y}`;
  const { start, end } = monthRange(S.month);
  const [todos, notes] = await Promise.all([
    api("GET", `/api/todos?due_from=${start}&due_to=${end}&sort=priority`),
    api("GET", `/api/notes?from=${start}&to=${end}`),
  ]);
  const byDay = {};
  for (const t of todos.items) (byDay[t.due_date] ||= []).push(t);
  const noteDays = new Set(notes);
  const grid = clear($("#cal-grid"));
  for (let d = start; d <= end; d = addDays(d, 1)) {
    const wd = fromYmd(d).getUTCDay();
    const items = byDay[d] || [];
    const cls = ["cell", d.slice(0, 7) !== S.month && "other", wd === 0 && "sun", wd === 6 && "sat",
      d === S.today && "today", d === S.day && "selected"].filter(Boolean).join(" ");
    const list = h("ul", { class: "mini" });
    const SHOW = 4;
    for (const t of items.slice(0, SHOW)) {
      const done = t.status === "done";
      list.append(h("li", { class: [done ? "done" : t.overdue ? "overdue" : null, "ptint", planColor(t.plan_id)].filter(Boolean).join(" "),
        title: `#${t.id} ${t.title} (${planById(t.plan_id)?.title || "plan"})` },
        h("input", { type: "checkbox", checked: done, "aria-label": `Complete ${t.title}`,
          onclick: (e) => { e.stopPropagation(); e.preventDefault(); done ? reopen(t.id) : complete(t.id); } }),
        h("span", {}, t.title)));
    }
    if (items.length > SHOW) list.append(h("li", { class: "more" }, `+${items.length - SHOW} more`));
    const cell = h("div", { class: cls, "data-date": d, onclick: () => selectDay(d) },
      h("div", { class: "dnum" }, h("b", {}, Number(d.slice(8))), noteDays.has(d) ? h("i", { class: "memo-dot", title: "Has notes" }) : null),
      h("button", { type: "button", class: "add ghost", title: "Add a to-do on this day", "aria-label": `Add a to-do on ${d}`,
        onclick: (e) => { e.stopPropagation(); openCellInput(cell, d); } }, "+"),
      list);
    grid.append(cell);
  }
  await renderDay();
}

function openCellInput(cell, d) {
  const plan = planForDay(d);
  if (!plan) { toast("Create a plan first with “+ New plan”", true); return; }
  if (cell.querySelector(".cell-input")) return cell.querySelector(".cell-input").focus();
  const input = h("input", { class: "cell-input", maxlength: 200,
    placeholder: S.plans.length > 1 ? `To-do → ${plan.title}` : "To-do + Enter",
    title: `Goes into plan #${planNo(plan.id)} ${plan.title}. To pick another plan, use the form on the right page.` });
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") return input.remove();
    if (e.key !== "Enter" || e.isComposing) return;
    e.preventDefault();
    const title = input.value.trim();
    if (!title) return;
    input.disabled = true;
    try {
      await api("POST", "/api/todos", { plan_id: plan.id, title, due_date: d, priority: 2, estimated_minutes: 30 });
      toast(`Added to “${plan.title}” on ${d} (30 min estimate — edit it on the right page)`);
      S.day = d;
      await renderCalendar();
      const again = document.querySelector(`.cell[data-date="${d}"]`);
      if (again) openCellInput(again, d); // keep adding
    } catch (err) { toast(err.message, true); input.disabled = false; }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (!input.disabled) input.remove(); }, 150));
  cell.append(input);
  input.focus();
}

async function selectDay(d) {
  await flushMemo();
  S.day = d;
  if (d.slice(0, 7) !== S.month) { S.month = d.slice(0, 7); return renderCalendar(); }
  for (const c of document.querySelectorAll(".cell")) c.classList.toggle("selected", c.dataset.date === d);
  await renderDay();
}

async function renderDay() {
  const d = S.day;
  const wd = WEEK[fromYmd(d).getUTCDay()];
  $("#day-title").textContent = `${wd}, ${MONTHS[Number(d.slice(5, 7)) - 1]} ${Number(d.slice(8))}`;
  const data = await api("GET", `/api/todos?due_from=${d}&due_to=${d}&sort=priority`);
  const doneN = data.items.filter((t) => t.status === "done").length;
  $("#day-sub").textContent = `${d === S.today ? "Today · " : ""}${doneN} of ${data.items.length} done`;
  const ul = clear($("#day-todos"));
  if (!data.items.length) ul.append(h("li", { class: "empty" }, "Nothing due this day. Add a to-do below."));
  for (const t of data.items) ul.append(todoItem(t, { showPlan: S.plans.length > 1 }));
  // Plan picker: default to the plan covering this day; keep the user's pick while they stay on the same day.
  const sel = clear($("#day-plan"));
  for (const p of S.plans) sel.append(h("option", { value: p.id }, `#${planNo(p.id)} ${p.title}`));
  const keep = S.dayPlan.day === d && planById(S.dayPlan.id);
  const def = keep || planForDay(d);
  sel.value = def ? def.id : "";
  sel.hidden = S.plans.length < 2;
  $("#day-add").querySelector("button").disabled = !S.plans.length;
  if (S.memo.day !== d) {
    const note = await api("GET", `/api/notes/${d}`);
    S.memo.day = d; S.memo.dirty = false;
    $("#memo").value = note.body;
    $("#memo-status").textContent = note.updated_at ? `saved ${showUTC(note.updated_at).slice(-5)}` : "";
  }
}

async function saveMemo() {
  clearTimeout(S.memo.timer);
  if (!S.memo.dirty || !S.user) return;
  const day = S.memo.day, body = $("#memo").value;
  S.memo.dirty = false;
  $("#memo-status").textContent = "saving…";
  try {
    const r = await api("PUT", `/api/notes/${day}`, { body });
    if (S.memo.day === day) $("#memo-status").textContent = `saved ${showUTC(r.updated_at).slice(-5)}`;
    const cell = document.querySelector(`.cell[data-date="${day}"] .dnum`);
    if (cell) { // update the note dot in the cell
      const dot = cell.querySelector(".memo-dot");
      if (body.trim() && !dot) cell.append(h("i", { class: "memo-dot", title: "Has notes" }));
      if (!body.trim() && dot) dot.remove();
    }
  } catch (e) { S.memo.dirty = true; $("#memo-status").textContent = "save failed"; toast(e.message, true); }
}
function flushMemo() { return saveMemo(); }

// ---------------------------------------------------------------- events
function bind() {
  $("#cal-prev").addEventListener("click", async () => { await flushMemo(); S.month = shiftMonth(S.month, -1); renderCalendar(); });
  $("#cal-next").addEventListener("click", async () => { await flushMemo(); S.month = shiftMonth(S.month, 1); renderCalendar(); });
  $("#cal-today").addEventListener("click", () => selectDay(S.today).then(() => { if (S.month !== S.today.slice(0, 7)) { S.month = S.today.slice(0, 7); renderCalendar(); } }));
  $("#memo").addEventListener("input", () => {
    S.memo.dirty = true; $("#memo-status").textContent = "typing…";
    clearTimeout(S.memo.timer); S.memo.timer = setTimeout(saveMemo, 800);
  });
  $("#memo").addEventListener("blur", saveMemo);
  $("#day-plan").addEventListener("change", (e) => { S.dayPlan = { day: S.day, id: Number(e.target.value) }; });
  window.addEventListener("beforeunload", (e) => { if (S.user && S.memo.dirty) { saveMemo(); e.preventDefault(); } });
  $("#day-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f);
    const plan = planById(Number(d.plan_id)) || planForDay(S.day);
    if (!plan) return toast("Create a plan first with “+ New plan”", true);
    try {
      await api("POST", "/api/todos", { plan_id: plan.id, title: d.title, priority: d.priority,
        estimated_minutes: d.estimated_minutes || 0, due_date: S.day });
      S.dayPlan = { day: S.day, id: plan.id };
      f.elements.title.value = "";
      toast(S.plans.length > 1 ? `To-do added to “${plan.title}”` : "To-do added");
      await renderCalendar(); $("#day-add").elements.title.focus();
    } catch (err) { toast(err.message, true); }
  });
  $("#tabs").addEventListener("click", async (e) => { const t = e.target.closest("button"); if (t) { await flushMemo(); go(t.dataset.tab); } });
  $("#plan-select").addEventListener("change", (e) => { S.planId = Number(e.target.value); S.ev = null; writeHash(); render(); });
  $("#btn-new-plan").addEventListener("click", () => { S.tab = "plan"; writeHash(); render().then(() => openPlanForm(null)); });
  $("#plan-form-cancel").addEventListener("click", () => { $("#plan-form").hidden = true; S.editingPlan = false; });
  $("#plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f), id = f.dataset.id;
    try {
      const p = id ? await api("PUT", `/api/plans/${id}`, d) : await api("POST", "/api/plans", d);
      f.hidden = true; S.editingPlan = false; S.planId = p.id;
      toast(id ? "Plan updated. The previous version is kept in the history." : "Plan saved.");
      await loadPlans(); writeHash(); await render();
    } catch (err) { toast(err.message, true); }
  });

  $("#todo-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f), id = d.id;
    delete d.id;
    d.plan_id = S.planId;
    try {
      if (id) await api("PUT", `/api/todos/${id}`, d); else await api("POST", "/api/todos", d);
      toast(id ? `#${id} updated` : "To-do added");
      resetTodoForm(); await renderTodos();
    } catch (err) { toast(err.message, true); }
  });
  $("#todo-cancel").addEventListener("click", resetTodoForm);
  let timer;
  $("#f-q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(renderTodos, 250); });
  for (const id of ["#f-status", "#f-priority", "#f-tag", "#f-sort", "#f-dir"]) $(id).addEventListener("change", renderTodos);

  $("#log-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f);
    const body = { started_at: localInputToISO(d.started_at), ended_at: localInputToISO(d.ended_at), actual_minutes: d.actual_minutes, blocker: d.blocker };
    try {
      await api("POST", `/api/todos/${d.todo_id}/logs`, body);
      toast("Work log saved (plan values unchanged)");
      f.elements.actual_minutes.value = ""; f.elements.blocker.value = "";
      await renderLogs(d.todo_id);
    } catch (err) { toast(err.message, true); }
  });

  for (const id of ["#r-from", "#r-to"]) $(id).addEventListener("change", renderReview);
  $("#r-clear").addEventListener("click", () => { $("#r-from").value = ""; $("#r-to").value = ""; renderReview(); });
  $("#reflect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    Object.assign(d, Object.fromEntries(reviewQuery()));
    try {
      await api("POST", `/api/plans/${S.planId}/reflections`, d);
      e.target.reset(); toast("Reflection saved"); await render();
    } catch (err) { toast(err.message, true); }
  });

  const fromHash = async () => {
    if (!S.user) return;
    const st = readHash();
    if ((st.plan || S.planId) === S.planId && st.tab === S.tab && st.ev === S.ev) return; // already on that screen
    if (st.plan) S.planId = st.plan;
    S.tab = st.tab; S.ev = st.ev;
    await render();
  };
  window.addEventListener("popstate", fromHash);
  window.addEventListener("hashchange", fromHash);
}

// ---------------------------------------------------------------- sign in / sign up / log out
const AUTH = { mode: "login" };
function setAuthMode(mode) {
  AUTH.mode = mode;
  const signup = mode === "signup";
  $("#auth-title").textContent = signup ? "Create an account" : "Log in";
  $("#auth-submit").textContent = signup ? "Sign up" : "Log in";
  $("#auth-tab-login").classList.toggle("on", !signup);
  $("#auth-tab-signup").classList.toggle("on", signup);
  $("#auth-hint").hidden = !signup;
  $("#auth-form").elements.password.autocomplete = signup ? "new-password" : "current-password";
  $("#auth-error").hidden = true;
}
function showAuth(message = "") {
  S.user = null; S.plans = []; S.plan = null; S.planId = null;
  $("#diary").hidden = true; $("#planbar").hidden = true; $("#auth").hidden = false;
  clear($("#cal-grid")); clear($("#day-todos")); clear($("#todo-list")); clear($("#log-list")); $("#memo").value = "";
  const err = $("#auth-error");
  err.textContent = message; err.hidden = !message;
  $("#auth-form").elements.password.value = "";
  $("#auth-form").elements.username.focus();
}
async function enterDiary(user) {
  S.user = user;
  $("#auth").hidden = true; $("#diary").hidden = false; $("#planbar").hidden = false;
  $("#who-name").textContent = user.username;
  const st = readHash();
  S.planId = st.plan; S.tab = st.tab; S.ev = st.ev;
  S.memo.day = ""; S.day = S.today; S.month = S.today.slice(0, 7);
  await loadPlans();
  history.replaceState(null, "", location.pathname + location.search);
  writeHash();
  await render();
}
function bindAuth() {
  $("#auth-tab-login").addEventListener("click", () => setAuthMode("login"));
  $("#auth-tab-signup").addEventListener("click", () => setAuthMode("signup"));
  $("#auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f);
    const btn = $("#auth-submit");
    btn.disabled = true;
    try {
      const r = await api("POST", AUTH.mode === "signup" ? "/api/auth/signup" : "/api/auth/login",
        { username: d.username, password: d.password });
      f.elements.password.value = "";
      if (AUTH.mode === "signup") toast(`Welcome, ${r.user.username}! Create your first plan to get started.`);
      await enterDiary(r.user);
    } catch (err) {
      const box = $("#auth-error"); box.textContent = err.message; box.hidden = false;
      f.elements.password.value = "";
    } finally { btn.disabled = false; }
  });
  $("#btn-logout").addEventListener("click", async () => {
    await flushMemo();
    try { await api("POST", "/api/auth/logout"); } catch (e) { /* already logged out */ }
    history.replaceState(null, "", location.pathname);
    showAuth(); setAuthMode("login");
  });
  $("#pw-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f);
    try {
      await api("POST", "/api/auth/password", d);
      f.reset(); toast("Password changed. Other browsers have been logged out.");
    } catch (err) { toast(err.message, true); }
  });
  $("#del-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f);
    if (!confirm(`Delete the account “${S.user.username}” and ALL of its data? This cannot be undone.`)) return;
    try {
      await api("POST", "/api/auth/delete-account", d);
      f.reset(); history.replaceState(null, "", location.pathname);
      showAuth("Your account and all of its data were deleted."); setAuthMode("login");
    } catch (err) { toast(err.message, true); }
  });
}

async function start() {
  bind(); bindAuth();
  const meta = await api("GET", "/api/meta");
  $("#today").textContent = `Today (KST) · ${meta.today_kst}`;
  S.today = meta.today_kst; S.day = S.today; S.month = S.today.slice(0, 7);
  let me = null;
  try { me = (await api("GET", "/api/auth/me")).user; } catch (e) { me = null; }
  if (me) await enterDiary(me);
  else { setAuthMode("login"); showAuth(); }
}
document.addEventListener("DOMContentLoaded", () => start().catch((e) => toast(e.message, true)));
