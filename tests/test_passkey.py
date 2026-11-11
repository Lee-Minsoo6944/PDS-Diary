"""과제 8 통과 기준(T08-Cxx) 자동 확인 — 패스키 등록·로그인·로그아웃·비공개 자료 차단.
실행: py -m unittest discover -s tests -v
브라우저와 인증기 대신 tools/soft_authenticator.py 가 P-256 키 쌍을 만들고 서명합니다.
"""
import hashlib
import io
import json
import os
import secrets
import sys
import tempfile
import unittest

if "PDS_DB_PATH" not in os.environ:
    os.environ["PDS_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402
import intro  # noqa: E402
import passkey  # noqa: E402
import soft_authenticator as sa  # noqa: E402

HOST = "localhost:8000"
ORIGIN = "http://localhost:8000"


def call(method, path, body=None, cookie=None, csrf=True, host=HOST):
    path, _, query = path.partition("?")
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_HOST": host,
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http"}
    if csrf:
        env["HTTP_X_PDS"] = "1"
    if cookie:
        env["HTTP_COOKIE"] = f"me_session={cookie}"
    out = {}

    def sr(status, hdrs):
        out["status"], out["headers"] = int(status.split()[0]), hdrs

    data = b"".join(app.application(env, sr))
    headers = dict(out["headers"])
    ctype = headers.get("Content-Type", "")
    return out["status"], (json.loads(data) if ctype.startswith("application/json") else data), headers


def me_cookie(headers):
    v = headers.get("Set-Cookie", "")
    return v.split(";")[0].split("=", 1)[1] if v.startswith("me_session=") else None


_n = [0]


def new_account(prefix="pk"):
    """새 계정 + 첫 패스키. (아이디, 세션 쿠키, 인증기 안의 패스키)"""
    _n[0] += 1
    name = f"{prefix}{_n[0]}_{secrets.token_hex(2)}"
    s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "laptop"})
    assert s == 200, (s, opts)
    cred, key = sa.create(opts, ORIGIN)
    s, d, h = call("POST", "/api/me/register/verify", {"credential": cred})
    assert s == 200, (s, d)
    return name, me_cookie(h), key


def login(key, username="", tamper=False):
    s, opts, _ = call("POST", "/api/me/login/options", {"username": username})
    assert s == 200, (s, opts)
    cred = sa.get(opts, ORIGIN, key, tamper=tamper)
    s, d, h = call("POST", "/api/me/login/verify", {"credential": cred})
    return s, d, me_cookie(h), cred


def add_passkey(cookie, name="phone"):
    s, opts, _ = call("POST", "/api/me/register/options", {"passkey_name": name}, cookie=cookie)
    assert s == 200, (s, opts)
    cred, key = sa.create(opts, ORIGIN)
    s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred}, cookie=cookie)
    return s, d, key, opts


def db():
    return app.connect()


class Crypto(unittest.TestCase):
    def test_p256_rfc6979_vector(self):
        # RFC 6979 A.2.5 (P-256, SHA-256, 메시지 "sample") — 직접 짠 타원곡선 계산이 표준값과 같은지
        d = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
        q = passkey.scalar_mult(d, passkey.G)
        self.assertEqual(q, (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
                             0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299))
        r = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
        s = 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
        body = sa.der_int(r) + sa.der_int(s)
        sig = b"\x30" + bytes([len(body)]) + body
        self.assertTrue(passkey.ecdsa_p256_verify(q, b"sample", sig))
        self.assertFalse(passkey.ecdsa_p256_verify(q, b"Sample", sig))
        bad = sa.der_int(r) + sa.der_int(s ^ 1)
        self.assertFalse(passkey.ecdsa_p256_verify(q, b"sample", b"\x30" + bytes([len(bad)]) + bad))
        self.assertFalse(passkey.ecdsa_p256_verify((q[0], q[1] ^ 1), b"sample", sig))  # 곡선 밖의 점

    def test_rs256(self):
        # 시험용 RSA-2048 키를 그 자리에서 만들어 PKCS#1 v1.5 서명 검사를 확인
        def prime(bits):
            while True:
                c = secrets.randbits(bits) | (1 << bits - 1) | 1
                if all(pow(a, c - 1, c) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23)):
                    return c
        e = 65537
        while True:
            p, q = prime(1024), prime(1024)
            if (p - 1) % e and (q - 1) % e and (p * q).bit_length() == 2048:
                break
        n, dd = p * q, pow(e, -1, (p - 1) * (q - 1))
        msg = b"authData||hash"
        t = passkey._SHA256_DIGEST_INFO + hashlib.sha256(msg).digest()
        em = b"\x00\x01" + b"\xff" * (256 - len(t) - 3) + b"\x00" + t
        sig = pow(int.from_bytes(em, "big"), dd, n).to_bytes(256, "big")
        self.assertTrue(passkey.rsa_sha256_verify(n, e, msg, sig))
        self.assertFalse(passkey.rsa_sha256_verify(n, e, msg + b"!", sig))


class PublicArea(unittest.TestCase):
    def test_intro_page_is_public_and_has_no_private_content(self):  # C10 C11 C13 C18
        s, html, h = call("GET", "/me/")
        self.assertEqual(s, 200)
        page = html.decode("utf-8")
        self.assertIn("안녕하세요👋, 이민수입니다.", page)          # 과제 1 내용 그대로
        self.assertIn("강점 2. 꼼꼼한 분석을 통한 문제 해결력", page)
        self.assertIn("여기부터 비공개 영역", page)                 # 경계가 화면에 있음
        for _, title, text_ in intro.SEED_ITEMS:                     # 비공개 내용은 소스에 없음
            self.assertNotIn(title, page)
            self.assertNotIn(text_[:12], page)
        for f in ("/me/about.js", "/me/private.js", "/me/about.css", "/me/private.css"):
            s, data, _ = call("GET", f)
            self.assertEqual(s, 200)
            self.assertNotIn("한빛데이터랩".encode(), data)
        self.assertNotIn(b'type="password"', html)                  # C35

    def test_original_page_unchanged(self):  # C11: 과제 1 의 본문(공개 내용)을 그대로 옮겼는지 — 덧붙인 줄만 다름
        s, html, _ = call("GET", "/me/")
        page = html.decode("utf-8")
        for line in ("이메일: <strong>alstn6944@naver.com</strong>", "📢 공개 범위 안내", "나만의 비밀",
                     "부산 남구청장 표창", "명중률을 <span class=\"highlight\">20%에서 70%까지"):
            self.assertIn(line, page)

    def test_me_redirect(self):
        s, _, h = call("GET", "/me")
        self.assertEqual(s, 301)
        self.assertEqual(h["Location"], "/me/")

    def test_private_api_needs_passkey(self):  # C15 C16 C17
        for path in ("/api/me/items", "/api/me/items/1", "/api/me/passkeys", "/api/me/session"):
            s, d, _ = call("GET", path)
            self.assertEqual(s, 401, path)
            self.assertNotIn("items", d)
        s, d, _ = call("GET", "/api/me/items", cookie="made-up-value")
        self.assertEqual(s, 401)

    def test_writes_need_csrf_header(self):
        s, d, _ = call("POST", "/api/me/login/options", {}, csrf=False)
        self.assertEqual(s, 403)

    def test_ip_address_host_is_refused(self):
        s, d, _ = call("POST", "/api/me/login/options", {}, host="127.0.0.1:8000")
        self.assertEqual(s, 400)


class Registration(unittest.TestCase):
    def test_register_stores_public_key_only(self):  # C19 C21 C22 C23 C24
        name = f"reg_{secrets.token_hex(3)}"
        s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "My laptop"})
        self.assertEqual(s, 200)
        ch = opts["publicKey"]["challenge"]
        with db() as c:
            row = c.execute("SELECT * FROM me_challenges WHERE challenge = ?", (ch,)).fetchone()
        self.assertIsNotNone(row)            # 서버가 챌린지를 보관
        self.assertIsNone(row["used_at"])
        cred, key = sa.create(opts, ORIGIN)
        self.assertNotIn(str(key._private), json.dumps(cred))
        self.assertNotIn(format(key._private, "x"), json.dumps(cred))
        s, d, h = call("POST", "/api/me/register/verify", {"credential": cred})
        self.assertEqual(s, 200, d)
        self.assertIsNotNone(me_cookie(h))
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Strict", h["Set-Cookie"])
        self.assertEqual(d["passkey"]["name"], "My laptop")
        with db() as c:
            r = c.execute("SELECT * FROM me_credentials WHERE credential_id = ?", (cred["id"],)).fetchone()
            used = c.execute("SELECT used_at FROM me_challenges WHERE challenge = ?", (ch,)).fetchone()[0]
        summary = passkey.cose_summary(passkey.b64url_decode(r["public_key"]))
        self.assertEqual(int(summary["x"], 16), key.public[0])   # 저장된 값 = 인증기의 공개키
        self.assertEqual(int(summary["y"], 16), key.public[1])
        self.assertNotIn(format(key._private, "x"), json.dumps(dict(r)))
        self.assertIsNotNone(used)

    def test_each_registration_gets_new_challenge(self):  # C20
        seen = set()
        for i in range(5):
            s, opts, _ = call("POST", "/api/me/register/options", {"username": f"chal{i}x", "passkey_name": "k"})
            seen.add(opts["publicKey"]["challenge"])
            self.assertGreaterEqual(len(passkey.b64url_decode(opts["publicKey"]["challenge"])), 32)
        self.assertEqual(len(seen), 5)

    def test_cancel_leaves_nothing(self):  # C25
        with db() as c:
            before = [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("me_accounts", "me_credentials")]
        name = f"cancel_{secrets.token_hex(3)}"
        s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "k"})
        s, d, _ = call("POST", "/api/me/cancel", {"challenge": opts["publicKey"]["challenge"]})
        self.assertEqual(s, 200)
        with db() as c:
            after = [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("me_accounts", "me_credentials")]
            ch = c.execute("SELECT COUNT(*) FROM me_challenges WHERE challenge = ?",
                           (opts["publicKey"]["challenge"],)).fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(ch, 0)
        cred, _ = sa.create(opts, ORIGIN)  # 취소한 챌린지로는 등록도 안 됨
        s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred})
        self.assertEqual(s, 400)

    def test_registration_checks(self):
        name = f"chk_{secrets.token_hex(3)}"
        s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "k"})
        cred, _ = sa.create(opts, "https://evil.example")  # 다른 사이트에서 만든 응답
        s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred})
        self.assertEqual(s, 400)
        self.assertIn("origin", d["error"])
        s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "k"})
        opts["publicKey"]["rp"]["id"] = "evil.example"  # rpIdHash 가 다름
        cred, _ = sa.create(opts, ORIGIN)
        s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred})
        self.assertEqual(s, 400)
        self.assertIn("rpIdHash", d["error"])
        s, opts, _ = call("POST", "/api/me/register/options", {"username": name, "passkey_name": "k"})
        cred, _ = sa.create(opts, ORIGIN)
        self.assertEqual(call("POST", "/api/me/register/verify", {"credential": cred})[0], 200)
        s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred})  # 같은 등록 응답 다시
        self.assertEqual(s, 400)
        self.assertIn("already used", d["error"])
        s, d, _ = call("POST", "/api/me/register/options", {"username": name.upper(), "passkey_name": "k"})
        self.assertEqual(s, 409)


class Login(unittest.TestCase):
    def test_login_new_challenge_each_time_and_signature(self):  # C27 C28 C29 C30
        name, _, key = new_account()
        chs = {call("POST", "/api/me/login/options", {})[1]["publicKey"]["challenge"] for _ in range(5)}
        self.assertEqual(len(chs), 5)
        s, d, cookie, _ = login(key, tamper=True)
        self.assertEqual(s, 401)
        self.assertIn("Signature", d["error"])
        self.assertIsNone(cookie)
        s, d, cookie, _ = login(key)
        self.assertEqual(s, 200, d)
        self.assertEqual(d["account"]["username"], name)
        self.assertEqual(call("GET", "/api/me/items", cookie=cookie)[0], 200)

    def test_used_challenge_is_rejected(self):  # C31
        _, _, key = new_account()
        s, d, cookie, cred = login(key)
        self.assertEqual(s, 200)
        s, d, h = call("POST", "/api/me/login/verify", {"credential": cred})  # 같은 응답 다시 보내기
        self.assertEqual(s, 401)
        self.assertEqual(d["error"], "This challenge was already used")
        self.assertIsNone(me_cookie(h))

    def test_failed_try_also_burns_challenge(self):
        _, _, key = new_account()
        s, opts, _ = call("POST", "/api/me/login/options", {})
        bad = sa.get(opts, ORIGIN, key, tamper=True)
        self.assertEqual(call("POST", "/api/me/login/verify", {"credential": bad})[0], 401)
        good = sa.get(opts, ORIGIN, key)
        s, d, _ = call("POST", "/api/me/login/verify", {"credential": good})
        self.assertEqual(s, 401)
        self.assertIn("already used", d["error"])

    def test_expired_challenge(self):
        _, _, key = new_account()
        s, opts, _ = call("POST", "/api/me/login/options", {})
        with db() as c:
            c.execute("UPDATE me_challenges SET expires_at = '2000-01-01T00:00:00Z' WHERE challenge = ?",
                      (opts["publicKey"]["challenge"],))
        s, d, _ = call("POST", "/api/me/login/verify", {"credential": sa.get(opts, ORIGIN, key)})
        self.assertEqual(s, 401)
        self.assertIn("expired", d["error"])

    def test_wrong_origin_on_login(self):
        _, _, key = new_account()
        s, opts, _ = call("POST", "/api/me/login/options", {})
        s, d, _ = call("POST", "/api/me/login/verify", {"credential": sa.get(opts, "https://evil.example", key)})
        self.assertEqual(s, 401)

    def test_logout_kills_session(self):  # C33
        _, cookie, _ = new_account()
        self.assertEqual(call("GET", "/api/me/items", cookie=cookie)[0], 200)
        s, d, h = call("POST", "/api/me/logout", cookie=cookie)
        self.assertEqual(s, 200)
        self.assertIn("Max-Age=0", h["Set-Cookie"])
        s, d, _ = call("GET", "/api/me/items", cookie=cookie)
        self.assertEqual(s, 401)

    def test_sign_counter_must_increase(self):
        _, _, key = new_account()
        key.count = 5
        self.assertEqual(login(key)[0], 200)
        self.assertEqual(login(key)[0], 401)  # 5 → 5: 복제 의심
        key.count = 6
        self.assertEqual(login(key)[0], 200)


class TwoPasskeys(unittest.TestCase):
    def test_add_second_delete_first_login_with_second(self):  # C42 C43 C44 C45 C46
        name, cookie, key1 = new_account()
        s, d, key2, opts = add_passkey(cookie, "phone")
        self.assertEqual(s, 200, d)
        self.assertEqual(len(opts["publicKey"]["excludeCredentials"]), 1)  # 첫 패스키가 제외 목록에
        s, d, _ = call("GET", "/api/me/passkeys", cookie=cookie)
        self.assertEqual([p["name"] for p in d["passkeys"]], ["laptop", "phone"])
        self.assertTrue(all(p["created_at"] for p in d["passkeys"]))
        first = d["passkeys"][0]["id"]
        s, d, _ = call("DELETE", f"/api/me/passkeys/{first}", cookie=cookie)
        self.assertEqual((s, d["left"]), (200, 1))
        s, d, _, _ = login(key1)
        self.assertEqual(s, 401)
        self.assertIn("not registered", d["error"])
        s, d, cookie2, _ = login(key2)
        self.assertEqual(s, 200)
        last = call("GET", "/api/me/passkeys", cookie=cookie2)[1]["passkeys"][0]["id"]
        s, d, _ = call("DELETE", f"/api/me/passkeys/{last}", cookie=cookie2)
        self.assertEqual(s, 409)  # 마지막 패스키는 지울 수 없음
        self.assertEqual(len(call("GET", "/api/me/passkeys", cookie=cookie2)[1]["passkeys"]), 1)

    def test_add_passkey_challenge_cannot_be_used_by_other_account(self):
        _, cookie_a, _ = new_account("a")
        _, cookie_b, _ = new_account("b")
        s, opts, _ = call("POST", "/api/me/register/options", {"passkey_name": "x"}, cookie=cookie_a)
        cred, _ = sa.create(opts, ORIGIN)
        s, d, _ = call("POST", "/api/me/register/verify", {"credential": cred}, cookie=cookie_b)
        self.assertEqual(s, 403)


class CrossAccount(unittest.TestCase):
    def test_accounts_cannot_read_each_other(self):  # C36 C37 C38 C39 C40
        a_name, a, key_a = new_account("alice")
        b_name, b, key_b = new_account("bob")
        call("POST", "/api/me/items", {"category": "memo", "title": "A only"}, cookie=a)
        s, d, _ = call("POST", "/api/me/items", {"category": "memo", "title": "B only"}, cookie=b)
        self.assertEqual(s, 201)
        b_item = d["id"]
        a_item = call("GET", "/api/me/items", cookie=a)[1]["items"][-1]["id"]
        b_before = len(call("GET", "/api/me/items", cookie=b)[1]["items"])
        self.assertEqual(call("GET", f"/api/me/items/{b_item}", cookie=a)[0], 404)   # A → B
        self.assertEqual(call("DELETE", f"/api/me/items/{b_item}", cookie=a)[0], 404)
        self.assertEqual(call("GET", f"/api/me/items/{a_item}", cookie=b)[0], 404)   # B → A
        self.assertEqual(call("GET", f"/api/me/items/{a_item}", cookie=a)[0], 200)
        s, d, _ = call("GET", f"/api/me/items?account={b_name}&account_id=1", cookie=a)
        self.assertEqual([i["title"] for i in d["items"]][-1], "A only")
        self.assertNotIn("B only", [i["title"] for i in d["items"]])
        s, d, _ = call("POST", "/api/me/items", {"category": "memo", "title": "sneaky", "account_id": 1,
                                                  "username": b_name}, cookie=a)
        self.assertEqual(s, 201)
        self.assertNotIn("sneaky", [i["title"] for i in call("GET", "/api/me/items", cookie=b)[1]["items"]])
        b_pk = call("GET", "/api/me/passkeys", cookie=b)[1]["passkeys"][0]["id"]
        self.assertEqual(call("DELETE", f"/api/me/passkeys/{b_pk}", cookie=a)[0], 404)
        self.assertEqual(len(call("GET", "/api/me/items", cookie=b)[1]["items"]), b_before)

    def test_other_accounts_passkey_cannot_log_into_me(self):
        a_name, _, key_a = new_account("alice")
        _, _, key_b = new_account("bob")
        s, d, cookie, _ = login(key_b, username=a_name)
        self.assertEqual(s, 403)
        self.assertIsNone(cookie)
        s, d, cookie, _ = login(key_a, username=a_name)
        self.assertEqual(s, 200)


if __name__ == "__main__":
    unittest.main()
