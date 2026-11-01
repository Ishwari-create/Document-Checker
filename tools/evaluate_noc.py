"""Scores the Fire NOC rule pack on data/fire_noc (8 synthetic NOCs). Writes reports/evaluation_noc.json."""
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.pipeline import load_applications, run_check   # noqa: E402


def main():
    apps = load_applications()
    rows = []
    for lab in csv.DictReader(open(ROOT / "data" / "fire_noc" / "labels.csv")):
        out = run_check((ROOT / "data" / "fire_noc" / lab["file"]).read_bytes(), apps[lab["app_id"]],
                        submitted_on=date.fromisoformat(lab["submitted_on"]))
        failed = [r["rule_id"] for r in out["results"] if r["status"] == "FAIL"]
        rows.append({"doc": lab["doc_id"], "defect": lab["defect_type"], "truth": lab["expected_overall"],
                     "system": out["overall"], "expected_rules": [x for x in lab["expected_fail_rules"].split(";") if x],
                     "failed_rules": failed, "doc_type": out["doc_type"]["type"]})
    bad = [r for r in rows if r["truth"] == "FAIL"]
    summary = {"documents": len(rows), "type_recognised": sum(r["doc_type"] == "fire_noc" for r in rows),
               "defects_caught_by_right_rule": f"{sum(bool(set(r['expected_rules']) & set(r['failed_rules'])) for r in bad)}/{len(bad)}",
               "clean_wrongly_failed": sum(1 for r in rows if r["truth"] == "PASS" and r["system"] == "FAIL"),
               "document_accuracy": round(sum(r["truth"] == r["system"] for r in rows) / len(rows), 3)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "evaluation_noc.json").write_text(json.dumps({"summary": summary, "documents": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
