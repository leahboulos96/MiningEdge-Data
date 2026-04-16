"""
Australian Financial Review (AFR) - Mining / Companies news via public RSS.
Note: Full article bodies are paywalled. We collect headline + summary +
link only. Analysts can follow the link for the full article.
"""

from scrapers.news._rss_base import RSSNewsScraper


class AFRNewsScraper(RSSNewsScraper):
    name = "news_afr"

    FEEDS = [
        {"url": "https://www.afr.com/rss/feed.xml", "section": "AFR Latest"},
    ]
    MINING_ONLY = True   # main feed is all-topics; filter for mining keywords


if __name__ == "__main__":
    AFRNewsScraper().execute()
