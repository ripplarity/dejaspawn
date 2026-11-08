import json
import os
import re
import urllib.error
import urllib.request
import uuid

from . import snapshots
from .receipt import sha256_file

API = "https://api.cloudflare.com/client/v4"
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class CFHTTP(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _call(token, method, path, body=None, headers=None):
    h = {"Authorization": "Bearer " + token, **(headers or {})}
    req = urllib.request.Request(API + path, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise CFHTTP(
            e.code,
            f"cloudflare {method} {path} -> HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}",
        )


def zones(token):
    page = 1
    while True:
        d = json.loads(_call(token, "GET", f"/zones?per_page=50&page={page}"))
        for z in d["result"]:
            yield z
        if page >= d.get("result_info", {}).get("total_pages", 1):
            return
        page += 1


def count_records(text):
    return sum(
        1
        for l in text.splitlines()
        if l.strip() and not l.lstrip().startswith((";", "$"))
    )


def _list_as_bind(token, zid):
    lines, page = [], 1
    while True:
        d = json.loads(
            _call(token, "GET", f"/zones/{zid}/dns_records?per_page=100&page={page}")
        )
        for r in d["result"]:
            c = r["content"]
            if r["type"] == "TXT" and not c.startswith('"'):
                c = '"' + c + '"'
            if r["type"] in ("MX", "SRV") and "priority" in r:
                c = f"{r['priority']} {c}"
            lines.append(f"{r['name']}.\t{r.get('ttl', 1)}\tIN\t{r['type']}\t{c}")
        if page >= d.get("result_info", {}).get("total_pages", 1):
            return "\n".join(lines) + ("\n" if lines else "")
        page += 1


def mirror(out="mirror/cloudflare", only=None):
    only = set(only) if only else None
    token = os.environ.get("CF_API_TOKEN")
    items = []  # (zone name, id, text)
    methods = set()
    if token:
        mode = "REAL"
        try:
            for z in zones(token):
                if only is not None and z["name"] not in only:
                    continue
                try:
                    txt = _call(
                        token, "GET", f"/zones/{z['id']}/dns_records/export"
                    ).decode("utf-8")
                    methods.add("export")
                except CFHTTP as e:
                    if e.code != 403:
                        raise
                    txt = _list_as_bind(token, z["id"])
                    methods.add("list")
                items.append((z["name"], z["id"], txt))
        except CFHTTP as e:
            if e.code == 403:
                raise SystemExit(
                    "CF-AUTH-FAILED: HTTP 403 on export and list; token needs "
                    "Zone:DNS:Read (and Zone:Zone:Read). No receipt written."
                )
            raise SystemExit(str(e))
    else:
        mode = "FIXTURE"
        for fn in sorted(os.listdir(FIXTURE_DIR)):
            if fn.endswith(".txt") and (only is None or fn[:-4] in only):
                items.append(
                    (
                        fn[:-4],
                        "fixture",
                        open(os.path.join(FIXTURE_DIR, fn), encoding="utf-8").read(),
                    )
                )
    if only is not None:
        missing = sorted(only - {i[0] for i in items})
        if missing:
            raise SystemExit("zones not found: " + ",".join(missing))
    for name, _z, _t in items:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise SystemExit("unsafe zone name")
    files = []
    zone_ids = {}
    rid, out = snapshots.new_run(out)
    for name, zid, txt in items:
        fp = os.path.join(out, name + ".txt")
        with open(fp, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt)
        zone_ids[name] = zid
        files.append(
            {
                "path": fp.replace("\\", "/"),
                "sha256": sha256_file(fp),
                "count": count_records(txt),
            }
        )
    with open(os.path.join(out, "zones.json"), "w") as f:
        json.dump(zone_ids, f, indent=2)
    snapshots.publish(os.path.dirname(out), rid)
    res = {"mode": mode, "files": files, "run": rid}
    if only is not None:
        res["zones_filter"] = sorted(only)
    if token:
        res["method"] = "+".join(sorted(methods)) or "export"
    return res


def import_zone(zone_id, name, text, dry_run=True, scratch="scratch/cloudflare"):
    """Single code path for restoring a zone. Builds the exact multipart request the API expects;
    dry_run writes that request body to a scratch file instead of sending it."""
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="proxied"\r\n\r\nfalse\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n{text}\r\n--{boundary}--\r\n"
    ).encode()
    path = f"/zones/{zone_id}/dns_records/import"
    if dry_run:
        os.makedirs(scratch, exist_ok=True)
        sp = os.path.join(scratch, name + ".import.txt")
        with open(sp, "wb") as f:
            f.write(f"POST {API}{path}\n".encode() + body)
        return {
            "sent": False,
            "scratch": sp.replace("\\", "/"),
            "records": count_records(text),
        }
    token = os.environ.get("CF_API_TOKEN")
    if not token:
        raise SystemExit("CF_API_TOKEN is not set; use --dry-run")
    try:
        _call(
            token,
            "POST",
            path,
            body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    except CFHTTP as e:
        raise SystemExit(str(e))
    return {"sent": True, "records": count_records(text)}


def restore(src="mirror/cloudflare", dry_run=True, run=None):
    src = snapshots.resolve(src, run) or src
    ids = json.load(open(os.path.join(src, "zones.json")))
    res = {}
    for name, zid in ids.items():
        text = open(os.path.join(src, name + ".txt"), encoding="utf-8").read()
        res[name] = import_zone(zid, name, text, dry_run)
    return {"zones": res, "dry_run": dry_run}
