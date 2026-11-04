"""통과 기준(T06-Cxx) 자동 확인.  실행: py -m unittest discover -s tests -v"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["PDS_DB_PATH"] = os.path.join(TMP, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


def call(method, path, body=None):
    path, _, query = path.partition("?")
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    out = {}

    def sr(status, headers):
        out["status"], out["headers"] = int(status.split()[0]), dict(headers)

    data = b"".join(app.application(env, sr))
    ctype = out["headers"]["Content-Type"]
    return out["status"], (json.loads(data) if ctype.startswith("application/json") else data), out["headers"]


def ok(method, path, body=None):
    s, d, _ = call(method, path, body)
    assert s in (200, 201), (s, d)
    return d


TODAY = app.today_kst()
D = lambda n: (datetime.fromisoformat(TODAY) + timedelta(days=n)).date().isoformat()  # noqa: E731


class PDS(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(w["started_at"], "2026-11-03T12:00:00Z")   # C23 (서울→UTC)
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

    def test_C82_notice_on_first_screen(self):
        s, html, _ = call("GET", "/")
        self.assertIn("지금은 로그인이 없어 링크를 아는 사람은 누구나 볼 수 있습니다. 남이 봐도 괜찮은 내용만 넣으세요",
                      html.decode("utf-8"))

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


if __name__ == "__main__":
    unittest.main()
