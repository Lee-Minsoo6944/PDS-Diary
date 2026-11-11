# 패스키 인증 확인 기록 (과제 8)

서버: `http://localhost:8017` · 시험 계정 `alice_341ca9`, `bob_341ca9` (이 기록을 만들 때마다 새로 만듦). 인증기는 `tools/soft_authenticator.py`(P-256 키 쌍을 만들고 개인키를 자기 안에만 두는 시험용 프로그램)가 맡았습니다. 세션 쿠키는 앞 5글자 뒤를 가렸고, 긴 base64 값은 앞부분과 길이만 적었습니다.

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
| <pre>GET /api/me/items<br>Cookie: me_session=5T7eM…(masked)<br>→ 200<br>{"items": ["#13 준비 중인 프로젝트 메모 (가상)", "#14 지원하려는 곳 목록 (가상)", "#15 11월 개인 회고 (가상)"]}</pre> | <pre>GET /api/me/items<br>Cookie: (none)<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

### ✅ 패스키 목록 요청 — 세션 있음 / 지어낸 쿠키 (C16)

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=5T7eM…(masked)<br>→ 200<br>{"passkeys": ["#5 Alice laptop (2026-11-11)"]}</pre> | <pre>GET /api/me/passkeys<br>Cookie: me_session=made-up-cookie-value<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

## 2. 패스키 등록 (C19–C26)


### ✅ 등록 요청마다 챌린지가 다름 (C20)

같은 요청을 세 번 보냈을 때 서버가 준 `challenge`(32바이트 무작위 값, base64url):

1. `Uhpqnlhkak0ydsA_VIXncTbswce7SPeVfjJZRgchDuw`
2. `Tt3yti6i28EWa-GA1NWQnwd3GqeOqEcKPkFPlNqIVBU`
3. `M5TA_soWMoGUmPcH4XBNsXbtCiFecQDF1BbZs9NgJfo`


### ✅ 등록 1단계 — 서버가 챌린지를 만들어 보내고 보관 (C19)

```
POST /api/me/register/options
Cookie: (none)
X-PDS: 1
{"passkey_name": "Bob phone", "username": "bob_341ca9"}
→ 200
{"publicKey": {"challenge": "bwAF3_bmbRdmfGFQtKf8qq0TWHxE…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "4FHJjjSbAS88IL4aypeDiA", "name": "bob_341ca9", "displayName": "bob_341ca9"}…
```
서버 DB `me_challenges` 의 그 줄(검증이 끝난 뒤라 `used_at` 이 채워져 있음. 5분 뒤 만료):

```json
[
 {
  "challenge": "bwAF3_bmbRdmfGFQtKf8qq0TWHxE2Ku4xrTP3HRke4Q",
  "purpose": "register",
  "username": "bob_341ca9",
  "created_at": "2026-11-11T07:26:16Z",
  "expires_at": "2026-11-11T07:31:16Z",
  "used_at": "2026-11-11T07:26:16Z"
 }
]
```

### ✅ 등록 2단계 — 브라우저가 보낸 요청 본문에 개인키가 없음 (C23)

아래가 `POST /api/me/register/verify` 본문 전체입니다(긴 값만 줄임). 들어 있는 것은 자격 증명 ID, `clientDataJSON`, `attestationObject`, 전송 방식뿐입니다.

```
POST /api/me/register/verify
Cookie: (none)
X-PDS: 1
{"credential": {"id": "zU9kMnWRhxwYxh1Kh8Hf3MqX…(43자)", "rawId": "zU9kMnWRhxwYxh1Kh8Hf3MqX…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(183자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
Set-Cookie: me_session=fNdMw…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200
{"ok": true, "account": {"username": "bob_341ca9"}, "passkey": {"id": 6, "name": "Bob phone", "created_at": "2026-11-11T07:26:16Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aaguid": "0000…
```
`attestationObject` 를 풀어 보면:

| 칸 | 값 | 뜻 |
|---|---|---|
| `fmt` | `none` | attestation 을 `none` 으로 요청 → 제조사 증명서 없음 |
| `attStmt` | `{}` | 비어 있음 |
| `authData.rpIdHash` | `49960de5880e8c68…` | SHA-256("localhost") — 이 사이트용 키 |
| `authData.flags` | `0x5d` | UP·UV·AT·BE·BS |
| `authData.credentialId` | `zU9kMnWRhxwYxh1Kh8Hf…` | 자격 증명 ID |
| `credentialPublicKey` | kty=2(EC2), alg=-7(ES256), crv=1(P-256), x=`430ff5774dd80361…`, y=`ef04c416f9896829…` | **공개키**(곡선 위의 점 x, y) |
| `clientDataJSON` | `{"type": "webauthn.create", "challenge": "bwAF3_bmbRdmfGFQtKf8qq0TWHxE2Ku4xrTP3HRke4Q", "o…` | 종류·챌린지·주소 |

개인키(인증기 안의 비밀 숫자 d)를 16진수로 바꾼 값 `634ede…` 이 요청 본문에 들어 있는지: **✅ 없음**. ES256 의 개인키는 숫자 하나(d)이고, 공개키(x, y)는 d×G 로 계산한 점이라 공개키에서 d 를 되돌려 구할 수 없습니다.


### ✅ 서버에 저장된 값 — 공개키이며 비밀번호가 아님 (C21, C22, C24)

```json
{
 "id": 6,
 "username": "bob_341ca9",
 "name": "Bob phone",
 "credential_id": "zU9kMnWRhxwYxh1Kh8Hf…",
 "public_key": "pQECAyYgASFYIEMP9XdN2ANhZiYF6hh13LDRPlMO…(103자)",
 "alg": -7,
 "sign_count": 0,
 "aaguid": "00000000-0000-0000-0000-000000000000",
 "backup_eligible": 1,
 "transports": "internal,hybrid",
 "fmt": "none",
 "created_at": "2026-11-11T07:26:16Z"
}
```
`public_key` 를 풀면 `ES256 P-256 x=430ff5774dd80361… y=ef04c416f9896829…` — 인증기가 만든 공개키와 같은 점: **✅ 같음**. 이 값은 남에게 보여도 되는 공개 정보라서 DB 가 새어도 이것으로 로그인할 수 없습니다(로그인하려면 이 공개키에 맞는 서명을 만들어야 하고, 그건 개인키가 있는 인증기만 할 수 있음). 비밀번호처럼 사람이 외우거나 입력하는 값도, 해시해 숨겨야 하는 값도 아닙니다. 이름 `name` 은 사람이 붙인 이름입니다.

`me_accounts`·`me_credentials` 표의 열: `aaguid`, `account_id`, `alg`, `backed_up`, `backup_eligible`, `created_at`, `credential_id`, `fmt`, `id`, `last_used_at`, `name`, `public_key`, `sign_count`, `transports`, `user_handle`, `username` — 비밀번호 열이 없습니다.


### ✅ 등록 중간에 취소 (C25)

사용자가 패스키 창을 닫으면 브라우저가 `NotAllowedError` 를 내고, 화면은 "등록 창이 닫혀 취소되었습니다… 서버에는 아무것도 저장되지 않았습니다." 를 보여 준 뒤 보관 중인 챌린지 삭제를 요청합니다.

```
POST /api/me/register/options
Cookie: (none)
X-PDS: 1
{"username": "cancel_341ca9", "passkey_name": "x"}
→ 200
{"publicKey": {"challenge": "O9r_YWMNe1liz5EXG3LAGFWO0Fvx…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "dzzpuo8t2MXJeD_hYXXv8Q", "name": "cancel_341ca9", "displayName": "cancel_34…
```
```
POST /api/me/cancel
Cookie: (none)
X-PDS: 1
{"challenge": "O9r_YWMNe1liz5EXG3LAGFWO…(43자)"}
→ 200
{"ok": true}
```
취소 전 계정·패스키 수 `{'a': 5, 'c': 5}` → 취소 후 `{'a': 5, 'c': 5}`, 그 챌린지 줄 수: `0`


## 3. 패스키 로그인 (C27–C35)


### ✅ 로그인 요청마다 챌린지가 다름 (C27, C28)

1. `cQ_O8BrDgrMkoiXhzZ87hZGKk-1uqLmB4KYcNRlDKeM`
2. `OePgSIydvh1duSI6KgjA-wPOuUdygdBCyoG6oPIr2nU`
3. `i2N9rtB-LtomQVpgKB7Md4KU5uR7En3fQyC0wS0mDFs`


### ✅ 서명 확인 성공 / 실패 (C29, C30)

오른쪽은 서명 마지막 바이트 한 개만 바꾼 요청입니다. 서버는 `me_credentials.public_key` 로 `authenticatorData ‖ SHA-256(clientDataJSON)` 에 대한 서명을 계산해 보고(`passkey.verify_assertion`), 맞지 않으면 401.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "rawId": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIFaE7d3vm5g16AAXQ5mm…(95자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 200<br>Set-Cookie: me_session=SCJuf…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_341ca9"}, "passkey": "Alice laptop"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "rawId": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIETp-dWBRvE4xNkGwcTe…(95자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 401<br>{"error": "Signature check failed"}</pre> |

### ✅ 이미 쓴 챌린지 다시 보내기 (C31)

왼쪽과 **완전히 같은 본문**(같은 챌린지·같은 올바른 서명)을 한 번 더 보냈습니다. 서명은 맞지만 챌린지를 이미 썼으므로 거절됩니다. 챌린지는 검사 전에 `used_at` 을 먼저 저장하므로, 실패한 시도의 챌린지도 다시 쓸 수 없습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "rawId": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIFaE7d3vm5g16AAXQ5mm…(95자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 200<br>Set-Cookie: me_session=SCJuf…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_341ca9"}, "passkey": "Alice laptop"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "rawId": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIFaE7d3vm5g16AAXQ5mm…(95자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 401<br>{"error": "This challenge was already used"}</pre> |

### ✅ 로그인 뒤 사용자 식별 방식 (C32, C34)

**서버 세션**입니다. 로그인에 성공하면 `secrets.token_urlsafe(32)` 무작위 값을 `me_session` 쿠키(`HttpOnly; SameSite=Strict; Path=/; Max-Age=43200`, https 에서는 `Secure`)로 주고, 서버 DB `me_sessions` 에는 그 값의 SHA-256 만 저장합니다. 이후 요청에서 쿠키 → 해시 → `me_sessions` → 계정 순으로 찾습니다. 주소·본문의 계정 이름은 읽지 않습니다. 기록의 쿠키 값은 앞 5글자 뒤를 가렸습니다.


**로그아웃 요청**

```
POST /api/me/logout
Cookie: me_session=SCJuf…(masked)
X-PDS: 1
→ 200
Set-Cookie: me_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0
{"ok": true}
```

### ✅ 로그아웃 전 / 후 — 같은 쿠키 값으로 요청 (C33)

로그아웃 때 서버가 `me_sessions` 에서 그 줄을 지우므로, 브라우저가 쿠키를 지우지 않고 그대로 다시 보내도 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=SCJuf…(masked)<br>→ 200<br>{"items": ["#13 준비 중인 프로젝트 메모 (가상)", "#14 지원하려는 곳 목록 (가상)", "#15 11월 개인 회고 (가상)"]}</pre> | <pre>GET /api/me/items<br>Cookie: me_session=SCJuf…(masked)<br>→ 401<br>{"error": "Log in with a passkey to see the private area"}</pre> |

## 4. 패스키 두 개 · 하나 삭제 (C42–C46)


### ✅ 두 번째 패스키 등록

로그인한 채로 같은 `register/options` 를 부르면 그 계정에 패스키를 추가합니다. `excludeCredentials` 에 첫 패스키 ID 1개가 들어가 같은 인증기에 두 번 만들지 않게 합니다.

```
POST /api/me/register/options
Cookie: me_session=c1hTi…(masked)
X-PDS: 1
{"passkey_name": "Alice phone"}
→ 200
{"publicKey": {"challenge": "5zVh8adHnwVQ8LoF13OQgwGR_0No…(43자)", "rp": {"id": "localhost", "name": "Lee Minsoo · About me"}, "user": {"id": "2nlK4h0a64v56aMc4av0YA", "name": "alice_341ca9", "displayName": "alice_341c…
```
```
POST /api/me/register/verify
Cookie: me_session=c1hTi…(masked)
X-PDS: 1
{"credential": {"id": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "rawId": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(183자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
{"ok": true, "account": {"username": "alice_341ca9"}, "passkey": {"id": 7, "name": "Alice phone", "created_at": "2026-11-11T07:26:16Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aaguid": "…
```

### ✅ 한 계정에 패스키 두 개 (C42, C43)

| 이름 | 등록한 날(UTC) | 저장된 곳(추정) | 공개키 |
|---|---|---|---|
| Alice laptop | 2026-11-11T07:26:16Z | 비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨 | ES256 x=6f7ccdcf4a82… |
| Alice phone | 2026-11-11T07:26:16Z | 비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨 | ES256 x=7e78fe718dd4… |

**첫 번째 패스키(Alice laptop) 삭제**

```
DELETE /api/me/passkeys/5
Cookie: me_session=c1hTi…(masked)
X-PDS: 1
→ 200
{"ok": true, "left": 1}
```

### ✅ 하나 지운 뒤 — 남은 패스키 / 지운 패스키로 로그인 (C44, C45)

지운 패스키는 인증기(기기) 쪽에는 남아 있어 서명은 만들 수 있지만, 서버에 그 공개키가 없으므로 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "rawId": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEYCIQCcABq1FK3WWGn8NWcI…(96자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 200<br>Set-Cookie: me_session=H1Zsv…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_341ca9"}, "passkey": "Alice phone"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "rawId": "zluxVD0cLpIdTU_LDAPok24g…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEQCIGmmeiuMkVqb1sE3RDLo…(94자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 401<br>{"error": "This passkey is not registered (it may have been deleted)"}</pre> |

### ✅ 마지막 남은 패스키 삭제 시도 (C46)

패스키가 하나만 남으면 서버가 삭제를 막습니다(409). 화면에는 패스키가 1개일 때 늘 경고가 보입니다. 비밀번호·이메일 복구가 없으므로, 남은 하나마저 잃으면 그 계정에는 다시 들어올 수 없습니다(PASSKEY.md ⑥).

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=H1Zsv…(masked)<br>→ 200<br>{"passkeys": ["#7 Alice phone (2026-11-11)"]}</pre> | <pre>DELETE /api/me/passkeys/7<br>Cookie: me_session=H1Zsv…(masked)<br>X-PDS: 1<br>→ 409<br>{"error": "This is your last passkey. Add another passkey first, or you could never log in again."}</pre> |

## 5. 다른 계정의 자료·패스키 (C36–C41)


### ✅ 계정 두 개, 서로 다른 비공개 내용 (C36)


**alice_341ca9**

```
GET /api/me/items
Cookie: me_session=H1Zsv…(masked)
→ 200
{"items": ["#13 준비 중인 프로젝트 메모 (가상)", "#14 지원하려는 곳 목록 (가상)", "#15 11월 개인 회고 (가상)", "#19 Alice만 아는 메모 (341ca9)"]}
```

**bob_341ca9**

```
GET /api/me/items
Cookie: me_session=2NrEs…(masked)
→ 200
{"items": ["#16 준비 중인 프로젝트 메모 (가상)", "#17 지원하려는 곳 목록 (가상)", "#18 11월 개인 회고 (가상)", "#20 Bob의 지원 목록 (341ca9)"]}
```

### ✅ A(alice_341ca9) 가 자기 자료 / B 의 자료 #20 요청 (C37)

남의 자료는 '없음'과 똑같이 404 로 답해, 번호를 바꿔 보며 남의 자료가 있는지 알아낼 수 없게 했습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items/19<br>Cookie: me_session=H1Zsv…(masked)<br>→ 200<br>{"id": 19, "category": "memo", "category_label": "메모", "title": "Alice만 아는 메모 (341ca9)", "body": "가상의 내용", "created_at": "2026-11-11T07:26:16Z"}</pre> | <pre>GET /api/me/items/20<br>Cookie: me_session=H1Zsv…(masked)<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ A 가 B 의 자료 #20 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=H1Zsv…(masked)<br>→ 200<br>{"items": ["#13 준비 중인 프로젝트 메모 (가상)", "#14 지원하려는 곳 목록 (가상)", "#15 11월 개인 회고 (가상)", "#19 Alice만 아는 메모 (341ca9)"]}</pre> | <pre>DELETE /api/me/items/20<br>Cookie: me_session=H1Zsv…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 반대 방향: B(bob_341ca9) 가 자기 자료 / A 의 자료 #19 요청 (C38)

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items/20<br>Cookie: me_session=2NrEs…(masked)<br>→ 200<br>{"id": 20, "category": "apply", "category_label": "지원하려는 곳", "title": "Bob의 지원 목록 (341ca9)", "body": "가상 회사 C", "created_at": "2026-11-11T07:26:16Z"}</pre> | <pre>GET /api/me/items/19<br>Cookie: me_session=2NrEs…(masked)<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 반대 방향: B 가 A 의 자료 #19 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: me_session=2NrEs…(masked)<br>→ 200<br>{"items": ["#16 준비 중인 프로젝트 메모 (가상)", "#17 지원하려는 곳 목록 (가상)", "#18 11월 개인 회고 (가상)", "#20 Bob의 지원 목록 (341ca9)"]}</pre> | <pre>DELETE /api/me/items/19<br>Cookie: me_session=2NrEs…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ 거절 앞뒤 자료 건수 (C39)

B 의 자료: 거절 전 **4건** → 거절 후 **4건** · A 의 자료: 거절 전 **4건** → 거절 후 **4건**


### ✅ 주소에 다른 계정을 적어 보내도 내 자료만 (C40)

```
GET /api/me/items?account=bob_341ca9&account_id=2&username=bob_341ca9
Cookie: me_session=H1Zsv…(masked)
→ 200
{"items": ["#13 준비 중인 프로젝트 메모 (가상)", "#14 지원하려는 곳 목록 (가상)", "#15 11월 개인 회고 (가상)", "#19 Alice만 아는 메모 (341ca9)"]}
```

**본문에 B 의 계정을 적어 자료 추가**

```
POST /api/me/items
Cookie: me_session=H1Zsv…(masked)
X-PDS: 1
{"category": "memo", "title": "몰래 넣기 (341ca9)", "account_id": 2, "username": "bob_341ca9"}
→ 201
{"id": 21, "category": "memo", "category_label": "메모", "title": "몰래 넣기 (341ca9)", "body": "", "created_at": "2026-11-11T07:26:16Z"}
```
B 의 자료 목록에 `몰래 넣기` 가 생겼는지: **✅ 아니오** — 본문의 `account_id`·`username` 은 읽지 않고 세션의 계정(A)으로 저장됩니다.


### ✅ A 가 B 의 패스키 #6 삭제 시도

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/passkeys<br>Cookie: me_session=H1Zsv…(masked)<br>→ 200<br>{"passkeys": ["#7 Alice phone (2026-11-11)"]}</pre> | <pre>DELETE /api/me/passkeys/6<br>Cookie: me_session=H1Zsv…(masked)<br>X-PDS: 1<br>→ 404<br>{"error": "Not found"}</pre> |

### ✅ A 의 아이디로 로그인 — A 의 패스키 / B 의 패스키

아이디를 적고 로그인하면 서버가 챌린지에 그 계정을 묶어 두고, 다른 계정의 패스키로 만든 서명은 서명이 맞아도 거절합니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "rawId": "p6D94bSm-1g183C2HSJ3bwyx…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEYCIQCs9Wzzh5RwTwyM3U23…(96자)", "userHandle": "2nlK4h0a64v56aMc4av0YA"}}}<br>→ 200<br>Set-Cookie: me_session=iHSYE…(masked); Path=/; HttpOnly; SameSite=Strict; Max-Age=43200<br>{"ok": true, "account": {"username": "alice_341ca9"}, "passkey": "Alice phone"}</pre> | <pre>POST /api/me/login/verify<br>Cookie: (none)<br>X-PDS: 1<br>{"credential": {"id": "zU9kMnWRhxwYxh1Kh8Hf3MqX…(43자)", "rawId": "zU9kMnWRhxwYxh1Kh8Hf3MqX…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(179자)", "authenticatorData": "SZYN5YgOjGh0NBcPZHZgW4_k…(50자)", "signature": "MEUCIQCwArtrSsJtC5pmAzW6…(95자)", "userHandle": "4FHJjjSbAS88IL4aypeDiA"}}}<br>→ 403<br>{"error": "This passkey belongs to a different account"}</pre> |

## 6. 결과물 주소(GitHub Pages)에서 부르기

결과물 https://lee-minsoo6944.github.io/About-me/ 의 화면은 이 서버와 주소가 달라서, 브라우저가 `Origin` 머리글을 붙여 보냅니다. 서버는 이 주소에만 CORS 를 열고, rpId 를 `lee-minsoo6944.github.io` 로 정하며, 쿠키 대신 **응답 본문의 세션 토큰**을 줍니다(화면은 탭을 닫으면 지워지는 sessionStorage 에 두고 `Authorization: Bearer` 로 보냄). 토큰 값은 앞 5글자 뒤를 가렸습니다.


### ✅ 사전 요청(preflight) — 결과물 주소 / 다른 사이트

다른 사이트에는 허락 머리글이 없어서, 그 사이트의 자바스크립트는 이 API 의 응답을 읽을 수 없습니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>OPTIONS /api/me/login/options<br>Cookie: (none)<br>Origin: https://lee-minsoo6944.github.io<br>Access-Control-Request-Method: POST<br>→ 204<br>Access-Control-Allow-Origin: https://lee-minsoo6944.github.io<br>""</pre> | <pre>OPTIONS /api/me/login/options<br>Cookie: (none)<br>Origin: https://evil.example<br>Access-Control-Request-Method: POST<br>→ 401<br>Access-Control-Allow-Origin: (없음 → 브라우저가 응답을 화면에 넘기지 않음)<br>{"error": "Log in with a passkey to see the private area"}</pre> |

### ✅ 결과물 주소에서 등록 — rpId 가 github.io, 쿠키 없이 토큰

```
POST /api/me/register/options
Cookie: (none)
X-PDS: 1
Origin: https://lee-minsoo6944.github.io
{"username": "gh_341ca9", "passkey_name": "GitHub Pages laptop"}
→ 200
Access-Control-Allow-Origin: https://lee-minsoo6944.github.io
{"publicKey": {"challenge": "Wckw-L4jykVGml-1LjRodoAV8mOr…(43자)", "rp": {"id": "lee-minsoo6944.github.io", "name": "Lee Minsoo · About me"}, "user": {"id": "v7JrCvch0SHrRfZ7TrXLeA", "name": "gh_341ca9", "displayName":…
```
```
POST /api/me/register/verify
Cookie: (none)
X-PDS: 1
Origin: https://lee-minsoo6944.github.io
{"credential": {"id": "aQCn3HHcv_ojBpawmRVg5z2r…(43자)", "rawId": "aQCn3HHcv_ojBpawmRVg5z2r…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(198자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 200
Access-Control-Allow-Origin: https://lee-minsoo6944.github.io
{"ok": true, "account": {"username": "gh_341ca9"}, "passkey": {"id": 8, "name": "GitHub Pages laptop", "created_at": "2026-11-11T07:26:16Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aagui…
```

### ✅ 토큰 있음 / 없음으로 비공개 자료 요청

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>GET /api/me/items<br>Cookie: (none)<br>Origin: https://lee-minsoo6944.github.io<br>Authorization: Bearer FMz1w…(masked)<br>→ 200<br>Access-Control-Allow-Origin: https://lee-minsoo6944.github.io<br>{"items": ["#22 준비 중인 프로젝트 메모 (가상)", "#23 지원하려는 곳 목록 (가상)", "#24 11월 개인 회고 (가상)"]}</pre> | <pre>GET /api/me/items<br>Cookie: (none)<br>Origin: https://lee-minsoo6944.github.io<br>→ 401<br>Access-Control-Allow-Origin: https://lee-minsoo6944.github.io<br>{"error": "Log in with a passkey to see the private area"}</pre> |

### ✅ 로그아웃 전 / 후 — 같은 토큰

왼쪽은 토큰을 받은 등록 응답, 오른쪽은 `POST /api/me/logout` 뒤에 같은 토큰을 다시 보낸 요청입니다. 서버에서 세션 줄을 지웠으므로 거절됩니다.

| 통과한 요청 | 거절된 요청 |
|---|---|
| <pre>POST /api/me/register/verify<br>Cookie: (none)<br>X-PDS: 1<br>Origin: https://lee-minsoo6944.github.io<br>{"credential": {"id": "aQCn3HHcv_ojBpawmRVg5z2r…(43자)", "rawId": "aQCn3HHcv_ojBpawmRVg5z2r…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(198자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}<br>→ 200<br>Access-Control-Allow-Origin: https://lee-minsoo6944.github.io<br>{"ok": true, "account": {"username": "gh_341ca9"}, "passkey": {"id": 8, "name": "GitHub Pages laptop", "created_at": "2026-11-11T07:26:16Z", "last_used_at": null, "storage": "비밀번호 관리자(종류 알 수 없음) · 여러 기기에 동기화됨", "aagui…</pre> | <pre>GET /api/me/items<br>Cookie: (none)<br>Origin: https://lee-minsoo6944.github.io<br>Authorization: Bearer FMz1w…(masked)<br>→ 401<br>Access-Control-Allow-Origin: https://lee-minsoo6944.github.io<br>{"error": "Log in with a passkey to see the private area"}</pre> |

### ✅ 다른 주소에서 만든 등록 응답을 결과물 주소 요청으로 보내기

인증기가 서명한 `clientDataJSON.origin` 은 화면의 진짜 주소라, 요청 머리글만 바꿔서는 통과할 수 없습니다.

```
POST /api/me/register/verify
Cookie: (none)
X-PDS: 1
Origin: https://lee-minsoo6944.github.io
{"credential": {"id": "fpQ0-5Ck_gd5LKrs_FhADBpr…(43자)", "rawId": "fpQ0-5Ck_gd5LKrs_FhADBpr…(43자)", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4u…(183자)", "attestationObject": "o2NmbXRkbm9uZWdhdHRTdG10…(259자)", "transports": ["internal", "hybrid"]}}}
→ 400
Access-Control-Allow-Origin: https://lee-minsoo6944.github.io
{"error": "clientData.origin does not match this site"}
```

### 거절을 만드는 소스 위치 (C41)

- `intro.py` `route()` — `/api/me/` 아래에서 세션이 없으면 `401 Log in with a passkey…`
- `intro.py` `get_item()` · `delete_item()` · `list_items()` — SQL `WHERE … AND account_id = ?` (세션의 계정만)
- `intro.py` `delete_passkey()` — `WHERE id = ? AND account_id = ?`, 마지막 하나면 409
- `intro.py` `login_verify()` — 챌린지에 묶인 계정과 패스키 주인이 다르면 403
- `intro.py` `consume_challenge()` — 모르는·이미 쓴·만료된 챌린지 거절
- `passkey.py` `verify_assertion()` — origin·rpIdHash·UP/UV 플래그·서명·signCount 검사
- `intro.py` `cors_headers()` · `site()` — 결과물 주소(GitHub Pages)에만 CORS, 그 주소의 rpId·origin 으로 검사


---

**결과: 모두 통과**

