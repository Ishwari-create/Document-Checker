"""Scores the infrastructure photo check on data/photos. Writes reports/evaluation_photos.json.

    python tools/evaluate_photos.py
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.photos import PhotoStore, check_photo   # noqa: E402
from src.pipeline import load_applications       # noqa: E402


def main():
    apps, store, rows = load_applications(), PhotoStore(None), []
    for lab in csv.DictReader(open(ROOT / "data" / "photos" / "labels.csv")):
        data = (ROOT / "data" / "photos" / lab["file"]).read_bytes()
        out = check_photo(data, apps[lab["app_id"]], lab["room"], submitted_on=date.fromisoformat(lab["submitted_on"]),
                          store=store, photo_id=lab["photo_id"])
        store.add({"id": lab["photo_id"], "app_id": lab["app_id"], "room": lab["room"], "meta": out["meta"],
                   "results": out["results"], "overall": out["overall"], "image": data, "submitted_on": lab["submitted_on"]})
        rows.append({"photo": lab["photo_id"], "room": lab["room"], "defect": lab["defect_type"],
                     "truth": lab["expected_overall"], "system": out["overall"],
                     "failed_rules": [r["rule_id"] for r in out["results"] if r["status"] == "FAIL"],
                     "expected_rules": [x for x in lab["expected_fail_rules"].split(";") if x]})
    bad = [r for r in rows if r["truth"] == "FAIL"]
    summary = {"photos": len(rows),
               "problems_caught_by_right_rule": f"{sum(bool(set(r['expected_rules']) & set(r['failed_rules'])) for r in bad)}/{len(bad)}",
               "edited_or_forwarded_sent_to_officer": f"{sum(r['system'] == 'UNCERTAIN' for r in rows if r['truth'] == 'UNCERTAIN')}/"
                                                       f"{sum(r['truth'] == 'UNCERTAIN' for r in rows)}",
               "clean_wrongly_flagged": sum(1 for r in rows if r["truth"] == "PASS" and r["system"] != "PASS"),
               "accuracy": round(sum(r["truth"] == r["system"] for r in rows) / len(rows), 3)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "evaluation_photos.json").write_text(json.dumps({"summary": summary, "photos": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
