"""Immutable mirror snapshots: mirror/<platform>/<UTC run id>/ plus a `latest` pointer file.

`latest` is a plain text file (not a symlink, so it works on Windows) holding the run id.
A legacy flat layout (files directly in mirror/<platform>/) is moved into `legacy-<mtime>`
the first time it is seen.
"""

import json
import os
import re
import shutil
import time

RUN_RE = re.compile(r"^(legacy-)?\d{8}T\d{6}Z(-\d+)?$")


def _utc(t):
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t))


def runs(base):
    """Snapshot ids under base, oldest first."""
    if not os.path.isdir(base):
        return []
    ids = [d for d in os.listdir(base) if RUN_RE.match(d) and os.path.isdir(os.path.join(base, d))]
    return sorted(ids, key=lambda i: (i.replace("legacy-", ""), i))


def migrate(base):
    """Move a legacy flat layout into legacy-<mtime>. Returns the new id or None."""
    if not os.path.isdir(base):
        return None
    legacy = [
        e for e in os.listdir(base)
        if e != "latest" and not (RUN_RE.match(e) and os.path.isdir(os.path.join(base, e)))
        and not e.endswith(".tmp")
    ]
    if not legacy:
        return None
    mt = max(os.path.getmtime(os.path.join(base, e)) for e in legacy)
    rid = "legacy-" + _utc(mt)
    n = 1
    while os.path.exists(os.path.join(base, rid)):
        n += 1
        rid = f"legacy-{_utc(mt)}-{n}"
    dest = os.path.join(base, rid)
    os.makedirs(dest)
    for e in legacy:
        shutil.move(os.path.join(base, e), os.path.join(dest, e))
    if not os.path.exists(os.path.join(base, "latest")):
        publish(base, rid)
    return rid


def latest_id(base):
    migrate(base)
    p = os.path.join(base, "latest")
    if not os.path.isfile(p):
        return None
    rid = open(p, encoding="utf-8").read().strip()
    return rid if rid and os.path.isdir(os.path.join(base, rid)) else None


def resolve(base, run=None):
    """Directory of the snapshot to read: `run` if given, else latest. None if absent."""
    rid = run or latest_id(base)
    if not rid:
        return None
    if not RUN_RE.match(rid):
        raise SystemExit(f"bad run id: {rid}")
    d = os.path.join(base, rid)
    if not os.path.isdir(d):
        raise SystemExit(f"no such snapshot: {d}")
    return d


def new_run(base):
    """Create a fresh snapshot dir. Returns (id, dir)."""
    migrate(base)
    os.makedirs(base, exist_ok=True)
    t = _utc(time.time())
    rid, n = t, 1
    while os.path.exists(os.path.join(base, rid)):
        n += 1
        rid = f"{t}-{n}"
    d = os.path.join(base, rid)
    os.makedirs(d)
    return rid, d


def publish(base, rid):
    tmp = os.path.join(base, "latest.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(rid + "\n")
    os.replace(tmp, os.path.join(base, "latest"))


def discard(d):
    shutil.rmtree(d, ignore_errors=True)


def _referenced(platform, receipts="receipts"):
    """Path prefixes named by receipts: set of (run id or None for flat legacy paths)."""
    refs = set()
    if not os.path.isdir(receipts):
        return refs
    pre = f"mirror/{platform}/"
    for fn in os.listdir(receipts):
        if not fn.endswith(".json") or fn.endswith(".dsse.json"):
            continue
        try:
            d = json.load(open(os.path.join(receipts, fn), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in (d.get("platforms") or {}).values():
            for f in p.get("files", []) if isinstance(p, dict) else []:
                n = str(f.get("path", "")).replace("\\", "/")
                if n.startswith(pre):
                    parts = n[len(pre):].split("/")
                    refs.add(parts[0] if len(parts) > 1 and RUN_RE.match(parts[0]) else None)
    return refs


def prune(platform, keep, root="mirror", receipts="receipts"):
    """Delete the oldest snapshots beyond `keep`, never `latest` nor one a receipt references.
    Returns (deleted, kept_protected)."""
    base = os.path.join(root, platform)
    migrate(base)
    ids = runs(base)
    lat = latest_id(base)
    refs = _referenced(platform, receipts)
    excess = ids[: max(0, len(ids) - keep)]
    gone, prot = [], []
    for i in excess:
        if i == lat or i in refs or (i.startswith("legacy-") and None in refs):
            prot.append(i)
            continue
        shutil.rmtree(os.path.join(base, i))
        gone.append(i)
    return gone, prot
