# Event Collector — 게임 외부행사 자동 수집

[![Collect game events](https://github.com/G-Dev-F-C/game_event_agent/actions/workflows/collect-events.yml/badge.svg)](https://github.com/G-Dev-F-C/game_event_agent/actions/workflows/collect-events.yml)

매주 월요일 09:00 KST에 itch.io 게임잼과 지정된 공식 출처의 게임 컨퍼런스를 수집해 Google Sheets에 저장.
캘린더에는 사용자가 선택한 행사만 수동 추가한다.

## 고정 수집 출처와 날짜 기준
- 게임잼: 기존 itch.io 수집 및 미래 접수/온라인·국내 필터 유지.
- 컨퍼런스: 넥슨(`nexon.com`), 스마일게이트(`smilegate.com`), NC소프트(`ncsoft.com`), 크래프톤(`krafton.com`), 인벤 게임 컨퍼런스 IGC(`inven.co.kr`), 지스타 본행사 및 G-CON(`gstar.or.kr`). 각 도메인의 하위 도메인 포함. 지스타 전시회와 G-CON은 별도 행사로 저장한다.
- 공식 대표 페이지를 직접 조회하고 행사 관련 링크를 한 단계 더 따라간다. Tavily는 수집 기간에 걸친 연도별·출처별 2개 쿼리를 각각 advanced 검색(쿼리당 최대 10개 결과)한다. 공식 도메인 이외의 결과와 리다이렉트는 제외한다.
- 이미지 배너의 대체 텍스트도 읽는다. 지스타/G-CON의 명시적 날짜는 직접 파싱하고 그 외 원문은 Gemini로 구조화한다.
- 컨퍼런스는 한국 시간 기준 `오늘 < start_date <= 오늘 + 6개월`만 포함한다. 6개월은 180일이 아닌 달력 기준이며 마지막 날도 포함한다. 오늘 시작/진행중/과거/취소/날짜 미정 행사는 제외한다. 접수 마감만 지났고 본행사가 미래인 경우는 유지한다.
- 조건에 맞게 발견한 컨퍼런스는 건수 제한 없이 저장한다. 기존 중복은 제외하고, 게임잼 등 다른 행사의 신규 20건 제한은 유지한다. 검색에 노출되지 않거나 접근이 차단된 페이지까지 전수 수집을 보장하지는 않는다.
- 기사 게시일이나 접수일을 행사 시작일로 추정하지 않는다. 타사 행사 참가 기사, IR 컨퍼런스콜, 일반 게임 이벤트는 추출 대상이 아니다.
- `TAVILY_API_KEY`, `GEMINI_API_KEY`가 컨퍼런스 수집에 필요하다. 키 누락이나 출처 실패 시 컨퍼런스 결과가 없을 수 있으며 게임잼 수집은 계속한다.
- 로컬 검증: `python -m unittest discover -s tests -v` (외부 API/시트 쓰기 없이 실행).

## 구조
```
.github/workflows/collect-events.yml  # GitHub Actions 예약/수동 실행
requirements-actions.txt             # Actions 배치 실행 의존성
scripts/run_collector.py             # 설정/시트 접근 확인, 실행, Summary 작성
agent.py              # search → extract → validate → overseas_filter → cap → present → dedup → sheets
tools/
  gemini.py           # Gemini 3.5-flash-lite rate limiter (4초 간격, 429 지수백오프, fallback flash-lite-latest)
  search.py           # itch.io 게임잼 + 컨퍼런스 결과 병합
  conferences.py      # 공식 출처 6곳 한정 검색/추출 + 미래 시작일 필터
  extractor.py        # 원문 fetch 및 구조화 결과 정규화
  validator.py        # 마감/종료 필터 + 해외 오프라인 필터 (국내 키워드/.kr/온라인 포함 시 유지)
  sheets.py           # Service Account, events 탭 자동 생성 + hash dedup + batchUpdate
  calendar.py         # Service Account, 그룹 캘린더 자동 등록 + eventId dedup + insert
prompts/extract_prompt.txt  # JSON 스키마 + location/해외 표기 규칙
setup_cron.py         # Cron 등록 (CRON_SCHEDULE env로 변경)
```

## 빠른 시작
1. `cp .env.example .env` 후 채우기:
   - `GEMINI_API_KEY` (모델: `gemini-3.5-flash-lite`, fallback `gemini-flash-lite-latest` — 2.5는 신규 사용자 404)
   - `TAVILY_API_KEY` (`tvly-...`, 컨퍼런스 출처별·연도별 검색)
   - `GOOGLE_SERVICE_ACCOUNT_FILE=game-event-agent-xxx.json` 또는 `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `SHEET_ID` (예: `1dL2n...`), `CALENDAR_ID` (그룹 캘린더 `...@group.calendar.google.com` 또는 `primary`)
2. Google Cloud: Service Account 생성 → Sheets/Calendar/Drive API 활성화 → 해당 시트/캘린더에 `...@...iam.gserviceaccount.com` 편집자 공유 (그룹 캘린더는 SA가 자동 `calendarList.insert`로 등록)
3. 배치 수집: `pip install -r requirements-actions.txt` (Actions와 동일한 의존성)
4. 로컬 테스트: `python -c "from agent import graph; print(graph.invoke({'messages':['test']}))"`  (키 없으면 dry-run)
5. LangGraph Studio: `langgraph dev`
6. Actions 예약은 아래 배포 안내 참고. `setup_cron.py`는 별도 LangGraph Cloud용이며 Actions에는 사용하지 않음.
7. 시트 확인: 하단 `events` 탭 (헤더: id/title/category/start_date/end_date/deadline/location/url/source/status/discovered_at/calendar_event_id/last_updated)

## 주기 변경

현재 GitHub Actions 배포는 [.github/workflows/collect-events.yml](.github/workflows/collect-events.yml)의 `on.schedule`을 수정해 `main`에 푸시한다. cron은 UTC 기준이다.

```yaml
# 매일 오전 9시 KST
- cron: '0 0 * * *'
# 월요일·목요일 오전 9시 KST
- cron: '0 0 * * 1,4'
```

로컬 `.env`의 `CRON_SCHEDULE`은 Actions에 영향을 주지 않는다. 아래 설정은 별도 LangGraph Cloud를 사용할 때만 적용한다.

```dotenv
CRON_SCHEDULE=0 0 * * *   # 매일
CRON_SCHEDULE=0 0 * * 1,4 # 월/목
```
후 `python setup_cron.py` 재실행 또는 Platform API로 update.

## 동작 규칙
- **컨퍼런스 날짜 필터:** `today < start_date <= today + 6개월` (Asia/Seoul). 날짜 미정/진행중/종료/취소 제외, 접수 마감은 별도.
- **해외 필터:** `location`에 `온라인` 포함 → 유지, `오프라인: 해외(미국/일본 등)` + 국내 키워드/`.kr` 없음 → 제외, 빈 location/혼합(오프라인+온라인)은 유지
- **중복:** `sha1(title+start_date+url)` 해시로 Sheets A열/Calendar eventId dedup

## 배포 및 운영

### GitHub Actions (현재 배포 환경)

| 항목 | 설정 |
| --- | --- |
| 저장소 / 브랜치 | 공개 저장소 `G-Dev-F-C/game_event_agent` / `main` |
| 실행 플랫폼 | GitHub-hosted 표준 Linux runner, `ubuntu-latest` |
| Python | `3.12` |
| 워크플로 이름 | `Collect game events` |
| 실행 진입점 | `python -m scripts.run_collector` |
| 의존성 | `requirements-actions.txt` |
| 예약 | 매주 월요일 09:00 KST, cron `0 0 * * 1` (UTC) |
| 시간대 | 환경변수 `TZ=Asia/Seoul`, 날짜 판정도 한국 시간 기준 |
| 제한 | 실행 최대 20분, 컨퍼런스 건수 제한 없음 / 기타 행사 신규 최대 20건 |
| 동시 실행 | `collect-game-events` 그룹으로 직렬화, 실행 중 작업은 취소하지 않음 |
| 저장소 권한 | `contents: read`, checkout 인증 정보 보존 안 함 |
| 영구 저장 | Google Sheets, 기본 탭 `events` |

정해진 시간에 수집 후 종료하는 배치 구조이며 상시 서버나 공개 API URL은 없다. runner 로컬 파일은 영구 저장하지 않는다.
기존 수집 데이터와 중복 판별 ID는 Google Sheets에서 읽는다. Calendar와 LangSmith 인증 정보는 현재 워크플로에 주입하지 않는다.

**배포 검증 기록 (2026-09-17):** 커밋 [`05f7607`](https://github.com/G-Dev-F-C/game_event_agent/commit/05f7607), [첫 실행 성공](https://github.com/G-Dev-F-C/game_event_agent/actions/runs/35186086663).
해당 실행에서 게임잼 29건, 컨퍼런스 0건을 확인했고 모두 기존 데이터라 신규 저장은 0건이었다. 최신 결과는 [Actions 실행 목록](https://github.com/G-Dev-F-C/game_event_agent/actions/workflows/collect-events.yml)에서 확인한다.

`.github/workflows/collect-events.yml`이 매주 월요일 09:00 KST에 실행된다.
GitHub Actions의 **Collect game events → Run workflow**로 수동 실행할 수 있다.
예약 실행은 지연될 수 있으며, 공개 저장소는 60일간 활동이 없으면 예약이 비활성화될 수 있다.

Repository Secrets: `GEMINI_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`(JSON 전체), `SHEET_ID`.
Repository Variables(선택): `SHEET_TAB`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`.

#### 인증 및 환경 설정

저장소 **Settings → Secrets and variables → Actions**에서 관리한다. 현재 배포 저장소에는 필수 Secrets가 등록되어 있으며, 복제/fork한 저장소에서는 별도로 등록해야 한다.

| 구분 | 이름 | 값 / 기본값 |
| --- | --- | --- |
| Secret (필수) | `GEMINI_API_KEY` | 컨퍼런스 구조화용 API 키 |
| Secret (필수) | `TAVILY_API_KEY` | 공식 출처 검색용 API 키 |
| Secret (필수) | `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스 계정 키 파일의 JSON 내용 전체. 파일 경로가 아님 |
| Secret (필수) | `SHEET_ID` | Google Sheets URL의 `/spreadsheets/d/` 다음 ID |
| Variable (선택) | `SHEET_TAB` | 기본 `events` |
| Variable (선택) | `GEMINI_MODEL` | 기본 `gemini-3.5-flash-lite` |
| Variable (선택) | `GEMINI_FALLBACK_MODEL` | 기본 `gemini-flash-lite-latest` |

Google Cloud에서 Sheets/Drive API를 활성화하고 대상 시트를 서비스 계정 `client_email`에 편집자로 공유한다.
Secrets는 수집 단계의 환경변수로 주입된다. API 키를 Variables에 넣지 않는다.
키 교체 시 해당 Secret을 갱신하고 수동 실행으로 검증한다. 로컬 `.env` 변경은 Actions에 반영되지 않는다.

API 키/서비스 계정 파일은 커밋하지 않는다. 기존 서비스 계정에 대상 시트 편집 권한이 필요하다.
Linux 표준 runner에서 `requirements-actions.txt`를 설치하고 테스트 후 수집한다.
Cloud 서버용 gRPC/protobuf 고정 의존성은 배치 환경에서 설치하지 않는다.
동시 실행을 방지하며 최대 20분으로 제한한다. 컨퍼런스는 6개월 내 발견한 신규 행사를 모두 저장하고 기타 행사는 신규 20건으로 제한한다. 결과는 실행 Summary에서 확인한다.
컨퍼런스 출처별 실패/누락은 로그로 확인한다. 수집 0건이 모든 출처의 정상 조회를 보장하지 않는다.
별도 LangGraph Cloud 배포나 `setup_cron.py` 실행은 필요 없다.

#### 수동 실행 및 로그 확인

1. **Actions → Collect game events → Run workflow**에서 브랜치 `main`을 선택한다.
2. 실행 페이지의 `collect` 작업에서 의존성 설치, 테스트, `Collect and save to Google Sheets` 단계를 확인한다.
3. 실행 **Summary**의 `stats`, `collected_by_category`, `errors`와 대상 시트 내용을 확인한다.

```bash
gh workflow run collect-events.yml --repo G-Dev-F-C/game_event_agent --ref main
gh run list --repo G-Dev-F-C/game_event_agent --workflow collect-events.yml --limit 5
gh run view RUN_ID --repo G-Dev-F-C/game_event_agent --log
```

`stats.found`는 추출된 행사 수, `stats.sheets_inserted`는 새로 저장한 행 수이다.
중복은 저장 전에 제외하므로 수집 건수가 있어도 신규 저장은 0일 수 있다. 중복 제거 건수는 `캡:` 로그를 확인한다.
진입점은 필수 설정과 시트 접근을 먼저 검사한다. 그래프가 반환한 오류 또는 시트 저장 오류가 있으면 작업을 실패로 종료한다.
출처별 오류는 수집기 내부에서 경고로 처리될 수 있어 성공 표시와 함께 원문 조회 실패 로그도 확인해야 한다.

#### 업데이트, 중지 및 장애 확인

- `main`에 푸시한 코드는 다음 예약/수동 실행부터 적용된다. **push 자체는 수집을 실행하지 않는다.**
- Actions 워크플로 메뉴의 **Disable workflow / Enable workflow**로 중지/재개한다.
- 예약 실행은 기본 브랜치 기준이며 GitHub 부하로 지연되거나 누락될 수 있다. 공개 저장소는 60일간 활동이 없으면 예약이 비활성화될 수 있다. [GitHub 예약 실행 안내](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- HTTP 403: 원문 접근 차단으로 해당 출처 결과가 누락될 수 있다.
- HTTP 429: API 할당량과 재시도 로그를 확인한다.
- 시트 접근 실패: 서비스 계정 JSON, `SHEET_ID`, 시트 공유 권한, API 활성화를 확인한다.
- 의존성 설치 실패: Actions용 `requirements-actions.txt`를 확인한다. 기존 `requirements.txt`의 서버용 gRPC/protobuf 고정 설정은 배치 환경에 사용하지 않는다.
- 실행 시간/저장 건수 변경은 워크플로의 `timeout-minutes`, `WEEKLY_CAP`을 수정한다.

### LangGraph Cloud (대안)

```bash
# 1. Secrets 업로드 — .env → Secret Manager
pip install google-cloud-secret-manager python-dotenv
python scripts/push_secrets.py --env .env --project game-event-agent
# 또는 dry-run: --dry-run, 또는 gcloud: bash scripts/setup_cloud_secrets.sh game-event-agent .env

# 2. Cloud 배포
npx @langchain/langgraph-cli login   # 또는 langgraph login
langgraph build --config langgraph.json
langgraph deploy --config langgraph.json
# 생성된 URL: https://<deployment>.us-central1.langgraph.app

# 3. Cron 등록 (Cloud에서만 동작)
LANGGRAPH_API_URL=https://<deployment>.us-central1.langgraph.app python setup_cron.py
# Cron: 0 0 * * 1 (월 09:00 KST) — .env CRON_SCHEDULE로 변경 가능
```

## 모니터링 (LangSmith — 프로젝트: game event collector)

현재 Actions는 실행 로그와 Summary로 모니터링한다. 아래 LangSmith 추적은 해당 키를 별도로 주입한 환경에서만 동작한다.

- `agent.py`가 `LANGSMITH_API_KEY` 존재 시 `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT=game event collector`로 자동 추적
- `.env`에 `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT=game event collector` 설정 (Cloud에서는 Secrets로 주입)
- 확인: https://smith.langchain.com → Projects → `game event collector` → 각 노드(search/extract/validate/overseas_filter/sheets/calendar) latency, `stats.found/expired/overseas_filtered/valid`, `errors` 추적
- 로컬도 `pip install langsmith` 후 동일 `.env`로 트레이싱 가능

## 무료 티어

- 공개 저장소의 표준 GitHub-hosted runner는 무료이며 현재 워크플로는 유료 larger runner를 사용하지 않는다. [Actions 요금 안내](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- Gemini/Tavily API 비용은 호스팅 비용과 별개이다. 사용하는 모델과 계정의 무료 할당량 및 결제 설정을 확인한다. 고정된 무료 요청 수를 가정하지 않는다.
- 컨퍼런스 검색은 실행당 12쿼리, 6개월 범위가 다음 해에 걸치면 24쿼리(advanced)이다. 수동 실행과 재실행도 API 사용량에 포함된다. 출처별 조회·실패·수집 건수는 `Conference source` 로그에서 확인한다.
- 최신 조건: [Gemini 결제 안내](https://ai.google.dev/gemini-api/docs/billing), [Tavily 요금](https://www.tavily.com/pricing).
