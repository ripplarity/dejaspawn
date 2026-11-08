import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

from .receipt import sha256_file

DEFAULT_BASE = "http://localhost:12111"
RESOURCES = [
    ("customers", "/v1/customers", False),
    ("subscriptions", "/v1/subscriptions", False),
    ("products", "/v1/products", False),
    ("prices", "/v1/prices", False),
    ("invoices", "/v1/invoices", True),
]


REAL_BASE = "https://api.stripe.com"


def _key_kind():
    k = os.environ.get("STRIPE_API_KEY", "")
    if k.startswith(("sk_live_", "rk_live_")):
        return "live"
    if k.startswith(("sk_test_", "rk_test_", "rkcs_test_")):
        return "test"
    return "none" if not k else "other"


def base_url():
    b = os.environ.get("STRIPE_API_BASE")
    if b:
        return b.rstrip("/")
    return REAL_BASE if _key_kind() == "test" else DEFAULT_BASE


def label(base=None):
    base = base or base_url()
    if is_mock(base):
        return "MOCK"
    return "REAL-TEST" if _key_kind() == "test" else "REAL"


def is_mock(base):
    return urllib.parse.urlparse(base).hostname in ("localhost", "127.0.0.1", "::1")


def restore_base():
    return os.environ.get("DEJASPAWN_STRIPE_RESTORE_BASE", DEFAULT_BASE).rstrip("/")


def reachable(base):
    """True if something answers HTTP at base (any status)."""
    try:
        urllib.request.urlopen(base + "/v1/customers?limit=1", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def api_key(base):
    k = os.environ.get("STRIPE_API_KEY")
    if k:
        return k
    if is_mock(base):
        return "sk_test_123"
    raise SystemExit("STRIPE_API_KEY is not set")


def _call(base, key, method, path, params=None):
    data = None
    url = base + path
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(params)
    elif method != "GET":
        data = urllib.parse.urlencode(params or {}).encode()
    hdr = {"Authorization": "Bearer " + key}
    if data is not None:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # never echo the key; body only
        raise SystemExit(
            f"stripe {method} {path} -> HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"
        )
    except urllib.error.URLError as e:
        raise SystemExit(f"stripe {method} {path} unreachable: {e.reason}")


def list_all(base, key, path, extra=None):
    params = {"limit": 100, **(extra or {})}
    while True:
        page = _call(base, key, "GET", path, params)
        for o in page.get("data", []):
            yield o
        if not page.get("has_more") or not page.get("data"):
            return
        params["starting_after"] = page["data"][-1]["id"]


def mirror(out="mirror/stripe", days=90):
    if _key_kind() == "live" and os.environ.get("DEJASPAWN_ALLOW_LIVE") != "1":
        raise SystemExit(
            "refusing a live Stripe key for a drill; use a test key (or set DEJASPAWN_ALLOW_LIVE=1)"
        )
    base = base_url()
    key = api_key(base)
    os.makedirs(out, exist_ok=True)
    tmp = out.rstrip("/\\") + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    since = int(time.time()) - days * 86400
    files = []
    for name, path, windowed in RESOURCES:
        extra = {"created[gte]": since} if windowed else None
        fp = os.path.join(tmp, name + ".jsonl")
        n = 0
        try:
            with open(fp, "w", encoding="utf-8", newline="\n") as f:
                for o in list_all(base, key, path, extra):
                    f.write(json.dumps(o, sort_keys=True) + "\n")
                    n += 1
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)  # old mirror stays intact
            raise
        files.append({"path": fp, "sha256": None, "count": n})
    for f in files:  # every page fetched: swap in
        dest = os.path.join(out, os.path.basename(f["path"]))
        os.replace(f["path"], dest)
        f["path"] = dest.replace("\\", "/")
        f["sha256"] = sha256_file(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return {
        "mode": label(base),
        "files": files,
        "invoice_window_days": days,
    }


def _read(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def restore(src="mirror/stripe", base=None, key=None):
    """Recreate customers, products, prices, subscriptions. Refuses a non-local target unless explicitly allowed."""
    base = base or os.environ.get("DEJASPAWN_STRIPE_RESTORE_BASE", DEFAULT_BASE).rstrip(
        "/"
    )
    if not is_mock(base) and os.environ.get("DEJASPAWN_ALLOW_REAL_RESTORE") != "1":
        raise SystemExit(
            "restore target is not local; set DEJASPAWN_ALLOW_REAL_RESTORE=1 to restore into a live account"
        )
    key = (
        key
        or os.environ.get("STRIPE_RESTORE_KEY")
        or ("sk_test_123" if is_mock(base) else None)
    )
    if not key:
        raise SystemExit("STRIPE_RESTORE_KEY is not set")
    idmap = {}
    counts = {"customers": 0, "products": 0, "prices": 0, "subscriptions": 0}

    def flat(prefix, d):
        return {f"{prefix}[{k}]": str(v) for k, v in (d or {}).items()}

    for c in _read(os.path.join(src, "customers.jsonl")):
        p = {k: c[k] for k in ("email", "name", "description", "phone") if c.get(k)}
        p.update(flat("metadata", c.get("metadata")))
        r = _call(base, key, "POST", "/v1/customers", p)
        idmap[c["id"]] = r["id"]
        counts["customers"] += 1
    for pr in _read(os.path.join(src, "products.jsonl")):
        p = {k: pr[k] for k in ("name", "description") if pr.get(k)}
        p["active"] = str(bool(pr.get("active", True))).lower()
        p.update(flat("metadata", pr.get("metadata")))
        r = _call(base, key, "POST", "/v1/products", p)
        idmap[pr["id"]] = r["id"]
        counts["products"] += 1
    for pc in _read(os.path.join(src, "prices.jsonl")):
        p = {
            "currency": pc["currency"],
            "product": idmap.get(pc.get("product"), pc.get("product")),
        }
        if pc.get("unit_amount") is not None:
            p["unit_amount"] = pc["unit_amount"]
        if pc.get("recurring"):
            p["recurring[interval]"] = pc["recurring"]["interval"]
            p["recurring[interval_count]"] = pc["recurring"].get("interval_count", 1)
        r = _call(base, key, "POST", "/v1/prices", p)
        idmap[pc["id"]] = r["id"]
        counts["prices"] += 1
    for s in _read(os.path.join(src, "subscriptions.jsonl")):
        items = ((s.get("items") or {}).get("data")) or []
        p = {"customer": idmap.get(s.get("customer"), s.get("customer"))}
        for i, it in enumerate(items):
            pid = (it.get("price") or {}).get("id")
            p[f"items[{i}][price]"] = idmap.get(pid, pid)
            if it.get("quantity"):
                p[f"items[{i}][quantity]"] = it["quantity"]
        _call(base, key, "POST", "/v1/subscriptions", p)
        counts["subscriptions"] += 1
    return {"base_mode": "MOCK" if is_mock(base) else "REAL", "restored": counts}
