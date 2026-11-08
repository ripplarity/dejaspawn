<p align="center">
  <img src="assets/logo.svg" width="112" alt="Deja Spawn">
</p>

<h1 align="center">Deja Spawn</h1>

<p align="center">
  <img src="assets/badges.svg" alt="Python 3.10+ · Stripe · Cloudflare · GitHub · ed25519-signed receipts · Apache-2.0">
</p>

<p align="center">
  <b>You've been here before.</b><br>
  Rehearse losing your Stripe, Cloudflare and GitHub accounts, so that when it happens for real, it's a re-run.
</p>

<table align="center">
  <tr>
    <td align="center"><h3>3</h3><sub>platforms mirrored<br>into files you own</sub></td>
    <td align="center"><h3>0.006 min</h3><sub>timed drill on one real setup<br>(mock / dry-run targets)</sub></td>
    <td align="center"><h3>1 byte</h3><sub>changed in a mirror<br>turns <code>verify</code> into FAIL</sub></td>
    <td align="center"><h3>DSSE</h3><sub>in-toto attestations,<br>pinned-keyid verify</sub></td>
  </tr>
</table>

---

## Contents

1. [Why](#1-why)
2. [Quick start](#2-quick-start)
3. [What it mirrors and drills](#3-what-it-mirrors-and-drills)
4. [Receipts](#4-receipts)
5. [Environment](#5-environment)
6. [What it does not protect](#6-what-it-does-not-protect)
7. [Scope and limits](#7-scope-and-limits)
8. [Evidence](#8-evidence)

---

## 1. Why

Accounts get suspended. Payment processors freeze. Repos vanish behind a policy email. When it happens, the question is not "do we have a backup?" but **"how many minutes until we're live again?"**

Deja Spawn answers that before it matters: it **mirrors** what you run on, **drills** the restore against safe targets and times it, and **proves** each run with a signed receipt. Per-platform backup tools exist; this is one owner-kept mirror across platforms, with a rehearsed restore you can verify.

## 2. Quick start

```bash
docker run -d -p 12111:12111 stripe/stripe-mock      # safe restore target for Stripe
python -m dejaspawn doctor                           # PASS/FAIL: Docker, stripe-mock, git, signing key
python -m dejaspawn mirror stripe
python -m dejaspawn mirror cloudflare
python -m dejaspawn mirror github --repo owner/name
python -m dejaspawn drill --dry-run                  # minutes to recovery, per platform
python -m dejaspawn verify receipts/<latest>.json.dsse.json   # OK, or FAIL if anything changed
```

## 3. What it mirrors and drills

| Platform | Mirror | Drill |
|---|---|---|
| **Stripe** | customers, subscriptions, products, prices, invoices (last 90 days) → `mirror/stripe/*.jsonl` | recreates customers, products, prices and subscriptions into stripe-mock |
| **Cloudflare** | every DNS zone export → `mirror/cloudflare/<zone>.txt` | re-imports each zone through the real import function; `--dry-run` writes the exact request to `scratch/` |
| **GitHub** | `git clone --mirror` of one repo (`--repo owner/name`) or, with `GITHUB_TOKEN`, every repo you own, collaborate on or reach through an organisation, plus issues and PRs as JSON | `git fsck` on every mirror |

A drill never touches a live account unless you ask it to. Stripe refuses any non-local restore target unless `DEJASPAWN_ALLOW_REAL_RESTORE=1`, and it refuses a live key unless `DEJASPAWN_ALLOW_LIVE=1`.

## 4. Receipts

Every command ends with `receipts/<time>-<command>.json` (the legacy-format file) and its DSSE envelope. The `.json` lists the files written (with record counts and sha256), the elapsed seconds, and a mode for each platform:

| Mode | Meaning |
|---|---|
| `REAL` | live API |
| `MOCK` | local mock server |
| `FIXTURE` | built-in sample data |
| `DRY-RUN` | request built, not sent |
| `NO-MIRROR`, `MOCK-UNAVAILABLE` | that platform was **not** rehearsed |

Each run also writes `<receipt>.json.dsse.json`: a standard **DSSE envelope over an in-toto Statement v1**, whose subjects are the mirrored files and their sha256. That means generic supply-chain tooling can read it, not just this one. The predicateType is `https://ripplarity.com/attestation/dejaspawn/mirror/v1`. Envelopes are signed with ed25519; the key is created on first use at `~/.dejaspawn/dejaspawn_ed25519.pem` (override with `DEJASPAWN_KEY`).

`verify` checks the signature against a **pinned keyid**: either your local signing key file (the output prints which source set the keyid), or `--key HEX --expect-keyid ID` given out of band. `--key` without `--expect-keyid` is refused, and so is a signing key file that sits next to the artefact. It also checks that every mirrored file named in the statement still matches its hash; files that are not on disk are reported, with the signature still confirmed.

> A FIXTURE or MOCK receipt is not evidence that your real data is safe.

<details>
<summary><b>Receipt and key details</b></summary>

- Key lookup: `DEJASPAWN_KEY` if set, otherwise `~/.dejaspawn/dejaspawn_ed25519.pem` (created on first use).
- Rotation: generate a new key at the first path, keep the old file until old attestations are re-verified with `--key`, publish the new keyid, then delete the old key.
- Each run also writes a plain `.json` receipt (version id `dejaspawn-receipt-1`); `verify` accepts it and labels it `legacy format`. They hold their own public key, so that check shows integrity, not who signed.
- `drill` exits 0 even when a platform is `NO-MIRROR` or `MOCK-UNAVAILABLE`. Read the mode, not the exit code.

</details>

## 5. Environment

| Variable | Use |
|---|---|
| `STRIPE_API_KEY` | test-mode key (`sk_test_`/`rk_test_`). With a test key set and no `STRIPE_API_BASE`, the target is the REAL Stripe API (`https://api.stripe.com`, label REAL-TEST); the stripe-mock default (`http://localhost:12111`) applies only when no key is set. Live keys are refused unless `DEJASPAWN_ALLOW_LIVE=1`. |
| `DEJASPAWN_STRIPE_RESTORE_BASE`, `STRIPE_RESTORE_KEY` | restore target and its key (default: stripe-mock) |
| `DEJASPAWN_ALLOW_LIVE`, `DEJASPAWN_ALLOW_REAL_RESTORE` | set to `1` to allow a live key, or a non-local restore target |
| `DEJASPAWN_KEY` | path of the signing key |
| `CF_API_TOKEN` | zone and DNS read access; edit access only for a real restore |
| `GITHUB_TOKEN` | optional for `--repo` on public repos |

API keys and tokens passed by environment variable are never logged or written to disk. The GitHub token reaches git through the environment, not the command line or the repo config. One exception, by necessity of OAuth: the Workspace mirror stores the Google refresh token at `~/.dejaspawn/workspace_token.json` (mode 600 on POSIX; Windows ACLs are not changed, so protect that folder yourself). Revoke it at any time at https://myaccount.google.com/permissions (remove the app) and delete the file.

## 6. What it does not protect

- **Anything the platform never exposes:** card numbers and payment methods (they stay with Stripe), secrets, webhook signing keys and Radar rules.
- **Stripe:** a restore recreates objects with new ids. Payment methods must be re-collected, and invoice history is mirrored but not re-created.
- **Cloudflare:** DNS records only. Not Workers, Pages, rules or certificates.
- **GitHub:** repositories, issues and PRs. Not Actions secrets, wikis, release assets or review comments.
- **Google Workspace:** step 1 is read-only (Gmail raw messages, Drive files). There is no restore; the drill only verifies manifest hashes and counts (VERIFY-ONLY). Drive items without an export format, and Google-native types beyond Docs, Sheets and Slides, are skipped.

## 7. Scope and limits

- Exercised so far: Stripe against stripe-mock and a sandbox, Cloudflare DNS-read on one real account, and GitHub against one public repo. A private GitHub repo with a token has not been exercised.
- stripe-mock returns one static object per list, so multi-page pagination is untested.
- The 0.006 min drill restored into stripe-mock and did not send the Cloudflare import. Real minutes-to-recovery will be dominated by re-authenticating to new accounts, which the drill does not measure yet.
- A mirror on the same machine and account as the original is a copy, not a safeguard. Keep `mirror/` somewhere the platforms cannot reach.

## 8. Evidence

- The full transcript is in `examples/drill_transcript.txt`.
- Signed examples: `examples/drill_attestation_mock.dsse.json` (current DSSE format, from a mock drill) and, in the legacy format, `examples/drill_receipt_mock_dejaspawn.json`.
- The mirrored files named as subjects in the DSSE example are not in the repository, so `verify` reports them as not on disk while still confirming the signature.

```bash
python -m dejaspawn verify examples/drill_receipt_mock_dejaspawn.json   # OK (legacy format)
python -m dejaspawn verify examples/drill_attestation_mock.dsse.json \
  --key 13b0904b0f53a56cc785e2b0aeff48794b3b5727e23169f56c9026255ca58587 \
  --expect-keyid e7606d656411c28130854a23473c47d4e3799ebae67f5ba5fc0f11fc0c17e38c   # OK
```

## 9. Respawn card, schedule, Workspace, Exit Score

- **Card:** `python -m dejaspawn drill --card` runs the drill and writes `cards/<date>.md` and `.txt`: per platform what came back, minutes to recovery, what is unrecoverable by design, the drill mode (MOCK, DRY-RUN or REAL), and the attestation file and keyid. Pass `--dry-run` to skip the DNS import.
- **Schedule:** `python -m dejaspawn drill --schedule monthly|weekly` installs a Windows Scheduled Task (`schtasks`) or a cron line, named `dejaspawn-drill`, that runs `drill --card --dry-run` from the current directory. `--unschedule` removes it. Add `--dry-run` to either to print the task or cron line without installing.
- **Workspace mirror:** `python -m dejaspawn mirror workspace` reads Gmail (`messages.list`, `messages.get` format raw, scope `gmail.readonly`) and Drive (`files.list`, `files.export`/`get`, scope `drive.readonly`) into `mirror/workspace/<account-hash>/` with `manifest.json` (sha256 per file). Set `GOOGLE_OAUTH_CLIENT_JSON` to an installed-app client file; the token is cached only under `~/.dejaspawn/`. Re-runs are incremental (Gmail by historyId, Drive by modifiedTime). Without the client file it runs in FIXTURE mode on synthetic data and says so. Implementation: `dejaspawn/workspace.py`. The real path has not been exercised against a live account.
- **Exit Score:** `python -m dejaspawn exitscore` prints, per platform, the share of the state classes it holds (customers, subscriptions, payment instruments, invoices, DNS, certs, code, issues, mail, files, secrets) that its documented export surface lets you take out (full = 1, partial = 0.5, none = 0), next to the latest drill mode, and writes `exitscore.json`. It is derived from vendor documentation, not measured against any vendor; every row carries its source URL, held in the table in `dejaspawn/exitscore.py`. All URLs were fetched and read on 2026-11-08 (HTTP 200). One row, Cloudflare certificates, is marked UNVERIFIED because its page does not state what can be exported; it is excluded from that platform's score. `python -m dejaspawn exitscore --check-sources` re-fetches every URL and prints reachable or unreachable per row.

---

<p align="center"><sub>Apache-2.0 · Copyright 2026 Ripplarity Inc.</sub></p>
