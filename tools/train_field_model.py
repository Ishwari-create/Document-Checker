"""
Trains the ML field extractor (src/ml_extractor.py) on the labelled test receipts.

Training data: only data/test_documents (3 bank layouts). The held-out sets in
data/holdout and data/holdout2 are never used here, so their scores show how
the model copes with layouts it has not seen.

    python tools/train_field_model.py
"""
import csv
import json
import re
import sys
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline, make_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.extractor import read_document          # noqa: E402
from src.ml_extractor import FIELDS, MODEL_FILE, candidates, context_part, features, marker_tokens, parsed  # noqa: E402

norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())


def truth_for(lab, spec):
    return {"fdr_number": lab["true_fdr_no"], "amount": float(lab["true_amount"]), "issue_date": lab["true_issue"],
            "maturity_date": lab["true_maturity"], "depositor_name": lab["true_depositor"],
            "beneficiary_name": spec["beneficiary"], "amount_words": spec["words"]}


def label(c, truth):
    for f in FIELDS:
        v = parsed(f, c["value"])
        t = truth[f]
        if v is None:
            continue
        if f == "amount" and isinstance(v, float) and abs(v - t) < 1 and c["type"] == "amount":
            return f
        if f in ("issue_date", "maturity_date") and v == t and c["type"] == "date":
            return f
        if f in ("fdr_number", "depositor_name", "beneficiary_name", "amount_words") and norm(v) == norm(t) and norm(t):
            if f == "amount_words" and c["type"] != "words":
                continue
            return f
    return "none"


def main():
    base = ROOT / "data" / "test_documents"
    specs = json.loads((base / "specs.json").read_text())
    X, y = [], []
    for lab in csv.DictReader(open(ROOT / "data" / "labels.csv")):
        if lab["defect_type"] in ("pdf_edited", "scan_pasted"):
            continue
        doc = read_document((base / lab["file"]).read_bytes())
        truth = truth_for(lab, specs[lab["doc_id"]])
        for c in candidates(doc["segments"], doc["pages"]):
            X.append(features(c)); y.append(label(c, truth))
    vec = make_union(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True,
                        preprocessor=context_part),
        TfidfVectorizer(analyzer=marker_tokens),
    )
    model = make_pipeline(vec, LogisticRegression(max_iter=3000, C=4.0, class_weight="balanced"))
    model.fit(X, y)
    MODEL_FILE.parent.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_FILE)
    counts = {k: y.count(k) for k in sorted(set(y))}
    print(f"trained on {len(X)} candidates from the test receipts: {counts}")


if __name__ == "__main__":
    main()
