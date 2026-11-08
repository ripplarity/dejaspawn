"""Google Workspace read-only mirror (step 1): Gmail raw .eml + Drive files, with a sha256 manifest.

Credentials: GOOGLE_OAUTH_CLIENT_JSON (path to an installed-app client JSON). The token is cached
only under ~/.dejaspawn/. Without a client JSON the mirror runs in FIXTURE mode (synthetic data).
"""

import base64
import hashlib
import http.server
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import snapshots

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"
EXPORT = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}
ROOT = os.path.join("mirror", "workspace")


def token_path():
    return os.path.join(os.path.expanduser("~"), ".dejaspawn", "workspace_token.json")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _http(url, data=None, headers=None, tries=5):
    for i in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(min(2**i, 30))
                continue
            raise
    raise RuntimeError("unreachable")


def _client(path):
    d = json.load(open(path, encoding="utf-8"))
    return d.get("installed") or d["web"]


def _save_token(t):
    p = token_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(t, f)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _token_call(c, fields):
    body = urllib.parse.urlencode(
        dict(fields, client_id=c["client_id"], client_secret=c.get("client_secret", ""))
    ).encode()
    return json.loads(_http(c["token_uri"], data=body))


def access_token(client_json):
    c = _client(client_json)
    p = token_path()
    if os.path.exists(p):
        t = json.load(open(p, encoding="utf-8"))
        if t.get("expires_at", 0) > time.time() + 60:
            return t["access_token"]
        if t.get("refresh_token"):
            n = _token_call(
                c, {"grant_type": "refresh_token", "refresh_token": t["refresh_token"]}
            )
            t.update(
                access_token=n["access_token"], expires_at=time.time() + n["expires_in"]
            )
            _save_token(t)
            return t["access_token"]
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"You can close this tab.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = (
        c["auth_uri"]
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": c["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )
    print("open this URL to authorise read-only access:\n" + url)
    webbrowser.open(url)
    srv.handle_request()
    n = _token_call(
        c,
        {
            "grant_type": "authorization_code",
            "code": got["code"][0],
            "redirect_uri": redirect,
        },
    )
    n["expires_at"] = time.time() + n["expires_in"]
    _save_token(n)
    return n["access_token"]


def _get(tok, url, params=None, raw=False):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    b = _http(url, headers={"Authorization": "Bearer " + tok})
    return b if raw else json.loads(b)


def _pages(tok, url, params, key):
    params = dict(params)
    while True:
        d = _get(tok, url, params)
        yield from d.get(key, [])
        if not d.get("nextPageToken"):
            return
        params["pageToken"] = d["nextPageToken"]


def write_manifest(d, mani):
    mani["files"].sort(key=lambda f: f["path"])
    tmp = os.path.join(d, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mani, f, indent=2)
    os.replace(tmp, os.path.join(d, "manifest.json"))


def _put(d, rel, data, mani):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    mani["files"] = [f for f in mani["files"] if f["path"] != rel]
    mani["files"].append({"path": rel, "sha256": _sha(data), "bytes": len(data)})


def _load(d):
    mp = os.path.join(d, "manifest.json")
    if os.path.exists(mp):
        return json.load(open(mp, encoding="utf-8"))
    return {"mode": "", "gmail": {}, "drive": {}, "files": []}


def mirror_fixture(root=ROOT):
    d = os.path.join(root, _sha(b"fixture-account")[:12])
    m = _load(d)
    m["mode"] = "FIXTURE"
    for i in range(3):
        eml = (
            f"From: a{i}@example.test\r\nTo: b@example.test\r\nSubject: fixture {i}\r\n\r\nbody {i}\r\n"
        ).encode()
        _put(d, f"gmail/fixture{i}.eml", eml, m)
    for i in range(2):
        _put(d, f"drive/file{i}.txt", f"fixture file {i}\n".encode(), m)
    m["gmail"] = {"historyId": "0"}
    m["drive"] = {"modifiedTime": "1970-01-01T00:00:00Z"}
    write_manifest(d, m)
    return d, m


def mirror_real(client_json, root=ROOT):
    tok = access_token(client_json)
    email = _get(tok, GMAIL + "/profile")
    d = os.path.join(root, _sha(email["emailAddress"].encode())[:12])
    m = _load(d)
    m["mode"] = "REAL"
    have = {f["path"] for f in m["files"]}
    ids = None
    if m["gmail"].get("historyId"):
        try:
            ids = []
            for h in _pages(
                tok,
                GMAIL + "/history",
                {
                    "startHistoryId": m["gmail"]["historyId"],
                    "historyTypes": "messageAdded",
                },
                "history",
            ):
                ids += [x["message"]["id"] for x in h.get("messagesAdded", [])]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            ids = None  # history expired: fall back to a full listing
    if ids is None:
        ids = [
            x["id"]
            for x in _pages(tok, GMAIL + "/messages", {"maxResults": 500}, "messages")
        ]
    for i in ids:
        if f"gmail/{i}.eml" in have:
            continue
        raw = _get(tok, f"{GMAIL}/messages/{i}", {"format": "raw"})["raw"]
        _put(
            d,
            f"gmail/{i}.eml",
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)),
            m,
        )
    m["gmail"]["historyId"] = email["historyId"]
    since = m["drive"].get("modifiedTime")
    q = "trashed=false" + (f" and modifiedTime > '{since}'" if since else "")
    newest = since or ""
    for f in _pages(
        tok,
        DRIVE + "/files",
        {
            "q": q,
            "pageSize": 200,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime)",
        },
        "files",
    ):
        mt = f["mimeType"]
        if mt == "application/vnd.google-apps.folder":
            continue
        if mt in EXPORT:
            data = _get(
                tok,
                f"{DRIVE}/files/{f['id']}/export",
                {"mimeType": EXPORT[mt][0]},
                raw=True,
            )
            ext = EXPORT[mt][1]
        elif mt.startswith("application/vnd.google-apps."):
            continue
        else:
            data = _get(tok, f"{DRIVE}/files/{f['id']}", {"alt": "media"}, raw=True)
            ext = ""
        _put(d, f"drive/{f['id']}{ext}", data, m)
        newest = max(newest, f["modifiedTime"])
    if newest:
        m["drive"]["modifiedTime"] = newest
    write_manifest(d, m)
    return d, m


def mirror():
    cj = os.environ.get("GOOGLE_OAUTH_CLIENT_JSON")
    prev = snapshots.resolve(ROOT)
    rid, root = snapshots.new_run(ROOT)
    try:
        if prev:  # incremental: start from the previous snapshot's files
            shutil.copytree(prev, root, dirs_exist_ok=True)
        d, m = mirror_real(cj, root) if cj else mirror_fixture(root)
    except BaseException:
        snapshots.discard(root)
        raise
    snapshots.publish(ROOT, rid)
    mp = os.path.join(d, "manifest.json")
    n = len(m["files"])
    return {
        "mode": m["mode"],
        "run": rid,
        "files": [
            {
                "path": mp.replace("\\", "/"),
                "count": n,
                "sha256": _sha(open(mp, "rb").read()),
            }
        ],
    }


def verify(d=None, run=None):
    """VERIFY-ONLY: recompute every manifest hash and count. Returns (ok, detail)."""
    snap = None if d else snapshots.resolve(ROOT, run)
    ds = (
        [d]
        if d
        else (
            [os.path.join(snap, x) for x in os.listdir(snap)]
            if snap
            else []
        )
    )
    ds = [x for x in ds if os.path.exists(os.path.join(x, "manifest.json"))]
    if not ds:
        return False, {"error": "no manifest"}
    bad, n = [], 0
    for x in ds:
        for f in _load(x)["files"]:
            n += 1
            p = os.path.join(x, f["path"])
            if not os.path.isfile(p) or _sha(open(p, "rb").read()) != f["sha256"]:
                bad.append(f["path"])
    return not bad, {"count": n, "bad": bad, "mode": "VERIFY-ONLY"}
