# Auth verification record

Server: `http://127.0.0.1:8017` · test accounts `check_a_64fee3`, `check_b_64fee3` (random passwords, shown as ••••; session cookies masked after 5 characters). Both accounts are deleted at the end.

### ✅ Sign up · same username again (C94, C98)

The second request uses the same name in capitals; usernames are compared without case.

| Allowed | Rejected |
|---|---|
| <pre>POST /api/auth/signup<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 200<br>Set-Cookie: pds_session=LywFS…(masked); Path=/; HttpOnly; SameSite=Lax; Max-Age=604800<br>{"ok": true, "user": {"id": 3, "username": "check_a_64fee3"}}</pre> | <pre>POST /api/auth/signup<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "CHECK_A_64FEE3", "password": "••••"}<br>→ 409<br>{"error": "That username is already taken"}</pre> |

### ✅ Log in · wrong password (C95)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 200<br>Set-Cookie: pds_session=tmJLX…(masked); Path=/; HttpOnly; SameSite=Lax; Max-Age=604800<br>{"ok": true, "user": {"id": 3, "username": "check_a_64fee3"}}</pre> | <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 401<br>{"error": "Wrong username or password"}</pre> |

### ✅ Log in · unknown username — same message (C99)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 200<br>Set-Cookie: pds_session=tmJLX…(masked); Path=/; HttpOnly; SameSite=Lax; Max-Age=604800<br>{"ok": true, "user": {"id": 3, "username": "check_a_64fee3"}}</pre> | <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "nobody_64fee3", "password": "••••"}<br>→ 401<br>{"error": "Wrong username or password"}</pre> |

### ✅ Both failures look identical (C99)

Wrong password → `401 {"error": "Wrong username or password"}`  
Unknown user → `401 {"error": "Wrong username or password"}`  
No cookie is set in either case.

### ✅ Same request with and without a session (C97, C124)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans<br>Cookie: pds_session=LywFS…(masked)<br>→ 200<br>{"list": []}</pre> | <pre>GET /api/plans<br>Cookie: (none)<br>→ 401<br>{"error": "Please log in"}</pre> |

Created: A → plan 6, to-do 23, log 8; B → plan 7, to-do 24, log 9.

### ✅ A reads plan: own vs B's (C117)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans/6<br>Cookie: pds_session=LywFS…(masked)<br>→ 200<br>{"id": 6, "title": "A private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "A only", "estimated_minutes": …</pre> | <pre>GET /api/plans/7<br>Cookie: pds_session=LywFS…(masked)<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ A updates plan: own vs B's (C118)

| Allowed | Rejected |
|---|---|
| <pre>PUT /api/plans/6<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"title": "A private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x"}<br>→ 200<br>{"id": 6, "title": "A private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x", "estimated_minutes": 0, "c…</pre> | <pre>PUT /api/plans/7<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"title": "changed by someone else", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x"}<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ A updates to-do: own vs B's (C118)

| Allowed | Rejected |
|---|---|
| <pre>PUT /api/todos/23<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"title": "A todo", "priority": 2}<br>→ 200<br>{"id": 23, "plan_id": 6, "title": "A todo", "note": "", "due_date": null, "priority": 2, "estimated_minutes": 0, "status": "open", "deleted_at": null, "creat…</pre> | <pre>PUT /api/todos/24<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"title": "changed", "priority": 2}<br>→ 404<br>{"error": "To-do not found"}</pre> |

### ✅ A deletes work log: own vs B's (C119)

| Allowed | Rejected |
|---|---|
| <pre>DELETE /api/logs/8<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>→ 200<br>{"ok": true, "id": 8}</pre> | <pre>DELETE /api/logs/9<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Work log not found"}</pre> |

### ✅ A adds a to-do to a plan: own vs B's (C118)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/todos<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"plan_id": 6, "title": "extra", "priority": 3}<br>→ 201<br>{"id": 25, "plan_id": 6, "title": "extra", "note": "", "due_date": null, "priority": 3, "estimated_minutes": 0, "status": "open", "deleted_at": null, "create…</pre> | <pre>POST /api/todos<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"plan_id": 7, "title": "planted", "priority": 3}<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ A reads review: own vs B's (C117)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans/6/review<br>Cookie: pds_session=LywFS…(masked)<br>→ 200<br>{"plan_id": 6, "plan_title": "A private plan", "today_kst": "2026-11-05", "period": {"from": null, "to": null}, "stats": {"planned": 2, "done": 0, "delayed":…</pre> | <pre>GET /api/plans/7/review<br>Cookie: pds_session=LywFS…(masked)<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ B reads plan: own vs A's (C117)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans/7<br>Cookie: pds_session=obnbk…(masked)<br>→ 200<br>{"id": 7, "title": "B private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "B only", "estimated_minutes": …</pre> | <pre>GET /api/plans/6<br>Cookie: pds_session=obnbk…(masked)<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ B updates plan: own vs A's (C118)

| Allowed | Rejected |
|---|---|
| <pre>PUT /api/plans/7<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"title": "B private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x"}<br>→ 200<br>{"id": 7, "title": "B private plan", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x", "estimated_minutes": 0, "c…</pre> | <pre>PUT /api/plans/6<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"title": "changed by someone else", "start_date": "2026-11-05", "end_date": "2026-11-12", "priority": 1, "success_criteria": "x"}<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ B updates to-do: own vs A's (C118)

| Allowed | Rejected |
|---|---|
| <pre>PUT /api/todos/24<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"title": "B todo", "priority": 2}<br>→ 200<br>{"id": 24, "plan_id": 7, "title": "B todo", "note": "", "due_date": null, "priority": 2, "estimated_minutes": 0, "status": "open", "deleted_at": null, "creat…</pre> | <pre>PUT /api/todos/23<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"title": "changed", "priority": 2}<br>→ 404<br>{"error": "To-do not found"}</pre> |

### ✅ B deletes work log: own vs A's (C119)

| Allowed | Rejected |
|---|---|
| <pre>DELETE /api/logs/9<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>→ 200<br>{"ok": true, "id": 9}</pre> | <pre>DELETE /api/logs/8<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Work log not found"}</pre> |

### ✅ B adds a to-do to a plan: own vs A's (C118)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/todos<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"plan_id": 7, "title": "extra", "priority": 3}<br>→ 201<br>{"id": 26, "plan_id": 7, "title": "extra", "note": "", "due_date": null, "priority": 3, "estimated_minutes": 0, "status": "open", "deleted_at": null, "create…</pre> | <pre>POST /api/todos<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"plan_id": 6, "title": "planted", "priority": 3}<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ B reads review: own vs A's (C117)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans/7/review<br>Cookie: pds_session=obnbk…(masked)<br>→ 200<br>{"plan_id": 7, "plan_title": "B private plan", "today_kst": "2026-11-05", "period": {"from": null, "to": null}, "stats": {"planned": 2, "done": 0, "delayed":…</pre> | <pre>GET /api/plans/6/review<br>Cookie: pds_session=obnbk…(masked)<br>→ 404<br>{"error": "Plan not found"}</pre> |

### ✅ The other side's data did not change (C122)

Each owner's full export, taken right before and right after the six rejected requests, is identical: B: same, A: same.

### ✅ Owner put in query / header is ignored (C125)

<pre>GET /api/plans?user_id=4
Cookie: pds_session=LywFS…(masked)
X-User-Id: 4
X-Username: check_b_64fee3
→ 200
{"list": ["A private plan"]}</pre>

### ✅ Owner put in the body is ignored (C125)

<pre>POST /api/plans
Cookie: pds_session=LywFS…(masked)
X-PDS: 1
{"title": "made by A with B's id", "start_date": "2026-11-05", "end_date": "2026-11-05", "priority": 3, "success_criteria": "x", "user_id": 4, "username": "check_b_64fee3"}
→ 201
{"id": 8, "title": "made by A with B's id", "start_date": "2026-11-05", "end_date": "2026-11-05", "priority": 3, "success_criteria": "x", "estimated_minutes"…</pre>

B's plan list afterwards: ["B private plan"]

### ✅ List /api/todos as A has nothing of B (C123)

<pre>GET /api/todos
Cookie: pds_session=LywFS…(masked)
→ 200
{"items": ["A todo", "extra"]}</pre>

### ✅ List /api/logs as A has nothing of B (C123)

<pre>GET /api/logs
Cookie: pds_session=LywFS…(masked)
→ 200
{"list": []}</pre>

### ✅ List /api/todos?plan_id=7 as A has nothing of B (C123)

<pre>GET /api/todos?plan_id=7
Cookie: pds_session=LywFS…(masked)
→ 200
{"items": []}</pre>

### ✅ List /api/logs?plan_id=7 as A has nothing of B (C123)

<pre>GET /api/logs?plan_id=7
Cookie: pds_session=LywFS…(masked)
→ 200
{"list": []}</pre>

### ✅ Write with and without the app header (CSRF)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/todos<br>Cookie: pds_session=LywFS…(masked)<br>X-PDS: 1<br>{"plan_id": 6, "title": "with header", "priority": 3}<br>→ 201<br>{"id": 27, "plan_id": 6, "title": "with header", "note": "", "due_date": null, "priority": 3, "estimated_minutes": 0, "status": "open", "deleted_at": null, "…</pre> | <pre>POST /api/todos<br>Cookie: pds_session=LywFS…(masked)<br>{"plan_id": 6, "title": "no header", "priority": 3}<br>→ 403<br>{"error": "Missing X-PDS header"}</pre> |

### ✅ Same request before and after logout (C96, C109, C110)

<pre>POST /api/auth/logout
Cookie: pds_session=tmJLX…(masked)
X-PDS: 1
→ 200
Set-Cookie: pds_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0
{"ok": true}</pre>

The server deletes the session row, so even a copied cookie stops working.

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans<br>Cookie: pds_session=tmJLX…(masked)<br>→ 200<br>{"list": ["made by A with B's id", "A private plan"]}</pre> | <pre>GET /api/plans<br>Cookie: pds_session=tmJLX…(masked)<br>→ 401<br>{"error": "Please log in"}</pre> |

### ✅ Old session after a password change (C114)

<pre>POST /api/auth/password
Cookie: pds_session=LywFS…(masked)
X-PDS: 1
{"current_password": "••••", "new_password": "••••"}
→ 200
Set-Cookie: pds_session=H9yiD…(masked); Path=/; HttpOnly; SameSite=Lax; Max-Age=604800
{"ok": true}</pre>

Left: the new session from the change. Right: another browser's session made before the change.

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans<br>Cookie: pds_session=H9yiD…(masked)<br>→ 200<br>{"list": ["made by A with B's id", "A private plan"]}</pre> | <pre>GET /api/plans<br>Cookie: pds_session=2XltE…(masked)<br>→ 401<br>{"error": "Please log in"}</pre> |

### ✅ Log in with new vs old password (C114)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 200<br>Set-Cookie: pds_session=z7Zjh…(masked); Path=/; HttpOnly; SameSite=Lax; Max-Age=604800<br>{"ok": true, "user": {"id": 3, "username": "check_a_64fee3"}}</pre> | <pre>POST /api/auth/login<br>Cookie: (none)<br>X-PDS: 1<br>{"username": "check_a_64fee3", "password": "••••"}<br>→ 401<br>{"error": "Wrong username or password"}</pre> |

### ✅ Stored password is a salted scrypt hash (C101–C105)

```
check_a_64fee3: scrypt$16384$8$1$23AaakjSVsznZsBMFOU5tQ=…
check_b_64fee3: scrypt$16384$8$1$M2ox6VjCUt8iVGdRneBduA=…
```
Format `scrypt$N$r$p$salt$hash`; the salt is different for each account. No plaintext appears. Sessions are stored only as SHA-256: `681eb29ef5829b4d…`.

### ✅ Delete account: wrong vs right password (C134)

| Allowed | Rejected |
|---|---|
| <pre>POST /api/auth/delete-account<br>Cookie: pds_session=H9yiD…(masked)<br>X-PDS: 1<br>{"password": "••••"}<br>→ 200<br>Set-Cookie: pds_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0<br>{"ok": true, "deleted": true}</pre> | <pre>POST /api/auth/delete-account<br>Cookie: pds_session=obnbk…(masked)<br>X-PDS: 1<br>{"password": "••••"}<br>→ 403<br>{"error": "Password is wrong"}</pre> |

### ✅ After deleting A: B still works, A's session is gone (C134)

| Allowed | Rejected |
|---|---|
| <pre>GET /api/plans<br>Cookie: pds_session=obnbk…(masked)<br>→ 200<br>{"list": ["B private plan"]}</pre> | <pre>GET /api/plans<br>Cookie: pds_session=H9yiD…(masked)<br>→ 401<br>{"error": "Please log in"}</pre> |


**Result: all checks passed**

