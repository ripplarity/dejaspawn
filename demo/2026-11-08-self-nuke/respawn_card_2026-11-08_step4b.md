# Respawn card 2026-11-08

Drill status: **FULL**
Drill mode: **REAL** (per platform: stripe=REAL)
Total seconds: 1.8

| Platform | Mode | Came back | Minutes to recovery | Unrecoverable by design |
|---|---|---|---|---|
| stripe | REAL | subscriptions=2 | 0.030 | card data and payment methods: not available via the API; card data moves only by a Stripe-mediated transfer to another PCI DSS Level 1 processor (see docs.stripe.com/get-started/data-migrations/pan-export), so a self-serve restore cannot recreate payment methods; webhook signing secrets; Radar rules |

Stripe objects:

| Type | Created | Failed |
|---|---|---|
| subscriptions | 2 | 0 |

Unrecoverable by design: payment methods: UNRECOVERABLE (not available via the API; card data moves only by a Stripe-mediated transfer to another PCI DSS Level 1 processor (see docs.stripe.com/get-started/data-migrations/pan-export), so a self-serve restore cannot recreate payment methods)

- subscription eaad1dcbd7e9: restored_status=trialing
- subscription 9a6ef0b79079: restored_status=trialing

Attestation: `20261108T221657Z-drill.json.dsse.json`, keyid `e7606d656411c28130854a23473c47d4e3799ebae67f5ba5fc0f11fc0c17e38c`
Verify: `python -m dejaspawn verify <file> --key <pubkey hex> --expect-keyid <keyid>`

Minutes cover the machine steps only, not re-authenticating to new accounts.
