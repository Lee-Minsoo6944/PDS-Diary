# 패스키 두 개 · 하나 삭제 — 실제 배포 서버 기록 (과제 8 카드 4)

- 일시: 2026-11-12 01:52 UTC
- 서버: `https://alstn.pythonanywhere.com/api/me/` (실제 배포된 PythonAnywhere)
- 화면 주소(Origin·rpId): `https://lee-minsoo6944.github.io` — 결과물 https://lee-minsoo6944.github.io/About-me/ 와 같은 조건
- 시험 계정: `test_twokeys_a515f1`
- **두 패스키 모두 `tools/soft_authenticator.py` 가 이 PC에서 만든 소프트웨어 시험 키입니다.** 실제 계정(`123`)의 첫 패스키는 구글 비밀번호 관리자에 있고, 이 PC에는 두 번째로 쓸 다른 인증기(Windows Hello PIN·휴대폰·보안 키)가 없어 같은 서버 흐름을 시험 키 두 개로 확인했습니다. 서버가 하는 검사(챌린지·origin·rpIdHash·서명)는 실제 인증기와 똑같습니다.
- 세션 토큰은 앞 5글자 뒤를 가렸습니다.


### 1. 계정 만들기 + 첫 번째 패스키

```
POST https://alstn.pythonanywhere.com/api/me/register/options
Origin: https://lee-minsoo6944.github.io
{"username": "test_twokeys_a515f1", "passkey_name": "시험 키 1 (PC)"}
→ 200
{"publicKey": {"challenge": "E99O5iAimqX_kxfhL0wiYjKpqkFE…(43자)", "rp": {"id": "lee-minsoo6944.github.io", "name": "Lee Minsoo · About me"}, "user": {"id": "dxX1rop5QDJ-gUEXlwWLGQ", "name": "test_twokeys_a515f1", "displayName": "test_two…
```
```
POST https://alstn.pythonanywhere.com/api/me/register/verify
Origin: https://lee-minsoo6944.github.io
{"credential": {"id": "_3h0bGS0IdreSt67A8WSAvHu…(43자)", "rawId": "_3h0bGS0IdreSt67A8WSAvHu…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(198자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
{"ok": true, "account": {"username": "test_twokeys_a515f1"}, "passkey": {"id": 3, "name": "시험 키 1 (PC)", "created_at": "2026-11-12T01:52:09Z", "last_used_at": null, "storage": "이 기기 · 이 인증기에만 있음", "aaguid": "00000000-0000-0000-0000-00000…
```

### 2. 두 번째 패스키 추가 (excludeCredentials 에 첫 패스키 1개)

```
POST https://alstn.pythonanywhere.com/api/me/register/options
Origin: https://lee-minsoo6944.github.io
Authorization: Bearer A3SPr…(masked)
{"passkey_name": "시험 키 2 (예비)"}
→ 200
{"publicKey": {"challenge": "UFt_pW7FliiVGlVL2v74OUR2QTfn…(43자)", "rp": {"id": "lee-minsoo6944.github.io", "name": "Lee Minsoo · About me"}, "user": {"id": "dxX1rop5QDJ-gUEXlwWLGQ", "name": "test_twokeys_a515f1", "displayName": "test_two…
```
```
POST https://alstn.pythonanywhere.com/api/me/register/verify
Origin: https://lee-minsoo6944.github.io
Authorization: Bearer A3SPr…(masked)
{"credential": {"id": "lGBGWevqupJBfq3sjGUVWm3f…(43자)", "rawId": "lGBGWevqupJBfq3sjGUVWm3f…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(198자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
{"ok": true, "account": {"username": "test_twokeys_a515f1"}, "passkey": {"id": 4, "name": "시험 키 2 (예비)", "created_at": "2026-11-12T01:52:11Z", "last_used_at": null, "storage": "이 기기 · 이 인증기에만 있음", "aaguid": "00000000-0000-0000-0000-00000…
```

### ✅ 3. 한 계정에 패스키 두 개 (C42, C43)

```
GET https://alstn.pythonanywhere.com/api/me/passkeys
Origin: https://lee-minsoo6944.github.io
Authorization: Bearer A3SPr…(masked)
→ 200
{"passkeys": ["#3 시험 키 1 (PC) (2026-11-12T0…(37자)", "#4 시험 키 2 (예비) (2026-11-12T0…(37자)"]}
```

### 4. 첫 번째 패스키 삭제

```
DELETE https://alstn.pythonanywhere.com/api/me/passkeys/3
Origin: https://lee-minsoo6944.github.io
Authorization: Bearer A3SPr…(masked)
→ 200
{"ok": true, "left": 1}
```

### ✅ 5. 하나 지운 뒤 — 남은 패스키 / 지운 패스키로 로그인 (C44, C45)

왼쪽은 남은 시험 키 2, 오른쪽은 지운 시험 키 1. 시험 키 1은 인증기 안에 그대로 있어 올바른 서명을 만들지만, 서버에 그 공개키가 없어 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST https://alstn.pythonanywhere.com/api/me/login/verify<br>Origin: https://lee-minsoo6944.github.io<br>{"credential": {"id": "lGBGWevqupJBfq3sjGUVWm3f…(43자)", "rawId": "lGBGWevqupJBfq3sjGUVWm3f…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(194자)", "authenticatorData": "YH_0Kmfc7hSaEVO42k8JEqbj…(50자)", "signature": "MEYCIQCLar5yXNe287yqS2YV…(96자)", "userHandle": "dxX1rop5QDJ-gUEXlwWLGQ"}}}<br>→ 200<br>{"ok": true, "account": {"username": "test_twokeys_a515f1"}, "passkey": "시험 키 2 (예비)", "token": "woiGc…(masked)"}</pre> | <pre>POST https://alstn.pythonanywhere.com/api/me/login/verify<br>Origin: https://lee-minsoo6944.github.io<br>{"credential": {"id": "_3h0bGS0IdreSt67A8WSAvHu…(43자)", "rawId": "_3h0bGS0IdreSt67A8WSAvHu…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(194자)", "authenticatorData": "YH_0Kmfc7hSaEVO42k8JEqbj…(50자)", "signature": "MEQCIB3VywCEX268VRheFCrE…(94자)", "userHandle": "dxX1rop5QDJ-gUEXlwWLGQ"}}}<br>→ 401<br>{"error": "This passkey is not registered (it may have been deleted)"}</pre> |

### ✅ 6. 마지막 남은 패스키 삭제 시도 (C46)

패스키가 하나만 남으면 서버가 삭제를 막습니다. 비밀번호·이메일 복구가 없어서, 남은 하나마저 잃으면 이 계정에는 다시 들어올 수 없습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET https://alstn.pythonanywhere.com/api/me/passkeys<br>Origin: https://lee-minsoo6944.github.io<br>Authorization: Bearer woiGc…(masked)<br>→ 200<br>{"passkeys": ["#4 시험 키 2 (예비) (2026-11-12T0…(37자)"]}</pre> | <pre>DELETE https://alstn.pythonanywhere.com/api/me/passkeys/4<br>Origin: https://lee-minsoo6944.github.io<br>Authorization: Bearer woiGc…(masked)<br>→ 409<br>{"error": "This is your last passkey. Add another passkey first, or you could never log in again."}</pre> |

---

**결과: 모두 통과**

