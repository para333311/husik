# husik — 매수맛집 경매 자동복기 시스템 (1차 MVP)

"매수맛집" 콘텐츠에서 공유되는 경매 PDF를 텔레그램으로 받아 사건 단위로 분석하고,
텔레그램 대표 메시지 + Notion DB("매수맛집 경매")로 자동 정리/추적하는 시스템입니다.

## 핵심 동작 개요

1. 사용자가 텔레그램 봇(개인 대화방)에 경매 PDF를 보냄
2. PDF 각 페이지를 이미지로 렌더링 (PyMuPDF)
3. 페이지별 텍스트 추출: PyMuPDF 텍스트 → Tesseract(kor+eng) OCR → OpenAI Vision fallback
4. **사건번호**(구역명 아님, 예: `2024타경12345`) 기준으로 페이지를 사건 단위로 묶음
   - 같은 사건번호가 여러 페이지에 반복돼도 하나의 사건으로 유지
   - `$$$$` 같은 달러 표시가 반복돼도 사건이 나뉘지 않음 (분할 기준이 아님)
5. 달러등급이 **`$$$` 이상**인 사건만 처리, `$$` 이하/등급 없음은 버림
6. 사건마다 대표 메시지 1개 + 페이지 이미지들을 텔레그램에 전송 (원본 PDF는 절대 전송하지 않음)
7. Notion DB("매수맛집 경매")에 사건번호 기준 upsert
8. 이후 블로그 신규 언급, 경매 상태변경/낙찰결과는 대표 메시지를 **editMessageText**로 갱신 (새 메시지 생성 X)

## 요구 사항

- Python 3.11+
- Tesseract OCR (`tesseract-ocr`, `tesseract-ocr-kor`) — 로컬 실행 시에만 필요, GitHub Actions는 자동 설치
- Telegram Bot 2개 (경매용/오디오용), Notion Integration, Naver 개발자 API, OpenAI API Key

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 환경변수

`.env.example`을 복사해 `.env`로 만들고 값을 채우세요 (`.env`는 절대 커밋하지 않습니다).

| 변수 | 설명 |
| --- | --- |
| `TELEGRAM_AUCTION_BOT_TOKEN` | 경매 PDF 수신/대표 메시지 발송용 봇 토큰 |
| `TELEGRAM_AUDIO_BOT_TOKEN` | (2차 MP3 쿠키봇용, 1차에서는 미사용) |
| `TELEGRAM_AUCTION_CHANNEL_ID` | 대표 메시지/이미지를 보낼 채널 ID (`-100...`) |
| `TELEGRAM_AUDIO_CHANNEL_ID` | (2차 MP3 쿠키봇용, 1차에서는 미사용) |
| `TELEGRAM_ALLOWED_USER_ID` | PDF 업로드를 허용할 유일한 텔레그램 사용자 ID |
| `OPENAI_API_KEY` | OCR 실패 시 Vision fallback에 사용 |
| `NOTION_TOKEN` | Notion Integration 토큰 |
| `NOTION_AUCTION_DB_URL` | "매수맛집 경매" DB URL (레거시 `NOTION_HUSIK_DB_ID`도 fallback으로 지원) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 블로그 검색 API |
| `COURT_AUCTION_ENABLED` / `MADANGS_ENABLED` / `BLOG_MONITOR_ENABLED` | 기능 on/off (`true`/`false`, 기본 true) |

값 자체는 절대 코드/로그/README에 하드코딩하지 않습니다. 모두 환경변수 또는 GitHub Actions Secrets에서만 읽습니다.

## CLI 사용법

```bash
# 필수 환경변수 검증
python -m husik.cli validate-env

# 텔레그램 PDF polling (실서비스/스케줄러용)
python -m husik.cli telegram-pdf-ingest

# 로컬 PDF 테스트: 전송 없이 감지된 사건 목록만 출력
python -m husik.cli process-local-pdf data/inbox/sample.pdf --dry-run

# 로컬 PDF 테스트: 실제로 Telegram/Notion에 전송
python -m husik.cli process-local-pdf data/inbox/sample.pdf --send

# 일일 블로그 모니터링
python -m husik.cli blog-monitor

# 일일 경매 상태/낙찰결과 모니터링
python -m husik.cli auction-monitor
```

`data/inbox/`는 로컬 테스트 전용이며 git에는 커밋되지 않습니다. 테스트하고 싶은 PDF를
`data/inbox/sample.pdf`로 넣고 `--dry-run`을 실행하면, 사건번호/달러등급/제목/페이지범위/처리여부만
출력되고 어떤 전송도 일어나지 않습니다.

### `--dry-run` 출력 예시

```
사건번호            달러등급      제목                            페이지범위       처리 여부
2024타경12345     $$$$      강남 아파트 특급매물                   1-3p        처리
2024타경99999     $$        부산 상가 매물                      4-4p        버림(달러등급 $$$ 미만)
2025타경555       $$$       인천 빌라 매물                      5-6p        처리
```

## 텔레그램 대표 메시지 포맷

```
[입찰일 확인중] $$$$ PDF 원문 제목
```

경매정보(매각기일)가 확인되면:

```
[2026-08-20 입찰 D-14] $$$$ PDF 원문 제목
```

블로그 업데이트/상태변경/낙찰결과는 새 메시지를 만들지 않고 기존 대표 메시지를
`editMessageText`로 수정하며, 새 이벤트를 항상 맨 위에 붙입니다:

```
[블로그업데이트] [2026-08-20 입찰 D-7] $$$$ PDF 원문 제목
...
--------------------
기존 내용
...
```

낙찰결과 업데이트에는 반드시 **입찰인수**가 포함됩니다.

메시지는 3800자 근처에서 안전하게 잘리며, 전체 누적 기록은 Notion 상세페이지에 남습니다.

## Notion 연동

- `NOTION_TOKEN` + `NOTION_AUCTION_DB_URL`(또는 레거시 `NOTION_HUSIK_DB_ID`)로 "매수맛집 경매" DB에 접근합니다.
- 필요한 속성이 없으면 자동 생성을 시도하고, 실패하면 어떤 속성이 빠졌는지 명확한 오류 메시지를 출력합니다.
- 사건번호(`사건번호` 속성) 기준으로 upsert합니다.
- 본문에는 대표 메시지 내용 복사본, 블로그 링크 목록, 상태변경 기록을 append 방식으로 누적합니다.
- 영상/MP3 파일은 Notion에 저장하지 않습니다.

## 상태 저장 (`data/state/`)

- Telegram `update_id` offset
- 처리된 PDF의 SHA-256 해시 (중복 처리 방지)
- 사건번호별 대표 메시지 ID / 이미지 메시지 ID / Notion page ID / 블로그 URL 목록 / 경매정보 스냅샷
- 원본 PDF/이미지는 저장하지 않고 처리 즉시 삭제합니다.
- `data/state/state.json`만 GitHub Actions에서 자동 커밋됩니다. `data/inbox`, `data/tmp`, `data/outbox`,
  `*.pdf`, `*.png`, `*.jpg`는 `.gitignore`에 포함되어 있어 커밋되지 않습니다.

## GitHub Actions

| Workflow | 주기 | 명령 |
| --- | --- | --- |
| `.github/workflows/pdf_ingest.yml` | 15분마다 + 수동 실행 | `telegram-pdf-ingest` |
| `.github/workflows/blog_monitor.yml` | 하루 1회 + 수동 실행 | `blog-monitor` |
| `.github/workflows/auction_monitor.yml` | 하루 1회 + 수동 실행 | `auction-monitor` |

세 workflow 모두 `data/state/`에 변경이 있을 때만 자동 커밋/푸시합니다. 필요한 Secrets는
아래 "필요한 GitHub Secrets" 섹션을 참고하세요.

## 필요한 GitHub Secrets

Repository → Settings → Secrets and variables → Actions 에 아래 이름으로 등록하세요.
(값은 실제 토큰/키이며 여기 문서에는 절대 예시 값을 넣지 않습니다.)

- `TELEGRAM_AUCTION_BOT_TOKEN`
- `TELEGRAM_AUDIO_BOT_TOKEN`
- `TELEGRAM_AUCTION_CHANNEL_ID`
- `TELEGRAM_AUDIO_CHANNEL_ID`
- `TELEGRAM_ALLOWED_USER_ID`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_AUCTION_DB_URL` (또는 레거시 `NOTION_HUSIK_DB_ID`)
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `COURT_AUCTION_ENABLED` (선택, 기본 true)
- `MADANGS_ENABLED` (선택, 기본 true)
- `BLOG_MONITOR_ENABLED` (선택, 기본 true)

## 테스트

```bash
pytest
ruff check .
```

pytest는 네트워크/외부 서비스 호출 없이 순수 로직(사건번호 정규화, 사건 묶기, 메시지 포맷,
state 저장/로드, Notion ID 파싱, 블로그 키워드 생성 등)을 검증합니다.

로컬에서 실제 PDF로 전체 파이프라인을 확인하려면:

```bash
mkdir -p data/inbox
cp <your-auction-pdf> data/inbox/sample.pdf
python -m husik.cli process-local-pdf data/inbox/sample.pdf --dry-run
```

## 경매정보/조회수 보강 (best-effort)

- `src/husik/auction/adapters.py`에 공통 인터페이스가 있고, `court.py`(법원경매)와
  `madangs.py`(경매마당)가 이를 구현합니다.
- 로그인 우회, CAPTCHA 우회, 비정상적인 크롤링은 하지 않습니다.
- 조회/파싱이 실패해도 전체 처리를 막지 않고 해당 필드를 "확인중"으로 둡니다.
- 정확한 사건 상세 URL 생성이 어려운 경우 검색/메인 링크를 대신 넣습니다.

## 알려진 제한사항 (1차 MVP)

- 경매마당/법원경매 adapter는 best-effort 수준이며, 실제 사건 상세 페이지 파싱(감정가/최저가/
  매각기일/낙찰가/조회수 등 정밀 추출)은 2차 이후 사이트별 파서를 붙여야 완성됩니다.
- OpenAI Vision fallback은 페이지 텍스트 추출용으로만 쓰이며, 사건 구조화 자체는 정규식 기반입니다.
- Tesseract가 설치되지 않은 환경(로컬)에서는 OCR 단계가 건너뛰어지고 native 텍스트 또는
  OpenAI Vision 결과만 사용됩니다.

## TODO (2차 이후 — MP3 쿠키봇, 이번 1차 범위 아님)

- 쉬는시간/음악구간 제거
- 원속 기준 30분 단위 분할
- 마지막 조각이 20분 이하면 앞 파일에 병합
- 최종 파일은 2배속 MP3
- 파일명 예: `2026-08-06_01.mp3`
