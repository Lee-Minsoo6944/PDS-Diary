"""플랜두씨 다이어리 서버.

표준 라이브러리만 씁니다(설치할 것 없음). SQLite 파일 하나에 모든 자료를 저장합니다.
- 로컬 실행:  py app.py   →  http://127.0.0.1:8000
- 배포(WSGI): 이 파일의 `application` 을 WSGI 진입점으로 씁니다.

시간 규칙
- 시각(…_at)은 UTC ISO-8601 문자열 'YYYY-MM-DDTHH:MM:SSZ' 로 저장하고, 화면에서 대한민국 시간(KST)으로 보여 줍니다.
- 날짜(…_date)는 대한민국 기준 달력 날짜 'YYYY-MM-DD' 로 저장합니다(시간대 없음).
- 시간 길이는 모두 '분(정수)' 단위로 저장하고 보여 줍니다.
"""
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PDS_DB_PATH", os.path.join(BASE_DIR, "data", "pds.db"))
STATIC_DIR = os.path.join(BASE_DIR, "static")
KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 +09:00 고정
SCHEMA_VERSION = 2
MAX_BODY = 64 * 1024

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}

SECURITY_HEADERS = [
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
     "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    title                      TEXT    NOT NULL,
    start_date                 TEXT    NOT NULL,
    end_date                   TEXT    NOT NULL,
    priority                   INTEGER NOT NULL CHECK (priority IN (1, 2, 3)),
    success_criteria           TEXT    NOT NULL,
    estimated_minutes          INTEGER NOT NULL CHECK (estimated_minutes >= 0),
    carried_from_reflection_id INTEGER REFERENCES reflections(id),
    current_version            INTEGER NOT NULL DEFAULT 1,
    created_at                 TEXT    NOT NULL,
    updated_at                 TEXT    NOT NULL,
    CHECK (end_date >= start_date)
);
CREATE TABLE IF NOT EXISTS plan_versions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER NOT NULL REFERENCES plans(id),
    version           INTEGER NOT NULL,
    title             TEXT    NOT NULL,
    start_date        TEXT    NOT NULL,
    end_date          TEXT    NOT NULL,
    priority          INTEGER NOT NULL,
    success_criteria  TEXT    NOT NULL,
    estimated_minutes INTEGER NOT NULL,
    change_note       TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL,
    UNIQUE (plan_id, version)
);
CREATE TRIGGER IF NOT EXISTS plan_versions_no_update BEFORE UPDATE ON plan_versions
BEGIN SELECT RAISE(ABORT, 'plan_versions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS plan_versions_no_delete BEFORE DELETE ON plan_versions
BEGIN SELECT RAISE(ABORT, 'plan_versions is append-only'); END;

CREATE TABLE IF NOT EXISTS todos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER NOT NULL REFERENCES plans(id),
    title             TEXT    NOT NULL,
    note              TEXT    NOT NULL DEFAULT '',
    due_date          TEXT,
    priority          INTEGER NOT NULL CHECK (priority IN (1, 2, 3)),
    estimated_minutes INTEGER NOT NULL DEFAULT 0 CHECK (estimated_minutes >= 0),
    status            TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    deleted_at        TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS todo_tags (
    todo_id INTEGER NOT NULL REFERENCES todos(id),
    tag     TEXT    NOT NULL,
    PRIMARY KEY (todo_id, tag)
);
CREATE TABLE IF NOT EXISTS completions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id         INTEGER NOT NULL REFERENCES todos(id),
    idempotency_key TEXT    NOT NULL UNIQUE,
    completed_at    TEXT    NOT NULL,
    undone_at       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS completions_one_active
    ON completions (todo_id) WHERE undone_at IS NULL;

CREATE TABLE IF NOT EXISTS work_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    todo_id        INTEGER NOT NULL REFERENCES todos(id),
    started_at     TEXT    NOT NULL,
    ended_at       TEXT    NOT NULL,
    actual_minutes INTEGER NOT NULL CHECK (actual_minutes >= 0),
    blocker        TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    CHECK (ended_at >= started_at)
);
CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plans(id),
    period_from TEXT,
    period_to   TEXT,
    note        TEXT    NOT NULL DEFAULT '',
    improvement TEXT    NOT NULL,
    stats_json  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS todos_plan ON todos (plan_id);
CREATE INDEX IF NOT EXISTS logs_todo ON work_logs (todo_id);
CREATE TABLE IF NOT EXISTS day_notes (
    note_date  TEXT PRIMARY KEY,
    body       TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

PRIORITY_LABEL = {1: "High", 2: "Normal", 3: "Low"}


# ---------------------------------------------------------------- 공통 도구
class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_kst():
    return datetime.now(KST).date().isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = connect()
    try:
        # WAL은 네트워크 디스크(PythonAnywhere 등)에서 믿을 수 없어 기본 방식을 씁니다.
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
    finally:
        conn.close()


class tx:
    """BEGIN IMMEDIATE … COMMIT/ROLLBACK. 쓰기를 한 줄로 세워 경쟁 상태를 막습니다."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


# ---------------------------------------------------------------- 입력 검사
def req_text(body, key, max_len=500, required=True):
    v = body.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ApiError(400, f"{key}: must be text")
    v = v.strip()
    if required and not v:
        raise ApiError(400, f"{key}: must not be empty")
    if len(v) > max_len:
        raise ApiError(400, f"{key}: must be {max_len} characters or fewer")
    return v


def req_int(body, key, lo=0, hi=100000, default=None):
    v = body.get(key, default)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        v = int(v.strip())
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(400, f"{key}: must be a whole number")
    if not lo <= v <= hi:
        raise ApiError(400, f"{key}: must be between {lo} and {hi}")
    return v


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, key, required=True):
    v = body.get(key)
    if v in (None, ""):
        if required:
            raise ApiError(400, f"{key}: a date is required")
        return None
    if not isinstance(v, str) or not DATE_RE.match(v):
        raise ApiError(400, f"{key}: must be in YYYY-MM-DD format")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ApiError(400, f"{key}: not a valid date")
    return v


def req_instant(body, key):
    """시간대가 붙은 ISO 시각 → UTC 'Z' 문자열."""
    v = body.get(key)
    if not isinstance(v, str) or not v:
        raise ApiError(400, f"{key}: a time is required")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(400, f"{key}: must be an ISO-8601 time")
    if dt.tzinfo is None:
        raise ApiError(400, f"{key}: must include a time zone (+09:00 or Z)")
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_tags(v):
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        raise ApiError(400, "tags: must be a list")
    out = []
    for t in v:
        if not isinstance(t, str):
            raise ApiError(400, "tags: must be text")
        t = t.strip().lstrip("#")
        if t and t not in out:
            if len(t) > 30:
                raise ApiError(400, "tags: each tag must be 30 characters or fewer")
            out.append(t)
    if len(out) > 10:
        raise ApiError(400, "tags: at most 10 tags")
    return out


def get_id(s):
    if not s.isdigit():
        raise ApiError(404, "Not found")
    return int(s)


# ---------------------------------------------------------------- 계획
PLAN_FIELDS = ("title", "start_date", "end_date", "priority", "success_criteria", "estimated_minutes")


def read_plan_body(body, fallback_minutes=0):
    # 계획에는 이제 예상 시간을 따로 적지 않고, 완료 기준(글)만 적습니다.
    # 예전 자료와 맞추려고 열은 남겨 두고, 값이 오지 않으면 기존 값(새 계획은 0)을 씁니다.
    if body.get("estimated_minutes") in (None, ""):
        body = {**body, "estimated_minutes": fallback_minutes}
    p = {
        "title": req_text(body, "title", 200),
        "start_date": req_date(body, "start_date"),
        "end_date": req_date(body, "end_date"),
        "priority": req_int(body, "priority", 1, 3),
        "success_criteria": req_text(body, "success_criteria", 1000),
        "estimated_minutes": req_int(body, "estimated_minutes", 0, 1000000),
    }
    if p["end_date"] < p["start_date"]:
        raise ApiError(400, "end_date: cannot be before the start date")
    return p


def plan_row(conn, plan_id):
    r = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not r:
        raise ApiError(404, "Plan not found")
    return dict(r)


def plan_detail(conn, plan_id):
    p = plan_row(conn, plan_id)
    p["versions"] = [dict(r) for r in conn.execute(
        "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version", (plan_id,))]
    p["reflections"] = [dict(r) for r in conn.execute(
        "SELECT * FROM reflections WHERE plan_id = ? ORDER BY id DESC", (plan_id,))]
    for r in p["reflections"]:
        r["stats"] = json.loads(r.pop("stats_json"))
        r["carried_to_plan_ids"] = [x[0] for x in conn.execute(
            "SELECT id FROM plans WHERE carried_from_reflection_id = ? ORDER BY id", (r["id"],))]
    p["carried_from"] = None
    if p["carried_from_reflection_id"]:
        r = conn.execute("SELECT id, plan_id, improvement, created_at FROM reflections WHERE id = ?",
                         (p["carried_from_reflection_id"],)).fetchone()
        p["carried_from"] = dict(r) if r else None
    return p


def list_plans(conn):
    rows = conn.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM todos t WHERE t.plan_id = p.id AND t.deleted_at IS NULL) AS todo_count
        FROM plans p ORDER BY p.start_date DESC, p.id DESC""")
    return [dict(r) for r in rows]


def create_plan(conn, body):
    p = read_plan_body(body)
    carried = body.get("carried_from_reflection_id")
    if carried in ("", None):
        carried = None
    else:
        carried = req_int(body, "carried_from_reflection_id", 1, 10 ** 12)
        if not conn.execute("SELECT 1 FROM reflections WHERE id = ?", (carried,)).fetchone():
            raise ApiError(400, "carried_from_reflection_id: reflection not found")
    ts = now_utc()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO plans (title, start_date, end_date, priority, success_criteria, estimated_minutes,"
            " carried_from_reflection_id, current_version, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,1,?,?)",
            (*[p[k] for k in PLAN_FIELDS], carried, ts, ts))
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO plan_versions (plan_id, version, title, start_date, end_date, priority,"
            " success_criteria, estimated_minutes, change_note, created_at) VALUES (?,1,?,?,?,?,?,?,?,?)",
            (pid, *[p[k] for k in PLAN_FIELDS], "Original plan", ts))
    return plan_detail(conn, pid)


def update_plan(conn, plan_id, body):
    note = req_text(body, "change_note", 300, required=False)
    ts = now_utc()
    with tx(conn):
        cur = plan_row(conn, plan_id)
        p = read_plan_body(body, fallback_minutes=cur["estimated_minutes"])
        if all(cur[k] == p[k] for k in PLAN_FIELDS):
            return plan_detail(conn, plan_id)  # 바뀐 게 없으면 새 판을 만들지 않음
        ver = cur["current_version"] + 1
        conn.execute(
            "INSERT INTO plan_versions (plan_id, version, title, start_date, end_date, priority,"
            " success_criteria, estimated_minutes, change_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (plan_id, ver, *[p[k] for k in PLAN_FIELDS], note, ts))
        conn.execute(
            "UPDATE plans SET title=?, start_date=?, end_date=?, priority=?, success_criteria=?,"
            " estimated_minutes=?, current_version=?, updated_at=? WHERE id=?",
            (*[p[k] for k in PLAN_FIELDS], ver, ts, plan_id))
    return plan_detail(conn, plan_id)


# ---------------------------------------------------------------- 할 일
def todo_row(conn, todo_id, include_deleted=False):
    r = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if not r or (r["deleted_at"] and not include_deleted):
        raise ApiError(404, "To-do not found")
    return r


def decorate_todos(conn, rows):
    todos = [dict(r) for r in rows]
    if not todos:
        return todos
    ids = [t["id"] for t in todos]
    marks = ",".join("?" * len(ids))
    tags, logs = {}, {}
    for r in conn.execute(f"SELECT todo_id, tag FROM todo_tags WHERE todo_id IN ({marks}) ORDER BY tag", ids):
        tags.setdefault(r[0], []).append(r[1])
    for r in conn.execute(
            f"SELECT todo_id, COUNT(*), COALESCE(SUM(actual_minutes),0),"
            f" SUM(CASE WHEN blocker <> '' THEN 1 ELSE 0 END)"
            f" FROM work_logs WHERE todo_id IN ({marks}) GROUP BY todo_id", ids):
        logs[r[0]] = (r[1], r[2], r[3])
    today = today_kst()
    for t in todos:
        t["tags"] = tags.get(t["id"], [])
        n, mins, blocked = logs.get(t["id"], (0, 0, 0))
        t["log_count"], t["actual_minutes"], t["blocked"] = n, mins, blocked > 0
        t["overdue"] = t["status"] != "done" and t["due_date"] is not None and t["due_date"] < today
    return todos


def todo_detail(conn, todo_id):
    t = decorate_todos(conn, [todo_row(conn, todo_id)])[0]
    t["logs"] = [dict(r) for r in conn.execute(
        "SELECT * FROM work_logs WHERE todo_id = ? ORDER BY started_at, id", (todo_id,))]
    t["completions"] = [dict(r) for r in conn.execute(
        "SELECT id, completed_at, undone_at FROM completions WHERE todo_id = ? ORDER BY id", (todo_id,))]
    return t


# 정렬 기준. 값이 같으면 언제나 ID 오름차순으로 순서를 정합니다.
SORTS = {
    "due": ("t.due_date IS NULL", "t.due_date"),          # 마감일 없는 것은 항상 맨 뒤
    "priority": (None, "t.priority"),                    # 1=높음 → 3=낮음
    "estimate": (None, "t.estimated_minutes"),
    "created": (None, "t.created_at"),
    "title": (None, "t.title"),
}


def list_todos(conn, qs):
    where, args = ["t.deleted_at IS NULL"], []
    plan_id = qs.get("plan_id")
    if plan_id:
        where.append("t.plan_id = ?")
        args.append(get_id(plan_id))
    q = (qs.get("q") or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(t.title LIKE ? ESCAPE '\\' OR t.note LIKE ? ESCAPE '\\' OR EXISTS"
                     " (SELECT 1 FROM todo_tags g WHERE g.todo_id = t.id AND g.tag LIKE ? ESCAPE '\\'))")
        args += [like, like, like]
    status = qs.get("status")
    if status in ("open", "done"):
        where.append("t.status = ?")
        args.append(status)
    elif status == "overdue":
        where.append("t.status <> 'done' AND t.due_date IS NOT NULL AND t.due_date < ?")
        args.append(today_kst())
    elif status == "blocked":
        where.append("EXISTS (SELECT 1 FROM work_logs w WHERE w.todo_id = t.id AND w.blocker <> '')")
    if qs.get("priority") in ("1", "2", "3"):
        where.append("t.priority = ?")
        args.append(int(qs["priority"]))
    tag = (qs.get("tag") or "").strip().lstrip("#")
    if tag:
        where.append("EXISTS (SELECT 1 FROM todo_tags g WHERE g.todo_id = t.id AND g.tag = ?)")
        args.append(tag)
    for key, op in (("due_from", ">="), ("due_to", "<=")):
        d = req_date(qs, key, required=False)
        if d:
            where.append(f"t.due_date {op} ?")
            args.append(d)
    ids = qs.get("ids")
    if ids:
        id_list = [get_id(x) for x in ids.split(",") if x][:500]
        where.append(f"t.id IN ({','.join('?' * len(id_list))})")
        args += id_list
    sort = qs.get("sort") if qs.get("sort") in SORTS else "due"
    direction = "DESC" if qs.get("dir") == "desc" else "ASC"
    nulls, col = SORTS[sort]
    order = ([nulls] if nulls else []) + [f"{col} {direction}", "t.id ASC"]
    sql = f"SELECT t.* FROM todos t WHERE {' AND '.join(where)} ORDER BY {', '.join(order)}"
    return {"sort": sort, "dir": direction.lower(), "items": decorate_todos(conn, conn.execute(sql, args))}


def read_todo_body(body):
    return {
        "title": req_text(body, "title", 200),
        "note": req_text(body, "note", 2000, required=False),
        "due_date": req_date(body, "due_date", required=False),
        "priority": req_int(body, "priority", 1, 3),
        "estimated_minutes": req_int(body, "estimated_minutes", 0, 1000000, default=0),
    }


def set_tags(conn, todo_id, tags):
    conn.execute("DELETE FROM todo_tags WHERE todo_id = ?", (todo_id,))
    conn.executemany("INSERT INTO todo_tags (todo_id, tag) VALUES (?, ?)", [(todo_id, t) for t in tags])


def create_todo(conn, body):
    plan_id = req_int(body, "plan_id", 1, 10 ** 12)
    plan_row(conn, plan_id)
    t, tags, ts = read_todo_body(body), parse_tags(body.get("tags")), now_utc()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO todos (plan_id, title, note, due_date, priority, estimated_minutes, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,'open',?,?)",
            (plan_id, t["title"], t["note"], t["due_date"], t["priority"], t["estimated_minutes"], ts, ts))
        set_tags(conn, cur.lastrowid, tags)
    return todo_detail(conn, cur.lastrowid)


def update_todo(conn, todo_id, body):
    t, tags = read_todo_body(body), parse_tags(body.get("tags"))
    with tx(conn):
        todo_row(conn, todo_id)
        conn.execute("UPDATE todos SET title=?, note=?, due_date=?, priority=?, estimated_minutes=?, updated_at=?"
                     " WHERE id=?", (t["title"], t["note"], t["due_date"], t["priority"],
                                     t["estimated_minutes"], now_utc(), todo_id))
        set_tags(conn, todo_id, tags)
    return todo_detail(conn, todo_id)


def delete_todo(conn, todo_id):
    with tx(conn):
        todo_row(conn, todo_id)
        ts = now_utc()
        conn.execute("UPDATE todos SET deleted_at=?, updated_at=? WHERE id=?", (ts, ts, todo_id))
    return {"ok": True, "id": todo_id}


def complete_todo(conn, todo_id, body):
    """완료 처리. 같은 키로 여러 번 와도, 키가 달라도, 진행 중인 완료 기록은 한 건만 남습니다."""
    key = req_text(body, "idempotency_key", 100)
    with tx(conn):
        t = todo_row(conn, todo_id)
        seen = conn.execute("SELECT todo_id FROM completions WHERE idempotency_key = ?", (key,)).fetchone()
        if seen:
            if seen[0] != todo_id:
                raise ApiError(409, "This key was already used for a different to-do")
            created = False
        elif t["status"] == "done":
            created = False
        else:
            ts = now_utc()
            # completions_one_active 인덱스가 같은 할 일의 두 번째 '진행 중 완료'를 DB 수준에서 막습니다.
            conn.execute("INSERT INTO completions (todo_id, idempotency_key, completed_at) VALUES (?,?,?)",
                         (todo_id, key, ts))
            conn.execute("UPDATE todos SET status='done', updated_at=? WHERE id=?", (ts, todo_id))
            created = True
    d = todo_detail(conn, todo_id)
    d["created"] = created
    return d


def reopen_todo(conn, todo_id):
    with tx(conn):
        t = todo_row(conn, todo_id)
        if t["status"] == "done":
            ts = now_utc()
            conn.execute("UPDATE completions SET undone_at=? WHERE todo_id=? AND undone_at IS NULL", (ts, todo_id))
            conn.execute("UPDATE todos SET status='open', updated_at=? WHERE id=?", (ts, todo_id))
    return todo_detail(conn, todo_id)


# ---------------------------------------------------------------- 실행 기록
def create_log(conn, todo_id, body):
    start, end = req_instant(body, "started_at"), req_instant(body, "ended_at")
    if end < start:
        raise ApiError(400, "ended_at: cannot be before the start time")
    computed = round((end - start).total_seconds() / 60)
    raw = body.get("actual_minutes")
    minutes = computed if raw in (None, "") else req_int(body, "actual_minutes", 0, 100000)
    blocker = req_text(body, "blocker", 1000, required=False)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    with tx(conn):
        todo_row(conn, todo_id)
        cur = conn.execute(
            "INSERT INTO work_logs (todo_id, started_at, ended_at, actual_minutes, blocker, created_at)"
            " VALUES (?,?,?,?,?,?)", (todo_id, start.strftime(fmt), end.strftime(fmt), minutes, blocker, now_utc()))
    return dict(conn.execute("SELECT * FROM work_logs WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_logs(conn, qs):
    where, args = ["t.deleted_at IS NULL"], []
    if qs.get("plan_id"):
        where.append("t.plan_id = ?")
        args.append(get_id(qs["plan_id"]))
    if qs.get("ids"):
        id_list = [get_id(x) for x in qs["ids"].split(",") if x][:500]
        where.append(f"w.id IN ({','.join('?' * len(id_list))})")
        args += id_list
    rows = conn.execute(
        f"SELECT w.*, t.title AS todo_title, t.plan_id, t.estimated_minutes AS todo_estimated_minutes"
        f" FROM work_logs w JOIN todos t ON t.id = w.todo_id WHERE {' AND '.join(where)}"
        f" ORDER BY w.started_at DESC, w.id DESC", args)
    return [dict(r) for r in rows]


def delete_log(conn, log_id):
    with tx(conn):
        if conn.execute("DELETE FROM work_logs WHERE id = ?", (log_id,)).rowcount == 0:
            raise ApiError(404, "Work log not found")
    return {"ok": True, "id": log_id}


# ---------------------------------------------------------------- 돌아보기
def review(conn, plan_id, qs):
    plan = plan_row(conn, plan_id)
    period_from = req_date(qs, "from", required=False)
    period_to = req_date(qs, "to", required=False)
    where, args = ["plan_id = ?", "deleted_at IS NULL"], [plan_id]
    if period_from:
        where.append("due_date >= ?")
        args.append(period_from)
    if period_to:
        where.append("due_date <= ?")
        args.append(period_to)
    todos = conn.execute(f"SELECT * FROM todos WHERE {' AND '.join(where)} ORDER BY id", args).fetchall()
    ids = [t["id"] for t in todos]
    logs = []
    if ids:
        logs = conn.execute(
            f"SELECT * FROM work_logs WHERE todo_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    today = today_kst()
    blocked_todo_ids = sorted({w["todo_id"] for w in logs if w["blocker"]})
    estimated = sum(t["estimated_minutes"] for t in todos)
    actual = sum(w["actual_minutes"] for w in logs)
    stats = {
        "planned": len(todos),
        "done": sum(1 for t in todos if t["status"] == "done"),
        "delayed": sum(1 for t in todos if t["status"] != "done" and t["due_date"] and t["due_date"] < today),
        "blocked": len(blocked_todo_ids),
        "estimated_minutes": estimated,
        "actual_minutes": actual,
        "diff_minutes": actual - estimated,
    }
    evidence = {
        "planned": {"todo_ids": ids},
        "done": {"todo_ids": [t["id"] for t in todos if t["status"] == "done"]},
        "delayed": {"todo_ids": [t["id"] for t in todos
                                 if t["status"] != "done" and t["due_date"] and t["due_date"] < today]},
        "blocked": {"todo_ids": blocked_todo_ids, "log_ids": [w["id"] for w in logs if w["blocker"]]},
        "estimated_minutes": {"todo_ids": ids},
        "actual_minutes": {"log_ids": [w["id"] for w in logs]},
        "diff_minutes": {"todo_ids": ids, "log_ids": [w["id"] for w in logs]},
    }
    return {"plan_id": plan_id, "plan_title": plan["title"], "today_kst": today,
            "period": {"from": period_from, "to": period_to},
            "stats": stats, "evidence": evidence}


def create_reflection(conn, plan_id, body):
    improvement = req_text(body, "improvement", 300)
    note = req_text(body, "note", 2000, required=False)
    qs = {"from": body.get("from") or None, "to": body.get("to") or None}
    r = review(conn, plan_id, qs)
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO reflections (plan_id, period_from, period_to, note, improvement, stats_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (plan_id, r["period"]["from"], r["period"]["to"], note, improvement,
             json.dumps(r["stats"], ensure_ascii=False), now_utc()))
    return plan_detail(conn, plan_id) | {"new_reflection_id": cur.lastrowid}


# ---------------------------------------------------------------- 날짜별 메모
def get_note(conn, day):
    r = conn.execute("SELECT * FROM day_notes WHERE note_date = ?", (day,)).fetchone()
    return dict(r) if r else {"note_date": day, "body": "", "updated_at": None}


def put_note(conn, day, body):
    text = body.get("body", "")
    if not isinstance(text, str):
        raise ApiError(400, "body: must be text")
    if len(text) > 5000:
        raise ApiError(400, "body: must be 5000 characters or fewer")
    with tx(conn):
        conn.execute("INSERT INTO day_notes (note_date, body, updated_at) VALUES (?,?,?)"
                     " ON CONFLICT(note_date) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                     (day, text, now_utc()))
    return get_note(conn, day)


def list_notes(conn, qs):
    lo, hi = req_date(qs, "from"), req_date(qs, "to")
    rows = conn.execute("SELECT note_date FROM day_notes WHERE body <> '' AND note_date BETWEEN ? AND ?"
                        " ORDER BY note_date", (lo, hi))
    return [r[0] for r in rows]


# ---------------------------------------------------------------- 내보내기
def export_all(conn):
    out = {"app": "plan-do-see-diary", "schema_version": SCHEMA_VERSION, "exported_at": now_utc(),
           "time_rules": {"instants": "UTC ISO-8601 (Z)", "dates": "Korea (KST, UTC+9, Asia/Seoul) calendar date YYYY-MM-DD",
                          "durations": "minutes (integer)"}}
    for table in ("plans", "plan_versions", "todos", "todo_tags", "completions", "work_logs", "reflections", "day_notes"):
        out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    return out


# ---------------------------------------------------------------- 라우팅
def route(method, path, qs, body, conn):
    parts = [p for p in path.split("/") if p][1:]  # 'api' 다음부터
    n = len(parts)
    if parts == ["meta"] and method == "GET":
        return {"today_kst": today_kst(), "schema_version": SCHEMA_VERSION, "login": False}
    if parts == ["plans"]:
        if method == "GET":
            return list_plans(conn)
        if method == "POST":
            return create_plan(conn, body)
    if n == 2 and parts[0] == "plans":
        pid = get_id(parts[1])
        if method == "GET":
            return plan_detail(conn, pid)
        if method == "PUT":
            return update_plan(conn, pid, body)
    if n == 3 and parts[0] == "plans" and parts[2] == "review" and method == "GET":
        return review(conn, get_id(parts[1]), qs)
    if n == 3 and parts[0] == "plans" and parts[2] == "reflections" and method == "POST":
        return create_reflection(conn, get_id(parts[1]), body)
    if parts == ["todos"]:
        if method == "GET":
            return list_todos(conn, qs)
        if method == "POST":
            return create_todo(conn, body)
    if n == 2 and parts[0] == "todos":
        tid = get_id(parts[1])
        if method == "GET":
            return todo_detail(conn, tid)
        if method == "PUT":
            return update_todo(conn, tid, body)
        if method == "DELETE":
            return delete_todo(conn, tid)
    if n == 3 and parts[0] == "todos" and method == "POST":
        tid = get_id(parts[1])
        if parts[2] == "complete":
            return complete_todo(conn, tid, body)
        if parts[2] == "reopen":
            return reopen_todo(conn, tid)
        if parts[2] == "logs":
            return create_log(conn, tid, body)
    if parts == ["logs"] and method == "GET":
        return list_logs(conn, qs)
    if n == 2 and parts[0] == "logs" and method == "DELETE":
        return delete_log(conn, get_id(parts[1]))
    if parts == ["notes"] and method == "GET":
        return list_notes(conn, qs)
    if n == 2 and parts[0] == "notes":
        day = req_date({"date": parts[1]}, "date")
        if method == "GET":
            return get_note(conn, day)
        if method == "PUT":
            return put_note(conn, day, body)
    if parts == ["export"] and method == "GET":
        return export_all(conn)
    raise ApiError(404, "Not found")


def respond(start_response, status, body_bytes, ctype, extra=()):
    headers = [("Content-Type", ctype), ("Content-Length", str(len(body_bytes)))] + SECURITY_HEADERS + list(extra)
    start_response(status, headers)
    return [body_bytes]


STATUS_TEXT = {200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found",
               405: "405 Method Not Allowed", 409: "409 Conflict", 413: "413 Payload Too Large",
               500: "500 Internal Server Error"}


# ---------------------------------------------------------------- 자동 배포(GitHub 웹훅)
# GitHub에 푸시하면 GitHub가 POST /api/deploy 로 알려 줍니다.
# 서명(X-Hub-Signature-256)이 서버에만 있는 암호와 맞을 때만 git pull 후 웹 앱을 다시 시작합니다.
# 암호 파일이 없으면 이 주소는 없는 것처럼(404) 동작합니다. 암호는 저장소에 넣지 않습니다.
DEPLOY_SECRET_FILE = os.environ.get("PDS_DEPLOY_SECRET_FILE", os.path.expanduser("~/.pds_deploy_secret"))
DEPLOY_BRANCH = "refs/heads/main"
DEPLOY_MAX_BODY = 5 * 1024 * 1024


def deploy_secret():
    try:
        with open(DEPLOY_SECRET_FILE, "rb") as f:
            s = f.read().strip()
        return s or None
    except OSError:
        return None


def wsgi_file():
    """PythonAnywhere는 WSGI 파일의 수정 시각이 바뀌면 웹 앱을 다시 시작합니다."""
    p = os.environ.get("PDS_WSGI_FILE")
    if p:
        return p
    import getpass
    return f"/var/www/{getpass.getuser().lower()}_pythonanywhere_com_wsgi.py"


def run_git_pull():
    import subprocess
    r = subprocess.run(["git", "pull", "--ff-only"], cwd=BASE_DIR, capture_output=True, text=True, timeout=90)
    return r.returncode, (r.stdout + r.stderr).strip()[-1500:]


def reload_later():
    def touch():
        p = wsgi_file()
        if os.path.exists(p):
            os.utime(p, None)
    import threading
    threading.Timer(1.0, touch).start()  # 응답을 먼저 보내고 다시 시작


def handle_deploy(environ):
    import hashlib
    import hmac
    secret = deploy_secret()
    if environ.get("REQUEST_METHOD") != "POST" or not secret:
        return 404, {"error": "Not found"}
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > DEPLOY_MAX_BODY:
        return 413, {"error": "Request body is too large"}
    raw = environ["wsgi.input"].read(length) if length else b""
    expected = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, environ.get("HTTP_X_HUB_SIGNATURE_256", "")):
        return 403, {"error": "Bad signature"}
    event = environ.get("HTTP_X_GITHUB_EVENT", "")
    if event == "ping":
        return 200, {"ok": True, "pong": True}
    if event != "push":
        return 200, {"ok": True, "skipped": f"event {event}"}
    try:
        ref = json.loads(raw.decode("utf-8")).get("ref")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return 400, {"error": "Body is not valid JSON"}
    if ref != DEPLOY_BRANCH:
        return 200, {"ok": True, "skipped": f"ref {ref}"}
    code, out = run_git_pull()
    if code != 0:
        return 500, {"ok": False, "git": out}
    reload_later()
    return 200, {"ok": True, "git": out, "reloading": True}


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/") or "/"

    if path == "/api/deploy":
        try:
            status, payload = handle_deploy(environ)
        except Exception:
            import traceback
            traceback.print_exc()
            status, payload = 500, {"error": "Server error"}
        return respond(start_response, STATUS_TEXT.get(status, f"{status} Error"),
                       json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", [("Cache-Control", "no-store")])

    if not path.startswith("/api/"):
        if method != "GET" or path not in STATIC_FILES:
            return respond(start_response, "404 Not Found", b"Not found", "text/plain; charset=utf-8")
        name, ctype = STATIC_FILES[path]
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            data = f.read()
        return respond(start_response, "200 OK", data, ctype, [("Cache-Control", "no-cache")])

    qs = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
    status, payload, extra = 200, None, [("Cache-Control", "no-store")]
    conn = None
    try:
        body = {}
        if method in ("POST", "PUT"):
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                raise ApiError(413, "Request body is too large")
            raw = environ["wsgi.input"].read(length) if length else b""
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise ApiError(400, "Body is not valid JSON")
                if not isinstance(body, dict):
                    raise ApiError(400, "Body must be a JSON object")
        conn = connect()
        payload = route(method, path, qs, body, conn)
        if method == "POST" and not path.endswith(("/complete", "/reopen")):
            status = 201
        if path == "/api/export":
            stamp = datetime.now(KST).strftime("%Y%m%d-%H%M")
            extra.append(("Content-Disposition", f'attachment; filename="pds-diary-export-{stamp}.json"'))
    except ApiError as e:
        status, payload = e.status, {"error": e.message}
    except sqlite3.IntegrityError as e:
        status, payload = 409, {"error": "Violates a storage rule: " + str(e)}
    except Exception:  # 내부 정보는 응답에 싣지 않음
        import traceback
        traceback.print_exc()
        status, payload = 500, {"error": "Server error"}
    finally:
        if conn is not None:
            conn.close()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return respond(start_response, STATUS_TEXT.get(status, f"{status} Error"), data,
                   "application/json; charset=utf-8", extra)


init_db()

if __name__ == "__main__":
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    with make_server(host, port, application, server_class=ThreadingWSGIServer) as srv:
        print(f"Plan-Do-See Diary: http://{host}:{port}  (DB: {DB_PATH})")
        srv.serve_forever()
