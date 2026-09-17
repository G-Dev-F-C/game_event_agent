import unittest
from datetime import date
from unittest.mock import patch

from tools.conferences import CONFERENCE_SOURCES, allowed_url, fetch_conferences
from tools.validator import is_expired
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
        self.assertTrue(is_expired({**base, "status": "cancelled"}, today))
        self.assertTrue(is_expired({**base, "end_date": "2026-09-01"}, today))
        self.assertTrue(is_expired({"category": "conference", "deadline": "2027-01-01"}, today))

    def test_domains(self):
        self.assertTrue(allowed_url("https://ndc.nexon.com/", ("nexon.com",)))
        for url in ("https://nexon.com.evil.com/", "https://evil.com/nexon.com", "file://nexon.com/x"):
            self.assertFalse(allowed_url(url, ("nexon.com",)))

    @patch.dict("os.environ", {"TAVILY_API_KEY": "test"})
    @patch("tools.gemini.generate_json")
    @patch("tools.extractor.fetch_url", return_value="Official conference date: 2099-01-01")
    @patch("tools.search._tavily_search")
    def test_fixed_sources_and_untrusted_results(self, search, fetch, generate):
        def results(query, include_domains):
            return [{"url": "https://" + include_domains[0] + "/event"},
                    {"url": "https://unrelated.example/event"}]
        search.side_effect = results
        generate.return_value = [{"title": "Conference", "category": "conference",
                                  "start_date": "2099-01-01", "url": "https://invented.example"},
                                 {"title": "Old", "category": "conference", "start_date": "2020-01-01"},
                                 {"title": "IR", "category": "other", "start_date": "2099-01-01"}]
        events = fetch_conferences()
        self.assertEqual(search.call_count, 6)
        self.assertEqual(fetch.call_count, 6)
        self.assertEqual({e["source"] for e in events}, {s[0] for s in CONFERENCE_SOURCES})
        self.assertTrue(all("invented" not in e["url"] for e in events))

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
