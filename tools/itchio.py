"""itch.io jam fetcher — 단일 소스, HTML 파싱."""
import re
import logging
import httpx
from bs4 import BeautifulSoup
from datetime import date
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
SEOUL = ZoneInfo("Asia/Seoul")
JAMS_URL = "https://itch.io/jams/upcoming"
JAMS_FALLBACK_URL = "https://itch.io/jams"
FETCH_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GameEventCollector/1.0)",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}

def _parse_itchio_date(s: str) -> str | None:
    s = s.strip()
    if not s:
        return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None

def _fetch_jam_detail(url: str) -> tuple[str | None, str | None]:
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            text = soup.get_text(separator=" | ")
            dates = re.findall(r'2026-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}', text)
            if not dates:
                dates = re.findall(r'2026-\d{2}-\d{2}', text)
            # also try 2027+
            if not dates:
                dates = re.findall(r'202\d-\d{2}-\d{2}', text)
            uniq = []
            seen = set()
            for d in dates:
                norm = _parse_itchio_date(d)
                if norm and norm not in seen:
                    seen.add(norm)
                    uniq.append(norm)
            if len(uniq) >= 2:
                return uniq[0], uniq[1]
            elif len(uniq) == 1:
                return uniq[0], uniq[0]
            return None, None
    except Exception as e:
        logger.warning(f"itch.io detail fetch failed {url}: {e}")
        return None, None

def fetch_itchio_jams(max_jams: int = 30) -> list[dict]:
    events = []
    soup = None
    last_exc = None
    for url in [JAMS_URL, JAMS_FALLBACK_URL]:
        try:
            with httpx.Client(timeout=FETCH_TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                divs = soup.select("div.jam")
                if divs:
                    logger.info(f"itch.io: found {len(divs)} jam divs from {url}")
                    break
        except Exception as e:
            last_exc = e
            logger.warning(f"itch.io fetch failed {url}: {e}")
            continue
    if soup is None or not soup.select("div.jam"):
        logger.error(f"itch.io fetch failed all urls: {last_exc}")
        return []
    jam_divs = soup.select("div.jam")
    for div in jam_divs[:max_jams]:
        try:
            a = div.select_one("h3 a") or div.select_one("a[href*='/jam/']")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if href.startswith("/"):
                href = "https://itch.io" + href
            short = div.select_one("p.short_text")
            desc = short.get_text(strip=True) if short else ""
            hosts = [x.get_text(strip=True) for x in div.select("div.hosted_by a")]
            host_str = ", ".join(hosts[:2])
            countdown = div.select_one("span.date_countdown")
            app_end = _parse_itchio_date(countdown.get_text(strip=True)) if countdown else None
            app_start, app_end_detail = _fetch_jam_detail(href)
            if not app_end:
                app_end = app_end_detail
            start = app_start
            end = app_end_detail or app_end
            ev = {
                "title": title,
                "category": "jam",
                "start_date": start,
                "end_date": end,
                "application_start": app_start,
                "application_end": app_end,
                "deadline": app_end,
                "location": "온라인",
                "url": href,
                "source": "itch.io",
                "status": "upcoming",
                "relevance_score": 0.85,
                "description": f"{desc} Hosted by {host_str}".strip()[:200] if desc else f"Hosted by {host_str}" if host_str else "itch.io Game Jam",
                "is_online": True,
            }
            events.append(ev)
        except Exception as e:
            logger.warning(f"itch.io jam parse failed: {e}")
            continue
    logger.info(f"itch.io: fetched {len(events)} structured jams")
    return events

def filter_future_online(events: list[dict]) -> list[dict]:
    from datetime import datetime
    from tools.validator import _is_domestic, _parse_date
    today = datetime.now(SEOUL).date()
    keep = []
    for ev in events:
        app_start = None
        for k in ("application_start", "deadline", "start_date"):
            v = ev.get(k)
            if v:
                try:
                    d = _parse_date(v)
                    if d:
                        app_start = d
                        break
                except:
                    pass
        if not app_start:
            continue
        if app_start <= today:
            continue
        loc = ev.get("location") or ""
        if "온라인" in loc or ev.get("is_online"):
            keep.append(ev)
        elif _is_domestic(ev):
            keep.append(ev)
    logger.info(f"itch.io filter: {len(events)} -> {len(keep)} (future online/KR)")
    return keep
