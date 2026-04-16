"""Tests for the RSS news base: parsing and mining-keyword filtering.
We don't hit the real internet - we stub .fetch to return canned RSS."""

import pytest
from scrapers.news._rss_base import RSSNewsScraper


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>BHP hits new lithium milestone in WA</title>
  <link>https://example.com/bhp</link>
  <description>Mining giant BHP...</description>
  <pubDate>Mon, 01 Apr 2026 09:00:00 +0000</pubDate>
</item>
<item>
  <title>Celebrity wedding ceremony</title>
  <link>https://example.com/celeb</link>
  <description>Not relevant.</description>
  <pubDate>Mon, 01 Apr 2026 09:05:00 +0000</pubDate>
</item>
<item>
  <title>Nickel prices rise</title>
  <link>https://example.com/nickel</link>
  <description>Commodity report.</description>
  <pubDate>Mon, 01 Apr 2026 09:10:00 +0000</pubDate>
</item>
</channel></rss>
"""


class _Resp:
    def __init__(self, text):
        self.text = text


class StubbedNewsScraper(RSSNewsScraper):
    name = "stub_news"
    FEEDS = [{"url": "http://example.test/feed", "section": "Stub"}]
    MINING_ONLY = True

    def fetch(self, url, **kw):
        return _Resp(SAMPLE_FEED)


def test_mining_filter_keeps_only_relevant(fresh_db):
    s = StubbedNewsScraper()
    articles = s.run()
    titles = [a["title"] for a in articles]
    assert "BHP hits new lithium milestone in WA" in titles
    assert "Nickel prices rise" in titles
    assert "Celebrity wedding ceremony" not in titles


def test_news_persists_through_execute(fresh_db):
    db = fresh_db
    StubbedNewsScraper().execute()
    assert db.count_records(source="stub_news") == 2


def test_mining_only_false_keeps_all(fresh_db):
    class AllThrough(StubbedNewsScraper):
        MINING_ONLY = False
    assert len(AllThrough().run()) == 3
