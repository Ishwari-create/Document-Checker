# Reviewing our own project as an SIH judge would

Written 28 Oct 2026, before submission. Part 1 is what a judge would have said about the version on `main` (A-1's first backend). Part 2 is what a judge can still attack in the current version, and the answer we give.

## Part 1: problems found in the first version, and what was done

| Problem | Why a judge cares | Fixed by |
|---|---|---|
| Clause numbers ("APH 4.1.2", "2.3.1", "1.4") could not be found in any AICTE text | An AICTE judge spots invented clauses in seconds; it sinks credibility of everything else | Rules now cite the 2024-27 guidelines, a real LOI and the older APH, with a *to confirm* tag where we are not sure (docs/RULE_SOURCES.md) |
| Tenure fixed at 8 years | The 2024-27 guidelines talk about a 10-year SD period | Configurable, set to 10, flagged *to confirm* |
| Bank check passed anything containing a listed name: "Fake Bank of India Co-op" passed because it contains "Bank of India"; "Central Bank of India" was read as "Bank of India" | Co-operative bank FDRs are a real, common rejection reason | Exact match after normalising, explicit co-operative / credit society / NBFC markers, fuzzy match only for scan errors |
| No OCR, though the brief says scans and the plan had 4 scanned test files | Most FDRs reach AICTE as scans | Tesseract fallback with speckle removal, line grouping, label matching tolerant of scan noise |
| No evidence location, so the "exact place on the page" promise could not be shown | Evidence-linked findings are a stated requirement of SIH26261 | Every field keeps its page and box; the screen draws them and lights up the box for the finding under the cursor |
| No test set, no evaluation | Plan says "never cut the accuracy table" | 24-document generator, labels.csv, evaluation script, plus two held-out layouts |
| Deficiency letter printed AICTE's real address and phone as if issued | Looks like impersonation; also takes the decision away from the officer | Letter is a marked DRAFT, built only from points an officer confirmed |
| Tamper check (R7) only searched the text for words like "void" or "specimen" | Not a real alteration check | Replaced by two real ones: figures vs words (R8) and the bank's own record (R9) |
| Nothing from the brief's verification and duplicate requirements | Brief lists issuer verification, duplicate detection, audit trail, human review | R9 (mock bank service with the brief's status words), R10 (reuse ledger), audit table, officer decision with mandatory reasons |
| Same 15 L amount for every "Technical" institute | Real rule depends on programmes (summed) and slab (minority/women/NE) | Amount computed from the application's programmes and slab |

## Part 2: what a judge can still attack

**"You wrote the test documents and the extractor. 96% on your own data proves nothing."**
Agreed, and the Test results screen says so. That is why we made two more sets in layouts the code was never written for. First runs: 1/4 and 2/4 defects caught, most of the rest sent to an officer, one correct receipt wrongly failed in each set, no defective receipt passed. The failure mode is "I can't read this, officer please look", which is the safe direction. The fix for unfamiliar wording is a config change (`config/field_labels.yaml`); the long-term fix is a layout model trained on real receipts, which needs AICTE data we do not have.

**"Where is the AI? This is regex and rules."**
OCR is the machine-learning part. The decisions are rules on purpose: a rejection must be explainable by clause, reproducible, and the brief itself says results are decision support only. We would add a learned field extractor for unseen layouts, not a learned decision-maker.

**"Your bank verification is fake."**
It is a mock with the same interface and status vocabulary a real connector would have (verified, mismatch detected, source unavailable, verification pending). The rule engine does not know or care that it is mocked. Real options: bank APIs, an NeSL-style registry, or the branch's signed confirmation, which is what Regional Offices do on paper today.

**"Only one document type. The PS covers the whole application."**
Yes. The rules and field labels are data; the engine and screens are generic. The next pack would be an affidavit or a fire NOC (validity date, issuing authority, institute name and address), which reuses R5, R6 and R9-style checks unchanged.

**"Amounts and tenure might be wrong."**
They might; both are tagged *to confirm* on screen and in the rules file. One line changes each, and every past check records which rule version it used.

**"What about privacy?"**
FDR numbers are financial identifiers. The self-check screen stores nothing. Next step: mask account numbers in the audit log and on screens for roles that do not need them.

**"How long does it take?"**
About 0.05 s for a digital PDF and 1.5 s for a scan on a laptop.

## Still to do before a real pilot

1. Confirm tenure and amounts against the APH 2024-27 PDF.
2. Get 30 to 50 real, anonymised FDR scans from one Regional Office and measure on those.
3. Role-based login (officer / institute / auditor); right now the screens are open.
4. Mask FDR and account numbers outside the officer view.
5. Second rule pack (affidavit or fire NOC) to prove the "any document" claim.

## Questions to be ready for (60 seconds each)

- Rule engine: rules.yaml in, PASS / FAIL / UNCERTAIN / NA out per rule, with evidence and clause. One function per rule, about 20 lines each.
- Extraction: text layer if the PDF has one, else OCR. Fields found by label wording from field_labels.yaml; each keeps its box for the evidence view.
- Why UNCERTAIN exists: the machine must be able to say "I don't know". It is how a misread scan reaches a person instead of becoming a wrong rejection.
- Evaluation: how the 24 files were made, what "caught by the right rule" means, why held-out sets matter.
