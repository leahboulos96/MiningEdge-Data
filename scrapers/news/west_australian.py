"""
The West Australian - mining-filtered news via public RSS.
Filters feed output by mining keywords since the feed covers all business news.
"""

from scrapers.news._rss_base import RSSNewsScraper


class WestAustralianScraper(RSSNewsScraper):
    name = "news_west"

    FEEDS = [
        {"url": "https://thewest.com.au/business/rss", "section": "West Business"},
    ]
    MINING_ONLY = True


if __name__ == "__main__":
    WestAustralianScraper().execute()
