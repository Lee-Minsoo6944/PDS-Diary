# 플랜두씨 다이어리 (과제 6)

계획(Plan) → 실제로 한 일(Do) → 돌아보기(See)가 서버 데이터베이스로 이어지는 다이어리.

> 지금은 로그인이 없어 링크를 아는 사람은 누구나 볼 수 있습니다. 남이 봐도 괜찮은 내용만 넣으세요. (잠그는 일은 7번 과제)

## 구성
- `app.py` — 서버. **파이썬 표준 라이브러리만** 사용(설치할 것 없음), 자료는 SQLite(`data/pds.db`)
- `static/` — 화면(HTML·JS·CSS). 글자는 모두 `textContent` 로 넣어 스크립트 모양 글자도 글자 그대로 보임
- `contracts/pds-schema-v2.json` — 표·항목·관계·날짜 규칙·집계 규칙
- `tests/test_app.py` — 통과 기준(T06-Cxx) 자동 확인

## 로컬 실행
```bash
py app.py
```
→ http://127.0.0.1:8000

```bash
py -m unittest discover -s tests -v
```

## 배포 (PythonAnywhere 무료 계정 기준 — 파일이 지워지지 않아 SQLite가 그대로 남음)
1. GitHub에 이 폴더를 올립니다(`data/` 는 .gitignore 로 빠짐).
2. PythonAnywhere → Consoles → Bash: `git clone https://github.com/<내아이디>/<저장소>.git pds`
3. Web → Add a new web app → Manual configuration → Python 3.x
4. WSGI configuration file 내용을 아래로 바꿉니다.
   ```python
   import sys
   sys.path.insert(0, "/home/<내아이디>/pds")
   from app import application
   ```
5. Reload → `https://<내아이디>.pythonanywhere.com` 을 시크릿 창에서 열어 확인.

비밀값(API 키 등)은 쓰지 않습니다. 저장소·배포 파일·응답 어디에도 비밀값이 없습니다.

## 시간 규칙
- 시각: UTC로 저장(`…Z`), 화면은 서울 시간
- 날짜: 서울 기준 `YYYY-MM-DD`
- 시간 길이: 모두 분(정수)

## 완료 중복 막기
1. 브라우저가 완료 요청마다 키(`idempotency_key`)를 붙이고, 연달아 눌러도 같은 키를 보냄 → 서버가 같은 요청으로 알아봄
2. DB 부분 고유 인덱스 `completions(todo_id) WHERE undone_at IS NULL` → 키가 달라도 유효한 완료는 1건
3. 버튼 잠금에 기대지 않음(버튼은 일부러 잠그지 않음)

---

## 제출용 — 짧은 확인 방법
1. **어디로 가나요:** `<결과물 주소>` 를 새 시크릿 창에서 엽니다.
2. **세 단계 안에 무엇을 하나요:** ① 위쪽 계획 상자에서 내 계획을 고르고 ② 「4. 돌아보기」 탭을 누른 뒤 ③ 「막힘 수」 같은 숫자를 누릅니다.
3. **무엇이 보이면 통과인가요:** 첫 화면 노란 공개 안내, 0이 아닌 집계 숫자, 숫자를 누르면 「근거 할 일 N건만 보는 중」과 그 숫자만큼의 할 일(또는 실행 기록) 목록이 보입니다.
4. **안 될 때는 무엇이 보이나요:** 오른쪽 아래 빨간 알림에 오류 문장이 뜨거나, 「계획이 없습니다」/ 빈 목록이 보입니다.

## 제출용 — AI와 내 판단 (본인 말로 고쳐 쓰세요)
1. **AI에게 맡긴 일:** 서버·DB 표 설계 초안, 화면 코드, 자동 테스트 작성.
2. **내가 직접 판단한 일:** (예: 어떤 계획을 넣을지, 예상 시간을 몇 분으로 잡을지, 돌아보기에서 고칠 점 한 줄)
3. **AI 말을 따르지 않은 일:** (본인이 바꾸거나 거절한 제안을 적고, 없다면 왜 없었는지)
