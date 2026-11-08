import json
import os
import time

import pytest
from cryptography.hazmat.primitives import serialization
from dejaspawn import cli, snapshots, stripe
from dejaspawn.receipt import key_path, keyid_of, pub_raw, verify_receipt
from test_extras import env  # noqa: F401


def _fake_stripe(monkeypatch):
    monkeypatch.setattr(
        stripe,
        "list_all",
        lambda base, key, path, extra=None: iter([{"id": path + str(time.time())}]),
    )


def _dsse():
    return sorted(
        os.path.join("receipts", f)
        for f in os.listdir("receipts")
        if f.endswith("-mirror-stripe.json.dsse.json")
    )


def _verify(path):
    k = serialization.load_pem_private_key(open(key_path(), "rb").read(), password=None)
    return verify_receipt(path, key=pub_raw(k).hex(), expect_keyid=keyid_of(k))


def test_two_mirrors_two_snapshots_both_verify(env, monkeypatch):
    _fake_stripe(monkeypatch)
    assert cli.main(["mirror", "stripe"]) == 0
    time.sleep(1.1)
    assert cli.main(["mirror", "stripe"]) == 0
    runs = snapshots.runs("mirror/stripe")
    assert len(runs) == 2
    assert open("mirror/stripe/latest").read().strip() == runs[-1]
    atts = _dsse()
    assert len(atts) == 2
    for a in atts:
        ok, msgs = _verify(a)
        assert ok, msgs
        assert not any("not on disk" in m for m in msgs)


def test_prune_keeps_latest_and_referenced(env, monkeypatch):
    _fake_stripe(monkeypatch)
    for _ in range(3):
        cli.main(["mirror", "stripe"])
        time.sleep(1.1)
    runs = snapshots.runs("mirror/stripe")
    assert len(runs) == 3
    gone, prot = snapshots.prune("stripe", 1)
    assert gone == [] and set(prot) == set(runs[:2])  # all referenced by receipts
    for f in list(os.listdir("receipts")):
        d = None
        if f.endswith(".json") and not f.endswith("dsse.json"):
            d = json.load(open(os.path.join("receipts", f)))
        if d and runs[0] in json.dumps(d):
            os.remove(os.path.join("receipts", f))
    gone, prot = snapshots.prune("stripe", 1)
    assert gone == [runs[0]] and runs[1] in prot
    for f in os.listdir("receipts"):
        os.remove(os.path.join("receipts", f))
    snapshots.prune("stripe", 1)
    assert snapshots.runs("mirror/stripe") == [runs[2]]
    assert cli.main(["mirror", "prune", "--keep", "1"]) == 0


def test_legacy_migration(env, monkeypatch):
    os.makedirs("mirror/stripe")
    with open("mirror/stripe/customers.jsonl", "w") as f:
        f.write('{"id":"old"}\n')
    assert cli._has_mirror("stripe")  # read path migrates too
    runs = snapshots.runs("mirror/stripe")
    assert len(runs) == 1 and runs[0].startswith("legacy-")
    assert open("mirror/stripe/latest").read().strip() == runs[0]
    assert not os.path.exists("mirror/stripe/customers.jsonl")
    assert os.path.exists(f"mirror/stripe/{runs[0]}/customers.jsonl")
    _fake_stripe(monkeypatch)
    cli.main(["mirror", "stripe"])
    assert len(snapshots.runs("mirror/stripe")) == 2


def test_drill_run_option(env, monkeypatch):
    monkeypatch.setattr("dejaspawn.stripe.reachable", lambda b: False)
    cli.main(["mirror", "cloudflare"])
    first = snapshots.runs("mirror/cloudflare")[0]
    time.sleep(1.1)
    cli.main(["mirror", "cloudflare"])
    assert cli.main(["drill", "--dry-run", "--run", first]) in (0, 3)
    # an unknown run id is reported per platform as NO-MIRROR, not a crash
    assert cli.main(["drill", "--dry-run", "--run", "20000101T000000Z"]) == 0
