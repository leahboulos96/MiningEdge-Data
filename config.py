import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# scrape.do proxy (set in .env file)
SCRAPE_DO_TOKEN = os.environ.get("SCRAPE_DO_TOKEN", "")
SCRAPE_DO_BASE = "https://api.scrape.do/"

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubles each retry

# ASX config (set in .env file)
ASX_API_BASE = "https://asx.api.markitdigital.com/asx-research/1.0"
ASX_CDN_BASE = "https://cdn-api.markitdigital.com/apiman-gateway/ASX/asx-research/1.0"
ASX_ACCESS_TOKEN = os.environ.get("ASX_ACCESS_TOKEN", "")
ASX_ANNOUNCEMENTS_COUNT = 50
ASX_RATE_LIMIT_DELAY = 0.5  # seconds between ticker requests

# Default mining tickers (client will provide full list of 150-250)
ASX_TICKERS = [
    "BHP", "RIO", "FMG", "MIN", "S32", "NCM", "NST", "EVN", "OZL", "IGO",
    "SFR", "PLS", "LTR", "AGY", "LYC", "ILU", "ORE", "AVZ", "CXO", "GL1",
    "SYA", "TLG", "NMT", "VUL", "AKE", "DEG", "GOR", "RMS", "CMM", "RED",
    "SLR", "WAF", "PRU", "RSG", "WGX", "TIE", "KAI", "BGL", "MML", "PNR",
    "CRN", "LNR", "AIS", "29M", "ASM", "NHC", "WHC", "YAL", "TIG",
]

# Flask config (set in .env file)
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-to-a-random-secret")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# ICN Gateway config
ICN_GATEWAY_BASE_URL = "https://gateway.icn.org.au"
ICN_COOKIES_FILE = os.path.join(BASE_DIR, "icn_cookies.json")
ICN_SEARCH_KEYWORDS = "mining"
