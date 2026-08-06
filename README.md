# husik — 매수맛집 경매 자동복기 시스템 (1차 MVP)

"매수맛집" 콘텐츠에서 공유되는 경매 PDF를 텔레그램으로 받아 사건 단위로 분석하고,
텔레그램 대표 메시지 + Notion DB("매수맛집 경매")로 자동 정리/추적하는 시스템입니다.

## PDF 입력/출력 위치 (반드시 확인)

실제 봇/채널 이름은 배포 환경마다 다를 수 있지만, 예시로는 다음과 같이 구성합니다.

- **입력**: PDF는 반드시 입력봇(예: "자료드랍_경매") **개인 대화방(1:1 DM)** 으로 보내야 합니다.
  - `TELEGRAM_AUCTION_BOT_TOKEN`이 이 입력봇의 토큰입니다.
  - `TELEGRAM_ALLOWED_USER_ID`로 등록된 사용자가 보낸 PDF만 처리합니다.
  - **출력 채널에 PDF를 직접 올리는 것이 아닙니다.** 채널에는 봇이 대표 메시지/이미지를 대신 올려줍니다.
- **출력**: 대표 메시지와 페이지 이미지는 출력 채널(예: "같이보는 경매")로 전송됩니다.
  - `TELEGRAM_AUCTION_CHANNEL_ID`가 이 출력 채널의 ID이며, **반드시 `-100`으로 시작**해야 합니다
    (양수 숫자를 넣으면 봇 ID나 사용자 ID를 잘못 넣은 것입니다 — `validate-env`가 경고합니다).
  - 입력봇은 이 출력 채널의 **관리자(admin)** 여야 메시지/이미지를 보낼 수 있습니다.
- PDF 처리가 성공/실패/스킵 중 무엇이든 **입력봇 개인 대화방으로 결과 요약이 옵니다.**
  아무 반응이 없다면 아래 "무반응일 때 확인하는 방법"을 따라가세요.

### 무반응일 때 확인하는 방법

workflow가 Success인데 채널/Notion에 아무것도 안 올라오고 개인 대화방에도 메시지가 없다면,
아래 순서로 원인을 좁혀갑니다 (모두 토큰 값 자체는 출력하지 않습니다).

```bash
# 1. 필수 환경변수 + 채널 ID 형식 확인
python -m husik.cli validate-env

# 2. 봇 토큰/webhook 상태/출력 채널 접근 권한 진단 (가능하면 테스트 메시지 전송 후 삭제)
python -m husik.cli telegram-diagnose

# 3. 실제로 전송/처리는 하지 않고 getUpdates만 조회해서 PDF가 도착했는지 확인
python -m husik.cli telegram-updates-dry-run
```

`telegram-updates-dry-run`으로 PDF가 안 보인다면 입력봇 개인 대화방에 PDF를 보냈는지,
`TELEGRAM_ALLOWED_USER_ID`가 실제 보낸 사람과 일치하는지 확인하세요 — 입력봇 개인 대화방에서
`/whoami`를 보내면 본인의 user_id를, `/chatid`를 보내면 현재 chat_id를 즉시 알려줍니다
(`/ping`은 봇이 살아있는지 확인용, "pong"으로 응답). 이 세 명령은 PDF 처리 로직과 무관하게
항상 즉시 응답하며, `TELEGRAM_ALLOWED_USER_ID`/`TELEGRAM_AUCTION_CHANNEL_ID` 설정 전에도 동작합니다.

GitHub Actions에서 `telegram-pdf-ingest`를 실행하면 각 단계별 카운터
(`updates_seen`, `allowed_user_passed`, `skipped_by_user`, `pdf_documents_seen`,
`sent_telegram_cases`, `notion_upserted`, `errors_count` 등)가 워크플로우 로그에
`PDF_INGEST_STAT` 접두사로 출력됩니다 (토큰/사용자 식별값 자체는 출력하지 않습니다).

## 핵심 동작 개요

1. 사용자가 텔레그램 봇(개인 대화방)에 경매 PDF를 보냄
2. PDF 각 페이지를 이미지로 렌더링 (PyMuPDF)
3. 페이지별 텍스트 추출: PyMuPDF 텍스트 → Tesseract(kor+eng) OCR → OpenAI Vision fallback
4. **사건번호**(구역명 아님, 예: `2024타경12345`) 기준으로 페이지를 사건 단위로 묶음
   - 형식: `20xx` + `타경` + 숫자 4~8자리. `2025타경102095`, `2025 타경 102095`,
     `2025타경 102095`, `2025 타경102095` 등 공백 유무와 무관하게 인식하고,
     항상 공백 없는 형태(`2025타경102095`)로 정규화해 저장합니다.
   - 같은 사건번호가 여러 페이지에 반복돼도 하나의 사건으로 유지
   - `$$$$` 같은 달러 표시가 반복돼도 사건이 나뉘지 않음 (분할 기준이 아님)
   - 한 페이지 안에 사건번호가 여러 개 있으면(다른 사건이 같은 페이지에서 시작하는
     경우) 페이지 전체를 붙이지 않고, 사건번호 위치(bbox) 기준으로 세로 구간을
     나눠 사건별로 그 구간만 crop해서 보냅니다 — 다른 사건 이미지가 섞이지 않습니다.
   - bbox를 구할 수 없는데 사건번호가 여러 개인 페이지처럼 확신할 수 없는 경우는
     특정 사건에 억지로 붙이지 않고 "[검토필요]" 메시지로 따로 보냅니다.
   - 사건번호가 없는 continuation 페이지 중 "20xx타경" 비슷한 조각만 있고 완전한
     사건번호가 아닌 경우(OCR 깨짐 의심)도 직전 사건에 붙이지 않고 검토필요로 분리합니다.
5. **사건번호가 있으면 달러등급과 무관하게 전부 등록/전송합니다.** 달러등급은 더 이상
   필터가 아니라 분류 태그입니다:
   - `$$$` / `$$$$` / `$$$$$` — 정상적으로 인식된 등급 (그대로 표시)
   - `$` 또는 `$$` 수준으로만 잡히면 → **"낮은등급"**
   - 등급을 전혀 못 찾거나 불확실하면 → **"등급확인"**
   - 등급 인식은 `$$$`/`SSS`/`추천 3` 등 다양한 표기를 지원하되, `SSS`나 숫자
     3/4/5는 "추천"/"등급"/"달러" 키워드 근처에서만 등급 후보로 인정합니다.
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
# 필수 환경변수 검증 (+ TELEGRAM_AUCTION_CHANNEL_ID 형식 검증)
python -m husik.cli validate-env

# 봇 토큰/webhook/출력 채널 접근 권한 진단 (토큰 값은 출력하지 않음)
python -m husik.cli telegram-diagnose

# getUpdates만 조회 (실제 처리/전송 없음, --commit-offset 없으면 offset도 변경 안 함)
python -m husik.cli telegram-updates-dry-run

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
사건번호            달러등급      제목                      페이지범위       처리 여부   혼합페이지
2024타경12345     $$$$      강남 아파트 특급매물             1-3p        처리      false
2024타경9999      낮은등급      부산 상가 매물                4-4p        처리      false
2025타경5551      등급확인      인천 빌라 매물                5-6p        처리      false
```

사건번호가 감지된 사건은 등급(`$$$`/`$$$$`/`$$$$$`/`낮은등급`/`등급확인`)과 무관하게
모두 "처리" 대상입니다 — 더 이상 등급으로 사건을 버리지 않습니다.

`--debug-layout`을 추가하면 각 사건이 어느 페이지/crop에서 왔는지(`p1 crop1, p2 crop1`
형태)도 함께 출력하고, `--save-crops <디렉터리>`를 추가하면 사건별/검토필요별 crop
이미지를 지정한 폴더에 저장해 직접 확인할 수 있습니다:

```bash
python -m husik.cli process-local-pdf data/inbox/sample.pdf --dry-run --debug-layout
python -m husik.cli process-local-pdf data/inbox/sample.pdf --dry-run --save-crops data/debug/crops
```

## 텔레그램 대표 메시지 포맷

가독성을 위해 값이 없는 항목("확인중"/None/0)은 아예 줄을 숨기고 핵심만 보여줍니다.
"확인중"은 상태/입찰일/등급처럼 꼭 필요한 곳에만 씁니다. 링크는 긴 URL을 그대로
노출하지 않고 `<a href="...">경매마당</a>` 형태의 HTML 링크로 보내며
(`parse_mode=HTML`, `disable_web_page_preview=True`), 헤더에는 제목 대신
**사건번호**를 표시하고 제목은 본문의 "제목:" 줄에 따로 보여줍니다.

```
[입찰일 확인중] [등급확인] 2025타경102095

사건번호: 2025타경102095
제목: 건물등기부 / 채권액합계 8,080,000,000원
상태: 확인중

관심도:
- 블로그 언급: 30
- 최근 7일 신규 블로그: 22

링크:
- 경매마당
- 법원경매

첨부 이미지: 2장
업데이트:
- 최초 등록
```

감정가/최저가/매각기일/법원/소재지/물건번호는 값이 있을 때만 표시되고, 없으면
줄 자체가 생략됩니다. 달러기호 등급(`$$$`/`$$$$`/`$$$$$`)은 헤더에 그대로 붙고,
`낮은등급`/`등급확인`은 대괄호로 감쌉니다.

블로그 업데이트/상태변경/낙찰결과는 새 메시지를 만들지 않고 기존 대표 메시지를
`editMessageText`로 수정하며, 새 이벤트를 항상 맨 위에 붙입니다:

```
[블로그업데이트] [2026-08-20 입찰 D-7] [등급확인] 2025타경102095
...
--------------------
기존 내용
...
```

낙찰결과 업데이트에는 반드시 **입찰인수**가 포함됩니다.

메시지는 3800자 근처에서 안전하게 잘리며, 전체 누적 기록은 Notion 상세페이지에 남습니다.

사건 구분이 불확실한 이미지(bbox 없이 한 페이지에 사건번호가 여러 개 있는 경우 등)는
특정 사건에 억지로 붙이지 않고 `[검토필요]` 메시지로 별도 전송됩니다.

## Notion 연동

- `NOTION_TOKEN` + `NOTION_AUCTION_DB_URL`(또는 레거시 `NOTION_HUSIK_DB_ID`)로 "매수맛집 경매" DB에 접근합니다.
- `NOTION_AUCTION_DB_URL`은 `notion.so/...?v=...`, `notion.so/workspace/slug-<32자리id>`,
  `app.notion.com/p/<32자리id>` 형태를 모두 지원합니다.
- 설정된 URL로 DB 접근이 실패하면(URL 오류, integration 미공유 등) Notion 검색 API로
  "매수맛집 경매"라는 이름의 DB를 찾는 fallback을 자동으로 시도합니다.
- 필요한 속성이 없으면 자동 생성을 시도하고, 실패하면 어떤 속성이 빠졌는지 명확한 오류 메시지를 출력합니다.
- "달러등급" select 속성 그룹: `$$$$$`, `$$$$`, `$$$`, `낮은등급`, `등급확인` (필터가 아니라 분류용).
  "달러개수"는 `$$$$$`→5, `$$$$`→4, `$$$`→3, `낮은등급`/`등급확인`→0으로 저장됩니다.
- 사건번호(`사건번호` 속성) 기준으로 upsert합니다.
- 본문에는 대표 메시지 내용 복사본, 블로그 링크 목록, 상태변경 기록을 append 방식으로 누적합니다.
- 영상/MP3 파일은 Notion에 저장하지 않습니다.
- **Notion 실패가 Telegram 전송을 막지 않습니다.** Notion이 완전히 실패해도 텔레그램 대표
  메시지/이미지는 정상 전송되며, 개인 대화방에 "텔레그램 전송은 완료됐지만 노션 업데이트에
  실패했습니다..." 알림이 옵니다.

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

## 텔레그램 이미지 전송 실패 fallback

- 대표 메시지(사건별 1개)는 출력 채널로 전송을 시도하고, 실패하면(`sendMessage` 실패) 채널 ID/봇
  관리자 권한 문제로 보고 해당 PDF의 나머지 사건 처리를 중단하며, 개인 대화방에 "텔레그램 채널
  전송 실패..." 메시지를 보냅니다.
- 이미지는 `sendMediaGroup`(최대 10장 단위, reply 포함)을 먼저 시도하고, 실패하면 reply 없이
  재시도한 뒤, 그래도 실패하면 `sendPhoto`로 한 장씩 순서대로 재시도합니다.
- `sendPhoto`가 그래도 실패하면 이미지를 압축/리사이즈한 뒤 한 번 더 재시도합니다.
- 대표 메시지는 성공했지만 일부 이미지가 끝내 실패하면, 개인 대화방에 몇 장이 실패했는지
  알려줍니다. PDF 원본 파일은 어떤 경우에도 전송하지 않습니다.

## 채널 접근 진단(`telegram-diagnose`) 주의사항

`telegram-diagnose`는 출력 채널 접근 권한을 확인하기 위해 `[시스템테스트]` 메시지를 채널에
보낸 뒤 즉시 삭제를 시도합니다. **봇에게 메시지 삭제 권한이 없으면 이 테스트 메시지 1개가
채널에 남을 수 있습니다** (진단 결과에 "삭제 권한이 없어 남아있을 수 있음"으로 표시됩니다).
이는 의도된 동작이며, 채널 관리자 권한을 봇에게 부여하면 자동으로 삭제됩니다.

## 알려진 제한사항 (1차 MVP)

- 경매마당/법원경매 adapter는 best-effort 수준이며, 실제 사건 상세 페이지 파싱(감정가/최저가/
  매각기일/낙찰가/조회수 등 정밀 추출)은 2차 이후 사이트별 파서를 붙여야 완성됩니다.
  상세정보는 OCR에서 억지로 뽑지 않고 사건번호를 키로 이 adapter에서 채웁니다.
- OpenAI Vision fallback은 (1) 페이지 텍스트 추출, (2) 텍스트 기반으로 사건번호를 못
  찾았을 때 사건번호 목록만 JSON으로 재확인하는 두 용도로 쓰이며, 사건 구조화 자체는
  정규식 기반입니다. Vision이 반환한 사건번호도 정규식으로 재검증한 뒤에만 사용합니다.
- Tesseract가 설치되지 않은 환경(로컬)에서는 OCR 단계가 건너뛰어지고 native 텍스트 또는
  OpenAI Vision 결과만 사용됩니다. 페이지 내 사건 단위 이미지 분리(crop)도 텍스트
  레이어가 없는 스캔 PDF에서는 tesseract의 단어 좌표(bbox)에 의존하므로, 로컬에
  tesseract가 없으면 사건번호가 1개인 페이지는 정상 동작하지만 한 페이지에 사건번호가
  여러 개인 경우는 "[검토필요]"로 분리됩니다 (섞이는 것보다 안전한 쪽을 택함).
- PDF 전체에서 텍스트를 전혀 추출하지 못하면(OCR 전면 실패) "PDF 분석에 실패했습니다..."
  알림이 오며, 텍스트는 있으나 사건번호 자체를 못 찾으면 "사건번호를 찾지 못했습니다..."
  알림이 옵니다 — 두 경우를 구분해서 알려줍니다. 사건번호가 있으면 달러등급과 무관하게
  항상 전송되므로, 등급 인식 실패로 사건이 누락되는 일은 없습니다.

## TODO (2차 이후 — MP3 쿠키봇, 이번 1차 범위 아님)

- 쉬는시간/음악구간 제거
- 원속 기준 30분 단위 분할
- 마지막 조각이 20분 이하면 앞 파일에 병합
- 최종 파일은 2배속 MP3
- 파일명 예: `2026-08-06_01.mp3`
