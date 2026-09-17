"""고정된 공식 출처에서 미래 게임 컨퍼런스를 수집한다."""
import logging
import os
from datetime import datetime
from urllib.parse import urlparse

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
        and start and start > today
        and (not end or end >= start)
        and (event.get("status") or "").lower() not in
        ("cancelled", "closed", "expired", "ongoing")
    )


def fetch_conferences(queries: list[str] | None = None) -> list[dict]:
    from .search import _tavily_search
    from .extractor import fetch_url
    from .gemini import generate_json

    if not os.getenv("TAVILY_API_KEY"):
        logger.warning("Conference collection skipped: TAVILY_API_KEY is missing")
        return []
    today = datetime.now(SEOUL).date()
    collected = []
    seen_pages = set()
    seen_events = set()
    for source, domains, keywords in CONFERENCE_SOURCES:
        query = f"{keywords} {today.year} {today.year + 1} 개최 일정"
        if queries:
            query += " " + " ".join(queries[:3])
        try:
            results = _tavily_search(query, include_domains=list(domains))
        except Exception:
            logger.exception("Conference search failed: %s", source)
            continue
        for result in results:
            url = result.get("url") or ""
            if not allowed_url(url, domains) or url in seen_pages:
                continue
            seen_pages.add(url)
            try:
                # 검색 요약만으로 행사 날짜를 확정하지 않는다.
                page = fetch_url(url)
                if not page:
                    continue
                instruction = (
                    f"수집 출처: {source}. 기준일: {today.isoformat()}.\n"
                    "아래 원문에서 이 출처가 주최/운영하는 게임 컨퍼런스만 추출하라. "
                    "인벤은 IGC, 지스타는 G-CON 컨퍼런스만 포함한다. "
                    "다른 주최 행사에 대한 기사, 단순 참가/후원, 실적발표/IR 컨퍼런스콜, "
                    "게임 출시/인게임 이벤트, 교육과정, 전시회 자체는 제외한다. "
                    "반드시 category=conference. 원문에 연도와 본행사 시작일이 명시된 "
                    "미래 행사만 포함한다. 연도를 현재 연도로 바꾸거나 접수일/기사일을 "
                    "행사일로 추정하지 마라. 날짜 미정, 과거/진행중/취소 행사는 빈 배열. "
                    "접수 마감만 지났더라도 본행사가 미래면 status=upcoming.\n\n"
                )
                for event in generate_json(instruction + page):
                    if not isinstance(event, dict) or not is_future_conference(event, today):
                        continue
                    if not event.get("title"):
                        continue
                    event = dict(event)
                    # 모델이 생성한 링크 대신 검증한 공식 원문을 보존한다.
                    event.update(source=source, url=url, status="upcoming")
                    key = (source, event["title"].strip().lower(), event["start_date"])
                    if key in seen_events:
                        continue
                    seen_events.add(key)
                    collected.append(event)
            except Exception:
                logger.exception("Conference extraction failed: %s", url)
    logger.info("Conferences: %d future events", len(collected))
    return collected
