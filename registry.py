"""
Scraper registry. Any new scraper added under scrapers/ only needs to be
imported here once - the dashboard, scheduler, CLI runner and API all pick
it up automatically. Group is used for bulk scheduling (e.g. "tenders",
"news", "asx").
"""

from scrapers.tenders.austender import AusTenderScraper
from scrapers.tenders.wa_tenders import WATendersScraper
from scrapers.tenders.qld_tenders import QLDTendersScraper
from scrapers.tenders.sa_tenders import SATendersScraper
from scrapers.tenders.icn_gateway import ICNGatewayScraper
from scrapers.tenders.icn_workpackages import ICNWorkpackagesScraper
from scrapers.asx.asx_scraper import ASXScraper
from scrapers.news.afr import AFRNewsScraper
from scrapers.news.west_australian import WestAustralianScraper
from scrapers.news.mining_review import MiningReviewScraper
from scrapers.news.business_news import BusinessNewsScraper


# key -> (label, class, default_group)  - default_group is a seed, NOT the
# source of truth at runtime. Actual group membership is read from the DB
# (custom_groups setting) so users can create / rename / delete groups via
# the UI without touching the code.
REGISTRY = {
    "austender":         ("AusTender (Federal)",        AusTenderScraper,       "tenders"),
    "wa_tenders":        ("WA Tenders",                 WATendersScraper,       "tenders"),
    "qld_tenders":       ("QLD QTenders",               QLDTendersScraper,      "tenders"),
    "sa_tenders":        ("SA Tenders",                 SATendersScraper,       "tenders"),
    "icn_gateway":       ("ICN Gateway (Projects)",     ICNGatewayScraper,      "tenders"),
    "icn_workpackages":  ("ICN Gateway (Work Pkgs)",    ICNWorkpackagesScraper, "tenders"),
    "asx_announcements": ("ASX Announcements",          ASXScraper,             "asx"),
    "news_afr":          ("AFR Mining News",            AFRNewsScraper,         "news"),
    "news_west":         ("The West Australian",        WestAustralianScraper,  "news"),
    "news_mining_rev":   ("Australian Mining Review",   MiningReviewScraper,    "news"),
    "news_business":     ("Business News",              BusinessNewsScraper,    "news"),
}


def _default_groups():
    """Seed groups derived from the hardcoded REGISTRY defaults."""
    out = {}
    for key, (_, _, grp) in REGISTRY.items():
        out.setdefault(grp, []).append(key)
    return out


def all_keys():
    return list(REGISTRY.keys())


def groups():
    """Return {group_name: [scraper_key, ...]} from DB-stored custom groups
    if any, otherwise the hardcoded defaults. Unknown scraper keys inside a
    group are filtered out."""
    try:
        import db
        custom = db.get_setting("custom_groups")
    except Exception:
        custom = None
    if not custom:
        return _default_groups()
    out = {}
    for name, keys in custom.items():
        cleaned = [k for k in (keys or []) if k in REGISTRY]
        if cleaned:
            out[name] = cleaned
    return out


def save_group(name, scraper_keys):
    """Create or overwrite a group. Persists to the DB."""
    import db
    name = (name or "").strip()
    if not name:
        raise ValueError("group name required")
    current = db.get_setting("custom_groups") or _default_groups()
    current[name] = [k for k in scraper_keys if k in REGISTRY]
    db.set_setting("custom_groups", current)


def rename_group(old_name, new_name):
    import db
    new_name = (new_name or "").strip()
    if not new_name or old_name == new_name:
        return
    current = db.get_setting("custom_groups") or _default_groups()
    if old_name in current:
        current[new_name] = current.pop(old_name)
        db.set_setting("custom_groups", current)


def delete_group(name):
    import db
    current = db.get_setting("custom_groups") or _default_groups()
    if name in current:
        del current[name]
        db.set_setting("custom_groups", current)


def label(key):
    return REGISTRY[key][0] if key in REGISTRY else key


def cls(key):
    return REGISTRY[key][1]


def group_of(key):
    return REGISTRY[key][2] if key in REGISTRY else ""


def resolve_targets(targets):
    """targets: list that may contain scraper keys or 'group:<name>'. Returns
    a flat list of scraper keys (deduplicated, preserving order)."""
    g = groups()
    out = []
    seen = set()
    for t in targets:
        if isinstance(t, str) and t.startswith("group:"):
            keys = g.get(t.split(":", 1)[1], [])
        else:
            keys = [t]
        for k in keys:
            if k in REGISTRY and k not in seen:
                seen.add(k)
                out.append(k)
    return out
