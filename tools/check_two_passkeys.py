"""실제 배포된 서버에서 '패스키 두 개 → 하나 삭제 → 로그인'을 확인하고 Markdown 기록을 남깁니다 (과제 8 카드 4).

    py tools/check_two_passkeys.py > docs/passkey-two-keys-production.md

- 서버: https://alstn.pythonanywhere.com, 화면 주소(Origin·rpId): https://lee-minsoo6944.github.io (결과물 주소와 같음)
- 두 패스키는 tools/soft_authenticator.py 로 만든 **소프트웨어 시험 키**입니다(개인키는 이 프로그램 안에만).
  실제 휴대폰·보안 키가 아니라는 점을 기록 맨 위에 적습니다.
- 시험 계정 이름은 test_twokeys_<무작위>. 세션 토큰은 앞 5글자 뒤를 가립니다.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soft_authenticator as sa  # noqa: E402

API = os.environ.get("ME_API", "https://alstn.pythonanywhere.com/api/me/")
ORIGIN = os.environ.get("ME_PAGE_ORIGIN", "https://lee-minsoo6944.github.io")
SECRETS, OUT, FAILS = [], [], []


def req(method, path, body=None, token=None):
    h = {"Origin": ORIGIN, "User-Agent": "passkey-check/1.0"}
    if method != "GET":
        h["X-PDS"] = "1"
    if body is not None:
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                               method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    payload = json.loads(raw) if raw else None
    if isinstance(payload, dict) and payload.get("token"):
        SECRETS.append(payload["token"])
    return {"method": method, "path": path, "body": body, "token": token, "status": status, "payload": payload}


def short(v, keep=24):
    if isinstance(v, str) and len(v) > keep + 8:
        return f"{v[:keep]}…({len(v)}자)"
    if isinstance(v, dict):
        return {k: (x if k == "error" else short(x, keep)) for k, x in v.items()}
    if isinstance(v, list):
        return [short(x, keep) for x in v]
    return v


def show(r):
    lines = [f"{r['method']} {API.rstrip('/')}/{r['path']}", f"Origin: {ORIGIN}"]
    if r["token"]:
        lines.append(f"Authorization: Bearer {r['token']}")
    if r["body"] is not None:
        lines.append(json.dumps(short(r["body"]), ensure_ascii=False))
    lines.append(f"→ {r['status']}")
    p = r["payload"]
    if isinstance(p, dict) and p.get("token"):  # 줄이기 전에 먼저 가림
        p = dict(p, token=p["token"][:5] + "…(masked)")
    if isinstance(p, dict) and "passkeys" in p:
        p = {"passkeys": [f"#{x['id']} {x['name']} ({x['created_at']})" for x in p["passkeys"]]}
    text = json.dumps(short(p, 28), ensure_ascii=False)
    if not (isinstance(p, dict) and "error" in p) and len(text) > 240:
        text = text[:237] + "…"
    lines.append(text)
    text = "\n".join(lines)
    for s in SECRETS:
        text = text.replace(s, s[:5] + "…(masked)")
    return text


def pre(r):
    return "<pre>" + show(r).replace("|", "&#124;").replace("\n", "<br>") + "</pre>"


def block(title, *rs):
    OUT.append(f"\n### {title}\n")
    for r in rs:
        OUT.append("```\n" + show(r) + "\n```")


def pair(title, ok, bad, want_bad, note=""):
    good = ok["status"] == 200 and bad["status"] == want_bad
    if not good:
        FAILS.append(title)
    OUT.append(f"\n### {'✅' if good else '❌'} {title}\n")
    if note:
        OUT.append(note + "\n")
    OUT.append("| 통과한 요청 | 거절된 요청 |\n|---|---|")
    OUT.append(f"| {pre(ok)} | {pre(bad)} |")


def login(key, username=""):
    o = req("POST", "login/options", {"username": username})
    return req("POST", "login/verify", {"credential": sa.get(o["payload"], ORIGIN, key)})


def main():
    name = f"test_twokeys_{secrets.token_hex(3)}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT.append("# 패스키 두 개 · 하나 삭제 — 실제 배포 서버 기록 (과제 8 카드 4)\n")
    OUT.append(f"- 일시: {now}\n- 서버: `{API}` (실제 배포된 PythonAnywhere)\n"
               f"- 화면 주소(Origin·rpId): `{ORIGIN}` — 결과물 https://lee-minsoo6944.github.io/About-me/ 와 같은 조건\n"
               f"- 시험 계정: `{name}`\n"
               "- **두 패스키 모두 `tools/soft_authenticator.py` 가 이 PC에서 만든 소프트웨어 시험 키입니다.** "
               "실제 계정(`123`)의 첫 패스키는 구글 비밀번호 관리자에 있고, 이 PC에는 두 번째로 쓸 다른 인증기(Windows Hello PIN·휴대폰·보안 키)가 없어 "
               "같은 서버 흐름을 시험 키 두 개로 확인했습니다. 서버가 하는 검사(챌린지·origin·rpIdHash·서명)는 실제 인증기와 똑같습니다.\n"
               "- 세션 토큰은 앞 5글자 뒤를 가렸습니다.\n")

    o1 = req("POST", "register/options", {"username": name, "passkey_name": "시험 키 1 (PC)"})
    cred1, key1 = sa.create(o1["payload"], ORIGIN, backup=False)
    v1 = req("POST", "register/verify", {"credential": cred1})
    token = v1["payload"]["token"]
    block("1. 계정 만들기 + 첫 번째 패스키", o1, v1)

    o2 = req("POST", "register/options", {"passkey_name": "시험 키 2 (예비)"}, token=token)
    cred2, key2 = sa.create(o2["payload"], ORIGIN, backup=False)
    v2 = req("POST", "register/verify", {"credential": cred2}, token=token)
    excl = len(o2["payload"]["publicKey"]["excludeCredentials"])
    block(f"2. 두 번째 패스키 추가 (excludeCredentials 에 첫 패스키 {excl}개)", o2, v2)

    lst = req("GET", "passkeys", token=token)
    two = len(lst["payload"]["passkeys"]) == 2
    if not two:
        FAILS.append("two passkeys")
    block(f"{'✅' if two else '❌'} 3. 한 계정에 패스키 두 개 (C42, C43)", lst)
    first_id = lst["payload"]["passkeys"][0]["id"]

    d = req("DELETE", f"passkeys/{first_id}", token=token)
    block("4. 첫 번째 패스키 삭제", d)
    req("POST", "logout", token=token)

    left = login(key2)
    deleted = login(key1)
    pair("5. 하나 지운 뒤 — 남은 패스키 / 지운 패스키로 로그인 (C44, C45)", left, deleted, 401,
         "왼쪽은 남은 시험 키 2, 오른쪽은 지운 시험 키 1. 시험 키 1은 인증기 안에 그대로 있어 올바른 서명을 만들지만, "
         "서버에 그 공개키가 없어 거절됩니다.")
    t2 = left["payload"]["token"]
    last_id = req("GET", "passkeys", token=t2)["payload"]["passkeys"][0]["id"]
    pair("6. 마지막 남은 패스키 삭제 시도 (C46)", req("GET", "passkeys", token=t2),
         req("DELETE", f"passkeys/{last_id}", token=t2), 409,
         "패스키가 하나만 남으면 서버가 삭제를 막습니다. 비밀번호·이메일 복구가 없어서, 남은 하나마저 잃으면 이 계정에는 다시 들어올 수 없습니다.")
    req("POST", "logout", token=t2)

    OUT.append(f"\n---\n\n**결과: {'모두 통과' if not FAILS else '실패: ' + ', '.join(FAILS)}**\n")
    print("\n".join(OUT))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
