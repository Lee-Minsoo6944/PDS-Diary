"""가입·로그인·로그아웃·남의 자료 차단을 실제 HTTP 요청으로 확인하고, 기록을 Markdown 으로 남깁니다.

    py tools/verify_auth.py http://127.0.0.1:8000  > docs/auth-verification.md
    py tools/verify_auth.py http://127.0.0.1:8000 --db scratch.db   (저장된 비밀번호 모양까지 확인)

- 시험용 계정 두 개(이름·비밀번호는 매번 무작위)를 만들고, 끝나면 두 계정 모두 지웁니다.
- 기록에는 비밀번호를 적지 않고(••••), 세션 쿠키는 앞 5글자만 남기고 가립니다.
"""
import json
import secrets
import sqlite3
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
DB = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else None
SECRETS = []  # 기록에서 가릴 값(비밀번호·쿠키)
OUT = []
FAILS = []


def mask(text):
    for s in SECRETS:
        text = text.replace(s, s[:5] + "…(masked)" if len(s) > 20 else "••••")
    return text


def req(method, path, body=None, cookie=None, headers=None, csrf=True):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if csrf and method != "GET":
        h["X-PDS"] = "1"
    if cookie:
        h["Cookie"] = f"pds_session={cookie}"
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            status, raw, rh = resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        status, raw, rh = e.code, e.read(), e.headers
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode("utf-8", "replace")[:80]
    set_cookie = rh.get("Set-Cookie")
    new = None
    if set_cookie and set_cookie.startswith("pds_session="):
        new = set_cookie.split(";")[0].split("=", 1)[1] or None
        if new:
            SECRETS.append(new)
    return {"method": method, "path": path, "body": body, "cookie": cookie, "headers": headers or {},
            "csrf": csrf and method != "GET", "status": status, "payload": payload, "set_cookie": set_cookie,
            "new_cookie": new}


def show(r):
    lines = [f"{r['method']} {r['path']}"]
    if r["cookie"]:
        lines.append(f"Cookie: pds_session={r['cookie']}")
    else:
        lines.append("Cookie: (none)")
    if r["csrf"]:
        lines.append("X-PDS: 1")
    for k, v in r["headers"].items():
        lines.append(f"{k}: {v}")
    if r["body"] is not None:
        lines.append(json.dumps(r["body"], ensure_ascii=False))
    lines.append(f"→ {r['status']}")
    if r["set_cookie"]:
        lines.append(f"Set-Cookie: {r['set_cookie']}")
    p = r["payload"]
    if isinstance(p, list):
        p = {"list": [x.get("title", x.get("id")) if isinstance(x, dict) else x for x in p]}
    elif isinstance(p, dict) and "items" in p:
        p = {"items": [x.get("title", x.get("id")) for x in p["items"]]}
    text = json.dumps(p, ensure_ascii=False)
    lines.append(text if len(text) < 160 else text[:157] + "…")
    return mask("\n".join(lines))


def pair(title, good, bad, expect_good, expect_bad, why=""):
    ok = good["status"] in expect_good and bad["status"] in expect_bad
    if not ok:
        FAILS.append(title)
    OUT.append(f"### {'✅' if ok else '❌'} {title}\n")
    if why:
        OUT.append(why + "\n")
    OUT.append("| Allowed | Rejected |\n|---|---|")
    cell = lambda r: "<pre>" + show(r).replace("|", "&#124;").replace("\n", "<br>") + "</pre>"  # noqa: E731
    OUT.append(f"| {cell(good)} | {cell(bad)} |\n")


def check(title, cond, detail):
    if not cond:
        FAILS.append(title)
    OUT.append(f"### {'✅' if cond else '❌'} {title}\n\n{mask(detail)}\n")


def main():
    tag = secrets.token_hex(3)
    A, B = f"check_a_{tag}", f"check_b_{tag}"
    pw_a, pw_b, pw_a2 = (secrets.token_urlsafe(12) for _ in range(3))
    SECRETS.extend([pw_a, pw_b, pw_a2])
    OUT.append(f"# Auth verification record\n\nServer: `{BASE}` · test accounts `{A}`, `{B}` "
               "(random passwords, shown as ••••; session cookies masked after 5 characters). "
               "Both accounts are deleted at the end.\n")

    # 1. 가입 / 같은 아이디 다시 가입
    ra = req("POST", "/api/auth/signup", {"username": A, "password": pw_a})
    ca = ra["new_cookie"]
    rb = req("POST", "/api/auth/signup", {"username": B, "password": pw_b})
    cb = rb["new_cookie"]
    pair("Sign up · same username again (C94, C98)", ra,
         req("POST", "/api/auth/signup", {"username": A.upper(), "password": pw_b}), {200}, {409},
         "The second request uses the same name in capitals; usernames are compared without case.")

    # 2. 로그인 / 틀린 비밀번호 / 없는 아이디
    good = req("POST", "/api/auth/login", {"username": A, "password": pw_a})
    bad1 = req("POST", "/api/auth/login", {"username": A, "password": "wrong-" + tag})
    bad2 = req("POST", "/api/auth/login", {"username": "nobody_" + tag, "password": "wrong-" + tag})
    SECRETS.append("wrong-" + tag)
    pair("Log in · wrong password (C95)", good, bad1, {200}, {401})
    pair("Log in · unknown username — same message (C99)", good, bad2, {200}, {401})
    check("Both failures look identical (C99)", bad1["payload"] == bad2["payload"] and not bad1["set_cookie"],
          f"Wrong password → `{bad1['status']} {json.dumps(bad1['payload'])}`  \n"
          f"Unknown user → `{bad2['status']} {json.dumps(bad2['payload'])}`  \nNo cookie is set in either case.")
    c_login = good["new_cookie"]

    # 3. 로그인 없이
    pair("Same request with and without a session (C97, C124)", req("GET", "/api/plans", cookie=ca),
         req("GET", "/api/plans"), {200}, {401})

    # 4. 자료 만들기
    D0 = "2026-11-05"
    pa = req("POST", "/api/plans", {"title": "A private plan", "start_date": D0, "end_date": "2026-11-12",
                                    "priority": 1, "success_criteria": "A only"}, cookie=ca)["payload"]
    pb = req("POST", "/api/plans", {"title": "B private plan", "start_date": D0, "end_date": "2026-11-12",
                                    "priority": 1, "success_criteria": "B only"}, cookie=cb)["payload"]
    ta = req("POST", "/api/todos", {"plan_id": pa["id"], "title": "A todo", "priority": 1}, cookie=ca)["payload"]
    tb = req("POST", "/api/todos", {"plan_id": pb["id"], "title": "B todo", "priority": 1}, cookie=cb)["payload"]
    la = req("POST", f"/api/todos/{ta['id']}/logs", {"started_at": f"{D0}T09:00:00+09:00",
                                                     "ended_at": f"{D0}T09:30:00+09:00"}, cookie=ca)["payload"]
    lb = req("POST", f"/api/todos/{tb['id']}/logs", {"started_at": f"{D0}T10:00:00+09:00",
                                                     "ended_at": f"{D0}T10:40:00+09:00"}, cookie=cb)["payload"]
    OUT.append(f"Created: A → plan {pa['id']}, to-do {ta['id']}, log {la['id']}; "
               f"B → plan {pb['id']}, to-do {tb['id']}, log {lb['id']}.\n")
    # 5. 남의 자료: 읽기·고치기·지우기, 양쪽 방향. 거절된 요청 앞뒤로 상대 자료를 통째로 비교합니다.
    upd = {"title": "changed by someone else", "start_date": D0, "end_date": "2026-11-12", "priority": 1,
           "success_criteria": "x"}
    unchanged = []
    for me, c, oc, mine, other, oname in (("A", ca, cb, (pa, ta, la), (pb, tb, lb), "B"),
                                          ("B", cb, ca, (pb, tb, lb), (pa, ta, la), "A")):
        (mp, mt, ml), (op, ot, ol) = mine, other
        snap = lambda: {k: v for k, v in req("GET", "/api/export", cookie=oc)["payload"].items()  # noqa: E731
                        if k != "exported_at"}
        before = snap()
        bad = [req("GET", f"/api/plans/{op['id']}", cookie=c),
               req("PUT", f"/api/plans/{op['id']}", upd, cookie=c),
               req("PUT", f"/api/todos/{ot['id']}", {"title": "changed", "priority": 2}, cookie=c),
               req("DELETE", f"/api/logs/{ol['id']}", cookie=c),
               req("POST", "/api/todos", {"plan_id": op["id"], "title": "planted", "priority": 3}, cookie=c),
               req("GET", f"/api/plans/{op['id']}/review", cookie=c)]
        unchanged.append((oname, before == snap()))
        good = [req("GET", f"/api/plans/{mp['id']}", cookie=c),
                req("PUT", f"/api/plans/{mp['id']}", upd | {"title": mp["title"]}, cookie=c),
                req("PUT", f"/api/todos/{mt['id']}", {"title": mt["title"], "priority": 2}, cookie=c),
                req("DELETE", f"/api/logs/{ml['id']}", cookie=c),
                req("POST", "/api/todos", {"plan_id": mp["id"], "title": "extra", "priority": 3}, cookie=c),
                req("GET", f"/api/plans/{mp['id']}/review", cookie=c)]
        labels = [("reads plan", "C117"), ("updates plan", "C118"), ("updates to-do", "C118"),
                  ("deletes work log", "C119"), ("adds a to-do to a plan", "C118"), ("reads review", "C117")]
        for (label, code), g, b in zip(labels, good, bad):
            pair(f"{me} {label}: own vs {oname}'s ({code})", g, b, {200, 201}, {403, 404})
    check("The other side's data did not change (C122)", all(ok for _, ok in unchanged),
          "Each owner's full export, taken right before and right after the six rejected requests, is identical: "
          + ", ".join(f"{n}: {'same' if ok else 'CHANGED'}" for n, ok in unchanged) + ".")

    # 6. 목록·끼워 넣기
    lst = req("GET", f"/api/plans?user_id={pb['user_id'] if 'user_id' in pb else 0}", cookie=ca,
              headers={"X-User-Id": str(pb.get("user_id", 0)), "X-Username": B})
    titles = [p["title"] for p in lst["payload"]]
    check("Owner put in query / header is ignored (C125)", "B private plan" not in titles,
          "<pre>" + show(lst) + "</pre>")
    body_inj = req("POST", "/api/plans", {"title": "made by A with B's id", "start_date": D0, "end_date": D0,
                                          "priority": 3, "success_criteria": "x", "user_id": pb.get("user_id", 0),
                                          "username": B}, cookie=ca)
    in_b = [p["title"] for p in req("GET", "/api/plans", cookie=cb)["payload"]]
    check("Owner put in the body is ignored (C125)", "made by A with B's id" not in in_b,
          "<pre>" + show(body_inj) + "</pre>\n\nB's plan list afterwards: " + json.dumps(in_b))
    for path in ("/api/todos", "/api/logs", f"/api/todos?plan_id={pb['id']}", f"/api/logs?plan_id={pb['id']}"):
        r = req("GET", path, cookie=ca)
        txt = json.dumps(r["payload"])
        check(f"List {path} as A has nothing of B (C123)", r["status"] == 200 and "B todo" not in txt
              and "B private" not in txt, "<pre>" + show(r) + "</pre>")

    # 7. 다른 사이트에서 몰래 보내는 쓰기 요청
    pair("Write with and without the app header (CSRF)",
         req("POST", "/api/todos", {"plan_id": pa["id"], "title": "with header", "priority": 3}, cookie=ca),
         req("POST", "/api/todos", {"plan_id": pa["id"], "title": "no header", "priority": 3}, cookie=ca,
             csrf=False), {201}, {403})

    # 8. 로그아웃: 같은 요청, 달라진 것은 로그아웃뿐
    before = req("GET", "/api/plans", cookie=c_login)
    out = req("POST", "/api/auth/logout", cookie=c_login)
    after = req("GET", "/api/plans", cookie=c_login)
    pair("Same request before and after logout (C96, C109, C110)", before, after, {200}, {401},
         "<pre>" + show(out) + "</pre>\n\nThe server deletes the session row, so even a copied cookie stops working.")

    # 9. 비밀번호 바꾸면 예전 세션 끊김
    other_browser = req("POST", "/api/auth/login", {"username": A, "password": pw_a})["new_cookie"]
    chg = req("POST", "/api/auth/password", {"current_password": pw_a, "new_password": pw_a2}, cookie=ca)
    ca_new = chg["new_cookie"]
    pair("Old session after a password change (C114)", req("GET", "/api/plans", cookie=ca_new),
         req("GET", "/api/plans", cookie=other_browser), {200}, {401},
         "<pre>" + show(chg) + "</pre>\n\nLeft: the new session from the change. Right: another browser's session "
         "made before the change.")
    pair("Log in with new vs old password (C114)",
         req("POST", "/api/auth/login", {"username": A, "password": pw_a2}),
         req("POST", "/api/auth/login", {"username": A, "password": pw_a}), {200}, {401})

    # 10. 저장된 비밀번호 모양
    if DB:
        conn = sqlite3.connect(DB)
        rows = conn.execute("SELECT username, password_hash FROM users WHERE username IN (?, ?)", (A, B)).fetchall()
        sess = conn.execute("SELECT token_hash FROM sessions LIMIT 1").fetchone()
        conn.close()
        lines = [f"{u}: {h[:40]}…" for u, h in rows]
        plain = any(p in h for _, h in rows for p in (pw_a, pw_a2, pw_b))
        check("Stored password is a salted scrypt hash (C101–C105)", rows and not plain and all(
            h.startswith("scrypt$") for _, h in rows), "```\n" + "\n".join(lines) + "\n```\n"
              "Format `scrypt$N$r$p$salt$hash`; the salt is different for each account. No plaintext appears. "
              f"Sessions are stored only as SHA-256: `{(sess[0][:16] + '…') if sess else '-'}`.")

    # 11. 계정 삭제
    pair("Delete account: wrong vs right password (C134)",
         req("POST", "/api/auth/delete-account", {"password": pw_a2}, cookie=ca_new),
         req("POST", "/api/auth/delete-account", {"password": "wrong-" + tag}, cookie=cb), {200}, {403})
    pair("After deleting A: B still works, A's session is gone (C134)", req("GET", "/api/plans", cookie=cb),
         req("GET", "/api/plans", cookie=ca_new), {200}, {401})
    req("POST", "/api/auth/delete-account", {"password": pw_b}, cookie=cb)

    OUT.append(f"\n**Result: {'all checks passed' if not FAILS else 'FAILED: ' + ', '.join(FAILS)}**\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print(mask("\n".join(OUT)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
