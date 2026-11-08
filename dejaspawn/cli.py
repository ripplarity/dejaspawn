import argparse
import time

from . import cloudflare, github, snapshots, stripe
from .receipt import verify_receipt, write_receipt


def _fin(cmd, t0, platforms):
    p = write_receipt(cmd, t0, time.time(), platforms)
    print("receipt:", p.replace("\\", "/"))
    _fin.last = p
    return 0


def _has_mirror(name, run=None):
    import os

    try:
        d = snapshots.resolve("mirror/" + name, run)
    except SystemExit:  # that run id does not exist for this platform
        return False
    if not d:
        return False
    if name == "stripe":
        return os.path.exists(os.path.join(d, "customers.jsonl"))
    if name == "cloudflare":
        return os.path.exists(os.path.join(d, "zones.json"))
    if name == "workspace":
        return os.path.isdir(d)
    return any(x.endswith(".git") for x in os.listdir(d))


def _prune(keep):
    for p in ("stripe", "cloudflare", "github", "workspace"):
        gone, prot = snapshots.prune(p, keep)
        print(f"{p}: deleted {len(gone)} {gone}; protected {prot if prot else '[]'}")
    return 0


def _ws_verify(run=None):
    from . import workspace

    ok, d = workspace.verify(run=run)
    return dict(d, ok=ok)


def _drill(a):
    t0 = time.time()
    plats = {}
    steps = (
        ("stripe", lambda: stripe.restore(run=a.run)),
        ("cloudflare", lambda: cloudflare.restore(dry_run=a.dry_run, run=a.run)),
        ("github", lambda: github.fsck_all(run=a.run)),
    ) + (
        (("workspace", lambda: _ws_verify(a.run)),)
        if _has_mirror("workspace", a.run)
        else ()
    )
    for name, fn in steps:
        s = time.time()
        if not _has_mirror(name, a.run):
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
        try:
            r = fn()
        except (Exception, SystemExit) as e:
            r = {"error": stripe._reason(e), "failed": {"all": 1}, "restored": {}, "status": "PARTIAL"}
        secs = time.time() - s
        if name == "stripe":
            mode = r.get("base_mode") or "ERROR"
        elif name == "cloudflare":
            mode = "DRY-RUN" if a.dry_run else "REAL"
        elif name == "workspace":
            mode = "VERIFY-ONLY" if r.get("ok") else "FAIL"
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
    if a.card:
        from . import card

        lp = _fin.last[: -len(".dsse.json")]
        print("card:", card.write_card(lp, _fin.last).replace("\\", "/"))
    partial = any(
        isinstance(p.get("detail"), dict) and p["detail"].get("status") == "PARTIAL"
        for p in plats.values()
    )
    bad = plats["github"]["mode"] == "FAIL" or plats.get("workspace", {}).get("mode") == "FAIL"
    if bad:
        return 1
    return 3 if partial else rc


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
    m.add_parser("cloudflare").add_argument(
        "--zones", help="comma-separated exact zone names; only these are mirrored"
    )
    m.add_parser("workspace")
    m.add_parser("github").add_argument("--repo")
    m.add_parser("prune").add_argument("--keep", type=int, required=True)
    d = sub.add_parser("drill")
    d.add_argument(
        "--dry-run", action="store_true", help="do not send the DNS import to the API"
    )
    d.add_argument("--card", action="store_true", help="write cards/<date>.md and .txt")
    d.add_argument("--run", help="snapshot run id to drill (default: latest)")
    d.add_argument("--schedule", choices=["monthly", "weekly"])
    d.add_argument("--unschedule", action="store_true")
    sub.add_parser("exitscore").add_argument("--check-sources", action="store_true")
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
    if a.cmd == "exitscore":
        from . import exitscore

        return exitscore.run(check=a.check_sources)
    if a.cmd == "drill":
        if a.schedule or a.unschedule:
            from . import schedule

            if a.unschedule:
                return schedule.uninstall(dry_run=a.dry_run)
            return schedule.install(a.schedule, dry_run=a.dry_run)
        return _drill(a)
    if a.platform == "prune":
        if a.keep < 1:
            raise SystemExit("--keep must be >= 1")
        return _prune(a.keep)
    if a.platform == "stripe":
        r = stripe.mirror(days=a.days)
    elif a.platform == "cloudflare":
        r = cloudflare.mirror(
            only=[z for z in a.zones.split(",") if z] if a.zones else None
        )
    elif a.platform == "workspace":
        from . import workspace

        r = workspace.mirror()
    else:
        r = github.mirror(only=a.repo)
    for f in r["files"]:
        print(f"{f['path']}  count={f['count']}  sha256={f['sha256'][:16]}")
    print(f"mode: {r['mode']}")
    return _fin("mirror " + a.platform, t0, {a.platform: r})
