# 패스키 인증 확인 기록 (과제 8)

서버: `http://localhost:8017` · 시험 계정 `alice_80b441`, `bob_80b441` (이 기록을 만들 때마다 새로 만듦). 인증기는 `tools/soft_authenticator.py`(P-256 키 쌍을 만들고 개인키를 자기 안에만 두는 시험용 프로그램)가 맡았습니다. 세션 쿠키는 앞 5글자 뒤를 가렸고, 긴 base64 값은 앞부분과 길이만 적었습니다.

> 실제 기기(Windows Hello·휴대폰·보안 키)로 한 확인은 [PASSKEY.md](../PASSKEY.md) 의 화면 기록을 보세요. 이 파일은 같은 HTTP 요청을 매번 똑같이 다시 만들어 볼 수 있게 자동으로 남긴 것입니다.


## 1. 로그인 없이 열기 (C15–C18)


### ✅ 로그인 없이 받은 `/me/` 페이지 소스 (C18)

`GET /me/` → 200, 16318바이트. 공개 소개 문구 `안녕하세요👋, 이민수입니다.` 포함: **예** · 경계 문구 `여기부터 비공개 영역` 포함: **예** · 비공개 자료 제목 ['준비 중인 프로젝트 메모 (가상)', '한빛데이터랩', '11월 개인 회고 (가상)'] 중 소스에 들어 있는 것: **없음** · 비밀번호 입력칸(`type="password"`): **없음**

비공개 영역 자리의 실제 소스(로그인 전). 안내 문구만 있고 자료는 없습니다:

```html
<section id="private" class="private-zone" aria-labelledby="private-title">
            <h2 id="private-title">🔒 비공개 영역</h2>
            <p class="pz-note">
                이 칸의 내용은 페이지 파일에 들어 있지 않습니다. <strong>패스키로 들어온 사람</strong>에게만 서버가 따로 보내 줍니다.
                비밀번호는 쓰지 않습니다. 안의 자료는 모두 <strong>지어낸 가상의 내용</strong>입니다.
            </p>
            <p id="pz-status" class="pz-status" role="status" aria-live="polite"></p>
```

### ✅ 같은 비공개 자료 요청 — 세션 있음 / 없음 (C16, C17)

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=D28MN…(masked)<br>→ 200<br>{"items": ["#37 준비 중인 프로젝트 메모 (가상)", "#38 지원하려는 곳 목록 (가상)", "#39 11월 개인 회고 (가상)"]}</pre> | <pre>GET /api/me/items<br>Cookie: (none)<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

### ✅ 패스키 목록 요청 — 세션 있음 / 지어낸 쿠키 (C16)

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=D28MN…(masked)<br>→ 200<br>{"passkeys": ["#13 Alice laptop (2026-11-11)"]}</pre> | <pre>GET /api/me/passkeys<br>Cookie: me_session=made-up-cookie-value<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

## 2. 패스키 등록 (C19–C26)


### ✅ 등록 요청마다 챌린지가 다름 (C20)

같은 요청을 세 번 보냈을 때 서버가 준 `challenge`(32바이트 무작위 값, base64url):

1. `Zp0p2sDfwmzsQqk0G2d_fU7rTxE-Bu04krNCCzrzQ90`
2. `Q70aDeL56J3LDCCQN6njgWaLP1sBoCvFQhmvH9oxpyo`
3. `EmqtnCeT8ZW2qnkMdm_fGzJdN41hVp9JeBmP6NXtAqU`


### ✅ 등록 1단계 — 서버가 챌린지를 만들어 보내고 보관 (C19)

```
POST /api/me/register/options
Cookie: (none)
X-PDS: 1
{"passkey_name": "Bob phone", "username": "bob_80b441"}
→ 200
{"publicKey": {"challenge": "fFOccwXsrwiMSQmWV9juR8l4ZS32…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "5ZaXCZhAijGsgUeRO87jmg", "name": "bob_80b441", "displayName": "bob_80b441"}…
```
서버 DB `me_challenges` 의 그 줄(검증이 끝난 뒤라 `used_at` 이 채워져 있음. 5분 뒤 만료):

```json
[
 {
  "challenge": "fFOccwXsrwiMSQmWV9juR8l4ZS32_Dlem6HyPNSxN4s",
  "purpose": "register",
  "username": "bob_80b441",
  "created_at": "2026-11-11T07:15:59Z",
  "expires_at": "2026-11-11T07:20:59Z",
  "used_at": "2026-11-11T07:15:59Z"
 }
]
```

### ✅ 등록 2단계 — 브라우저가 보낸 요청 본문에 개인키가 없음 (C23)

아래가 `POST /api/me/register/verify` 본문 전체입니다(긴 값만 줄임). 들어 있는 것은 자격 증명 ID, `clientDataJSON`, `attestationObject`, 전송 방식뿐입니다.

```
POST /api/me/register/verify
Cookie: (none)
X-PDS: 1
{"credential": {"id": "AiA3FcT6k1eQ07XsdOJECvuv…(43자)", "rawId": "AiA3FcT6k1eQ07XsdOJECvuv…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(183자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
Set-Cookie: me_session=rL8NZ…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200
{"ok": true, "account": {"username": "bob_80b441"}, "passkey": {"id": 14, "name": "Bob phone", "created_at": "2026-11-11T07:15:59Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aaguid": "000…
```
`attestationObject` 를 풀어 보면:

| 칸 | 값 | 뜻 |
|---|---|---|
| `fmt` | `none` | attestation 을 `none` 으로 요청 → 제조사 증명서 없음 |
| `attStmt` | `{}` | 비어 있음 |
| `authData.rpIdHash` | `49960de5880e8c68…` | SHA-256("localhost") — 이 사이트용 키 |
| `authData.flags` | `0x5d` | UP·UV·AT·BE·BS |
| `authData.credentialId` | `AiA3FcT6k1eQ07XsdOJE…` | 자격 증명 ID |
| `credentialPublicKey` | kty=2(EC2), alg=-7(ES256), crv=1(P-256), x=`2b84c74ce1793ef7…`, y=`97f33360ae6f3475…` | **공개키**(곡선 위의 점 x, y) |
| `clientDataJSON` | `{"type": "webauthn.create", "challenge": "fFOccwXsrwiMSQmWV9juR8l4ZS32_Dlem6HyPNSxN4s", "o…` | 종류·챌린지·주소 |

개인키(인증기 안의 비밀 숫자 d)를 16진수로 바꾼 값 `209775…` 이 요청 본문에 들어 있는지: **✅ 없음**. ES256 의 개인키는 숫자 하나(d)이고, 공개키(x, y)는 d×G 로 계산한 점이라 공개키에서 d 를 되돌려 구할 수 없습니다.


### ✅ 서버에 저장된 값 — 공개키이며 비밀번호가 아님 (C21, C22, C24)

```json
{
 "id": 14,
 "username": "bob_80b441",
 "name": "Bob phone",
 "credential_id": "AiA3FcT6k1eQ07XsdOJE…",
 "public_key": "pQECAyYgASFYICuEx0zheT739L3BGKWTahs3I3FW…(103자)",
 "alg": -7,
 "sign_count": 0,
 "aaguid": "00000000-0000-0000-0000-000000000000",
 "backup_eligible": 1,
 "transports": "internal,hybrid",
 "fmt": "none",
 "created_at": "2026-11-11T07:15:59Z"
}
```
`public_key` 를 풀면 `ES256 P-256 x=2b84c74ce1793ef7… y=97f33360ae6f3475…` — 인증기가 만든 공개키와 같은 점: **✅ 같음**. 이 값은 남에게 보여도 되는 공개 정보라서 DB 가 새어도 이것으로 로그인할 수 없습니다(로그인하려면 이 공개키에 맞는 서명을 만들어야 하고, 그건 개인키가 있는 인증기만 할 수 있음). 비밀번호처럼 사람이 외우거나 입력하는 값도, 해시해 숨겨야 하는 값도 아닙니다. 이름 `name` 은 사람이 붙인 이름입니다.

`me_accounts`·`me_credentials` 표의 열: `aaguid`, `account_id`, `alg`, `backed_up`, `backup_eligible`, `created_at`, `credential_id`, `fmt`, `id`, `last_used_at`, `name`, `public_key`, `sign_count`, `transports`, `user_handle`, `username` — 비밀번호 열이 없습니다.


### ✅ 등록 중간에 취소 (C25)

사용자가 패스키 창을 닫으면 브라우저가 `NotAllowedError` 를 내고, 화면은 "등록 창이 닫혀 취소되었습니다… 서버에는 아무것도 저장되지 않았습니다." 를 보여 준 뒤 보관 중인 챌린지 삭제를 요청합니다.

```
POST /api/me/register/options
Cookie: (none)
X-PDS: 1
{"username": "cancel_80b441", "passkey_name": "x"}
→ 200
{"publicKey": {"challenge": "6WJDJ_qUif2-SrFCi7TalvOPkWbZ…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "234PCoI_44eCAPt15w-nnQ", "name": "cancel_80b441", "displayName": "cancel_80…
```
```
POST /api/me/cancel
Cookie: (none)
X-PDS: 1
{"challenge": "6WJDJ_qUif2-SrFCi7TalvOP…(43자)"}
→ 200
{"ok": true}
```
취소 전 계정·패스키 수 `{'a': 10, 'c': 10}` → 취소 후 `{'a': 10, 'c': 10}`, 그 챌린지 줄 수: `0`


## 3. 패스키 로그인 (C27–C35)


### ✅ 로그인 요청마다 챌린지가 다름 (C27, C28)

1. `6ZcKwC8RhyBg1e1K1TDqBUqu9nSytN-0f2uLidZdaYk`
2. `ewOTfgaBmUlGpfSve27aqQBKgKMr_acaazoh-njc6k0`
3. `cKslFe9_oQam1fU3wRJrQl57LIAtAWxNfqe43jn0Dkw`


### ✅ 서명 확인 성공 / 실패 (C29, C30)

오른쪽은 서명 마지막 바이트 한 개만 바꾼 요청입니다. 서버는 `me_credentials.public_key` 로 `authenticatorData ‖ SHA-256(clientDataJSON)` 에 대한 서명을 계산해 보고(`passkey.verify_assertion`), 맞지 않으면 401.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "rawId": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIHH7nXdg02D-gVJQI_Oq…(94자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 200<br>Set-Cookie: me_session=d0i6W…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_80b441"}, "passkey": "Alice laptop"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "rawId": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIAovgArmwdiQ_i_IeEMX…(94자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 401<br>{"error": "Signature check failed"}</pre> |

### ✅ 이미 쓴 챌린지 다시 보내기 (C31)

왼쪽과 **완전히 같은 본문**(같은 챌린지·같은 올바른 서명)을 한 번 더 보냈습니다. 서명은 맞지만 챌린지를 이미 썼으므로 거절됩니다. 챌린지는 검사 전에 `used_at` 을 먼저 저장하므로, 실패한 시도의 챌린지도 다시 쓸 수 없습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "rawId": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIHH7nXdg02D-gVJQI_Oq…(94자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 200<br>Set-Cookie: me_session=d0i6W…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_80b441"}, "passkey": "Alice laptop"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "rawId": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIHH7nXdg02D-gVJQI_Oq…(94자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 401<br>{"error": "This challenge was already used"}</pre> |

### ✅ 로그인 뒤 사용자 식별 방식 (C32, C34)

**서버 세션**입니다. 로그인에 성공하면 `secrets.token_urlsafe(32)` 무작위 값을 `me_session` 쿠키(`HttpOnly; SameSite=Strict; Path=/; Max-Age=43200`, https 에서는 `Secure`)로 주고, 서버 DB `me_sessions` 에는 그 값의 SHA-256 만 저장합니다. 이후 요청에서 쿠키 → 해시 → `me_sessions` → 계정 순으로 찾습니다. 주소·본문의 계정 이름은 읽지 않습니다. 기록의 쿠키 값은 앞 5글자 뒤를 가렸습니다.


**로그아웃 요청**

```
POST /api/me/logout
Cookie: me_session=d0i6W…(masked)
X-PDS: 1
→ 200
Set-Cookie: me_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0
{"ok": true}
```

### ✅ 로그아웃 전 / 후 — 같은 쿠키 값으로 요청 (C33)

로그아웃 때 서버가 `me_sessions` 에서 그 줄을 지우므로, 브라우저가 쿠키를 지우지 않고 그대로 다시 보내도 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=d0i6W…(masked)<br>→ 200<br>{"items": ["#37 준비 중인 프로젝트 메모 (가상)", "#38 지원하려는 곳 목록 (가상)", "#39 11월 개인 회고 (가상)"]}</pre> | <pre>GET /api/me/items<br>Cookie: me_session=d0i6W…(masked)<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

## 4. 패스키 두 개 · 하나 삭제 (C42–C46)


### ✅ 두 번째 패스키 등록

로그인한 채로 같은 `register/options` 를 부르면 그 계정에 패스키를 추가합니다. `excludeCredentials` 에 첫 패스키 ID 1개가 들어가 같은 인증기에 두 번 만들지 않게 합니다.

```
POST /api/me/register/options
Cookie: me_session=WEazU…(masked)
X-PDS: 1
{"passkey_name": "Alice phone"}
→ 200
{"publicKey": {"challenge": "riXUn5x9ShcL6A2jNlu5n4OB3UC2…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "K_0NrbKWhxmVeqJBa1lx4A", "name": "alice_80b441", "displayName": "alice_80b4…
```
```
POST /api/me/register/verify
Cookie: me_session=WEazU…(masked)
X-PDS: 1
{"credential": {"id": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "rawId": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(183자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
{"ok": true, "account": {"username": "alice_80b441"}, "passkey": {"id": 15, "name": "Alice phone", "created_at": "2026-11-11T07:15:59Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aaguid": …
```

### ✅ 한 계정에 패스키 두 개 (C42, C43)

| 이름 | 등록한 날(UTC) | 저장된 곳(추정) | 공개키 |
|---|---|---|---|
| Alice laptop | 2026-11-11T07:15:59Z | 비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨 | ES256 x=6a212411c408… |
| Alice phone | 2026-11-11T07:15:59Z | 비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨 | ES256 x=fedb27b7602a… |

**첫 번째 패스키(Alice laptop) 삭제**

```
DELETE /api/me/passkeys/13
Cookie: me_session=WEazU…(masked)
X-PDS: 1
→ 200
{"ok": true, "left": 1}
```

### ✅ 하나 지운 뒤 — 남은 패스키 / 지운 패스키로 로그인 (C44, C45)

지운 패스키는 인증기(기기) 쪽에는 남아 있어 서명은 만들 수 있지만, 서버에 그 공개키가 없으므로 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "rawId": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEYCIQDmjBCrj6VrHphI7Ryr…(96자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 200<br>Set-Cookie: me_session=e-B3Z…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_80b441"}, "passkey": "Alice phone"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "rawId": "ajbEM5tz9bKIDEMYpNeIL5HT…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIDMyry_jHZoGy67UCOw_…(94자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 401<br>{"error": "This passkey is not registered (it may have been deleted)"}</pre> |

### ✅ 마지막 남은 패스키 삭제 시도 (C46)

패스키가 하나만 남으면 서버가 삭제를 막습니다(409). 화면에는 패스키가 1개일 때 늘 경고가 보입니다. 비밀번호·이메일 복구가 없으므로, 남은 하나마저 잃으면 그 계정에는 다시 들어올 수 없습니다(PASSKEY.md ⑥).

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=e-B3Z…(masked)<br>→ 200<br>{"passkeys": ["#15 Alice phone (2026-11-11)"]}</pre> | <pre>DELETE /api/me/passkeys/15<br>Cookie: me_session=e-B3Z…(masked)<br>X-PDS: 1<br>→ 409<br>{"error": "This is your last passkey. Add another passkey first, or you could never log in again."}</pre> |

## 5. 다른 계정의 자료·패스키 (C36–C41)


### ✅ 계정 두 개, 서로 다른 비공개 내용 (C36)


**alice_80b441**

```
GET /api/me/items
Cookie: me_session=e-B3Z…(masked)
→ 200
{"items": ["#37 준비 중인 프로젝트 메모 (가상)", "#38 지원하려는 곳 목록 (가상)", "#39 11월 개인 회고 (가상)", "#43 Alice만 아는 메모 (80b441)"]}
```

**bob_80b441**

```
GET /api/me/items
Cookie: me_session=-2C78…(masked)
→ 200
{"items": ["#40 준비 중인 프로젝트 메모 (가상)", "#41 지원하려는 곳 목록 (가상)", "#42 11월 개인 회고 (가상)", "#44 Bob의 지원 목록 (80b441)"]}
```

### ✅ A(alice_80b441) 가 자기 자료 / B 의 자료 #44 요청 (C37)

남의 자료는 '없음'과 똑같이 404 로 답해, 번호를 바꿔 보며 남의 자료가 있는지 알아낼 수 없게 했습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items/43<br>Cookie: me_session=e-B3Z…(masked)<br>→ 200<br>{"id": 43, "category": "memo", "category_label": "메모", "title": "Alice만 아는 메모 (80b441)", "body": "가상의 내용", "created_at": "2026-11-11T07:15:59Z"}</pre> | <pre>GET /api/me/items/44<br>Cookie: me_session=e-B3Z…(masked)<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ A 가 B 의 자료 #44 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=e-B3Z…(masked)<br>→ 200<br>{"items": ["#37 준비 중인 프로젝트 메모 (가상)", "#38 지원하려는 곳 목록 (가상)", "#39 11월 개인 회고 (가상)", "#43 Alice만 아는 메모 (80b441)"]}</pre> | <pre>DELETE /api/me/items/44<br>Cookie: me_session=e-B3Z…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 반대 방향: B(bob_80b441) 가 자기 자료 / A 의 자료 #43 요청 (C38)

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items/44<br>Cookie: me_session=-2C78…(masked)<br>→ 200<br>{"id": 44, "category": "apply", "category_label": "지원하려는 곳", "title": "Bob의 지원 목록 (80b441)", "body": "가상 회사 C", "created_at": "2026-11-11T07:15:59Z"}</pre> | <pre>GET /api/me/items/43<br>Cookie: me_session=-2C78…(masked)<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 반대 방향: B 가 A 의 자료 #43 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=-2C78…(masked)<br>→ 200<br>{"items": ["#40 준비 중인 프로젝트 메모 (가상)", "#41 지원하려는 곳 목록 (가상)", "#42 11월 개인 회고 (가상)", "#44 Bob의 지원 목록 (80b441)"]}</pre> | <pre>DELETE /api/me/items/43<br>Cookie: me_session=-2C78…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 거절 앞뒤 자료 건수 (C39)

B 의 자료: 거절 전 **4건** → 거절 후 **4건** · A 의 자료: 거절 전 **4건** → 거절 후 **4건**


### ✅ 주소에 다른 계정을 적어 보내도 내 자료만 (C40)

```
GET /api/me/items?account=bob_80b441&account_id=2&username=bob_80b441
Cookie: me_session=e-B3Z…(masked)
→ 200
{"items": ["#37 준비 중인 프로젝트 메모 (가상)", "#38 지원하려는 곳 목록 (가상)", "#39 11월 개인 회고 (가상)", "#43 Alice만 아는 메모 (80b441)"]}
```

**본문에 B 의 계정을 적어 자료 추가**

```
POST /api/me/items
Cookie: me_session=e-B3Z…(masked)
X-PDS: 1
{"category": "memo", "title": "몰래 넣기 (80b441)", "account_id": 2, "username": "bob_80b441"}
→ 201
{"id": 45, "category": "memo", "category_label": "메모", "title": "몰래 넣기 (80b441)", "body": "", "created_at": "2026-11-11T07:16:00Z"}
```
B 의 자료 목록에 `몰래 넣기` 가 생겼는지: **✅ 아니오** — 본문의 `account_id`·`username` 은 읽지 않고 세션의 계정(A)으로 저장됩니다.


### ✅ A 가 B 의 패스키 #14 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=e-B3Z…(masked)<br>→ 200<br>{"passkeys": ["#15 Alice phone (2026-11-11)"]}</pre> | <pre>DELETE /api/me/passkeys/14<br>Cookie: me_session=e-B3Z…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ A 의 아이디로 로그인 — A 의 패스키 / B 의 패스키

아이디를 적고 로그인하면 서버가 챌린지에 그 계정을 묶어 두고, 다른 계정의 패스키로 만든 서명은 서명이 맞아도 거절합니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "rawId": "f2AePrGcCkPENbzlF5sbMnzS…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIGNd1HOt-gEzsliL7Ufc…(95자)", "userHandle": "K_0NrbKWhxmVeqJBa1lx4A"}}}<br>→ 200<br>Set-Cookie: me_session=E9lQp…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_80b441"}, "passkey": "Alice phone"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "AiA3FcT6k1eQ07XsdOJECvuv…(43자)", "rawId": "AiA3FcT6k1eQ07XsdOJECvuv…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEYCIQDy4kqwqiy35x3m3hX5…(96자)", "userHandle": "5ZaXCZhAijGsgUeRO87jmg"}}}<br>→ 403<br>{"error": "This passkey belongs to a different account"}</pre> |

### 거절을 만드는 소스 위치 (C41)

- `intro.py` `route()` — `/api/me/` 아래에서 세션이 없으면 `401 Log in with a passkey…`
- `intro.py` `get_item()` · `delete_item()` · `list_items()` — SQL `WHERE … AND account_id = ?` (세션의 계정만)
- `intro.py` `delete_passkey()` — `WHERE id = ? AND account_id = ?`, 마지막 하나면 409
- `intro.py` `login_verify()` — 챌린지에 묶인 계정과 패스키 주인이 다르면 403
- `intro.py` `consume_challenge()` — 모르는·이미 쓴·만료된 챌린지 거절
- `passkey.py` `verify_assertion()` — origin·rpIdHash·UP/UV 플래그·서명·signCount 검사


---

**결과: 모두 통과**

