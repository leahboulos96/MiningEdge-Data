"""
Business News (businessnews.com.au) - WA business publication.
We pull the main RSS feed and filter for mining-related articles.
"""

from scrapers.news._rss_base import RSSNewsScraper


class BusinessNewsScraper(RSSNewsScraper):
    name = "news_business"

    FEEDS = [
        {"url": "https://www.businessnews.com.au/rssfeed/latest.rss",
         "section": "Business News"},
    ]
    MINING_ONLY = True


if __name__ == "__main__":
    BusinessNewsScraper().execute()
