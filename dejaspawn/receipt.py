"""Attestations: DSSE envelope over an in-toto Statement v1 (attest-spec v1), plus a legacy receipt file.

New runs write `<receipt>.json` (legacy format, kept one release) and `<receipt>.json.dsse.json`.
`verify` routes DSSE envelopes through the byte-identical attest_verify.py with a pinned keyid.
"""

import base64
import hashlib
import json
import os
import platform
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from . import __version__

VERSION = "dejaspawn-receipt-1"  # legacy receipt id
PAYLOAD_TYPE = "application/vnd.in-toto+json"
PREDICATE_TYPE = "https://ripplarity.com/attestation/dejaspawn/mirror/v1"


def key_path():
    if os.environ.get("DEJASPAWN_KEY"):
        return os.environ["DEJASPAWN_KEY"]
    return os.path.join(os.path.expanduser("~"), ".dejaspawn", "dejaspawn_ed25519.pem")


def load_key():
    p = key_path()
    if os.path.exists(p):
        return serialization.load_pem_private_key(open(p, "rb").read(), password=None)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    k = Ed25519PrivateKey.generate()
    with open(p, "wb") as f:
        f.write(
            k.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return k


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def pub_raw(key):
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def keyid_of(key):
    return hashlib.sha256(pub_raw(key)).hexdigest()


def pae(payload_type, payload):
    t = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(t), t, len(payload), payload)


def make_envelope(stmt, key):
    payload = json.dumps(
        stmt, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    sig = key.sign(pae(PAYLOAD_TYPE, payload))
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode(),
        "signatures": [{"keyid": keyid_of(key), "sig": base64.b64encode(sig).decode()}],
    }


def run_mode(platforms):
    modes = [str(p.get("mode", "")) for p in platforms.values()]
    if any(m.startswith("REAL") for m in modes):
        return "REAL"
    if "MOCK" in modes:
        return "MOCK"
    if "DRY-RUN" in modes:
        return "DRY-RUN"
    return "FIXTURE"


def _utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def write_receipt(command, started, ended, platforms, out_dir="receipts"):
    """platforms: {name: {"mode": "REAL|MOCK|FIXTURE", "files": [{"path","sha256","count"}], ...}}
    Returns the path of the DSSE envelope."""
    key = load_key()
    pub = pub_raw(key)
    payload = {
        "version": VERSION,
        "command": command,
        "started": _utc(started),
        "ended": _utc(ended),
        "seconds": round(ended - started, 3),
        "platforms": platforms,
        "pubkey": base64.b64encode(pub).decode(),
        "pubkey_sha256": hashlib.sha256(pub).hexdigest(),
    }
    payload["signature"] = base64.b64encode(key.sign(_canon(payload))).decode()
    os.makedirs(out_dir, exist_ok=True)
    name = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ended))
        + "-"
        + command.replace(" ", "-")
        + ".json"
    )
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    # subjects = mirrored files with sha256, plus the legacy receipt file itself (never empty)
    subjects, seen = [], set()
    for p in platforms.values():
        for f in p.get("files", []):
            n = f.get("path", "").replace("\\", "/")
            if f.get("sha256") and len(f["sha256"]) == 64 and n not in seen:
                seen.add(n)
                subjects.append({"name": n, "digest": {"sha256": f["sha256"]}})
    subjects.append(
        {"name": path.replace("\\", "/"), "digest": {"sha256": sha256_file(path)}}
    )
    stmt = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "producer": {"tool": "dejaspawn", "version": __version__},
            "started": _utc(started),
            "ended": _utc(ended),
            "environment": {
                "host_os": platform.system().lower(),
                "run_mode": run_mode(platforms),
            },
            "command": command,
            "seconds": round(ended - started, 3),
            "platforms": platforms,
        },
    }
    dpath = path + ".dsse.json"
    with open(dpath, "w", encoding="utf-8") as f:
        json.dump(make_envelope(stmt, key), f, indent=2)
        f.write("\n")
    return dpath


def _verify_dsse(path, check_files, key, expect_keyid):
    import contextlib
    import io

    from . import attest_verify

    if key:
        if not expect_keyid:
            return False, [
                "--key given without --expect-keyid: refusing to trust an unpinned key"
            ]
        keyarg, pin, src = key, expect_keyid, "--expect-keyid (out of band)"
    else:
        lp = key_path()
        if not os.path.exists(lp):
            return False, [
                "no trusted key: pass --key HEX --expect-keyid ID, or provide the signing key file"
            ]
        if os.path.dirname(os.path.abspath(lp)) == os.path.dirname(
            os.path.abspath(path)
        ):
            return False, [
                "signing key file sits beside the artefact; refusing to trust it"
            ]
        k = serialization.load_pem_private_key(open(lp, "rb").read(), password=None)
        keyarg = pub_raw(k).hex()
        pin = expect_keyid or keyid_of(k)
        src = ("--expect-keyid; key from " if expect_keyid else "keyid of ") + (
            "local signing key file " + lp
        )
    msgs = [f"trusted keyid {pin} (source: {src})"]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = attest_verify.main([path, "--key", keyarg, "--expect-keyid", pin])
    msgs += [x for x in (out.getvalue() + err.getvalue()).splitlines() if x]
    if rc == 5:
        # the byte-identical spec verifier does not list our predicateType yet (signature already
        # checked); check the mandatory predicate fields here instead
        st = json.loads(
            base64.b64decode(json.load(open(path, encoding="utf-8"))["payload"])
        )
        if st.get(
            "predicateType"
        ) == PREDICATE_TYPE and not attest_verify.check_mandatory(st.get("predicate")):
            msgs.append(
                f"VALID {PREDICATE_TYPE} (mandatory fields checked by dejaspawn)"
            )
            rc = 0
    if rc != 0:
        return False, msgs
    ok = True
    if check_files:
        d = json.load(open(path, encoding="utf-8"))
        st = json.loads(base64.b64decode(d["payload"]))
        for s in st["subject"]:
            n = s["name"]
            if not os.path.isfile(n):
                msgs.append(f"{n} not on disk (signature still valid)")
            elif sha256_file(n) != s["digest"]["sha256"]:
                msgs.append(f"{n} changed since attestation")
                ok = False
    return ok, msgs


def verify_receipt(path, check_files=True, key=None, expect_keyid=None):
    """Returns (ok, messages). DSSE envelopes go through attest_verify with a pinned keyid;
    older receipts verify as 'legacy format'."""
    d = json.load(open(path, encoding="utf-8"))
    if "payloadType" in d:
        return _verify_dsse(path, check_files, key, expect_keyid)
    ok, msgs = _verify_legacy(path, check_files)
    return ok, [f"legacy format ({d.get('version')})"] + msgs


def _verify_legacy(path, check_files=True):
    msgs = []
    d = json.load(open(path, encoding="utf-8"))
    sig = base64.b64decode(d.pop("signature", ""))
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(d["pubkey"]))
        pub.verify(sig, _canon(d))
    except Exception:
        return False, ["signature INVALID"]
    ok = True
    if check_files:
        for name, p in d.get("platforms", {}).items():
            for f in p.get("files", []):
                if not os.path.exists(f["path"]):
                    msgs.append(
                        f"{name}: {f['path']} not on disk (signature still valid)"
                    )
                elif (
                    f.get("sha256")
                    and os.path.isfile(f["path"])
                    and sha256_file(f["path"]) != f["sha256"]
                ):
                    msgs.append(f"{name}: {f['path']} changed since receipt")
                    ok = False
    return ok, msgs
