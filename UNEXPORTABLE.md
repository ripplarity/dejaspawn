# The Unexportable List

Rule: every row needs a mechanism, a source URL and a check date; corrections within 24 hours.

| Platform | State class | Self-serve export via API or dashboard | Other route | Source URL | Checked | Evidence |
|---|---|---|---|---|---|---|
| Stripe | Payment methods / card data | no (not available via the API) | Stripe-mediated transfer to another PCI DSS Level 1 processor | https://docs.stripe.com/get-started/data-migrations/pan-export | 2026-11-08 | demo/2026-11-08-self-nuke/attestations/20261108T221657Z-drill.json |
| Stripe | Customers | yes (list endpoint) | none listed | https://docs.stripe.com/api/customers/list | 2026-11-08 | demo/2026-11-08-self-nuke/attestations/20261108T221711Z-mirror-stripe.json.dsse.json (and the pre-nuke 20261108T221012Z-mirror-stripe.json.dsse.json) |
| Stripe | Subscriptions | yes (list endpoint) | none listed | https://docs.stripe.com/api/subscriptions/list | 2026-11-08 | demo/2026-11-08-self-nuke/attestations/20261108T221711Z-mirror-stripe.json.dsse.json (restore outcome: demo/2026-11-08-self-nuke/attestations/20261108T221657Z-drill.json.dsse.json) |
| Stripe | Invoices | yes (list endpoint) | none listed | https://docs.stripe.com/api/invoices/list | 2026-11-08 | none |
| GitHub | Actions secrets | no (stored encrypted; the REST API lists names and metadata, not values) | none listed | https://docs.github.com/en/rest/actions/secrets | 2026-11-08 | none |
| Cloudflare | DNS records | yes (export endpoint) | none listed | https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/export/ | 2026-11-08 | demo/2026-11-08-self-nuke/attestations/20261108T222131Z-mirror-cloudflare.json.dsse.json (drill: demo/2026-11-08-self-nuke/attestations/20261108T222136Z-drill.json.dsse.json) (DRY-RUN import) |
| Cloudflare | Certificates | partial, UNVERIFIED (the page does not state what can be exported) | none listed | https://developers.cloudflare.com/ssl/edge-certificates/custom-certificates/ | 2026-11-08 | none |
| Google Workspace | Mail | yes (Gmail API messages.get, format raw) | none listed | https://developers.google.com/gmail/api/reference/rest/v1/users.messages/get | 2026-11-08 | none |
| Google Workspace | Drive files | yes (Drive API download and export) | none listed | https://developers.google.com/drive/api/guides/manage-downloads | 2026-11-08 | none |

All URLs returned HTTP 200 or a 301 redirect to an equivalent page on the check date. They are also rows of the table in `dejaspawn/exitscore.py`, so `python -m dejaspawn exitscore --check-sources` re-fetches them.
