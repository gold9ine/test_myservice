# 꽃사슴 (FLAP)

디자이너를 중심으로 한 커리어·포트폴리오·팔로우 기반 미용 지도입니다.

단골 디자이너가 다른 헤어샵으로 옮기면 고객은 디자이너를 다시 찾기 어렵습니다. 꽃사슴은 디자이너가 새 소속 헤어샵을 등록해, 예전 고객이 디자이너의 새 소속을 확인할 수 있게 하는 것을 목표로 합니다. 제품 요구사항은 [PRD.md](PRD.md)에 있습니다.

Streamlit 으로 만든 MVP 이고, 수업 「생성형 AI 실전 활용 — 나만의 웹서비스·MVP 제작」 실습 저장소입니다.

## 화면

| 화면 | 하는 일 |
|---|---|
| 첫 화면 | 서비스 소개와 할 수 있는 일 |
| 꽃사슴 (헤어샵 찾기) | 지역을 골라 헤어샵 목록과 지도 위치 보기 |
| 헤어샵 세부정보 | 헤어샵 정보와 소속 디자이너 보기, 이직 등록 |
| 디자이너 상세 | 디자이너 프로필과 포트폴리오 보기 |
| 새 헤어샵 등록 | 이름 · 연락처 · 지도 위치(주소 또는 좌표)로 헤어샵 등록 |

어느 화면에서든 오른쪽 아래 아이콘으로 상담 챗봇(Claude)을 열 수 있습니다.

> **지금은 읽기 전용입니다.** 새 헤어샵 등록과 데이터베이스 저장(이직 등록, 챗봇 기록)을 막아 두었습니다.
> 다시 열려면 `app.py` 의 `NEW_SALON_OPEN`, `DB_WRITE_OPEN` 을 `True` 로 바꿉니다.

아직 없는 것: 로그인(로그인 버튼은 샘플), 사용자 대시보드, 예약. 「준비 중이에요」 표시가 있는 버튼은 자리만 잡아 둔 것입니다.

## 실행하기

Python 과 아래 패키지가 필요합니다. (이 저장소에는 requirements 파일이 없습니다)

```
pip install streamlit anthropic pillow
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 이 열립니다.

### 키 넣기

`.env.example` 을 `.env` 로 복사해 값을 채웁니다. `.env` 는 GitHub 에 올리지 않습니다.

| 이름 | 쓰는 곳 | 비워 두면 |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | 헤어샵 · 디자이너 자료 | `data/` 폴더의 CSV 를 읽습니다 |
| `ANTHROPIC_API_KEY` | 상담 챗봇 | 챗봇이 키를 채워 달라고 안내합니다 |
| `KAKAO_REST_API_KEY` | `lunch.py` 연습 페이지 | 검색을 할 수 없습니다 |

네이버 지도는 `.streamlit/secrets.toml` 에 `NAVER_MAP_CLIENT_ID`, `NAVER_MAP_CLIENT_SECRET` 을 넣으면 보입니다. 없으면 지도 자리에 좌표 글자만 나옵니다. 이 파일도 GitHub 에 올리지 않습니다.

### Supabase 쓰기 (선택)

Supabase 대시보드 > SQL Editor 에서 `supabase_setup.sql` 을 실행하면 `data/*.csv` 자료가 표로 만들어집니다. 챗봇 기록 표는 `supabase_chatbot_logs.sql`, 쓰기 권한은 `supabase_write_policies.sql` 입니다.

## 연습 페이지

수업 중에 따로 만들어 본 페이지입니다. 꽃사슴 앱과는 연결되어 있지 않고, 하나씩 `streamlit run 파일이름.py` 로 엽니다.

| 파일 | 페이지 | 필요한 것 |
|---|---|---|
| `key_check.py` | Claude 키 확인 | `ANTHROPIC_API_KEY` |
| `helper.py` | 챗봇 | `ANTHROPIC_API_KEY` |
| `guestbook.py` | 한 줄 방명록 | Supabase |
| `docs.py` | 문서 보관함 | Supabase, `supabase_docs_storage.sql` |
| `photos.py` | 사진 보관함 | Supabase, `supabase_photos_storage.sql` |
| `subs.py` | 구독 정리함 | Supabase, `supabase_subscriptions.sql` |
| `lunch.py` | 전주 객사 맛집 | `KAKAO_REST_API_KEY` |
| `practice_table.py` | 연습 문의 목록 | `pandas` |

## 폴더

```
app.py                 꽃사슴 앱 (화면 전체)
chatbot.py             상담 챗봇
chatbot_instruction.md 챗봇 지시문
PRD.md                 제품 요구사항
backlog.md, progress.md  할 일과 진행 기록
idea/                  제품 발굴 메모, 흐름, 와이어프레임
data/                  예비 CSV (Supabase 키가 없을 때 읽음)와 연습 자료
assets/                로고, 아이콘, 폰트, 샘플 사진
supabase_*.sql         Supabase 표와 권한을 만드는 SQL
.streamlit/config.toml 화면 색 (보라 테마)
```

© 2026 gold9ine
