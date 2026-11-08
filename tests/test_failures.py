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
    assert open("mirror/stripe/customers.jsonl").read() == '{"id":"old"}\n'
    assert not os.path.exists("mirror/stripe.tmp")
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
