"use strict";
// 화면에 글자를 넣을 때는 textContent 만 씁니다(innerHTML 금지) → 스크립트 모양 글자도 글자 그대로 보입니다.

const PRI = { 1: "높음", 2: "보통", 3: "낮음" };
const SORT_LABEL = { due: "마감일", priority: "우선순위(높음→낮음)", estimate: "예상 시간", created: "만든 시각", title: "제목" };
const STAT_LABEL = {
  planned: "계획 수", done: "완료 수", delayed: "지연 수", blocked: "막힘 수",
  estimated_minutes: "예상 시간(분)", actual_minutes: "실제 시간(분)", diff_minutes: "차이(실제−예상, 분)",
};
const fmtKST = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});

const S = { plans: [], planId: null, plan: null, tab: "plan", ev: null, today: "", completeKeys: new Map(), editingPlan: false };

// ---------------------------------------------------------------- 도구
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
function showUTC(s) { return s ? fmtKST.format(new Date(s)) : ""; }
function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
function kstLocalInput(date) { // Date → 'YYYY-MM-DDTHH:MM' (서울 시간)
  return new Date(date.getTime() + 9 * 3600e3).toISOString().slice(0, 16);
}
function localInputToISO(v) { return v ? v + ":00+09:00" : ""; } // 입력값은 서울 시간으로 해석
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}
async function api(method, url, body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `요청 실패 (${res.status})`);
  return data;
}
function formData(form) { return Object.fromEntries(new FormData(form).entries()); }

// ---------------------------------------------------------------- 주소(#) ↔ 상태
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  return { plan: Number(p.get("plan")) || null, tab: p.get("tab") || "plan", ev: p.get("ev") || null };
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

// ---------------------------------------------------------------- 그리기
async function loadPlans() {
  S.plans = await api("GET", "/api/plans");
  const sel = clear($("#plan-select"));
  for (const p of S.plans) sel.append(h("option", { value: p.id }, `#${p.id} ${p.title} (${p.start_date}~${p.end_date})`));
  if (!S.plans.find((p) => p.id === S.planId)) S.planId = S.plans.length ? S.plans[0].id : null;
  sel.value = S.planId ?? "";
}

async function render() {
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === S.tab);
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== "tab-" + S.tab;
  $("#plan-select").value = S.planId ?? "";
  S.plan = S.planId ? await api("GET", `/api/plans/${S.planId}`) : null;
  if (!S.plan && S.tab !== "plan" && S.tab !== "export") { S.tab = "plan"; return render(); }
  if (S.tab === "plan") renderPlan();
  if (S.tab === "todos") await renderTodos();
  if (S.tab === "logs") await renderLogs();
  if (S.tab === "review") await renderReview();
}

// ---- 1. 계획
function renderPlan() {
  const p = S.plan;
  $("#plan-empty").hidden = !!p;
  const view = clear($("#plan-view"));
  view.hidden = !p;
  const versions = clear($("#plan-versions"));
  if (!p) { if (!S.editingPlan) openPlanForm(null); return; }
  view.append(
    h("h2", {}, `#${p.id} ${p.title}`, h("small", { class: "muted" }, ` (현재 ${p.current_version}판)`)),
    p.carried_from ? h("p", { class: "carried" }, `지난 돌아보기(#${p.carried_from.id})에서 넘어온 고칠 점: `, h("b", {}, p.carried_from.improvement)) : null,
    h("dl", { class: "grid" },
      h("dt", {}, "기간"), h("dd", {}, `${p.start_date} ~ ${p.end_date}`),
      h("dt", {}, "우선순위"), h("dd", {}, PRI[p.priority]),
      h("dt", {}, "성공 기준"), h("dd", {}, p.success_criteria),
      h("dt", {}, "예상 시간"), h("dd", {}, `${p.estimated_minutes}분`),
      h("dt", {}, "만든 시각"), h("dd", {}, showUTC(p.created_at)),
    ),
    h("button", { type: "button", onclick: () => openPlanForm(p) }, "계획 고치기"),
  );
  const cols = ["title", "start_date", "end_date", "priority", "success_criteria", "estimated_minutes"];
  const tbl = h("table", { class: "list" },
    h("thead", {}, h("tr", {}, ["판", "이름", "기간", "우선순위", "성공 기준", "예상(분)", "고친 이유", "저장 시각"].map((x) => h("th", {}, x)))));
  const tb = h("tbody");
  p.versions.forEach((v, i) => {
    const prev = p.versions[i - 1];
    const cell = (k, text) => h("td", { class: prev && prev[k] !== v[k] ? "changed" : null }, text);
    tb.append(h("tr", {},
      h("td", {}, `${v.version}판${v.version === 1 ? " (처음 계획)" : ""}`),
      cell("title", v.title), h("td", { class: prev && (prev.start_date !== v.start_date || prev.end_date !== v.end_date) ? "changed" : null }, `${v.start_date}~${v.end_date}`),
      cell("priority", PRI[v.priority]), cell("success_criteria", v.success_criteria), cell("estimated_minutes", v.estimated_minutes),
      h("td", {}, v.change_note), h("td", {}, showUTC(v.created_at))));
  });
  tbl.append(tb);
  versions.append(tbl, h("p", { class: "muted" }, "색칠된 칸은 바로 앞 판과 달라진 값입니다. ", cols.length, "개 항목을 판마다 통째로 남깁니다."));
}

function openPlanForm(plan, carried = null) {
  S.editingPlan = true;
  const f = $("#plan-form");
  f.reset(); f.hidden = false; f.dataset.id = plan ? plan.id : "";
  $("#plan-form-title").textContent = plan ? `계획 #${plan.id} 고치기` : "새 계획";
  $("#change-note-label").hidden = !plan;
  const c = $("#plan-form-carried");
  c.hidden = !carried;
  f.elements.carried_from_reflection_id.value = carried ? carried.id : "";
  if (carried) c.textContent = `돌아보기 #${carried.id}에서 넘어오는 고칠 점: ${carried.improvement}`;
  if (plan) for (const k of ["title", "start_date", "end_date", "priority", "estimated_minutes", "success_criteria"]) f.elements[k].value = plan[k];
  if (carried && !plan) f.elements.success_criteria.value = `(고칠 점 반영) ${carried.improvement}`;
  f.elements.title.focus();
}

// ---- 2. 할 일
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
  const all = await api("GET", `/api/todos?plan_id=${S.planId}`);
  // 태그 목록과 실행 기록 고르기 상자는 전체 할 일 기준
  const tagSel = $("#f-tag"), cur = tagSel.value;
  const tags = [...new Set(all.items.flatMap((t) => t.tags))].sort();
  clear(tagSel).append(h("option", { value: "" }, "전체"), ...tags.map((t) => h("option", { value: t }, t)));
  tagSel.value = tags.includes(cur) ? cur : "";

  const q = todoQuery();
  const note = $("#evidence-filter");
  note.hidden = true;
  if (S.ev) {
    const ev = await evidenceIds(S.ev);
    if (ev && ev.todo_ids) {
      q.set("ids", ev.todo_ids.join(",") || "0");
      note.hidden = false;
      clear(note).append(`돌아보기 「${STAT_LABEL[S.ev]}」의 근거 할 일 ${ev.todo_ids.length}건만 보는 중 `,
        h("button", { type: "button", class: "ghost small", onclick: () => go("todos") }, "전체 보기"));
    }
  }
  const data = await api("GET", `/api/todos?${q}`);
  $("#sort-explain").textContent =
    `정렬 기준: ${SORT_LABEL[data.sort]} ${data.dir === "asc" ? "오름차순" : "내림차순"}` +
    (data.sort === "due" ? " (마감일 없는 할 일은 맨 뒤)" : "") +
    " → 값이 같으면 ID 오름차순. 거르기와 정렬은 서버에서 합니다.";
  const tb = clear($("#todo-list"));
  if (!data.items.length) tb.append(h("tr", {}, h("td", { colspan: 9, class: "muted" }, "조건에 맞는 할 일이 없습니다.")));
  for (const t of data.items) {
    tb.append(h("tr", { class: t.status === "done" ? "done" : null, id: `todo-${t.id}` },
      h("td", {}, t.id),
      h("td", {}, t.status === "done" ? "완료" : "진행 중", t.overdue ? h("span", { class: "badge red" }, "지연") : null,
        t.blocked ? h("span", { class: "badge amber" }, "막힘") : null),
      h("td", {}, h("a", { href: "#", onclick: (e) => { e.preventDefault(); showTodo(t.id); } }, t.title),
        t.note ? h("div", { class: "muted small" }, t.note) : null),
      h("td", {}, t.due_date || "—"), h("td", {}, PRI[t.priority]),
      h("td", {}, `${t.estimated_minutes}분`), h("td", {}, `${t.actual_minutes}분 (${t.log_count}건)`),
      h("td", {}, t.tags.map((g) => h("span", { class: "tag" }, "#" + g))),
      h("td", { class: "actions" },
        t.status === "done"
          ? h("button", { type: "button", class: "ghost small", onclick: () => reopen(t.id) }, "되돌리기")
          : h("button", { type: "button", class: "small", onclick: () => complete(t.id) }, "완료"),
        h("button", { type: "button", class: "ghost small", onclick: () => editTodo(t) }, "고치기"),
        h("button", { type: "button", class: "ghost small", onclick: () => addLogFor(t.id) }, "기록"),
        h("button", { type: "button", class: "ghost small danger", onclick: () => removeTodo(t) }, "지우기"))));
  }
}

async function complete(id) {
  // 같은 '완료 의도'에는 같은 키를 씁니다. 연달아 눌러도 서버가 같은 요청으로 알아봅니다.
  if (!S.completeKeys.has(id)) S.completeKeys.set(id, uuid());
  const key = S.completeKeys.get(id);
  try {
    const r = await api("POST", `/api/todos/${id}/complete`, { idempotency_key: key });
    S.completeKeys.delete(id);
    toast(r.created ? `#${id} 완료로 바꿨습니다` : `#${id}는 이미 완료 상태입니다 (중복 기록 없음)`);
  } catch (e) { toast(e.message, true); }
  await renderTodos();
}
async function reopen(id) {
  try { await api("POST", `/api/todos/${id}/reopen`); toast(`#${id} 진행 중으로 되돌렸습니다`); } catch (e) { toast(e.message, true); }
  await renderTodos();
}
async function removeTodo(t) {
  if (!confirm(`할 일 #${t.id} 「${t.title}」을(를) 지울까요?`)) return;
  try { await api("DELETE", `/api/todos/${t.id}`); toast(`#${t.id} 지웠습니다`); } catch (e) { toast(e.message, true); }
  $("#todo-detail").hidden = true;
  await renderTodos();
}
function editTodo(t) {
  const f = $("#todo-form");
  f.elements.id.value = t.id;
  for (const k of ["title", "due_date", "priority", "estimated_minutes", "note"]) f.elements[k].value = t[k] ?? "";
  f.elements.tags.value = t.tags.join(", ");
  $("#todo-form-title").textContent = `할 일 #${t.id} 고치기`;
  $("#todo-submit").textContent = "고친 내용 저장";
  $("#todo-cancel").hidden = false;
  f.scrollIntoView({ behavior: "smooth" });
  f.elements.title.focus();
}
function resetTodoForm() {
  const f = $("#todo-form");
  f.reset(); f.elements.id.value = "";
  $("#todo-form-title").textContent = "할 일 추가";
  $("#todo-submit").textContent = "추가";
  $("#todo-cancel").hidden = true;
}
async function showTodo(id) {
  const t = await api("GET", `/api/todos/${id}`);
  const box = clear($("#todo-detail"));
  box.hidden = false;
  box.append(
    h("h2", {}, `할 일 #${t.id} ${t.title}`),
    h("p", { class: "muted" }, `계획 #${t.plan_id} · 마감 ${t.due_date || "없음"} · 우선순위 ${PRI[t.priority]} · 예상 ${t.estimated_minutes}분 · 실제 ${t.actual_minutes}분`),
    h("h3", {}, `이 할 일에 붙은 실행 기록 (${t.logs.length}건)`),
    t.logs.length ? h("ul", {}, t.logs.map((w) => h("li", {},
      `#${w.id} ${showUTC(w.started_at)} → ${showUTC(w.ended_at)} · ${w.actual_minutes}분`,
      w.blocker ? h("span", { class: "badge amber" }, "막힘: " + w.blocker) : null))) : h("p", { class: "muted" }, "아직 없습니다."),
    h("h3", {}, "완료 기록"),
    t.completions.length ? h("ul", {}, t.completions.map((c) => h("li", {},
      `#${c.id} 완료 ${showUTC(c.completed_at)}`, c.undone_at ? ` · 되돌림 ${showUTC(c.undone_at)}` : " · 현재 유효"))) : h("p", { class: "muted" }, "아직 없습니다."),
    h("button", { type: "button", class: "small", onclick: () => addLogFor(t.id) }, "이 할 일에 실행 기록 추가"));
  box.scrollIntoView({ behavior: "smooth" });
}

// ---- 3. 실행 기록
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
      clear(note).append(`돌아보기 「${STAT_LABEL[S.ev]}」의 근거 실행 기록 ${ev.log_ids.length}건만 보는 중 `,
        h("button", { type: "button", class: "ghost small", onclick: () => go("logs") }, "전체 보기"));
    }
  }
  const logs = await api("GET", `/api/logs?${q}`);
  const tb = clear($("#log-list"));
  if (!logs.length) tb.append(h("tr", {}, h("td", { colspan: 7, class: "muted" }, "실행 기록이 없습니다.")));
  let sum = 0;
  for (const w of logs) {
    sum += w.actual_minutes;
    tb.append(h("tr", {},
      h("td", {}, w.id),
      h("td", {}, h("a", { href: "#", onclick: async (e) => { e.preventDefault(); await go("todos"); showTodo(w.todo_id); } }, `#${w.todo_id} ${w.todo_title}`),
        h("div", { class: "muted small" }, `할 일 예상 ${w.todo_estimated_minutes}분`)),
      h("td", {}, showUTC(w.started_at)), h("td", {}, showUTC(w.ended_at)), h("td", {}, w.actual_minutes),
      h("td", {}, w.blocker || "—"),
      h("td", {}, h("button", { type: "button", class: "ghost small danger", onclick: () => removeLog(w) }, "지우기"))));
  }
  if (logs.length) tb.append(h("tr", { class: "sum" }, h("td", { colspan: 4 }, "합계"), h("td", {}, sum), h("td", { colspan: 2 })));
}
async function addLogFor(todoId) { S.tab = "logs"; S.ev = null; writeHash(); await render(); $("#log-todo").value = todoId; $("#log-form").scrollIntoView(); }
async function removeLog(w) {
  if (!confirm(`실행 기록 #${w.id}을(를) 지울까요?`)) return;
  try { await api("DELETE", `/api/logs/${w.id}`); toast("지웠습니다"); } catch (e) { toast(e.message, true); }
  await renderLogs();
}

// ---- 4. 돌아보기
function reviewQuery() {
  const p = new URLSearchParams();
  if ($("#r-from").value) p.set("from", $("#r-from").value);
  if ($("#r-to").value) p.set("to", $("#r-to").value);
  return p;
}
async function renderReview() {
  const r = await api("GET", `/api/plans/${S.planId}/review?${reviewQuery()}`);
  $("#review-meta").textContent = `#${r.plan_id} ${r.plan_title} · 서울 기준 오늘 ${r.today_kst}` +
    (r.period.from || r.period.to ? ` · 마감일 ${r.period.from || "처음"}~${r.period.to || "끝"}` : " · 전체 기간");
  const box = clear($("#stats"));
  for (const [k, label] of Object.entries(STAT_LABEL)) {
    const ev = r.evidence[k];
    const target = ev.log_ids && !ev.todo_ids ? "logs" : "todos";
    const v = r.stats[k];
    box.append(h("button", { type: "button", class: "stat" + (k === "diff_minutes" ? (v > 0 ? " over" : v < 0 ? " under" : "") : ""),
      title: `눌러서 근거 ${target === "logs" ? "실행 기록" : "할 일"} 보기`, onclick: () => go(target, k) },
      h("span", { class: "num" }, k === "diff_minutes" && v > 0 ? "+" + v : v), h("span", { class: "lbl" }, label)));
  }
  const list = clear($("#reflections"));
  if (!S.plan.reflections.length) list.append(h("p", { class: "muted" }, "아직 남긴 돌아보기가 없습니다."));
  for (const rf of S.plan.reflections) {
    const s = rf.stats;
    list.append(h("div", { class: "reflection" },
      h("p", {}, h("b", {}, `#${rf.id} `), showUTC(rf.created_at),
        h("span", { class: "muted" }, ` · 계획 ${s.planned} / 완료 ${s.done} / 지연 ${s.delayed} / 막힘 ${s.blocked} / 예상 ${s.estimated_minutes}분 / 실제 ${s.actual_minutes}분 / 차이 ${s.diff_minutes}분`)),
      rf.note ? h("p", {}, rf.note) : null,
      h("p", { class: "carried" }, "고칠 점: ", h("b", {}, rf.improvement)),
      rf.carried_to_plan_ids.length
        ? h("p", {}, "넘어간 계획: ", rf.carried_to_plan_ids.map((id) => h("a", { href: `#plan=${id}&tab=plan` }, `#${id} `)))
        : h("button", { type: "button", class: "small", onclick: () => { S.tab = "plan"; S.ev = null; writeHash(); render().then(() => openPlanForm(null, rf)); } },
          "이 고칠 점으로 다음 계획 만들기")));
  }
}

// ---------------------------------------------------------------- 이벤트
function bind() {
  $("#tabs").addEventListener("click", (e) => { const t = e.target.closest("button"); if (t) go(t.dataset.tab); });
  $("#plan-select").addEventListener("change", (e) => { S.planId = Number(e.target.value); S.ev = null; writeHash(); render(); });
  $("#btn-new-plan").addEventListener("click", () => { S.tab = "plan"; writeHash(); render().then(() => openPlanForm(null)); });
  $("#plan-form-cancel").addEventListener("click", () => { $("#plan-form").hidden = true; S.editingPlan = false; });
  $("#plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, d = formData(f), id = f.dataset.id;
    try {
      const p = id ? await api("PUT", `/api/plans/${id}`, d) : await api("POST", "/api/plans", d);
      f.hidden = true; S.editingPlan = false; S.planId = p.id;
      toast(id ? "계획을 고쳤습니다. 이전 판은 이력에 남아 있습니다." : "계획을 저장했습니다.");
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
      toast(id ? `#${id} 고쳤습니다` : "할 일을 추가했습니다");
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
      toast("실행 기록을 저장했습니다 (계획 값은 그대로)");
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
      e.target.reset(); toast("돌아보기를 저장했습니다"); await render();
    } catch (err) { toast(err.message, true); }
  });

  const fromHash = async () => {
    const st = readHash();
    if ((st.plan || S.planId) === S.planId && st.tab === S.tab && st.ev === S.ev) return; // 이미 그 화면
    if (st.plan) S.planId = st.plan;
    S.tab = st.tab; S.ev = st.ev;
    await render();
  };
  window.addEventListener("popstate", fromHash);
  window.addEventListener("hashchange", fromHash);
}

async function start() {
  bind();
  const meta = await api("GET", "/api/meta");
  $("#today").textContent = `서울 기준 오늘: ${meta.today_kst}`;
  const st = readHash();
  S.planId = st.plan; S.tab = st.tab; S.ev = st.ev;
  await loadPlans();
  history.replaceState(null, "", location.pathname + location.search);
  writeHash();
  await render();
}
document.addEventListener("DOMContentLoaded", () => start().catch((e) => toast(e.message, true)));
