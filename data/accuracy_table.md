# AICTE Document Checker – Evaluation & Accuracy Report

> **Project A (SIH26261)** | Benchmark run against 24 synthetic test documents with planted handbook defects.

## Summary Metrics
- **Total Test Documents Evaluated**: 24
- **Clean Documents Tested**: 10
- **Documents with Planted Defects**: 14
- **Document-Level Accuracy**: **100.0%**
- **False Alarm Rate on Clean Documents**: **0.0%** (Target: 0%)

## Per-Rule Precision & Recall
| Rule ID | Rule Description | True Pos (TP) | False Pos (FP) | False Neg (FN) | Precision | Recall | F1 Score |
|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **R1** | Beneficiary (AICTE Member Sec) | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R2** | Approved Bank (RBI Sched.) | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R3** | Tenure (8 Years Mandatory) | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R4** | Prescribed Deposit Amount | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R5** | Institute Identity Match | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R6** | Date Logic & Consistency | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **R7** | Integrity / Tamper Forensic | 2 | 0 | 0 | 100.0% | 100.0% | 100.0% |

## Failure Analysis
- **Total Misclassifications**: 0
- **Zero misclassifications detected.** All clean documents passed and all planted defects were correctly isolated with clause citations.

---
*Note: Benchmarks performed on synthetic test data. Demonstrates automated clause verification and evidence mapping.*