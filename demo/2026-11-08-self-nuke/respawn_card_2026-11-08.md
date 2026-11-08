# Respawn card 2026-11-08

Drill status: **FULL**
Drill mode: **REAL** (per platform: stripe=MOCK-UNAVAILABLE, cloudflare=DRY-RUN, github=REAL)
Total seconds: 4.373

| Platform | Mode | Came back | Minutes to recovery | Unrecoverable by design |
|---|---|---|---|---|
| stripe | MOCK-UNAVAILABLE | repos=1 (0 ok) | n/a | card tokens and PANs are never exported by the API (payment methods must be re-collected); webhook signing secrets; Radar rules |
| cloudflare | DRY-RUN | zones=2, dns_records=6 | 0.000 | certificates (private keys are not retrievable) and Workers |
| github | REAL | repos=1 (1 ok) | 0.003 | Actions secrets and packages |

Attestation: `20261108T222136Z-drill.json.dsse.json`, keyid `e7606d656411c28130854a23473c47d4e3799ebae67f5ba5fc0f11fc0c17e38c`
Verify: `python -m dejaspawn verify <file> --key <pubkey hex> --expect-keyid <keyid>`

Minutes cover the machine steps only, not re-authenticating to new accounts.
