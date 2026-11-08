import argparse
import time

from . import cloudflare, github, stripe
from .receipt import verify_receipt, write_receipt


def _fin(cmd, t0, platforms):
    p = write_receipt(cmd, t0, time.time(), platforms)
    print("receipt:", p.replace("\\", "/"))
    return 0


def _has_mirror(name):
    import os

    if name == "stripe":
        return os.path.exists("mirror/stripe/customers.jsonl")
    if name == "cloudflare":
        return os.path.exists("mirror/cloudflare/zones.json")
    d = "mirror/github"
    return os.path.isdir(d) and any(x.endswith(".git") for x in os.listdir(d))


def _drill(a):
    t0 = time.time()
    plats = {}
    steps = (
        ("stripe", lambda: stripe.restore()),
        ("cloudflare", lambda: cloudflare.restore(dry_run=a.dry_run)),
        ("github", lambda: github.fsck_all()),
    )
    for name, fn in steps:
        s = time.time()
        if not _has_mirror(name):
            print(f"{name:11s} NO-MIRROR  run: python -m dejaspawn mirror {name}")
            plats[name] = {
                "mode": "NO-MIRROR",
                "detail": {},
                "seconds": 0,
                "minutes_to_recovery": None,
                "files": [],
            }
            continue
        if name == "stripe":
            base = stripe.restore_base()
            if not stripe.reachable(base):
                print(
                    f"stripe-mock not reachable at {base}; start it with: "
                    "docker run -p 12111:12111 stripe/stripe-mock"
                )
                plats[name] = {
                    "mode": "MOCK-UNAVAILABLE",
                    "detail": {"url": base},
                    "seconds": 0,
                    "minutes_to_recovery": None,
                    "files": [],
                }
                continue
        r = fn()
        secs = time.time() - s
        if name == "stripe":
            mode = r["base_mode"]
        elif name == "cloudflare":
            mode = "DRY-RUN" if a.dry_run else "REAL"
        else:
            mode = "REAL" if r and all(v == "ok" for v in r.values()) else "FAIL"
        plats[name] = {
            "mode": mode,
            "detail": r,
            "seconds": round(secs, 3),
            "minutes_to_recovery": round(secs / 60, 3),
            "files": [],
        }
        print(f"{name:11s} {mode:8s} {secs / 60:7.3f} min  {r}")
    print(f"total       {(time.time() - t0) / 60:7.3f} min")
    rc = _fin("drill", t0, plats)
    return 1 if plats["github"]["mode"] == "FAIL" else rc


def _doctor():
    import os
    import shutil
    import subprocess

    from .receipt import key_path

    def docker_ok():
        if not shutil.which("docker"):
            return False
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0

    base = stripe.restore_base()
    print(f"stripe mirror target: base={stripe.base_url()} label={stripe.label()}")
    checks = [
        ("docker", docker_ok()),
        (f"stripe-mock at {base}", stripe.reachable(base)),
        ("git", bool(shutil.which("git"))),
        ("signing key file (created on first receipt)", os.path.exists(key_path())),
    ]
    for n, ok in checks:
        print(("PASS " if ok else "FAIL ") + n)
    return 0 if all(ok for _, ok in checks) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dejaspawn")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mirror").add_subparsers(dest="platform", required=True)
    m.add_parser("stripe").add_argument("--days", type=int, default=90)
    m.add_parser("cloudflare")
    m.add_parser("github").add_argument("--repo")
    d = sub.add_parser("drill")
    d.add_argument(
        "--dry-run", action="store_true", help="do not send the DNS import to the API"
    )
    v = sub.add_parser("verify")
    v.add_argument("receipt")
    v.add_argument(
        "--key", help="trusted public key (hex or keys.json), from out of band"
    )
    v.add_argument(
        "--expect-keyid", help="pin: signer keyid (sha256 of the raw public key)"
    )
    sub.add_parser("doctor")
    a = ap.parse_args(argv)
    t0 = time.time()
    if a.cmd == "doctor":
        return _doctor()
    if a.cmd == "verify":
        ok, msgs = verify_receipt(a.receipt, key=a.key, expect_keyid=a.expect_keyid)
        for x in msgs:
            print("note:", x)
        print("OK" if ok else "FAIL")
        return 0 if ok else 1
    if a.cmd == "drill":
        return _drill(a)
    if a.platform == "stripe":
        r = stripe.mirror(days=a.days)
    elif a.platform == "cloudflare":
        r = cloudflare.mirror()
    else:
        r = github.mirror(only=a.repo)
    for f in r["files"]:
        print(f"{f['path']}  count={f['count']}  sha256={f['sha256'][:16]}")
    print(f"mode: {r['mode']}")
    return _fin("mirror " + a.platform, t0, {a.platform: r})
