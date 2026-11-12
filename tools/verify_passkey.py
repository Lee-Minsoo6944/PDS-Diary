"""패스키 인증(과제 8)을 실제 HTTP 요청으로 확인하고, 기록을 Markdown 으로 남깁니다.

    set PDS_DB_PATH=scratch.db && py app.py          (다른 창에서, PORT=8017 등)
    py tools/verify_passkey.py http://localhost:8017 --db scratch.db > docs/passkey-verification.md

- 브라우저+인증기 대신 tools/soft_authenticator.py 가 P-256 키 쌍을 만들고 서명합니다(개인키는 이 프로그램 안에만).
- 서버 주소는 localhost 여야 합니다(패스키는 IP 주소 127.0.0.1 에서 쓸 수 없음).
- 세션 쿠키는 앞 5글자만 남기고 가립니다. 긴 base64 값은 앞부분만 보여 줍니다.
"""
import json
import os
import secrets
import sqlite3
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soft_authenticator as sa  # noqa: E402
from soft_authenticator import passkey  # noqa: E402

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "http://localhost:8017"
DB = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else None
ORIGIN = BASE
# Windows 에서 localhost 는 IPv6(::1)부터 시도해 요청마다 느려지므로, 접속은 127.0.0.1 로 하고 Host 머리글만 localhost 로 보냅니다.
CONNECT = BASE.replace("://localhost", "://127.0.0.1")
HOST = BASE.split("://", 1)[1]
SECRETS = []
OUT = []
FAILS = []


def mask(text):
    for s in SECRETS:
        text = text.replace(s, s[:5] + "…(masked)")
    return text


def short(v, keep=24):
    if isinstance(v, str) and len(v) > keep + 8:
        return f"{v[:keep]}…({len(v)}자)"
    if isinstance(v, dict):  # 오류 문구는 줄이지 않음
        return {k: (x if k == "error" else short(x, keep)) for k, x in v.items()}
    if isinstance(v, list):
        return [short(x, keep) for x in v]
    return v


def req(method, path, body=None, cookie=None, csrf=True, headers=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if csrf and method != "GET":
        h["X-PDS"] = "1"
    if cookie:
        h["Cookie"] = f"me_session={cookie}"
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    h["Host"] = HOST
    r = urllib.request.Request(CONNECT + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            status, raw, rh = resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        status, raw, rh = e.code, e.read(), e.headers
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode("utf-8", "replace")
    if isinstance(payload, dict) and payload.get("token"):
        SECRETS.append(payload["token"])
    sc = rh.get("Set-Cookie")
    new = None
    if sc and sc.startswith("me_session="):
        new = sc.split(";")[0].split("=", 1)[1] or None
        if new:
            SECRETS.append(new)
    return {"method": method, "path": path, "body": body, "cookie": cookie, "csrf": csrf and method != "GET",
            "status": status, "payload": payload, "set_cookie": sc, "new_cookie": new, "headers": headers or {},
            "acao": rh.get("Access-Control-Allow-Origin")}


def show(r, full_payload=False):
    lines = [f"{r['method']} {r['path']}", f"Cookie: me_session={r['cookie']}" if r["cookie"] else "Cookie: (none)"]
    if r["csrf"]:
        lines.append("X-PDS: 1")
    for k, v in r.get("headers", {}).items():
        lines.append(f"{k}: {v}")
    if r["body"] is not None:
        lines.append(json.dumps(short(r["body"]), ensure_ascii=False))
    lines.append(f"→ {r['status']}")
    if r["set_cookie"]:
        lines.append(f"Set-Cookie: {r['set_cookie']}")
    if r.get("acao"):
        lines.append(f"Access-Control-Allow-Origin: {r['acao']}")
    elif r.get("headers", {}).get("Origin"):
        lines.append("Access-Control-Allow-Origin: (없음 → 브라우저가 응답을 화면에 넘기지 않음)")
    p = r["payload"]
    if isinstance(p, dict) and p.get("token"):  # 줄이기 전에 먼저 가림
        p = dict(p, token=p["token"][:5] + "…(masked)")
    if isinstance(p, dict) and "items" in p and not full_payload:
        p = {"items": [f"#{x['id']} {x['title']}" for x in p["items"]]}
    elif isinstance(p, dict) and "passkeys" in p and not full_payload:
        p = {"passkeys": [f"#{x['id']} {x['name']} ({x['created_at'][:10]})" for x in p["passkeys"]]}
    text = json.dumps(short(p, 28), ensure_ascii=False)
    if not (isinstance(p, dict) and "error" in p) and len(text) >= 220:
        text = text[:217] + "…"
    lines.append(text)
    return mask("\n".join(lines))


def pre(r, **kw):
    return "<pre>" + show(r, **kw).replace("|", "&#124;").replace("\n", "<br>") + "</pre>"


def section(title, note=""):
    OUT.append(f"\n### {title}\n")
    if note:
        OUT.append(note + "\n")


def pair(title, ok, bad, note="", expect_ok=200, expect_bad=(401, 403, 404)):
    good = ok["status"] == expect_ok and bad["status"] in (expect_bad if isinstance(expect_bad, tuple) else (expect_bad,))
    if not good:
        FAILS.append(title)
    section(("✅ " if good else "❌ ") + title, note)
    OUT.append("| 통과한 요청 | 거절된 요청 |\n|---|---|")
    OUT.append(f"| {pre(ok)} | {pre(bad)} |")


def block(r, title=None, **kw):
    if title:
        OUT.append(f"\n**{title}**\n")
    OUT.append("```\n" + show(r, **kw) + "\n```")


def check(cond, title):
    if not cond:
        FAILS.append(title)
    return "✅" if cond else "❌"


def db_rows(sql, args=()):
    if not DB:
        return None
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def register(username=None, name="laptop", cookie=None):
    body = {"passkey_name": name}
    if username:
        body["username"] = username
    o = req("POST", "/api/me/register/options", body, cookie=cookie)
    cred, key = sa.create(o["payload"], ORIGIN)
    v = req("POST", "/api/me/register/verify", {"credential": cred}, cookie=cookie)
    return o, cred, key, v


def login(key, username=""):
    o = req("POST", "/api/me/login/options", {"username": username})
    cred = sa.get(o["payload"], ORIGIN, key)
    v = req("POST", "/api/me/login/verify", {"credential": cred})
    return o, cred, v


def main():
    tag = secrets.token_hex(3)
    a_name, b_name = f"alice_{tag}", f"bob_{tag}"
    OUT.append("# 패스키 인증 확인 기록 (과제 8)\n")
    OUT.append(f"서버: `{BASE}` · 시험 계정 `{a_name}`, `{b_name}` (이 기록을 만들 때마다 새로 만듦). "
               "인증기는 `tools/soft_authenticator.py`(P-256 키 쌍을 만들고 개인키를 자기 안에만 두는 시험용 프로그램)가 맡았습니다. "
               "세션 쿠키는 앞 5글자 뒤를 가렸고, 긴 base64 값은 앞부분과 길이만 적었습니다.\n")
    OUT.append("> 실제 기기(Windows Hello·휴대폰·보안 키)로 한 확인은 [PASSKEY.md](../PASSKEY.md) 의 화면 기록을 보세요. "
               "이 파일은 같은 HTTP 요청을 매번 똑같이 다시 만들어 볼 수 있게 자동으로 남긴 것입니다.\n")

    # ------------------------------------------------------------ 1. 로그인 없이
    OUT.append("\n## 1. 로그인 없이 열기 (C15–C18)\n")
    page = urllib.request.urlopen(urllib.request.Request(CONNECT + "/me/", headers={"Host": HOST})).read().decode("utf-8")
    seeds = ["준비 중인 프로젝트 메모 (가상)", "한빛데이터랩", "11월 개인 회고 (가상)"]
    found = [s for s in seeds if s in page]
    section(check(not found and "여기부터 비공개 영역" in page, "page source") + " 로그인 없이 받은 `/me/` 페이지 소스 (C18)",
            f"`GET /me/` → 200, {len(page.encode())}바이트. 공개 소개 문구 `안녕하세요👋, 이민수입니다.` 포함: "
            f"**{'예' if '안녕하세요👋, 이민수입니다.' in page else '아니오'}** · 경계 문구 `여기부터 비공개 영역` 포함: "
            f"**{'예' if '여기부터 비공개 영역' in page else '아니오'}** · 비공개 자료 제목 {seeds} 중 소스에 들어 있는 것: "
            f"**{found or '없음'}** · 비밀번호 입력칸(`type=\"password\"`): **{'있음' if 'type=\"password\"' in page else '없음'}**")
    snippet = page[page.index('<section id="private"'):page.index('<!-- 들어가기 전 -->')]
    OUT.append("비공개 영역 자리의 실제 소스(로그인 전). 안내 문구만 있고 자료는 없습니다:\n")
    OUT.append("```html\n" + snippet.strip() + "\n```")

    o, cred_a, key_a, v = register(a_name, "Alice laptop")
    cookie_a = v["new_cookie"]
    pair("같은 비공개 자료 요청 — 세션 있음 / 없음 (C16, C17)",
         req("GET", "/api/me/items", cookie=cookie_a), req("GET", "/api/me/items"))
    pair("패스키 목록 요청 — 세션 있음 / 지어낸 쿠키 (C16)",
         req("GET", "/api/me/passkeys", cookie=cookie_a), req("GET", "/api/me/passkeys", cookie="made-up-cookie-value"))

    # ------------------------------------------------------------ 2. 등록
    OUT.append("\n## 2. 패스키 등록 (C19–C26)\n")
    opts = [req("POST", "/api/me/register/options", {"username": f"tmp{i}_{tag}", "passkey_name": "x"}) for i in range(3)]
    chs = [x["payload"]["publicKey"]["challenge"] for x in opts]
    for x in opts:  # 쓰지 않을 챌린지는 바로 지움
        req("POST", "/api/me/cancel", {"challenge": x["payload"]["publicKey"]["challenge"]})
    section(check(len(set(chs)) == 3, "reg challenges") + " 등록 요청마다 챌린지가 다름 (C20)",
            "같은 요청을 세 번 보냈을 때 서버가 준 `challenge`(32바이트 무작위 값, base64url):\n\n"
            + "\n".join(f"{i + 1}. `{c}`" for i, c in enumerate(chs)))

    o, cred_b, key_b, v_b = register(b_name, "Bob phone")
    cookie_b = v_b["new_cookie"]
    ch_b = o["payload"]["publicKey"]["challenge"]
    section("✅ 등록 1단계 — 서버가 챌린지를 만들어 보내고 보관 (C19)")
    block(o, full_payload=True)
    rows = db_rows("SELECT challenge, purpose, username, created_at, expires_at, used_at FROM me_challenges"
                   " WHERE challenge = ?", (ch_b,))
    if rows is not None:
        OUT.append("서버 DB `me_challenges` 의 그 줄(검증이 끝난 뒤라 `used_at` 이 채워져 있음. 5분 뒤 만료):\n")
        OUT.append("```json\n" + json.dumps(rows, ensure_ascii=False, indent=1) + "\n```")

    att, _ = passkey.cbor_decode(passkey.b64url_decode(cred_b["response"]["attestationObject"]))
    ad = passkey.parse_auth_data(att["authData"])
    cose, _ = passkey.cbor_decode(ad["public_key"])
    cd = json.loads(passkey.b64url_decode(cred_b["response"]["clientDataJSON"]))
    section("✅ 등록 2단계 — 브라우저가 보낸 요청 본문에 개인키가 없음 (C23)",
            "아래가 `POST /api/me/register/verify` 본문 전체입니다(긴 값만 줄임). 들어 있는 것은 자격 증명 ID, "
            "`clientDataJSON`, `attestationObject`, 전송 방식뿐입니다.")
    block(v_b, full_payload=True)
    priv_hex = format(key_b._private, "064x")
    body_text = json.dumps(cred_b)
    OUT.append("`attestationObject` 를 풀어 보면:\n")
    OUT.append("| 칸 | 값 | 뜻 |\n|---|---|---|")
    OUT.append(f"| `fmt` | `{att['fmt']}` | attestation 을 `none` 으로 요청 → 제조사 증명서 없음 |")
    OUT.append(f"| `attStmt` | `{att['attStmt']}` | 비어 있음 |")
    OUT.append(f"| `authData.rpIdHash` | `{ad['rp_id_hash'].hex()[:16]}…` | SHA-256(\"localhost\") — 이 사이트용 키 |")
    OUT.append(f"| `authData.flags` | `0x{ad['flags']:02x}` | UP·UV·AT{'·BE·BS' if ad['flags'] & 0x08 else ''} |")
    OUT.append(f"| `authData.credentialId` | `{passkey.b64url(ad['credential_id'])[:20]}…` | 자격 증명 ID |")
    OUT.append(f"| `credentialPublicKey` | kty={cose[1]}(EC2), alg={cose[3]}(ES256), crv={cose[-1]}(P-256), "
               f"x=`{cose[-2].hex()[:16]}…`, y=`{cose[-3].hex()[:16]}…` | **공개키**(곡선 위의 점 x, y) |")
    OUT.append(f"| `clientDataJSON` | `{json.dumps(cd, ensure_ascii=False)[:90]}…` | 종류·챌린지·주소 |")
    OUT.append(f"\n개인키(인증기 안의 비밀 숫자 d)를 16진수로 바꾼 값 `{priv_hex[:6]}…` 이 요청 본문에 들어 있는지: "
               f"**{check(priv_hex not in body_text and str(key_b._private) not in body_text, 'no private key') + (' 없음' if priv_hex not in body_text else ' 있음')}**. "
               "ES256 의 개인키는 숫자 하나(d)이고, 공개키(x, y)는 d×G 로 계산한 점이라 공개키에서 d 를 되돌려 구할 수 없습니다.\n")

    rows = db_rows("SELECT c.id, a.username, c.name, c.credential_id, c.public_key, c.alg, c.sign_count, c.aaguid,"
                   " c.backup_eligible, c.transports, c.fmt, c.created_at FROM me_credentials c"
                   " JOIN me_accounts a ON a.id = c.account_id WHERE a.username = ?", (b_name,))
    if rows is not None:
        section("✅ 서버에 저장된 값 — 공개키이며 비밀번호가 아님 (C21, C22, C24)")
        r = rows[0]
        shown = dict(r, public_key=r["public_key"][:40] + f"…({len(r['public_key'])}자)",
                     credential_id=r["credential_id"][:20] + "…")
        OUT.append("```json\n" + json.dumps(shown, ensure_ascii=False, indent=1) + "\n```")
        s = passkey.cose_summary(passkey.b64url_decode(r["public_key"]))
        same = int(s["x"], 16) == key_b.public[0] and int(s["y"], 16) == key_b.public[1]
        OUT.append(f"`public_key` 를 풀면 `{s['alg']} {s['crv']} x={s['x'][:16]}… y={s['y'][:16]}…` — 인증기가 만든 공개키와 "
                   f"같은 점: **{check(same, 'stored = public') + (' 같음' if same else ' 다름')}**. 이 값은 남에게 보여도 되는 공개 정보라서 "
                   "DB 가 새어도 이것으로 로그인할 수 없습니다(로그인하려면 이 공개키에 맞는 서명을 만들어야 하고, 그건 개인키가 있는 인증기만 할 수 있음). "
                   "비밀번호처럼 사람이 외우거나 입력하는 값도, 해시해 숨겨야 하는 값도 아닙니다. 이름 `name` 은 사람이 붙인 이름입니다.\n")
        pw_cols = db_rows("SELECT name FROM pragma_table_info('me_accounts') UNION SELECT name FROM pragma_table_info('me_credentials')")
        OUT.append("`me_accounts`·`me_credentials` 표의 열: `" + "`, `".join(x["name"] for x in pw_cols)
                   + "` — 비밀번호 열이 없습니다.\n")

    # 취소
    before = db_rows("SELECT (SELECT COUNT(*) FROM me_accounts) a, (SELECT COUNT(*) FROM me_credentials) c")
    oc = req("POST", "/api/me/register/options", {"username": f"cancel_{tag}", "passkey_name": "x"})
    cc = req("POST", "/api/me/cancel", {"challenge": oc["payload"]["publicKey"]["challenge"]})
    after = db_rows("SELECT (SELECT COUNT(*) FROM me_accounts) a, (SELECT COUNT(*) FROM me_credentials) c")
    left = db_rows("SELECT COUNT(*) n FROM me_challenges WHERE challenge = ?", (oc["payload"]["publicKey"]["challenge"],))
    section(check(cc["status"] == 200 and (before == after if DB else True), "cancel") + " 등록 중간에 취소 (C25)",
            "사용자가 패스키 창을 닫으면 브라우저가 `NotAllowedError` 를 내고, 화면은 "
            "\"등록 창이 닫혀 취소되었습니다… 서버에는 아무것도 저장되지 않았습니다.\" 를 보여 준 뒤 보관 중인 챌린지 삭제를 요청합니다.")
    block(oc)
    block(cc)
    if DB:
        OUT.append(f"취소 전 계정·패스키 수 `{before[0]}` → 취소 후 `{after[0]}`, 그 챌린지 줄 수: `{left[0]['n']}`\n")

    # ------------------------------------------------------------ 3. 로그인
    OUT.append("\n## 3. 패스키 로그인 (C27–C35)\n")
    lo = [req("POST", "/api/me/login/options", {}) for _ in range(3)]
    lchs = [x["payload"]["publicKey"]["challenge"] for x in lo]
    section(check(len(set(lchs)) == 3, "login challenges") + " 로그인 요청마다 챌린지가 다름 (C27, C28)",
            "\n".join(f"{i + 1}. `{c}`" for i, c in enumerate(lchs)))

    o1 = req("POST", "/api/me/login/options", {})
    bad_cred = sa.get(o1["payload"], ORIGIN, key_a, tamper=True)
    bad = req("POST", "/api/me/login/verify", {"credential": bad_cred})
    o2, good_cred, good = login(key_a)
    pair("서명 확인 성공 / 실패 (C29, C30)", good, bad,
         "오른쪽은 서명 마지막 바이트 한 개만 바꾼 요청입니다. 서버는 `me_credentials.public_key` 로 "
         "`authenticatorData ‖ SHA-256(clientDataJSON)` 에 대한 서명을 계산해 보고(`passkey.verify_assertion`), 맞지 않으면 401.")
    cookie_a = good["new_cookie"]
    replay = req("POST", "/api/me/login/verify", {"credential": good_cred})
    pair("이미 쓴 챌린지 다시 보내기 (C31)", good, replay,
         "왼쪽과 **완전히 같은 본문**(같은 챌린지·같은 올바른 서명)을 한 번 더 보냈습니다. 서명은 맞지만 챌린지를 이미 썼으므로 거절됩니다. "
         "챌린지는 검사 전에 `used_at` 을 먼저 저장하므로, 실패한 시도의 챌린지도 다시 쓸 수 없습니다.")

    section("✅ 로그인 뒤 사용자 식별 방식 (C32, C34)",
            "**서버 세션**입니다. 로그인에 성공하면 `secrets.token_urlsafe(32)` 무작위 값을 `me_session` 쿠키"
            "(`HttpOnly; SameSite=Strict; Path=/; Max-Age=43200`, https 에서는 `Secure`)로 주고, 서버 DB `me_sessions` 에는 "
            "그 값의 SHA-256 만 저장합니다. 이후 요청에서 쿠키 → 해시 → `me_sessions` → 계정 순으로 찾습니다. "
            "주소·본문의 계정 이름은 읽지 않습니다. 기록의 쿠키 값은 앞 5글자 뒤를 가렸습니다.")
    before_lo = req("GET", "/api/me/items", cookie=cookie_a)
    lo_r = req("POST", "/api/me/logout", cookie=cookie_a)
    after_lo = req("GET", "/api/me/items", cookie=cookie_a)
    block(lo_r, "로그아웃 요청")
    pair("로그아웃 전 / 후 — 같은 쿠키 값으로 요청 (C33)", before_lo, after_lo,
         "로그아웃 때 서버가 `me_sessions` 에서 그 줄을 지우므로, 브라우저가 쿠키를 지우지 않고 그대로 다시 보내도 거절됩니다.")

    # ------------------------------------------------------------ 4. 패스키 두 개
    OUT.append("\n## 4. 패스키 두 개 · 하나 삭제 (C42–C46)\n")
    _, _, v = login(key_a)
    cookie_a = v["new_cookie"]
    o_add, cred_a2, key_a2, v_add = register(name="Alice phone", cookie=cookie_a)
    section(check(v_add["status"] == 200, "add second") + " 두 번째 패스키 등록",
            "로그인한 채로 같은 `register/options` 를 부르면 그 계정에 패스키를 추가합니다. "
            f"`excludeCredentials` 에 첫 패스키 ID {len(o_add['payload']['publicKey']['excludeCredentials'])}개가 들어가 "
            "같은 인증기에 두 번 만들지 않게 합니다.")
    block(o_add)
    block(v_add)
    lst = req("GET", "/api/me/passkeys", cookie=cookie_a)
    section(check(len(lst["payload"].get("passkeys", [])) == 2, "two passkeys") + " 한 계정에 패스키 두 개 (C42, C43)")
    OUT.append("| 이름 | 등록한 날(UTC) | 저장된 곳(추정) | 공개키 |\n|---|---|---|---|")
    for p in lst["payload"]["passkeys"]:
        k = p["public_key"]
        OUT.append(f"| {p['name']} | {p['created_at']} | {p['storage']} | {k['alg']} x={k['x'][:12]}… |")
    first_id = lst["payload"]["passkeys"][0]["id"]
    d = req("DELETE", f"/api/me/passkeys/{first_id}", cookie=cookie_a)
    block(d, "첫 번째 패스키(Alice laptop) 삭제")
    _, _, with_deleted = login(key_a)
    _, _, with_left = login(key_a2)
    pair("하나 지운 뒤 — 남은 패스키 / 지운 패스키로 로그인 (C44, C45)", with_left, with_deleted,
         "지운 패스키는 인증기(기기) 쪽에는 남아 있어 서명은 만들 수 있지만, 서버에 그 공개키가 없으므로 거절됩니다.")
    cookie_a = with_left["new_cookie"]
    last_id = req("GET", "/api/me/passkeys", cookie=cookie_a)["payload"]["passkeys"][0]["id"]
    last = req("DELETE", f"/api/me/passkeys/{last_id}", cookie=cookie_a)
    pair("마지막 남은 패스키 삭제 시도 (C46)", req("GET", "/api/me/passkeys", cookie=cookie_a), last,
         "패스키가 하나만 남으면 서버가 삭제를 막습니다(409). 화면에는 패스키가 1개일 때 늘 경고가 보입니다. "
         "비밀번호·이메일 복구가 없으므로, 남은 하나마저 잃으면 그 계정에는 다시 들어올 수 없습니다(PASSKEY.md ⑥).",
         expect_bad=409)

    # ------------------------------------------------------------ 5. 다른 계정
    OUT.append("\n## 5. 다른 계정의 자료·패스키 (C36–C41)\n")
    _, _, vb = login(key_b)
    cookie_b = vb["new_cookie"]
    ra = req("POST", "/api/me/items", {"category": "memo", "title": f"Alice만 아는 메모 ({tag})", "body": "가상의 내용"}, cookie=cookie_a)
    rb = req("POST", "/api/me/items", {"category": "apply", "title": f"Bob의 지원 목록 ({tag})", "body": "가상 회사 C"}, cookie=cookie_b)
    a_item, b_item = ra["payload"]["id"], rb["payload"]["id"]
    a_list = req("GET", "/api/me/items", cookie=cookie_a)
    b_list = req("GET", "/api/me/items", cookie=cookie_b)
    section("✅ 계정 두 개, 서로 다른 비공개 내용 (C36)")
    block(a_list, f"{a_name}")
    block(b_list, f"{b_name}")
    count = lambda c: len(req("GET", "/api/me/items", cookie=c)["payload"]["items"])  # noqa: E731
    b_before, a_before = count(cookie_b), count(cookie_a)
    pair(f"A({a_name}) 가 자기 자료 / B 의 자료 #{b_item} 요청 (C37)",
         req("GET", f"/api/me/items/{a_item}", cookie=cookie_a), req("GET", f"/api/me/items/{b_item}", cookie=cookie_a),
         "남의 자료는 '없음'과 똑같이 404 로 답해, 번호를 바꿔 보며 남의 자료가 있는지 알아낼 수 없게 했습니다.")
    pair(f"A 가 B 의 자료 #{b_item} 삭제 시도",
         req("GET", "/api/me/items", cookie=cookie_a), req("DELETE", f"/api/me/items/{b_item}", cookie=cookie_a))
    pair(f"반대 방향: B({b_name}) 가 자기 자료 / A 의 자료 #{a_item} 요청 (C38)",
         req("GET", f"/api/me/items/{b_item}", cookie=cookie_b), req("GET", f"/api/me/items/{a_item}", cookie=cookie_b))
    pair(f"반대 방향: B 가 A 의 자료 #{a_item} 삭제 시도",
         req("GET", "/api/me/items", cookie=cookie_b), req("DELETE", f"/api/me/items/{a_item}", cookie=cookie_b))
    b_after, a_after = count(cookie_b), count(cookie_a)
    section(check(b_before == b_after and a_before == a_after, "counts") + " 거절 앞뒤 자료 건수 (C39)",
            f"B 의 자료: 거절 전 **{b_before}건** → 거절 후 **{b_after}건** · A 의 자료: 거절 전 **{a_before}건** → 거절 후 **{a_after}건**")

    q = req("GET", f"/api/me/items?account={b_name}&account_id=2&username={b_name}", cookie=cookie_a)
    titles = [x["title"] for x in q["payload"]["items"]]
    section(check(not any("Bob" in t for t in titles), "query other account") + " 주소에 다른 계정을 적어 보내도 내 자료만 (C40)")
    block(q)
    w = req("POST", "/api/me/items", {"category": "memo", "title": f"몰래 넣기 ({tag})", "account_id": 2, "username": b_name},
            cookie=cookie_a)
    block(w, "본문에 B 의 계정을 적어 자료 추가")
    b_titles = [x["title"] for x in req("GET", "/api/me/items", cookie=cookie_b)["payload"]["items"]]
    OUT.append(f"B 의 자료 목록에 `몰래 넣기` 가 생겼는지: **{check(not any('몰래' in t for t in b_titles), 'body other account') + (' 아니오' if not any('몰래' in t for t in b_titles) else ' 예')}** "
               "— 본문의 `account_id`·`username` 은 읽지 않고 세션의 계정(A)으로 저장됩니다.\n")
    b_pk = req("GET", "/api/me/passkeys", cookie=cookie_b)["payload"]["passkeys"][0]["id"]
    pair(f"A 가 B 의 패스키 #{b_pk} 삭제 시도", req("GET", "/api/me/passkeys", cookie=cookie_a),
         req("DELETE", f"/api/me/passkeys/{b_pk}", cookie=cookie_a))
    _, _, own = login(key_a2, username=a_name)
    _, _, other = login(key_b, username=a_name)
    pair(f"A 의 아이디로 로그인 — A 의 패스키 / B 의 패스키", own, other,
         "아이디를 적고 로그인하면 서버가 챌린지에 그 계정을 묶어 두고, 다른 계정의 패스키로 만든 서명은 서명이 맞아도 거절합니다.")

    # ------------------------------------------------------------ 6. GitHub Pages 화면에서 부르기
    GH = "https://lee-minsoo6944.github.io"
    OUT.append("\n## 6. 결과물 주소(GitHub Pages)에서 부르기\n")
    OUT.append("결과물 https://lee-minsoo6944.github.io/About-me/ 의 화면은 이 서버와 주소가 달라서, 브라우저가 `Origin` 머리글을 붙여 보냅니다. "
               "서버는 이 주소에만 CORS 를 열고, rpId 를 `lee-minsoo6944.github.io` 로 정하며, 쿠키 대신 **응답 본문의 세션 토큰**을 줍니다"
               "(화면은 탭을 닫으면 지워지는 sessionStorage 에 두고 `Authorization: Bearer` 로 보냄). 토큰 값은 앞 5글자 뒤를 가렸습니다.\n")
    pre_ok = req("OPTIONS", "/api/me/login/options", headers={"Origin": GH, "Access-Control-Request-Method": "POST"}, csrf=False)
    pre_bad = req("OPTIONS", "/api/me/login/options", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}, csrf=False)
    pair("사전 요청(preflight) — 결과물 주소 / 다른 사이트", pre_ok, pre_bad,
         "다른 사이트에는 허락 머리글이 없어서, 그 사이트의 자바스크립트는 이 API 의 응답을 읽을 수 없습니다.",
         expect_ok=204, expect_bad=(401, 404))
    gname = f"gh_{tag}"
    go = req("POST", "/api/me/register/options", {"username": gname, "passkey_name": "GitHub Pages laptop"}, headers={"Origin": GH})
    gcred, gkey = sa.create(go["payload"], GH)
    gv = req("POST", "/api/me/register/verify", {"credential": gcred}, headers={"Origin": GH})
    rp_ok = go["payload"]["publicKey"]["rp"]["id"] == "lee-minsoo6944.github.io"
    section(check(gv["status"] == 200 and rp_ok and not gv["set_cookie"] and gv["payload"].get("token"), "gh register")
            + " 결과물 주소에서 등록 — rpId 가 github.io, 쿠키 없이 토큰")
    block(go)
    block(gv)
    gtoken = gv["payload"]["token"]
    pair("토큰 있음 / 없음으로 비공개 자료 요청", req("GET", "/api/me/items", headers={"Origin": GH, "Authorization": f"Bearer {gtoken}"}),
         req("GET", "/api/me/items", headers={"Origin": GH}))
    req("POST", "/api/me/logout", headers={"Origin": GH, "Authorization": f"Bearer {gtoken}"})
    pair("로그아웃 전 / 후 — 같은 토큰", gv, req("GET", "/api/me/items", headers={"Origin": GH, "Authorization": f"Bearer {gtoken}"}),
         "왼쪽은 토큰을 받은 등록 응답, 오른쪽은 `POST /api/me/logout` 뒤에 같은 토큰을 다시 보낸 요청입니다. 서버에서 세션 줄을 지웠으므로 거절됩니다.")
    lcred_other = sa.create(req("POST", "/api/me/register/options", {"username": f"gh2_{tag}", "passkey_name": "x"},
                                headers={"Origin": GH})["payload"], BASE)[0]
    wrong = req("POST", "/api/me/register/verify", {"credential": lcred_other}, headers={"Origin": GH})
    section(check(wrong["status"] == 400, "gh wrong origin") + " 다른 주소에서 만든 등록 응답을 결과물 주소 요청으로 보내기",
            "인증기가 서명한 `clientDataJSON.origin` 은 화면의 진짜 주소라, 요청 머리글만 바꿔서는 통과할 수 없습니다.")
    block(wrong)

    section("거절을 만드는 소스 위치 (C41)",
            "- `intro.py` `route()` — `/api/me/` 아래에서 세션이 없으면 `401 Log in with a passkey…`\n"
            "- `intro.py` `get_item()` · `delete_item()` · `list_items()` — SQL `WHERE … AND account_id = ?` (세션의 계정만)\n"
            "- `intro.py` `delete_passkey()` — `WHERE id = ? AND account_id = ?`, 마지막 하나면 409\n"
            "- `intro.py` `login_verify()` — 챌린지에 묶인 계정과 패스키 주인이 다르면 403\n"
            "- `intro.py` `consume_challenge()` — 모르는·이미 쓴·만료된 챌린지 거절\n"
            "- `passkey.py` `verify_assertion()` — origin·rpIdHash·UP/UV 플래그·서명·signCount 검사\n"
            "- `intro.py` `cors_headers()` · `site()` — 결과물 주소(GitHub Pages)에만 CORS, 그 주소의 rpId·origin 으로 검사")

    # 정리
    OUT.append("\n---\n")
    OUT.append(f"**결과: {'모두 통과' if not FAILS else '실패 ' + str(len(FAILS)) + '건: ' + ', '.join(FAILS)}**\n")
    print("\n".join(OUT))
    if FAILS:
        print("FAILED: " + ", ".join(FAILS), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
