# Nuke-demo transcript (steps 1, 2, 5, 6; 2026-11-08 UTC)
Env: STRIPE_API_KEY=<ENV> (write-capable sandbox restricted key), CF_API_TOKEN=<ENV>, GITHUB_TOKEN=<ENV>. Commands run from the dejaspawn repo root; the shipped dejaspawn commit is 3b9455a (the step 4b run used the pre-commit tree of the same change); the Cloudflare mirror/drill below were re-run with the --zones allowlist (commit 92d5588).
An all-zones Cloudflare run was done first; its attestations are not published because their payloads name non-product zones.
Attestation signing keyid: e7606d656411c28130854a23473c47d4e3799ebae67f5ba5fc0f11fc0c17e38c

## Steps 1-2: doctor, mirrors, counts
Commands: `python -m dejaspawn doctor`; `python -m dejaspawn mirror stripe`; `python -m dejaspawn mirror github --repo ripplarity/stillherd`; `python -m dejaspawn mirror cloudflare --zones dejaspawn.com,stillherd.com`; `wc -l mirror/stripe/*.jsonl`
Note: doctor FAIL on stripe-mock (docker container not running) is expected; mirror targets the real Stripe test API (label REAL-TEST).
```
## S1 2026-11-08T22:10:05Z
stripe mirror target: base=https://api.stripe.com label=REAL-TEST
PASS docker
FAIL stripe-mock at http://localhost:12111
PASS git
PASS signing key file (created on first receipt)
## S1-stripe 2026-11-08T22:10:10Z
mirror/stripe/customers.jsonl  count=3  sha256=aee29fb0f9635dfe
mirror/stripe/subscriptions.jsonl  count=2  sha256=4fea8e9e81831e4e
mirror/stripe/products.jsonl  count=1  sha256=229adbb9ca266a6c
mirror/stripe/prices.jsonl  count=1  sha256=47463e97d477e289
mirror/stripe/invoices.jsonl  count=2  sha256=c5a131d9fb2e6edd
mode: REAL-TEST
receipt: receipts/20261108T221012Z-mirror-stripe.json.dsse.json
## S1-github 2026-11-08T22:10:12Z
mirror/github/stillherd.refs.txt  count=1  sha256=ca680b937811eec9
mirror/github/stillherd.issues.jsonl  count=0  sha256=e3b0c44298fc1c14
mirror/github/stillherd.pulls.jsonl  count=0  sha256=e3b0c44298fc1c14
mode: REAL
receipt: receipts/20261108T221015Z-mirror-github.json.dsse.json
## S1-cf 2026-11-08T22:21:31Z (2-zone run)
mirror/cloudflare/dejaspawn.com.txt  count=3  sha256=c92aa4f2d4d7f7be
mirror/cloudflare/stillherd.com.txt  count=3  sha256=c8c0207359024350
mode: REAL
receipt: receipts/20261108T222131Z-mirror-cloudflare.json.dsse.json
## S2 2026-11-08T22:10:20Z
    3 mirror/stripe/customers.jsonl
    2 mirror/stripe/invoices.jsonl
    1 mirror/stripe/prices.jsonl
    1 mirror/stripe/products.jsonl
    2 mirror/stripe/subscriptions.jsonl
    9 total
mirror/cloudflare/dejaspawn.com.txt
mirror/cloudflare/stillherd.com.txt
mirror/cloudflare/zones.json
```
(Listing of mirror/cloudflare after the 2-zone run: 3 files, 2 real zones plus zones.json; the offline fixture example.test is not part of a REAL run.)
Per-type Stripe counts (step 2): customers 3, subscriptions 2, products 1, prices 1, invoices 2.

## Step 5: GitHub restore into a scratch private repo
All times UTC. Create via REST API (POST orgs/<org>/repos, private, auto_init=false): HTTP 201 at 22:11:23Z.
`git -C mirror/github/stillherd.git push --mirror git@<ssh alias>:<org>/respawn-scratch.git` at 22:11:34Z.
- mirror HEAD 6601a45c18cc4132bf2f7d3e45d67d3061b08665; scratch ls-remote HEAD identical.
- commit count (rev-list --count --all): mirror 20, fresh fetch of scratch 20. `git fsck` rc=0.
- push + verify wall time: 5 s.
- DELETE of the scratch repo by the token: HTTP 403 "Must have admin rights to Repository" (the token has no delete_repo scope). A follow-up GET returned 200: the scratch repo (private, a copy of public content) still existed then. The founder deleted the scratch repo afterwards (API 404 confirmed 22:2xZ). Not worked around.

## Step 6: Cloudflare dry-run import (22:21:36Z, about 5 s)
`python -m dejaspawn drill --dry-run --card`; nothing sent (sent=False for every zone, import files written to scratch only). Drill covers only zones present in the mirror (2).
Drill totals: 2 zones, 6 DNS records (SOA + 2 NS per zone); cloudflare dry-run 0.000 min; github 1 repo REAL.
Per-zone import records vs mirror records: dejaspawn.com 3/3, stillherd.com 3/3. (The earlier all-zones run, not published, showed import-record counts above the mirror-line counts for some zones; the cause was not determined before that run was discarded. For the two product zones published here the import counter and the mirror agree, 3 and 3.)
Respawn card: respawn_card_2026-11-08.md. The Stripe row of the drill reads MOCK-UNAVAILABLE (stripe-mock not running; no restore attempted).

## Attestation verification (`python -m dejaspawn verify <file> --expect-keyid <keyid above>`)
- 20261108T221012Z-mirror-stripe.json.dsse.json: OK (rc=0)
- 20261108T221015Z-mirror-github.json.dsse.json: OK (rc=0)
- 20261108T222131Z-mirror-cloudflare.json.dsse.json: OK (rc=0)
- 20261108T222136Z-drill.json.dsse.json: OK (rc=0)

## Steps 3-4: nuke and respawn of the Stripe sandbox (UTC, 2026-11-08)
Key: restricted test-mode key, in env only (<ENV>); it was labelled read-only but has write on the sandbox. Safety checks before any delete: GET /v1/account id hash 3830ed1e9d5e; all 3 mirror customer ids present in the account, livemode false, customer count equal to the mirror (3).
Subscriptions before: 618615e972cb trialing, 48650d585a0f trialing (both charge_automatically, trial_end set).

### Step 3 NUKE (22:14:05Z to 22:14:07Z, 2 s), via REST DELETE/POST
- customers 3 -> 0 (DELETE returned deleted=true for 89a76f5b83db, 94ea1e312712, 73bbba7e6c0c)
- subscriptions 618615e972cb, 48650d585a0f -> canceled with their customers
- price 9e88ea1b751e and product 97cffb66bc9e archived (active=false; Stripe does not delete priced products or prices)
- list customers after: 0

### Step 4 RESPAWN (22:14:15Z to 22:14:19Z, 4 s), PARTIAL: subscriptions NOT recreated
Command: `DEJASPAWN_ALLOW_REAL_RESTORE=1 STRIPE_API_KEY=<ENV> STRIPE_RESTORE_KEY=<ENV> DEJASPAWN_STRIPE_RESTORE_BASE=https://api.stripe.com python -m dejaspawn drill --dry-run --card` (--dry-run keeps the Cloudflare step to scratch files; the GitHub step is fsck only).
Result: exit 1. stripe.restore() created customers, product and price, then `POST /v1/subscriptions` returned HTTP 400 resource_missing: "This customer has no attached payment source or default payment method." (stripe.py restore(), subscription loop near line 210: it sends only customer + items, drops trial_end, and the API never exports payment methods).
Recreated (old-id-hash -> new-id-hash):
- customers 3/3: 89a76f5b83db -> c7128477acab; 94ea1e312712 -> 7786b3af60e7; 73bbba7e6c0c -> 235841c2208c
- product 1/1: 97cffb66bc9e -> 2f1b31a7be26
- price 1/1: 9e88ea1b751e -> 4f94413a3166
- subscriptions 0/2 (before: both trialing; after: none exist, the two old ones stay canceled). This is the honest difference.
Customers 3 -> 0 -> 3; product and price archived -> recreated; 4 s for the objects that came back, but the run did not complete.
No drill attestation or card was produced (the command aborted before the receipt), so none is copied. No code was patched. No re-mirror was run: it would overwrite mirror/stripe/subscriptions.jsonl, the only record of the 2 subscriptions, with an empty list. The earlier attestations remain the pre-nuke record.
Possible fix (not applied, needs a decision): send trial_end (or attach a test payment method to the new customer) in the restore, then re-run only the subscriptions step.

### Step 4b SUBSCRIPTIONS RERUN with patched restore (22:16:50Z, 0.03 min), dejaspawn (shipped as 3b9455a)
Fix: restore sends `trial_end` (mirror value, only if future) + `payment_behavior=default_incomplete` + `collection_method`; per-object outcomes; drill PARTIAL/exit 3; receipt and card always written. Payment method stays UNRECOVERABLE (never exported by the platform); none fabricated.
Customers mapped old -> new by email; price mapped by amount/currency (only active price). Real restore base, DEJASPAWN_ALLOW_REAL_RESTORE=1, keys from <secrets file> (not printed).
Subscriptions 0 -> 2 (old-id-hash -> new-id-hash, outcome, status; trial_end sent = yes for both):
- 618615e972cb -> df945aabc9af: created, status trialing
- 48650d585a0f -> 2ce13b882150: created, status trialing
Attestation: attestations/20261108T221657Z-drill.json.dsse.json verifies OK with the pinned keyid e7606d65...e38c (receipt + card respawn_card_2026-11-08_step4b.md copied). Note: this receipt covers the subscription step only (written via write_receipt), not a full drill.
Re-mirror run after both existed: subscriptions.jsonl count=2 (the new ones), attestation 20261108T221711Z-mirror-stripe.json.dsse.json.

## Note on the pre-nuke Stripe mirror attestation (20261108T221012Z)
Its signature verifies; on the machine that ran the demo its subject check fails on purpose (on a fresh clone the subject files are absent and the verifier tolerates missing files, so it reports OK there): the subjects are the mirror files as they were BEFORE the nuke, and the re-mirror after the respawn (22:17:11Z) rewrote them with the respawned objects (new ids). The attestation therefore proves what the mirror held before the nuke; the post-respawn attestation (20261108T221711Z) proves what it holds now. Both are kept. Lesson recorded for the product: the mirror should keep a per-run snapshot directory so earlier attestations keep verifying against their own subjects.
