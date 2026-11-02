# Five-minute demo and judges' questions

Sign in as `officer` / `officer123`. Have `data/test_documents/FDR-T25.pdf` and the
`inbox/` folder open in a file window before you start.

| Time | Screen | Say | Do |
|---|---|---|---|
| 0:00 | Dashboard | "This is what a Regional Office officer sees in the morning: what came in, what is wrong, and what is about to expire." | Point at the alerts (Fire NOC expiring, FDR maturing) and the most common deficiencies. |
| 0:40 | Dashboard → an application | "The officer decides on an application, not on a file. Here are all its documents together." | Open 1-SYN-2026-0101. Show the checklist and the four checks between documents. |
| 1:30 | Application → photos | "Photos are checked for date, GPS, editing, and whether another college already submitted the same picture." | Open 1-SYN-2026-0111: its library photo is Sahyadri's, resized. |
| 2:10 | Live inbox | "Documents arrive from the portal; here a folder stands in for it." | Drag FDR-T25.pdf into `inbox/`. The row appears in seconds. |
| 2:40 | FDR-T25 | "Figures and words agree, so a normal check passes it. The file says otherwise." | Show A1 edit history, A2 font, A3 QR. Click a finding to light up the box on the receipt. |
| 3:30 | Decide → letter | "The officer agrees or overrules with a reason, and the letter goes out by e-mail." | Agree, prepare letter, approve and email. |
| 4:10 | Results | "Every number is on synthetic data, and we show where it is weak." | Show held-out layouts and the time study. |
| 4:40 | Close | "Rules are config files; adding a document type is a YAML file, not code." | Open the Rules page. |

Keep the recorded video ready in case the live demo fails.

## Questions and short answers

- **Where is the AI?** OCR, a trained field extractor for layouts it has not seen, photo
  matching by perceptual hash, and forgery checks on the file. The final call is rules on
  purpose: a deficiency letter has to cite a clause.
- **What if it is wrong?** It never rejects. A low-confidence read or a scan sends the
  point to an officer, and every overrule is logged with a reason.
- **Real data?** Synthetic only, because real FDRs carry account numbers. `tools/redact.py`
  makes a real receipt safe to test with; we are collecting samples. *(Update this line
  with how many real receipts you tested.)*
- **Unseen layouts?** On a layout never used for tuning, ML lifted the right-document rate
  from 25% to 62.5%, and no defective receipt was passed. The rest go to an officer.
- **Bank verification?** QR check works today; the bank connector is an interface (see
  `docs/INTEGRATION.md`).
- **Scale?** About 0.3 s per digital PDF and 3–4 s per scan on a laptop; one server per
  Regional Office handles a day's files in minutes.
- **Time saved?** Measured with the built-in time study: *(fill in from the Results page:
  N people, M files, X% faster, Y vs Z defects found)*.
- **Privacy?** Runs on the RO's own machine; FDR numbers are stored only as a hash;
  institute self-checks are not stored.
