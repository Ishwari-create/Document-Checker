"""Scores the Fire NOC and affidavit rule packs on their synthetic sets.
Writes reports/evaluation_noc.json and reports/evaluation_affidavit.json.

    python tools/evaluate_noc.py
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.pipeline import load_applications, run_check   # noqa: E402


SETS = {"noc": ("fire_noc", "fire_noc"), "affidavit": ("affidavits", "affidavit")}


def main():
    for key, (folder, doc_type) in SETS.items():
        if (ROOT / "data" / folder / "labels.csv").exists():
            evaluate(key, folder, doc_type)


def evaluate(key, folder, doc_type):
    apps = load_applications()
    rows = []
    for lab in csv.DictReader(open(ROOT / "data" / folder / "labels.csv")):
        out = run_check((ROOT / "data" / folder / lab["file"]).read_bytes(), apps[lab["app_id"]],
                        submitted_on=date.fromisoformat(lab["submitted_on"]))
        failed = [r["rule_id"] for r in out["results"] if r["status"] == "FAIL"]
        rows.append({"doc": lab["doc_id"], "defect": lab["defect_type"], "truth": lab["expected_overall"],
                     "system": out["overall"], "expected_rules": [x for x in lab["expected_fail_rules"].split(";") if x],
                     "failed_rules": failed, "doc_type": out["doc_type"]["type"]})
    bad = [r for r in rows if r["truth"] == "FAIL"]
    summary = {"documents": len(rows), "type_recognised": sum(r["doc_type"] == doc_type for r in rows),
               "defective_passed": sum(1 for r in bad if r["system"] == "PASS"),
               "defects_caught_by_right_rule": f"{sum(bool(set(r['expected_rules']) & set(r['failed_rules'])) for r in bad)}/{len(bad)}",
               "clean_wrongly_failed": sum(1 for r in rows if r["truth"] == "PASS" and r["system"] == "FAIL"),
               "document_accuracy": round(sum(r["truth"] == r["system"] for r in rows) / len(rows), 3)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / f"evaluation_{key}.json").write_text(json.dumps({"summary": summary, "documents": rows}, indent=2))
    print(key, json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
