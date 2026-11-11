"""시험용 소프트웨어 인증기 — 자동 테스트와 확인 기록(verify_passkey.py)에서 브라우저+인증기 대신 씁니다.

실제 인증기처럼 P-256 키 쌍을 만들고, 개인키는 이 객체 안에만 두며, 서버에는 공개키·서명만 내보냅니다.
실제 사이트에서는 휴대폰·PC·보안 키가 이 일을 합니다. (운영 코드에서는 쓰지 않습니다)
"""
import hashlib
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import passkey  # noqa: E402
from passkey import G, N, b64url, scalar_mult  # noqa: E402


def cbor(v):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return head(3, len(b)) + b
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(type(v))


def der_int(i):
    b = i.to_bytes(33, "big").lstrip(b"\x00")
    if b[0] & 0x80:
        b = b"\x00" + b
    return b"\x02" + bytes([len(b)]) + b


class Passkey:
    """인증기 안의 패스키 하나. private 는 밖으로 내보내지 않습니다."""

    def __init__(self, rp_id, user_handle, aaguid=b"\x00" * 16, backup=True):
        self.rp_id = rp_id
        self.user_handle = user_handle
        self.credential_id = secrets.token_bytes(32)
        self._private = secrets.randbelow(N - 1) + 1
        self.public = scalar_mult(self._private, G)
        self.aaguid = aaguid
        self.backup = backup
        self.count = 0

    def cose_public_key(self):
        x, y = self.public
        return cbor({1: 2, 3: -7, -1: 1, -2: x.to_bytes(32, "big"), -3: y.to_bytes(32, "big")})

    def flags(self, at=False):
        f = passkey.FLAG_UP | passkey.FLAG_UV
        if self.backup:
            f |= passkey.FLAG_BE | passkey.FLAG_BS
        if at:
            f |= passkey.FLAG_AT
        return f

    def sign(self, message):
        e = int.from_bytes(hashlib.sha256(message).digest(), "big")
        while True:
            k = secrets.randbelow(N - 1) + 1
            r = scalar_mult(k, G)[0] % N
            s = pow(k, -1, N) * (e + r * self._private) % N
            if r and s:
                body = der_int(r) + der_int(s)
                return b"\x30" + bytes([len(body)]) + body


def client_data(kind, challenge, origin):
    return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False},
                      separators=(",", ":")).encode()


def create(options, origin, aaguid=b"\x00" * 16, backup=True):
    """navigator.credentials.create() 흉내. (서버로 보낼 JSON, 인증기 안의 Passkey)"""
    pk = options["publicKey"]
    key = Passkey(pk["rp"]["id"], pk["user"]["id"], aaguid, backup)
    cd = client_data("webauthn.create", pk["challenge"], origin)
    auth_data = (hashlib.sha256(pk["rp"]["id"].encode()).digest() + bytes([key.flags(at=True)])
                 + key.count.to_bytes(4, "big") + aaguid + len(key.credential_id).to_bytes(2, "big")
                 + key.credential_id + key.cose_public_key())
    att = cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
    cid = b64url(key.credential_id)
    return {"id": cid, "rawId": cid, "type": "public-key",
            "response": {"clientDataJSON": b64url(cd), "attestationObject": b64url(att),
                         "transports": ["internal", "hybrid"]}}, key


def get(options, origin, key, tamper=False):
    """navigator.credentials.get() 흉내. tamper=True 면 서명 한 바이트를 바꿔 '틀린 서명'을 만듭니다."""
    pk = options["publicKey"]
    cd = client_data("webauthn.get", pk["challenge"], origin)
    auth_data = hashlib.sha256(key.rp_id.encode()).digest() + bytes([key.flags()]) + key.count.to_bytes(4, "big")
    sig = key.sign(auth_data + hashlib.sha256(cd).digest())
    if tamper:
        sig = sig[:-1] + bytes([sig[-1] ^ 0x01])
    cid = b64url(key.credential_id)
    return {"id": cid, "rawId": cid, "type": "public-key",
            "response": {"clientDataJSON": b64url(cd), "authenticatorData": b64url(auth_data),
                         "signature": b64url(sig), "userHandle": key.user_handle}}
