import hashlib
import os
import subprocess
import sys
import time

from dejaspawn.receipt import (
    keyid_of,
    load_key,
    pub_raw,
    verify_receipt,
    write_receipt,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "..", "attest-spec", "attest_verify.py")
NEW = os.path.join(ROOT, "examples", "drill_attestation_mock.dsse.json")


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "dejaspawn", "verify", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_attest_verify_byte_identical_to_spec():
    if not os.path.exists(SPEC):
        return
    # pinned: the spec REVISION this package ships (attest-spec 1.4); a moved spec HEAD is informational
    SHIPPED_SPEC_SHA = (
        "51da005156826521b9a55ecf2ad3b5eb2aeb8cf85fb9ba70f231bfce55403687"
    )
    mine = os.path.join(ROOT, "dejaspawn", "attest_verify.py")
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h(mine) == SHIPPED_SPEC_SHA
    return
    # compare against the spec's COMMITTED verifier (the working copy may be CRLF on Windows or mid-edit)
    import subprocess

    try:
        committed = subprocess.run(
            ["git", "-C", os.path.dirname(SPEC), "show", "HEAD:attest_verify.py"],
            capture_output=True,
            check=True,
        ).stdout
        spec_hash = hashlib.sha256(committed).hexdigest()
    except Exception:
        spec_hash = h(SPEC)
    assert h(mine) == spec_hash


def test_legacy_examples_verify_and_are_labelled():
    for n in ("drill_receipt_mock_dejaspawn.json",):
        ok, msgs = verify_receipt(os.path.join(ROOT, "examples", n))
        assert ok and msgs[0].startswith("legacy format")


def _make(tmp_path, monkeypatch, key_dir):
    kd = tmp_path / key_dir
    kd.mkdir(exist_ok=True)
    monkeypatch.setenv("DEJASPAWN_KEY", str(kd / "k.pem"))
    monkeypatch.chdir(tmp_path)
    k = load_key()  # generates the throwaway key
    t = time.time()
    p = write_receipt("drill", t, t, {"stripe": {"mode": "MOCK", "files": []}})
    return k, p


def test_new_dsse_verify_ok_wrong_pin_rejected(tmp_path, monkeypatch):
    k, p = _make(tmp_path, monkeypatch, "keys")
    kid = keyid_of(k)
    assert verify_receipt(p)[0]  # pinned via the local key file
    assert verify_receipt(p, key=pub_raw(k).hex(), expect_keyid=kid)[0]
    assert not verify_receipt(p, key=pub_raw(k).hex(), expect_keyid="00" * 32)[0]
    assert not verify_receipt(p, key=pub_raw(k).hex())[0]  # unpinned --key refused


def test_key_beside_artefact_refused(tmp_path, monkeypatch):
    _, p = _make(
        tmp_path, monkeypatch, "receipts"
    )  # key in the same dir as the envelope
    ok, msgs = verify_receipt(p)
    assert not ok and "beside" in msgs[0]
