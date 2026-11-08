import io
import json
import os
import urllib.error

import pytest
from dejaspawn import cli, cloudflare, stripe
from dejaspawn.receipt import verify_receipt


def _err(code):
    def f(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, code, "x", {}, io.BytesIO(b'{"error":"api_key_expired"}')
        )

    return f


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEJASPAWN_KEY", str(tmp_path / "k.pem"))
    for k in (
        "STRIPE_API_BASE",
        "STRIPE_API_KEY",
        "CF_API_TOKEN",
        "DEJASPAWN_ALLOW_LIVE",
    ):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _receipts():
    if not os.path.isdir("receipts"):
        return []
    return [os.path.join("receipts", f) for f in os.listdir("receipts")]


def test_stripe_error_leaves_old_mirror_and_no_receipt(env, monkeypatch):
    os.makedirs("mirror/stripe")
    open("mirror/stripe/customers.jsonl", "w").write('{"id":"old"}\n')
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_000")
    monkeypatch.setattr("urllib.request.urlopen", _err(401))
    with pytest.raises(SystemExit):
        cli.main(["mirror", "stripe"])
    old = os.path.join("mirror/stripe", open("mirror/stripe/latest").read().strip())
    assert open(old + "/customers.jsonl").read() == '{"id":"old"}\n'
    assert (
        len(os.listdir("mirror/stripe")) == 2
    )  # legacy snapshot + latest; failed run discarded
    for r in _receipts():
        assert verify_receipt(r)[0]


def test_labels_and_live_refusal(env, monkeypatch):
    assert stripe.label() == "MOCK" and stripe.base_url() == stripe.DEFAULT_BASE
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_000")
    assert stripe.base_url() == "https://api.stripe.com"
    assert stripe.label() == "REAL-TEST"
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_000")
    with pytest.raises(SystemExit):
        stripe.mirror()


def test_cf_fallback_to_list(env, monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "t")

    def call(token, method, path, body=None, headers=None):
        if path.startswith("/zones?"):
            return json.dumps(
                {
                    "result": [{"id": "z1", "name": "example.com"}],
                    "result_info": {"total_pages": 1},
                }
            ).encode()
        if path.endswith("/export"):
            raise cloudflare.CFHTTP(403, "403")
        return json.dumps(
            {
                "result": [
                    {"name": "example.com", "type": "A", "content": "1.2.3.4", "ttl": 1}
                ],
                "result_info": {"total_pages": 1},
            }
        ).encode()

    monkeypatch.setattr(cloudflare, "_call", call)
    assert cli.main(["mirror", "cloudflare"]) == 0
    rc = _receipts()
    assert json.load(open(rc[0]))["platforms"]["cloudflare"]["method"] == "list"
    assert verify_receipt(rc[0])[0]


def test_cf_both_403_no_receipt(env, monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "t")

    def call(token, method, path, body=None, headers=None):
        raise cloudflare.CFHTTP(403, "403")

    monkeypatch.setattr(cloudflare, "_call", call)
    with pytest.raises(SystemExit) as e:
        cli.main(["mirror", "cloudflare"])
    assert "Zone:DNS:Read" in str(e.value)
    assert _receipts() == []


def _mk_mirror():
    os.makedirs("mirror/stripe")
    rows = {
        "customers": [{"id": "cus_A", "email": "a@x.test"}],
        "products": [{"id": "prod_A", "name": "P"}],
        "prices": [
            {"id": "price_A", "product": "prod_A", "currency": "usd", "unit_amount": 5}
        ],
        "subscriptions": [
            {
                "id": "sub_1",
                "customer": "cus_A",
                "status": "trialing",
                "collection_method": "charge_automatically",
                "trial_end": 4102444800,
                "items": {"data": [{"price": {"id": "price_A"}}]},
            },
            {
                "id": "sub_2",
                "customer": "cus_A",
                "status": "active",
                "trial_end": 1,
                "items": {"data": [{"price": {"id": "price_A"}}]},
            },
        ],
    }
    for k, v in rows.items():
        with open(f"mirror/stripe/{k}.jsonl", "w") as f:
            f.write("\n".join(json.dumps(x) for x in v) + "\n")


def test_drill_partial_on_subscription_400(env, monkeypatch, capsys):
    _mk_mirror()
    sent = []

    def fake(req, timeout=None):
        if isinstance(req, str):
            raise urllib.error.HTTPError(req, 404, "x", {}, io.BytesIO(b"{}"))
        body = (req.data or b"").decode()
        if req.full_url.endswith("/v1/subscriptions"):
            sent.append(body)
            if len(sent) == 2:
                raise urllib.error.HTTPError(
                    req.full_url,
                    400,
                    "x",
                    {},
                    io.BytesIO(
                        b'{"error":{"code":"resource_missing","message":"no payment method"}}'
                    ),
                )
            payload = {"id": "sub_new", "status": "trialing"}
        else:
            payload = {"id": "new_" + req.full_url.rsplit("/", 1)[-1], "data": []}

        class R:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return R()

    monkeypatch.setattr("urllib.request.urlopen", fake)
    rc = cli.main(["drill", "--dry-run", "--card"])
    assert rc == 3
    assert "trial_end=4102444800" in sent[0] and "default_incomplete" in sent[0]
    assert "trial_end" not in sent[1]
    assert len(_receipts()) == 2
    card = open(
        [os.path.join("cards", f) for f in os.listdir("cards") if f.endswith(".md")][0]
    ).read()
    assert "PARTIAL" in card and "failed: HTTP 400 resource_missing" in card
    assert "Unrecoverable by design" in card and "not available via the API" in card


def test_cloudflare_zones_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    fx = sorted(
        f[:-4] for f in os.listdir(cloudflare.FIXTURE_DIR) if f.endswith(".txt")
    )
    keep = fx[0]
    r = cloudflare.mirror(only=[keep])
    assert [f["path"].split("/")[-1] for f in r["files"]] == [keep + ".txt"]
    assert r["zones_filter"] == [keep]
    assert list(json.load(open(os.path.join("mirror/cloudflare", open("mirror/cloudflare/latest").read().strip(), "zones.json")))) == [keep]
    with pytest.raises(SystemExit):
        cloudflare.mirror(only=["nope.invalid"])
