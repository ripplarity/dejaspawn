"""Exit Score: documentation-derived share of state that a platform lets you export.
Not a measurement of any vendor. Every row carries the URL it is derived from."""

import glob
import json
import os

CLASSES = [
    "customers",
    "subscriptions",
    "payment instruments",
    "invoices",
    "DNS",
    "certs",
    "code",
    "issues",
    "mail",
    "files",
    "secrets",
]
DATE = "2026-11-08"
FETCHED = "2026-11-08"  # date every URL below was fetched and read (HTTP 200)
# Rows whose page was read but does not state the level: excluded from the score.
UNVERIFIED = {
    ("cloudflare", "certs"): "page says Cloudflare stores the private key for CSR-generated certificates; it does not state what can be exported",
}
# (platform, class, level, url); level: full=1, partial=0.5, none=0. Classes a platform
# does not hold are omitted (not applicable).
TABLE = [
    ("stripe", "customers", "full", "https://docs.stripe.com/api/customers/list"),
    (
        "stripe",
        "subscriptions",
        "full",
        "https://docs.stripe.com/api/subscriptions/list",
    ),
    (
        "stripe",
        "payment instruments",
        "partial",
        "https://docs.stripe.com/get-started/data-migrations/pan-export",
    ),
    ("stripe", "invoices", "full", "https://docs.stripe.com/api/invoices/list"),
    ("stripe", "secrets", "none", "https://docs.stripe.com/keys"),
    (
        "cloudflare",
        "DNS",
        "full",
        "https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/export/",
    ),
    (
        "cloudflare",
        "certs",
        "partial",
        "https://developers.cloudflare.com/ssl/edge-certificates/custom-certificates/",
    ),
    (
        "cloudflare",
        "code",
        "partial",
        "https://developers.cloudflare.com/api/resources/workers/subresources/scripts/",
    ),
    (
        "cloudflare",
        "secrets",
        "none",
        "https://developers.cloudflare.com/workers/configuration/secrets/",
    ),
    (
        "github",
        "code",
        "full",
        "https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository",
    ),
    ("github", "issues", "full", "https://docs.github.com/en/rest/issues/issues"),
    ("github", "secrets", "none", "https://docs.github.com/en/rest/actions/secrets"),
    (
        "workspace",
        "mail",
        "full",
        "https://developers.google.com/gmail/api/reference/rest/v1/users.messages/get",
    ),
    (
        "workspace",
        "files",
        "partial",
        "https://developers.google.com/drive/api/guides/manage-downloads",
    ),
]
VAL = {"full": 1.0, "partial": 0.5, "none": 0.0}


def latest_receipt(d="receipts"):
    fs = sorted(glob.glob(os.path.join(d, "*-drill.json")))
    return json.load(open(fs[-1], encoding="utf-8")) if fs else None


def compute(table=TABLE, receipt=None):
    out = {}
    for p in dict.fromkeys(r[0] for r in table):
        rows = [r for r in table if r[0] == p]
        mode = ((receipt or {}).get("platforms", {}).get(p) or {}).get(
            "mode", "no drill receipt"
        )
        sc = [r for r in rows if (r[0], r[1]) not in UNVERIFIED]
        out[p] = {
            "score": round(sum(VAL[r[2]] for r in sc) / len(sc), 3) if sc else None,
            "latest_drill_mode": mode,
            "classes": {
                r[1]: (
                    {"level": "UNVERIFIED", "claimed": r[2], "reason": UNVERIFIED[(r[0], r[1])], "url": r[3]}
                    if (r[0], r[1]) in UNVERIFIED
                    else {"level": r[2], "url": r[3]}
                )
                for r in rows
            },
        }
    return {
        "basis": "documentation-derived, not a vendor measurement",
        "date": DATE,
        "urls_fetched": FETCHED,
        "state_classes": CLASSES,
        "platforms": out,
    }


def check_sources(table=TABLE, fetch=None):
    """Re-fetch every cited URL. Returns {url: True|False}; prints reachable/unreachable."""
    import urllib.request

    def get(u):
        r = urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": "dejaspawn"}), timeout=30
        )
        return r.status == 200

    res = {}
    for p, c, _, u in table:
        try:
            ok = bool((fetch or get)(u))
        except Exception:
            ok = False
        res[u] = ok
        tag = "reachable" if ok else "unreachable"
        if (p, c) in UNVERIFIED:
            tag += " UNVERIFIED"
        print(f"{tag:22s} {p}/{c} {u}")
    return res


def run(out="exitscore.json", receipt_dir="receipts", check=False):
    if check:
        check_sources()
    res = compute(receipt=latest_receipt(receipt_dir))
    json.dump(res, open(out, "w", encoding="utf-8"), indent=2)
    for p, v in res["platforms"].items():
        print(f"{p:11s} score {v['score']}  drill: {v['latest_drill_mode']}")
        for c, x in v["classes"].items():
            print(f"    {c}: {x['level']}  {x['url']}")
    print("documentation-derived score; wrote", out)
    return 0
