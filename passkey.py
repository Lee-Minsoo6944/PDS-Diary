"""패스키(WebAuthn) 응답 검사 — 표준 라이브러리만 씁니다(과제 8).

서버가 하는 일은 '검사'뿐입니다. 개인키는 인증기(휴대폰·PC·보안 키) 밖으로 나오지 않고,
서버는 등록 때 받은 공개키로 로그인 때 온 서명이 맞는지만 확인합니다.

- verify_registration(): 등록 응답에서 공개키·자격 증명 ID를 꺼내고 rpId·origin·챌린지·플래그를 확인
- verify_assertion():    로그인 응답의 서명을 저장된 공개키로 확인
- 지원하는 서명 방식: ES256(-7, P-256 타원곡선) · RS256(-257, RSA 2048비트 이상)
  공개 자료(공개키·서명·메시지)만 다루므로, 계산 시간이 드러나도 새는 비밀이 없습니다.
"""
import base64
import hashlib
import hmac
import json

ALG_ES256 = -7
ALG_RS256 = -257
SUPPORTED_ALGS = (ALG_ES256, ALG_RS256)

FLAG_UP = 0x01  # 사용자가 있음(버튼·터치)
FLAG_UV = 0x04  # 사용자 확인(지문·얼굴·PIN)
FLAG_BE = 0x08  # 다른 기기로 동기화될 수 있는 패스키
FLAG_BS = 0x10  # 지금 동기화(백업)되어 있음
FLAG_AT = 0x40  # 등록 응답에 공개키가 들어 있음
FLAG_ED = 0x80  # 확장 자료가 붙어 있음


class WebAuthnError(Exception):
    """검사 실패. 메시지는 화면에 그대로 보여도 되는 내용만 담습니다."""


# ---------------------------------------------------------------- base64url
def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s):
    if not isinstance(s, str) or len(s) > 20000:
        raise WebAuthnError("Bad base64url value")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (ValueError, TypeError):
        raise WebAuthnError("Bad base64url value")


# ---------------------------------------------------------------- CBOR (읽기만, 필요한 만큼)
def cbor_decode(data, pos=0, depth=0):
    """(값, 다음 위치). 정수·바이트·문자열·배열·맵·true/false/null 만 읽습니다."""
    if depth > 8:
        raise WebAuthnError("CBOR nested too deeply")
    if pos >= len(data):
        raise WebAuthnError("CBOR ended early")
    ib = data[pos]
    major, info = ib >> 5, ib & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(data):
            raise WebAuthnError("CBOR ended early")
        arg = int.from_bytes(data[pos:pos + size], "big")
        pos += size
    else:
        raise WebAuthnError("CBOR length form not supported")
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise WebAuthnError("CBOR ended early")
        raw = data[pos:pos + arg]
        pos += arg
        if major == 2:
            return bytes(raw), pos
        try:
            return raw.decode("utf-8"), pos
        except UnicodeDecodeError:
            raise WebAuthnError("CBOR text is not UTF-8")
    if major == 4:
        if arg > 64:
            raise WebAuthnError("CBOR array too long")
        out = []
        for _ in range(arg):
            v, pos = cbor_decode(data, pos, depth + 1)
            out.append(v)
        return out, pos
    if major == 5:
        if arg > 64:
            raise WebAuthnError("CBOR map too long")
        out = {}
        for _ in range(arg):
            k, pos = cbor_decode(data, pos, depth + 1)
            if isinstance(k, (list, dict)):
                raise WebAuthnError("CBOR map key not supported")
            v, pos = cbor_decode(data, pos, depth + 1)
            out[k] = v
        return out, pos
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    raise WebAuthnError("CBOR type not supported")


# ---------------------------------------------------------------- P-256 (secp256r1) ECDSA 검증
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def on_curve(pt):
    if pt is None:
        return False
    x, y = pt
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None  # 무한원점
        lam = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def scalar_mult(k, pt):
    result = None
    addend = pt
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def der_to_rs(sig):
    """ECDSA 서명(DER: SEQUENCE{INTEGER r, INTEGER s}) → (r, s)"""
    def read_int(buf, i):
        if i + 2 > len(buf) or buf[i] != 0x02:
            raise WebAuthnError("Bad signature encoding")
        ln = buf[i + 1]
        if ln == 0 or ln > 33 or i + 2 + ln > len(buf):
            raise WebAuthnError("Bad signature encoding")
        return int.from_bytes(buf[i + 2:i + 2 + ln], "big"), i + 2 + ln

    if len(sig) < 8 or sig[0] != 0x30 or sig[1] != len(sig) - 2:
        raise WebAuthnError("Bad signature encoding")
    r, i = read_int(sig, 2)
    s, i = read_int(sig, i)
    if i != len(sig):
        raise WebAuthnError("Bad signature encoding")
    return r, s


def ecdsa_p256_verify(pub, message, sig_der):
    r, s = der_to_rs(sig_der)
    if not (1 <= r < N and 1 <= s < N) or not on_curve(pub):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    pt = point_add(scalar_mult(e * w % N, G), scalar_mult(r * w % N, pub))
    return pt is not None and pt[0] % N == r


# ---------------------------------------------------------------- RSA PKCS#1 v1.5 + SHA-256 검증
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def rsa_sha256_verify(n, e, message, sig):
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    m = pow(int.from_bytes(sig, "big"), e, n)
    em = m.to_bytes(k, "big")
    t = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    want = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, want)


# ---------------------------------------------------------------- COSE 공개키
def parse_cose_key(cose):
    """COSE_Key(CBOR 맵) → 검사용 dict. 지원하지 않는 형식은 거절합니다."""
    if not isinstance(cose, dict):
        raise WebAuthnError("Public key is not a COSE map")
    kty, alg = cose.get(1), cose.get(3)
    if alg == ALG_ES256:
        x, y = cose.get(-2), cose.get(-3)
        if kty != 2 or cose.get(-1) != 1 or not isinstance(x, bytes) or not isinstance(y, bytes) \
                or len(x) != 32 or len(y) != 32:
            raise WebAuthnError("ES256 key must be a P-256 point")
        pt = (int.from_bytes(x, "big"), int.from_bytes(y, "big"))
        if not on_curve(pt):
            raise WebAuthnError("Public key is not on the P-256 curve")
        return {"alg": ALG_ES256, "point": pt}
    if alg == ALG_RS256:
        n, e = cose.get(-1), cose.get(-2)
        if kty != 3 or not isinstance(n, bytes) or not isinstance(e, bytes):
            raise WebAuthnError("RS256 key must have n and e")
        n_int, e_int = int.from_bytes(n, "big"), int.from_bytes(e, "big")
        if n_int.bit_length() < 2048 or e_int < 3 or e_int % 2 == 0:
            raise WebAuthnError("RSA key is too small or malformed")
        return {"alg": ALG_RS256, "n": n_int, "e": e_int}
    raise WebAuthnError("Only ES256 (-7) and RS256 (-257) keys are accepted")


def cose_summary(cose_bytes):
    """화면·기록에 보여 줄 공개키 요약(공개 정보)."""
    cose, _ = cbor_decode(cose_bytes)
    key = parse_cose_key(cose)
    if key["alg"] == ALG_ES256:
        return {"alg": "ES256", "kty": "EC2", "crv": "P-256",
                "x": format(key["point"][0], "064x"), "y": format(key["point"][1], "064x")}
    return {"alg": "RS256", "kty": "RSA", "n_bits": key["n"].bit_length(), "e": key["e"]}


def verify_signature(cose_bytes, message, sig):
    cose, _ = cbor_decode(cose_bytes)
    key = parse_cose_key(cose)
    if key["alg"] == ALG_ES256:
        return ecdsa_p256_verify(key["point"], message, sig)
    return rsa_sha256_verify(key["n"], key["e"], message, sig)


# ---------------------------------------------------------------- 인증기 데이터(authenticatorData)
def parse_auth_data(ad):
    if len(ad) < 37:
        raise WebAuthnError("authenticatorData is too short")
    out = {"rp_id_hash": ad[:32], "flags": ad[32], "sign_count": int.from_bytes(ad[33:37], "big")}
    pos = 37
    if out["flags"] & FLAG_AT:
        if len(ad) < pos + 18:
            raise WebAuthnError("authenticatorData is too short")
        out["aaguid"] = ad[pos:pos + 16]
        ln = int.from_bytes(ad[pos + 16:pos + 18], "big")
        pos += 18
        if ln < 16 or ln > 1023 or len(ad) < pos + ln:
            raise WebAuthnError("Bad credential ID length")
        out["credential_id"] = ad[pos:pos + ln]
        pos += ln
        _, end = cbor_decode(ad, pos)
        out["public_key"] = ad[pos:end]  # COSE 원본 바이트를 그대로 저장
        pos = end
    if out["flags"] & FLAG_ED:
        _, pos = cbor_decode(ad, pos)
    if pos != len(ad):
        raise WebAuthnError("authenticatorData has extra bytes")
    return out


def format_aaguid(raw):
    h = raw.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


# ---------------------------------------------------------------- 공통 검사
def parse_client_data(b64, want_type, origin):
    raw = b64url_decode(b64)
    try:
        cd = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WebAuthnError("clientDataJSON is not JSON")
    if not isinstance(cd, dict):
        raise WebAuthnError("clientDataJSON is not an object")
    if cd.get("type") != want_type:
        raise WebAuthnError(f"clientData.type must be {want_type}")
    if cd.get("origin") != origin:
        raise WebAuthnError("clientData.origin does not match this site")
    if cd.get("crossOrigin") is True:
        raise WebAuthnError("Cross-origin requests are not accepted")
    if not isinstance(cd.get("challenge"), str):
        raise WebAuthnError("clientData.challenge is missing")
    return cd, raw


def read_challenge(credential, want_type, origin):
    """응답을 검사하기 전에, 어떤 챌린지에 대한 응답인지 먼저 꺼냅니다(서버 보관값과 맞춰 보려고)."""
    resp = credential.get("response") if isinstance(credential, dict) else None
    if not isinstance(resp, dict):
        raise WebAuthnError("credential.response is missing")
    cd, _ = parse_client_data(resp.get("clientDataJSON"), want_type, origin)
    return cd["challenge"]


def check_flags(flags):
    if not flags & FLAG_UP:
        raise WebAuthnError("User presence flag is not set")
    if not flags & FLAG_UV:
        raise WebAuthnError("User verification (PIN or biometrics) is required")


def check_credential_shape(credential):
    if not isinstance(credential, dict) or credential.get("type") != "public-key":
        raise WebAuthnError("credential.type must be public-key")
    raw_id = b64url_decode(credential.get("rawId") or credential.get("id"))
    if credential.get("id") and b64url_decode(credential["id"]) != raw_id:
        raise WebAuthnError("credential.id and rawId differ")
    return raw_id


# ---------------------------------------------------------------- 등록
def verify_registration(credential, expected_challenge, rp_id, origin):
    raw_id = check_credential_shape(credential)
    resp = credential["response"]
    cd, _ = parse_client_data(resp.get("clientDataJSON"), "webauthn.create", origin)
    if not hmac.compare_digest(cd["challenge"], expected_challenge):
        raise WebAuthnError("Challenge does not match")
    att, _ = cbor_decode(b64url_decode(resp.get("attestationObject")))
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes) or not isinstance(att.get("fmt"), str):
        raise WebAuthnError("attestationObject is malformed")
    ad = parse_auth_data(att["authData"])
    if not hmac.compare_digest(ad["rp_id_hash"], hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("rpIdHash does not match this site")
    check_flags(ad["flags"])
    if "public_key" not in ad:
        raise WebAuthnError("No public key in the registration response")
    if ad["credential_id"] != raw_id:
        raise WebAuthnError("Credential ID differs from authenticatorData")
    cose, _ = cbor_decode(ad["public_key"])
    key = parse_cose_key(cose)
    transports = resp.get("transports") if isinstance(resp.get("transports"), list) else []
    transports = [t for t in transports if isinstance(t, str) and len(t) <= 20][:6]
    # attestation 은 "none" 으로 요청했습니다. 인증기가 다른 형식(packed 등)을 보내도 증명서 체인은 검사하지 않고
    # 형식 이름만 기록합니다(누가 만든 인증기인지 증명받을 필요가 없는 개인 페이지라서).
    return {
        "credential_id": b64url(raw_id),
        "public_key": b64url(ad["public_key"]),
        "alg": key["alg"],
        "sign_count": ad["sign_count"],
        "aaguid": format_aaguid(ad["aaguid"]),
        "backup_eligible": bool(ad["flags"] & FLAG_BE),
        "backed_up": bool(ad["flags"] & FLAG_BS),
        "transports": transports,
        "fmt": att["fmt"][:20],
    }


# ---------------------------------------------------------------- 로그인
def verify_assertion(credential, expected_challenge, rp_id, origin, public_key_b64, stored_sign_count):
    """서명이 맞으면 새 signCount 를 돌려줍니다. 하나라도 틀리면 WebAuthnError."""
    check_credential_shape(credential)
    resp = credential["response"]
    cd, cd_raw = parse_client_data(resp.get("clientDataJSON"), "webauthn.get", origin)
    if not hmac.compare_digest(cd["challenge"], expected_challenge):
        raise WebAuthnError("Challenge does not match")
    ad_raw = b64url_decode(resp.get("authenticatorData"))
    ad = parse_auth_data(ad_raw)
    if not hmac.compare_digest(ad["rp_id_hash"], hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("rpIdHash does not match this site")
    check_flags(ad["flags"])
    sig = b64url_decode(resp.get("signature"))
    signed = ad_raw + hashlib.sha256(cd_raw).digest()  # 인증기가 서명한 바이트 = authData ‖ SHA-256(clientDataJSON)
    if not verify_signature(b64url_decode(public_key_b64), signed, sig):
        raise WebAuthnError("Signature check failed")
    new_count = ad["sign_count"]
    # 동기화 패스키는 늘 0. 0이 아닌 값을 쓰는 인증기에서 숫자가 줄거나 그대로면 복제 의심 → 거절
    if (new_count or stored_sign_count) and new_count <= stored_sign_count:
        raise WebAuthnError("Signature counter went backwards (possible cloned key)")
    return {"sign_count": new_count, "backed_up": bool(ad["flags"] & FLAG_BS)}
