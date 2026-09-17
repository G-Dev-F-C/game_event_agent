import unittest
from datetime import date, timedelta
from unittest.mock import patch

from tools.conferences import CONFERENCE_SOURCES, allowed_url, fetch_conferences, window_end, parse_official_html, parse_gstar_events, SEOUL
from tools.validator import is_expired, cap_events
from datetime import datetime
from tools.search import search_all
from tools.extractor import extract_events


class ConferenceTests(unittest.TestCase):
    def test_future_dates(self):
        today = date(2026, 9, 17)
        base = {"category": "conference", "start_date": "2026-09-18"}
        self.assertFalse(is_expired({**base, "deadline": "2026-09-01"}, today))
        for start in (None, "invalid", "2026-09-16", "2026-09-17"):
            self.assertTrue(is_expired({**base, "start_date": start}, today))
        self.assertFalse(is_expired({**base, "start_date": "2027-01-10"}, today))
        self.assertFalse(is_expired({**base, "start_date": "2027-03-17"}, today))
        self.assertTrue(is_expired({**base, "start_date": "2027-03-18"}, today))
        self.assertEqual(window_end(date(2026, 8, 31)), date(2027, 2, 28))
        self.assertTrue(is_expired({**base, "status": "cancelled"}, today))
        self.assertTrue(is_expired({**base, "end_date": "2026-09-01"}, today))
        self.assertTrue(is_expired({"category": "conference", "deadline": "2027-01-01"}, today))

    def test_domains(self):
        self.assertTrue(allowed_url("https://ndc.nexon.com/", ("nexon.com",)))
        for url in ("https://nexon.com.evil.com/", "https://evil.com/nexon.com", "file://nexon.com/x"):
            self.assertFalse(allowed_url(url, ("nexon.com",)))

    @patch.dict("os.environ", {"TAVILY_API_KEY": "test"})
    @patch("tools.gemini.generate_json")
    @patch("tools.conferences.fetch_official_page")
    @patch("tools.search._tavily_search")
    def test_fixed_sources_and_untrusted_results(self, search, fetch, generate):
        fetch.return_value = (f"Official conference date {datetime.now(SEOUL).year}", [])
        def results(query, include_domains, **kwargs):
            return [{"url": "https://" + include_domains[0] + "/event"},
                    {"url": "https://unrelated.example/event"}]
        search.side_effect = results
        generate.return_value = [{"title": "Conference", "category": "conference",
                                  "start_date": (datetime.now(SEOUL).date() + timedelta(days=1)).isoformat(), "url": "https://invented.example"},
                                 {"title": "Old", "category": "conference", "start_date": "2020-01-01"},
                                 {"title": "IR", "category": "other", "start_date": "2099-01-01"}]
        events = fetch_conferences()
        today = datetime.now(SEOUL).date()
        self.assertEqual(search.call_count, 12 * (window_end(today).year - today.year + 1))
        self.assertGreaterEqual(fetch.call_count, 6)
        self.assertEqual({e["source"] for e in events}, {s[0] for s in CONFERENCE_SOURCES})
        self.assertTrue(all("invented" not in e["url"] for e in events))

    def test_gstar_banner_and_conference_dates(self):
        html = '<img alt="지스타 2026 - 2026년 11월 19일~22일, 부산 벡스코"><a href="/conference/conf_info.do">About G-CON</a>'
        text, links = parse_official_html(html, "https://www.gstar.or.kr/", ("gstar.or.kr",))
        event = parse_gstar_events(text, "https://www.gstar.or.kr/")[0]
        self.assertEqual((event["start_date"], event["end_date"]), ("2026-11-19", "2026-11-22"))
        self.assertEqual(links, ["https://www.gstar.or.kr/conference/conf_info.do"])
        conference = parse_gstar_events("G-CON 2026 2026. 11 .19(Thu) - 20(Fri) Convention Hall, Bexco", links[0])[0]
        self.assertEqual(conference["end_date"], "2026-11-20")
        self.assertEqual(parse_gstar_events("G-CON 2026 접수 11/19-22", links[0]), [])
        self.assertEqual(parse_gstar_events(text + " 행사 취소", links[0]), [])

    def test_conferences_are_not_capped_by_jams(self):
        events = [{"title": str(i), "category": "jam", "start_date": "2026-09-18"} for i in range(25)]
        conferences = [{"title": str(i), "category": "conference", "start_date": "2026-11-19"} for i in range(25)]
        keep, skipped = cap_events(events + conferences, limit=20)
        self.assertEqual(len(keep), 45)
        self.assertEqual(len(skipped), 5)
        self.assertTrue(all(e["category"] == "jam" for e in skipped))

    @patch("tools.conferences.fetch_conferences")
    @patch("tools.search._search_jams")
    def test_mixed_pipeline(self, jams, conferences):
        jam = {"title": "Jam", "category": "jam", "url": "https://itch.io/jam/a"}
        conference = {"title": "NDC", "category": "conference", "source": "넥슨",
                      "url": "https://ndc.nexon.com", "start_date": "2099-01-01"}
        jams.return_value = [{"event": jam}]
        conferences.return_value = [conference]
        self.assertEqual([e["category"] for e in extract_events(search_all())], ["jam", "conference"])
        self.assertEqual(conference["location"], "")
        conferences.side_effect = RuntimeError("unavailable")
        with self.assertLogs("tools.search", level="ERROR"):
            self.assertEqual(search_all(), [{"event": jam}])


if __name__ == "__main__":
    unittest.main()
