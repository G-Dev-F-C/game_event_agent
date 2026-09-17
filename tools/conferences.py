"""고정된 공식 출처에서 미래 게임 컨퍼런스를 수집한다."""
import logging
import re
from datetime import datetime
from urllib.parse import urlparse, urljoin, urldefrag, parse_qs, urlencode, urlunparse
from dateutil.relativedelta import relativedelta
import httpx
from bs4 import BeautifulSoup

from .validator import SEOUL, _parse_date

logger = logging.getLogger(__name__)

# 하위 도메인도 허용하되 외부 기사/커뮤니티로 검색 범위를 넓히지 않는다.
CONFERENCE_SOURCES = (
    ("넥슨", ("nexon.com",), "넥슨 NDC 게임 개발자 컨퍼런스"),
    ("스마일게이트", ("smilegate.com",), "스마일게이트 게임 개발자 컨퍼런스"),
    ("NC소프트", ("ncsoft.com",), "엔씨소프트 NC NCDP 게임 개발 컨퍼런스"),
    ("크래프톤", ("krafton.com",), "크래프톤 게임 개발 컨퍼런스"),
    ("인벤 게임 컨퍼런스", ("inven.co.kr",), "인벤 게임 컨퍼런스 IGC"),
    ("지스타", ("gstar.or.kr",), "지스타 G-CON 게임 컨퍼런스"),
)

SOURCE_PAGES = {
    "넥슨": ("https://ndc.nexon.com/",),
    "스마일게이트": ("https://newsroom.smilegate.com/",),
    "NC소프트": ("https://about.ncsoft.com/news",),
    "크래프톤": ("https://www.krafton.com/news/press/", "https://blog.krafton.com/"),
    "인벤 게임 컨퍼런스": ("https://igc.inven.co.kr/",),
    "지스타": ("https://www.gstar.or.kr/", "https://www.gstar.or.kr/conference/conf_info.do?tabKind=gcon_tab"),
}


def window_end(today):
    """180일이 아닌 달력 기준 6개월. 말일은 해당 월의 마지막 날로 보정."""
    return today + relativedelta(months=6)


def canonical_page(url):
    """같은 기사의 게임 스킨/모바일 주소 및 단순 페이지 앵커를 합친다."""
    parsed = urlparse(urldefrag(url)[0])
    params = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()
    if (host == "inven.co.kr" or host.endswith(".inven.co.kr")) and (
        parsed.path.rstrip("/") == "/webzine/news" or parsed.path == "/webzine/wznews.php"
    ):
        article = params.get("news") or params.get("idx")
        if article:
            return "https://www.inven.co.kr/webzine/news/?" + urlencode({"news": article[0]})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def is_schedule_page(url, today):
    """행사 자체가 아닌 과거 회차/연사 소개/게임 커뮤니티를 제외한다."""
    parsed = urlparse(url)
    if re.search(r"speaker|presenter|/sessions?/|/community/|last_(?:conf_)?list", parsed.path, re.I):
        return False
    if "speaker" in parsed.query.lower():
        return False
    editions = re.findall(r"(?:NDC|IGC|/)(20\d{2})(?=/|$|&)", parsed.path + "?" + parsed.query, re.I)
    return not editions or max(map(int, editions)) >= today.year


def fetch_official_page(url, domains):
    from .extractor import FETCH_HEADERS, FETCH_TIMEOUT
    # 다른 도메인으로 리다이렉트되는 원문은 사용하지 않는다.
    with httpx.Client(timeout=FETCH_TIMEOUT, headers=FETCH_HEADERS) as client:
        for _ in range(6):
            if not allowed_url(url, domains):
                raise ValueError("Redirect outside official domains")
            response = client.get(url)
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            break
        else:
            raise ValueError("Too many redirects")
    if "html" not in response.headers.get("content-type", ""):
        return "", []
    return parse_official_html(response.text, url, domains)


def parse_official_html(html, url, domains):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("a[href]"):
        target = urldefrag(urljoin(url, anchor["href"]))[0]
        label = anchor.get_text(" ", strip=True) + " " + urlparse(target).path
        if allowed_url(target, domains) and re.search(
            r"컨퍼런스|콘퍼런스|conference|g-con|gcon|ndc|ncdp|igc|전시개요", label, re.I
        ) and not re.search(r"login|inscr|\.pdf(?:\?|$)", target, re.I):
            if target not in links:
                links.append(target)
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    # 메인 일정이 배너 이미지 alt에만 있는 경우도 읽는다.
    for img in soup.select("img[alt]"):
        img.replace_with(" " + img["alt"] + " ")
    return soup.get_text(" ", strip=True), links


def parse_gstar_events(text, url):
    """공식 배너/컨퍼런스 본문의 명시적 날짜만 파싱. 연도를 고정하지 않는다."""
    patterns = (
        ("G-STAR", r"지스타\s*(\d{4})\s*[-–:]\s*\1년\s*(\d{1,2})월\s*(\d{1,2})일\s*[~～–-]\s*(\d{1,2})일[^,]*,\s*부산\s*벡스코", "지스타", "오프라인: 부산 벡스코"),
        ("G-CON", r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\([^)]*\)\s*[-~–]\s*(\d{1,2})\s*\([^)]*\)\s*Convention Hall,\s*Bexco", "지스타 G-CON", "오프라인: 부산 벡스코 컨벤션홀"),
    )
    events = []
    for kind, pattern, title, location in patterns:
        match = re.search(pattern, text, re.I)
        if not match or (kind == "G-CON" and "G-CON" not in text):
            continue
        year, month, start, end = map(int, match.groups())
        try:
            start_date = datetime(year, month, start).date().isoformat()
            end_date = datetime(year, month, end).date().isoformat()
        except ValueError:
            continue
        if re.search(r"취소|cancelled|canceled", text, re.I):
            continue
        events.append({"title": f"{title} {year}", "category": "conference",
                       "start_date": start_date, "end_date": end_date,
                       "location": location, "url": url, "source": "지스타",
                       "status": "upcoming", "relevance_score": 0.9,
                       "description": "공식 행사 안내의 일정 확인", "event_kind": kind})
    return events


def allowed_url(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(
        host == domain or host.endswith("." + domain) for domain in domains
    )


def is_future_conference(event: dict, today=None) -> bool:
    today = today or datetime.now(SEOUL).date()
    start = _parse_date(event.get("start_date"))
    end = _parse_date(event.get("end_date"))
    return bool(
        event.get("category") == "conference"
        and start and today < start <= window_end(today)
        and (not end or end >= start)
        and (event.get("status") or "").lower() not in
        ("cancelled", "closed", "expired", "ongoing")
    )


def fetch_conferences(queries: list[str] | None = None) -> list[dict]:
    from .search import _tavily_search
    from .gemini import generate_json

    today = datetime.now(SEOUL).date()
    until = window_end(today)
    collected = []
    seen_pages = set()
    seen_events = set()
    for source, domains, keywords in CONFERENCE_SOURCES:
        pending = [(url, 0) for url in SOURCE_PAGES[source]]
        seed_pages = {canonical_page(url) for url in SOURCE_PAGES[source]}
        # 연도를 한 쿼리에 묶지 않고 검색해 연말/연초 공지 누락을 줄인다.
        for year in range(today.year, until.year + 1):
            for term in (keywords, f"{source} 컨퍼런스 행사 일정 신청"):
                query = f"{term} {year}"
                if queries:
                    query += " " + " ".join(queries[:3])
                try:
                    results = _tavily_search(query, include_domains=list(domains), max_results=10, search_depth="advanced")
                    pending.extend((r.get("url") or "", 0) for r in results)
                except Exception:
                    logger.exception("Conference search failed: %s", source)
        fetched = failures = accepted = 0
        seen_texts = set()
        for url, depth in pending:
            if not allowed_url(url, domains) or not is_schedule_page(url, today):
                continue
            url = canonical_page(url)
            if url in seen_pages:
                continue
            seen_pages.add(url)
            try:
                # 검색 요약만으로 행사 날짜를 확정하지 않는다.
                page, links = fetch_official_page(url, domains)
                fetched += 1
                if not page:
                    continue
                if depth == 0 and url in seed_pages:
                    pending.extend((link, 1) for link in links)
                if not any(str(year) in page for year in range(today.year, until.year + 1)):
                    continue  # 연도 없는/과거 전용 원문에서 미래 일정을 추측하지 않는다.
                if not re.search(r"컨퍼런스|콘퍼런스|conference|\bNDC\b|\bNCDP\b|\bIGC\b|지스타|G-CON", page, re.I):
                    continue
                if page in seen_texts:
                    continue
                seen_texts.add(page)
                instruction = (
                    f"수집 출처: {source}. 수집 기간: {today.isoformat()} 다음날부터 {until.isoformat()}까지.\n"
                    "아래 원문에서 이 출처가 주최/운영하는 게임 컨퍼런스만 추출하라. "
                    "인벤은 IGC, 지스타는 지스타 본행사(국제게임전시회)와 G-CON을 별개 행사로 포함한다. "
                    "다른 주최 행사에 대한 기사, 단순 참가/후원, 실적발표/IR 컨퍼런스콜, "
                    "게임 출시/인게임 이벤트, 교육과정은 제외한다. 세션/연사별로 행사를 나누지 마라. "
                    "반드시 category=conference. 원문에 연도와 본행사 시작일이 명시된 "
                    "미래 행사만 포함한다. 연도를 현재 연도로 바꾸거나 접수일/기사일을 "
                    "행사일로 추정하지 마라. 날짜 미정, 과거/진행중/취소 행사는 빈 배열. "
                    "접수 마감만 지났더라도 본행사가 미래면 status=upcoming.\n\n"
                )
                parsed = parse_gstar_events(page, url) if source == "지스타" else []
                extracted = parsed or generate_json(instruction + f"공식 URL: {url}\n" + page)
                for event in extracted:
                    if not isinstance(event, dict) or not is_future_conference(event, today):
                        continue
                    if not event.get("title"):
                        continue
                    event = dict(event)
                    # 모델이 생성한 링크 대신 검증한 공식 원문을 보존한다.
                    event.update(source=source, url=url, status="upcoming")
                    if source == "지스타":
                        is_gcon = bool(re.search(r"g[ -]?con|컨퍼런스|콘퍼런스", event["title"], re.I))
                        event["title"] = f"지스타{' G-CON' if is_gcon else ''} {_parse_date(event['start_date']).year}"
                    key = (source, re.sub(r"\W", "", event["title"].lower()), event["start_date"])
                    if key in seen_events:
                        continue
                    seen_events.add(key)
                    collected.append(event)
                    accepted += 1
            except Exception:
                failures += 1
                logger.exception("Conference extraction failed: %s", url)
        logger.info("Conference source %s: fetched=%d failures=%d accepted=%d window=%s..%s", source, fetched, failures, accepted, today, until)
    logger.info("Conferences: %d future events", len(collected))
    return collected
