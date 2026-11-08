import hashlib
import json
import os
import subprocess
import sys

import pytest
from dejaspawn import cli


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("DEJASPAWN_KEY", str(tmp_path / "k.pem"))
    for k in ("STRIPE_API_KEY", "STRIPE_API_BASE", "CF_API_TOKEN", "GOOGLE_OAUTH_CLIENT_JSON"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("dejaspawn.stripe.reachable", lambda b: False)
    return tmp_path


def _pack(env):
    assert cli.main(["mirror", "workspace"]) == 0
    assert cli.main(["drill", "--dry-run"]) in (0, 3)
    assert cli.main(["evidence"]) == 0
    root = env / "evidence"
    (d,) = list(root.iterdir())
    return d


def test_evidence_pack_verifies(env):
    d = _pack(env)
    man = json.load(open(d / "MANIFEST.json"))
    assert man["files"]
    for f in man["files"]:
        assert hashlib.sha256((d / f["path"]).read_bytes()).hexdigest() == f["sha256"]
    names = {f["path"] for f in man["files"]}
    for n in ("respawn_card.md", "respawn_card.txt", "verify.sh", "verify.cmd",
              "attest_verify.py", "CONTROL_MAP.md", "README.md", "keyid.txt"):
        assert n in names
    shipped = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "dejaspawn", "attest_verify.py")
    assert (d / "attest_verify.py").read_bytes() == open(shipped, "rb").read()
    keyid = (d / "keyid.txt").read_text().strip()
    key = (d / "pubkey.hex").read_text().strip()
    r = subprocess.run(
        [sys.executable, "attest_verify.py", "MANIFEST.json.dsse.json", "--key", key,
         "--expect-keyid", keyid, "--check-subjects", "."],
        cwd=d, capture_output=True, text=True,
    )
    assert "VALID-SIGNATURE" in r.stdout and r.returncode in (0, 5), r.stderr
    st = json.loads(__import__("base64").b64decode(
        json.load(open(d / "MANIFEST.json.dsse.json"))["payload"]))
    assert st["predicateType"] == "https://ripplarity.com/attestation/dejaspawn/evidence/v1"
    bad = subprocess.run(
        [sys.executable, "attest_verify.py", "MANIFEST.json.dsse.json", "--key", key,
         "--expect-keyid", "0" * 64], cwd=d, capture_output=True, text=True)
    assert bad.returncode == 2


def _sh(d, keyid=None):
    e = {k: v for k, v in os.environ.items() if k != "KEYID"}
    if keyid:
        e["KEYID"] = keyid
    return subprocess.run(["sh", "verify.sh"], cwd=d, capture_output=True, text=True, env=e)


def test_verify_script_keyid_required_and_tamper(env):
    d = _pack(env)
    keyid = (d / "keyid.txt").read_text().strip()
    r = _sh(d)
    if r.returncode == 127 or "not found" in r.stderr:
        pytest.skip("no sh")
    assert r.returncode == 2 and "PACK OK" not in r.stdout
    assert "out of band" in r.stderr
    r = _sh(d, keyid)
    assert r.returncode == 0 and "PACK OK" in r.stdout, r.stdout + r.stderr
    r = _sh(d, "0" * 64)
    assert r.returncode == 1 and "PACK OK" not in r.stdout
    (d / "respawn_card.txt").write_text("edited")
    assert _sh(d, keyid).returncode == 1
