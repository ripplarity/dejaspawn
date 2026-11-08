import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

from . import snapshots
from .receipt import sha256_file

API = "https://api.github.com"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _get(path, token):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "dejaspawn"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"github GET {path.split('?')[0]} -> HTTP {e.code}")


def _paged(path, token):
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        d = _get(f"{path}{sep}per_page=100&page={page}", token)
        if not d:
            return
        yield from d
        if len(d) < 100:
            return
        page += 1


def _git(args, token=None, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token:  # header via env, so the token never lands in argv or the repo config
        b = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0=f"Authorization: Basic {b}",
        )
    r = subprocess.run(["git"] + args, cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("git " + args[0] + " failed: " + r.stderr.strip()[:300])
    return r.stdout


def repo_list(token, only):
    if only:
        if not REPO_RE.fullmatch(only):
            raise SystemExit("--repo must be owner/name")
        return [only]
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN is required to list repos; or pass --repo owner/name"
        )
    return [
        r["full_name"]
        for r in _paged(
            "/user/repos?affiliation=owner,collaborator,organization_member", token
        )
    ]


def mirror(out="mirror/github", only=None):
    token = os.environ.get("GITHUB_TOKEN")
    base = out
    prev = snapshots.resolve(base)
    rid, out = snapshots.new_run(base)
    try:
        r = _mirror_into(out, prev, token, only)
    except BaseException:
        snapshots.discard(out)
        raise
    snapshots.publish(base, rid)
    r["run"] = rid
    return r


def _mirror_into(out, prev, token, only):
    import shutil

    files = []
    if prev:  # start from the previous clones so `remote update` stays incremental
        for d in os.listdir(prev):
            if d.endswith(".git"):
                shutil.copytree(os.path.join(prev, d), os.path.join(out, d))
    for full in repo_list(token, only):
        name = full.split("/")[1]
        gd = os.path.join(out, name + ".git")
        if os.path.isdir(gd):
            _git(["remote", "update", "--prune"], token, cwd=gd)
        else:
            _git(["clone", "--mirror", f"https://github.com/{full}.git", gd], token)
        refs = _git(["for-each-ref"], cwd=gd)
        rp = os.path.join(out, name + ".refs.txt")
        with open(rp, "w", newline="\n") as f:
            f.write(refs)
        files.append(
            {
                "path": rp.replace("\\", "/"),
                "sha256": sha256_file(rp),
                "count": len(refs.splitlines()),
                "note": "refs of mirror " + name + ".git",
            }
        )
        for kind in ("issues", "pulls"):
            fp = os.path.join(out, f"{name}.{kind}.jsonl")
            n = 0
            with open(fp, "w", encoding="utf-8", newline="\n") as f:
                for o in _paged(f"/repos/{full}/{kind}?state=all", token):
                    f.write(json.dumps(o, sort_keys=True) + "\n")
                    n += 1
            files.append(
                {"path": fp.replace("\\", "/"), "sha256": sha256_file(fp), "count": n}
            )
    return {"mode": "REAL", "authenticated": bool(token), "files": files}


def fsck_all(src="mirror/github", run=None):
    src = snapshots.resolve(src, run) or src
    res = {}
    for d in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if d.endswith(".git"):
            try:
                _git(["fsck", "--no-progress"], cwd=os.path.join(src, d))
                res[d] = "ok"
            except SystemExit as e:
                res[d] = "FAIL " + str(e)
    return res
