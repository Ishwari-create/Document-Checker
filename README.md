# SD Scrutiny Desk

Checks the documents a technical institute submits to AICTE (Security Deposit FDR, Fire NOC, Trust affidavit and infrastructure photographs), and tells the scrutiny officer what is wrong, where on the document it is, which clause it breaks, whether the document itself looks altered, and whether the documents of one application agree with each other.

Built for SIH 2026, problem statement **SIH26261** (AICTE: application validation, document authentication and compliance verification), by Team GitHappens.

## How a document is checked

1. **Arrives**: through the portal API, an upload, or the **live inbox folder**.
2. **Document type** (D0): the system first decides what it is (Security Deposit FDR, Fire NOC, affidavit, or not a supported document). A wrong document gets one clear message instead of a page of failures.
3. **Read**: the PDF text layer, or Tesseract OCR for scans (English, plus Hindi when the page is in Devanagari).
4. **Find the fields**: label matching first (`config/field_labels.yaml`). For fields it cannot find, a **machine-learning extractor** trained on labelled receipts proposes values. The rules then check whatever was found, by either method; a value found by the ML extractor with low confidence cannot fail a document on its own.
5. **Authenticity** (A1–A4): checks on the file itself.
6. **Rule pack** for that document type, each rule citing its source.
7. **Officer** confirms or overrules each point (overruling needs a reason), can correct a misread value, and approves the letter, which is **emailed to the institute with the PDF attached**.

Every automated check and every officer action is logged with the file's SHA-256 and the rule version.

## What it checks

**Security Deposit FDR** (`config/rules.yaml`)

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

**Fire NOC** (`config/fire_noc_rules.yaml`): N1 issued by a fire authority, N2 valid on the date of submission (warns 90 days before expiry), N3 issued to the applicant institute, N4 covers the applicant's premises (same PIN code).

**Affidavit by the Trust / Society** (`config/affidavit_rules.yaml`): F1 on non-judicial stamp paper of at least Rs. 100 *(to confirm per State)*, F2 attested by a Notary / Magistrate with registration number, F3 sworn by the Chairman / President / Secretary of the applicant trust, F4 names the applicant institute, F5 executed within 6 months and not after submission, F6 contains the required undertakings (true and correct; liable to action; will abide by norms).

**Infrastructure photographs** (`config/photo_rules.yaml`, `src/photos.py`)

| | Check | How |
|---|---|---|
| P1 | Taken recently (6 months) | Camera date in the file (EXIF) |
| P2 | Taken at the campus (1 km) | GPS in the file against the campus point in the application |
| P3 | Not the same picture as another application | Perceptual hash plus thumbnail match against every photo on record: a resized or re-saved copy is still caught |
| P4 | Straight from a camera | Editing software tag; no camera make or model (screenshot or forwarded) |

A missing date, location or camera tag sends the photo to an officer; it never fails it on its own.

**The whole application** (`config/application_rules.yaml`, `src/application.py`): which required documents are missing (no Security Deposit for Government / aided institutes), and checks no single document can show: X1 every document names the same institute, X2 the Fire NOC and the photos point to the same campus, X3 the same trust stands behind the affidavit and the deposit, X4 the Fire NOC covers the coming academic year. The officer can then prepare **one letter for the whole application**.

**Authenticity, any document** (`src/authenticity.py`)

| | Check | What it looks at |
|---|---|---|
| A1 | No edits after issue | PDF revisions (incremental saves), producer / editing tool, digital signature present |
| A2 | Key values use the document's own fonts | A value printed in a font used nowhere else, or printed on top of older text |
| A3 | QR code agrees with the printed details | Decodes the bank's QR and compares FDR number, amount and maturity date |
| A4 | No pasted regions in a scan | Paper-grain consistency: a patch pasted in from a digital source has no grain |

These are preliminary indicators (as the brief puts it), so most send the case to an officer; a QR mismatch or an edited file is a deficiency.

Rules marked *to confirm* use a value we could not verify against the current APH 2024-27 text; see [docs/RULE_SOURCES.md](docs/RULE_SOURCES.md). **Confirm R3 and R4 with AICTE before real use.**

## Who uses it

Sign in at `/login`. Demo accounts (replace with the AICTE portal's own sign-in for real use):

| Role | Username / password | Can do |
|---|---|---|
| Scrutiny officer | officer / officer123 | Queue, scrutiny, corrections, decisions, letters, live inbox, audit trail |
| Auditor | auditor / auditor123 | Audit trail only |
| Institute | sahyadri or vindhya / inst123 | Self-check of its own application only |

## Screens

- **Dashboard**: workload, most common deficiencies, alerts (Fire NOC expiring, FDR maturing or ending before the Security Deposit period, letters with no reply in 30 days), every application's status, by State
- **Application**: all documents of one application, missing ones, checks between documents, photographs, one consolidated letter
- **Time study**: the same receipts checked by hand and with the desk, every file timed and scored, to measure the time saved
- **Received**: queue of every document, cases needing a person first (filter by type)
- **Scrutiny view**: document with evidence boxes, findings, officer decision, corrections, history
- **Check**: upload a document against an application
- **Live inbox**: watches a folder; drop a PDF in and the result appears in a few seconds (see below)
- **Letters**: every deficiency letter, emailed or saved to the outbox
- **Self-check**: the same checks in plain language for the institute, before it submits; nothing stored
- **Try to fool it**: make one edit to a good receipt and watch the checker catch it
- **Results**, **Rules**, **Audit**

### Live inbox demo

1. Start the app and open **Live inbox**. It shows the folder being watched (`inbox/` inside the project, or set `INBOX_DIR`).
2. For the sample receipts, set **Treat files as received on** to 02 May 2026 and click Save.
3. Copy any PDF from `data/test_documents/` or `data/fire_noc/` into that folder.
4. The row appears within a few seconds: document type, the application it matched, the finding and the points raised. Click the file name to open the case.

The application is taken from a sub-folder named after the application number (`inbox/1-SYN-2026-0101/receipt.pdf`), otherwise from the institute name on the document, otherwise from the default chosen on the screen.

### Emailing the letter

After **Prepare deficiency letter**, click **Approve and email letter**. The PDF goes to the institute's contact address. Configure a real mail server with environment variables:

```
SMTP_HOST=smtp.yourmail.in  SMTP_PORT=587  SMTP_USER=...  SMTP_PASSWORD=...  MAIL_FROM=ro-pune@...
```

Without `SMTP_HOST`, the email (with the PDF attached) is saved as a `.eml` file in `data/outbox/`, which opens in Outlook or Thunderbird, so nothing is sent by accident during a demo.

## Results

All data is synthetic and marked SAMPLE - TEST DATA. These numbers show the method works; they are not a claim about real AICTE files.

| Set | What it is | Defects caught | Correct docs wrongly failed | Defective docs passed |
|---|---|---|---|---|
| Main | 26 FDRs, 3 layouts, 5 scans, incl. 2 careful forgeries | 16/16 | 0/10 | 0 |
| Fire NOC | 8 NOCs | 4/4 | 0/4 | 0 |
| Affidavit | 10 affidavits, 1 scan | 5/5 | 0/5 | 0 |
| Photos | 19 room photos | 3/3 failed, 2/2 edited or forwarded sent to an officer | 0/14 | 0 |

**The ML extractor on layouts it was never trained on** (trained only on the main set):

| Unseen layout | Without ML | With ML |
|---|---|---|
| Set 2 (8 receipts) | maturity date read 0/8, depositor 0/8; 4 of 4 correct receipts sent to an officer; 25% of documents right | maturity date 7/8, depositor 7/8; 1 of 4 sent to an officer; 62.5% right |
| Set 1 (8 receipts) | 75% right | 75% right (label matching already found every field it could) |

On both unseen sets, no defective receipt was passed as clean. The remaining misses are scans whose OCR text is too poor to read; those go to an officer. Full tables: `reports/`.

**Time saved** is measured, not assumed: open **Time study**, have 3 or more people check at least 10 receipts by hand and 10 with the desk, and the Results page shows minutes per file and defects found in each mode.

Speed: about 0.3–0.4 s for a digital PDF and 3–4 s for a scan (OCR plus scan forensics) on a laptop.

## Run it

### Windows (Anaconda Prompt)

```
cd "%USERPROFILE%\Document-Checker"
pip install -r requirements.txt
python app/app.py
```

Open http://localhost:8501 and sign in as `officer` / `officer123`.

That is enough for digital PDFs. **Scanned documents need the Tesseract OCR program:**

- Easiest: `conda install -c conda-forge tesseract` (needs about 100 MB of free disk space), or
- Download the Windows installer from the UB Mannheim Tesseract page, tick **Hindi** under additional languages during setup, and add `C:\Program Files\Tesseract-OCR` to PATH.

If Tesseract is missing, the app says so in a banner and sends scans to an officer instead of guessing. Poppler is not needed.

### Linux / macOS

```bash
sudo apt install tesseract-ocr tesseract-ocr-hin     # or: brew install tesseract tesseract-lang
pip install -r requirements.txt
python tools/generate_test_docs.py                   # test receipts, labels, mock bank records
python tools/generate_noc_docs.py && python tools/generate_affidavit_docs.py && python tools/generate_photos.py
python tools/train_field_model.py                    # trains models/field_model.joblib
python tools/evaluate.py                             # writes reports/evaluation.md (add --holdout2, --no-ml)
python tools/evaluate_noc.py && python tools/evaluate_photos.py   # Fire NOC, affidavit, photo results
python app/app.py                                    # http://localhost:8501
pytest -q
```

### Docker (everything included, also how it deploys to Hugging Face Spaces)

```bash
docker build -t sd-desk . && docker run -p 7860:7860 sd-desk
```

### Before real use

Set `APP_ENV=production` together with long random `SECRET_KEY` and `API_TOKEN`. In production mode the app **refuses to start** if either is still the default. Cases, the reuse ledger and the audit trail are stored in SQLite (`data/ledger.sqlite3`) and survive a restart.

## Connecting to the AICTE portal

```bash
curl -H "Authorization: Bearer $API_TOKEN" \
     -F pdf=@receipt.pdf -F app_id=1-SYN-2026-0101 -F received=2026-05-02 \
     http://localhost:8501/api/v1/check
```

Returns the document type, overall finding, each rule's status, evidence and clause, the extracted fields with their location on the page, and the rule version. Instead of `app_id` the portal can send its own application record as JSON in `application`. `GET /api/v1/rules` returns the rules in force. `POST /api/v1/photo` (fields `photo`, `app_id`, `room`, `received`) checks one infrastructure photograph.

How each mock is replaced by a real service: [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Testing with real documents

Real receipts carry account numbers. `python tools/redact.py real.pdf safe.pdf` blacks out account, FDR, PAN, Aadhaar-like and phone numbers and e-mail addresses, and saves an image-only PDF, which the checker then reads with OCR like any scan. Check the result by eye before sharing it.

## Privacy

FDR numbers are not stored: the reuse ledger keeps only a SHA-256 of bank + FDR number. Institute self-checks are not stored at all. Demo passwords are salted hashes. The ML model and OCR run on the same machine; no document leaves it.

## Layout

```
config/document_types.yaml   how each document type is recognised
config/rules.yaml            FDR rules, thresholds, clause references, sources, rule version
config/fire_noc_rules.yaml   Fire NOC rules
config/affidavit_rules.yaml  affidavit rules
config/photo_rules.yaml      photo checks and required rooms
config/application_rules.yaml  required documents, checks between documents
config/*_labels.yaml         wording used for each field; onboarding a bank = editing this
src/doctype.py               document type check (D0)
src/extractor.py             text layer or OCR -> fields, each with page and box
src/ml_extractor.py          ML fallback for fields the label matcher misses
src/authenticity.py          A1-A4
src/rule_engine.py           FDR rules R0-R10
src/noc_rules.py             Fire NOC rules N1-N4
src/affidavit_rules.py       affidavit rules F1-F6
src/photos.py                photo checks P1-P4, photo store
src/application.py           whole-application review X1-X4, consolidated letter
src/registry.py              mock bank service, reuse ledger, audit trail, case store (SQLite)
src/inbox.py                 live folder watcher
src/mailer.py                email with the letter attached (SMTP or outbox)
src/pipeline.py              one call: type, read, extract, authenticate, check, log
app/                         Flask screens
tools/                       test-set generators, model training, evaluation
data/                        synthetic applications, banks, documents, labels
models/field_model.joblib    trained ML extractor (about 160 KB)
```

Demo order and answers to likely questions: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Team

Team GitHappens. A-1 built the first backend (extractor, rule engine, letter, tests). A-2 (Rutuja Patole) did the rules research, test set, evaluation and screens, and extended the backend.
