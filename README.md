# Event Collector — 게임 외부행사 자동 수집

매주 월요일 09:00 KST에 itch.io 게임잼과 지정된 공식 출처의 게임 컨퍼런스를 수집해 Google Sheets에 저장.
캘린더에는 사용자가 선택한 행사만 수동 추가한다.

## 고정 수집 출처와 날짜 기준
- 게임잼: 기존 itch.io 수집 및 미래 접수/온라인·국내 필터 유지.
- 컨퍼런스: 넥슨(`nexon.com`), 스마일게이트(`smilegate.com`), NC소프트(`ncsoft.com`), 크래프톤(`krafton.com`), 인벤 게임 컨퍼런스 IGC(`inven.co.kr`), 지스타 G-CON(`gstar.or.kr`). 각 도메인의 하위 도메인 포함.
- Tavily로 출처별 검색 1회(총 6회), 공식 원문을 가져와 Gemini로 추출한다. 외부 도메인 검색 결과는 제외한다.
- 컨퍼런스는 한국 시간 기준 `start_date > 오늘`만 포함한다. 오늘 시작/진행중/과거/취소/날짜 미정 행사는 제외한다. 접수 마감만 지났고 본행사가 미래인 경우는 유지한다.
- 기사 게시일이나 접수일을 행사 시작일로 추정하지 않는다. 타사 행사 참가 기사, IR 컨퍼런스콜, 일반 게임 이벤트는 추출 대상이 아니다.
- `TAVILY_API_KEY`, `GEMINI_API_KEY`가 컨퍼런스 수집에 필요하다. 키 누락이나 출처 실패 시 컨퍼런스 결과가 없을 수 있으며 게임잼 수집은 계속한다.
- 로컬 검증: `python -m unittest discover -s tests -v` (외부 API/시트 쓰기 없이 실행).

## 구조
```
agent.py              # 7노드 LangGraph (search → extract → validate → overseas_filter → dedup → sheets → calendar)
tools/
  gemini.py           # Gemini 3.5-flash-lite rate limiter (4초 간격, 429 지수백오프, fallback flash-lite-latest)
  search.py           # itch.io 게임잼 + 컨퍼런스 결과 병합
  conferences.py      # 공식 출처 6곳 한정 검색/추출 + 미래 시작일 필터
  extractor.py        # httpx+BS4 fetch → Gemini JSON 추출 (배치 4개씩)
  validator.py        # 마감/종료 필터 + 해외 오프라인 필터 (국내 키워드/.kr/온라인 포함 시 유지)
  sheets.py           # Service Account, events 탭 자동 생성 + hash dedup + batchUpdate
  calendar.py         # Service Account, 그룹 캘린더 자동 등록 + eventId dedup + insert
prompts/extract_prompt.txt  # JSON 스키마 + location/해외 표기 규칙
setup_cron.py         # Cron 등록 (CRON_SCHEDULE env로 변경)
```

## 빠른 시작
1. `cp .env.example .env` 후 채우기:
   - `GEMINI_API_KEY` (모델: `gemini-3.5-flash-lite`, fallback `gemini-flash-lite-latest` — 2.5는 신규 사용자 404)
   - `TAVILY_API_KEY` (`tvly-...`, 컨퍼런스 출처별 총 6쿼리)
   - `GOOGLE_SERVICE_ACCOUNT_FILE=game-event-agent-xxx.json` 또는 `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `SHEET_ID` (예: `1dL2n...`), `CALENDAR_ID` (그룹 캘린더 `...@group.calendar.google.com` 또는 `primary`)
2. Google Cloud: Service Account 생성 → Sheets/Calendar/Drive API 활성화 → 해당 시트/캘린더에 `...@...iam.gserviceaccount.com` 편집자 공유 (그룹 캘린더는 SA가 자동 `calendarList.insert`로 등록)
3. `pip install -r requirements.txt` (protobuf 6.33.6 고정)
4. 로컬 테스트: `python -c "from agent import graph; print(graph.invoke({'messages':['test']}))"`  (키 없으면 dry-run)
5. LangGraph Studio: `langgraph dev`
6. Cron 등록: `python setup_cron.py`  (또는 `.env` CRON_SCHEDULE 수정)
7. 시트 확인: 하단 `events` 탭 (헤더: id/title/category/start_date/end_date/deadline/location/url/source/status/discovered_at/calendar_event_id/last_updated)

## 주기 변경
`.env` 한 줄만 수정:
```
CRON_SCHEDULE=0 0 * * *   # 매일
CRON_SCHEDULE=0 0 * * 1,4 # 월/목
```
후 `python setup_cron.py` 재실행 또는 Platform API로 update.

## 동작 규칙
- **컨퍼런스 날짜 필터:** `start_date > today(Asia/Seoul)` 필수. 날짜 미정/진행중/종료/취소 제외, 접수 마감은 별도.
- **해외 필터:** `location`에 `온라인` 포함 → 유지, `오프라인: 해외(미국/일본 등)` + 국내 키워드/`.kr` 없음 → 제외, 빈 location/혼합(오프라인+온라인)은 유지
- **중복:** `sha1(title+start_date+url)` 해시로 Sheets A열/Calendar eventId dedup

## 배포 (LangGraph Cloud)

### GitHub Actions (권장 무료 배치 실행)

`.github/workflows/collect-events.yml`이 매주 월요일 09:00 KST에 실행된다.
GitHub Actions의 **Collect game events → Run workflow**로 수동 실행할 수 있다.
예약 실행은 지연될 수 있으며, 공개 저장소는 60일간 활동이 없으면 예약이 비활성화될 수 있다.

Repository Secrets: `GEMINI_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`(JSON 전체), `SHEET_ID`.
Repository Variables(선택): `SHEET_TAB`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`.
API 키/서비스 계정 파일은 커밋하지 않는다. 기존 서비스 계정에 대상 시트 편집 권한이 필요하다.
Linux 표준 runner에서 `requirements-actions.txt`를 설치하고 테스트 후 수집한다.
Cloud 서버용 gRPC/protobuf 고정 의존성은 배치 환경에서 설치하지 않는다.
동시 실행을 방지하며 최대 20분, 신규 20건으로 제한한다. 결과는 실행 Summary에서 확인한다.
컨퍼런스 출처별 실패/누락은 로그로 확인한다. 수집 0건이 모든 출처의 정상 조회를 보장하지 않는다.
별도 LangGraph Cloud 배포나 `setup_cron.py` 실행은 필요 없다.

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

- `agent.py`가 `LANGSMITH_API_KEY` 존재 시 `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT=game event collector`로 자동 추적
- `.env`에 `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT=game event collector` 설정 (Cloud에서는 Secrets로 주입)
- 확인: https://smith.langchain.com → Projects → `game event collector` → 각 노드(search/extract/validate/overseas_filter/sheets/calendar) latency, `stats.found/expired/overseas_filtered/valid`, `errors` 추적
- 로컬도 `pip install langsmith` 후 동일 `.env`로 트레이싱 가능

## 무료 티어
- Gemini 3.5-flash-lite (free): ~15 RPM / 1,000 RPD — 주 1회 8쿼리 × ~10 Gemini 호출 = 1% 미만
- Sheets: 300/min/project, 60/min/user — `events` 탭 `batchUpdate` 1회
- Calendar: 10,000/min/project, 600/min/user — 그룹 캘린더 자동 등록 후 `events.insert` (0.2초 간격)
