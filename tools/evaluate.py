"""
Scores the checker against data/labels.csv and writes reports/evaluation.md
and reports/evaluation.json.

    python tools/evaluate.py

Counting rules
- A rule "flags" a document when it returns FAIL.
- UNCERTAIN is not counted as a catch. It is reported separately as
  "sent to an officer", because that is what happens to it in practice.
- Document level: truth is PASS (clean) or FAIL (defect planted). The system
  answer is PASS / FAIL / UNCERTAIN.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline import load_applications, run_check          # noqa: E402
from src.registry import IssuerConnector, Ledger                # noqa: E402

RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]


def main():
    apps = load_applications()
    issuer = IssuerConnector()
    ledger = Ledger(db_path=None)              # fresh, in memory
    labels = list(csv.DictReader(open(ROOT / "data" / "labels.csv")))

    rows, tp, fp, fn, review = [], defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    field_hits, field_total = defaultdict(int), defaultdict(int)
    t_all = time.time()
    for lab in labels:
        t0 = time.time()
        pdf = (ROOT / "data" / "test_documents" / lab["file"]).read_bytes()
        out = run_check(pdf, apps[lab["app_id"]], submitted_on=date.fromisoformat(lab["submitted_on"]),
                        issuer=issuer, ledger=ledger)
        secs = time.time() - t0
        status = {r["rule_id"]: r["status"] for r in out["results"]}
        truth = set(filter(None, lab["expected_fail_rules"].split(";")))
        for rid in RULES:
            flagged = status.get(rid) == "FAIL"
            if flagged and rid in truth: tp[rid] += 1
            elif flagged: fp[rid] += 1
            elif rid in truth: fn[rid] += 1
            if status.get(rid) == "UNCERTAIN": review[rid] += 1

        f = out["extraction"]["fields"]
        for name, key, conv in [("FDR number", "true_fdr_no", str), ("Amount", "true_amount", float),
                                ("Deposit date", "true_issue", str), ("Maturity date", "true_maturity", str),
                                ("Depositor", "true_depositor", str)]:
            got = {"FDR number": f["fdr_number"], "Amount": f["amount"], "Deposit date": f["issue_date"],
                   "Maturity date": f["maturity_date"], "Depositor": f["depositor_name"]}[name]
            field_total[name] += 1
            field_hits[name] += int(got is not None and conv(got) == conv(lab[key]))

        rows.append({"doc": lab["doc_id"], "scanned": lab["scanned"] == "1", "layout": lab["layout"],
                     "defect": lab["defect_type"], "truth": lab["expected_overall"], "system": out["overall"],
                     "expected_rules": sorted(truth),
                     "failed_rules": sorted([r for r, s in status.items() if s == "FAIL"], key=lambda x: int(x[1:])),
                     "review_rules": sorted([r for r, s in status.items() if s == "UNCERTAIN"], key=lambda x: int(x[1:])),
                     "seconds": round(secs, 2), "note": lab["note"]})

    # --- summary numbers -------------------------------------------------------
    clean = [r for r in rows if r["truth"] == "PASS"]
    bad = [r for r in rows if r["truth"] == "FAIL"]
    caught = [r for r in bad if set(r["expected_rules"]) & set(r["failed_rules"])]
    correct_doc = sum(1 for r in rows if r["system"] == r["truth"])
    false_alarm = [r for r in clean if r["system"] == "FAIL"]
    clean_to_review = [r for r in clean if r["system"] == "UNCERTAIN"]
    missed = [r for r in bad if r["system"] == "PASS"]

    per_rule = []
    for rid in RULES:
        p_den, r_den = tp[rid] + fp[rid], tp[rid] + fn[rid]
        per_rule.append({"rule": rid, "planted": r_den, "caught": tp[rid], "false_flags": fp[rid],
                         "sent_to_review": review[rid],
                         "precision": round(tp[rid] / p_den, 2) if p_den else None,
                         "recall": round(tp[rid] / r_den, 2) if r_den else None})

    summary = {
        "documents": len(rows), "clean": len(clean), "defective": len(bad),
        "scanned": sum(r["scanned"] for r in rows),
        "document_accuracy": round(correct_doc / len(rows), 3),
        "defects_caught_by_right_rule": f"{len(caught)}/{len(bad)}",
        "defective_passed_as_clean": len(missed),
        "clean_wrongly_failed": len(false_alarm),
        "clean_sent_to_review": len(clean_to_review),
        "false_alarm_rate_on_clean": round(len(false_alarm) / len(clean), 3),
        "field_accuracy": {k: f"{field_hits[k]}/{field_total[k]}" for k in field_total},
        "avg_seconds_text_pdf": round(sum(r["seconds"] for r in rows if not r["scanned"]) /
                                      max(1, sum(not r["scanned"] for r in rows)), 2),
        "avg_seconds_scan": round(sum(r["seconds"] for r in rows if r["scanned"]) /
                                  max(1, sum(r["scanned"] for r in rows)), 2),
        "total_seconds": round(time.time() - t_all, 1),
    }

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "evaluation.json").write_text(json.dumps({"summary": summary, "per_rule": per_rule, "documents": rows},
                                                        indent=2))
    write_markdown(out_dir / "evaluation.md", summary, per_rule, rows)
    print(json.dumps(summary, indent=2))
    for r in rows:
        mark = "ok " if r["system"] == r["truth"] else "XX "
        print(mark, r["doc"], "scan" if r["scanned"] else "    ", r["defect"].ljust(18), "truth", r["truth"],
              "sys", r["system"].ljust(9), "fail", r["failed_rules"], "review", r["review_rules"])


def write_markdown(path, s, per_rule, rows):
    L = ["# Evaluation on the synthetic test set", "",
         f"{s['documents']} documents ({s['clean']} clean, {s['defective']} with one planted defect, "
         f"{s['scanned']} scanned). Generated by `tools/generate_test_docs.py`; truth in `data/labels.csv`.",
         "", "These are synthetic receipts from three invented bank layouts. The numbers show that the method "
         "works end to end; they do not show performance on real AICTE files.", "",
         "## Headline", "",
         "| Measure | Result |", "|---|---|",
         f"| Document-level accuracy (PASS/FAIL/REVIEW matches truth) | {s['document_accuracy']:.0%} |",
         f"| Planted defects caught by the right rule | {s['defects_caught_by_right_rule']} |",
         f"| Defective documents passed as clean | {s['defective_passed_as_clean']} |",
         f"| Clean documents wrongly failed (false alarms) | {s['clean_wrongly_failed']} of {s['clean']} |",
         f"| Clean documents sent to an officer for review | {s['clean_sent_to_review']} of {s['clean']} |",
         f"| Time per document: digital PDF / scan | {s['avg_seconds_text_pdf']} s / {s['avg_seconds_scan']} s |",
         "", "## Field extraction", "", "| Field | Exact match |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in s["field_accuracy"].items()]
    L += ["", "## Per rule", "", "A rule 'catches' a document when it returns FAIL. 'Sent to review' counts "
          "UNCERTAIN results, which go to an officer instead of being decided by the machine.", "",
          "| Rule | Planted | Caught | False flags | Sent to review | Precision | Recall |", "|---|---|---|---|---|---|---|"]
    for r in per_rule:
        fmt = lambda x: "-" if x is None else f"{x:.2f}"
        L.append(f"| {r['rule']} | {r['planted']} | {r['caught']} | {r['false_flags']} | {r['sent_to_review']} | "
                 f"{fmt(r['precision'])} | {fmt(r['recall'])} |")
    L += ["", "## Every document", "", "| Doc | Scan | Planted defect | Truth | System | Failed rules | Review |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['doc']} | {'yes' if r['scanned'] else ''} | {r['defect']} | {r['truth']} | {r['system']} | "
                 f"{', '.join(r['failed_rules'])} | {', '.join(r['review_rules'])} |")
    wrong = [r for r in rows if r["system"] != r["truth"]]
    L += ["", "## Where it went wrong", ""]
    if not wrong:
        L.append("No document-level errors on this set.")
    for r in wrong:
        L.append(f"- **{r['doc']}** ({'scan, ' if r['scanned'] else ''}{r['defect']}): truth {r['truth']}, "
                 f"system {r['system']}; review flags {', '.join(r['review_rules']) or 'none'}. _Cause: see note below._")
    Path(path).write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
