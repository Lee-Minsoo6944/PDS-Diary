"""플랜두씨 다이어리 서버 (과제 7: 가입·로그인 추가).

표준 라이브러리만 씁니다(설치할 것 없음). SQLite 파일 하나에 모든 자료를 저장합니다.
- 로컬 실행:  py app.py   →  http://127.0.0.1:8000
- 배포(WSGI): 이 파일의 `application` 을 WSGI 진입점으로 씁니다.
- 6번 자료를 내 계정으로 옮기기:  python3 app.py claim <아이디>

인증 (직접 구현, 자세한 설명은 AUTH.md)
- 비밀번호: hashlib.scrypt(N=2^14, r=8, p=1) + 계정마다 다른 16바이트 소금값. 원문은 어디에도 저장하지 않습니다.
- 로그인 상태: 서버 세션. 브라우저에는 무작위 값(쿠키, HttpOnly·SameSite=Lax·https면 Secure)만 주고,
  서버에는 그 값의 SHA-256만 저장합니다. 7일 뒤 만료, 로그아웃·비밀번호 변경 때 서버에서 지웁니다.
- 서명용 비밀키를 쓰지 않으므로 코드·배포 파일·Git 기록에 비밀키가 없습니다.
- 모든 자료 조회·수정·삭제는 로그인한 사람(user_id)의 자료로만 제한합니다. 남의 자료는 404(있는지조차 숨김).

시간 규칙
- 시각(…_at)은 UTC ISO-8601 문자열 'YYYY-MM-DDTHH:MM:SSZ' 로 저장하고, 화면에서 대한민국 시간(KST)으로 보여 줍니다.
- 날짜(…_date)는 대한민국 기준 달력 날짜 'YYYY-MM-DD' 로 저장합니다(시간대 없음).
- 시간 길이는 모두 '분(정수)' 단위로 저장하고 보여 줍니다.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PDS_DB_PATH", os.path.join(BASE_DIR, "data", "pds.db"))
STATIC_DIR = os.path.join(BASE_DIR, "static")
KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 +09:00 고정
SCHEMA_VERSION = 3
MAX_BODY = 64 * 1024

SESSION_COOKIE = "pds_session"
SESSION_DAYS = 7
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN = 2 ** 14, 8, 1, 32
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
LOGIN_FAILED = "Wrong username or password"  # 아이디가 없을 때와 비밀번호가 틀릴 때 같은 문구

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

# 새 DB용 표. 예전(v2) DB는 migrate() 가 고칩니다.
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash       TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    password_changed_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS account_deletions (
    user_id INTEGER PRIMARY KEY
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
    user_id                    INTEGER REFERENCES users(id),
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
CREATE TABLE IF NOT EXISTS day_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    note_date  TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    updated_at TEXT    NOT NULL,
    UNIQUE (user_id, note_date)
);
"""

# 표가 모두 준비된 뒤에 만드는 것들(예전 DB는 이 시점에 user_id 열이 생겨 있음)
POST_SCHEMA = """
CREATE INDEX IF NOT EXISTS todos_plan ON todos (plan_id);
CREATE INDEX IF NOT EXISTS logs_todo ON work_logs (todo_id);
CREATE INDEX IF NOT EXISTS plans_user ON plans (user_id);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
CREATE TRIGGER IF NOT EXISTS plan_versions_no_update BEFORE UPDATE ON plan_versions
BEGIN SELECT RAISE(ABORT, 'plan_versions is append-only'); END;
DROP TRIGGER IF EXISTS plan_versions_no_delete;
CREATE TRIGGER plan_versions_no_delete BEFORE DELETE ON plan_versions
WHEN NOT EXISTS (SELECT 1 FROM account_deletions d JOIN plans p ON p.user_id = d.user_id
                 WHERE p.id = OLD.plan_id)
BEGIN SELECT RAISE(ABORT, 'plan_versions is append-only'); END;
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


def kst_date_of(instant):
    """'…Z' UTC 시각 → 대한민국 날짜 'YYYY-MM-DD'"""
    return datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(KST).date().isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def table_columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn):
    """v2(로그인 없음) → v3(계정별 자료). 예전 자료는 주인 없이(user_id NULL) 남고, claim 으로 옮깁니다."""
    if "user_id" not in table_columns(conn, "plans"):
        conn.execute("ALTER TABLE plans ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if "user_id" not in table_columns(conn, "day_notes"):
        conn.executescript("""
            BEGIN;
            CREATE TABLE day_notes_v3 (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER REFERENCES users(id),
                note_date  TEXT    NOT NULL,
                body       TEXT    NOT NULL DEFAULT '',
                updated_at TEXT    NOT NULL,
                UNIQUE (user_id, note_date)
            );
            INSERT INTO day_notes_v3 (user_id, note_date, body, updated_at)
                SELECT NULL, note_date, body, updated_at FROM day_notes;
            DROP TABLE day_notes;
            ALTER TABLE day_notes_v3 RENAME TO day_notes;
            COMMIT;
        """)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    existed = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0
    conn = connect()
    try:
        # WAL은 네트워크 디스크(PythonAnywhere 등)에서 믿을 수 없어 기본 방식을 씁니다.
        conn.execute("PRAGMA journal_mode = DELETE")
        old = None
        if existed:
            try:
                r = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
                old = int(r[0]) if r else None
            except sqlite3.OperationalError:
                old = None
        if existed and (old or 0) < SCHEMA_VERSION:
            stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
            shutil.copy2(DB_PATH, f"{DB_PATH}.v{old}-backup-{stamp}")  # 고치기 전에 통째로 백업
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.executescript(POST_SCHEMA)
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


# ---------------------------------------------------------------- 비밀번호 (scrypt)
def hash_password(password):
    """되돌릴 수 없게 바꿔 저장. 계정마다 새 소금값을 쓰므로 같은 비밀번호도 저장값이 다릅니다."""
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                        maxmem=64 * 1024 * 1024, dklen=SCRYPT_LEN)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(dk)}"


def verify_password(password, stored):
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        want = base64.b64decode(dk)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                             p=int(p), maxmem=64 * 1024 * 1024, dklen=len(want))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY_HASH = []


def dummy_hash():
    # 없는 아이디로 로그인할 때도 같은 계산을 해서, 걸리는 시간으로 아이디 유무가 드러나지 않게 합니다.
    if not _DUMMY_HASH:
        _DUMMY_HASH.append(hash_password(secrets.token_hex(16)))
    return _DUMMY_HASH[0]


def read_password(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v:
        raise ApiError(400, f"{key}: required")
    return v


def check_new_password(pw):
    if len(pw) < 8:
        raise ApiError(400, "password: use at least 8 characters")
    if len(pw) > 128:
        raise ApiError(400, "password: use 128 characters or fewer")
    return pw


# ---------------------------------------------------------------- 세션
def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(conn, user_id):
    token = secrets.token_urlsafe(32)  # 256비트 무작위 값. 브라우저 쿠키에만 원문이 있음
    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (token_hash(token), user_id, now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  (now + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    return token


def read_session_token(environ):
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
    except CookieError:
        return None
    m = c.get(SESSION_COOKIE)
    return m.value if m and m.value else None


def session_user(conn, environ):
    token = read_session_token(environ)
    if not token:
        return None
    r = conn.execute("SELECT s.user_id, s.expires_at, u.username FROM sessions s JOIN users u ON u.id = s.user_id"
                     " WHERE s.token_hash = ?", (token_hash(token),)).fetchone()
    if not r:
        return None
    if r["expires_at"] <= now_utc():  # 만료: 서버에서 지우고 거절
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        return None
    return {"id": r["user_id"], "username": r["username"]}


def cookie_header(environ, value, max_age):
    secure = (environ.get("wsgi.url_scheme") == "https"
              or environ.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https")
    parts = [f"{SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
    if secure:
        parts.append("Secure")
    return ("Set-Cookie", "; ".join(parts))


# ---------------------------------------------------------------- 가입·로그인·로그아웃·계정
def signup(conn, body, ctx):
    username = req_text(body, "username", 30)
    if not USERNAME_RE.match(username):
        raise ApiError(400, "username: 3–30 letters, numbers, dot, dash or underscore")
    pw = check_new_password(read_password(body, "password"))
    pw_hash, ts = hash_password(pw), now_utc()
    with tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise ApiError(409, "That username is already taken")
        cur = conn.execute("INSERT INTO users (username, password_hash, created_at, password_changed_at)"
                           " VALUES (?,?,?,?)", (username, pw_hash, ts, ts))
        token = new_session(conn, cur.lastrowid)
    ctx["headers"].append(cookie_header(ctx["environ"], token, SESSION_DAYS * 86400))
    return {"ok": True, "user": {"id": cur.lastrowid, "username": username}}


def login(conn, body, ctx):
    username = body.get("username") if isinstance(body.get("username"), str) else ""
    pw = body.get("password") if isinstance(body.get("password"), str) else ""
    r = conn.execute("SELECT id, username, password_hash FROM users WHERE username = ?",
                     (username.strip(),)).fetchone()
    ok = verify_password(pw, r["password_hash"] if r else dummy_hash())
    if not r or not ok:
        raise ApiError(401, LOGIN_FAILED)
    with tx(conn):
        token = new_session(conn, r["id"])
    ctx["headers"].append(cookie_header(ctx["environ"], token, SESSION_DAYS * 86400))
    return {"ok": True, "user": {"id": r["id"], "username": r["username"]}}


def logout(conn, ctx):
    token = read_session_token(ctx["environ"])
    if token:
        with tx(conn):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))  # 서버에서 끊기
    ctx["headers"].append(cookie_header(ctx["environ"], "", 0))
    return {"ok": True}


def change_password(conn, user, body, ctx):
    cur_pw = read_password(body, "current_password")
    new_pw = check_new_password(read_password(body, "new_password"))
    r = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not verify_password(cur_pw, r["password_hash"]):
        raise ApiError(403, "Current password is wrong")
    new_hash = hash_password(new_pw)
    with tx(conn):
        conn.execute("UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?",
                     (new_hash, now_utc(), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))  # 이전 세션 모두 끊기
        token = new_session(conn, user["id"])
    ctx["headers"].append(cookie_header(ctx["environ"], token, SESSION_DAYS * 86400))
    return {"ok": True}


def delete_account(conn, user, body, ctx):
    pw = read_password(body, "password")
    r = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not verify_password(pw, r["password_hash"]):
        raise ApiError(403, "Password is wrong")
    uid = user["id"]
    plans_q = "SELECT id FROM plans WHERE user_id = ?"
    todos_q = f"SELECT id FROM todos WHERE plan_id IN ({plans_q})"
    with tx(conn):
        conn.execute("INSERT OR IGNORE INTO account_deletions (user_id) VALUES (?)", (uid,))
        conn.execute(f"UPDATE plans SET carried_from_reflection_id = NULL WHERE carried_from_reflection_id IN"
                     f" (SELECT id FROM reflections WHERE plan_id IN ({plans_q}))", (uid,))
        for sql in (f"DELETE FROM todo_tags WHERE todo_id IN ({todos_q})",
                    f"DELETE FROM completions WHERE todo_id IN ({todos_q})",
                    f"DELETE FROM work_logs WHERE todo_id IN ({todos_q})",
                    f"DELETE FROM todos WHERE plan_id IN ({plans_q})",
                    f"DELETE FROM reflections WHERE plan_id IN ({plans_q})",
                    f"DELETE FROM plan_versions WHERE plan_id IN ({plans_q})",
                    "DELETE FROM plans WHERE user_id = ?",
                    "DELETE FROM day_notes WHERE user_id = ?",
                    "DELETE FROM sessions WHERE user_id = ?",
                    "DELETE FROM users WHERE id = ?",
                    "DELETE FROM account_deletions WHERE user_id = ?"):
            conn.execute(sql, (uid,))
    ctx["headers"].append(cookie_header(ctx["environ"], "", 0))
    return {"ok": True, "deleted": True}


# ---------------------------------------------------------------- 계획
PLAN_FIELDS = ("title", "start_date", "end_date", "priority", "success_criteria", "estimated_minutes")


def read_plan_body(body, current=None):
    # 계획에는 이름과 완료 기준(글)만 적습니다. 날짜는 할 일마다(마감일) 정합니다.
    # 기간·우선순위·예상 시간 열은 예전 자료·버전 기록과 맞추려고 남겨 두고, 값이 오지 않으면
    # 고칠 때는 기존 값을, 새 계획은 기본값(오늘(KST)~오늘, 보통, 0분)을 씁니다.
    keep = current or {"start_date": today_kst(), "end_date": today_kst(), "priority": 2, "estimated_minutes": 0}
    for k in ("start_date", "end_date", "priority", "estimated_minutes"):
        if body.get(k) in (None, ""):
            body = {**body, k: keep[k]}
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


def plan_row(conn, uid, plan_id):
    """내 계획만. 남의 계획이거나 없으면 똑같이 404 (있는지조차 알려 주지 않음)."""
    r = conn.execute("SELECT * FROM plans WHERE id = ? AND user_id = ?", (plan_id, uid)).fetchone()
    if not r:
        raise ApiError(404, "Plan not found")
    return dict(r)


def plan_detail(conn, uid, plan_id):
    p = plan_row(conn, uid, plan_id)
    p["versions"] = [dict(r) for r in conn.execute(
        "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version", (plan_id,))]
    p["reflections"] = [dict(r) for r in conn.execute(
        "SELECT * FROM reflections WHERE plan_id = ? ORDER BY id DESC", (plan_id,))]
    for r in p["reflections"]:
        r["stats"] = json.loads(r.pop("stats_json"))
        r["carried_to_plan_ids"] = [x[0] for x in conn.execute(
            "SELECT id FROM plans WHERE carried_from_reflection_id = ? AND user_id = ? ORDER BY id", (r["id"], uid))]
    p["carried_from"] = None
    if p["carried_from_reflection_id"]:
        r = conn.execute("SELECT id, plan_id, improvement, created_at FROM reflections WHERE id = ?",
                         (p["carried_from_reflection_id"],)).fetchone()
        p["carried_from"] = dict(r) if r else None
    return p


def list_plans(conn, uid):
    rows = conn.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM todos t WHERE t.plan_id = p.id AND t.deleted_at IS NULL) AS todo_count
        FROM plans p WHERE p.user_id = ? ORDER BY p.id""", (uid,))
    return [dict(r) for r in rows]


def create_plan(conn, uid, body):
    p = read_plan_body(body)
    carried = body.get("carried_from_reflection_id")
    if carried in ("", None):
        carried = None
    else:
        carried = req_int(body, "carried_from_reflection_id", 1, 10 ** 12)
        if not conn.execute("SELECT 1 FROM reflections r JOIN plans p ON p.id = r.plan_id"
                            " WHERE r.id = ? AND p.user_id = ?", (carried, uid)).fetchone():
            raise ApiError(400, "carried_from_reflection_id: reflection not found")
    ts = now_utc()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO plans (title, start_date, end_date, priority, success_criteria, estimated_minutes,"
            " carried_from_reflection_id, current_version, created_at, updated_at, user_id)"
            " VALUES (?,?,?,?,?,?,?,1,?,?,?)",
            (*[p[k] for k in PLAN_FIELDS], carried, ts, ts, uid))
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO plan_versions (plan_id, version, title, start_date, end_date, priority,"
            " success_criteria, estimated_minutes, change_note, created_at) VALUES (?,1,?,?,?,?,?,?,?,?)",
            (pid, *[p[k] for k in PLAN_FIELDS], "Original plan", ts))
    return plan_detail(conn, uid, pid)


def update_plan(conn, uid, plan_id, body):
    note = req_text(body, "change_note", 300, required=False)
    ts = now_utc()
    with tx(conn):
        cur = plan_row(conn, uid, plan_id)  # 주인 확인이 먼저, 저장은 그다음
        p = read_plan_body(body, current=cur)
        if all(cur[k] == p[k] for k in PLAN_FIELDS):
            return plan_detail(conn, uid, plan_id)  # 바뀐 게 없으면 새 판을 만들지 않음
        ver = cur["current_version"] + 1
        conn.execute(
            "INSERT INTO plan_versions (plan_id, version, title, start_date, end_date, priority,"
            " success_criteria, estimated_minutes, change_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (plan_id, ver, *[p[k] for k in PLAN_FIELDS], note, ts))
        conn.execute(
            "UPDATE plans SET title=?, start_date=?, end_date=?, priority=?, success_criteria=?,"
            " estimated_minutes=?, current_version=?, updated_at=? WHERE id=? AND user_id=?",
            (*[p[k] for k in PLAN_FIELDS], ver, ts, plan_id, uid))
    return plan_detail(conn, uid, plan_id)


# ---------------------------------------------------------------- 할 일
def todo_row(conn, uid, todo_id, include_deleted=False):
    """내 계획에 속한 할 일만. 남의 것이면 404."""
    r = conn.execute("SELECT t.* FROM todos t JOIN plans p ON p.id = t.plan_id"
                     " WHERE t.id = ? AND p.user_id = ?", (todo_id, uid)).fetchone()
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


def todo_detail(conn, uid, todo_id):
    t = decorate_todos(conn, [todo_row(conn, uid, todo_id)])[0]
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


def list_todos(conn, uid, qs):
    # 목록도 한 건 조회와 같은 주인 조건을 붙입니다(내 계획의 할 일만).
    where, args = ["t.deleted_at IS NULL", "t.plan_id IN (SELECT id FROM plans WHERE user_id = ?)"], [uid]
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


def create_todo(conn, uid, body):
    plan_id = req_int(body, "plan_id", 1, 10 ** 12)
    t, tags, ts = read_todo_body(body), parse_tags(body.get("tags")), now_utc()
    with tx(conn):
        plan_row(conn, uid, plan_id)  # 남의 계획에는 넣을 수 없음(404)
        cur = conn.execute(
            "INSERT INTO todos (plan_id, title, note, due_date, priority, estimated_minutes, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,'open',?,?)",
            (plan_id, t["title"], t["note"], t["due_date"], t["priority"], t["estimated_minutes"], ts, ts))
        set_tags(conn, cur.lastrowid, tags)
    return todo_detail(conn, uid, cur.lastrowid)


def update_todo(conn, uid, todo_id, body):
    t, tags = read_todo_body(body), parse_tags(body.get("tags"))
    with tx(conn):
        cur = todo_row(conn, uid, todo_id)  # 주인 확인이 먼저, 저장은 그다음
        # 다른 계획으로 옮기기: plan_id 를 보내면 그 계획으로. 내 계획이어야 함(남의 계획은 404).
        # 실행 기록·완료 기록은 할 일에 딸려 있어 함께 옮겨짐.
        plan_id = cur["plan_id"]
        if body.get("plan_id") not in (None, ""):
            plan_id = req_int(body, "plan_id", 1, 10 ** 12)
            plan_row(conn, uid, plan_id)
        conn.execute("UPDATE todos SET plan_id=?, title=?, note=?, due_date=?, priority=?, estimated_minutes=?,"
                     " updated_at=? WHERE id=?", (plan_id, t["title"], t["note"], t["due_date"], t["priority"],
                                                  t["estimated_minutes"], now_utc(), todo_id))
        set_tags(conn, todo_id, tags)
    return todo_detail(conn, uid, todo_id)


def delete_todo(conn, uid, todo_id):
    with tx(conn):
        todo_row(conn, uid, todo_id)
        ts = now_utc()
        conn.execute("UPDATE todos SET deleted_at=?, updated_at=? WHERE id=?", (ts, ts, todo_id))
    return {"ok": True, "id": todo_id}


def complete_todo(conn, uid, todo_id, body):
    """완료 처리. 같은 키로 여러 번 와도, 키가 달라도, 진행 중인 완료 기록은 한 건만 남습니다."""
    key = req_text(body, "idempotency_key", 100)
    with tx(conn):
        t = todo_row(conn, uid, todo_id)
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
    d = todo_detail(conn, uid, todo_id)
    d["created"] = created
    return d


def reopen_todo(conn, uid, todo_id):
    with tx(conn):
        t = todo_row(conn, uid, todo_id)
        if t["status"] == "done":
            ts = now_utc()
            conn.execute("UPDATE completions SET undone_at=? WHERE todo_id=? AND undone_at IS NULL", (ts, todo_id))
            conn.execute("UPDATE todos SET status='open', updated_at=? WHERE id=?", (ts, todo_id))
    return todo_detail(conn, uid, todo_id)


# ---------------------------------------------------------------- 실행 기록
def create_log(conn, uid, todo_id, body):
    start, end = req_instant(body, "started_at"), req_instant(body, "ended_at")
    if end < start:
        raise ApiError(400, "ended_at: cannot be before the start time")
    computed = round((end - start).total_seconds() / 60)
    raw = body.get("actual_minutes")
    minutes = computed if raw in (None, "") else req_int(body, "actual_minutes", 0, 100000)
    blocker = req_text(body, "blocker", 1000, required=False)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    with tx(conn):
        todo_row(conn, uid, todo_id)
        cur = conn.execute(
            "INSERT INTO work_logs (todo_id, started_at, ended_at, actual_minutes, blocker, created_at)"
            " VALUES (?,?,?,?,?,?)", (todo_id, start.strftime(fmt), end.strftime(fmt), minutes, blocker, now_utc()))
    return dict(conn.execute("SELECT * FROM work_logs WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_logs(conn, uid, qs):
    where, args = ["t.deleted_at IS NULL", "p.user_id = ?"], [uid]
    if qs.get("plan_id"):
        where.append("t.plan_id = ?")
        args.append(get_id(qs["plan_id"]))
    if qs.get("ids"):
        id_list = [get_id(x) for x in qs["ids"].split(",") if x][:500]
        where.append(f"w.id IN ({','.join('?' * len(id_list))})")
        args += id_list
    rows = conn.execute(
        f"SELECT w.*, t.title AS todo_title, t.plan_id, t.estimated_minutes AS todo_estimated_minutes"
        f" FROM work_logs w JOIN todos t ON t.id = w.todo_id JOIN plans p ON p.id = t.plan_id"
        f" WHERE {' AND '.join(where)} ORDER BY w.started_at DESC, w.id DESC", args)
    return [dict(r) for r in rows]


def delete_log(conn, uid, log_id):
    with tx(conn):
        n = conn.execute("DELETE FROM work_logs WHERE id = ? AND todo_id IN (SELECT t.id FROM todos t"
                         " JOIN plans p ON p.id = t.plan_id WHERE p.user_id = ?)", (log_id, uid)).rowcount
        if n == 0:
            raise ApiError(404, "Work log not found")
    return {"ok": True, "id": log_id}


# ---------------------------------------------------------------- 돌아보기
OUTLIER_MINUTES = 720  # 기록 한 건이 12시간을 넘으면 '튀는 값'으로 표시(합계에는 넣음)
DAILY_MAX_DAYS = 62


def daily_table(conn, plan, todos, logs, period_from, period_to):
    """날짜별(대한민국 기준) 실행 시간·완료 수와 합계·평균.

    - 날짜: 실행 기록은 시작 시각, 완료는 완료 시각의 대한민국 날짜
    - 빠진 날: 기록이 없는 날도 0분으로 줄에 넣고 평균의 날짜 수에 셈
    - 중복: 같은 할 일·같은 시작·같은 끝 시각의 기록은 한 번만 셈
    - 튀는 값: 한 건이 720분을 넘으면 표시만 하고 합계에는 넣음
    - 반올림: 평균은 소수 첫째 자리까지, 사사오입(ROUND_HALF_UP)
    """
    # 기간을 따로 고르지 않으면: 계획 시작일(새 계획은 만든 날) 또는 그보다 이른 마감일·기록부터 오늘(KST)까지
    first = [plan["start_date"]] + [t["due_date"] for t in todos if t["due_date"]] \
        + [kst_date_of(w["started_at"]) for w in logs]
    d_from = period_from or min(first)
    d_to = period_to or today_kst()
    if d_to < d_from:
        d_to = d_from
    start = date.fromisoformat(d_from)
    days = []
    while len(days) < DAILY_MAX_DAYS and start.isoformat() <= d_to:
        days.append(start.isoformat())
        start += timedelta(days=1)
    rows = {d: {"date": d, "logs": 0, "actual_minutes": 0, "done": 0, "duplicates": 0, "outliers": 0}
            for d in days}
    seen = set()
    for w in logs:
        d = kst_date_of(w["started_at"])
        if d not in rows:
            continue
        key = (w["todo_id"], w["started_at"], w["ended_at"])
        if key in seen:
            rows[d]["duplicates"] += 1
            continue
        seen.add(key)
        rows[d]["logs"] += 1
        rows[d]["actual_minutes"] += w["actual_minutes"]
        if w["actual_minutes"] > OUTLIER_MINUTES:
            rows[d]["outliers"] += 1
    ids = [t["id"] for t in todos]
    if ids:
        for c in conn.execute(f"SELECT completed_at FROM completions WHERE undone_at IS NULL AND todo_id IN"
                              f" ({','.join('?' * len(ids))})", ids):
            d = kst_date_of(c["completed_at"])
            if d in rows:
                rows[d]["done"] += 1
    out = [rows[d] for d in days]
    n = len(out)
    total_min = sum(r["actual_minutes"] for r in out)
    total_done = sum(r["done"] for r in out)

    def avg(x):
        return float((Decimal(x) / Decimal(n)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if n else 0.0
    return {"from": days[0] if days else d_from, "to": days[-1] if days else d_to, "days": n, "rows": out,
            "total": {"actual_minutes": total_min, "done": total_done, "logs": sum(r["logs"] for r in out)},
            "average": {"actual_minutes": avg(total_min), "done": avg(total_done)},
            "rules": {"date": "Korea (KST) date of the log's start time / the completion time",
                      "missing": "days with no records count as 0 and are included in the average",
                      "duplicates": "logs with the same to-do, start and end are counted once",
                      "outliers": f"a single log over {OUTLIER_MINUTES} min is flagged but still counted",
                      "rounding": "averages to 1 decimal place, half up",
                      "week_starts": "Sunday"}}


def review(conn, uid, plan_id, qs):
    plan = plan_row(conn, uid, plan_id)
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
    # 날짜별 표는 기간 안 '모든' 할 일의 기록을 봅니다(마감일 기간과 무관하게, 기록한 날 기준).
    all_todos = conn.execute("SELECT * FROM todos WHERE plan_id = ? AND deleted_at IS NULL", (plan_id,)).fetchall()
    all_ids = [t["id"] for t in all_todos]
    all_logs = conn.execute(f"SELECT * FROM work_logs WHERE todo_id IN ({','.join('?' * len(all_ids))})"
                            f" ORDER BY id", all_ids).fetchall() if all_ids else []
    return {"plan_id": plan_id, "plan_title": plan["title"], "today_kst": today,
            "period": {"from": period_from, "to": period_to},
            "stats": stats, "evidence": evidence,
            "daily": daily_table(conn, plan, all_todos, all_logs, period_from, period_to)}


def create_reflection(conn, uid, plan_id, body):
    improvement = req_text(body, "improvement", 300)
    note = req_text(body, "note", 2000, required=False)
    qs = {"from": body.get("from") or None, "to": body.get("to") or None}
    r = review(conn, uid, plan_id, qs)
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO reflections (plan_id, period_from, period_to, note, improvement, stats_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (plan_id, r["period"]["from"], r["period"]["to"], note, improvement,
             json.dumps(r["stats"], ensure_ascii=False), now_utc()))
    return plan_detail(conn, uid, plan_id) | {"new_reflection_id": cur.lastrowid}


# ---------------------------------------------------------------- 날짜별 메모
def get_note(conn, uid, day):
    r = conn.execute("SELECT note_date, body, updated_at FROM day_notes WHERE user_id = ? AND note_date = ?",
                     (uid, day)).fetchone()
    return dict(r) if r else {"note_date": day, "body": "", "updated_at": None}


def put_note(conn, uid, day, body):
    text = body.get("body", "")
    if not isinstance(text, str):
        raise ApiError(400, "body: must be text")
    if len(text) > 5000:
        raise ApiError(400, "body: must be 5000 characters or fewer")
    with tx(conn):
        conn.execute("INSERT INTO day_notes (user_id, note_date, body, updated_at) VALUES (?,?,?,?)"
                     " ON CONFLICT(user_id, note_date) DO UPDATE SET body = excluded.body,"
                     " updated_at = excluded.updated_at", (uid, day, text, now_utc()))
    return get_note(conn, uid, day)


def list_notes(conn, uid, qs):
    lo, hi = req_date(qs, "from"), req_date(qs, "to")
    rows = conn.execute("SELECT note_date FROM day_notes WHERE user_id = ? AND body <> ''"
                        " AND note_date BETWEEN ? AND ? ORDER BY note_date", (uid, lo, hi))
    return [r[0] for r in rows]


# ---------------------------------------------------------------- 내보내기 (내 자료만)
def export_all(conn, user):
    uid = user["id"]
    plans_q = "SELECT id FROM plans WHERE user_id = ?"
    todos_q = f"SELECT id FROM todos WHERE plan_id IN ({plans_q})"
    out = {"app": "plan-do-see-diary", "schema_version": SCHEMA_VERSION, "exported_at": now_utc(),
           "account": {"username": user["username"]},
           "time_rules": {"instants": "UTC ISO-8601 (Z)", "dates": "Korea (KST, UTC+9, Asia/Seoul) calendar date YYYY-MM-DD",
                          "durations": "minutes (integer)"}}
    queries = {
        "plans": ("SELECT * FROM plans WHERE user_id = ? ORDER BY id", uid),
        "plan_versions": (f"SELECT * FROM plan_versions WHERE plan_id IN ({plans_q}) ORDER BY id", uid),
        "todos": (f"SELECT * FROM todos WHERE plan_id IN ({plans_q}) ORDER BY id", uid),
        "todo_tags": (f"SELECT * FROM todo_tags WHERE todo_id IN ({todos_q}) ORDER BY rowid", uid),
        "completions": (f"SELECT * FROM completions WHERE todo_id IN ({todos_q}) ORDER BY id", uid),
        "work_logs": (f"SELECT * FROM work_logs WHERE todo_id IN ({todos_q}) ORDER BY id", uid),
        "reflections": (f"SELECT * FROM reflections WHERE plan_id IN ({plans_q}) ORDER BY id", uid),
        "day_notes": ("SELECT note_date, body, updated_at FROM day_notes WHERE user_id = ? ORDER BY note_date", uid),
    }
    for table, (sql, arg) in queries.items():
        out[table] = [dict(r) for r in conn.execute(sql, (arg,))]
    return out


# ---------------------------------------------------------------- 라우팅
def route(method, path, qs, body, conn, ctx):
    parts = [p for p in path.split("/") if p][1:]  # 'api' 다음부터
    n = len(parts)
    if parts == ["meta"] and method == "GET":
        return {"today_kst": today_kst(), "schema_version": SCHEMA_VERSION}
    # --- 로그인 없이 부를 수 있는 것: 가입·로그인·로그아웃·내가 누구인지
    if parts[:1] == ["auth"]:
        if parts == ["auth", "signup"] and method == "POST":
            return signup(conn, body, ctx)
        if parts == ["auth", "login"] and method == "POST":
            return login(conn, body, ctx)
        if parts == ["auth", "logout"] and method == "POST":
            return logout(conn, ctx)
        if parts == ["auth", "me"] and method == "GET":
            if not ctx["user"]:
                raise ApiError(401, "Please log in")
            return {"user": ctx["user"]}
    # --- 여기부터는 로그인한 사람만. 모든 조회에 그 사람의 id(uid)를 넘깁니다.
    user = ctx["user"]
    if not user:
        raise ApiError(401, "Please log in")
    uid = user["id"]
    if parts == ["auth", "password"] and method == "POST":
        return change_password(conn, user, body, ctx)
    if parts == ["auth", "delete-account"] and method == "POST":
        return delete_account(conn, user, body, ctx)
    if parts == ["plans"]:
        if method == "GET":
            return list_plans(conn, uid)
        if method == "POST":
            return create_plan(conn, uid, body)
    if n == 2 and parts[0] == "plans":
        pid = get_id(parts[1])
        if method == "GET":
            return plan_detail(conn, uid, pid)
        if method == "PUT":
            return update_plan(conn, uid, pid, body)
    if n == 3 and parts[0] == "plans" and parts[2] == "review" and method == "GET":
        return review(conn, uid, get_id(parts[1]), qs)
    if n == 3 and parts[0] == "plans" and parts[2] == "reflections" and method == "POST":
        return create_reflection(conn, uid, get_id(parts[1]), body)
    if parts == ["todos"]:
        if method == "GET":
            return list_todos(conn, uid, qs)
        if method == "POST":
            return create_todo(conn, uid, body)
    if n == 2 and parts[0] == "todos":
        tid = get_id(parts[1])
        if method == "GET":
            return todo_detail(conn, uid, tid)
        if method == "PUT":
            return update_todo(conn, uid, tid, body)
        if method == "DELETE":
            return delete_todo(conn, uid, tid)
    if n == 3 and parts[0] == "todos" and method == "POST":
        tid = get_id(parts[1])
        if parts[2] == "complete":
            return complete_todo(conn, uid, tid, body)
        if parts[2] == "reopen":
            return reopen_todo(conn, uid, tid)
        if parts[2] == "logs":
            return create_log(conn, uid, tid, body)
    if parts == ["logs"] and method == "GET":
        return list_logs(conn, uid, qs)
    if n == 2 and parts[0] == "logs" and method == "DELETE":
        return delete_log(conn, uid, get_id(parts[1]))
    if parts == ["notes"] and method == "GET":
        return list_notes(conn, uid, qs)
    if n == 2 and parts[0] == "notes":
        day = req_date({"date": parts[1]}, "date")
        if method == "GET":
            return get_note(conn, uid, day)
        if method == "PUT":
            return put_note(conn, uid, day, body)
    if parts == ["export"] and method == "GET":
        return export_all(conn, user)
    raise ApiError(404, "Not found")


def respond(start_response, status, body_bytes, ctype, extra=()):
    headers = [("Content-Type", ctype), ("Content-Length", str(len(body_bytes)))] + SECURITY_HEADERS + list(extra)
    start_response(status, headers)
    return [body_bytes]


STATUS_TEXT = {200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 401: "401 Unauthorized",
               403: "403 Forbidden", 404: "404 Not Found",
               405: "405 Method Not Allowed", 409: "409 Conflict", 413: "413 Payload Too Large",
               429: "429 Too Many Requests", 500: "500 Internal Server Error"}


# ---------------------------------------------------------------- 자동 배포(GitHub 웹훅)
# GitHub에 푸시하면 GitHub가 POST /api/deploy 로 알려 주고, 서버가 git pull 후 웹 앱을 다시 시작합니다.
# 암호(비밀값)는 쓰지 않습니다. 대신 안전하게 만드는 규칙:
# - 받아오는 곳은 이 저장소의 origin(내 GitHub 저장소) 하나뿐 → 누가 불러도 이미 올라간 코드만 받음
# - --ff-only: 서버 폴더를 덮어쓰거나 합치지 않음
# - 코드가 실제로 바뀐 때만 다시 시작, 짧은 시간에 여러 번 부르면 무시(429)
# - PythonAnywhere(WSGI 파일이 있는 곳)에서만 켜짐. 내 PC에서 실행할 때는 404
DEPLOY_BRANCH = "refs/heads/main"
DEPLOY_MAX_BODY = 5 * 1024 * 1024
DEPLOY_COOLDOWN = 15  # 초
_deploy_state = {"last": 0.0}


def wsgi_file():
    """PythonAnywhere는 WSGI 파일의 수정 시각이 바뀌면 웹 앱을 다시 시작합니다."""
    p = os.environ.get("PDS_WSGI_FILE")
    if p:
        return p
    import getpass
    return f"/var/www/{getpass.getuser().lower()}_pythonanywhere_com_wsgi.py"


def deploy_enabled():
    return os.path.exists(wsgi_file())


def git(*args):
    import subprocess
    r = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=90)
    return r.returncode, (r.stdout + r.stderr).strip()[-1500:]


def run_git_pull():
    """(성공 여부 코드, git 메시지, 코드가 바뀌었는지)"""
    _, before = git("rev-parse", "HEAD")
    code, out = git("pull", "--ff-only")
    _, after = git("rev-parse", "HEAD")
    return code, out, code == 0 and before != after


def reload_later():
    def touch():
        p = wsgi_file()
        if os.path.exists(p):
            os.utime(p, None)
    import threading
    threading.Timer(1.0, touch).start()  # 응답을 먼저 보내고 다시 시작


def handle_deploy(environ):
    import time
    if environ.get("REQUEST_METHOD") != "POST" or not deploy_enabled():
        return 404, {"error": "Not found"}
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > DEPLOY_MAX_BODY:
        return 413, {"error": "Request body is too large"}
    raw = environ["wsgi.input"].read(length) if length else b""
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
    now = time.monotonic()
    if now - _deploy_state["last"] < DEPLOY_COOLDOWN:
        return 429, {"ok": False, "error": "Too soon, try again shortly"}
    _deploy_state["last"] = now
    code, out, changed = run_git_pull()
    if code != 0:
        return 500, {"ok": False, "git": out}
    if changed:
        reload_later()
    return 200, {"ok": True, "git": out, "reloading": changed}


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
    ctx = {"environ": environ, "user": None, "headers": extra}
    conn = None
    try:
        body = {}
        if method in ("POST", "PUT", "DELETE"):
            # 다른 사이트가 내 쿠키를 싣고 몰래 보내는 요청(CSRF) 막기: 이 앱의 화면만 붙이는 헤더가 있어야 함.
            # 다른 사이트의 form 은 이 헤더를 붙일 수 없고, fetch 로 붙이면 브라우저가 먼저 허락을 묻는데(CORS) 허락하지 않음.
            if environ.get("HTTP_X_PDS") != "1":
                raise ApiError(403, "Missing X-PDS header")
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
        ctx["user"] = session_user(conn, environ)
        payload = route(method, path, qs, body, conn, ctx)
        if method == "POST" and not path.endswith(("/complete", "/reopen")) and not path.startswith("/api/auth/"):
            status = 201
        if path == "/api/export":
            stamp = datetime.now(KST).strftime("%Y%m%d-%H%M")
            extra.append(("Content-Disposition", f'attachment; filename="pds-diary-export-{stamp}.json"'))
    except ApiError as e:
        status, payload = e.status, {"error": e.message}
    except sqlite3.IntegrityError:
        status, payload = 409, {"error": "Violates a storage rule"}
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


# ---------------------------------------------------------------- 6번 자료를 내 계정으로 옮기기
def claim_unowned(username):
    """주인 없는(6번 때 만든) 계획·메모를 이 계정으로 옮깁니다. PythonAnywhere 콘솔에서 한 번 실행."""
    conn = connect()
    try:
        u = conn.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
        if not u:
            return f"No account named {username!r}. Sign up on the site first."
        with tx(conn):
            plans = conn.execute("UPDATE plans SET user_id = ? WHERE user_id IS NULL", (u["id"],)).rowcount
            notes = conn.execute("UPDATE OR IGNORE day_notes SET user_id = ? WHERE user_id IS NULL",
                                 (u["id"],)).rowcount
            left = conn.execute("SELECT COUNT(*) FROM day_notes WHERE user_id IS NULL").fetchone()[0]
        msg = f"Moved {plans} plan(s) and {notes} daily note(s) to {u['username']}."
        if left:
            msg += f" {left} note(s) were left because that day already has a note in this account."
        return msg
    finally:
        conn.close()


init_db()

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "claim":
        print(claim_unowned(sys.argv[2]))
        sys.exit(0)
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt, *args):  # 요청 줄(주소)만 남기고, 본문·쿠키는 남기지 않음
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    with make_server(host, port, application, server_class=ThreadingWSGIServer, handler_class=QuietHandler) as srv:
        print(f"Plan-Do-See Diary: http://{host}:{port}  (DB: {DB_PATH})")
        srv.serve_forever()
