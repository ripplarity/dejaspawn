import json
import os

import pytest
from dejaspawn import card, cli, exitscore, schedule, workspace

RECEIPT = {
    "ended": "2026-11-08T20:00:00Z",
    "seconds": 1.5,
    "platforms": {
        "stripe": {"mode": "MOCK", "minutes_to_recovery": 0.002,
                   "detail": {"restored": {"customers": 2, "invoices": 3}}},
        "cloudflare": {"mode": "DRY-RUN", "minutes_to_recovery": 0.0,
                       "detail": {"zones": {"a.test": {"records": 5}}}},
        "github": {"mode": "NO-MIRROR", "minutes_to_recovery": None, "detail": {}},
    },
    "pubkey_sha256": "ab" * 32,
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("DEJASPAWN_KEY", str(tmp_path / "k.pem"))
    for k in ("STRIPE_API_KEY", "STRIPE_API_BASE", "CF_API_TOKEN", "GOOGLE_OAUTH_CLIENT_JSON"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_card_render():
    md, txt = card.render(RECEIPT)
    assert "Drill mode: **MOCK**" in md and "customers=2" in md and "dns_records=5" in md
    assert "not available via the API" in md and "keyid `" + "ab" * 32 in md
    assert "RESPAWN CARD 2026-11-08" in txt


def test_drill_card_fresh(env, monkeypatch):
    monkeypatch.setattr("dejaspawn.stripe.reachable", lambda b: False)
    assert cli.main(["drill", "--card", "--dry-run"]) == 0
    cards = os.listdir("cards")
    assert any(c.endswith(".md") for c in cards) and any(c.endswith(".txt") for c in cards)
    assert "NO-MIRROR" in open(os.path.join("cards", [c for c in cards if c.endswith(".md")][0])).read()


def test_schedule_dry_run(env, capsys):
    assert cli.main(["drill", "--schedule", "monthly", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dejaspawn drill --card --dry-run" in out
    assert cli.main(["drill", "--unschedule", "--dry-run"]) == 0
    k, line = schedule.plan("weekly", windows=False, cwd="/x")
    assert k == "cron" and line.startswith("0 3 * * 1 ")
    k, args = schedule.plan("monthly", windows=True, cwd="C:/x")
    assert args[:2] == ["schtasks", "/Create"] and "MONTHLY" in args


def test_workspace_fixture_and_verify(env, capsys):
    assert cli.main(["mirror", "workspace"]) == 0
    assert "mode: FIXTURE" in capsys.readouterr().out
    ok, d = workspace.verify()
    assert ok and d["count"] == 5 and d["mode"] == "VERIFY-ONLY"
    victim = next(os.path.join(r, f) for r, _, fs in os.walk("mirror/workspace") for f in fs if f.endswith(".eml"))
    open(victim, "ab").write(b"x")
    ok, d = workspace.verify()
    assert not ok and len(d["bad"]) == 1


def test_drill_includes_workspace_verify_only(env, monkeypatch):
    monkeypatch.setattr("dejaspawn.stripe.reachable", lambda b: False)
    cli.main(["mirror", "workspace"])
    assert cli.main(["drill", "--dry-run"]) == 0
    r = json.load(open(os.path.join("receipts", sorted(f for f in os.listdir("receipts") if f.endswith("-drill.json"))[-1])))
    assert r["platforms"]["workspace"]["mode"] == "VERIFY-ONLY"


def test_exitscore(env, capsys):
    assert cli.main(["exitscore"]) == 0
    d = json.load(open("exitscore.json"))
    for p in d["platforms"].values():
        for c in p["classes"].values():
            assert c["url"].startswith("https://")
    assert set(exitscore.CLASSES) >= {c for p in d["platforms"].values() for c in p["classes"]}


def test_check_sources_and_unverified(env, capsys):
    r = exitscore.check_sources(fetch=lambda u: u.endswith("/list"))
    assert len(r) == len(exitscore.TABLE) and any(r.values()) and not all(r.values())
    out = capsys.readouterr().out
    assert "unreachable" in out and "reachable" in out
    d = exitscore.compute()
    assert d["platforms"]["cloudflare"]["classes"]["certs"]["level"] == "UNVERIFIED"


def test_unexportable_urls_are_checked_sources():
    import re

    from dejaspawn.exitscore import TABLE

    urls = set(re.findall(r"https://\S+?(?=\s\|)", open("UNEXPORTABLE.md", encoding="utf-8").read()))
    assert urls and urls <= {t[3] for t in TABLE}
