# 패스키 인증 설명서 — 자기소개 페이지의 비공개 영역 (과제 8)

과제 1의 자기소개 페이지([About-me](https://github.com/Lee-Minsoo6944/About-me)) 아래에 **패스키로만 열리는 비공개 영역**을 새로 붙였습니다. 비밀번호는 쓰지 않습니다. 화면은 과제 1 그대로 GitHub Pages 에 있고, 챌린지 보관·서명 검사·비공개 자료는 과제 7 서버(PythonAnywhere)가 맡습니다.

- **결과물:** https://lee-minsoo6944.github.io/About-me/ — 첫 화면은 과제 1 소개 페이지 그대로, 맨 아래가 비공개 영역
- **소스:** https://github.com/Lee-Minsoo6944/PDS-Diary — 서버 `intro.py`(흐름) · `passkey.py`(서명 검사) · 화면 `static/me/private.js`. 같은 `private.js`·`private.css` 를 [About-me 저장소](https://github.com/Lee-Minsoo6944/About-me)에도 넣었습니다.
- 같은 화면을 서버 주소에서도 열 수 있습니다: https://alstn.pythonanywhere.com/me/ (이 주소는 쿠키 세션. 패스키는 주소마다 따로라 두 주소의 패스키는 서로 바꿔 쓸 수 없음)
- **확인 기록 전체:** [docs/passkey-verification.md](docs/passkey-verification.md) (실제 HTTP 요청·응답, 세션 쿠키는 가림)
- **자동 테스트:** `py -m unittest discover -s tests -v` (63개 중 과제 8 테스트 26개: `tests/test_passkey.py`)

비공개 영역의 자료는 모두 **지어낸 가상의 내용**입니다(가상 회사 이름, 지어낸 메모·회고). 연락처·신분증 번호 같은 실제 개인정보는 넣지 않았습니다.

---

## 짧은 확인 방법

1. **어디로 가나요** — https://lee-minsoo6944.github.io/About-me/ 를 새 시크릿 창에서 엽니다. 위쪽은 과제 1 소개(공개), 노란 점선 아래가 비공개 영역입니다.
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
| 로그인 유지 | **서버 세션 + 세션 토큰** — 무작위 값 `secrets.token_urlsafe(32)`, DB 에는 SHA-256 만, 12시간. 결과물(GitHub Pages)에서는 응답 본문으로 받아 `sessionStorage` 에 두고 `Authorization: Bearer` 로 보냄. 서버 주소(`/me/`)에서는 같은 값을 `HttpOnly; SameSite=Strict` 쿠키로 | `intro.py` `start_session`, `read_token`, `session_account` |
| 다른 주소 허용 | `https://lee-minsoo6944.github.io` 한 곳에만 CORS(`Access-Control-Allow-Origin`) — 다른 사이트는 응답을 읽을 수 없음 | `intro.py` `cors_headers`, `app.py` `application` |
| CSRF | 쓰기 요청은 `X-PDS: 1` 머리글 필요(과제 7 규칙 그대로) | `app.py` `application` |
| 저장소 | 기존 SQLite 에 `me_accounts`, `me_credentials`, `me_challenges`, `me_sessions`, `me_items` 표 추가(다이어리 표와 분리) | `intro.py` `SCHEMA` |

attestation 은 `"none"` 으로 요청합니다. 인증기 제조사 증명서는 받지 않고 검사하지도 않습니다.

## ② 왜 그걸 골랐나

- **화면은 About-me, 검사는 과제 7 서버:** 과제 1 페이지는 GitHub Pages(정적 파일)라 챌린지를 보관하고 서명을 검사할 서버가 없습니다. 결과물 주소를 과제 1 그대로 두려고 화면은 About-me 저장소에 넣고, 검사는 이미 배포된 PythonAnywhere 서버의 `/api/me/*` 가 하게 했습니다. 이때 패스키의 rpId 는 화면 주소인 `lee-minsoo6944.github.io` 이고, 서버는 그 주소를 기준으로 origin·rpIdHash 를 검사합니다.
- **쿠키 대신 토큰(결과물 주소에서):** 화면과 서버 주소가 달라 쿠키를 쓰려면 `SameSite=None` 제3자 쿠키가 필요한데, Safari·Firefox 는 이를 막습니다. 그래서 응답 본문으로 세션 토큰을 주고, 화면은 **탭을 닫으면 지워지는 sessionStorage** 에만 둡니다. 토큰은 자동으로 실리지 않으므로 다른 사이트가 몰래 요청을 보내도(CSRF) 로그인 상태가 따라가지 않습니다. 서버 주소(`/me/`)에서는 자바스크립트가 읽을 수 없는 HttpOnly 쿠키를 그대로 씁니다.
- **직접 구현(표준 라이브러리만):** 이 앱은 과제 6부터 설치 없이 `py app.py` 하나로 돌고 PythonAnywhere 에도 그대로 올라갑니다. 서버가 하는 일은 **공개된 값(공개키·서명·메시지)의 검사뿐**이라 비밀값을 다루지 않고, 그래서 계산 시간이 드러나도 샐 비밀이 없습니다. 대신 표준 시험값(RFC 6979)과 틀린 서명·곡선 밖의 점 거절 테스트로 계산이 맞는지 확인했습니다.
- **서버 세션(JWT 아님):** 토큰은 서명된 정보가 아니라 무작위 값이고, 서버 DB 에 해시가 있을 때만 통합니다. 로그아웃하면 서버에서 줄을 지워 **그 즉시** 같은 토큰·쿠키가 거절됩니다. 서명용 비밀키가 없어 저장소에 숨길 값도 없습니다.
- **userVerification `required`:** 비밀번호 없이 패스키 하나로 들어오므로, 기기를 주운 사람이 터치만으로 들어오지 못하게 지문·얼굴·PIN 확인(UV 플래그)을 요구합니다.
- **디스커버러블 패스키(residentKey required):** 아이디를 적지 않아도 기기가 이 사이트용 패스키를 골라 줍니다. 아이디를 적으면 그 계정의 패스키만 허용합니다.
- **마지막 패스키는 못 지우게:** 비밀번호·이메일 복구가 없으므로 마지막 하나를 지우면 영영 못 들어옵니다. 그래서 서버가 막습니다(409).
- **남의 자료는 404:** 403 은 "있긴 하다"를 알려 주므로, 없는 것과 똑같이 답합니다.

## ③ 어디를 어떻게 고쳤나 (흐름별)

줄 번호는 이 커밋 기준입니다. 새 파일: `intro.py`, `passkey.py`, `static/me/*`, `tests/test_passkey.py`, `tools/soft_authenticator.py`, `tools/verify_passkey.py`. 고친 파일: `app.py`(아래 5곳). About-me 저장소: `index.html` 에 줄 추가만, `private.js`·`private.css` 새 파일.

**결과물 화면(About-me):** 원래 `index.html` 은 한 줄도 지우지 않고, 맨 위 "🌐 공개 영역" 띠, 맨 아래 경계선과 `<section id="private">`, `<script src="private.js" data-api="https://alstn.pythonanywhere.com/api/me/">` 만 덧붙였습니다. `private.js` 는 `data-api` 가 다른 주소면 토큰 방식으로 동작합니다.

**app.py 연결:** `/me/` 정적 파일 등록, `/me` → `/me/` 이동, `intro.SCHEMA` 로 표 만들기, `/api/me/*` 를 `intro.route` 로 넘기기, `/api/me/*` 에 CORS 머리글·사전 요청(OPTIONS) 처리(`application`).

**서버 주소의 같은 화면:** `static/me/index.html` — 과제 1 `index.html` 의 본문을 그대로 두고, 인라인 `<style>`·`<script>` 는 서버의 CSP(인라인 스크립트 금지) 때문에 `about.css`·`about.js` 로 옮겼습니다(내용은 같음). 맨 위에 "🌐 공개 영역" 띠, 맨 아래에 경계선과 `<section id="private">` 를 덧붙였습니다. 이 파일에는 비공개 내용이 없습니다.

### 등록 — `POST /api/me/register/options` → `navigator.credentials.create` → `POST /api/me/register/verify`
1. 화면: `private.js` `register()` — 아이디·패스키 이름을 보냄. 결과물 주소에서는 브라우저가 `Origin: https://lee-minsoo6944.github.io` 를 붙이고, 서버 `site()` 가 그 주소를 rpId·origin 으로 씀.
2. `intro.py` `register_options` (314행): 아이디 확인, 무작위 `user.id`(16바이트), `new_challenge` (229행)로 32바이트 챌린지를 만들어 `me_challenges` 에 보관(5분). 로그인한 채면 그 계정에 추가하고, 기존 패스키를 `excludeCredentials` 에 넣음.
3. 브라우저·인증기: 키 쌍을 만들고 **공개키만** `attestationObject` 에 담아 돌려줌(`registrationJSON`). 사용자가 창을 닫으면 `POST /api/me/cancel` 로 챌린지를 지움(`cancel_challenge`, 260행).
4. `intro.py` `register_verify` (349행): `consume_challenge` (241행)로 챌린지를 '썼음'으로 먼저 저장 → `passkey.py` `verify_registration` (314행)이 type·origin·챌린지·rpIdHash·UP/UV 플래그·자격 증명 ID 를 확인하고 COSE 공개키를 꺼냄 → `me_credentials` 에 공개키·ID·이름 저장, 새 계정이면 예시 자료 3개와 세션 생성.

### 로그인 — `POST /api/me/login/options` → `navigator.credentials.get` → `POST /api/me/login/verify`
1. `intro.py` `login_options` (396행): 매번 새 챌린지. 아이디를 적었으면 챌린지에 그 계정을 묶고 그 계정 패스키만 `allowCredentials` 에.
2. 인증기: 개인키로 `authenticatorData ‖ SHA-256(clientDataJSON)` 에 서명(`assertionJSON`).
3. `intro.py` `login_verify` (416행): `consume_challenge` → 자격 증명 ID 로 `me_credentials` 에서 공개키를 찾음(없으면 401) → 계정이 다르면 403 → `passkey.py` `verify_assertion` (351행)이 origin·rpIdHash·플래그를 보고 **저장된 공개키로 서명 검사**, signCount 가 거꾸로 가면 거절 → 통과하면 `start_session` (217행).

### 로그아웃 — `POST /api/me/logout`
- `intro.py` `logout` (449행): 토큰(또는 쿠키) 값의 해시로 `me_sessions` 에서 줄을 지움. 쿠키 방식이면 `Max-Age=0` 쿠키도 보냄. 화면은 sessionStorage 의 토큰을 지움.

### 비공개 자료 조회 — `GET /api/me/items`, `GET/DELETE /api/me/items/<id>`, `POST /api/me/items`
1. `intro.py` `route` (519행): `session_account` (193행)가 `Authorization: Bearer` 토큰(없으면 쿠키) → 해시 → `me_sessions` → 만료 확인. 없으면 **401**.
2. `list_items` (483행)·`get_item` (489행)·`delete_item` (510행)·`create_item` (496행): 모든 SQL 에 `account_id = <세션의 계정>`. 주소·본문의 `account`, `account_id`, `username` 은 읽지 않음.
3. 패스키 목록·삭제: `list_passkeys` (460행), `delete_passkey` (465행) — 자기 것만, 마지막 하나는 409.
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
| 로그아웃 뒤 같은 쿠키·토큰 | 로그아웃 전 `GET /api/me/items` → **200** | 로그아웃 후 같은 쿠키 → **401**, 같은 토큰 → **401** |
| 결과물 주소(GitHub Pages) | `Origin: https://lee-minsoo6944.github.io` 사전 요청 → **204** + 허락 머리글, 등록 → rpId `lee-minsoo6944.github.io`, 쿠키 없이 토큰 | `Origin: https://evil.example` 사전 요청 → 허락 머리글 **없음** · localhost 에서 만든 응답을 결과물 주소로 → **400** `clientData.origin does not match this site` |

**실제 배포 서버에서 한 "패스키 두 개 → 하나 삭제" 확인:** [docs/passkey-two-keys-production.md](docs/passkey-two-keys-production.md) — https://alstn.pythonanywhere.com 에 결과물 주소(`lee-minsoo6944.github.io`) 조건으로 시험 계정을 만들어, 두 번째 패스키 추가 → 첫 번째 삭제 → 남은 패스키 로그인 **200** / 지운 패스키 로그인 **401** / 마지막 패스키 삭제 **409** 를 확인했습니다. 두 패스키는 `tools/soft_authenticator.py` 로 만든 **소프트웨어 시험 키**입니다. 실제 계정 `123` 의 첫 패스키는 구글 비밀번호 관리자에 있고, 이 PC에는 두 번째로 쓸 다른 인증기가 없었습니다(Windows 계정에 비밀번호가 없어 Windows Hello PIN 불가, 휴대폰·보안 키 미사용).

**실제 기기로 한 확인**

- 계정 `123` 의 패스키 저장 위치: **구글 비밀번호 관리자**(Chrome, 여러 기기에 동기화). 계정 `456` 도 같은 PC의 같은 Chrome·같은 구글 계정으로 만들어 **구글 비밀번호 관리자**에 저장했습니다. 같은 곳에 두 번째 패스키를 만들려 하면 `excludeCredentials` 때문에 "이 인증기에는 이 계정의 패스키가 이미 있습니다"가 나옴
- 두 번째 패스키: 실제 인증기 대신 위의 소프트웨어 시험 키 두 개로 확인(실제 배포 서버 기록)
- 제출문에 붙일 화면: 공개/비공개 경계, 로그인 전 비공개 영역(안내 문구만), 로그인 뒤 비공개 자료와 패스키 표, 두 번째 패스키를 같은 곳에 만들려다 막힌 안내 문구

## ⑤ AI와 나

- **AI에게 맡긴 일:** WebAuthn 등록·로그인 흐름 코드(`intro.py`, `passkey.py`, `private.js`), P-256·RSA 서명 검사와 CBOR 해석 구현, 자동 테스트 23개, 시험용 소프트웨어 인증기와 확인 기록 도구, 이 설명서 초안.
- **내가 직접 판단한 일:** 처음에는 PDS 서버의 `/me/` 로 옮겨 붙였다가, 결과물은 **과제 1 주소(About-me, GitHub Pages) 그대로 두고 그 아래에 붙이기로** 다시 정했습니다. 검사는 이미 있는 PDS 서버가 맡고, 그 대신 생기는 CORS·토큰 문제는 설명서 ②·⑥에 적었습니다. 패스키는 Chrome 의 저장 위치 선택 창에서 **구글 비밀번호 관리자**를 골라 실제 계정 `123`, `456` 을 직접 만들었습니다. 두 번째 패스키를 같은 곳에 만들려다 막힌 뒤(이미 같은 계정의 패스키가 있음), PC 에 다른 인증기가 없다는 것을 확인하고 **"패스키 두 개 → 하나 삭제" 확인은 실제 배포 서버에서 시험 키로 하기로** 정했고, 그 키가 실제 기기가 아니라는 사실을 기록에 밝히도록 했습니다.
- **AI 제안을 따르지 않은 일:** ① 처음에 AI 는 GitHub Pages 를 두고 서버 주소(`alstn.pythonanywhere.com/me/`)로 옮겨 붙이는 방식을 추천했고 한 번은 그대로 따랐지만, 결과물은 과제 1 주소 그대로여야 한다고 판단해 **AI 가 덜 권한 방식(GitHub Pages 화면 + 다른 주소의 서버)으로 바꿨습니다.** ② 두 번째 패스키를 위해 AI 가 휴대폰 QR 연결이나 Bitwarden 같은 다른 비밀번호 관리자 확장 설치를 제안했지만, 휴대폰을 쓰지 않고 새 서비스에 가입하지도 않기로 하고 **따르지 않았습니다.** Windows 계정에 비밀번호를 추가해 Windows Hello PIN 을 켜는 방법도 PC 로그인 방식이 바뀌어 쓰지 않았습니다.

## ⑥ 아직 못 막은 것

1. **누구나 가입할 수 있고, 가입·로그인 횟수 제한이 없습니다.** 패스키만 있으면 계정을 얼마든지 만들 수 있고(계정마다 예시 자료 3줄이 생김), 같은 IP 에서 옵션 요청을 계속 보내면 `me_challenges` 에 줄이 쌓입니다(하루 지난 줄은 다음 요청 때 지움). IP 별 요청 제한은 아직 없습니다.
2. **패스키를 지워도 이미 열린 세션은 살아 있습니다.** 다른 기기에서 그 패스키로 로그인해 둔 세션은 만료(12시간)나 로그아웃 때까지 유효합니다. 세션이 어느 패스키로 열렸는지 기록하지 않아서 함께 끊지 못합니다.
3. **마지막 패스키를 잃으면 복구할 방법이 없습니다.** 비밀번호·이메일·복구 코드가 없어서, 남은 패스키가 있는 기기·비밀번호 관리자를 모두 잃으면 그 계정은 다시 열 수 없습니다. 서버는 마지막 하나의 삭제만 막을 뿐입니다. 계정 삭제 기능도 아직 없습니다.
4. **attestation 을 검사하지 않습니다.** 어떤 인증기(진짜 보안 키인지, 소프트웨어인지)로 만든 패스키인지 증명받지 않습니다. 화면의 "저장된 곳"은 AAGUID·BE 플래그로 **추정**한 값이라 틀릴 수 있습니다.
5. **지운 패스키가 기기에는 남습니다.** 서버에서 지워도 휴대폰·비밀번호 관리자의 목록에는 남아 있어 사용자가 직접 지워야 합니다.
6. **결과물 주소의 토큰은 자바스크립트가 읽을 수 있습니다.** GitHub Pages 화면은 서버와 주소가 달라 HttpOnly 쿠키를 쓰지 못하고 토큰을 sessionStorage 에 둡니다. 페이지에 남의 스크립트가 끼어드는 문제(XSS)가 생기면 그 탭이 열려 있는 동안(최대 12시간) 토큰을 훔쳐 갈 수 있습니다. 자료는 `textContent` 로만 그리고 외부 스크립트를 쓰지 않아 위험을 줄였지만, GitHub Pages 에는 CSP 머리글을 붙일 수 없어 서버 주소(`/me/`)만큼 막지는 못합니다.

---

## 실제 기기로 한 일

1. https://lee-minsoo6944.github.io/About-me/ 에서 Chrome 으로 계정 `123` 을 만들었습니다. 저장 위치는 **구글 비밀번호 관리자**(구글 비밀번호 관리자 PIN 으로 본인 확인).
2. 같은 방법으로 계정 `456` 을 만들었습니다. 서버에서 두 계정 모두 패스키 1개씩 등록된 것을 확인했습니다(`POST /api/me/login/options` 에 아이디를 넣으면 `allowCredentials` 1개).
3. 가입 전에 없는 아이디로 "패스키로 들어가기"를 누르면, 이 PC 에 그 사이트용 패스키가 없어 Windows 가 "보안 키를 USB 포트에 삽입하십시오" 창을 띄웠습니다(사이트 오류가 아님).
4. `123` 에 두 번째 패스키를 추가하려 하자:
   - 구글 비밀번호 관리자 → 화면에 "이 인증기(기기·비밀번호 관리자)에는 이 계정의 패스키가 이미 있습니다…" (서버가 보낸 `excludeCredentials` 로 브라우저가 막음, 서버에는 저장 안 됨)
   - Windows 창 → USB 보안 키만 제시. Windows Hello PIN 은 "이 로그인 옵션을 사용하려면 비밀번호를 추가해야 합니다"로 켤 수 없음
5. 그래서 "패스키 두 개 → 하나 삭제 → 로그인"은 실제 배포 서버에서 소프트웨어 시험 키 두 개로 확인했습니다([docs/passkey-two-keys-production.md](docs/passkey-two-keys-production.md)).

## 완주 체크리스트

- [x] 공개 영역과 비공개 영역을 화면에서 갈라 두었습니다 (공개 띠 + 노란 점선 경계 + 줄무늬 비공개 상자).
- [x] 패스키를 등록했고, 서버에 저장된 것이 공개키라는 것을 보였습니다 (기록 2절: DB 의 `public_key` = 인증기의 x, y).
- [x] 로그인마다 새 챌린지가 발급되고, 이미 사용한 챌린지는 다시 통과하지 않는 것을 확인했습니다 (기록 3절).
- [x] 패스키를 두 개 등록하고, 하나를 삭제한 뒤에도 로그인했습니다 — 실제 배포 서버 기록([docs/passkey-two-keys-production.md](docs/passkey-two-keys-production.md)), 소프트웨어 시험 키 사용(위 "실제 기기로 한 일" 4–5).
- [x] 다른 계정의 패스키로는 비공개 자료에 접근할 수 없음을 요청과 응답으로 남겼습니다 (기록 5절).
- [x] 제출물 어디에도 실제 개인정보와 비밀값이 없습니다 — 비공개 영역의 자료는 모두 지어낸 가상의 내용이고, 기록의 세션 쿠키·토큰은 앞 5글자 뒤를 가렸으며, 코드·저장소에 비밀키가 없습니다. 공개 소개의 이름·생년월일·이메일·인스타그램 ID 는 과제 1에서 본인이 **공개하기로 정해 이미 공개된 정보**이고, "1번의 공개 내용을 그대로 남긴다"(C11)에 따라 바꾸지 않았습니다. 연락처(전화번호)·주민등록번호는 어디에도 없습니다.
