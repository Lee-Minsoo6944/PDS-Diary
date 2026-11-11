# 패스키 인증 설명서 — 자기소개 페이지의 비공개 영역 (과제 8)

과제 1의 자기소개 페이지([About-me](https://github.com/Lee-Minsoo6944/About-me))를 이 서버의 `/me/` 로 옮겨 붙이고, 그 아래에 **패스키로만 열리는 비공개 영역**을 새로 만들었습니다. 비밀번호는 쓰지 않습니다.

- **결과물:** https://alstn.pythonanywhere.com/me/ — 첫 화면은 누구나 볼 수 있는 소개 페이지
- **소스:** https://github.com/Lee-Minsoo6944/PDS-Diary — `intro.py`(흐름) · `passkey.py`(서명 검사) · `static/me/`(화면)
- **확인 기록 전체:** [docs/passkey-verification.md](docs/passkey-verification.md) (실제 HTTP 요청·응답, 세션 쿠키는 가림)
- **자동 테스트:** `py -m unittest discover -s tests -v` (58개 중 과제 8 테스트 23개: `tests/test_passkey.py`)

비공개 영역의 자료는 모두 **지어낸 가상의 내용**입니다(가상 회사 이름, 지어낸 메모·회고). 연락처·신분증 번호 같은 실제 개인정보는 넣지 않았습니다.

---

## 짧은 확인 방법

1. **어디로 가나요** — https://alstn.pythonanywhere.com/me/ 를 새 시크릿 창에서 엽니다. 위쪽은 과제 1 소개(공개), 노란 점선 아래가 비공개 영역입니다.
2. **세 단계 안에 무엇을 하나요** — ① 비공개 영역의 "처음이면" 칸에 아이디와 패스키 이름을 적고 **패스키 만들고 가입** → ② 기기의 지문·얼굴·PIN 확인 → ③ 로그아웃한 뒤 **패스키로 들어가기**.
3. **무엇이 보이면 통과인가요** — "🔓 ○○ 님의 비공개 영역" 아래에 가상의 자료 3개와 **내 패스키** 표(이름·등록한 날·저장된 곳·서버에 저장된 공개키)가 보입니다.
4. **안 될 때는 무엇이 보이나요** — 들어가기 전에는 비공개 영역에 안내 문구와 버튼만 있고 자료는 없습니다. 창을 닫으면 "…창이 닫혀 취소되었습니다. 서버에는 아무것도 저장되지 않았습니다.", 지운 패스키로 들어가면 "This passkey is not registered…", 패스키를 지원하지 않는 브라우저면 "이 브라우저는 패스키를 지원하지 않습니다"가 빨간 글씨로 나옵니다. (심사자는 공개 소개 페이지까지만 보면 됩니다. 가입은 필요 없습니다.)

---

## ① 무엇으로 붙였나

**직접 구현**했습니다. 외부 라이브러리·인증 서비스 없이 Python 표준 라이브러리(`hashlib`, `secrets`, `json`, `base64`, `sqlite3`)만 씁니다. 브라우저 쪽은 표준 **WebAuthn API**(`navigator.credentials.create` / `get`)를 그대로 부릅니다.

| 부분 | 쓴 것 | 어디에 |
|---|---|---|
| 등록·로그인 옵션, 챌린지 발급·보관·1회 사용 | 직접 구현, `secrets.token_bytes(32)` 챌린지, SQLite `me_challenges` 표, 5분 만료 | `intro.py` `new_challenge`, `consume_challenge` |
| 등록 응답 해석 | 직접 짠 CBOR 읽기 + authenticatorData·COSE 공개키 해석 | `passkey.py` `cbor_decode`, `parse_auth_data`, `parse_cose_key` |
| 서명 검사 | **ES256**(P-256 ECDSA)·**RS256**(RSA PKCS#1 v1.5) 검증을 직접 계산. RFC 6979 표준 시험값으로 맞는지 확인(`tests/test_passkey.py` `test_p256_rfc6979_vector`) | `passkey.py` `ecdsa_p256_verify`, `rsa_sha256_verify` |
| 로그인 유지 | **서버 세션** — 무작위 값을 `me_session` 쿠키(`HttpOnly; SameSite=Strict`, https 에서 `Secure`, 12시간)로, DB 에는 SHA-256 만 | `intro.py` `start_session`, `session_account` |
| CSRF | 쓰기 요청은 `X-PDS: 1` 머리글 필요(과제 7 규칙 그대로) | `app.py` `application` |
| 저장소 | 기존 SQLite 에 `me_accounts`, `me_credentials`, `me_challenges`, `me_sessions`, `me_items` 표 추가(다이어리 표와 분리) | `intro.py` `SCHEMA` |

attestation 은 `"none"` 으로 요청합니다. 인증기 제조사 증명서는 받지 않고 검사하지도 않습니다.

## ② 왜 그걸 골랐나

- **같은 서버에 `/me/` 로 붙임:** 과제 1 페이지는 GitHub Pages(정적 파일)라 챌린지를 보관하고 서명을 검사할 서버가 없습니다. GitHub Pages 에 두고 API 만 다른 주소에 두면 CORS 와 자바스크립트가 읽을 수 있는 토큰이 필요해집니다. 같은 주소에 두면 **HttpOnly 쿠키 세션**을 그대로 쓸 수 있고, 과제 7 서버의 자동 배포도 그대로 씁니다.
- **직접 구현(표준 라이브러리만):** 이 앱은 과제 6부터 설치 없이 `py app.py` 하나로 돌고 PythonAnywhere 에도 그대로 올라갑니다. 서버가 하는 일은 **공개된 값(공개키·서명·메시지)의 검사뿐**이라 비밀값을 다루지 않고, 그래서 계산 시간이 드러나도 샐 비밀이 없습니다. 대신 표준 시험값(RFC 6979)과 틀린 서명·곡선 밖의 점 거절 테스트로 계산이 맞는지 확인했습니다.
- **서버 세션(토큰 아님):** 로그아웃하면 서버에서 줄을 지워 **그 즉시** 같은 쿠키가 거절됩니다. 서명용 비밀키가 없어 저장소에 숨길 값도 없습니다. `SameSite=Strict` 로 다른 사이트에서 온 요청에는 쿠키가 실리지 않습니다.
- **userVerification `required`:** 비밀번호 없이 패스키 하나로 들어오므로, 기기를 주운 사람이 터치만으로 들어오지 못하게 지문·얼굴·PIN 확인(UV 플래그)을 요구합니다.
- **디스커버러블 패스키(residentKey required):** 아이디를 적지 않아도 기기가 이 사이트용 패스키를 골라 줍니다. 아이디를 적으면 그 계정의 패스키만 허용합니다.
- **마지막 패스키는 못 지우게:** 비밀번호·이메일 복구가 없으므로 마지막 하나를 지우면 영영 못 들어옵니다. 그래서 서버가 막습니다(409).
- **남의 자료는 404:** 403 은 "있긴 하다"를 알려 주므로, 없는 것과 똑같이 답합니다.

## ③ 어디를 어떻게 고쳤나 (흐름별)

줄 번호는 이 커밋 기준입니다. 새 파일: `intro.py`, `passkey.py`, `static/me/*`, `tests/test_passkey.py`, `tools/soft_authenticator.py`, `tools/verify_passkey.py`. 고친 파일: `app.py`(아래 4곳).

**app.py 연결:** `/me/` 정적 파일 등록(55–60행), `/me` → `/me/` 이동(`application`), `intro.SCHEMA` 로 표 만들기(272행), `/api/me/*` 를 `intro.route` 로 넘기기(1073행).

**공개 페이지:** `static/me/index.html` — 과제 1 `index.html` 의 본문을 그대로 두고, 인라인 `<style>`·`<script>` 는 서버의 CSP(인라인 스크립트 금지) 때문에 `about.css`·`about.js` 로 옮겼습니다(내용은 같음). 맨 위에 "🌐 공개 영역" 띠, 맨 아래에 경계선과 `<section id="private">` 를 덧붙였습니다. 이 파일에는 비공개 내용이 없습니다.

### 등록 — `POST /api/me/register/options` → `navigator.credentials.create` → `POST /api/me/register/verify`
1. 화면: `static/me/private.js` `register()` — 아이디·패스키 이름을 보냄.
2. `intro.py` `register_options` (289행): 아이디 확인, 무작위 `user.id`(16바이트), `new_challenge` (204행)로 32바이트 챌린지를 만들어 `me_challenges` 에 보관(5분). 로그인한 채면 그 계정에 추가하고, 기존 패스키를 `excludeCredentials` 에 넣음.
3. 브라우저·인증기: 키 쌍을 만들고 **공개키만** `attestationObject` 에 담아 돌려줌(`registrationJSON`). 사용자가 창을 닫으면 `POST /api/me/cancel` 로 챌린지를 지움(`cancel_challenge`, 235행).
4. `intro.py` `register_verify` (324행): `consume_challenge` (216행)로 챌린지를 '썼음'으로 먼저 저장 → `passkey.py` `verify_registration` (314행)이 type·origin·챌린지·rpIdHash·UP/UV 플래그·자격 증명 ID 를 확인하고 COSE 공개키를 꺼냄 → `me_credentials` 에 공개키·ID·이름 저장, 새 계정이면 예시 자료 3개와 세션 생성.

### 로그인 — `POST /api/me/login/options` → `navigator.credentials.get` → `POST /api/me/login/verify`
1. `intro.py` `login_options` (368행): 매번 새 챌린지. 아이디를 적었으면 챌린지에 그 계정을 묶고 그 계정 패스키만 `allowCredentials` 에.
2. 인증기: 개인키로 `authenticatorData ‖ SHA-256(clientDataJSON)` 에 서명(`assertionJSON`).
3. `intro.py` `login_verify` (388행): `consume_challenge` → 자격 증명 ID 로 `me_credentials` 에서 공개키를 찾음(없으면 401) → 계정이 다르면 403 → `passkey.py` `verify_assertion` (351행)이 origin·rpIdHash·플래그를 보고 **저장된 공개키로 서명 검사**, signCount 가 거꾸로 가면 거절 → 통과하면 `start_session` (195행).

### 로그아웃 — `POST /api/me/logout`
- `intro.py` `logout` (418행): 쿠키 값의 해시로 `me_sessions` 에서 줄을 지우고 `Max-Age=0` 쿠키를 보냄.

### 비공개 자료 조회 — `GET /api/me/items`, `GET/DELETE /api/me/items/<id>`, `POST /api/me/items`
1. `intro.py` `route` (487행): `session_account` (171행)가 쿠키 → 해시 → `me_sessions` → 만료 확인. 없으면 **401**.
2. `list_items` (451행)·`get_item` (457행)·`delete_item` (478행)·`create_item` (464행): 모든 SQL 에 `account_id = <세션의 계정>`. 주소·본문의 `account`, `account_id`, `username` 은 읽지 않음.
3. 패스키 목록·삭제: `list_passkeys` (428행), `delete_passkey` (433행) — 자기 것만, 마지막 하나는 409.
4. 화면: `private.js` `showPrivate` → `loadItems`·`loadPasskeys` 가 응답을 `textContent` 로만 그림(태그를 해석하지 않음).

## ④ 안 열리는 것을 확인한 기록

전체는 [docs/passkey-verification.md](docs/passkey-verification.md) 에 통과한 요청과 거절된 요청을 나란히 적었습니다(`py tools/verify_passkey.py` 로 다시 만들 수 있음). 요약:

| 확인 | 통과한 요청 | 거절된 요청 |
|---|---|---|
| **로그인 없이 열기** | `GET /api/me/items` + 세션 쿠키 → **200** 자료 3건 | 같은 요청, 쿠키 없음 → **401** `Log in with a passkey to see the private area` · 로그인 없이 받은 `/me/` 소스에 자료 제목 0개 |
| **남의 패스키로 열기** | A 의 아이디 + A 의 패스키로 로그인 → **200** | A 의 아이디 + B 의 패스키(서명은 올바름) → **403** `This passkey belongs to a different account` |
| ↳ 남의 자료 | A 가 자기 자료 `GET /api/me/items/<A의 번호>` → **200** | A 가 `GET /api/me/items/<B의 번호>` → **404**, 반대(B→A)도 **404**, 거절 앞뒤 건수 4건 → 4건 |
| ↳ 다른 계정을 적어 보내기 | `GET /api/me/items?account=bob…&account_id=2` → **200, A 의 자료만** · 본문 `"account_id": 2` 로 추가해도 A 에 저장 | A 가 B 의 패스키 `DELETE /api/me/passkeys/<B의 번호>` → **404** |
| **사용한 챌린지 재사용** | 로그인 `POST /api/me/login/verify` → **200** | **같은 본문** 다시 → **401** `This challenge was already used` · 서명 한 바이트 바꾼 요청 → **401** `Signature check failed` |
| **패스키 삭제 뒤 로그인** | 남은 패스키(Alice phone) → **200** | 지운 패스키(Alice laptop) → **401** `This passkey is not registered (it may have been deleted)` · 마지막 하나 삭제 → **409** |
| 로그아웃 뒤 같은 쿠키 | 로그아웃 전 `GET /api/me/items` → **200** | 로그아웃 후 같은 쿠키 → **401** |

**실제 기기로 한 확인** (✏️ 직접 채울 곳 — 아래 "실제 기기로 할 일" 참고)

- 패스키 1 이름·저장된 곳: ✏️ (예: "노트북 Windows Hello" — **기기 자체**(Windows Hello) / 또는 **구글 비밀번호 관리자**)
- 패스키 2 이름·저장된 곳: ✏️ (예: "내 휴대폰" — 휴대폰으로 QR 을 찍어 **구글 비밀번호 관리자** / 또는 **보안 키**)
- 화면 캡처: ✏️ `docs/images/passkey-*.png` (공개/비공개 경계, 패스키 두 개 목록, 하나 지운 뒤 로그인, 지운 패스키 로그인 실패)

## ⑤ AI와 나

✏️ 아래는 이번 작업 기록을 바탕으로 쓴 초안입니다. 본인 생각에 맞게 고치세요.

- **AI에게 맡긴 일:** WebAuthn 등록·로그인 흐름 코드(`intro.py`, `passkey.py`, `private.js`), P-256·RSA 서명 검사와 CBOR 해석 구현, 자동 테스트 23개, 시험용 소프트웨어 인증기와 확인 기록 도구, 이 설명서 초안.
- **내가 직접 판단한 일:** 과제 1 페이지(GitHub Pages)를 그대로 두고 따로 API 를 붙이는 대신, **PDS 서버의 `/me/` 로 옮겨 붙이기로** 했습니다(같은 주소라 HttpOnly 쿠키 세션을 쓸 수 있고 자동 배포를 그대로 씀). 실제 기기로 패스키 두 개를 어디에 저장할지 정하고 등록·삭제·로그인을 직접 해 보았습니다. ✏️
- **AI 제안을 따르지 않은 일:** ✏️ (없다면 왜 없었는지. 예: "배치 방식은 AI 가 두 가지를 내놓고 추천했는데 그 추천과 같아서 따랐다" 처럼 사실대로)

## ⑥ 아직 못 막은 것

1. **누구나 가입할 수 있고, 가입·로그인 횟수 제한이 없습니다.** 패스키만 있으면 계정을 얼마든지 만들 수 있고(계정마다 예시 자료 3줄이 생김), 같은 IP 에서 옵션 요청을 계속 보내면 `me_challenges` 에 줄이 쌓입니다(하루 지난 줄은 다음 요청 때 지움). IP 별 요청 제한은 아직 없습니다.
2. **패스키를 지워도 이미 열린 세션은 살아 있습니다.** 다른 기기에서 그 패스키로 로그인해 둔 세션은 만료(12시간)나 로그아웃 때까지 유효합니다. 세션이 어느 패스키로 열렸는지 기록하지 않아서 함께 끊지 못합니다.
3. **마지막 패스키를 잃으면 복구할 방법이 없습니다.** 비밀번호·이메일·복구 코드가 없어서, 남은 패스키가 있는 기기·비밀번호 관리자를 모두 잃으면 그 계정은 다시 열 수 없습니다. 서버는 마지막 하나의 삭제만 막을 뿐입니다. 계정 삭제 기능도 아직 없습니다.
4. **attestation 을 검사하지 않습니다.** 어떤 인증기(진짜 보안 키인지, 소프트웨어인지)로 만든 패스키인지 증명받지 않습니다. 화면의 "저장된 곳"은 AAGUID·BE 플래그로 **추정**한 값이라 틀릴 수 있습니다.
5. **지운 패스키가 기기에는 남습니다.** 서버에서 지워도 휴대폰·비밀번호 관리자의 목록에는 남아 있어 사용자가 직접 지워야 합니다.

---

## 실제 기기로 할 일 (제출 전 체크)

자동 기록은 시험용 인증기로 만든 것이므로, 아래는 실제 사이트에서 직접 해 주세요.

1. https://alstn.pythonanywhere.com/me/ 에서 계정 A 를 만듭니다(패스키 1, 예: Windows Hello). 비공개 영역과 패스키 표가 보이는 화면을 캡처합니다.
2. **패스키 추가**로 다른 곳에 패스키 2를 만듭니다. 같은 인증기에는 `excludeCredentials` 때문에 안 만들어지므로, 창에서 "다른 기기 사용"(휴대폰 QR) 또는 보안 키를 고릅니다. 두 개가 보이는 목록을 캡처합니다.
3. 패스키 1을 삭제 → 로그아웃 → 패스키 2로 로그인(성공) → 로그아웃 → 패스키 1로 로그인(실패 문구) 을 캡처합니다.
4. 시크릿 창에서 계정 B 를 만들고 다른 가상 자료를 하나 추가합니다.
5. 위 ④의 ✏️, ⑤의 ✏️ 를 채웁니다.

## 완주 체크리스트

- [x] 공개 영역과 비공개 영역을 화면에서 갈라 두었습니다 (공개 띠 + 노란 점선 경계 + 줄무늬 비공개 상자).
- [x] 패스키를 등록했고, 서버에 저장된 것이 공개키라는 것을 보였습니다 (기록 2절: DB 의 `public_key` = 인증기의 x, y).
- [x] 로그인마다 새 챌린지가 발급되고, 이미 사용한 챌린지는 다시 통과하지 않는 것을 확인했습니다 (기록 3절).
- [ ] 패스키를 두 개 등록하고, 하나를 삭제한 뒤에도 로그인했습니다 — 자동 기록 4절은 완료, **실제 기기 확인은 위 "실제 기기로 할 일"**.
- [x] 다른 계정의 패스키로는 비공개 자료에 접근할 수 없음을 요청과 응답으로 남겼습니다 (기록 5절).
- [ ] 제출물 어디에도 실제 개인정보와 비밀값이 없습니다 — 비공개 영역·기록·코드에는 없습니다. 다만 **과제 1 공개 소개 내용**(이름·생년월일·이메일·인스타그램 ID)은 과제 1에서 공개하기로 정한 내용이라 "그대로 남긴다"는 기준(C11)에 따라 그대로 두었습니다. ✏️ 이 부분을 어떻게 할지 정하세요.
