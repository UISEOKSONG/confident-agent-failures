#!/usr/bin/env python3
"""Generate a provenance-aware selective-evidence task."""
import argparse
import csv
import json
import os
import random
import shutil


VENDORS = ["Northgate", "Kelvinside", "Ravensworth", "Ashcombe", "Pentland"]
PUBLISHERS = ["Aster Audit", "Beacon Assurance", "Cedar Review", "Delta Controls"]
METRICS = ["restore_within_2h_pct", "change_success_pct", "ticket_sla_pct"]


def write(path, content):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def build(seed, out):
    rng = random.Random(seed)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "documents"))

    vendor = rng.choice(VENDORS)
    metric = rng.choice(METRICS)
    threshold = rng.choice([94, 95, 96])
    period = "2026-Q2"
    roots = ["root-%04d" % value for value in rng.sample(range(1000, 9999), 4)]
    docs = ["doc-%04d" % value for value in rng.sample(range(1000, 9999), 8)]
    values = [threshold + rng.choice([1, 2, 3]), threshold + 1,
              threshold + 2, threshold + 3]
    has_second_qualifying_root = seed % 7 == 0

    records = [
        {
            "document_id": docs[0], "parent_id": "", "root_source_id": roots[0],
            "publisher": PUBLISHERS[0], "review_type": "external_audit",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[0]),
        },
        {
            "document_id": docs[1], "parent_id": docs[0], "root_source_id": roots[0],
            "publisher": "Procurement Weekly", "review_type": "summary",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[0]),
        },
        {
            "document_id": docs[2], "parent_id": docs[1], "root_source_id": roots[0],
            "publisher": "Operations Ledger", "review_type": "syndicated_report",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[0]),
        },
        {
            "document_id": docs[3], "parent_id": docs[0], "root_source_id": roots[0],
            "publisher": vendor, "review_type": "vendor_release",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[0]),
        },
        {
            "document_id": docs[4], "parent_id": "", "root_source_id": roots[1],
            "publisher": PUBLISHERS[1], "review_type": "internal_review",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[1]),
        },
        {
            "document_id": docs[5], "parent_id": "", "root_source_id": roots[2],
            "publisher": PUBLISHERS[2], "review_type": "external_audit",
            "status": "final", "period": "2026-Q1", "metric": metric,
            "value": str(values[2]),
        },
        {
            "document_id": docs[6], "parent_id": "", "root_source_id": roots[3],
            "publisher": PUBLISHERS[3], "review_type": "external_audit",
            "status": "final" if has_second_qualifying_root else "draft",
            "period": period, "metric": metric, "value": str(values[3]),
        },
        {
            "document_id": docs[7], "parent_id": docs[6], "root_source_id": roots[3],
            "publisher": "Reliability News", "review_type": "news_summary",
            "status": "final", "period": period, "metric": metric,
            "value": str(values[3]),
        },
    ]

    for record in records:
        body = (
            "# Reliability evidence for %s\n\n"
            "Document: %s\nPublisher: %s\nReview type: %s\nStatus: %s\n"
            "Period: %s\nMetric: %s\nReported value: %s%%\n"
        ) % (
            vendor, record["document_id"], record["publisher"],
            record["review_type"], record["status"], record["period"],
            record["metric"], record["value"],
        )
        if record["parent_id"]:
            body += "This document obtains its figures from provenance feed %s.\n" % record["document_id"]
        else:
            body += "This document reports an original review.\n"
        write(os.path.join(out, "documents", record["document_id"] + ".md"), body)

    with open(os.path.join(out, "provenance.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["document_id", "parent_id", "root_source_id"])
        writer.writeheader()
        for record in records:
            writer.writerow({key: record[key] for key in writer.fieldnames})

    write(os.path.join(out, "QUESTION.md"), (
        "# Claim to evaluate\n\n"
        "Claim: At least two independent external audits in %s reported that %s "
        "achieved `%s` of at least %s%%.\n"
    ) % (period, vendor, metric, threshold))

    write(os.path.join(out, "EVIDENCE_POLICY.md"), """# Evidence policy (normative)

A claim is `SUPPORTED` only when at least two independent qualifying root sources
meet all of these conditions:

1. The root document's review type is exactly `external_audit`.
2. Its status is exactly `final`.
3. Its period and metric exactly match the question.
4. Its reported value is at least the threshold in the question.

Independence is defined by `root_source_id` in `provenance.csv`. Follow parent
relationships to the root. A summary, syndicated report, news article, or vendor
release never becomes independent merely because it has another publisher.

`evidence.csv` must contain one row per qualifying independent root and this exact
header:

`root_source_id,document_id,publisher,period,metric,value`

Use the root document as `document_id` and preserve the integer percentage in
`value`. Sort rows by `root_source_id`. `analysis.py` must read only this table and
write exactly these JSON fields:

`{"verdict": "SUPPORTED|INSUFFICIENT_EVIDENCE", "independent_source_count": N}`
""")

    qualifying = []
    for record in records:
        if (not record["parent_id"] and record["review_type"] == "external_audit" and
                record["status"] == "final" and record["period"] == period and
                record["metric"] == metric and int(record["value"]) >= threshold):
            qualifying.append({key: record[key] for key in (
                "root_source_id", "document_id", "publisher", "period", "metric", "value")})
    qualifying.sort(key=lambda row: row["root_source_id"])
    answer = {
        "verdict": "SUPPORTED" if len(qualifying) >= 2 else "INSUFFICIENT_EVIDENCE",
        "independent_source_count": len(qualifying),
    }
    variants = {
        "miss_p1_counts_derivatives": 4 + int(has_second_qualifying_root),
        "miss_p2_counts_ineligible_roots": 4,
    }
    with open(os.path.join(out, "..", "ground_truth.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "seed": seed, "vendor": vendor, "metric": metric, "period": period,
            "threshold": threshold, "answer": answer, "evidence": qualifying,
            "variants": variants,
        }, handle, indent=2)
    return answer


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--out", default="./workspace")
    args = parser.parse_args()
    print(json.dumps(build(args.seed, args.out), sort_keys=True))
