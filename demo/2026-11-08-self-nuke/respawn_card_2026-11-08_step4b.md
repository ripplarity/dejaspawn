# Respawn card 2026-11-08

Drill status: **FULL**
Drill mode: **REAL** (per platform: stripe=REAL)
Total seconds: 1.8

| Platform | Mode | Came back | Minutes to recovery | Unrecoverable by design |
|---|---|---|---|---|
| stripe | REAL | subscriptions=2 | 0.030 | card tokens and PANs are never exported by the API (payment methods must be re-collected); webhook signing secrets; Radar rules |

Stripe objects:

| Type | Created | Failed |
|---|---|---|
| subscriptions | 2 | 0 |

Unrecoverable by design: payment methods: UNRECOVERABLE (never exported by the platform)

- subscription eaad1dcbd7e9: restored_status=trialing
- subscription 9a6ef0b79079: restored_status=trialing

Attestation: `20261108T221657Z-drill.json.dsse.json`, keyid `e7606d656411c28130854a23473c47d4e3799ebae67f5ba5fc0f11fc0c17e38c`
Verify: `python -m dejaspawn verify <file> --key <pubkey hex> --expect-keyid <keyid>`

Minutes cover the machine steps only, not re-authenticating to new accounts.
