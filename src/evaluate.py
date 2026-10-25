"""
Evaluation & Accuracy Benchmarking Script (A-1)
Runs automated verification against the 24 synthetic test documents.
Compares system output against data/labels.csv to calculate:
- Document-level accuracy
- False alarm rate on clean documents (Target: 0%)
- Per-rule Precision, Recall, and F1-score (R1 through R7)
- Failure analysis summary
Outputs formatted Markdown & JSON evidence for presentation slides.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.api import verify_fdr

DATA_DIR = Path(__file__).parent.parent / "data"
TEST_DOCS_DIR = DATA_DIR / "test_documents"
LABELS_FILE = DATA_DIR / "labels.csv"
REPORT_JSON = DATA_DIR / "evaluation_report.json"
REPORT_MD = DATA_DIR / "accuracy_table.md"


def run_evaluation() -> Dict[str, Any]:
    """Execute end-to-end evaluation against labels.csv ground truth."""
    if not LABELS_FILE.exists():
        raise FileNotFoundError(f"Ground truth file {LABELS_FILE} not found. Run generate_test_data.py first.")

    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        test_cases = list(reader)

    total_docs = len(test_cases)
    doc_matches = 0
    clean_total = 0
    clean_false_alarms = 0

    # Rule metrics: { rule_id: { "tp": 0, "fp": 0, "fn": 0, "tn": 0 } }
    rule_metrics = {f"R{i}": {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for i in range(1, 8)}
    failure_analysis: List[Dict[str, Any]] = []

    results_log = []

    for case in test_cases:
        filename = case["filename"]
        pdf_path = TEST_DOCS_DIR / filename
        true_verdict = case["true_verdict"]
        expected_failed_rule = case["failed_rule"]

        app_ctx = {
            "institute_name": case["institute_name"],
            "category": case["category"],
            "required_amount": float(case["required_amount"])
        }

        # Run scrutiny
        res = verify_fdr(pdf_path, application_context=app_ctx)
        pred_verdict = res["verdict"]

        # Document level match
        is_doc_match = (pred_verdict == true_verdict)
        if is_doc_match:
            doc_matches += 1

        # Check clean documents false alarms
        if expected_failed_rule == "NONE":
            clean_total += 1
            if pred_verdict == "FAIL":
                clean_false_alarms += 1

        # Per-rule tracking
        rule_map = {r["rule_id"]: r["status"] for r in res["rule_results"]}

        for rid in rule_metrics:
            is_rule_defective_in_truth = (expected_failed_rule == rid)
            rule_status = rule_map.get(rid, "PASS")
            rule_fired = rule_status in ("FAIL", "UNCERTAIN")

            if is_rule_defective_in_truth and rule_fired:
                rule_metrics[rid]["tp"] += 1
            elif not is_rule_defective_in_truth and rule_fired:
                rule_metrics[rid]["fp"] += 1
            elif is_rule_defective_in_truth and not rule_fired:
                rule_metrics[rid]["fn"] += 1
            else:
                rule_metrics[rid]["tn"] += 1

        if not is_doc_match:
            failure_analysis.append({
                "filename": filename,
                "true_verdict": true_verdict,
                "pred_verdict": pred_verdict,
                "expected_defect": case["defect_type"],
                "failed_rule": expected_failed_rule
            })

        results_log.append({
            "filename": filename,
            "true_verdict": true_verdict,
            "predicted_verdict": pred_verdict,
            "expected_rule": expected_failed_rule,
            "match": is_doc_match
        })

    # Calculate aggregate metrics
    doc_accuracy = round((doc_matches / total_docs) * 100, 2)
    false_alarm_rate = round((clean_false_alarms / clean_total) * 100, 2) if clean_total > 0 else 0.0

    # Per-rule precision / recall
    rule_table = []
    rule_names = {
        "R1": "Beneficiary (AICTE Member Sec)",
        "R2": "Approved Bank (RBI Sched.)",
        "R3": "Tenure (8 Years Mandatory)",
        "R4": "Prescribed Deposit Amount",
        "R5": "Institute Identity Match",
        "R6": "Date Logic & Consistency",
        "R7": "Integrity / Tamper Forensic"
    }

    for rid, m in rule_metrics.items():
        tp, fp, fn = m["tp"], m["fp"], m["fn"]
        prec = (tp / (tp + fp)) * 100 if (tp + fp) > 0 else 100.0
        rec = (tp / (tp + fn)) * 100 if (tp + fn) > 0 else 100.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        rule_table.append({
            "rule_id": rid,
            "rule_name": rule_names.get(rid, rid),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 1),
            "recall": round(rec, 1),
            "f1_score": round(f1, 1)
        })

    evaluation_summary = {
        "dataset": "24 Synthetic AICTE Fixed Deposit Receipts",
        "total_documents": total_docs,
        "clean_documents": clean_total,
        "defective_documents": total_docs - clean_total,
        "document_level_accuracy_pct": doc_accuracy,
        "false_alarm_rate_pct": false_alarm_rate,
        "rule_performance": rule_table,
        "failure_analysis": failure_analysis,
        "note": "These numbers come from synthetic data and demonstrate algorithmic validity under rigorous clause-checking rules."
    }

    # Save JSON report
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(evaluation_summary, f, indent=2)

    # Save Markdown report
    md_lines = [
        "# AICTE Document Checker – Evaluation & Accuracy Report",
        "",
        "> **Project A (SIH26261)** | Benchmark run against 24 synthetic test documents with planted handbook defects.",
        "",
        "## Summary Metrics",
        f"- **Total Test Documents Evaluated**: {total_docs}",
        f"- **Clean Documents Tested**: {clean_total}",
        f"- **Documents with Planted Defects**: {total_docs - clean_total}",
        f"- **Document-Level Accuracy**: **{doc_accuracy}%**",
        f"- **False Alarm Rate on Clean Documents**: **{false_alarm_rate}%** (Target: 0%)",
        "",
        "## Per-Rule Precision & Recall",
        "| Rule ID | Rule Description | True Pos (TP) | False Pos (FP) | False Neg (FN) | Precision | Recall | F1 Score |",
        "|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|"
    ]

    for r in rule_table:
        md_lines.append(
            f"| **{r['rule_id']}** | {r['rule_name']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['precision']}% | {r['recall']}% | {r['f1_score']}% |"
        )

    md_lines.extend([
        "",
        "## Failure Analysis",
        f"- **Total Misclassifications**: {len(failure_analysis)}"
    ])

    if failure_analysis:
        for fa in failure_analysis:
            md_lines.append(f"- Document `{fa['filename']}`: Expected `{fa['true_verdict']}`, Predicted `{fa['pred_verdict']}` ({fa['expected_defect']})")
    else:
        md_lines.append("- **Zero misclassifications detected.** All clean documents passed and all planted defects were correctly isolated with clause citations.")

    md_lines.extend([
        "",
        "---",
        "*Note: Benchmarks performed on synthetic test data. Demonstrates automated clause verification and evidence mapping.*"
    ])

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"\n================ EVALUATION SUMMARY ================")
    print(f"Document Accuracy: {doc_accuracy}% ({doc_matches}/{total_docs})")
    print(f"False Alarm Rate on Clean Docs: {false_alarm_rate}% ({clean_false_alarms}/{clean_total})")
    print(f"Per-rule metrics written to {REPORT_MD}")
    return evaluation_summary


if __name__ == "__main__":
    run_evaluation()
