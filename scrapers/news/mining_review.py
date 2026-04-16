"""
The Australian Mining Review - RSS of latest articles.
"""

from scrapers.news._rss_base import RSSNewsScraper


class MiningReviewScraper(RSSNewsScraper):
    name = "news_mining_rev"

    FEEDS = [
        {"url": "https://australianminingreview.com.au/feed/",
         "section": "Australian Mining Review"},
    ]
    MINING_ONLY = False  # whole publication is mining-focused


if __name__ == "__main__":
    MiningReviewScraper().execute()
