# 인증 설명서 — Plan · Do · See Diary 2

과제 6의 다이어리(마지막 커밋 [`b2caa89`](https://github.com/Lee-Minsoo6944/PDS-Diary/commit/b2caa89))에 가입·로그인·로그아웃을 붙여, **자기 자료만 보이게** 바꿨습니다. 이 저장소의 과제 7 커밋들은 모두 `b2caa89` 위에 이어집니다(`git merge-base --is-ancestor b2caa89 HEAD` 로 확인).

- 사이트: https://alstn.pythonanywhere.com — 첫 화면이 로그인 화면입니다.
- 확인 기록 전체: [docs/auth-verification.md](docs/auth-verification.md) (실제 HTTP 요청, 비밀번호·쿠키는 가림)
- 자동 테스트: `py -m unittest discover -s tests -v` (35개, 인증·차단 관련 16개 포함)

---

## ① 무엇을 썼나

| 부분 | 쓴 것 | 어디에 |
|---|---|---|
| 비밀번호 저장 | Python 표준 라이브러리 `hashlib.scrypt` (N=2¹⁴, r=8, p=1, 32바이트) + 계정마다 다른 16바이트 소금값(`os.urandom`) | `app.py` `hash_password`, `verify_password` |
| 비밀번호 비교 | `hmac.compare_digest` (비교 시간이 값에 따라 달라지지 않음) | `verify_password` |
| 로그인 유지 | **서버 세션** — `secrets.token_urlsafe(32)` 무작위 값을 `HttpOnly` 쿠키 `pds_session` 에 담고, 서버 DB 에는 그 값의 SHA-256 만 저장 | `new_session`, `session_user`, `sessions` 표 |
| 쿠키 설정 | `HttpOnly; SameSite=Lax; Path=/; Max-Age=604800(7일)`, https 에서는 `Secure` | `cookie_header` |
| 다른 사이트에서 몰래 보내는 쓰기 막기(CSRF) | 쓰기 요청(POST·PUT·DELETE)은 `X-PDS: 1` 헤더가 있어야 받음 | `application` |
| 주인 확인 | 모든 조회·수정·삭제 SQL 에 `user_id = 로그인한 사람` 조건 | `plan_row`, `todo_row`, `list_*`, `delete_log`, `get_note` 등 |
| 저장소 | 기존 SQLite 에 `users`, `sessions`, `account_deletions` 표 추가 | `SCHEMA` |

새로 설치한 패키지는 없습니다. 외부 로그인 서비스(구글 등)도 쓰지 않습니다.

## ② 왜 이렇게 했나

- **표준 라이브러리만**: 과제 6부터 이 앱은 설치 없이 `py app.py` 하나로 돌아가는 구조였고, PythonAnywhere 에도 그대로 올라갑니다. scrypt 는 Python 에 들어 있고, 일부러 느리고 메모리를 많이 쓰게 만든 비밀번호 전용 해시라 SHA-256 한 번보다 훨씬 깨기 어렵습니다.
- **JWT 대신 서버 세션**: JWT 는 서버가 비밀키로 서명해야 하고, 로그아웃해도 만료 전까지 토큰이 살아 있습니다. 서버 세션은 ⓐ 비밀키가 아예 없고(저장소에 숨길 값이 없음) ⓑ 로그아웃·비밀번호 변경 때 서버에서 줄을 지우면 **그 즉시** 같은 쿠키가 거절됩니다. 과제 기준 C109·C110·C114 를 가장 단순하게 지킬 수 있는 방법이라 골랐습니다.
- **세션 값을 해시로 저장**: DB 파일이 새어도 그 안의 값으로는 로그인할 수 없습니다.
- **HttpOnly 쿠키**: 화면의 자바스크립트가 세션 값을 읽을 수 없고, 주소(URL)에도 실리지 않습니다.
- **남의 자료는 404**: 403 은 "있긴 한데 네 것이 아님"을 알려 주므로, 없는 것과 똑같이 404 로 답해 번호를 넣어 보며 남의 자료가 있는지 알아내는 것도 막았습니다.
- **같은 실패 문구**: 아이디가 없을 때와 비밀번호가 틀릴 때 모두 `401 Wrong username or password`. 없는 아이디일 때도 가짜 해시로 같은 계산을 해서 걸리는 시간도 비슷하게 맞췄습니다(`dummy_hash`).

## ③ 어떤 코드를 바꿨나 (흐름별)

줄 번호는 이 커밋 기준 `app.py` 입니다.

### 가입 — `POST /api/auth/signup`
1. `signup` (470행): 아이디 3–30자(영문·숫자·`._-`) 확인, 비밀번호 8–128자 확인(`check_new_password`).
2. `hash_password` (372행)로 소금값+scrypt 해시 → `scrypt$16384$8$1$<소금>$<해시>` 문자열만 저장.
3. 같은 아이디가 있으면 `409 That username is already taken`. 아이디는 대소문자를 구분하지 않습니다(`username TEXT UNIQUE COLLATE NOCASE`, 69행) — DB 규칙이라 동시에 두 번 눌러도 하나만 들어갑니다.
4. 성공하면 바로 세션을 만들어(`new_session`, 424행) 쿠키로 돌려줍니다.

### 로그인 — `POST /api/auth/login`
1. `login` (486행): 아이디로 사용자를 찾고, 없으면 `dummy_hash()` 로 같은 계산.
2. `verify_password` (381행)가 저장된 소금값으로 다시 계산해 `hmac.compare_digest` 로 비교.
3. 틀리면 `401` + 같은 문구, 쿠키 없음. 맞으면 새 세션 쿠키.

### 로그아웃 — `POST /api/auth/logout`
- `logout` (500행): 쿠키의 세션 값을 해시해 `sessions` 표에서 **지우고**, `Max-Age=0` 쿠키로 브라우저 쪽도 지웁니다.
- 비밀번호 변경(`change_password`, 509행)은 그 사람의 세션을 **모두** 지우고(519행) 새 세션 하나만 줍니다 → 다른 브라우저는 로그아웃됩니다.

### 자료 읽기·쓰기 — 나머지 모든 `/api/*`
1. `application` (1231행): 쓰기 요청에 `X-PDS: 1` 이 없으면 `403` (1263행). 그다음 `session_user` (446행)가 쿠키 → 해시 → `sessions` 표 → 만료 확인(7일 지나면 지우고 거절).
2. `route` (1057행): `/api/meta`, `/api/auth/signup|login|logout|me` 말고는 로그인이 없으면 `401 Please log in`. 있으면 `uid = user["id"]` (1078행)를 **모든** 처리 함수에 넘깁니다. 주소·본문·헤더에 적힌 `user_id` 는 아예 읽지 않습니다.
3. 주인 확인이 들어 있는 곳:
   - 계획: `plan_row` (575행) `WHERE id = ? AND user_id = ?`, `list_plans` (604행)
   - 할 일: `todo_row` (657행) `JOIN plans p … AND p.user_id = ?`, `list_todos` (707행)
   - 작업 기록: `list_logs` (852행), `delete_log` (870행)
   - 날짜 메모: `get_note`·`put_note`·`list_notes` (1006–1030행) `WHERE user_id = ?`
   - 내보내기: `export_all` (1033행) — 내 계획에 딸린 것만, 비밀번호 해시는 넣지 않음
   - 리뷰·회고·완료·되돌리기도 모두 `plan_row`/`todo_row` 를 먼저 거칩니다.
4. 화면(`static/app.js`): 쓰기 요청에 `X-PDS` 헤더(58행), 시작할 때 `/api/auth/me` 로 로그인 여부 확인 → 아니면 로그인 화면(`start`, 728행). 중간에 401 이 오면 로그인 화면으로 돌아갑니다.

### 과제 6 자료 옮기기 (DB 버전 2 → 3)
- `init_db` (245행)가 DB 를 고치기 **전에** 파일을 통째로 복사해 둡니다(`pds.db.v2-backup-날짜`).
- `migrate` (222행): `plans` 에 `user_id` 열 추가, `day_notes` 는 사용자별로 같은 날짜를 가질 수 있게 다시 만듦.
- 예전 자료는 주인이 비어 있어 **아무에게도 보이지 않다가**, 콘솔에서 `python3 app.py claim <아이디>` (`claim_unowned`, 1305행)를 실행하면 그 계정으로 옮겨집니다.

### 내보내기·계정 삭제
- Account 탭: `Export as JSON` → 내 자료만 담긴 파일.
- `Delete my account and all my data`: 비밀번호를 다시 넣고 확인 창까지 거쳐야 하며, 지워진다는 안내가 붙어 있습니다. `delete_account` (525행)가 한 번의 트랜잭션으로 내 계획·버전·할 일·기록·회고·메모·세션·계정을 지웁니다. 계획 버전 표는 원래 지울 수 없게 막혀 있어서(과제 6 규칙), 계정 삭제 중일 때만 풀리도록 트리거를 바꿨습니다(181행).

## ④ 확인 기록

로컬 서버(과제 6 데모 DB 를 복사해 v3 로 고친 것)에 [`tools/verify_auth.py`](tools/verify_auth.py) 를 돌린 결과입니다. 매번 무작위 시험 계정 A·B 를 만들고 끝나면 지웁니다. **31개 확인 모두 통과.** 비밀번호는 `••••`, 세션 쿠키는 앞 5글자 뒤를 `…(masked)` 로 가렸습니다. 전체는 [docs/auth-verification.md](docs/auth-verification.md).

대표 몇 개만 나란히 옮깁니다.

**같은 요청, 로그아웃 전과 후** (C109·C110)

| 허용 | 거절 |
|---|---|
| `GET /api/plans`<br>`Cookie: pds_session=tmJLX…(masked)`<br>→ **200** | (그 사이 `POST /api/auth/logout` → 200)<br>`GET /api/plans`<br>`Cookie: pds_session=tmJLX…(masked)`<br>→ **401** `{"error": "Please log in"}` |

**A 가 자기 계획 vs B 의 계획 읽기** (C117) — 반대 방향(B→A)도 같은 결과

| 허용 | 거절 |
|---|---|
| `GET /api/plans/6` (A 의 것)<br>`Cookie: pds_session=LywFS…(masked)`<br>→ **200** | `GET /api/plans/7` (B 의 것)<br>`Cookie: pds_session=LywFS…(masked)`<br>→ **404** `{"error": "Plan not found"}` |

**틀린 비밀번호 vs 없는 아이디** (C99)

```
POST /api/auth/login {"username": "check_a_…", "password": "••••"}  → 401 {"error": "Wrong username or password"}
POST /api/auth/login {"username": "nobody_…",  "password": "••••"}  → 401 {"error": "Wrong username or password"}
```

**저장된 비밀번호** (C101–C105) — 같은 비밀번호를 써도 소금값이 달라 저장값이 다릅니다.

```
check_a_…: scrypt$16384$8$1$23Aaak…(소금)$…(해시)
```

그 밖에 기록에 있는 것: 같은 아이디 재가입 409, 로그인 없이 401, 남의 계획·할 일 고치기 404, 남의 작업 기록 지우기 404, 남의 계획에 할 일 넣기 404, 남의 리뷰 404(모두 양쪽 방향), 거절 전후 상대 자료 통째로 같음, 주소·헤더·본문에 남의 `user_id` 를 넣어도 무시, 목록에 남의 자료 없음, `X-PDS` 없는 쓰기 403, 비밀번호 변경 뒤 다른 브라우저 세션 401, 예전 비밀번호 401, 계정 삭제(틀린 비밀번호 403 / 맞으면 200, 남은 B 는 그대로).

## ⑤ AI와 나

- 이 기능의 코드와 이 문서의 초안은 AI(Claude)가 썼습니다.
- 나는 "라이브러리 vs 직접 구현" 선택지 중 **직접 구현(표준 라이브러리 scrypt + 서버 세션)** 을 골랐습니다. 이유: 설치 없이 지금 배포 구조를 그대로 쓰고, 로그아웃이 바로 먹히고, 숨겨야 할 비밀키가 없기 때문.
- 확인은 AI 의 설명을 믿는 대신 **요청을 직접 보내 결과 숫자로** 했습니다: 자동 테스트 35개, 실제 HTTP 확인 31개, 브라우저에서 가입 → 과제 6 자료 옮기기 → 로그아웃 → 틀린 비밀번호까지 눌러 봄.
- 실제 계정의 비밀번호는 문서·기록·채팅 어디에도 적지 않았고, 시험 계정은 무작위 값으로 만들었다가 지웠습니다.
- <!-- 내가 직접 확인하거나 고친 것을 한두 줄 더 적기 -->

## ⑥ 아직 막지 못한 것

- **비밀번호 무차별 대입**: 로그인 실패 횟수 제한·잠금이 없습니다. scrypt 가 한 번에 수십 ms 걸려 느리게는 만들지만, 오래 시도하면 약한 비밀번호는 뚫릴 수 있습니다.
- **비밀번호 찾기 없음**: 이메일을 받지 않으므로 잊으면 되찾을 방법이 없습니다(관리자가 DB 에서 직접 고쳐야 함).
- **2단계 인증 없음**.
- **약한 비밀번호 허용**: 길이(8자)만 봅니다. 흔한 비밀번호 목록과 비교하지 않습니다.
- **기록(감사 로그) 없음**: 누가 언제 로그인·실패했는지 남기지 않습니다.
- **세션 목록 보기 없음**: 지금 어느 브라우저가 로그인돼 있는지 볼 수 없습니다(비밀번호를 바꾸면 모두 끊기는 것만 있음).
- **아이디 존재 여부**: 로그인에서는 숨기지만, **가입** 화면에서 "이미 있는 아이디"라고 알려 주므로 아이디가 있는지는 알아낼 수 있습니다(가입에는 필요한 안내라 남겨 둠).
- **서버·DB 자체**: PythonAnywhere 계정이 털리거나 DB 파일이 통째로 새면, 비밀번호 원문은 없지만 일기 내용은 그대로 보입니다(암호화해 저장하지 않음).
- **예전 자료 백업 파일**: 버전 2 → 3 으로 고칠 때 만든 백업 파일은 주인 구분이 없는 과제 6 자료 그대로입니다. 서버 안에만 있고 웹으로는 열리지 않습니다.
- **자동 배포 주소** `/api/deploy` 는 비밀값 없이 열려 있습니다. 하는 일은 GitHub 의 최신 코드를 받는 것뿐이고(15초에 한 번), 자료를 읽거나 바꾸지는 못합니다.
