"""Tests that the scraper registry stays in sync and groups resolve."""

import registry


def test_all_registered():
    expected_min = {
        "austender", "wa_tenders", "qld_tenders", "sa_tenders",
        "icn_gateway", "icn_workpackages", "asx_announcements",
        "news_afr", "news_west", "news_mining_rev", "news_business",
    }
    assert expected_min.issubset(set(registry.all_keys()))


def test_groups_cover_every_key():
    flat = {k for keys in registry.groups().values() for k in keys}
    assert flat == set(registry.all_keys())


def test_resolve_group_target():
    keys = registry.resolve_targets(["group:news"])
    assert "news_afr" in keys
    assert "austender" not in keys


def test_resolve_mixed_and_dedup():
    keys = registry.resolve_targets(
        ["group:tenders", "austender", "news_afr"])
    assert keys.count("austender") == 1  # dedup
    assert "news_afr" in keys


def test_labels_and_classes():
    for k in registry.all_keys():
        assert registry.label(k)
        cls = registry.cls(k)
        assert hasattr(cls, "run")
        assert hasattr(cls, "execute")


def test_unknown_target_ignored():
    assert registry.resolve_targets(["does_not_exist"]) == []
