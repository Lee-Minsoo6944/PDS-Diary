"""통과 기준(T06-Cxx, T07-Cxx) 자동 확인.  실행: py -m unittest discover -s tests -v"""
import io
import json
import os
import sys
import tempfile
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["PDS_DB_PATH"] = os.path.join(TMP, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


SESSION = {"cookie": None}  # 지금 로그인한 사람의 세션 값(테스트마다 새 계정)
DEFAULT = object()
PW = "correct-horse-battery"  # 테스트 전용 비밀번호


def call(method, path, body=None, cookie=DEFAULT, headers=None, csrf=True):
    path, _, query = path.partition("?")
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http"}
    if csrf:
        env["HTTP_X_PDS"] = "1"
    c = SESSION["cookie"] if cookie is DEFAULT else cookie
    if c:
        env["HTTP_COOKIE"] = f"pds_session={c}"
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    out = {}

    def sr(status, hdrs):
        out["status"], out["headers"] = int(status.split()[0]), dict(hdrs)

    data = b"".join(app.application(env, sr))
    ctype = out["headers"]["Content-Type"]
    return out["status"], (json.loads(data) if ctype.startswith("application/json") else data), out["headers"]


def session_from(headers):
    v = headers.get("Set-Cookie", "")
    return v.split(";")[0].split("=", 1)[1] if v.startswith("pds_session=") else None


_n = [0]


def new_user(prefix="user"):
    _n[0] += 1
    name = f"{prefix}{_n[0]}"
    s, d, h = call("POST", "/api/auth/signup", {"username": name, "password": PW}, cookie=None)
    assert s == 200, (s, d)
    return name, session_from(h)


def ok(method, path, body=None):
    s, d, _ = call(method, path, body)
    assert s in (200, 201), (s, d)
    return d


TODAY = app.today_kst()
D = lambda n: (datetime.fromisoformat(TODAY) + timedelta(days=n)).date().isoformat()  # noqa: E731


class PDS(unittest.TestCase):
    def setUp(self):
        _, SESSION["cookie"] = new_user("t06_")
        self.plan = ok("POST", "/api/plans", {"title": "테스트 계획", "start_date": D(-7), "end_date": D(7),
                                              "priority": 1, "success_criteria": "주 3회", "estimated_minutes": 600})
        self.pid = self.plan["id"]

    def todo(self, **kw):
        b = {"plan_id": self.pid, "title": "할 일", "priority": 2, "estimated_minutes": 30, "tags": ["a"]}
        b.update(kw)
        return ok("POST", "/api/todos", b)

    def review(self):
        return ok("GET", f"/api/plans/{self.pid}/review")

    def test_C04_07_plan_fields(self):
        p = ok("GET", f"/api/plans/{self.pid}")
        self.assertEqual((p["start_date"], p["end_date"]), (D(-7), D(7)))
        self.assertEqual(p["priority"], 1)
        self.assertEqual(p["success_criteria"], "주 3회")
        self.assertEqual(p["estimated_minutes"], 600)

    def test_C08_plan_history_kept(self):
        body = dict(title="고친 계획", start_date=D(-7), end_date=D(14), priority=2,
                    success_criteria="주 4회", estimated_minutes=900, change_note="늘림")
        p = ok("PUT", f"/api/plans/{self.pid}", body)
        self.assertEqual(p["id"], self.pid)
        self.assertEqual(p["title"], "고친 계획")
        self.assertEqual(len(p["versions"]), 2)
        v1 = p["versions"][0]
        self.assertEqual((v1["version"], v1["title"], v1["estimated_minutes"], v1["end_date"]),
                         (1, "테스트 계획", 600, D(7)))
        # 이력 표는 고칠 수 없음
        conn = app.connect()
        with self.assertRaises(Exception):
            conn.execute("UPDATE plan_versions SET title='x' WHERE plan_id=?", (self.pid,))
        conn.close()

    def test_C09_20_todo_crud_search_filter_sort(self):
        a = self.todo(title="영단어 외우기", due_date=D(2), priority=1, tags=["공부", "영어"], estimated_minutes=40)
        self.assertEqual((a["due_date"], a["priority"], a["tags"], a["estimated_minutes"]),
                         (D(2), 1, ["공부", "영어"], 40))                          # C09, C14~C17
        b = ok("PUT", f"/api/todos/{a['id']}", {"title": "영단어 50개", "due_date": D(3), "priority": 3,
                                                "tags": "공부", "estimated_minutes": 50})
        self.assertEqual((b["title"], b["priority"], b["tags"]), ("영단어 50개", 3, ["공부"]))  # C10
        c = ok("POST", f"/api/todos/{a['id']}/complete", {"idempotency_key": "k-c11"})
        self.assertEqual(c["status"], "done")                                  # C11
        c = ok("POST", f"/api/todos/{a['id']}/reopen")
        self.assertEqual(c["status"], "open")                                  # C12
        x = self.todo(title="지울 것")
        ok("DELETE", f"/api/todos/{x['id']}")
        ids = [t["id"] for t in ok("GET", f"/api/todos?plan_id={self.pid}")["items"]]
        self.assertNotIn(x["id"], ids)                                         # C13
        self.assertEqual([t["id"] for t in ok("GET", f"/api/todos?plan_id={self.pid}&q=영단어")["items"]], [a["id"]])  # C18
        self.assertEqual([t["id"] for t in ok("GET", f"/api/todos?plan_id={self.pid}&tag=공부")["items"]], [a["id"]])  # C19
        # C20: 같은 마감일이면 ID 오름차순, 마감 없음은 맨 뒤
        t1 = self.todo(due_date=D(5)); t2 = self.todo(due_date=D(5)); t3 = self.todo(); t4 = self.todo(due_date=D(1))
        got = [t["id"] for t in ok("GET", f"/api/todos?plan_id={self.pid}&sort=due")["items"]]
        self.assertEqual(got, [t4["id"], a["id"], t1["id"], t2["id"], t3["id"]])
        got2 = [t["id"] for t in ok("GET", f"/api/todos?plan_id={self.pid}&sort=due")["items"]]
        self.assertEqual(got, got2)

    def test_C21_C22_double_complete(self):
        t = self.todo()
        before = self.review()["stats"]["done"]
        r1 = ok("POST", f"/api/todos/{t['id']}/complete", {"idempotency_key": "same"})
        r2 = ok("POST", f"/api/todos/{t['id']}/complete", {"idempotency_key": "same"})
        self.assertTrue(r1["created"]); self.assertFalse(r2["created"])
        self.assertEqual(len(r2["completions"]), 1)
        self.assertEqual(self.review()["stats"]["done"], before + 1)

    def test_C21_concurrent_different_keys(self):
        t = self.todo()
        errs = []

        def hit(k):
            s, d, _ = call("POST", f"/api/todos/{t['id']}/complete", {"idempotency_key": k})
            if s != 200:
                errs.append((s, d))
        th = [threading.Thread(target=hit, args=(f"k{i}",)) for i in range(8)]
        [x.start() for x in th]; [x.join() for x in th]
        self.assertEqual(errs, [])
        self.assertEqual(len(ok("GET", f"/api/todos/{t['id']}")["completions"]), 1)

    def test_C23_27_logs_do_not_touch_plan(self):
        t = self.todo(estimated_minutes=30)
        plan_before = ok("GET", f"/api/plans/{self.pid}")
        w = ok("POST", f"/api/todos/{t['id']}/logs", {"started_at": "2026-11-03T21:00:00+09:00",
                                                      "ended_at": "2026-11-03T21:45:00+09:00", "blocker": "졸림"})
        self.assertEqual(w["started_at"], "2026-11-03T12:00:00Z")   # C23 (KST→UTC)
        self.assertEqual(w["ended_at"], "2026-11-03T12:45:00Z")     # C24
        self.assertEqual(w["actual_minutes"], 45)                    # C25
        self.assertEqual(w["blocker"], "졸림")                       # C26
        self.assertEqual(w["todo_id"], t["id"])
        plan_after = ok("GET", f"/api/plans/{self.pid}")
        for k in app.PLAN_FIELDS + ("current_version",):
            self.assertEqual(plan_before[k], plan_after[k])          # C27
        self.assertEqual(ok("GET", f"/api/todos/{t['id']}")["estimated_minutes"], 30)

    def test_C28_32_review_math_and_evidence(self):
        self.assertEqual(self.review()["stats"], {"planned": 0, "done": 0, "delayed": 0, "blocked": 0,
                                                  "estimated_minutes": 0, "actual_minutes": 0, "diff_minutes": 0})
        late_done = self.todo(due_date=D(-2), estimated_minutes=20)
        late_open = self.todo(due_date=D(-1), estimated_minutes=30)
        today_open = self.todo(due_date=D(0), estimated_minutes=40)
        gone = self.todo(due_date=D(-3), estimated_minutes=999)
        ok("POST", f"/api/todos/{late_done['id']}/complete", {"idempotency_key": "r1"})
        ok("DELETE", f"/api/todos/{gone['id']}")
        w1 = ok("POST", f"/api/todos/{late_open['id']}/logs", {"started_at": "2026-11-01T10:00:00Z",
                                                               "ended_at": "2026-11-01T11:00:00Z", "blocker": "자료 없음"})
        w2 = ok("POST", f"/api/todos/{late_open['id']}/logs", {"started_at": "2026-11-02T10:00:00Z",
                                                               "ended_at": "2026-11-02T10:10:00Z", "blocker": "또 막힘"})
        w3 = ok("POST", f"/api/todos/{late_done['id']}/logs", {"started_at": "2026-11-02T10:00:00Z",
                                                               "ended_at": "2026-11-02T10:05:00Z", "actual_minutes": 25})
        r = self.review()
        self.assertEqual(r["stats"], {"planned": 3, "done": 1, "delayed": 1, "blocked": 1,
                                      "estimated_minutes": 90, "actual_minutes": 95, "diff_minutes": 5})
        ev = r["evidence"]
        self.assertEqual(ev["delayed"]["todo_ids"], [late_open["id"]])
        self.assertEqual(ev["blocked"]["todo_ids"], [late_open["id"]])
        self.assertEqual(sorted(ev["actual_minutes"]["log_ids"]), sorted([w1["id"], w2["id"], w3["id"]]))
        # C83: 근거 ID로 실제 기록을 불러올 수 있다
        got = ok("GET", f"/api/todos?plan_id={self.pid}&ids={','.join(map(str, ev['done']['todo_ids']))}")
        self.assertEqual([t["id"] for t in got["items"]], [late_done["id"]])

    def test_C33_improvement_carried_to_next_plan(self):
        p = ok("POST", f"/api/plans/{self.pid}/reflections", {"note": "밤에 몰아서 함", "improvement": "아침 30분 먼저"})
        rid = p["new_reflection_id"]
        nxt = ok("POST", "/api/plans", {"title": "다음 계획", "start_date": D(8), "end_date": D(14), "priority": 1,
                                        "success_criteria": "아침", "estimated_minutes": 300,
                                        "carried_from_reflection_id": rid})
        self.assertEqual(nxt["carried_from"]["improvement"], "아침 30분 먼저")
        self.assertIn(nxt["id"], ok("GET", f"/api/plans/{self.pid}")["reflections"][0]["carried_to_plan_ids"])

    def test_C36_export_and_C35_roundtrip(self):
        t = self.todo(due_date=D(1), estimated_minutes=33)
        s, data, headers = call("GET", "/api/export")
        self.assertEqual(s, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        for k in ("plans", "plan_versions", "todos", "todo_tags", "completions", "work_logs", "reflections"):
            self.assertIn(k, data)
        row = [x for x in data["todos"] if x["id"] == t["id"]][0]
        again = ok("GET", f"/api/todos/{t['id']}")  # 새 연결로 다시 읽어도 같음
        self.assertEqual((row["due_date"], row["estimated_minutes"]), (again["due_date"], again["estimated_minutes"]))

    def test_C57_script_text_is_stored_verbatim_and_headers(self):
        evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
        t = self.todo(title=evil)
        self.assertEqual(ok("GET", f"/api/todos/{t['id']}")["title"], evil)
        s, html, h = call("GET", "/")
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        with open(os.path.join(app.STATIC_DIR, "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertNotIn(".innerHTML", js)
        self.assertNotIn("insertAdjacentHTML", js)

    def test_first_screen_english_without_login_notice(self):
        s, html, _ = call("GET", "/")
        page = html.decode("utf-8")
        self.assertNotIn("지금은 로그인이 없어", page)
        self.assertIn('lang="en"', page)
        self.assertIn("Completion criteria", page)

    def test_plan_without_estimate_keeps_old_value(self):
        # 계획은 완료 기준(글)만 적고, 예상 시간은 보내지 않아도 됩니다.
        p = ok("POST", "/api/plans", {"title": "글 기준", "start_date": D(0), "end_date": D(3), "priority": 2,
                                      "success_criteria": "보고서 초안을 끝까지 쓴다"})
        self.assertEqual(p["estimated_minutes"], 0)
        # 예상 시간을 보내지 않고 고쳐도, 예전 계획의 값은 그대로 남습니다.
        u = ok("PUT", f"/api/plans/{self.pid}", {"title": "테스트 계획", "start_date": D(-7), "end_date": D(7),
                                                 "priority": 1, "success_criteria": "글로 바꿈"})
        self.assertEqual(u["estimated_minutes"], 600)
        self.assertEqual(u["versions"][-1]["success_criteria"], "글로 바꿈")

    def test_plan_needs_only_name_and_criteria(self):
        # 계획에는 날짜·우선순위를 적지 않음 — 날짜는 할 일마다 정함
        p = ok("POST", "/api/plans", {"title": "날짜 없는 계획", "success_criteria": "끝까지 한다"})
        self.assertEqual((p["start_date"], p["end_date"], p["priority"]), (TODAY, TODAY, 2))
        # 고칠 때 날짜·우선순위를 보내지 않으면 원래 값이 그대로 (예전 계획도 안전)
        u = ok("PUT", f"/api/plans/{self.pid}", {"title": "이름만 바꿈", "success_criteria": "주 3회"})
        self.assertEqual((u["start_date"], u["end_date"], u["priority"]), (D(-7), D(7), 1))
        self.assertEqual(u["current_version"], 2)
        # 계획 기간과 상관없이, 어느 날짜의 할 일이든 넣을 수 있음
        t = self.todo(title="한참 뒤", due_date=D(60), plan_id=p["id"])
        self.assertEqual(t["due_date"], D(60))
        # 돌아보기 날짜별 표: 따로 고르지 않으면 이른 날부터 오늘(KST)까지
        self.todo(title="지난주", due_date=D(-3), plan_id=p["id"])
        days = [r["date"] for r in ok("GET", f"/api/plans/{p['id']}/review")["daily"]["rows"]]
        self.assertEqual((days[0], days[-1]), (D(-3), TODAY))

    def test_calendar_range_and_day_notes(self):
        a = self.todo(title="달력 안", due_date=D(1))
        self.todo(title="달력 밖", due_date=D(40))
        got = ok("GET", f"/api/todos?due_from={D(0)}&due_to={D(7)}")["items"]
        self.assertIn(a["id"], [t["id"] for t in got])
        self.assertNotIn("달력 밖", [t["title"] for t in got])
        day = D(2)
        self.assertEqual(ok("GET", f"/api/notes/{day}")["body"], "")
        evil = "<script>alert(1)</script> 오늘 메모"
        n = ok("PUT", f"/api/notes/{day}", {"body": evil})
        self.assertEqual(n["body"], evil)
        ok("PUT", f"/api/notes/{day}", {"body": evil + "!"})  # 같은 날은 덮어쓰기(행 1개)
        self.assertEqual(ok("GET", f"/api/notes/{day}")["body"], evil + "!")
        self.assertIn(day, ok("GET", f"/api/notes?from={D(0)}&to={D(7)}"))
        self.assertTrue(any(r["note_date"] == day for r in call("GET", "/api/export")[1]["day_notes"]))
        s, _, _ = call("PUT", "/api/notes/2026-13-01", {"body": "x"})
        self.assertEqual(s, 400)

    def test_validation(self):
        s, d, _ = call("POST", "/api/plans", {"title": "x", "start_date": D(5), "end_date": D(1), "priority": 1,
                                              "success_criteria": "x", "estimated_minutes": 1})
        self.assertEqual(s, 400)
        s, d, _ = call("GET", "/../app.py")
        self.assertEqual(s, 404)
        s, d, _ = call("POST", f"/api/todos/1/logs", {"started_at": "2026-11-01T10:00", "ended_at": "2026-11-01T11:00"})
        self.assertIn(s, (400, 404))


class Deploy(unittest.TestCase):
    """자동 배포: 암호 없이, 내 저장소에서만 받아오고, 바뀐 때만 다시 시작. 실제 git/재시작은 가짜로 바꿔 확인."""

    def setUp(self):
        self.wsgi = os.path.join(TMP, "fake_wsgi.py")
        open(self.wsgi, "w").close()
        self.calls = []
        self.changed = True
        self._saved = (app.wsgi_file, app.run_git_pull, app.reload_later)
        app.wsgi_file = lambda: self.wsgi
        app.run_git_pull = lambda: (self.calls.append("pull"), (0, "Fast-forward", self.changed))[1]
        app.reload_later = lambda: self.calls.append("reload")
        app._deploy_state["last"] = 0.0

    def tearDown(self):
        app.wsgi_file, app.run_git_pull, app.reload_later = self._saved

    def hook(self, body, event="push", method="POST"):
        raw = json.dumps(body).encode()
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/api/deploy", "QUERY_STRING": "",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "HTTP_X_GITHUB_EVENT": event}
        out = {}
        data = b"".join(app.application(env, lambda s, h: out.update(status=int(s.split()[0]))))
        return out["status"], json.loads(data)

    def test_push_to_main_pulls_and_reloads(self):
        s, d = self.hook({"ref": "refs/heads/main"})
        self.assertEqual((s, d["ok"], d["reloading"]), (200, True, True))
        self.assertEqual(self.calls, ["pull", "reload"])

    def test_no_change_means_no_reload(self):
        self.changed = False
        s, d = self.hook({"ref": "refs/heads/main"})
        self.assertEqual((s, d["reloading"]), (200, False))
        self.assertEqual(self.calls, ["pull"])

    def test_repeated_calls_are_throttled(self):
        self.assertEqual(self.hook({"ref": "refs/heads/main"})[0], 200)
        self.assertEqual(self.hook({"ref": "refs/heads/main"})[0], 429)
        self.assertEqual(self.calls, ["pull", "reload"])

    def test_other_branch_ping_and_get_do_nothing(self):
        self.assertEqual(self.hook({"ref": "refs/heads/dev"})[0], 200)
        self.assertEqual(self.hook({"zen": "hi"}, event="ping")[1].get("pong"), True)
        self.assertEqual(self.hook({"ref": "refs/heads/main"}, method="GET")[0], 404)
        self.assertEqual(self.calls, [])

    def test_off_when_not_on_pythonanywhere(self):
        os.remove(self.wsgi)
        self.assertEqual(self.hook({"ref": "refs/heads/main"})[0], 404)
        self.assertEqual(self.calls, [])

    def test_failed_pull_does_not_reload(self):
        app.run_git_pull = lambda: (1, "error: Your local changes would be overwritten", False)
        s, d = self.hook({"ref": "refs/heads/main"})
        self.assertEqual((s, d["ok"]), (500, False))
        self.assertEqual(self.calls, [])


# ================================================================ T07: 가입·로그인·로그아웃
class Auth(unittest.TestCase):
    def test_C94_C95_C96_signup_login_logout(self):
        name, c1 = new_user("auser")
        self.assertTrue(c1)
        s, d, _ = call("GET", "/api/auth/me", cookie=c1)
        self.assertEqual((s, d["user"]["username"]), (200, name))
        s, d, h = call("POST", "/api/auth/login", {"username": name, "password": PW}, cookie=None)
        self.assertEqual(s, 200)
        c2 = session_from(h)
        self.assertNotEqual(c1, c2)
        # C109/C110: 같은 주소·같은 방식, 달라진 것은 로그아웃 여부뿐
        self.assertEqual(call("GET", "/api/plans", cookie=c2)[0], 200)
        s, _, h = call("POST", "/api/auth/logout", cookie=c2)
        self.assertEqual(s, 200)
        self.assertIn("Max-Age=0", h["Set-Cookie"])
        s, d, _ = call("GET", "/api/plans", cookie=c2)
        self.assertEqual((s, d["error"]), (401, "Please log in"))
        self.assertEqual(call("GET", "/api/plans", cookie=c1)[0], 200)  # 다른 브라우저의 세션은 그대로

    def test_C97_C124_no_login_means_401(self):
        for method, path in (("GET", "/api/plans"), ("GET", "/api/todos"), ("GET", "/api/logs"),
                             ("GET", "/api/plans/1"), ("GET", "/api/notes/2026-11-05"), ("GET", "/api/export"),
                             ("POST", "/api/todos"), ("DELETE", "/api/todos/1")):
            s, d, _ = call(method, path, {} if method == "POST" else None, cookie=None)
            self.assertEqual(s, 401, (method, path, d))
        s, d, _ = call("GET", "/api/plans", cookie="made-up-session-value")
        self.assertEqual(s, 401)

    def test_C98_same_username_twice(self):
        name, _ = new_user("dup")
        s, d, _ = call("POST", "/api/auth/signup", {"username": name, "password": PW}, cookie=None)
        self.assertEqual((s, d["error"]), (409, "That username is already taken"))
        s, _, _ = call("POST", "/api/auth/signup", {"username": name.upper(), "password": PW}, cookie=None)
        self.assertEqual(s, 409)  # 대소문자만 다른 아이디도 같은 아이디

    def test_C99_same_message_for_wrong_password_and_unknown_user(self):
        name, _ = new_user("msg")
        s1, d1, h1 = call("POST", "/api/auth/login", {"username": name, "password": "wrong-password"}, cookie=None)
        s2, d2, h2 = call("POST", "/api/auth/login", {"username": "nobody-here", "password": "wrong-password"},
                          cookie=None)
        self.assertEqual((s1, d1), (s2, d2))
        self.assertEqual((s1, d1["error"]), (401, "Wrong username or password"))
        self.assertNotIn("Set-Cookie", h1)
        self.assertNotIn("Set-Cookie", h2)

    def test_C103_C104_C105_password_stored_as_salted_scrypt(self):
        n1, _ = new_user("same")
        n2, _ = new_user("same")
        conn = app.connect()
        h1, h2 = [conn.execute("SELECT password_hash FROM users WHERE username = ?", (n,)).fetchone()[0]
                  for n in (n1, n2)]
        conn.close()
        self.assertTrue(h1.startswith("scrypt$16384$8$1$"))
        self.assertNotIn(PW, h1)
        self.assertNotEqual(h1, h2)  # 같은 비밀번호라도 소금값이 달라 저장값이 다름
        s, d, h = call("POST", "/api/auth/login", {"username": n1, "password": PW}, cookie=None)
        self.assertNotIn(PW, json.dumps(d) + json.dumps(h))  # 응답 어디에도 비밀번호 원문 없음

    def test_C111_C112_cookie_flags_and_expiry(self):
        s, d, h = call("POST", "/api/auth/signup", {"username": "cookie1", "password": PW}, cookie=None)
        c = h["Set-Cookie"]
        for part in ("HttpOnly", "SameSite=Lax", "Path=/", f"Max-Age={7 * 86400}"):
            self.assertIn(part, c)
        self.assertNotIn(session_from(h), json.dumps(d))  # 세션 값은 본문(그리고 주소)에 실리지 않음
        conn = app.connect()
        row = conn.execute("SELECT created_at, expires_at FROM sessions WHERE token_hash = ?",
                           (app.token_hash(session_from(h)),)).fetchone()
        conn.close()
        made = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        ends = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
        self.assertEqual(ends - made, timedelta(days=7))
        # https 에서는 Secure 도 붙음
        raw = json.dumps({"username": "cookie2", "password": PW}).encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/auth/signup", "QUERY_STRING": "",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "HTTP_X_PDS": "1",
               "wsgi.url_scheme": "https"}
        got = {}
        b"".join(app.application(env, lambda st, hd: got.update(dict(hd))))
        self.assertIn("Secure", got["Set-Cookie"])

    def test_expired_session_is_rejected(self):
        _, c = new_user("exp")
        conn = app.connect()
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z' WHERE token_hash = ?",
                     (app.token_hash(c),))
        conn.close()
        self.assertEqual(call("GET", "/api/plans", cookie=c)[0], 401)

    def test_C114_password_change_ends_old_sessions(self):
        name, c1 = new_user("pw")
        _, _, h = call("POST", "/api/auth/login", {"username": name, "password": PW}, cookie=None)
        c2 = session_from(h)
        s, d, h = call("POST", "/api/auth/password", {"current_password": PW, "new_password": "brand-new-pass"},
                       cookie=c1)
        self.assertEqual(s, 200)
        c3 = session_from(h)
        self.assertEqual(call("GET", "/api/plans", cookie=c1)[0], 401)
        self.assertEqual(call("GET", "/api/plans", cookie=c2)[0], 401)
        self.assertEqual(call("GET", "/api/plans", cookie=c3)[0], 200)
        self.assertEqual(call("POST", "/api/auth/login", {"username": name, "password": PW}, cookie=None)[0], 401)
        self.assertEqual(call("POST", "/api/auth/login", {"username": name, "password": "brand-new-pass"},
                              cookie=None)[0], 200)

    def test_writes_need_the_app_header(self):
        _, c = new_user("csrf")
        s, d, _ = call("POST", "/api/plans", {"title": "x", "start_date": D(0), "end_date": D(1), "priority": 1,
                                              "success_criteria": "x"}, cookie=c, csrf=False)
        self.assertEqual((s, d["error"]), (403, "Missing X-PDS header"))
        self.assertEqual(call("GET", "/api/plans", cookie=c)[1], [])


# ================================================================ T07: 남의 자료는 안 열림
class Isolation(unittest.TestCase):
    def fill(self, c, tag):
        def ok_as(method, path, body=None):
            st, d, _ = call(method, path, body, cookie=c)
            assert st in (200, 201), (st, d)
            return d
        p = ok_as("POST", "/api/plans", {"title": f"{tag} plan", "start_date": D(-3), "end_date": D(3),
                                         "priority": 1, "success_criteria": f"{tag} done"})
        t = ok_as("POST", "/api/todos", {"plan_id": p["id"], "title": f"{tag} todo", "priority": 2,
                                         "due_date": D(0), "estimated_minutes": 30})
        w = ok_as("POST", f"/api/todos/{t['id']}/logs", {"started_at": f"{D(0)}T09:00:00+09:00",
                                                        "ended_at": f"{D(0)}T09:30:00+09:00"})
        ok_as("PUT", f"/api/notes/{D(0)}", {"body": f"{tag} note"})
        return {"plan": p["id"], "todo": t["id"], "log": w["id"]}

    def setUp(self):
        _, self.ca = new_user("alice")
        _, self.cb = new_user("bob")
        self.a, self.b = self.fill(self.ca, "A"), self.fill(self.cb, "B")

    def snapshot(self, c):
        d = call("GET", "/api/export", cookie=c)[1]
        return {k: d[k] for k in ("plans", "plan_versions", "todos", "completions", "work_logs", "day_notes")}

    def attacks(self, me, other):
        ids = other
        return [
            ("read plan", "GET", f"/api/plans/{ids['plan']}", None),
            ("read review", "GET", f"/api/plans/{ids['plan']}/review", None),
            ("update plan", "PUT", f"/api/plans/{ids['plan']}", {"title": "hacked", "start_date": D(0),
                                                                  "end_date": D(1), "priority": 1,
                                                                  "success_criteria": "hacked"}),
            ("read todo", "GET", f"/api/todos/{ids['todo']}", None),
            ("update todo", "PUT", f"/api/todos/{ids['todo']}", {"title": "hacked", "priority": 1}),
            ("complete todo", "POST", f"/api/todos/{ids['todo']}/complete", {"idempotency_key": "x" + me}),
            ("delete todo", "DELETE", f"/api/todos/{ids['todo']}", None),
            ("add log to todo", "POST", f"/api/todos/{ids['todo']}/logs", {"started_at": "2026-11-05T00:00:00Z",
                                                                             "ended_at": "2026-11-05T01:00:00Z"}),
            ("delete log", "DELETE", f"/api/logs/{ids['log']}", None),
            ("add todo to plan", "POST", "/api/todos", {"plan_id": ids["plan"], "title": "planted", "priority": 1}),
            ("reflect on plan", "POST", f"/api/plans/{ids['plan']}/reflections", {"improvement": "planted"}),
        ]

    def test_C117_C122_both_directions_are_404_and_nothing_changes(self):
        for me, c, other, oc in (("A", self.ca, self.b, self.cb), ("B", self.cb, self.a, self.ca)):
            before = self.snapshot(oc)
            for label, method, path, body in self.attacks(me, other):
                s, d, _ = call(method, path, body, cookie=c)
                self.assertEqual(s, 404, (me, label, s, d))
            self.assertEqual(before, self.snapshot(oc), me)  # 반대편 자료 그대로

    def test_C123_C125_lists_and_injected_owner_return_only_mine(self):
        b_ids = {self.b["plan"], self.b["todo"]}
        for path in ("/api/plans", f"/api/plans?user_id=2&plan_id={self.b['plan']}",
                     f"/api/todos?plan_id={self.b['plan']}", "/api/todos", f"/api/logs?plan_id={self.b['plan']}",
                     "/api/logs", f"/api/notes?from={D(-1)}&to={D(1)}"):
            s, d, _ = call("GET", path, cookie=self.ca, headers={"X-User-Id": "2", "X-Username": "bob"})
            self.assertEqual(s, 200)
            text = json.dumps(d)
            self.assertNotIn("B plan", text)
            self.assertNotIn("B todo", text)
            items = d["items"] if isinstance(d, dict) else d
            if items and isinstance(items[0], dict):
                self.assertFalse({x.get("id") for x in items} & b_ids - {self.a["plan"], self.a["todo"]}
                                 if path.startswith("/api/plans") or path.startswith("/api/todos") else set())
        self.assertEqual(call("GET", f"/api/notes/{D(0)}", cookie=self.ca)[1]["body"], "A note")
        # 본문에 남의 계정·남의 계획을 적어도 내 계정에 만들어지거나 거절됨
        s, p, _ = call("POST", "/api/plans", {"title": "mine", "start_date": D(0), "end_date": D(1), "priority": 1,
                                              "success_criteria": "x", "user_id": 999, "username": "bob"},
                       cookie=self.ca)
        self.assertEqual(s, 201)
        self.assertIn(p["id"], [x["id"] for x in call("GET", "/api/plans", cookie=self.ca)[1]])
        self.assertNotIn(p["id"], [x["id"] for x in call("GET", "/api/plans", cookie=self.cb)[1]])
        exp = call("GET", "/api/export", cookie=self.ca)[1]
        self.assertNotIn("B plan", json.dumps(exp))
        self.assertNotIn("password_hash", json.dumps(exp))

    def test_C134_delete_account_removes_only_my_data(self):
        b_before = self.snapshot(self.cb)
        s, d, _ = call("POST", "/api/auth/delete-account", {"password": "wrong"}, cookie=self.ca)
        self.assertEqual(s, 403)
        s, d, h = call("POST", "/api/auth/delete-account", {"password": PW}, cookie=self.ca)
        self.assertEqual((s, d["deleted"]), (200, True))
        self.assertEqual(call("GET", "/api/plans", cookie=self.ca)[0], 401)
        conn = app.connect()
        for table, col, val in (("plans", "id", self.a["plan"]), ("todos", "id", self.a["todo"]),
                                ("work_logs", "id", self.a["log"]), ("plan_versions", "plan_id", self.a["plan"])):
            self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (val,)).fetchone()[0], 0)
        conn.close()
        self.assertEqual(b_before, self.snapshot(self.cb))


# ================================================================ T07: 6번 자료 옮기기·DB 고치기
class Migration(unittest.TestCase):
    def test_C100_unowned_data_is_hidden_until_claimed(self):
        name, c = new_user("owner")
        conn = app.connect()
        conn.execute("INSERT INTO plans (title, start_date, end_date, priority, success_criteria, estimated_minutes,"
                     " current_version, created_at, updated_at) VALUES ('T06 plan', ?, ?, 1, 'x', 0, 1, ?, ?)",
                     (D(0), D(1), app.now_utc(), app.now_utc()))
        conn.close()
        self.assertNotIn("T06 plan", json.dumps(call("GET", "/api/plans", cookie=c)[1]))
        self.assertIn("Moved 1 plan(s)", app.claim_unowned(name))
        self.assertIn("T06 plan", json.dumps(call("GET", "/api/plans", cookie=c)[1]))

    def test_v2_database_is_backed_up_and_upgraded(self):
        path = os.path.join(TMP, "old_v2.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('schema_version', '2');
            CREATE TABLE plans (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, start_date TEXT NOT NULL,
              end_date TEXT NOT NULL, priority INTEGER NOT NULL, success_criteria TEXT NOT NULL,
              estimated_minutes INTEGER NOT NULL, carried_from_reflection_id INTEGER,
              current_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE plan_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL, version INTEGER,
              title TEXT, start_date TEXT, end_date TEXT, priority INTEGER, success_criteria TEXT,
              estimated_minutes INTEGER, change_note TEXT DEFAULT '', created_at TEXT, UNIQUE (plan_id, version));
            CREATE TRIGGER plan_versions_no_delete BEFORE DELETE ON plan_versions
              BEGIN SELECT RAISE(ABORT, 'plan_versions is append-only'); END;
            CREATE TABLE day_notes (note_date TEXT PRIMARY KEY, body TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
            INSERT INTO plans (title, start_date, end_date, priority, success_criteria, estimated_minutes, created_at,
              updated_at) VALUES ('old', '2026-11-01', '2026-11-08', 1, 'x', 0, 'a', 'a');
            INSERT INTO day_notes VALUES ('2026-11-05', 'old note', 'a');
        """)
        conn.close()
        saved = app.DB_PATH
        app.DB_PATH = path
        try:
            app.init_db()
            conn = app.connect()
            self.assertIn("user_id", app.table_columns(conn, "plans"))
            self.assertIn("user_id", app.table_columns(conn, "day_notes"))
            self.assertEqual(conn.execute("SELECT title, user_id FROM plans").fetchone()[:], ("old", None))
            self.assertEqual(conn.execute("SELECT body FROM day_notes").fetchone()[0], "old note")
            self.assertEqual(conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "3")
            conn.close()
            self.assertTrue([f for f in os.listdir(TMP) if f.startswith("old_v2.db.v2-backup-")])
            app.init_db()  # 두 번 돌려도 괜찮음
        finally:
            app.DB_PATH = saved


# ================================================================ T07: 5일 기록용 날짜별 표
class Daily(unittest.TestCase):
    def test_daily_sum_average_missing_duplicate_outlier(self):
        _, SESSION["cookie"] = new_user("daily")
        p = ok("POST", "/api/plans", {"title": "obs", "start_date": "2026-11-01", "end_date": "2026-11-30",
                                      "priority": 1, "success_criteria": "x"})
        t = ok("POST", "/api/todos", {"plan_id": p["id"], "title": "study", "priority": 1})
        logs = [("2026-11-02T23:30:00+09:00", "2026-11-03T00:10:00+09:00"),  # KST 11/2 시작 → 11/2
                ("2026-11-03T09:00:00+09:00", "2026-11-03T09:25:00+09:00"),
                ("2026-11-03T09:00:00+09:00", "2026-11-03T09:25:00+09:00"),  # 중복
                ("2026-11-05T08:00:00+09:00", "2026-11-05T21:00:00+09:00")]  # 780분: 튀는 값
        for a, b in logs:
            ok("POST", f"/api/todos/{t['id']}/logs", {"started_at": a, "ended_at": b})
        d = ok("GET", f"/api/plans/{p['id']}/review?from=2026-11-02&to=2026-11-06")["daily"]
        self.assertEqual([r["date"] for r in d["rows"]],
                         ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"])
        self.assertEqual([r["actual_minutes"] for r in d["rows"]], [40, 25, 0, 780, 0])
        self.assertEqual(d["rows"][1]["duplicates"], 1)
        self.assertEqual(d["rows"][3]["outliers"], 1)
        self.assertEqual(d["total"]["actual_minutes"], 845)
        self.assertEqual(d["average"]["actual_minutes"], 169.0)  # 845 ÷ 5
        self.assertEqual(sum(r["actual_minutes"] for r in d["rows"]), d["total"]["actual_minutes"])


if __name__ == "__main__":
    unittest.main()
