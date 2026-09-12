"""검색 레이어 — itch.io 단일 (Tavily 제거, 향후 확장용 폴백만 유지)."""
import os
import time
import random
import logging

logger = logging.getLogger(__name__)

# itch.io 단일 — Tavily 16쿼리는 제거, 필요 시 폴백으로만 사용
DEFAULT_QUERIES = []  # 사용 안 함 — itch.io 직접 호출

# Tavily 무료: 1,000회/월
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic")  # basic / advanced


def _tavily_search(query: str) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        resp = client.search(
            query=query,
            max_results=TAVILY_MAX_RESULTS,
            search_depth=TAVILY_SEARCH_DEPTH,
            include_answer=False,
        )
        results = []
        for r in resp.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
                "query": query,
            })
        return results
    except Exception as e:
        logger.warning(f"Tavily search failed for '{query}': {e}")
        return []


def _gemini_grounding_search(query: str) -> list[dict]:
    """Gemini googleSearch grounding fallback (선택). 현재는 placeholder."""
    # gemini grounding은 별도 API 필요하므로 여기서는 빈 결과
    # 필요 시 tools/gemini.py에 grounding tool 추가
    return []


def search_all(queries: list[str] | None = None) -> list[dict]:
    """itch.io 단일 — 미래 접수 + 온라인/한국만. 채팅에서는 queries로 추가 필터."""
    try:
        from tools.itchio import fetch_itchio_jams, filter_future_online
        max_jams = int(os.getenv("ITCHIO_MAX_JAMS", "30"))
        raw = fetch_itchio_jams(max_jams=max_jams)
        filtered = filter_future_online(raw)
        # 채팅 모드: queries가 있으면 제목/설명에 키워드가 포함된 것만 추가 필터
        if queries:
            q_lower = [q.lower() for q in queries]
            # itch.io는 영문이므로, 한국어 쿼리는 매칭이 어려울 수 있어 느슨하게 필터: 하나라도 포함되면 keep
            # 예: "충북대 게임잼" -> itch.io에는 없으므로 0건이 될 수 있음 — 이 경우 필터를 완화하고 전체를 반환하지 않고 0건 반환(정확도 우선)
            # 대신, 쿼리가 itch.io에 매칭되는 것이 없으면 전체 중 상위 5개를 반환하지 않고 빈 결과를 반환하여 "없음"을 명시
            matched = []
            for ev in filtered:
                blob = f"{ev.get('title','')} {ev.get('description','')} {ev.get('source','')}".lower()
                if any(q in blob for q in q_lower) or any(q.split()[0].lower() in blob for q in q_lower if len(q) > 3):
                    matched.append(ev)
            # 매칭이 1건 이상이면 그것만, 없으면 빈 결과 (채팅에서 "해당 조건 없음"으로 표시)
            if matched:
                filtered = matched
                logger.info(f"itch.io chat filter with queries {queries} -> {len(filtered)} matched")
            else:
                logger.info(f"itch.io chat filter with queries {queries} -> no match, returning empty to indicate no results")
                filtered = []

        results = []
        for ev in filtered:
            results.append({
                "title": ev["title"],
                "url": ev["url"],
                "content": f"{ev.get('description','')} | application {ev.get('application_start')}~{ev.get('application_end')} | location {ev.get('location')}",
                "source": ev.get("source", "itch.io"),
                "event": ev,
            })
        logger.info(f"Search done (itch.io): {len(raw)} raw -> {len(filtered)} future online/KR -> {len(results)} results")
        return results
    except Exception as e:
        logger.error(f"itch.io search failed: {e}")
        return []
