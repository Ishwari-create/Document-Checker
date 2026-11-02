# How the desk connects to real systems

The prototype runs with mock services. Each one sits behind a small interface, so
the real service replaces the mock without touching the rules.

| What | Prototype | Real connection | Status |
|---|---|---|---|
| Applications | `data/applications.json` | AICTE portal sends the application record with each document (`POST /api/v1/check`, field `application`) | API ready |
| Bank confirmation of the FDR (R9) | `IssuerConnector` reads `data/bank_confirmations.json` | 1. Bank QR on the receipt (A3, works today on receipts that carry one). 2. Bank confirmation by e-mail to the branch: the officer's "Ask the bank" action. 3. Bank API or a central deposit registry where one exists. | 1 working, 2 manual, 3 to be agreed with banks |
| Reuse of an FDR across applications (R10) | SQLite ledger, FDR number stored only as a SHA-256 | Same ledger on the Regional Office server, shared across ROs | Working |
| Fire NOC authenticity | Rule pack N1-N4 on the document | State fire-service portals that list issued NOCs (where available), or DigiLocker if the issuing department publishes there | To confirm per State |
| Infrastructure photos | Upload on the application page, `POST /api/v1/photo` | The portal's existing geo-tagged photo upload sends each file to the API | API ready |
| Letters | SMTP, or `.eml` files in `data/outbox/` | RO mail server (set `SMTP_HOST` etc.) | Working |
| Sign-in | `config/users.yaml` | Portal single sign-on | To integrate |

Nothing in this table needs a change to the rule packs: they only see the status the
connector returns (`found`, `not_found`, `mismatch`, `verification_pending`).
