# SD Scrutiny Desk

Checks the Security Deposit FDR that a private technical institute submits to AICTE after its Letter of Approval, and tells the scrutiny officer what is wrong, where on the receipt it is, and which clause it breaks.

Built for SIH 2026, problem statement **SIH26261** (AICTE: application validation, document authentication and compliance verification), by Team GitHappens.

## Why this document first

The brief asks for validation of many application documents. We started with the Security Deposit FDR because it is the one where every check can be written down precisely: who it is payable to, which bank issued it, how long it runs, how much it is for, whether the bank confirms it. The engine is not FDR-specific. Rules and field labels live in config files; a second document type is a new rule pack, not a new program.

## What it checks

| | Check | Where the rule comes from |
|---|---|---|
| R0 | Is a Security Deposit needed at all? Government and aided institutes are exempt | Guidelines 2024-27 cl. 6.6(c), LOI |
| R1 | Payable to Member Secretary, AICTE | AICTE LOI condition |
| R2 | Issued by a nationalised or scheduled commercial bank (not a co-operative bank, credit society or NBFC) | LOI; RBI Act, Second Schedule |
| R3 | Runs for the full Security Deposit period (10 years) | Guidelines 2024-27 cl. 6.2(g) *(to confirm)* |
| R4 | Amount covers every programme applied for, at the right slab | APH cl. 9 table *(older edition, to confirm)*; cl. 4.15(b) |
| R5 | Depositor is the applicant institute or its trust | cl. 6.2(f) |
| R6 | Not post-dated, not already matured | cl. 11.8 |
| R7 | Submitted within 15 days of the LoA, with the 10% / 50% penalty worked out | cl. 6.2(f) |
| R8 | Amount in figures matches amount in words | Scrutiny practice |
| R9 | The issuing bank's record matches the receipt | SIH26261 brief (mocked bank service) |
| R10 | The same FDR or file has not been used for another application | SIH26261 brief |

Every finding shows the evidence (with a box on the receipt), the clause, and what the institute has to do. Rules marked *to confirm* use a value we could not verify against the current APH 2024-27 text; see [docs/RULE_SOURCES.md](docs/RULE_SOURCES.md).

The system never rejects anything. A failed check becomes a point for the officer, who confirms or overrules it (overruling needs a reason), and only confirmed points go into the draft deficiency letter. Every automated check and every officer decision is logged with the file's SHA-256 and the rule version.

## Who uses it

Sign in at `/login`. Demo accounts (replace with the AICTE portal's own sign-in for real use):

| Role | Username / password | Can do |
|---|---|---|
| Scrutiny officer | officer / officer123 | Queue, scrutiny, corrections, decisions, letters, audit trail |
| Auditor | auditor / auditor123 | Audit trail only |
| Institute | sahyadri or vindhya / inst123 | Self-check of its own application only |

## Screens

- **Received FDRs**: queue, cases needing a person first
- **Scrutiny view**: receipt with evidence boxes, findings, officer decision, history. If a scan was misread, the officer corrects the value and the checks run again; the correction is logged
- **Check a receipt**: upload a new one against an application
- **Institute self-check**: the same checks in plain language for the institute, before it submits; nothing stored
- **Try to fool it**: make one edit to a good receipt and watch the checker catch it
- **Test results**, **Rules**, **Audit trail**

## Connecting to the AICTE portal

The portal can send each receipt to the checker as soon as an institute uploads it:

```bash
curl -H "Authorization: Bearer $API_TOKEN" \
     -F pdf=@receipt.pdf -F app_id=1-SYN-2026-0101 -F received=2026-05-02 \
     http://localhost:8501/api/v1/check
```

It returns the overall finding, each rule's status, evidence and clause, the extracted fields with their location on the page, and the rule version. Instead of `app_id` the portal can send its own application record as JSON in `application`. `GET /api/v1/rules` returns the rules in force. Set `API_TOKEN` and `SECRET_KEY` as environment variables before deploying.

## Privacy

FDR numbers are not stored. The reuse ledger keeps only a SHA-256 of bank + FDR number, which is enough to spot the same deposit twice. Institute self-checks are not stored at all. Demo passwords are salted hashes.

## Results

On 24 synthetic receipts (10 correct, 14 with one planted defect, 4 scanned, 3 bank layouts): all 14 defects caught by the right rule, no correct receipt failed, one correct scan sent to an officer because OCR misread two fields. Field extraction: 23/24 FDR numbers, 24/24 amounts, dates and depositors. Full table: [reports/evaluation.md](reports/evaluation.md).

That set uses layouts the extractor was written against. On two further sets in layouts it had never seen, the first runs caught 1/4 and 2/4 defects, sent most other receipts to an officer, wrongly failed one correct receipt in each set, and passed no defective receipt. Details and what we changed afterwards are on the Test results screen and in [docs/JUDGE_REVIEW.md](docs/JUDGE_REVIEW.md).

All data is synthetic and marked SAMPLE - TEST DATA. These numbers show the method works; they are not a claim about real AICTE files.

## Run it

Needs Python 3.10+, `tesseract-ocr` and `poppler-utils`.

```bash
pip install -r requirements.txt
python tools/generate_test_docs.py      # 24 test receipts, labels, mock bank records
python tools/evaluate.py                # writes reports/evaluation.md
python app/app.py                       # http://localhost:8501
pytest -q
```

Or with Docker (also how it deploys to Hugging Face Spaces):

```bash
docker build -t sd-desk . && docker run -p 7860:7860 sd-desk
```

## Layout

```
config/rules.yaml          rules, thresholds, clause references, sources, rule version
config/field_labels.yaml   wording banks use for each field; onboarding a bank = editing this
src/extractor.py           text layer or OCR -> fields, each with page and box
src/rule_engine.py         R0-R10
src/registry.py            mock bank confirmation, reuse ledger, audit trail (SQLite)
src/pipeline.py            one call: read, check, log
src/deficiency.py          draft letter from officer-confirmed points
app/                       Flask screens
tools/                     test-set generator, held-out sets, evaluation
data/                      synthetic applications, banks, receipts, labels
```

## Team

Team GitHappens. A-1 built the first backend (extractor, rule engine, letter, tests). A-2 (Rutuja Patole) did the rules research, test set, evaluation and screens, and reworked the backend on the `feature/a2-frontend` branch.
