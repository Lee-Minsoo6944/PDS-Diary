"""자기소개 페이지(/me/)의 비공개 영역과 패스키 인증 (과제 8).

공개 소개 페이지는 정적 파일(static/me/index.html)이라 누구나 열 수 있고, 그 파일에는 비공개 내용이 없습니다.
비공개 내용은 패스키로 들어온 사람에게만 /api/me/items 가 JSON 으로 보냅니다.

흐름(모두 이 파일)
- 등록:   register_options → (브라우저가 인증기에서 키 쌍 생성) → register_verify
- 로그인: login_options    → (인증기가 챌린지에 서명)           → login_verify
- 로그아웃: logout   · 비공개 자료: list_items / get_item / create_item / delete_item
- 패스키 관리: list_passkeys / delete_passkey (두 번째 패스키는 register_options 를 로그인한 채로 부름)

다이어리(과제 7)와는 계정·세션·표를 따로 씁니다. 비밀번호는 어디에도 없습니다.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie

import passkey
from passkey import WebAuthnError

ME_COOKIE = "me_session"
ME_SESSION_HOURS = 12
CHALLENGE_SECONDS = 300  # 챌린지는 5분 안에만 쓸 수 있고, 한 번 쓰면 끝
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
RP_NAME = "Lee Minsoo · About me"
# 패스키를 쓸 수 있는 주소. 패스키는 https 에서만 되고, 개발 중에는 http://localhost 만 예외입니다.
ORIGINS = [o.strip() for o in os.environ.get("ME_ORIGINS", "https://alstn.pythonanywhere.com").split(",")
           if o.strip()]

SCHEMA = """
CREATE TABLE IF NOT EXISTS me_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    user_handle TEXT    NOT NULL UNIQUE,          -- WebAuthn user.id (무작위 16바이트, 이름과 무관)
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS me_credentials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES me_accounts(id),
    credential_id   TEXT    NOT NULL UNIQUE,      -- 인증기가 정한 자격 증명 ID (base64url)
    public_key      TEXT    NOT NULL,             -- COSE 형식 공개키 (base64url). 개인키는 서버에 없음
    alg             INTEGER NOT NULL,             -- -7 = ES256, -257 = RS256
    sign_count      INTEGER NOT NULL DEFAULT 0,
    name            TEXT    NOT NULL,             -- 사람이 알아볼 이름
    aaguid          TEXT    NOT NULL,
    backup_eligible INTEGER NOT NULL,
    backed_up       INTEGER NOT NULL,
    transports      TEXT    NOT NULL DEFAULT '',
    fmt             TEXT    NOT NULL DEFAULT 'none',
    created_at      TEXT    NOT NULL,
    last_used_at    TEXT
);
CREATE TABLE IF NOT EXISTS me_challenges (
    challenge    TEXT    PRIMARY KEY,             -- 32바이트 무작위 값 (base64url)
    purpose      TEXT    NOT NULL CHECK (purpose IN ('register', 'login')),
    account_id   INTEGER,                         -- 패스키 추가·아이디를 적은 로그인일 때 그 계정
    username     TEXT,                            -- 새 계정 등록일 때 만들 이름
    user_handle  TEXT,
    passkey_name TEXT,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    used_at      TEXT                             -- 한 번 쓰면 시각을 적고 다시는 통과시키지 않음
);
CREATE TABLE IF NOT EXISTS me_sessions (
    token_hash TEXT    PRIMARY KEY,               -- 쿠키 값의 SHA-256 만 저장
    account_id INTEGER NOT NULL REFERENCES me_accounts(id),
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS me_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES me_accounts(id),
    category   TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS me_credentials_account ON me_credentials (account_id);
CREATE INDEX IF NOT EXISTS me_items_account ON me_items (account_id);
"""

CATEGORIES = {"project": "준비 중인 프로젝트", "apply": "지원하려는 곳", "retro": "개인 회고", "memo": "메모"}

# 새 계정에 넣어 두는 예시 자료. 모두 지어낸 내용이며 실제 개인정보가 아닙니다.
SEED_ITEMS = [
    ("project", "준비 중인 프로젝트 메모 (가상)",
     "주말 풋살 모임 출석 체크 앱 — 12월 첫 주까지 화면 초안, 회비 정산은 다음 단계. (지어낸 메모)"),
    ("apply", "지원하려는 곳 목록 (가상)",
     "① 한빛데이터랩(가상 회사) 데이터 분석 인턴 — 마감 12/01\n"
     "② 푸른바다소프트(가상 회사) 보안 관제 신입 — 마감 12/15\n"
     "③ 은하수공사(가상 기관) 정보화 담당 — 공고 대기"),
    ("retro", "11월 개인 회고 (가상)",
     "잘한 것: 매일 30분 코딩 기록. 아쉬운 것: 테니스 레슨 두 번 빠짐. 다음 달: 회고를 주 1회로. (지어낸 회고)"),
]

# 화면에 '어디에 저장된 패스키인지' 추정해 보여 주려고 쓰는 AAGUID(인증기 종류 번호) 표. 공개된 값입니다.
KNOWN_AAGUIDS = {
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google 비밀번호 관리자",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome (Mac)",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "Apple iCloud 키체인",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "Apple iCloud 키체인",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "cb69481e-8ff7-4039-93ec-0a2729a154a8": "YubiKey 5 (보안 키)",
    "ee882879-721c-4913-9775-3dfcce97072a": "YubiKey 5 (보안 키)",
    "fa2b99dc-9e39-4257-8f92-4a30d23c4118": "YubiKey 5 NFC (보안 키)",
}


class Ctx:
    """app.py 의 ApiError·tx·now_utc 를 받아 씁니다(순환 import 를 피하려고 init 에서 넣음)."""
    ApiError = None
    tx = None
    now_utc = None


def init(api_error, tx, now_utc):
    Ctx.ApiError, Ctx.tx, Ctx.now_utc = api_error, tx, now_utc


def err(status, message):
    return Ctx.ApiError(status, message)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------- 이 요청이 어느 사이트(rpId·origin)인지
def site(environ):
    """(rpId, origin). 정해 둔 주소와 http://localhost:<포트> 만 받습니다. 127.0.0.1 은 패스키 규칙상 안 됩니다."""
    host = environ.get("HTTP_HOST", "")
    for o in ORIGINS:
        if o.split("://", 1)[-1] == host:
            return host.split(":")[0], o
    if re.fullmatch(r"localhost(:\d{1,5})?", host):
        return "localhost", f"http://{host}"
    raise err(400, "Passkeys work only on https://alstn.pythonanywhere.com/me/ (or http://localhost during development)")


# ---------------------------------------------------------------- 세션 (쿠키에는 무작위 값, DB에는 그 해시)
def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def read_token(environ):
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw)
    except CookieError:
        return None
    m = c.get(ME_COOKIE)
    return m.value if m and m.value else None


def session_account(conn, environ):
    token = read_token(environ)
    if not token:
        return None
    r = conn.execute("SELECT s.account_id, s.expires_at, a.username FROM me_sessions s"
                     " JOIN me_accounts a ON a.id = s.account_id WHERE s.token_hash = ?",
                     (token_hash(token),)).fetchone()
    if not r:
        return None
    if r["expires_at"] <= Ctx.now_utc():
        conn.execute("DELETE FROM me_sessions WHERE token_hash = ?", (token_hash(token),))
        return None
    return {"id": r["account_id"], "username": r["username"]}


def cookie(environ, value, max_age):
    secure = (environ.get("wsgi.url_scheme") == "https"
              or environ.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https")
    parts = [f"{ME_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={max_age}"]
    if secure:
        parts.append("Secure")
    return ("Set-Cookie", "; ".join(parts))


def start_session(conn, ctx, account_id):
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute("INSERT INTO me_sessions (token_hash, account_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (token_hash(token), account_id, iso(now), iso(now + timedelta(hours=ME_SESSION_HOURS))))
    ctx["headers"].append(cookie(ctx["environ"], token, ME_SESSION_HOURS * 3600))


# ---------------------------------------------------------------- 챌린지 (서버가 만들고, 보관하고, 한 번만 받음)
def new_challenge(conn, purpose, account_id=None, username=None, user_handle=None, passkey_name=None):
    now = utcnow()
    # 하루 넘은 챌린지는 정리(쓴 것도 하루는 남겨 '이미 썼음'을 알려 줌)
    conn.execute("DELETE FROM me_challenges WHERE expires_at < ?", (iso(now - timedelta(days=1)),))
    challenge = passkey.b64url(secrets.token_bytes(32))
    conn.execute("INSERT INTO me_challenges (challenge, purpose, account_id, username, user_handle, passkey_name,"
                 " created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                 (challenge, purpose, account_id, username, user_handle, passkey_name, iso(now),
                  iso(now + timedelta(seconds=CHALLENGE_SECONDS))))
    return challenge


def consume_challenge(conn, challenge, purpose, status):
    """보관해 둔 챌린지를 '썼음'으로 바꾸고 그 줄을 돌려줍니다. 검사보다 먼저 따로 저장(COMMIT)하므로,
    뒤에서 서명 검사가 실패해도 같은 챌린지로 다시 시도할 수 없습니다."""
    with Ctx.tx(conn):
        row = conn.execute("SELECT * FROM me_challenges WHERE challenge = ? AND purpose = ?",
                           (challenge, purpose)).fetchone()
        if not row:
            raise err(status, "Unknown challenge — ask the server for a new one")
        if row["used_at"]:
            raise err(status, "This challenge was already used")
        if row["expires_at"] <= Ctx.now_utc():
            raise err(status, "This challenge has expired")
        done = conn.execute("UPDATE me_challenges SET used_at = ? WHERE challenge = ? AND used_at IS NULL",
                            (Ctx.now_utc(), challenge)).rowcount
        if done != 1:
            raise err(status, "This challenge was already used")
    return row


def cancel_challenge(conn, body):
    """등록·로그인 창을 사용자가 닫았을 때: 아직 안 쓴 챌린지를 지워 서버에 아무것도 남기지 않습니다."""
    ch = body.get("challenge")
    if isinstance(ch, str):
        with Ctx.tx(conn):
            conn.execute("DELETE FROM me_challenges WHERE challenge = ? AND used_at IS NULL", (ch,))
    return {"ok": True}


# ---------------------------------------------------------------- 입력
def text(body, key, max_len, required=True):
    v = body.get(key, "")
    if not isinstance(v, str):
        raise err(400, f"{key}: must be text")
    v = v.strip()
    if required and not v:
        raise err(400, f"{key}: required")
    if len(v) > max_len:
        raise err(400, f"{key}: {max_len} characters or fewer")
    return v


def credential_of(body):
    c = body.get("credential")
    if not isinstance(c, dict):
        raise err(400, "credential: required")
    return c


def storage_guess(aaguid, backup_eligible, transports):
    name = KNOWN_AAGUIDS.get(aaguid)
    kind = "여러 기기에 동기화됨" if backup_eligible else "이 인증기에만 있음"
    if name:
        return f"{name} · {kind}"
    if not backup_eligible and any(t in ("usb", "nfc", "ble") for t in transports.split(",")):
        return "보안 키 · 이 인증기에만 있음"
    if backup_eligible:
        return "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨"
    return "이 기기 · 이 인증기에만 있음"


def public_passkey(r):
    try:
        key = passkey.cose_summary(passkey.b64url_decode(r["public_key"]))
    except WebAuthnError:
        key = {"alg": str(r["alg"])}
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
            "storage": storage_guess(r["aaguid"], r["backup_eligible"], r["transports"]),
            "aaguid": r["aaguid"], "backup_eligible": bool(r["backup_eligible"]), "backed_up": bool(r["backed_up"]),
            "transports": [t for t in r["transports"].split(",") if t],
            "credential_id": r["credential_id"], "public_key": key}


# ---------------------------------------------------------------- 등록 (새 계정 · 로그인한 계정에 패스키 추가)
def register_options(conn, body, ctx):
    rp_id, _ = site(ctx["environ"])
    account = ctx["account"]
    pk_name = text(body, "passkey_name", 40)
    with Ctx.tx(conn):
        if account:  # 두 번째·세 번째 패스키 추가
            a = conn.execute("SELECT * FROM me_accounts WHERE id = ?", (account["id"],)).fetchone()
            username, handle = a["username"], a["user_handle"]
            challenge = new_challenge(conn, "register", account_id=a["id"], passkey_name=pk_name)
            exclude = [r["credential_id"] for r in
                       conn.execute("SELECT credential_id FROM me_credentials WHERE account_id = ?", (a["id"],))]
        else:  # 새 계정
            username = text(body, "username", 30)
            if not USERNAME_RE.match(username):
                raise err(400, "username: 3–30 letters, numbers, dot, dash or underscore")
            if conn.execute("SELECT 1 FROM me_accounts WHERE username = ?", (username,)).fetchone():
                raise err(409, "That username is already taken")
            handle = passkey.b64url(secrets.token_bytes(16))
            challenge = new_challenge(conn, "register", username=username, user_handle=handle, passkey_name=pk_name)
            exclude = []
    return {"publicKey": {
        "challenge": challenge,
        "rp": {"id": rp_id, "name": RP_NAME},
        "user": {"id": handle, "name": username, "displayName": username},
        "pubKeyCredParams": [{"type": "public-key", "alg": passkey.ALG_ES256},
                             {"type": "public-key", "alg": passkey.ALG_RS256}],
        "timeout": CHALLENGE_SECONDS * 1000,
        "attestation": "none",
        "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True,
                                   "userVerification": "required"},
        # 이 계정에 이미 있는 패스키. 같은 인증기에 두 번 만들지 않게 브라우저가 막습니다.
        "excludeCredentials": [{"type": "public-key", "id": c} for c in exclude],
    }}


def register_verify(conn, body, ctx):
    rp_id, origin = site(ctx["environ"])
    cred = credential_of(body)
    try:
        challenge = passkey.read_challenge(cred, "webauthn.create", origin)
    except WebAuthnError as e:
        raise err(400, str(e))
    row = consume_challenge(conn, challenge, "register", 400)
    account = ctx["account"]
    if row["account_id"] is not None and (not account or account["id"] != row["account_id"]):
        raise err(403, "This challenge was issued to a different account")
    if row["account_id"] is None and account:
        raise err(400, "Log out before creating a new account")
    try:
        reg = passkey.verify_registration(cred, row["challenge"], rp_id, origin)
    except WebAuthnError as e:
        raise err(400, str(e))
    now = Ctx.now_utc()
    with Ctx.tx(conn):
        if conn.execute("SELECT 1 FROM me_credentials WHERE credential_id = ?", (reg["credential_id"],)).fetchone():
            raise err(409, "This passkey is already registered")
        if row["account_id"] is None:
            if conn.execute("SELECT 1 FROM me_accounts WHERE username = ?", (row["username"],)).fetchone():
                raise err(409, "That username is already taken")
            account_id = conn.execute("INSERT INTO me_accounts (username, user_handle, created_at) VALUES (?,?,?)",
                                      (row["username"], row["user_handle"], now)).lastrowid
            for cat, title, text_ in SEED_ITEMS:
                conn.execute("INSERT INTO me_items (account_id, category, title, body, created_at) VALUES (?,?,?,?,?)",
                             (account_id, cat, title, text_, now))
            start_session(conn, ctx, account_id)
        else:
            account_id = row["account_id"]
        cid = conn.execute(
            "INSERT INTO me_credentials (account_id, credential_id, public_key, alg, sign_count, name, aaguid,"
            " backup_eligible, backed_up, transports, fmt, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, reg["credential_id"], reg["public_key"], reg["alg"], reg["sign_count"], row["passkey_name"],
             reg["aaguid"], int(reg["backup_eligible"]), int(reg["backed_up"]), ",".join(reg["transports"]),
             reg["fmt"], now)).lastrowid
        r = conn.execute("SELECT * FROM me_credentials WHERE id = ?", (cid,)).fetchone()
        username = conn.execute("SELECT username FROM me_accounts WHERE id = ?", (account_id,)).fetchone()[0]
    return {"ok": True, "account": {"username": username}, "passkey": public_passkey(r)}


# ---------------------------------------------------------------- 로그인
def login_options(conn, body, ctx):
    rp_id, _ = site(ctx["environ"])
    username = body.get("username") if isinstance(body.get("username"), str) else ""
    username = username.strip()
    account_id, allow = None, []
    with Ctx.tx(conn):
        if username:  # 아이디를 적으면 그 계정의 패스키만 허용
            a = conn.execute("SELECT id FROM me_accounts WHERE username = ?", (username,)).fetchone()
            if a:
                account_id = a["id"]
                allow = [r["credential_id"] for r in conn.execute(
                    "SELECT credential_id FROM me_credentials WHERE account_id = ?", (a["id"],))]
            else:
                account_id = -1  # 없는 아이디: 있는 척하고 넘어가되, 어떤 패스키도 통과하지 못함
        challenge = new_challenge(conn, "login", account_id=account_id)
    return {"publicKey": {"challenge": challenge, "rpId": rp_id, "timeout": CHALLENGE_SECONDS * 1000,
                          "userVerification": "required",
                          "allowCredentials": [{"type": "public-key", "id": c} for c in allow]}}


def login_verify(conn, body, ctx):
    rp_id, origin = site(ctx["environ"])
    cred = credential_of(body)
    try:
        challenge = passkey.read_challenge(cred, "webauthn.get", origin)
    except WebAuthnError as e:
        raise err(401, str(e))
    row = consume_challenge(conn, challenge, "login", 401)
    cid = cred.get("rawId") or cred.get("id")
    c = conn.execute("SELECT c.*, a.user_handle, a.username FROM me_credentials c"
                     " JOIN me_accounts a ON a.id = c.account_id WHERE c.credential_id = ?",
                     (cid if isinstance(cid, str) else "",)).fetchone()
    if not c:
        raise err(401, "This passkey is not registered (it may have been deleted)")
    if row["account_id"] is not None and row["account_id"] != c["account_id"]:
        raise err(403, "This passkey belongs to a different account")
    handle = cred.get("response", {}).get("userHandle")
    if handle and handle != c["user_handle"]:
        raise err(401, "userHandle does not match this passkey's account")
    try:
        res = passkey.verify_assertion(cred, row["challenge"], rp_id, origin, c["public_key"], c["sign_count"])
    except WebAuthnError as e:
        raise err(401, str(e))
    with Ctx.tx(conn):
        conn.execute("UPDATE me_credentials SET sign_count = ?, backed_up = ?, last_used_at = ? WHERE id = ?",
                     (res["sign_count"], int(res["backed_up"]), Ctx.now_utc(), c["id"]))
        start_session(conn, ctx, c["account_id"])
    return {"ok": True, "account": {"username": c["username"]}, "passkey": c["name"]}


def logout(conn, ctx):
    token = read_token(ctx["environ"])
    if token:
        with Ctx.tx(conn):
            conn.execute("DELETE FROM me_sessions WHERE token_hash = ?", (token_hash(token),))
    ctx["headers"].append(cookie(ctx["environ"], "", 0))
    return {"ok": True}


# ---------------------------------------------------------------- 패스키 목록·삭제 (자기 것만)
def list_passkeys(conn, aid):
    rows = conn.execute("SELECT * FROM me_credentials WHERE account_id = ? ORDER BY id", (aid,)).fetchall()
    return {"passkeys": [public_passkey(r) for r in rows]}


def delete_passkey(conn, aid, pid):
    with Ctx.tx(conn):
        r = conn.execute("SELECT id FROM me_credentials WHERE id = ? AND account_id = ?", (pid, aid)).fetchone()
        if not r:
            raise err(404, "Not found")
        left = conn.execute("SELECT COUNT(*) FROM me_credentials WHERE account_id = ?", (aid,)).fetchone()[0]
        if left <= 1:
            raise err(409, "This is your last passkey. Add another passkey first, or you could never log in again.")
        conn.execute("DELETE FROM me_credentials WHERE id = ? AND account_id = ?", (pid, aid))
    return {"ok": True, "left": left - 1}


# ---------------------------------------------------------------- 비공개 자료 (자기 것만)
def item_out(r):
    return {"id": r["id"], "category": r["category"], "category_label": CATEGORIES.get(r["category"], r["category"]),
            "title": r["title"], "body": r["body"], "created_at": r["created_at"]}


def list_items(conn, aid):
    # 주소에 ?account=… 를 붙여도 읽지 않습니다. 누구의 자료인지는 세션(쿠키)만 정합니다.
    rows = conn.execute("SELECT * FROM me_items WHERE account_id = ? ORDER BY id", (aid,)).fetchall()
    return {"items": [item_out(r) for r in rows]}


def get_item(conn, aid, iid):
    r = conn.execute("SELECT * FROM me_items WHERE id = ? AND account_id = ?", (iid, aid)).fetchone()
    if not r:
        raise err(404, "Not found")  # 남의 자료도 '없음'과 똑같이 답해 있는지조차 숨김
    return item_out(r)


def create_item(conn, aid, body):
    cat = body.get("category", "memo")
    if cat not in CATEGORIES:
        raise err(400, "category: project, apply, retro or memo")
    title = text(body, "title", 80)
    content = text(body, "body", 2000, required=False)
    with Ctx.tx(conn):
        if conn.execute("SELECT COUNT(*) FROM me_items WHERE account_id = ?", (aid,)).fetchone()[0] >= 100:
            raise err(409, "You can keep up to 100 items")
        iid = conn.execute("INSERT INTO me_items (account_id, category, title, body, created_at) VALUES (?,?,?,?,?)",
                           (aid, cat, title, content, Ctx.now_utc())).lastrowid
    return get_item(conn, aid, iid)


def delete_item(conn, aid, iid):
    with Ctx.tx(conn):
        n = conn.execute("DELETE FROM me_items WHERE id = ? AND account_id = ?", (iid, aid)).rowcount
    if not n:
        raise err(404, "Not found")
    return {"ok": True}


# ---------------------------------------------------------------- 주소 → 처리 함수
def route(method, parts, body, conn, ctx):
    """parts 는 /api/me/ 다음 조각들. 예: ['items', '3']"""
    ctx["account"] = account = session_account(conn, ctx["environ"])
    if parts == ["register", "options"] and method == "POST":
        return register_options(conn, body, ctx)
    if parts == ["register", "verify"] and method == "POST":
        return register_verify(conn, body, ctx)
    if parts == ["login", "options"] and method == "POST":
        return login_options(conn, body, ctx)
    if parts == ["login", "verify"] and method == "POST":
        return login_verify(conn, body, ctx)
    if parts == ["cancel"] and method == "POST":
        return cancel_challenge(conn, body)
    if parts == ["logout"] and method == "POST":
        return logout(conn, ctx)
    # --- 여기부터는 패스키로 들어온 사람만
    if not account:
        raise err(401, "Log in with a passkey to see the private area")
    aid = account["id"]
    if parts == ["session"] and method == "GET":
        n = conn.execute("SELECT COUNT(*) FROM me_credentials WHERE account_id = ?", (aid,)).fetchone()[0]
        return {"account": {"username": account["username"]}, "passkey_count": n}
    if parts == ["passkeys"] and method == "GET":
        return list_passkeys(conn, aid)
    if len(parts) == 2 and parts[0] == "passkeys" and method == "DELETE":
        return delete_passkey(conn, aid, num(parts[1]))
    if parts == ["items"] and method == "GET":
        return list_items(conn, aid)
    if parts == ["items"] and method == "POST":
        ctx["status"] = 201
        return create_item(conn, aid, body)
    if len(parts) == 2 and parts[0] == "items" and method == "GET":
        return get_item(conn, aid, num(parts[1]))
    if len(parts) == 2 and parts[0] == "items" and method == "DELETE":
        return delete_item(conn, aid, num(parts[1]))
    raise err(404, "Not found")


def num(s):
    if not s.isdigit() or len(s) > 12:
        raise err(404, "Not found")
    return int(s)
