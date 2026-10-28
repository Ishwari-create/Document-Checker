# Where each rule comes from

Checked on 28 Oct 2026. The original A-1 version cited "APH Clause 4.1.2", "4.1.3", "2.3.1" and "1.4". We could not find those clause numbers in any AICTE text, so they were replaced with the references below. A judge from AICTE will know the handbook; an invented clause number does more damage than an honest "to confirm".

## Sources used

| Code | Document | What it gave us |
|---|---|---|
| REG2024 | AICTE (Grant of Approvals for the Technical Institutions) guidelines 2024-27, text on indiankanoon.org/doc/173919027 | SD created after the Letter of Approval, proof and affidavit within 15 days (6.2(f)); penalty 10% / 50% by 31 May / 31 July, then withdrawal (6.2(f)); SD withdrawable after 10 years, interest to AICTE (6.2(g)); multiple programmes = sum of SDs (4.15(b)); exemptions (6.6(c)); premature encashment penalty (11.8) |
| LOI | A public AICTE Letter of Intent (stisttvm.edu.in) | FD in a nationalised or RBI-recognised scheduled commercial bank, in favour of Member Secretary AICTE, 8-year period, amount per APH cl. 9, Government and aided institutes exempt, scanned copy on portal plus original with affidavit to the Regional Office |
| APH_CL9 | An older Approval Process Handbook (public copy, ~2010-11 edition), cl. 9 | Amount table: Engineering 35 L (28 L for minority / women / hilly-NE), other programmes 15 L (12 L) |
| RBI2 | RBI Act 1934, Second Schedule | Which banks are scheduled banks |

## Open questions to confirm with the SPOC or the APH 2024-27 PDF

1. **Tenure: 8 or 10 years.** Older letters say 8 years. The 2024-27 guidelines say the SD can be withdrawn after 10 years. The rule uses 10 and is marked *to confirm*. Changing it is one line in `config/rules.yaml` (`minimum_tenure_years`).
2. **Amounts.** The table is from an older handbook. Replace `amount_table` in `config/rules.yaml` with the APH 2024-27 figures. Marked *to confirm*.
3. **Joint name.** Some institutes hold the FDR jointly with AICTE. The rule accepts "Member Secretary, AICTE" alone or jointly with the trust.

The 2024-27 APH PDF itself could not be downloaded from this environment (aicte.gov.in and the state mirror refused the connection), so the two values above are the honest gaps.

## Rules not from a clause

- **R8** figures vs words: standard bank-instrument scrutiny practice, used here as an alteration signal.
- **R9** issuer confirmation and **R10** reuse: required by the SIH26261 brief (verification with issuing authority; duplicate detection). The bank service is a mock reading `data/bank_confirmations.json`; in production this is a bank API, an NeSL-style registry, or a signed confirmation from the branch.
