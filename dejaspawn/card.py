"""Respawn card: one-page summary of a drill receipt."""

import json
import os

from .receipt import run_mode

UNRECOVERABLE = {
    "stripe": "card tokens and PANs are never exported by the API (payment methods must be re-collected); webhook signing secrets; Radar rules",
    "cloudflare": "certificates (private keys are not retrievable) and Workers",
    "github": "Actions secrets and packages",
    "workspace": "no restore in step 1 (VERIFY-ONLY): the drill checks manifest hashes and counts only",
}


def _counts(detail):
    if not isinstance(detail, dict) or not detail:
        return "-"
    if isinstance(detail.get("restored"), dict):
        return ", ".join(f"{k}={v}" for k, v in detail["restored"].items())
    if isinstance(detail.get("zones"), dict):
        n = sum(z.get("records", 0) for z in detail["zones"].values())
        return f"zones={len(detail['zones'])}, dns_records={n}"
    if "count" in detail:
        return f"files={detail['count']}"
    return f"repos={len(detail)} ({sum(1 for v in detail.values() if v == 'ok')} ok)"


def keyid_from(env_path):
    try:
        d = json.load(open(env_path, encoding="utf-8"))
        return d["signatures"][0]["keyid"]
    except Exception:
        return None


def render(receipt, env_path=None):
    """receipt: legacy receipt dict. Returns (markdown, plaintext)."""
    plats = receipt["platforms"]
    mode = run_mode(plats)
    keyid = (env_path and keyid_from(env_path)) or receipt.get("pubkey_sha256", "?")
    rows = []
    for n, p in plats.items():
        m = p.get("minutes_to_recovery")
        rows.append(
            (
                n,
                p.get("mode", "?"),
                _counts(p.get("detail")),
                "n/a" if m is None else f"{m:.3f}",
                UNRECOVERABLE.get(n, "see README section 6"),
            )
        )
    att = os.path.basename(env_path) if env_path else "(none)"
    md = [
        f"# Respawn card {receipt['ended'][:10]}",
        "",
        f"Drill mode: **{mode}** (per platform: "
        + ", ".join(f"{n}={p.get('mode')}" for n, p in plats.items())
        + ")",
        f"Total seconds: {receipt['seconds']}",
        "",
        "| Platform | Mode | Came back | Minutes to recovery | Unrecoverable by design |",
        "|---|---|---|---|---|",
    ]
    md += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows]
    md += [
        "",
        f"Attestation: `{att}`, keyid `{keyid}`",
        "Verify: `python -m dejaspawn verify <file> --key <pubkey hex> --expect-keyid <keyid>`",
        "",
        "Minutes cover the machine steps only, not re-authenticating to new accounts.",
    ]
    txt = [
        f"RESPAWN CARD {receipt['ended'][:10]}  mode={mode}",
        f"total seconds: {receipt['seconds']}",
    ]
    for a, b, c, d, e in rows:
        txt += [f"- {a} [{b}] came back: {c}; minutes: {d}", f"    unrecoverable: {e}"]
    txt += [f"attestation: {att}  keyid: {keyid}"]
    return "\n".join(md) + "\n", "\n".join(txt) + "\n"


def write_card(receipt_path, env_path, out_dir="cards"):
    r = json.load(open(receipt_path, encoding="utf-8"))
    md, txt = render(r, env_path)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, r["ended"][:10])
    open(base + ".md", "w", encoding="utf-8").write(md)
    open(base + ".txt", "w", encoding="utf-8").write(txt)
    return base + ".md"
